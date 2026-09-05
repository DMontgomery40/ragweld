"""Aggregate run census; native LiteLLM remains the per-request spend ledger."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

import httpx
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

Lane = Literal[
    "embedding", "semantic_kg", "figure_description", "schema_proposal",
    "index_embeddings", "retrieval_embeddings", "cache_embeddings",
]
Outcome = Literal["completed", "failed", "uncertain"]


@dataclass(frozen=True)
class RunIdentity:
    session_id: str
    corpus_id: str
    lane: Lane

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", self.session_id):
            raise ValueError("Invalid session identity")
        if not 1 <= len(self.corpus_id) <= 256:
            raise ValueError("Invalid corpus identity")
        if self.lane not in {"embedding", "semantic_kg", "figure_description", "schema_proposal",
                            "index_embeddings", "retrieval_embeddings", "cache_embeddings"}:
            raise ValueError("Unsupported cost lane")


def native_request_headers(identity: RunIdentity) -> dict[str, str]:
    """Native request correlation, independent of tracing or durable census coverage."""
    metadata = json.dumps(
        {"run_id": identity.session_id, "corpus_id": identity.corpus_id, "lane": identity.lane},
        separators=(",", ":"), sort_keys=True,
    )
    return {
        "x-litellm-session-id": identity.session_id,
        # Native trace-id takes precedence over session-id; both name this operation.
        "x-litellm-trace-id": identity.session_id,
        "x-litellm-spend-logs-metadata": metadata,
        "langfuse_session_id": identity.session_id,
        "langfuse_trace_metadata": metadata,
    }


@dataclass(frozen=True)
class CensusCheckpoint:
    """A durable admission census, not a count reconstructed from spend rows.

    ``started_requests`` records intent immediately before transport dispatch.
    A crash or unacknowledged persistence in that unavoidable gap can leave an
    admitted-but-unsent request uncertain. Counters never roll back. Completed
    includes all settled attempts; failed and uncertain are disjoint subsets.
    """

    identity: RunIdentity
    revision: int
    started_requests: int
    completed_requests: int
    failed_requests: int
    uncertain_requests: int
    inflight: int
    active_producers: int
    owner_finished: bool
    dispatch_enabled: bool
    state: Literal["open", "closed", "interrupted"]


class CensusPersistenceError(RuntimeError):
    """The checkpoint was not acknowledged; this scope can never claim closure."""


class CensusDispatchDisabledError(RuntimeError):
    """No additional request/producer may start in this scope."""


# Keep the reviewed prototype's import/catch interface while following repo naming.
CensusDispatchDisabled = CensusDispatchDisabledError


class RunCensusScope:
    """Thread-safe ownership plus aggregate dispatch accounting.

    ``persist`` must atomically replace the owner's durable summary and return only
    after its durability requirements succeed. It must not call back into this scope.
    The lock is held across this callback to order checkpoints across worker threads.
    A closed census proves local quiescence, not complete native spend accounting.
    """

    def __init__(
        self, identity: RunIdentity, persist: Callable[[CensusCheckpoint], None],
        *, trace_headers: Mapping[str, str] | None = None,
    ):
        self._identity = identity
        self._persist = persist
        # Capture once on the owning thread; worker threads must not acquire an
        # unrelated request's context when the actual HTTP dispatch happens.
        carrier: dict[str, str] = {}
        if trace_headers is None:
            TraceContextTextMapPropagator().inject(carrier)
        else:
            carrier.update({key.lower(): value for key, value in trace_headers.items() if key.lower() in {"traceparent", "tracestate"}})
        self._trace_headers = carrier
        self._lock = threading.Lock()
        self._revision = 0
        self._started = self._completed = self._failed = self._uncertain = self._inflight = 0
        self._active_producers = 0
        self._owner_finished = False
        self._dispatch_enabled = True
        self._state: Literal["open", "closed", "interrupted"] = "open"
        with self._lock:
            self._checkpoint_locked()

    @property
    def identity(self) -> RunIdentity:
        return self._identity

    def _snapshot_locked(self) -> CensusCheckpoint:
        return CensusCheckpoint(
            identity=self.identity,
            revision=self._revision,
            started_requests=self._started,
            completed_requests=self._completed,
            failed_requests=self._failed,
            uncertain_requests=self._uncertain,
            inflight=self._inflight,
            active_producers=self._active_producers,
            owner_finished=self._owner_finished,
            dispatch_enabled=self._dispatch_enabled,
            state=self._state,
        )

    def snapshot(self) -> CensusCheckpoint:
        with self._lock:
            return self._snapshot_locked()

    def _checkpoint_locked(self) -> None:
        if (
            self._state == "open"
            and self._owner_finished
            and self._active_producers == 0
            and self._inflight == 0
        ):
            self._state = "closed"
            self._dispatch_enabled = False
        try:
            self._persist(self._snapshot_locked())
        except Exception as exc:
            # Never recover this process-local census to closed after a missed
            # checkpoint. Another successful write may preserve later observations.
            self._state = "interrupted"
            self._dispatch_enabled = False
            self._revision += 1
            try:
                self._persist(self._snapshot_locked())
            except Exception:
                pass
            raise CensusPersistenceError(
                "Run census checkpoint was not acknowledged; admitted requests may be unsent and uncertain"
            ) from exc

    def _require_dispatch_locked(self) -> None:
        if (
            self._state != "open"
            or not self._dispatch_enabled
            or (self._owner_finished and self._active_producers == 0)
        ):
            raise CensusDispatchDisabled("Run census does not permit additional dispatch")

    def producer_started(self) -> ProducerLease:
        """Register before scheduling; close if scheduling fails or actual work finishes."""
        with self._lock:
            self._require_dispatch_locked()
            self._active_producers += 1
            self._revision += 1
            try:
                self._checkpoint_locked()
            except CensusPersistenceError:
                # No lease was handed to a caller, so no worker was scheduled.
                self._active_producers -= 1
                self._revision += 1
                self._save_interrupted_observations_locked()
                raise
            return ProducerLease(self)

    def start_attempt(self) -> RequestAttempt:
        """Durably admit one outbound HTTP attempt before its transport is called."""
        with self._lock:
            self._require_dispatch_locked()
            self._started += 1
            self._inflight += 1
            self._revision += 1
            try:
                self._checkpoint_locked()
            except CensusPersistenceError:
                # No transport was called, but its durable admission may already
                # exist. Keep counters monotonic and fail closed as uncertain.
                self._inflight -= 1
                self._completed += 1
                self._uncertain += 1
                self._revision += 1
                self._save_interrupted_observations_locked()
                raise
            return RequestAttempt(self)

    def _save_interrupted_observations_locked(self) -> None:
        try:
            self._persist(self._snapshot_locked())
        except Exception:
            pass

    def finish_owner(self) -> None:
        with self._lock:
            if self._owner_finished:
                return
            self._owner_finished = True
            self._revision += 1
            self._checkpoint_locked()

    def disable_dispatch(self) -> None:
        """Cancellation can stop future sends without forgetting retained workers."""
        with self._lock:
            if not self._dispatch_enabled:
                return
            self._dispatch_enabled = False
            self._revision += 1
            self._checkpoint_locked()

    def mark_interrupted(self) -> None:
        with self._lock:
            self._state = "interrupted"
            self._dispatch_enabled = False
            self._revision += 1
            self._checkpoint_locked()

    def apply_headers(self, request: httpx.Request) -> None:
        if "traceparent" not in request.headers:
            request.headers.update(self._trace_headers)
        request.headers.update(native_request_headers(self.identity))


class ProducerLease:
    def __init__(self, scope: RunCensusScope):
        self._scope = scope
        self._closed = False

    def close(self) -> None:
        with self._scope._lock:
            if self._closed:
                return
            self._closed = True
            self._scope._active_producers -= 1
            self._scope._revision += 1
            self._scope._checkpoint_locked()


class RequestAttempt:
    def __init__(self, scope: RunCensusScope):
        self._scope = scope
        self._finished = False

    def finish(self, outcome: Outcome) -> None:
        with self._scope._lock:
            if self._finished:
                return
            self._finished = True
            self._scope._inflight -= 1
            self._scope._completed += 1
            if outcome == "failed":
                self._scope._failed += 1
            elif outcome == "uncertain":
                self._scope._uncertain += 1
            self._scope._revision += 1
            self._scope._checkpoint_locked()

    def preserve_uncertain_exception(self) -> None:
        """Record uncertainty without replacing the transport/cancellation exception."""
        try:
            self.finish("uncertain")
        except CensusPersistenceError:
            pass


class CensusSyncStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, attempt: RequestAttempt, failed: bool):
        self._stream = stream
        self._attempt = attempt
        self._failed = failed
        self._exhausted = False

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._stream
            self._exhausted = True
        except BaseException:
            self._attempt.preserve_uncertain_exception()
            raise

    def close(self) -> None:
        try:
            self._stream.close()
        except BaseException:
            self._attempt.preserve_uncertain_exception()
            raise
        self._attempt.finish(
            ("failed" if self._failed else "completed") if self._exhausted else "uncertain"
        )


class CensusAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, attempt: RequestAttempt, failed: bool):
        self._stream = stream
        self._attempt = attempt
        self._failed = failed
        self._exhausted = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self._stream:
                yield chunk
            self._exhausted = True
        except BaseException:
            self._attempt.preserve_uncertain_exception()
            raise

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        except BaseException:
            self._attempt.preserve_uncertain_exception()
            raise
        self._attempt.finish(
            ("failed" if self._failed else "completed") if self._exhausted else "uncertain"
        )


class CensusTransport(httpx.BaseTransport):
    def __init__(self, scope: RunCensusScope, transport: httpx.BaseTransport | None = None):
        self._scope = scope
        self._transport = transport if transport is not None else httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            return self._transport.handle_request(request)
        self._scope.apply_headers(request)
        attempt = self._scope.start_attempt()
        try:
            response = self._transport.handle_request(request)
        except BaseException:
            attempt.preserve_uncertain_exception()
            raise
        assert isinstance(response.stream, httpx.SyncByteStream)
        response.stream = CensusSyncStream(response.stream, attempt, response.status_code >= 400)
        return response

    def close(self) -> None:
        self._transport.close()


class CensusAsyncTransport(httpx.AsyncBaseTransport):
    def __init__(self, scope: RunCensusScope, transport: httpx.AsyncBaseTransport | None = None):
        self._scope = scope
        self._transport = transport if transport is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            return await self._transport.handle_async_request(request)
        self._scope.apply_headers(request)
        attempt = self._scope.start_attempt()
        try:
            response = await self._transport.handle_async_request(request)
        except BaseException:
            attempt.preserve_uncertain_exception()
            raise
        assert isinstance(response.stream, httpx.AsyncByteStream)
        response.stream = CensusAsyncStream(response.stream, attempt, response.status_code >= 400)
        return response

    async def aclose(self) -> None:
        await self._transport.aclose()
