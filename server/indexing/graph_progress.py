"""Owned extraction progress with serial, failure-visible run-summary persistence."""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from types import TracebackType

from server.indexing.extraction_checkpoint import (
    ExtractionPhase,
    ExtractionProgress,
    await_checkpoint_task,
)
from server.indexing.run_records import persist_graph_progress
from server.models.index import GraphExtractionTelemetry


class GraphProgressState:
    """Reduce official per-chunk transitions without treating selected work as dispatch."""

    def __init__(self, repo_id: str, run_id: str, extraction: GraphExtractionTelemetry):
        if extraction.outcome_version != "checkpoint_v1" or extraction.progress_owner_run_id != run_id:
            raise ValueError("Measured progress requires the checkpoint owner")
        self.repo_id = repo_id
        self.run_id = run_id
        self.extraction = extraction
        self.phases: dict[str, ExtractionPhase] = {}

    def apply(self, event: ExtractionProgress) -> None:
        if (event.repo_id, event.owner_run_id) != (self.repo_id, self.run_id):
            raise ValueError("Progress belongs to another corpus or run owner")
        if not math.isfinite(event.duration_s) or event.duration_s < 0:
            raise ValueError("Fresh extraction duration must be finite and nonnegative")
        current = self.extraction
        if event.sequence <= current.progress_sequence:
            return
        if event.sequence != current.progress_sequence + 1:
            raise ValueError("Progress sequence must be consecutive")
        previous = self.phases.get(event.cache_key)
        allowed: dict[ExtractionPhase | None, set[ExtractionPhase]] = {
            None: {"selected"}, "selected": {"admitted", "failed", "cancelled"},
            "admitted": {"dispatching", "reused", "failed", "cancelled"},
            "dispatching": {"succeeded", "failed", "cancelled"},
        }
        if event.phase not in allowed.get(previous, set()):
            raise ValueError(f"Invalid extraction progress transition: {previous} -> {event.phase}")
        values = current.model_dump()
        values["progress_sequence"] = event.sequence
        if event.phase == "selected":
            values["selected_chunks"] += 1
            values["unfinished_chunks"] += 1
        elif event.phase == "admitted":
            values["attempted_chunks"] += 1
        elif event.phase in {"succeeded", "reused", "failed", "cancelled"}:
            values["unfinished_chunks"] -= 1
            key = "succeeded_chunks" if event.phase == "reused" else f"{event.phase}_chunks"
            values[key] += 1
            if event.phase == "reused":
                values["reused_chunks"] += 1
            if previous == "dispatching":
                values["worker_seconds"] += event.duration_s
        validated = GraphExtractionTelemetry.model_validate(values)
        self.phases[event.cache_key] = event.phase
        # The run's invariant checker shares this owner-held telemetry object.
        for name in type(validated).model_fields:
            setattr(current, name, getattr(validated, name))


class GraphProgressOwner:
    """One synchronous callback queue, retained until every filesystem write settles."""

    def __init__(self, path: Path, repo_id: str, run_id: str, extraction: GraphExtractionTelemetry):
        self.path = path
        self.state = GraphProgressState(repo_id, run_id, extraction)
        self.queue: asyncio.Queue[ExtractionProgress | None] = asyncio.Queue()
        self.error: Exception | None = None
        self.closed = False
        self.writer = asyncio.create_task(self._write(), name=f"graph-progress:{run_id}")

    def __call__(self, event: ExtractionProgress) -> None:
        if self.closed:
            raise ValueError("Graph progress owner is closed")
        self.queue.put_nowait(event)

    async def __aenter__(self) -> GraphProgressOwner:
        return self

    async def __aexit__(self, _kind: type[BaseException] | None, error: BaseException | None,
                        _traceback: TracebackType | None) -> None:
        await self.close(primary_error=error)

    def failure_codes(self, primary_error: BaseException | None) -> list[str]:
        codes = ["progress_persistence_failure"] if self.error is not None else []
        if self.state.extraction.failed_chunks:
            codes.append("extraction_failure")
        elif (primary_error is not None and primary_error is not self.error
              and not isinstance(primary_error, asyncio.CancelledError)):
            codes.append("graph_build_or_promotion_failure")
        return codes

    async def _write(self) -> None:
        while True:
            event = await self.queue.get()
            if event is None:
                self.queue.task_done()
                if self.error is not None:
                    raise self.error
                return
            try:
                # Preserve all actual outcomes in memory even when persistence failed;
                # failure still refuses promotion and is surfaced by drain/close.
                self.state.apply(event)
                await asyncio.to_thread(
                    persist_graph_progress, self.path, repo_id=self.state.repo_id,
                    run_id=self.state.run_id, extraction=self.state.extraction.model_copy(deep=True),
                )
            except Exception as exc:
                if self.error is None:
                    self.error = exc
            finally:
                self.queue.task_done()

    async def drain(self) -> None:
        await await_checkpoint_task(asyncio.create_task(self.queue.join()))
        if self.error is not None:
            raise self.error

    async def close(self, *, primary_error: BaseException | None = None) -> None:
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(None)
        cancelled: asyncio.CancelledError | None = None
        try:
            # Progress persistence has different outcome precedence from the
            # checkpoint commit helper: retain the writer, but preserve an
            # operator cancellation delivered while closing an otherwise
            # successful body even if this writer also fails.
            while not self.writer.done():
                try:
                    await asyncio.shield(self.writer)
                except asyncio.CancelledError as exc:
                    if self.writer.cancelled():
                        raise
                    if cancelled is None:
                        cancelled = exc
            self.writer.result()
            if self.error is not None:
                raise self.error
        except BaseException as close_error:
            if primary_error is None:
                if cancelled is not None:
                    cancelled.add_note(f"Graph progress closure also failed: {close_error!r}")
                    raise cancelled from close_error
                raise
            # Keep the original error/cancellation as the run's outcome. The
            # retained writer error remains separately inspectable and coded.
            primary_error.add_note(f"Graph progress closure also failed: {close_error!r}")
            return
        if cancelled is not None:
            if primary_error is None:
                raise cancelled
            primary_error.add_note(f"Graph progress closure also received cancellation: {cancelled}")
