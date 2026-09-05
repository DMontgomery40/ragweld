"""Atomic updates to existing index summaries, including durable cost checkpoints."""

from __future__ import annotations

import fcntl
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from server.models.index import GraphExtractionTelemetry, IndexRunSummary
from server.models.run_accounting import (
    CostLane,
    IndexRunAccounting,
    RunCostIdentity,
    RunRequestCensus,
)

_GRAPH_PROGRESS_FIELDS = frozenset({
    "outcome_version", "progress_owner_run_id", "progress_sequence", "selected_chunks",
    "attempted_chunks", "succeeded_chunks", "failed_chunks", "reused_chunks",
    "cancelled_chunks", "unfinished_chunks", "worker_seconds",
})


@contextmanager
def _locked_summary(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A stable lock inode, separate from the summary inode replaced atomically.
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _write_locked(path: Path, summary: IndexRunSummary) -> None:
    validated = IndexRunSummary.model_validate(summary.model_dump(mode="json", by_alias=True))
    fd, temporary = tempfile.mkstemp(prefix=".summary-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(validated.model_dump_json(by_alias=True, exclude_none=False, indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_locked(path: Path) -> IndexRunSummary:
    return IndexRunSummary.model_validate_json(path.read_text(encoding="utf-8"))


def write_run_summary(path: Path, summary: IndexRunSummary) -> None:
    """Persist run status without overwriting newer accounting or graph progress."""
    with _locked_summary(path):
        if path.exists():
            previous = _read_locked(path)
            if (previous.run_id, previous.repo_id) != (summary.run_id, summary.repo_id):
                raise ValueError("Cannot replace another run's summary")
            if previous.accounting is not None:
                summary = summary.model_copy(update={"accounting": previous.accounting})
            prior_graph = previous.graph_metadata
            if prior_graph is not None and prior_graph.extraction.outcome_version == "checkpoint_v1":
                graph = summary.graph_metadata
                if graph is None:
                    summary = summary.model_copy(update={"graph_metadata": prior_graph})
                elif (graph.extraction.outcome_version != "checkpoint_v1"
                      or graph.extraction.progress_sequence < prior_graph.extraction.progress_sequence):
                    extraction = graph.extraction.model_copy(update=prior_graph.extraction.model_dump(
                        include=set(_GRAPH_PROGRESS_FIELDS),
                    ))
                    summary = summary.model_copy(update={
                        "graph_metadata": graph.model_copy(update={"extraction": extraction}),
                    })
        _write_locked(path, summary)


def persist_graph_progress(
    path: Path, *, repo_id: str, run_id: str, extraction: GraphExtractionTelemetry,
) -> None:
    """Update only outcome fields under the shared accounting/status record lock."""
    extraction = GraphExtractionTelemetry.model_validate(extraction.model_dump())
    if extraction.outcome_version != "checkpoint_v1" or extraction.progress_owner_run_id != run_id:
        raise ValueError("Graph progress must name its checkpoint run owner")
    with _locked_summary(path):
        summary = _read_locked(path)
        if (summary.repo_id, summary.run_id) != (repo_id, run_id):
            raise ValueError("Graph progress belongs to another run")
        graph = summary.graph_metadata
        if graph is None or graph.extraction.progress_owner_run_id != run_id:
            raise ValueError("Graph progress owner was not initialized in the run summary")
        if extraction.progress_sequence <= graph.extraction.progress_sequence:
            return
        updated = graph.extraction.model_copy(update=extraction.model_dump(include=set(_GRAPH_PROGRESS_FIELDS)))
        _write_locked(path, summary.model_copy(update={
            "graph_metadata": graph.model_copy(update={"extraction": updated}),
        }))


def initialize_run_accounting(path: Path, accounting: IndexRunAccounting) -> None:
    """Require an existing run record, and acknowledge the initial open census."""
    with _locked_summary(path):
        summary = _read_locked(path)
        if (summary.run_id, summary.repo_id) != (accounting.session_id, accounting.corpus_id):
            raise ValueError("Accounting identity differs from the persisted run")
        if summary.accounting is not None:
            raise ValueError("Run accounting is already initialized")
        _write_locked(path, summary.model_copy(update={"accounting": accounting}))


def initial_request_census(accounting: IndexRunAccounting, lane: CostLane) -> RunRequestCensus:
    return RunRequestCensus(
        identity=RunCostIdentity(session_id=accounting.session_id, corpus_id=accounting.corpus_id, lane=lane),
        revision=0, started_requests=0, completed_requests=0, failed_requests=0, uncertain_requests=0,
        inflight=0, active_producers=0, owner_finished=False, dispatch_enabled=True, state="open",
    )


def initialize_accounted_run(
    path: Path, summary: IndexRunSummary, accounting: IndexRunAccounting, *, owner_lock: TextIO | None = None,
) -> None:
    """Publish owner identity and all zero-lane checkpoints in one durable write."""
    if (summary.run_id, summary.repo_id) != (accounting.session_id, accounting.corpus_id):
        raise ValueError("Accounting identity differs from the run")
    if accounting.census or accounting.ended_at is not None:
        raise ValueError("Owner initialization requires fresh accounting")
    initialized = accounting.model_copy(update={
        "census": {lane: initial_request_census(accounting, lane) for lane in accounting.models},
    })
    with _locked_summary(path):
        if path.exists():
            previous = _read_locked(path)
            if (previous.run_id, previous.repo_id) != (summary.run_id, summary.repo_id):
                raise ValueError("Cannot replace another run's summary")
            if previous.accounting is not None:
                raise ValueError("Run accounting is already initialized")
        # Reject duplicates before claiming liveness. Recovery checks this same
        # summary lock, so it cannot mistake a rejected constructor for an owner.
        if owner_lock is not None:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _write_locked(path, summary.model_copy(update={"accounting": initialized}))


def update_run_accounting(
    path: Path, update: Callable[[IndexRunAccounting], IndexRunAccounting]
) -> IndexRunAccounting:
    """Serialize a read/modify/write and propagate failure to its dispatch owner."""
    with _locked_summary(path):
        summary = _read_locked(path)
        previous = summary.accounting
        if previous is None:
            raise ValueError("Run accounting has not been initialized")
        updated = IndexRunAccounting.model_validate(
            update(previous.model_copy(deep=True)).model_dump(mode="json")
        )
        for field in ("session_id", "corpus_id", "started_at", "config_fingerprint", "gateway_base_url", "models", "estimate"):
            if getattr(updated, field) != getattr(previous, field):
                raise ValueError(f"Cannot change immutable run accounting field {field}")
        if updated != previous:
            _write_locked(path, summary.model_copy(update={"accounting": updated}))
        return updated


def persist_request_census(path: Path, checkpoint: RunRequestCensus) -> None:
    """Store one lane checkpoint; reject stale snapshots and cross-run writes."""
    def update(accounting: IndexRunAccounting) -> IndexRunAccounting:
        identity = checkpoint.identity
        if (identity.session_id, identity.corpus_id) != (accounting.session_id, accounting.corpus_id):
            raise ValueError("Census does not belong to this run")
        if identity.lane not in accounting.models:
            raise ValueError("Census lane was not declared before the run")
        previous = accounting.census.get(identity.lane)
        if previous is not None:
            if checkpoint == previous:
                return accounting
            if checkpoint.revision <= previous.revision or (
                checkpoint.revision != previous.revision + 1 and checkpoint.state != "interrupted"
            ):
                raise ValueError("Census revision is not the next checkpoint")
            if any(
                getattr(checkpoint, name) < getattr(previous, name)
                for name in ("started_requests", "completed_requests", "failed_requests", "uncertain_requests")
            ):
                raise ValueError("Census counters cannot move backwards")
            if previous.state != "open" and checkpoint.state != "interrupted":
                raise ValueError("A terminal census cannot be reopened or declared complete again")
        elif checkpoint.revision != 0 and checkpoint.state != "interrupted":
            raise ValueError("Initial census revision must be zero")
        census = {**accounting.census, identity.lane: checkpoint}
        ended_at = None
        if set(census) == set(accounting.models) and all(item.state == "closed" for item in census.values()):
            ended_at = datetime.now(UTC)
        return accounting.model_copy(update={
            "census": census, "ended_at": ended_at, "costs": None, "reconciled_at": None,
            "reconciliation_error": None,
        })

    update_run_accounting(path, update)
