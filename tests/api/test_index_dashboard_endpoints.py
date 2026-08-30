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
