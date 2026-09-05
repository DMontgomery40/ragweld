"""Run ownership and native-cost reconciliation on existing index summaries."""

from __future__ import annotations

import fcntl
import hashlib
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from opentelemetry.propagate import inject

from server.indexing.run_records import (
    initial_request_census,
    initialize_accounted_run,
    persist_request_census,
    update_run_accounting,
)
from server.models.index import IndexRunSummary
from server.models.run_accounting import (
    CostLane,
    IndexCostEstimateSnapshot,
    IndexRunAccounting,
    NativeRunCosts,
    RunRequestCensus,
)
from server.observability.gateway_costs import (
    NativeLedgerReadError,
    NativeSpendReader,
    RequestCensus,
)
from server.observability.run_census import CensusCheckpoint, RunCensusScope, RunIdentity
from server.observability.runtime import StreamingObservation, start_streaming_observation

if TYPE_CHECKING:
    from server.models.tribrid_config_model import TriBridConfig

_ABANDONED_NOTE = "Worker process ended before a closed accounting checkpoint."


class IndexAccountingOwner:
    """One explicit owner passed to workers; no process-global attribution state."""

    def __init__(
        self, path: Path, summary: IndexRunSummary, *, config_json: str,
        models: dict[CostLane, str], coverage_complete: bool, coverage_notes: list[str],
        estimate: IndexCostEstimateSnapshot | None = None,
        gateway_attempt_policy_verified: bool = False,
        gateway_base_url: str | None = None,
        config: TriBridConfig | None = None,
    ) -> None:
        self.path = path
        self._finished = False
        self._release_lock = threading.Lock()
        self.scopes: dict[CostLane, RunCensusScope] = {}
        self._observation: StreamingObservation | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        self._owner_lock = path.with_name(f"{path.name}.accounting-owner.lock").open("a")
        try:
            initialize_accounted_run(path, summary, IndexRunAccounting(
                session_id=summary.run_id, corpus_id=summary.repo_id, started_at=summary.started_at,
                config_fingerprint=hashlib.sha256(config_json.encode()).hexdigest(), models=models,
                coverage_complete=coverage_complete, coverage_notes=coverage_notes, estimate=estimate,
                gateway_attempt_policy_verified=gateway_attempt_policy_verified,
                gateway_base_url=gateway_base_url,
            ), owner_lock=self._owner_lock)
            trace_headers: dict[str, str] = {}
            if config is not None:
                self._observation = start_streaming_observation(
                    config=config, route_name=f"index.{summary.run_kind}",
                    path="/api/index/{corpus_id}/graph-schema/proposal" if summary.run_kind == "schema_proposal" else "/api/index", method="POST",
                    correlation_id=summary.run_id, run_id=summary.run_id, repo_id=summary.repo_id,
                )
                with self._observation.scope():
                    inject(trace_headers)
            for lane in models:
                self.scopes[lane] = RunCensusScope(
                    RunIdentity(summary.run_id, summary.repo_id, lane), self._checkpoint,
                    trace_headers=trace_headers,
                )
        except BaseException:
            self._owner_lock.close()
            if self._observation is not None:
                self._observation.finish()
            raise

    def _checkpoint(self, checkpoint: CensusCheckpoint) -> None:
        persist_request_census(self.path, RunRequestCensus.model_validate(asdict(checkpoint)))
        self._release_if_quiescent()

    def _release_if_quiescent(self) -> None:
        with self._release_lock:
            if not self._finished or self._owner_lock.closed:
                return
            summary = IndexRunSummary.model_validate_json(self.path.read_text())
            record = summary.accounting
            if record is not None and all(
                item.owner_finished and not item.inflight and not item.active_producers
                for item in record.census.values()
            ):
                self._owner_lock.close()
                if self._observation is not None:
                    self._observation.finish()

    def progress(self, *, files: int = 0, chunks: int = 0, tokens: int = 0) -> None:
        """Processed denominators survive failure; they do not claim store promotion."""
        if min(files, chunks, tokens) < 0:
            raise ValueError("Processed counters cannot decrease")
        update_run_accounting(self.path, lambda record: record.model_copy(update={
            "processed_files": record.processed_files + files,
            "processed_chunks": record.processed_chunks + chunks,
            "processed_tokens": record.processed_tokens + tokens,
        }))

    def finish(self, *, interrupted: bool = False) -> None:
        """Stop new sends on failure; retained workers still own their leases."""
        if self._owner_lock.closed:
            return
        errors: list[Exception] = []
        self._finished = True
        for scope in self.scopes.values():
            try:
                if interrupted:
                    scope.disable_dispatch()
                scope.finish_owner()
            except Exception as exc:
                errors.append(exc)
        if not self.scopes:
            update_run_accounting(self.path, lambda record: record if record.ended_at is not None else record.model_copy(update={
                "ended_at": datetime.now(UTC), "costs": None,
                "reconciled_at": None, "reconciliation_error": None,
            }))
        if errors:
            raise errors[0]
        self._release_if_quiescent()


