"""Real-file accounting checkpoints remain durable under status and worker writes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr, ValidationError

from server.indexing.accounting import (
    IndexAccountingOwner,
    accounting_census,
    accounting_owner_alive,
    interrupt_abandoned_accounting,
    reconcile_run_costs,
)
from server.indexing.run_records import (
    initialize_accounted_run,
    initialize_run_accounting,
    persist_request_census,
    update_run_accounting,
    write_run_summary,
)
from server.models.index import IndexRunSummary
from server.models.run_accounting import (
    IndexRunAccounting,
    RunCostIdentity,
    RunRequestCensus,
)
from server.models.tribrid_config_model import TriBridConfig
from server.observability.gateway_costs import NativeSpendReader
from server.observability.run_census import CensusTransport
from server.observability.runtime import get_observability_manager


def _summary() -> IndexRunSummary:
    return IndexRunSummary(run_id="run-a", repo_id="corpus-a", status="indexing", started_at=datetime.now(UTC))


def _accounting(summary: IndexRunSummary) -> IndexRunAccounting:
    return IndexRunAccounting(
        session_id=summary.run_id, corpus_id=summary.repo_id, started_at=summary.started_at,
        config_fingerprint="0" * 64, models={"semantic_kg": "openai.gpt-5.6-sol"},
    )


def _checkpoint(summary: IndexRunSummary, **changes: object) -> RunRequestCensus:
    data = {
        "identity": RunCostIdentity(session_id=summary.run_id, corpus_id=summary.repo_id, lane="semantic_kg"),
        "revision": 0, "started_requests": 0, "completed_requests": 0,
        "failed_requests": 0, "uncertain_requests": 0, "inflight": 0,
        "active_producers": 0, "owner_finished": False, "dispatch_enabled": True, "state": "open",
    }
    return RunRequestCensus.model_validate({**data, **changes})


def _read(path: Path) -> IndexRunSummary:
    return IndexRunSummary.model_validate_json(path.read_text())


def test_summary_updates_cannot_erase_durable_census_or_processed_counts(tmp_path: Path) -> None:
    path = tmp_path / "run-a" / "summary.json"
    original = _summary()
    write_run_summary(path, original)
    initialize_run_accounting(path, _accounting(original))
    persist_request_census(path, _checkpoint(original))
    sent = _checkpoint(original, revision=1, started_requests=1, inflight=1, active_producers=1)
    persist_request_census(path, sent)
    update_run_accounting(path, lambda record: record.model_copy(update={"processed_chunks": 8, "processed_tokens": 37}))
    for status in ("indexing", "cancelled", "error", "complete"):
        write_run_summary(path, original.model_copy(update={"status": status}))
        saved = _read(path)
        assert saved.status == status
        assert saved.accounting is not None
        assert saved.accounting.census["semantic_kg"] == sent
        assert (saved.accounting.processed_chunks, saved.accounting.processed_tokens) == (8, 37)
        assert saved.accounting.ended_at is None


def test_concurrent_accounting_and_status_updates_are_serialized(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    write_run_summary(path, summary)
    initialize_run_accounting(path, _accounting(summary))

    def advance(_index: int) -> None:
        update_run_accounting(path, lambda record: record.model_copy(update={"processed_chunks": record.processed_chunks + 1}))
        write_run_summary(path, summary)

    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(advance, range(80)))
    saved = _read(path)
    assert saved.accounting is not None and saved.accounting.processed_chunks == 80
    assert not list(tmp_path.glob(".summary-*.tmp"))
    assert path.stat().st_mode & 0o777 == 0o600


def test_owner_lock_tracks_actual_retained_workers_and_preserves_progress(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    owner = IndexAccountingOwner(
        path, summary, config_json="{}", models={"semantic_kg": "kg"},
        coverage_complete=True, coverage_notes=[], gateway_attempt_policy_verified=True,
    )
    worker = owner.scopes["semantic_kg"].producer_started()
    owner.progress(files=2, chunks=14, tokens=900)
    owner.finish()
    assert accounting_owner_alive(path)
    assert accounting_census(_read(path).accounting).state == "open"
    worker.close()
    assert not accounting_owner_alive(path)
    saved = _read(path).accounting
    assert accounting_census(saved).state == "closed"
    assert (saved.processed_files, saved.processed_chunks, saved.processed_tokens) == (2, 14, 900)


@pytest.mark.parametrize("field", ["files", "chunks", "tokens"])
def test_owner_rejects_negative_processed_deltas(tmp_path: Path, field: str) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models={}, coverage_complete=True, coverage_notes=[])
    with pytest.raises(ValueError, match="cannot decrease"):
        owner.progress(**{field: -1})
    owner.finish()
    assert accounting_census(_read(path).accounting).state == "closed"
    assert not accounting_owner_alive(path)


def test_another_owner_cannot_overwrite_a_live_run(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    owner = IndexAccountingOwner(path, summary, config_json="{}", models={"semantic_kg": "kg"}, coverage_complete=True, coverage_notes=[])
    before = path.read_bytes()
    with pytest.raises(ValueError, match="already initialized"):
        IndexAccountingOwner(path, summary, config_json="changed", models={}, coverage_complete=True, coverage_notes=[])
    assert path.read_bytes() == before
    owner.finish()


def test_worker_process_death_keeps_open_census_interrupted_not_reconstructed(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    code = """
import os, sys
from datetime import UTC, datetime
from pathlib import Path
from server.indexing.accounting import IndexAccountingOwner
from server.models.index import IndexRunSummary
owner = IndexAccountingOwner(Path(sys.argv[1]), IndexRunSummary(run_id='run-a',repo_id='corpus-a',status='indexing',started_at=datetime.now(UTC)), config_json='{}',models={'semantic_kg':'kg'},coverage_complete=True,coverage_notes=[])
owner.progress(files=1,chunks=8,tokens=43)
owner.scopes['semantic_kg'].producer_started()
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)], check=False)
    assert result.returncode == 17
    assert not accounting_owner_alive(path)
    interrupt_abandoned_accounting(path)
    saved = _read(path).accounting
    assert accounting_census(saved).state == "interrupted"
    assert saved.ended_at is None and saved.costs is None
    assert (saved.processed_files, saved.processed_chunks, saved.processed_tokens) == (1, 8, 43)


