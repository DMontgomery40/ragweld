"""API tests for persisted index run replay/status fallback endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generator

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
