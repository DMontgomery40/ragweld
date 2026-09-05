from __future__ import annotations

import asyncio
import contextlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from server.indexing.run_records import (
    initialize_run_accounting,
    persist_request_census,
    write_run_summary,
)
from server.models.index import IndexRunSummary
from server.models.run_accounting import IndexRunAccounting, RunRequestCensus
from server.observability.run_census import (
    CensusAsyncTransport,
    CensusCheckpoint,
    CensusDispatchDisabled,
    CensusPersistenceError,
    CensusTransport,
    RunCensusScope,
    RunIdentity,
)


class FileCheckpointStore:
    def __init__(self, path: Path):
        self.path = path
        self.history: list[CensusCheckpoint] = []
        self.additional_fsync_target: Path | None = None

    def __call__(self, checkpoint: CensusCheckpoint) -> None:
        validated = RunRequestCensus.model_validate(asdict(checkpoint))
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as output:
            output.write(validated.model_dump_json())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)
        directory = os.open(self.path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if self.additional_fsync_target is not None:
            with self.additional_fsync_target.open("rb") as target:
                os.fsync(target.fileno())
        self.history.append(checkpoint)

    def read(self) -> CensusCheckpoint:
        data = RunRequestCensus.model_validate_json(self.path.read_text()).model_dump()
        return CensusCheckpoint(identity=RunIdentity(**data.pop("identity")), **data)


class IndexSummaryCheckpointStore(FileCheckpointStore):
    """Exercise the real run boundary and filesystem owner for every checkpoint."""

    def __init__(self, path: Path):
        super().__init__(path)
        started = datetime.now(UTC)
        write_run_summary(path, IndexRunSummary(
            run_id="run-123", repo_id="synthetic", status="indexing", started_at=started,
        ))
        initialize_run_accounting(path, IndexRunAccounting(
            session_id="run-123", corpus_id="synthetic", started_at=started,
            config_fingerprint="a" * 64, models={"semantic_kg": "fixture-model"},
        ))

    def __call__(self, checkpoint: CensusCheckpoint) -> None:
        persist_request_census(self.path, RunRequestCensus.model_validate(asdict(checkpoint)))
        if self.additional_fsync_target is not None:
            with self.additional_fsync_target.open("rb") as target:
                os.fsync(target.fileno())
        self.history.append(checkpoint)

    def read(self) -> CensusCheckpoint:
        summary = IndexRunSummary.model_validate_json(self.path.read_text())
        assert summary.accounting is not None
        data = summary.accounting.census["semantic_kg"].model_dump()
        return CensusCheckpoint(identity=RunIdentity(**data.pop("identity")), **data)


@pytest.fixture(params=[FileCheckpointStore, IndexSummaryCheckpointStore], ids=["checkpoint", "index-summary"])
def accounting(tmp_path, request):
    store = request.param(tmp_path / "summary.json")
    scope = RunCensusScope(
        RunIdentity(session_id="run-123", corpus_id="synthetic", lane="semantic_kg"), store
    )
    return scope, store


@pytest.fixture
def gateway(accounting):
    _, store = accounting
    received = []
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            with lock:
                received.append((self.path, dict(self.headers), store.read()))
                number = len(received)
            if self.path == "/held":
                entered.set()
                release.wait(5)
            if self.path == "/disconnect":
                self.close_connection = True
                return
            if self.path == "/partial":
                self.send_response(200)
                self.send_header("Content-Length", "20")
                self.end_headers()
                self.wfile.write(b"short")
                self.wfile.flush()
                self.close_connection = True
                return
            if self.path == "/stream":
                self.send_response(200)
                self.send_header("Content-Length", "10")
                self.end_headers()
                self.wfile.write(b"first")
                self.wfile.flush()
                entered.set()
                release.wait(5)
                with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                    self.wfile.write(b"last!")
                return
            status = 503 if self.path == "/failure" else 200
            if self.path == "/v1/chat/completions":
                status = 429 if number == 1 else 200
                body = json.dumps(
                    {"error": {"message": "retry once", "type": "rate_limit_error"}}
                    if status == 429
                    else {
                        "id": "fixture-completion",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "fixture-model",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    }
                ).encode()
            else:
                body = b"ok"
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", received, entered, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def assert_closed(scope, store, *, started, completed=0, failed=0, uncertain=0):
    checkpoint = store.read()
    assert checkpoint == scope.snapshot()
    assert checkpoint.state == "closed"
    assert (checkpoint.started_requests, checkpoint.completed_requests, checkpoint.failed_requests, checkpoint.uncertain_requests) == (
        started, completed + failed + uncertain, failed, uncertain
    )
    assert checkpoint.inflight == checkpoint.active_producers == 0
    assert checkpoint.owner_finished and not checkpoint.dispatch_enabled


@pytest.mark.parametrize("explicit", [True, False])
def test_trace_context_is_copied_across_threads_and_native_session_is_canonical(accounting, gateway, explicit):
    from opentelemetry import trace
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    _, store = accounting
    base, received, _, _ = gateway
    carrier = {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01", "tracestate": "fixture=owned"}
    context = TraceContextTextMapPropagator().extract(carrier)
    with trace.use_span(trace.get_current_span(context)):
        scope = RunCensusScope(
            RunIdentity("run-123", "synthetic", "semantic_kg"), store,
            **({"trace_headers": carrier} if explicit else {}),
        )
    carrier["traceparent"] = "mutated-after-construction"
    other_parent = "00-" + "3" * 32 + "-" + "4" * 16 + "-01"
    with httpx.Client(transport=CensusTransport(scope), timeout=5) as client:
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(client.post, base + "/ok").result().status_code == 200
        assert client.post(base + "/ok", headers={"traceparent": other_parent, "langfuse_session_id": "wrong"}).status_code == 200
    scope.finish_owner()
    first, second = [headers for _, headers, _ in received]
    assert first["traceparent"] == "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
    assert first["tracestate"] == "fixture=owned"
    assert second["traceparent"] == other_parent
    assert "tracestate" not in second
    for headers in (first, second):
        assert headers["langfuse_session_id"] == "run-123"
        assert json.loads(headers["langfuse_trace_metadata"]) == {
            "run_id": "run-123", "corpus_id": "synthetic", "lane": "semantic_kg",
        }


def test_identity_and_checkpoint_are_immutable_and_validated(accounting):
    scope, _ = accounting
    with pytest.raises(FrozenInstanceError):
        scope.identity.session_id = "other"
    with pytest.raises(AttributeError):
        scope.identity = RunIdentity(session_id="other", corpus_id="x", lane="embedding")
    with pytest.raises(ValueError):
        RunIdentity(session_id="x", corpus_id="x", lane="unbounded-user-value")
    with pytest.raises(ValidationError):
        RunRequestCensus.model_validate({**asdict(scope.snapshot()), "started_requests": 2})


def test_sync_concurrent_requests_durable_before_dispatch_and_exact_headers(accounting, gateway):
    scope, store = accounting
    base, received, _, _ = gateway
    traceparent = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    with httpx.Client(transport=CensusTransport(scope), timeout=5) as client:
        assert client.get(base).status_code == 200
        producer = scope.producer_started()
        with ThreadPoolExecutor(max_workers=4) as workers:
            responses = list(workers.map(lambda _: client.post(base + "/ok", headers={
                "traceparent": traceparent,
                "x-litellm-session-id": "incorrect",
                "x-litellm-trace-id": "incorrect",
                "x-litellm-spend-logs-metadata": '{"prompt":"must disappear"}',
            }), range(8)))
        producer.close()
        assert all(response.status_code == 200 for response in responses)
        assert client.post(base + "/failure").status_code == 503
        scope.finish_owner()
        with pytest.raises(CensusDispatchDisabled):
            client.post(base + "/ok")
    assert len(received) == 9
    for index, (_, headers, checkpoint) in enumerate(received):
        assert checkpoint.state == "open" and checkpoint.started_requests >= index + 1
        assert headers["x-litellm-session-id"] == headers["x-litellm-trace-id"] == "run-123"
        assert json.loads(headers["x-litellm-spend-logs-metadata"]) == {
            "run_id": "run-123", "corpus_id": "synthetic", "lane": "semantic_kg"
        }
        if index < 8:
            assert headers["traceparent"] == traceparent
    assert_closed(scope, store, started=9, completed=8, failed=1)


def test_registered_worker_can_continue_after_owner_finishes(accounting, gateway):
    scope, store = accounting
    base, received, _, _ = gateway
    ready = threading.Event()
    producer = scope.producer_started()

    def work():
        try:
            assert ready.wait(5)
            with httpx.Client(transport=CensusTransport(scope)) as client:
                assert client.post(base + "/ok").status_code == 200
        finally:
            producer.close()

    with ThreadPoolExecutor(max_workers=1) as workers:
        task = workers.submit(work)
        scope.finish_owner()
        assert store.read().state == "open"
        assert store.read().active_producers == 1
        ready.set()
        task.result(timeout=5)
    assert len(received) == 1
    assert_closed(scope, store, started=1, completed=1)
    producer.close()  # idempotent, not a negative counter


def test_real_worker_scheduling_failure_releases_registered_producer(accounting):
    scope, store = accounting
    workers = ThreadPoolExecutor(max_workers=1)
    workers.shutdown()
    producer = scope.producer_started()
    try:
        with pytest.raises(RuntimeError, match="cannot schedule"):
            workers.submit(lambda: None)
    finally:
        producer.close()
    scope.finish_owner()
    assert_closed(scope, store, started=0)


@pytest.mark.asyncio
async def test_async_cancelled_held_request_is_uncertain_and_retained_producer_blocks_closure(accounting, gateway):
    scope, store = accounting
    base, received, entered, release = gateway
    producer = scope.producer_started()
    async with httpx.AsyncClient(transport=CensusAsyncTransport(scope), timeout=5) as client:
        task = asyncio.create_task(client.post(base + "/held"))
        assert await asyncio.to_thread(entered.wait, 5)
        assert store.read().inflight == 1
        scope.disable_dispatch()
        scope.finish_owner()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert store.read().uncertain_requests == 1
        assert store.read().state == "open"
        with pytest.raises(CensusDispatchDisabled):
            await client.post(base + "/ok")
        release.set()
    producer.close()
    assert len(received) == 1
    assert_closed(scope, store, started=1, uncertain=1)


@pytest.mark.asyncio
async def test_async_sdk_retries_count_each_outbound_attempt(accounting, gateway):
    scope, store = accounting
    base, received, _, _ = gateway
    async with AsyncOpenAI(
        api_key="synthetic-only",
        base_url=base + "/v1",
        max_retries=1,
        http_client=httpx.AsyncClient(transport=CensusAsyncTransport(scope)),
    ) as client:
        result = await client.chat.completions.create(
            model="fixture-model", messages=[{"role": "user", "content": "synthetic"}]
        )
    assert result.choices[0].message.content == "ok"
    scope.finish_owner()
    assert len(received) == 2
    assert_closed(scope, store, started=2, completed=1, failed=1)


@pytest.mark.parametrize("mode", ["partial", "abandoned", "timeout", "disconnect"])
def test_sync_incomplete_responses_are_uncertain(accounting, gateway, mode):
    scope, store = accounting
    base, received, _, release = gateway
    with httpx.Client(transport=CensusTransport(scope), timeout=0.1) as client:
        if mode in {"partial", "disconnect"}:
            with pytest.raises(httpx.RemoteProtocolError):
                client.post(base + "/" + mode)
        elif mode == "timeout":
            with pytest.raises(httpx.ReadTimeout):
                client.post(base + "/held")
        else:
            with client.stream("POST", base + "/stream") as response:
                iterator = response.iter_bytes()
                assert next(iterator) == b"first"
                assert scope.snapshot().inflight == 1
            release.set()
    scope.finish_owner()
    assert len(received) == 1
    assert_closed(scope, store, started=1, uncertain=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["partial", "abandoned", "timeout", "disconnect"])
async def test_async_incomplete_responses_are_uncertain(accounting, gateway, mode):
    scope, store = accounting
    base, received, _, release = gateway
    async with httpx.AsyncClient(transport=CensusAsyncTransport(scope), timeout=0.1) as client:
        if mode in {"partial", "disconnect"}:
            with pytest.raises(httpx.RemoteProtocolError):
                await client.post(base + "/" + mode)
        elif mode == "timeout":
            with pytest.raises(httpx.ReadTimeout):
                await client.post(base + "/held")
        else:
            async with client.stream("POST", base + "/stream") as response:
                iterator = response.aiter_bytes()
                assert await anext(iterator) == b"first"
                assert scope.snapshot().inflight == 1
            release.set()
    scope.finish_owner()
    assert len(received) == 1
    assert_closed(scope, store, started=1, uncertain=1)


@pytest.mark.parametrize("transition", ["dispatch", "producer", "closure"])
def test_real_filesystem_write_failure_interrupts_and_cannot_send(accounting, gateway, transition):
    scope, store = accounting
    base, received, _, _ = gateway
    original = store.path
    directory = original.parent / "cannot-replace-directory"
    directory.mkdir()
    store.path = directory
    with pytest.raises(CensusPersistenceError):
        if transition == "dispatch":
            with httpx.Client(transport=CensusTransport(scope)) as client:
                client.post(base + "/ok")
        elif transition == "producer":
            scope.producer_started()
        else:
            scope.finish_owner()
    assert scope.snapshot().state == "interrupted"
    assert scope.snapshot().active_producers == 0
    assert scope.snapshot().started_requests == (1 if transition == "dispatch" else 0)
    assert scope.snapshot().uncertain_requests == (1 if transition == "dispatch" else 0)
    assert not received
    store.path = original
    scope.mark_interrupted()
    scope.finish_owner()
    assert store.read().state == "interrupted"
    with pytest.raises(CensusDispatchDisabled):
        scope.start_attempt()


def test_reloaded_open_checkpoint_never_implies_completion(accounting):
    scope, store = accounting
    producer = scope.producer_started()
    scope.start_attempt()
    loaded = store.read()
    assert loaded.state == "open" and loaded.inflight == loaded.active_producers == 1
    scope.mark_interrupted()
    scope.finish_owner()
    producer.close()
    assert store.read().state == "interrupted"
    assert store.read().inflight == 1


def test_initial_checkpoint_failure_never_returns_a_dispatch_scope(tmp_path):
    directory = tmp_path / "summary-is-directory"
    directory.mkdir()
    store = FileCheckpointStore(directory)
    with pytest.raises(CensusPersistenceError):
        RunCensusScope(RunIdentity(session_id="x", corpus_id="x", lane="embedding"), store)
    assert directory.is_dir()


@pytest.mark.asyncio
async def test_owner_finishes_after_headers_but_census_waits_for_full_body_close(accounting, gateway):
    scope, store = accounting
    base, _, _, release = gateway
    async with httpx.AsyncClient(transport=CensusAsyncTransport(scope), timeout=5) as client:
        async with client.stream("POST", base + "/stream") as response:
            scope.finish_owner()
            assert store.read().state == "open" and store.read().inflight == 1
            release.set()
            assert await response.aread() == b"firstlast!"
        assert_closed(scope, store, started=1, completed=1)


def test_late_response_stays_interrupted_after_an_accounting_failure(accounting, gateway):
    scope, store = accounting
    base, _, _, release = gateway
    with httpx.Client(transport=CensusTransport(scope)) as client:
        with client.stream("POST", base + "/stream") as response:
            scope.mark_interrupted()
            scope.finish_owner()
            release.set()
            assert response.read() == b"firstlast!"
    checkpoint = store.read()
    assert checkpoint.state == "interrupted"
    assert checkpoint.started_requests == checkpoint.completed_requests == 1
    assert checkpoint.inflight == 0


@pytest.mark.asyncio
async def test_shielded_real_worker_retains_scope_after_awaiting_owner_is_cancelled(accounting, gateway):
    scope, store = accounting
    base, _, entered, release = gateway
    producer = scope.producer_started()

    def blocking_work():
        try:
            with httpx.Client(transport=CensusTransport(scope), timeout=5) as client:
                assert client.post(base + "/held").status_code == 200
        finally:
            producer.close()  # the actual thread releases ownership

    worker = asyncio.create_task(asyncio.to_thread(blocking_work))

    async def await_worker():
        await asyncio.shield(worker)

    owner = asyncio.create_task(await_worker())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        scope.disable_dispatch()
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        scope.finish_owner()
        checkpoint = store.read()
        assert checkpoint.state == "open"
        assert checkpoint.inflight == checkpoint.active_producers == 1
    finally:
        release.set()
        await worker
    assert_closed(scope, store, started=1, completed=1)


@pytest.mark.parametrize("transition", ["dispatch", "closure"])
def test_replaced_but_unacknowledged_checkpoint_escalates_to_interrupted(accounting, gateway, transition):
    scope, store = accounting
    base, received, _, _ = gateway
    # A real fsync on this character device fails after the summary was replaced.
    # No callback/transport monkeypatching or fabricated provider response.
    store.additional_fsync_target = Path("/dev/null")
    with pytest.raises(CensusPersistenceError):
        if transition == "dispatch":
            with httpx.Client(transport=CensusTransport(scope)) as client:
                client.post(base + "/ok")
        else:
            scope.finish_owner()
    checkpoint = store.read()
    assert checkpoint == scope.snapshot()
    assert checkpoint.state == "interrupted" and not checkpoint.dispatch_enabled
    assert checkpoint.inflight == 0
    assert checkpoint.started_requests == checkpoint.uncertain_requests == (
        1 if transition == "dispatch" else 0
    )
    assert not received
    if isinstance(store, IndexSummaryCheckpointStore):
        summary = IndexRunSummary.model_validate_json(store.path.read_text())
        assert summary.accounting is not None
        assert summary.accounting.ended_at is None
        assert summary.accounting.census["semantic_kg"].state == "interrupted"