def test_census_closes_only_after_all_declared_lanes_and_workers(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    write_run_summary(path, summary)
    record = _accounting(summary).model_copy(update={"models": {"semantic_kg": "kg", "figure_description": "vision"}})
    initialize_run_accounting(path, record)
    initial = _checkpoint(summary)
    persist_request_census(path, initial)
    finished = _checkpoint(summary, revision=1, owner_finished=True, dispatch_enabled=False, state="closed")
    persist_request_census(path, finished)
    assert _read(path).accounting.ended_at is None
    figure = initial.model_copy(update={"identity": RunCostIdentity(session_id=summary.run_id, corpus_id=summary.repo_id, lane="figure_description")})
    persist_request_census(path, figure)
    persist_request_census(path, figure.model_copy(update={"revision": 1, "owner_finished": True, "dispatch_enabled": False, "active_producers": 1}))
    assert _read(path).accounting.ended_at is None
    persist_request_census(path, figure.model_copy(update={"revision": 2, "owner_finished": True, "dispatch_enabled": False, "state": "closed"}))
    assert _read(path).accounting.ended_at is not None


@pytest.mark.parametrize("change", [
    {"started_requests": -1}, {"started_requests": True},
    {"completed_requests": 1}, {"inflight": 1},
    {"started_requests": 1, "completed_requests": 1, "failed_requests": 1, "uncertain_requests": 1},
    {"state": "closed"},
    {"state": "closed", "owner_finished": True, "dispatch_enabled": False, "active_producers": 1},
])
def test_invalid_census_states_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _checkpoint(_summary(), **change)


@pytest.mark.parametrize("change", [
    {"revision": 3}, {"revision": 0},
    {"revision": 2, "started_requests": 0, "completed_requests": 0, "inflight": 0},
])
def test_stale_or_regressive_census_never_changes_the_saved_record(tmp_path: Path, change: dict[str, object]) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    write_run_summary(path, summary)
    initialize_run_accounting(path, _accounting(summary))
    persist_request_census(path, _checkpoint(summary))
    sent = _checkpoint(summary, revision=1, started_requests=1, inflight=1)
    persist_request_census(path, sent)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persist_request_census(path, RunRequestCensus.model_validate({**sent.model_dump(), **change}))
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value", [("session_id", "other-run"), ("corpus_id", "other-corpus"), ("config_fingerprint", "1" * 64), ("gateway_base_url", "http://other-gateway:4000"), ("models", {})])
def test_immutable_accounting_identity_cannot_be_replaced(tmp_path: Path, field: str, value: object) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    write_run_summary(path, summary)
    initialize_run_accounting(path, _accounting(summary))
    before = path.read_bytes()
    with pytest.raises(ValueError):
        update_run_accounting(path, lambda record: record.model_copy(update={field: value}))
    assert path.read_bytes() == before


@pytest.mark.parametrize("url", [
    "", "file:///tmp/gateway", "/relative", "https://user:secret@example.test",
    "https://example.test/v1", "https://example.test?key=private", "https://example.test#fragment",
])
def test_saved_gateway_refuses_non_root_or_credential_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        IndexRunAccounting.model_validate({**_accounting(_summary()).model_dump(), "gateway_base_url": url})


@pytest.mark.parametrize("url", ["http://127.0.0.1:54000", "https://gateway.example.test/"])
def test_saved_gateway_survives_accounting_reload(url: str, tmp_path: Path) -> None:
    summary = _summary()
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(
        path, summary, config_json="{}", models={}, coverage_complete=True,
        coverage_notes=[], gateway_base_url=url,
    )
    owner.finish()
    assert _read(path).accounting.gateway_base_url == url


def test_missing_corrupt_or_unwritable_run_refuses_accounting_initialization(tmp_path: Path) -> None:
    summary = _summary()
    path = tmp_path / "summary.json"
    with pytest.raises(FileNotFoundError):
        initialize_run_accounting(path, _accounting(summary))
    path.write_text("not valid JSON")
    with pytest.raises(ValidationError):
        initialize_run_accounting(path, _accounting(summary))
    with pytest.raises(OSError):
        write_run_summary(path / "child.json", summary)
    assert path.read_text() == "not valid JSON"


@pytest.mark.parametrize("previous_closed", [False, True])
def test_persistence_failure_can_escalate_and_keep_late_worker_evidence(tmp_path: Path, previous_closed: bool) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    write_run_summary(path, summary)
    initialize_run_accounting(path, _accounting(summary))
    previous = _checkpoint(summary)
    if previous_closed:
        previous = _checkpoint(summary, owner_finished=True, dispatch_enabled=False, state="closed")
    persist_request_census(path, previous)
    interrupted = _checkpoint(summary, revision=3, started_requests=1, inflight=1, state="interrupted", dispatch_enabled=False)
    persist_request_census(path, interrupted)
    finished = interrupted.model_copy(update={"revision": 4, "inflight": 0, "completed_requests": 1, "uncertain_requests": 1})
    persist_request_census(path, finished)
    saved = _read(path).accounting
    assert saved is not None and saved.census["semantic_kg"] == finished
    assert saved.ended_at is None
    assert saved.costs is None
    with pytest.raises(ValueError):
        persist_request_census(path, finished.model_copy(update={"revision": 5, "state": "closed", "owner_finished": True}))


@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg", "embedding": "embed"}])
def test_stale_open_observation_cannot_interrupt_a_newly_closed_owner(tmp_path: Path, models) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models=models, coverage_complete=True, coverage_notes=[])
    assert _read(path).accounting.ended_at is None  # Reconciliation's stale observation.
    owner.finish()
    assert not accounting_owner_alive(path)
    closed = path.read_bytes()
    modified = path.stat().st_mtime_ns
    interrupt_abandoned_accounting(path)
    assert path.read_bytes() == closed
    assert path.stat().st_mtime_ns == modified
    assert accounting_census(_read(path).accounting).state == "closed"


