"""API tests for dashboard index summary + storage endpoints.

`GET /api/index/status` is what the Dashboard's System Status strip reads. Its status line
used to come only from this process's in-memory `_STATUS`, so a corpus indexed by an earlier
process reported "Ready to index…" with a null progress while the same page's Recent Index
Runs table showed it complete with 5,806 chunks -- an indexed corpus and a never-indexed one
were indistinguishable in the ops strip.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.db.postgres import PostgresClient
from server.indexing.accounting import IndexAccountingOwner
from server.indexing.generations import GENERATION_META_KEY, GenerationManifest
from server.indexing.run_records import write_run_summary
from server.models.index import IndexRunSummary
from server.models.run_accounting import IndexCostEstimateSnapshot

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
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
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
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
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
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
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
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
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
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
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


def _estimate_snapshot(amount: float) -> IndexCostEstimateSnapshot:
    return IndexCostEstimateSnapshot(
        captured_at=datetime.now(UTC), embedding_usd=amount,
        semantic_kg_usd=amount * 2, figure_description_usd=amount * 3,
        total_usd=amount * 6, estimated_chunks=3, estimated_tokens=17,
        detail="Synthetic immutable pre-run quote",
    )


@pytest.mark.asyncio
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.parametrize("state", ["complete", "error", "cancelled", "held"])
async def test_deleting_the_index_preserves_accounting_and_late_worker_history(
    client: AsyncClient, state: str,
) -> None:
    """Deleting stores never erases a paid attempt's census, quote or event history."""
    corpus_id = f"pytest_dash_status_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    run_id = uuid.uuid4().hex
    path = index_api._run_summary_path(corpus_id, run_id)
    status = "cancelled" if state == "held" else state
    summary = _summary(corpus_id, run_id, status=status)
    owner = IndexAccountingOwner(
        path, summary, config_json='{"synthetic": true}', models={"semantic_kg": "openai.gpt-5.6-sol"},
        coverage_complete=True, coverage_notes=[], estimate=_estimate_snapshot(0.25),
    )
    release = threading.Event()
    worker_started = threading.Event()
    executor = ThreadPoolExecutor(max_workers=1)
    worker = None
    try:
        owner.progress(files=1, chunks=3, tokens=17)
        if state == "held":
            lease = owner.scopes["semantic_kg"].producer_started()

            def retained_worker() -> None:
                worker_started.set()
                try:
                    if not release.wait(60):
                        raise TimeoutError("test did not release its retained producer")
                finally:
                    lease.close()

            worker = executor.submit(retained_worker)
            assert await asyncio.to_thread(worker_started.wait, 5)
        owner.finish(interrupted=status != "complete")
        index_api._append_run_event(corpus_id, run_id, {"type": "log", "message": "retained attempt"})
        await index_api._flush_run_events()
        before = IndexRunSummary.model_validate_json(path.read_text())
        assert before.accounting is not None
        before_census = before.accounting.census["semantic_kg"]
        assert before_census.active_producers == int(state == "held")
        assert before_census.state == ("open" if state == "held" else "closed")

        deleted = await client.delete(f"/api/index/{corpus_id}")
        assert deleted.status_code == 200, deleted.text
        exact = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
        assert exact.status_code == 200, exact.text
        saved = IndexRunSummary.model_validate(exact.json())
        assert saved == before
        history = await client.get(f"/api/index/{corpus_id}/runs/{run_id}/events")
        assert history.status_code == 200 and history.json()["total"] == 1
        assert history.json()["events"][0]["message"] == "retained attempt"

        if worker is not None:
            release.set()
            await asyncio.wrap_future(worker)
            closed = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
            assert closed.status_code == 200, closed.text
            final = IndexRunSummary.model_validate(closed.json())
            assert final.accounting is not None
            census = final.accounting.census["semantic_kg"]
            assert census.state == "closed" and census.active_producers == census.inflight == 0
            assert census.revision > before_census.revision
            assert final.accounting.estimate == before.accounting.estimate
            assert final.accounting.processed_tokens == 17
            assert final.status == status
        response = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert response.status_code == 200, response.text
        costs = response.json()["metadata"]["costs"]
        assert costs["accounting"] is None and costs["total_cost"] is None
    finally:
        release.set()
        if worker is not None:
            await asyncio.wrap_future(worker)
        executor.shutdown(wait=True)
        owner.finish(interrupted=True)
        await _drop(corpus_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("newer_kind,newer_status", [
    ("index", "error"), ("index", "indexing"), ("schema_proposal", "complete"),
])
async def test_dashboard_costs_name_the_manifest_run_and_never_reprice_history(
    client: AsyncClient, newer_kind: str, newer_status: str,
) -> None:
    corpus_id = f"pytest_dash_cost_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await _seed_chunk(corpus_id)
        active_id = uuid.uuid4().hex
        active = _summary(corpus_id, active_id)
        owner = IndexAccountingOwner(
            index_api._run_summary_path(corpus_id, active_id), active,
            config_json='{"price_snapshot": "original"}', models={}, coverage_complete=True,
            coverage_notes=[], estimate=_estimate_snapshot(1.25),
        )
        owner.finish()
        expected = IndexRunSummary.model_validate_json(owner.path.read_text()).accounting
        assert expected is not None
        manifest = GenerationManifest(run_id=active_id, promoted_at=datetime.now(UTC))
        await pg.update_corpus_meta(corpus_id, {GENERATION_META_KEY: manifest.model_dump(mode="json")})
        assert (await pg.get_corpus(corpus_id))["meta"][GENERATION_META_KEY]["run_id"] == active_id
        newer_id = uuid.uuid4().hex
        newer = _summary(corpus_id, newer_id, run_kind=newer_kind, status=newer_status,
                         started_at=datetime.now(UTC), completed_at=None)
        competing = IndexAccountingOwner(
            index_api._run_summary_path(corpus_id, newer_id), newer,
            config_json='{"price_snapshot": "new"}', models={}, coverage_complete=True,
            coverage_notes=[], estimate=_estimate_snapshot(99),
        )
        competing.finish()
        # A later status write must retain the active run's immutable cost snapshot.
        write_run_summary(owner.path, active)
        status = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert status.status_code == 200, status.text
        costs = status.json()["metadata"]["costs"]
        assert costs["accounting"] == expected.model_dump(mode="json")
        assert costs["embedding_cost"] == 1.25
        assert costs["semantic_kg_cost"] == 2.5
        assert costs["figure_description_cost"] == 3.75
        assert costs["total_cost"] == 7.5

        # History and even old chunks do not imply a currently promoted generation.
        await pg.update_corpus_meta(corpus_id, {GENERATION_META_KEY: None})
        without_manifest = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert without_manifest.status_code == 200, without_manifest.text
        costs = without_manifest.json()["metadata"]["costs"]
        assert costs["accounting"] is None
        assert all(costs[key] is None for key in (
            "embedding_cost", "semantic_kg_cost", "figure_description_cost", "total_cost",
        ))
        for run_id in (active_id, newer_id):
            historical = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
            assert historical.status_code == 200 and historical.json()["accounting"] is not None
    finally:
        await pg.disconnect()
        await _drop(corpus_id)


async def test_dashboard_status_and_stats_are_404_for_an_unregistered_corpus(
    client: AsyncClient,
) -> None:
    """A poll from a tab open on a since-deleted corpus is a typed 404, not a 500.

    The corpus is never registered, so `load_scoped_config` raises CorpusNotFoundError
    inside both dashboard endpoints; that must surface as 404, not an unhandled 500.
    """
    missing = f"pytest_dash_missing_{uuid.uuid4().hex[:10]}"

    status = await client.get("/api/index/status", params={"corpus_id": missing})
    assert status.status_code == 404, status.text

    stats = await client.get("/api/index/stats", params={"corpus_id": missing})
    assert stats.status_code == 404, stats.text


@pytest.mark.asyncio
async def test_the_neo4j_store_is_reported_as_unmeasured_not_zero(client: AsyncClient) -> None:
    """Neo4j 5 Community has no store-size source, so the dashboard says so instead of "0 B".

    `dbms.queryJmx` is gone in Neo4j 5, APOC core has no `apoc.monitor.store`, `SHOW DATABASES`
    carries no size column, and the data volume is not readable from the API process. Both
    dashboard endpoints report the store as unmeasured (null bytes plus the reason) and leave it
    out of the storage total rather than adding a measured-looking zero to it.
    """
    corpus_id = f"pytest_dash_neo4j_{uuid.uuid4().hex[:10]}"
    await _register(corpus_id)
    await _seed_chunk(corpus_id)
    try:
        stats = await client.get("/api/index/stats", params={"corpus_id": corpus_id})
        assert stats.status_code == 200, stats.text
        payload = stats.json()
        storage = payload["storage_breakdown"]
        assert storage["neo4j_store_bytes"] is None, storage
        assert "no store-size procedure" in str(storage["neo4j_store_note"]), storage
        assert int(storage["total_storage_bytes"]) == int(storage["postgres_total_bytes"]) + int(
            storage["qdrant_dense_vector_bytes"]
        )
        assert int(payload["total_storage"]) == int(storage["total_storage_bytes"])

        status = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert status.status_code == 200, status.text
        metadata = status.json()["metadata"]
        assert metadata["storage_breakdown"]["neo4j_store_bytes"] is None, metadata
        assert metadata["storage_breakdown"]["neo4j_store_note"] == storage["neo4j_store_note"]
        assert int(metadata["total_storage"]) == int(storage["total_storage_bytes"])
    finally:
        await _drop(corpus_id)
