"""API tests for dashboard index summary + storage endpoints.

`GET /api/index/status` is what the Dashboard's System Status strip reads. Its status line
used to come only from this process's in-memory `_STATUS`, so a corpus indexed by an earlier
process reported "Ready to index…" with a null progress while the same page's Recent Index
Runs table showed it complete with 5,806 chunks -- an indexed corpus and a never-indexed one
were indistinguishable in the ops strip.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.db.postgres import PostgresClient
from server.models.index import IndexRunSummary

pytestmark = pytest.mark.requires_postgres


@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    old_runs_dir = index_api._INDEX_RUNS_DIR
    old_status = dict(index_api._STATUS)
    index_api._INDEX_RUNS_DIR = tmp_path
    index_api._STATUS.clear()
    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir
        index_api._STATUS.clear()
        index_api._STATUS.update(old_status)


async def _register(corpus_id: str) -> None:
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
    finally:
        await pg.disconnect()


async def _seed_chunk(corpus_id: str) -> None:
    """One real chunk row, so the corpus has an index the status line can be about."""
    from server.models.index import Chunk

    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_chunks(
            corpus_id,
            [
                Chunk(
                    chunk_id=f"{corpus_id}-c1",
                    content="aurora tidal observatory commissioning note",
                    file_path="notes/commissioning.md",
                    start_line=1,
                    end_line=1,
                    language="markdown",
                    token_count=7,
                )
            ],
        )
    finally:
        await pg.disconnect()


async def _drop(corpus_id: str) -> None:
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.delete_corpus_with_data(corpus_id)
    finally:
        await pg.disconnect()


def _summary(corpus_id: str, run_id: str, **overrides) -> IndexRunSummary:
    started = datetime.now(UTC) - timedelta(minutes=5)
    fields = {
        "run_id": run_id,
        "repo_id": corpus_id,
        "status": "complete",
        "started_at": started,
        "completed_at": started + timedelta(minutes=4),
        "progress": 1.0,
        "error": None,
        "total_files": 765,
        "total_chunks": 5806,
        "total_tokens": 3531477,
    }
    fields.update(overrides)
    return IndexRunSummary(**fields)


@pytest.mark.asyncio
async def test_the_status_line_reports_the_completed_run_not_ready_to_index(
    client: AsyncClient,
) -> None:
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        # A completed run AND chunks in the store: the ragweld_code shape the row describes.
        # Without the chunks this is a deleted index, which is a different line (see below).
        await _seed_chunk(corpus_id)
        index_api._persist_run_summary(_summary(corpus_id, "run_complete"))

        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        payload = response.json()

        assert payload["running"] is False
        line = " ".join(payload["lines"]).lower()
        assert "ready to index" not in line
        assert "complete" in line
        # A completed run is finished, so the ops strip must not read a null progress.
        assert payload["progress"] == pytest.approx(1.0)
    finally:
        await _drop(corpus_id)


@pytest.mark.asyncio
async def test_a_corpus_that_was_never_indexed_still_says_ready_to_index(
    client: AsyncClient,
) -> None:
    """The other half of the contract: the two states have to stay distinguishable."""
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        payload = response.json()

        assert payload["running"] is False
        assert "ready to index" in " ".join(payload["lines"]).lower()
        assert payload["progress"] is None
    finally:
        await _drop(corpus_id)


@pytest.mark.asyncio
async def test_a_failed_last_run_is_reported_as_failed(client: AsyncClient) -> None:
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        index_api._persist_run_summary(
            _summary(
                corpus_id,
                "run_failed",
                status="error",
                error="neo4j schema initialization failed",
                progress=0.42,
            )
        )

        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        line = " ".join(response.json()["lines"])

        assert "neo4j schema initialization failed" in line
        assert "ready to index" not in line.lower()
    finally:
        await _drop(corpus_id)


@pytest.mark.asyncio
async def test_an_interrupted_run_is_not_reported_as_a_completed_index(
    client: AsyncClient,
) -> None:
    """A persisted `indexing` summary with no live fence is a run that never committed."""
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        index_api._persist_run_summary(
            _summary(corpus_id, "run_interrupted", status="indexing", completed_at=None, progress=0.3)
        )

        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        payload = response.json()
        line = " ".join(payload["lines"]).lower()

        assert payload["running"] is False
        assert "interrupted" in line
        assert "complete" not in line
    finally:
        await _drop(corpus_id)


@pytest.mark.asyncio
async def test_a_completed_run_whose_chunks_are_gone_is_not_reported_as_complete(
    client: AsyncClient,
) -> None:
    """The store's word beats the run record's.

    `_load_latest_run_summary` keeps answering with the last completed run after the index it
    describes has been deleted, so the ops strip claimed "Indexing complete — 0 chunks" for a
    corpus with nothing in it — the same dishonesty M-44 removed, pointing the other way.
    """
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        # A completed run on a corpus that has no chunks: exactly the post-delete shape.
        index_api._persist_run_summary(_summary(corpus_id, "run_orphaned"))

        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        payload = response.json()
        line = " ".join(payload["lines"])

        assert "complete" not in line.lower(), line
        assert "0 chunks" not in line
        assert "ready to index" in line.lower()
    finally:
        await _drop(corpus_id)


@pytest.mark.asyncio
async def test_deleting_the_index_discards_the_persisted_runs(client: AsyncClient) -> None:
    """DELETE must not leave run summaries describing an index that no longer exists."""
    corpus_id = f"dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    try:
        index_api._persist_run_summary(_summary(corpus_id, "run_before_delete"))
        index_api._append_run_event(corpus_id, "run_before_delete", {"type": "log", "message": "hi"})
        # Summaries and events are written by a background writer thread; the endpoint flushes
        # it, so read through the API before asserting anything about the directory.
        latest = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert latest.status_code == 200
        runs_dir = index_api._repo_runs_dir(corpus_id)
        assert runs_dir.exists(), "precondition: the run directory is on disk"

        deleted = await client.delete(f"/api/index/{corpus_id}")
        assert deleted.status_code == 200, deleted.text

        assert not runs_dir.exists(), "the run directory outlived the index it describes"
        gone = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert gone.status_code == 404

        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200
        assert "ready to index" in " ".join(response.json()["lines"]).lower()
    finally:
        await _drop(corpus_id)