@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg"}])
def test_duplicate_finished_owner_is_refused_before_any_summary_write(tmp_path: Path, models) -> None:
    path = tmp_path / "summary.json"
    initial = _summary()
    owner = IndexAccountingOwner(path, initial, config_json="{}", models=models, coverage_complete=True, coverage_notes=[])
    owner.finish()
    write_run_summary(path, initial.model_copy(update={"status": "complete", "total_chunks": 19}))
    previous = path.read_bytes()
    modified = path.stat().st_mtime_ns
    with pytest.raises(ValueError, match="already initialized"):
        IndexAccountingOwner(path, initial, config_json="stale-config", models={}, coverage_complete=False, coverage_notes=[])
    assert path.read_bytes() == previous
    assert path.stat().st_mtime_ns == modified
    assert not accounting_owner_alive(path)


@pytest.mark.parametrize("names", [("a.json", "b.json"), ("a.json", "a.yaml")])
def test_lifetime_locks_are_specific_to_the_complete_summary_filename(tmp_path: Path, names) -> None:
    paths = [tmp_path / name for name in names]
    owners = []
    try:
        for index, path in enumerate(paths):
            owners.append(IndexAccountingOwner(path, _summary().model_copy(update={"run_id": f"run-{index}"}), config_json="{}", models={}, coverage_complete=True, coverage_notes=[]))
        assert all(accounting_owner_alive(path) for path in paths)
        owners[0].finish()
        assert not accounting_owner_alive(paths[0])
        assert accounting_owner_alive(paths[1])
    finally:
        for owner in owners:
            owner.finish()


