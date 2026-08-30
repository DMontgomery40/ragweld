"""API tests for persisted index run replay/status fallback endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.models.index import IndexRunSummary


@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    old_runs_dir = index_api._INDEX_RUNS_DIR
    old_status = dict(index_api._STATUS)
    old_stats = dict(index_api._STATS)
    old_tasks = dict(index_api._TASKS)
    old_queues = dict(index_api._EVENT_QUEUES)
    old_active_runs = dict(index_api._ACTIVE_RUNS)
    old_queue_ctx = dict(index_api._QUEUE_RUN_CONTEXT)

    index_api._INDEX_RUNS_DIR = tmp_path
    index_api._STATUS.clear()
    index_api._STATS.clear()
    index_api._TASKS.clear()
    index_api._EVENT_QUEUES.clear()
    index_api._ACTIVE_RUNS.clear()
    index_api._QUEUE_RUN_CONTEXT.clear()

    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir
        index_api._STATUS.clear()
        index_api._STATUS.update(old_status)
        index_api._STATS.clear()
        index_api._STATS.update(old_stats)
        index_api._TASKS.clear()
        index_api._TASKS.update(old_tasks)
        index_api._EVENT_QUEUES.clear()
        index_api._EVENT_QUEUES.update(old_queues)
        index_api._ACTIVE_RUNS.clear()
        index_api._ACTIVE_RUNS.update(old_active_runs)
        index_api._QUEUE_RUN_CONTEXT.clear()
        index_api._QUEUE_RUN_CONTEXT.update(old_queue_ctx)


@pytest.mark.asyncio
async def test_latest_run_and_events_endpoints(client: AsyncClient) -> None:
    corpus_id = "replay-corpus"
    run_id = "run_20260227_test"
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=corpus_id,
        status="error",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        progress=0.42,
        error="semantic extraction parse failure",
        total_files=33,
        total_chunks=74,
        total_tokens=29224,
        embedding_provider="openai",
        embedding_model="text-embedding-3-large",
        embedding_dimensions=3072,
    )
    index_api._persist_run_summary(summary)
    index_api._append_run_event(corpus_id, run_id, {"type": "log", "message": "started"})
    index_api._append_run_event(corpus_id, run_id, {"type": "error", "message": "semantic extraction parse failure"})

    latest = await client.get(f"/api/index/{corpus_id}/runs/latest")
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert latest_payload["run_id"] == run_id
    assert latest_payload["status"] == "error"
    assert latest_payload["error"] == "semantic extraction parse failure"

    events = await client.get(f"/api/index/{corpus_id}/runs/{run_id}/events", params={"limit": 50})
    assert events.status_code == 200
    events_payload = events.json()
    assert len(events_payload) == 2
    assert events_payload[0]["type"] == "log"
    assert events_payload[1]["type"] == "error"


@pytest.mark.asyncio
async def test_index_status_prefers_persisted_run_over_stats_inference(client: AsyncClient) -> None:
    corpus_id = "status-fallback-corpus"
    run_id = "run_20260227_error"
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=corpus_id,
        status="error",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        progress=0.9,
        error="neo4j schema initialization failed",
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    index_api._persist_run_summary(summary)

    response = await client.get(f"/api/index/{corpus_id}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"] == "neo4j schema initialization failed"


@pytest.mark.asyncio
async def test_latest_run_coerces_stale_indexing_run_to_error(client: AsyncClient) -> None:
    corpus_id = "stale-run-corpus"
    run_id = "run_20260227_stale"
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=corpus_id,
        status="indexing",
        started_at=datetime.now(UTC),
        completed_at=None,
        progress=0.12,
        error=None,
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    index_api._persist_run_summary(summary)
    index_api._append_run_event(corpus_id, run_id, {"type": "progress", "message": "foo.txt", "percent": 12})

    latest = await client.get(f"/api/index/{corpus_id}/runs/latest")
    assert latest.status_code == 200
    latest_payload = latest.json()
    assert latest_payload["status"] == "error"
    assert "interrupted before completion" in str(latest_payload.get("error") or "").lower()
    assert latest_payload["completed_at"] is not None

    events = await client.get(f"/api/index/{corpus_id}/runs/{run_id}/events", params={"limit": 50})
    assert events.status_code == 200
    events_payload = events.json()
    assert len(events_payload) >= 2
    assert events_payload[-1]["type"] == "error"
    assert "interrupted before completion" in str(events_payload[-1].get("message") or "").lower()


@pytest.mark.asyncio
async def test_index_status_coerces_stale_indexing_run_to_error(client: AsyncClient) -> None:
    corpus_id = "stale-status-corpus"
    run_id = "run_20260227_stale_status"
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=corpus_id,
        status="indexing",
        started_at=datetime.now(UTC),
        completed_at=None,
        progress=0.42,
        error=None,
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    index_api._persist_run_summary(summary)

    response = await client.get(f"/api/index/{corpus_id}/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["completed_at"] is not None
    assert "interrupted before completion" in str(payload.get("error") or "").lower()


def _runs_dir_fingerprint(runs_root: Path) -> set[tuple[str, int, int, str]]:
    """Every file under the runs root with its size, mtime_ns and contents.

    Contents are included because a rewrite that happens to preserve size and lands inside one
    mtime tick would otherwise pass: the claim being tested is "no writes", not "no visible
    writes".
    """
    return {
        (
            str(p.relative_to(runs_root)),
            p.stat().st_size,
            p.stat().st_mtime_ns,
            p.read_text(),
        )
        for p in sorted(runs_root.rglob("*"))
        if p.is_file()
    }


@pytest.mark.asyncio
async def test_latest_run_with_finalize_false_is_a_pure_read(
    client: AsyncClient, tmp_path
) -> None:
    """`finalize=false` touches nothing on disk and reports the run exactly as stored.

    The dashboard's index-runs listing asks every corpus for its latest run on every load. The
    finalizing path reads the fence, loads scoped config and flushes the event queue per call,
    and rewrites the summary of any run stuck in `indexing` -- so a panel that only displays
    runs would mutate them N times a page load, against corpora that may be mid-run.

    That an `indexing` run comes back as `indexing` is the load-bearing half: it is precisely
    the status the finalizing path would rewrite (to `complete` or to `error`), so returning it
    untouched proves the reconcile did not run rather than merely that it found nothing to do.
    """
    corpus_id = "readonly-corpus"
    run_id = "run_20260830_readonly"
    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=corpus_id,
        status="indexing",
        started_at=datetime.now(UTC),
        completed_at=None,
        progress=0.31,
        total_files=5,
        total_chunks=11,
        total_tokens=900,
        figures_described=7,
        figure_description_cost_usd=0.0125,
    )
    index_api._persist_run_summary(summary)
    await asyncio.to_thread(index_api._flush_run_events_sync)

    runs_root = index_api._INDEX_RUNS_DIR
    before = _runs_dir_fingerprint(runs_root)
    assert before, "the fixture must have persisted a summary to read"

    response = await client.get(
        f"/api/index/{corpus_id}/runs/latest", params={"finalize": "false"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == run_id
    # Returned as stored: the reconcile that would have rewritten this status never ran.
    assert payload["status"] == "indexing"
    assert payload["completed_at"] is None
    assert payload["figures_described"] == 7
    assert payload["figure_description_cost_usd"] == pytest.approx(0.0125)

    await asyncio.to_thread(index_api._flush_run_events_sync)
    assert _runs_dir_fingerprint(runs_root) == before, "the read-only path wrote to the runs dir"


@pytest.mark.asyncio
async def test_latest_run_with_finalize_false_still_404s_when_nothing_is_persisted(
    client: AsyncClient,
) -> None:
    """The read-only path keeps the endpoint's own 404 contract; it does not invent an empty run."""
    response = await client.get(
        "/api/index/never-indexed-corpus/runs/latest", params={"finalize": "false"}
    )
    assert response.status_code == 404
    assert "never-indexed-corpus" in response.json()["detail"]
