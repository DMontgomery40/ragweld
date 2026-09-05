"""API tests for persisted index run replay/status fallback endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.indexing.accounting import IndexAccountingOwner
from server.indexing.run_records import write_run_summary
from server.models.index import (
    GraphExtractionTelemetry,
    GraphGenerationMetadata,
    GraphResolutionTelemetry,
    IndexRunSummary,
)


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
    # The page carries the run's real total, so a cap is never mistaken for a fact.
    assert events_payload["total"] == 2
    assert events_payload["first_index"] == 0
    assert events_payload["corpus_id"] == corpus_id
    assert len(events_payload["events"]) == 2
    assert events_payload["events"][0]["type"] == "log"
    assert events_payload["events"][1]["type"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("corpus_ids", [("a:b", "a@b"), ("a__b", "a_b"), ("_a_", "a")])
@pytest.mark.parametrize("run_kind", ["index", "schema_proposal"])
async def test_colliding_corpus_directories_cannot_disclose_retained_runs(client: AsyncClient, corpus_ids, run_kind) -> None:
    own, other = corpus_ids
    assert index_api._repo_runs_dir(own) == index_api._repo_runs_dir(other)
    now = datetime.now(UTC)
    own_run = IndexRunSummary(run_id="own-run", repo_id=own, run_kind=run_kind, status="complete", started_at=now)
    index_api._persist_run_summary(own_run)
    index_api._append_run_event(own, own_run.run_id, {"type": "log", "message": "owned evidence"})
    await index_api._flush_run_events()
    for suffix in (f"runs/latest?finalize=false&run_kind={run_kind}", "runs/own-run", "runs/own-run/events"):
        response = await client.get(f"/api/index/{other}/{suffix}")
        assert response.status_code == 404, response.text
        assert "owned evidence" not in response.text
    assert index_api._load_run_summary(other, own_run.run_id) is None
    assert index_api._load_run_events(other, own_run.run_id, limit=50) == ([], 0)
    assert index_api._latest_run_stage(other, own_run.run_id) is None
    other_run = own_run.model_copy(update={"repo_id": other, "run_id": "other-run", "started_at": now + timedelta(seconds=1)})
    index_api._persist_run_summary(other_run)
    await index_api._flush_run_events()
    for corpus, expected in ((own, "own-run"), (other, "other-run")):
        response = await client.get(f"/api/index/{corpus}/runs/latest", params={"finalize": False, "run_kind": run_kind})
        assert response.status_code == 200 and response.json()["run_id"] == expected
        assert response.json()["corpus_id"] == corpus


@pytest.mark.asyncio
async def test_run_aliases_and_foreign_event_rows_are_not_replayed(client: AsyncClient) -> None:
    corpus, own_run, alias_run = "events-scope", "r:1", "r@1"
    assert index_api._run_dir(corpus, own_run) == index_api._run_dir(corpus, alias_run)
    index_api._persist_run_summary(IndexRunSummary(run_id=own_run, repo_id=corpus, status="complete", started_at=datetime.now(UTC)))
    index_api._append_run_event(corpus, own_run, {"type": "log", "message": "owned stage"})
    index_api._append_run_event(corpus, alias_run, {"type": "log", "message": "foreign stage"})
    await index_api._flush_run_events()
    response = await client.get(f"/api/index/{corpus}/runs/{alias_run}/events")
    assert response.status_code == 404
    assert index_api._load_run_summary(corpus, alias_run) is None
    response = await client.get(f"/api/index/{corpus}/runs/{own_run}/events")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [event["message"] for event in response.json()["events"]] == ["owned stage"]
    assert index_api._latest_run_stage(corpus, own_run) == "owned stage"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["indexing", "complete", "error", "cancelled"])
async def test_latest_is_start_order_after_old_run_reconciliation_and_proposal(client: AsyncClient, status: str) -> None:
    corpus_id = "ordered-runs"
    now = datetime.now(UTC)
    old = IndexRunSummary(run_id="old", repo_id=corpus_id, status="complete", started_at=now-timedelta(hours=2))
    new = IndexRunSummary.model_validate({"run_id":"new", "repo_id":corpus_id, "status":status, "started_at":now-timedelta(hours=1)})
    proposal = IndexRunSummary(run_id="proposal", repo_id=corpus_id, run_kind="schema_proposal", status="complete", started_at=now)
    for run in (new, proposal, old):
        write_run_summary(index_api._run_summary_path(corpus_id, run.run_id), run)
    # A cost reconciliation or file restoration changes mtime, not run chronology.
    os.utime(index_api._run_summary_path(corpus_id, old.run_id), (now.timestamp()+3600, now.timestamp()+3600))
    response = await client.get(f"/api/index/{corpus_id}/runs/latest", params={"finalize":False})
    assert response.status_code == 200 and response.json()["run_id"] == "new"
    exact = await client.get(f"/api/index/{corpus_id}/runs/proposal")
    assert exact.status_code == 200 and exact.json()["run_kind"] == "schema_proposal"
    legacy = await client.post(f"/api/index/{corpus_id}/runs/old/costs/reconcile")
    assert legacy.status_code == 200 and legacy.json()["accounting"] is None


def test_equal_start_times_use_stable_run_id_order() -> None:
    now = datetime.now(UTC)
    for run_id in ("run-z", "run-a"):
        run = IndexRunSummary(run_id=run_id, repo_id="ties", status="complete", started_at=now)
        write_run_summary(index_api._run_summary_path("ties", run_id), run)
    assert index_api._load_latest_run_summary("ties").run_id == "run-z"


@pytest.mark.asyncio
@pytest.mark.requires_postgres
@pytest.mark.parametrize("history_state", ["reconfigured", "deindexed", "corpus_deleted"])
async def test_historical_reconciliation_keeps_original_gateway_after_current_state_changes(
    client: AsyncClient, tmp_path: Path, history_state: str,
) -> None:
    observed: list[str] = []

    class NativeLedger(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            observed.append(self.path)
            body = json.dumps({"data": [], "total": 0, "page": 1, "page_size": 100,
                               "total_pages": 0, "total_is_capped": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), NativeLedger)
    serving = threading.Thread(target=gateway.serve_forever, daemon=True)
    serving.start()
    corpus_id = f"pytest_native_history_{uuid.uuid4().hex[:8]}"
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path)})
    assert created.status_code in (200, 201), created.text
    try:
        run = IndexRunSummary(run_id="local-run", repo_id=corpus_id, status="complete", started_at=datetime.now(UTC))
        owner = IndexAccountingOwner(index_api._run_summary_path(corpus_id, run.run_id), run,
                                     config_json="{}", models={}, coverage_complete=True, coverage_notes=[],
                                     gateway_base_url=f"http://127.0.0.1:{gateway.server_port}")
        owner.finish()
        configured = await client.patch(f"/api/config/chat?corpus_id={corpus_id}", json={"litellm": {"base_url": "http://127.0.0.1:1/v1"}})
        assert configured.status_code == 200, configured.text
        if history_state == "deindexed":
            removed = await client.delete(f"/api/index/{corpus_id}")
            assert removed.status_code == 200, removed.text
        elif history_state == "corpus_deleted":
            removed = await client.delete(f"/api/corpora/{corpus_id}")
            assert removed.status_code == 200, removed.text
        exact = await client.get(f"/api/index/{corpus_id}/runs/{run.run_id}")
        assert exact.status_code == 200, exact.text
        refreshed = await client.post(f"/api/index/{corpus_id}/runs/{run.run_id}/costs/reconcile")
        assert refreshed.status_code == 200, refreshed.text
        record = refreshed.json()["accounting"]
        assert record["reconciliation_error"] is None
        assert record["costs"]["state"] == "complete"
        assert record["costs"]["native_logged_usd"] == 0
        assert len(observed) == 1
        request = urlsplit(observed[0])
        assert request.path == "/spend/logs/v2"
        assert parse_qs(request.query)["session_id"] == [run.run_id]
    finally:
        if history_state != "corpus_deleted":
            await client.delete(f"/api/corpora/{corpus_id}")
        gateway.shutdown()
        gateway.server_close()
        serving.join(timeout=2)


@pytest.mark.asyncio
@pytest.mark.requires_postgres
@pytest.mark.parametrize("status", ["complete", "error", "cancelled"])
@pytest.mark.parametrize("cached", [False, True])
async def test_deleted_corpus_current_status_is_absent_but_run_history_survives(
    client: AsyncClient, tmp_path: Path, status: str, cached: bool,
) -> None:
    corpus_id = f"pytest_deleted_status_{uuid.uuid4().hex[:8]}"
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(tmp_path)})
    assert created.status_code in (200, 201), created.text
    run = IndexRunSummary.model_validate({
        "run_id": "retained", "repo_id": corpus_id, "status": status,
        "started_at": datetime.now(UTC), "completed_at": datetime.now(UTC),
    })
    write_run_summary(index_api._run_summary_path(corpus_id, run.run_id), run)
    removed = await client.delete(f"/api/corpora/{corpus_id}")
    assert removed.status_code == 200, removed.text
    if cached:
        # Another API worker can retain its terminal cache after the deletion.
        index_api._STATUS[corpus_id] = index_api.IndexStatus.model_validate({
            "repo_id": corpus_id, "status": status, "progress": 1.0,
        })
    response = await client.get(f"/api/index/{corpus_id}/status")
    assert response.status_code == 404, response.text
    for suffix in ("retained", "latest?finalize=false"):
        history = await client.get(f"/api/index/{corpus_id}/runs/{suffix}")
        assert history.status_code == 200, history.text
        assert history.json()["status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize(("gateway", "key", "error"), [
    ("http://127.0.0.1:1", None, "gateway_credentials_unavailable"),
    ("http://127.0.0.1:1", "   ", "gateway_credentials_unavailable"),
    ("http://127.0.0.1:invalid", "synthetic-test-key", "gateway_client_configuration_invalid"),
    (None, "synthetic-test-key", "saved_gateway_location_unavailable"),
])
async def test_historical_reconciliation_setup_failure_is_durable(
    client: AsyncClient, gateway: str | None, key: str | None, error: str,
) -> None:
    corpus_id, run_id = "setup-error-history", "retained"
    run = IndexRunSummary(run_id=run_id, repo_id=corpus_id, status="complete", started_at=datetime.now(UTC))
    owner = IndexAccountingOwner(index_api._run_summary_path(corpus_id, run_id), run,
                                 config_json="{}", models={}, coverage_complete=True, coverage_notes=[],
                                 gateway_base_url=gateway)
    owner.finish()
    previous = os.environ.pop("LITELLM_API_KEY", None)
    if key is not None:
        os.environ["LITELLM_API_KEY"] = key
    try:
        response = await client.post(f"/api/index/{corpus_id}/runs/{run_id}/costs/reconcile")
        assert response.status_code == 200, response.text
        record = response.json()["accounting"]
        assert record["reconciliation_error"] == error
        assert record["reconciled_at"] is not None
        assert record["costs"] is None
        retained = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
        assert retained.json() == response.json()
    finally:
        os.environ.pop("LITELLM_API_KEY", None)
        if previous is not None:
            os.environ["LITELLM_API_KEY"] = previous


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    "saved_gateway_location_unavailable", "gateway_credentials_unavailable",
    "gateway_client_configuration_invalid",
])
async def test_late_setup_error_preserves_newer_native_reconciliation_and_status(
    client: AsyncClient, error: str,
) -> None:
    received = threading.Event()

    class NativeLedger(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            received.set()
            payload = json.dumps({"data": [], "total": 0, "page": 1, "page_size": 100,
                                  "total_pages": 0, "total_is_capped": False}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    gateway = ThreadingHTTPServer(("127.0.0.1", 0), NativeLedger)
    serving = threading.Thread(target=gateway.serve_forever, daemon=True)
    serving.start()
    try:
        run = IndexRunSummary(run_id="retained", repo_id="late-setup", status="indexing", started_at=datetime.now(UTC))
        path = index_api._run_summary_path(run.repo_id, run.run_id)
        owner = IndexAccountingOwner(path, run, config_json="{}", models={}, coverage_complete=True,
                                     coverage_notes=[], gateway_base_url=f"http://127.0.0.1:{gateway.server_port}")
        owner.finish()
        captured = IndexRunSummary.model_validate_json(path.read_text())
        # Interleave a successful native HTTP reconciliation after the older read
        # but before its setup-error merge acquires the summary lock.
        refreshed = await client.post(f"/api/index/{run.repo_id}/runs/{run.run_id}/costs/reconcile")
        assert refreshed.status_code == 200, refreshed.text
        assert received.is_set()
        assert refreshed.json()["accounting"]["costs"]["state"] == "complete"
        write_run_summary(path, run.model_copy(update={"status": "complete", "progress": 1.0}))
        before = path.read_bytes()
        response = await index_api._record_cost_reconciliation_setup_error(captured, error)
        assert path.read_bytes() == before
        assert response.status == "complete" and response.progress == 1.0
        assert response.accounting is not None
        assert response.accounting.reconciliation_error is None
        assert response.accounting.costs is not None and response.accounting.costs.state == "complete"
    finally:
        gateway.shutdown()
        gateway.server_close()
        serving.join(timeout=2)


@pytest.mark.asyncio
async def test_latest_run_replays_graph_promotion_telemetry_and_refusal(client: AsyncClient) -> None:
    corpus_id = "graph-refusal-replay"
    run_id = "run_20260831_graph_refusal"
    graph = GraphGenerationMetadata(
        policy="semantic",
        schema_hash="a" * 64,
        schema_payload={"node_types": []},
        extraction=GraphExtractionTelemetry(
            selected_chunks=3,
            attempted_chunks=3,
            succeeded_chunks=3,
            failed_chunks=0,
            truncated_chunks=0,
            extracted_entities=0,
            semantic_relationships=0,
            from_chunk_relationships=0,
        ),
        resolution=GraphResolutionTelemetry(
            candidate_nodes=0,
            resolved_nodes=0,
            merged_nodes=0,
            unresolved_duplicate_groups=0,
        ),
    )
    index_api._persist_run_summary(
        IndexRunSummary(
            run_id=run_id,
            repo_id=corpus_id,
            status="error",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            error="Graph promotion refused (zero_entities, zero_semantic_relationships)",
            graph_metadata=graph,
            graph_failure_codes=["zero_entities", "zero_semantic_relationships"],
            graph_promotable=False,
        )
    )

    response = await client.get(f"/api/index/{corpus_id}/runs/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_promotable"] is False
    assert payload["graph_failure_codes"] == [
        "zero_entities",
        "zero_semantic_relationships",
    ]
    assert payload["graph_metadata"]["extraction"]["selected_chunks"] == 3
    assert payload["graph_metadata"]["resolution"]["resolved_nodes"] == 0


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
    assert response.status_code == 404
    retained = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
    assert retained.status_code == 200
    payload = retained.json()
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
    assert len(events_payload["events"]) >= 2
    assert events_payload["total"] == len(events_payload["events"])
    assert events_payload["events"][-1]["type"] == "error"
    assert "interrupted before completion" in str(events_payload["events"][-1].get("message") or "").lower()


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
    assert response.status_code == 404
    retained = await client.get(f"/api/index/{corpus_id}/runs/{run_id}")
    assert retained.status_code == 200
    assert retained.json()["status"] == "indexing"
    assert retained.json()["completed_at"] is None


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


@pytest.mark.asyncio
async def test_the_event_page_reports_the_total_not_the_requested_cap(client: AsyncClient) -> None:
    """The run header printed "500 replayed events" -- exactly the limit it had asked for.

    A slice alone cannot tell a complete log from a truncated one, so the header presented a
    cap as a fact about the run. The page states the total and where the slice starts.
    """
    corpus_id = "event-cap-corpus"
    run_id = "run_20260227_capped"
    index_api._persist_run_summary(
        IndexRunSummary(
            run_id=run_id,
            repo_id=corpus_id,
            status="complete",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            progress=1.0,
        )
    )
    for n in range(37):
        index_api._append_run_event(corpus_id, run_id, {"type": "log", "message": f"line {n}"})

    capped = await client.get(f"/api/index/{corpus_id}/runs/{run_id}/events", params={"limit": 10})
    assert capped.status_code == 200
    page = capped.json()
    assert len(page["events"]) == 10
    assert page["total"] == 37
    assert page["first_index"] == 27
    # The tail is what is served: the most recent events, oldest first.
    assert page["events"][0]["message"] == "line 27"
    assert page["events"][-1]["message"] == "line 36"

    whole = await client.get(f"/api/index/{corpus_id}/runs/{run_id}/events", params={"limit": 500})
    whole_page = whole.json()
    assert whole_page["total"] == 37
    assert whole_page["first_index"] == 0
    assert len(whole_page["events"]) == 37