def test_live_neighbor_does_not_hide_an_abandoned_summary(tmp_path: Path) -> None:
    owner = IndexAccountingOwner(tmp_path / "live.json", _summary(), config_json="{}", models={}, coverage_complete=True, coverage_notes=[])
    dead = tmp_path / "dead.json"
    summary = _summary().model_copy(update={"run_id": "dead-run"})
    write_run_summary(dead, summary)
    initialize_run_accounting(dead, _accounting(summary))
    try:
        assert not accounting_owner_alive(dead)
        interrupt_abandoned_accounting(dead)
        assert accounting_census(_read(dead).accounting).state == "interrupted"
        assert accounting_owner_alive(owner.path)
    finally:
        owner.finish()


@pytest.mark.parametrize("existing_lanes", [[], ["semantic_kg"], ["embedding"]])
def test_old_partial_bootstrap_is_recovered_as_interrupted_and_incomplete(tmp_path: Path, existing_lanes) -> None:
    summary = _summary()
    path = tmp_path / "summary.json"
    record = _accounting(summary).model_copy(update={"models": {"semantic_kg": "kg", "embedding": "embed"}, "coverage_complete": True})
    write_run_summary(path, summary)
    initialize_run_accounting(path, record)
    for lane in existing_lanes:
        checkpoint = _checkpoint(summary)
        persist_request_census(path, checkpoint.model_copy(update={
            "identity": checkpoint.identity.model_copy(update={"lane": lane}),
        }))
    interrupt_abandoned_accounting(path)
    saved = _read(path).accounting
    assert set(saved.census) == set(record.models)
    assert saved.owner_interrupted is True
    assert all(item.state == "interrupted" and not item.dispatch_enabled for item in saved.census.values())
    assert accounting_census(saved).state == "interrupted"
    assert not accounting_census(saved).coverage_complete
    before = path.read_bytes()
    interrupt_abandoned_accounting(path)
    assert path.read_bytes() == before