def accounting_census(record: IndexRunAccounting) -> RequestCensus:
    checkpoints = list(record.census.values())
    all_present = set(record.census) == set(record.models)
    quiescent = all_present and all(
        item.owner_finished and not item.inflight and not item.active_producers
        for item in checkpoints
    ) and record.ended_at is not None
    state: Literal["open", "closed", "interrupted"] = "open"
    if any(item.state == "interrupted" for item in checkpoints) or record.owner_interrupted:
        state = "interrupted"
    elif quiescent and all(item.state == "closed" for item in checkpoints):
        state = "closed"
    return RequestCensus(
        state=state,
        started_requests=sum(item.started_requests for item in checkpoints),
        completed_requests=sum(item.completed_requests for item in checkpoints),
        failed_requests=sum(item.failed_requests for item in checkpoints),
        uncertain_requests=sum(item.uncertain_requests for item in checkpoints),
        workers_quiescent=quiescent,
        coverage_complete=record.coverage_complete and all_present,
        gateway_attempt_policy_verified=record.gateway_attempt_policy_verified or not record.models,
    )


async def reconcile_run_costs(path: Path, reader: NativeSpendReader) -> IndexRunSummary:
    """Refresh a derived aggregate, discarding results if workers advanced meanwhile."""
    summary = IndexRunSummary.model_validate_json(path.read_text())
    record = summary.accounting
    if record is None:
        return summary
    if record.ended_at is None and not accounting_owner_alive(path):
        interrupt_abandoned_accounting(path)
        summary = IndexRunSummary.model_validate_json(path.read_text())
        record = summary.accounting
        assert record is not None
    census = accounting_census(record)
    try:
        aggregate = await reader.read_run(
            session_id=record.session_id, corpus_id=record.corpus_id,
            lanes=frozenset(record.models) or frozenset({"embedding", "semantic_kg", "figure_description", "schema_proposal"}), started_at=record.started_at,
            ended_at=record.ended_at or datetime.now(UTC), census=census,
        )
        costs = NativeRunCosts.model_validate(asdict(aggregate))
        error = None
    except NativeLedgerReadError as exc:
        costs = None
        error = exc.code

    def merge(current: IndexRunAccounting) -> IndexRunAccounting:
        if any(getattr(current, field) != getattr(record, field) for field in (
            "census", "ended_at", "reconciled_at", "reconciliation_error", "costs",
            "coverage_complete", "gateway_attempt_policy_verified", "coverage_notes",
            "owner_interrupted",
        )):
            return current
        return current.model_copy(update={
            "costs": costs, "reconciled_at": datetime.now(UTC), "reconciliation_error": error,
        })

    update_run_accounting(path, merge)
    return IndexRunSummary.model_validate_json(path.read_text())


def interrupt_abandoned_accounting(path: Path) -> None:
    """A dead owner's open census cannot be reconstructed as closed from log rows."""
    def interrupt(record: IndexRunAccounting) -> IndexRunAccounting:
        # Recheck under the summary lock: the caller's earlier open observation
        # may precede the owner completing and releasing its lifetime lock.
        if record.ended_at is not None or accounting_owner_alive(path):
            return record
        if (
            record.owner_interrupted
            and set(record.census) == set(record.models)
            and all(checkpoint.state != "open" for checkpoint in record.census.values())
        ):
            return record
        census = {
            lane: checkpoint.model_copy(update={
                "state": "interrupted", "dispatch_enabled": False,
                "revision": checkpoint.revision + 1,
            }) if checkpoint.state == "open" else checkpoint
            for lane, checkpoint in record.census.items()
        }
        missing = set(record.models) - set(census)
        for lane in missing:
            census[lane] = initial_request_census(record, lane).model_copy(update={
                "state": "interrupted", "dispatch_enabled": False,
            })
        return record.model_copy(update={
            "census": census, "ended_at": None, "costs": None, "reconciled_at": None,
            "owner_interrupted": True,
            "coverage_complete": record.coverage_complete and not missing,
            "coverage_notes": list(dict.fromkeys([
                *record.coverage_notes, _ABANDONED_NOTE,
            ])),
        })

    update_run_accounting(path, interrupt)


def accounting_owner_alive(path: Path) -> bool:
    """The OS releases this existing run's lifetime lock if its worker dies."""
    with path.with_name(f"{path.name}.accounting-owner.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