def test_dead_zero_lane_owner_has_an_explicit_interrupted_state(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    initialize_accounted_run(path, summary, _accounting(summary).model_copy(update={"models": {}}))
    interrupt_abandoned_accounting(path)
    assert _read(path).accounting.owner_interrupted is True
    assert accounting_census(_read(path).accounting).state == "interrupted"


def test_bootstrap_process_death_before_scope_creation_already_has_every_lane_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    code = """
import os, sys
from datetime import UTC, datetime
from pathlib import Path
from server.indexing.accounting import IndexAccountingOwner
from server.models.index import IndexRunSummary
def die_before_scope(frame, event, arg):
    if event == 'call' and frame.f_code.co_qualname == 'RunCensusScope.__init__':
        os._exit(19)
    return die_before_scope
sys.settrace(die_before_scope)
IndexAccountingOwner(Path(sys.argv[1]), IndexRunSummary(run_id='run-a',repo_id='corpus-a',status='indexing',started_at=datetime.now(UTC)),config_json='{}',models={'semantic_kg':'kg','embedding':'embed'},coverage_complete=True,coverage_notes=[])
"""
    result = subprocess.run([sys.executable, "-c", code, str(path)], check=False, timeout=10)
    assert result.returncode == 19
    saved = _read(path).accounting
    assert set(saved.census) == set(saved.models) == {"semantic_kg", "embedding"}
    assert all(item.revision == 0 and item.started_requests == 0 for item in saved.census.values())
    assert not accounting_owner_alive(path)
    interrupt_abandoned_accounting(path)
    assert accounting_census(_read(path).accounting).state == "interrupted"


def test_initial_scope_acknowledgements_do_not_rewrite_atomic_bootstrap(tmp_path: Path) -> None:
    summary = _summary()
    path = tmp_path / "summary.json"
    initialize_accounted_run(path, summary, _accounting(summary))
    before, modified = path.read_bytes(), path.stat().st_mtime_ns
    persist_request_census(path, _checkpoint(summary))
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified


@contextlib.contextmanager
def _held_native_page(first_mode: str):
    """Real HTTP scheduling using the pinned native v2 empty-page contract.

    Native gateway tests separately establish this wire shape. Here HTTP events
    provide deterministic interleavings without changing reader/owner methods.
    """
    received, release = threading.Event(), threading.Event()
    counter_lock = threading.Lock()
    requests = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_GET(self):  # noqa: N802 - stdlib HTTP handler
            nonlocal requests
            with counter_lock:
                requests += 1
                first = requests == 1
            assert self.path.startswith("/spend/logs/v2?")
            assert self.headers.get("Authorization") == "Bearer synthetic-only"
            if first and first_mode != "success":
                received.set()
                assert release.wait(10)
            status = 503 if first and first_mode == "http_error" else 200
            body = b"malformed JSON" if first and first_mode == "malformed" else json.dumps({
                "data": [], "total": 0, "page": 1, "page_size": 100,
                "total_pages": 0, "total_is_capped": False,
            }).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "http_error", "malformed"])
async def test_late_failed_reconciliation_does_not_erase_a_newer_success(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models={"semantic_kg": "kg"}, coverage_complete=True, coverage_notes=[], gateway_attempt_policy_verified=True)
    owner.finish()
    with _held_native_page(mode) as (base, received, release):
        slow = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
        fast = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
        earlier = asyncio.create_task(reconcile_run_costs(path, slow))
        assert await asyncio.to_thread(received.wait, 3)
        newer = await reconcile_run_costs(path, fast)
        assert newer.accounting.costs is not None and newer.accounting.costs.state == "complete"
        checkpoint = newer.accounting
        if mode != "timeout":
            release.set()
        returned = await earlier
        assert returned.accounting == checkpoint
        assert _read(path).accounting == checkpoint


@pytest.mark.asyncio
async def test_returned_summary_preserves_a_worker_write_during_the_final_filesystem_read(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models={"semantic_kg": "kg"}, coverage_complete=True, coverage_notes=[])
    trigger, advanced = threading.Event(), threading.Event()

    def advance_worker():
        assert trigger.wait(5)
        owner.progress(chunks=7)
        advanced.set()

    class ObservedPath(type(Path())):
        """Real-file observer schedules a real worker after reconciliation lands."""
        fired = False

        def read_text(self, *args, **kwargs):
            text = super().read_text(*args, **kwargs)
            if self == path and not self.fired and json.loads(text)["accounting"]["reconciled_at"] is not None:
                self.fired = True
                trigger.set()
                assert advanced.wait(5)
                text = super().read_text(*args, **kwargs)
            return text

    thread = threading.Thread(target=advance_worker)
    thread.start()
    try:
        with _held_native_page("success") as (base, _received, _release):
            reader = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
            returned = await reconcile_run_costs(ObservedPath(path), reader)
        assert advanced.is_set()
        assert returned.accounting == _read(path).accounting
        assert returned.accounting.processed_chunks == 7
    finally:
        trigger.set()
        thread.join(timeout=5)
        owner.finish()


@pytest.mark.asyncio
@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg"}])
async def test_repeated_dead_owner_recovery_preserves_native_measurements(tmp_path: Path, models) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    initialize_accounted_run(path, summary, _accounting(summary).model_copy(update={"models": models}))
    with _held_native_page("success") as (base, _received, _release):
        reader = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
        reconciled = await reconcile_run_costs(path, reader)
    assert reconciled.accounting.costs is not None
    assert reconciled.accounting.costs.state == "incomplete"
    saved = path.read_bytes()
    interrupt_abandoned_accounting(path)
    assert path.read_bytes() == saved


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["coverage_complete", "gateway_attempt_policy_verified", "owner_interrupted"])
async def test_reconciliation_rechecks_all_coverage_inputs_before_saving(tmp_path: Path, field: str) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models={"semantic_kg": "kg"}, coverage_complete=True, coverage_notes=[], gateway_attempt_policy_verified=True)
    owner.finish()
    with _held_native_page("held_success") as (base, received, release):
        reader = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=5, total_timeout_s=6)
        pending = asyncio.create_task(reconcile_run_costs(path, reader))
        assert await asyncio.to_thread(received.wait, 3)
        changed = field == "owner_interrupted"
        update_run_accounting(path, lambda record: record.model_copy(update={field: changed}))
        release.set()
        result = await pending
    assert getattr(result.accounting, field) is changed
    assert result.accounting.costs is None
    assert result.accounting.reconciled_at is None


def test_human_coverage_note_does_not_determine_owner_lifecycle() -> None:
    record = _accounting(_summary()).model_copy(update={
        "models": {}, "coverage_notes": ["Worker process ended before a closed accounting checkpoint."],
    })
    assert record.owner_interrupted is False
    assert accounting_census(record).state == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg"}])
async def test_duplicate_constructor_cannot_hide_a_dead_owner(tmp_path: Path, models) -> None:
    path = tmp_path / "summary.json"
    summary = _summary()
    initialize_accounted_run(path, summary, _accounting(summary).model_copy(update={"models": models}))
    code = """
import sys
from pathlib import Path
from server.indexing.accounting import IndexAccountingOwner
from server.models.index import IndexRunSummary
def pause_at_initialization(frame, event, arg):
    if event == 'call' and frame.f_code.co_name == 'initialize_accounted_run':
        print('ready', flush=True)
        sys.stdin.readline()
    return pause_at_initialization
path = Path(sys.argv[1])
summary = IndexRunSummary.model_validate_json(path.read_text())
sys.settrace(pause_at_initialization)
try:
    IndexAccountingOwner(path, summary, config_json='{}', models=summary.accounting.models, coverage_complete=True, coverage_notes=[])
except ValueError as exc:
    if 'already initialized' in str(exc):
        sys.exit(23)
    raise
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 10) == "ready\n"
        assert not accounting_owner_alive(path)
        with _held_native_page("success") as (base, _received, _release):
            reader = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
            recovered = await reconcile_run_costs(path, reader)
        assert recovered.accounting.owner_interrupted is True
        assert recovered.accounting.costs.state == "incomplete"
    finally:
        _stdout, stderr = process.communicate(input="continue\n", timeout=10)
    assert process.returncode == 23, stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg"}])
@pytest.mark.parametrize("mode", ["success", "malformed"])
async def test_completion_invalidates_live_reconciliation_and_is_idempotent(tmp_path: Path, models, mode: str) -> None:
    path = tmp_path / "summary.json"
    owner = IndexAccountingOwner(path, _summary(), config_json="{}", models=models, coverage_complete=True, coverage_notes=[], gateway_attempt_policy_verified=True)
    try:
        with _held_native_page(mode) as (base, _received, release):
            release.set()
            reader = NativeSpendReader(base_url=base, api_key=SecretStr("synthetic-only"), request_timeout_s=2, total_timeout_s=3)
            live = await reconcile_run_costs(path, reader)
        assert live.accounting.reconciled_at is not None
        if mode == "success":
            assert live.accounting.costs.state == "pending"
        else:
            assert live.accounting.reconciliation_error is not None
        owner.finish()
        closed = _read(path).accounting
        assert closed.ended_at is not None
        assert closed.costs is None
        assert closed.reconciled_at is None
        assert closed.reconciliation_error is None
        saved = path.read_bytes()
        owner.finish()
        owner.finish(interrupted=True)
        assert path.read_bytes() == saved
    finally:
        owner.finish()


@pytest.mark.parametrize("models", [{}, {"semantic_kg": "kg", "figure_description": "figure"}])
@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("run_kind", ["index", "schema_proposal"])
def test_run_trace_parent_spans_lanes_and_actual_retained_threads(tmp_path: Path, models, interrupted: bool, run_kind: str) -> None:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "local"
    cfg.tracing.otel_export_enabled = False
    cfg.tracing.langfuse_enabled = False
    cfg.tracing.otel_service_name = f"owner-{tmp_path.name}-{interrupted}"
    exporter = InMemorySpanExporter()
    manager = get_observability_manager(cfg)
    manager.tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    path = tmp_path / "summary.json"
    summary = _summary().model_copy(update={"run_kind": run_kind})
    owner = IndexAccountingOwner(path, summary, config_json="{}", config=cfg, models=models, coverage_complete=True, coverage_notes=[])
    received, release = threading.Event(), threading.Event()
    header_lock = threading.Lock()
    carriers: list[dict[str, str]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            with header_lock:
                carriers.append(dict(self.headers))
                if len(carriers) == len(models):
                    received.set()
            assert release.wait(10)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    leases = {lane: scope.producer_started() for lane, scope in owner.scopes.items()}

    def send(lane):
        try:
            with httpx.Client(transport=CensusTransport(owner.scopes[lane])) as client:
                response = client.post(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", json={"model": models[lane]})
                assert response.status_code == 200
        finally:
            leases[lane].close()

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            pending = [workers.submit(send, lane) for lane in models]
            try:
                if pending:
                    assert received.wait(5)
                owner.finish(interrupted=interrupted)
                if pending:
                    assert accounting_owner_alive(path)
                    assert exporter.get_finished_spans() == ()
            finally:
                release.set()
            for future in pending:
                future.result(timeout=5)
        assert not accounting_owner_alive(path)
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        root = spans[0]
        assert root.name == f"ragweld.index.{run_kind}"
        assert root.attributes["http.route"] == (
            "/api/index/{corpus_id}/graph-schema/proposal" if run_kind == "schema_proposal" else "/api/index"
        )
        assert root.attributes["ragweld.run_id"] == "run-a"
        assert root.attributes["ragweld.repo_id"] == "corpus-a"
        expected = f"00-{root.context.trace_id:032x}-{root.context.span_id:016x}-01"
        assert all(headers["traceparent"] == expected for headers in carriers)
        assert len(carriers) == len(models)
        owner.finish()
        assert len(exporter.get_finished_spans()) == 1
    finally:
        release.set()
        for lease in leases.values():
            lease.close()
        owner.finish()
        server.shutdown()
        server.server_close()
        serving.join(timeout=3)
