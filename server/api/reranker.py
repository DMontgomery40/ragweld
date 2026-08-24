from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
import weakref
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NamedTuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from server.api.dataset import _dataset_path_for_corpus, _load_dataset
from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.api.eval import _load_run as load_eval_run
from server.api.eval import latest_run_for_repo as latest_eval_run_for_repo
from server.config import load_config
from server.db.postgres import PostgresClient
from server.dependency_errors import DependencyUnavailableError
from server.lineage import (
    attach_refs_to_current_bundle,
    capture_path_version,
    capture_training_run_version,
    ensure_current_bundle,
    make_ref,
)
from server.models.training_eval import (
    CorpusEvalProfile,
    RerankerTrainMetricEvent,
    RerankerTrainRun,
    RerankerTrainRunMeta,
    RerankerTrainRunsResponse,
    RerankerTrainStartRequest,
)
from server.models.tribrid_config_model import (
    CountResponse,
    EvalRun,
    OkResponse,
    RerankerClickRequest,
    RerankerCostsResponse,
    RerankerEvaluateResponse,
    RerankerInfoResponse,
    RerankerLegacyStatus,
    RerankerLegacyTask,
    RerankerLegacyTaskResult,
    RerankerLogsResponse,
    RerankerMineResponse,
    RerankerNoHitsResponse,
    RerankerScoreRequest,
    RerankerScoreResponse,
    RerankerTrainDiagnosticRecord,
    RerankerTrainDiagnosticsResponse,
    RerankerTrainDiffRequest,
    RerankerTrainDiffResponse,
    RerankerTrainLegacyRequest,
    RerankerTrainLegacyResponse,
    RerankerTrainMetricsResponse,
    RerankerTrainStartResponse,
    TriBridConfig,
)
from server.observability.metrics import (
    RERANKER_DIAGNOSTIC_EVENTS_TOTAL,
    RERANKER_EVAL_LATENCY_SECONDS,
    RERANKER_EVAL_RUNS_TOTAL,
    RERANKER_MINE_LATENCY_SECONDS,
    RERANKER_MINE_RUNS_TOTAL,
    RERANKER_PROMOTION_LATENCY_SECONDS,
    RERANKER_PROMOTIONS_TOTAL,
    RERANKER_TRAIN_ACTIVE_RUNS,
    RERANKER_TRAIN_EVENTS_TOTAL,
    RERANKER_TRAIN_GRAD_NORM,
    RERANKER_TRAIN_LAST_EPOCH,
    RERANKER_TRAIN_LAST_METRIC,
    RERANKER_TRAIN_LAST_STEP,
    RERANKER_TRAIN_LOSS,
    RERANKER_TRAIN_PROGRESS_PERCENT,
    RERANKER_TRAIN_RUNS_TOTAL,
    RERANKER_TRAIN_SAMPLES_TOTAL,
    RERANKER_TRAIN_STAGE_ERRORS_TOTAL,
    RERANKER_TRAIN_STAGE_LATENCY_SECONDS,
    RERANKER_TRAIN_STEP_TIME_SECONDS,
    RERANKER_TRIPLET_SKIPS_TOTAL,
    RERANKER_TRIPLETS_TOTAL,
)
from server.retrieval.mlx_qwen3 import (
    invalidate_mlx_qwen3_cache_sync,
    is_mlx_qwen3_artifact_compatible,
    mlx_is_available,
    read_manifest,
    read_manifest_backend,
    write_mlx_manifest,
)
from server.retrieval.rerank import resolve_learning_backend
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.training.atomic_json import write_json_atomic
from server.training.metric_policy import infer_corpus_eval_profile
from server.training.metric_values import (
    finite_metrics,
    finite_or_none,
    non_negative_or_none,
    stability_stddev,
    step_or_none,
)
from server.training.mlx_qwen3_trainer import (
    TrainingCancelledError,
    deterministic_split_by_query,
    evaluate_mlx_qwen3_reranker,
    train_qwen3_lora_reranker,
)
from server.training.artifact_store import (
    ArtifactStoreError,
    VersionedArtifactSwap,
    resolve_active_artifact_dir,
)
from server.training.promotion import (
    BaselineState,
    await_uncancellable,
    decide_auto_promotion,
    run_promotion_transaction,
)
from server.training.reranker_trainer import (
    load_triplets,
    materialize_triplets,
)
from server.training.triplet_miner import mine_triplets
from server.training.triplet_rows import TripletRowsCorruptError

router = APIRouter(tags=["reranker"])
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _ROOT / "data" / "reranker_train_runs"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_LOGS_ROOT = (PROJECT_ROOT / "data" / "logs").resolve()
_TMP_ROOT = Path(tempfile.gettempdir()).resolve()


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _resolve_safe_log_path(path_str: str) -> Path:
    """Resolve and validate a log path for *API exposure* (read/download/clear).

    Prevents config-controlled path traversal or absolute path abuse from turning
    the logs endpoints into an arbitrary file read/truncate primitive.
    """
    raw = str(path_str or "data/logs/queries.jsonl")
    p = _resolve_path(raw)
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p.absolute()

    allowed_roots = (_LOGS_ROOT, _TMP_ROOT)
    allowed = False
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            allowed = True
            break
        except Exception:
            continue

    if not allowed:
        raise HTTPException(
            status_code=400,
            detail="Invalid tracing.tribrid_log_path (must be under data/logs/ or OS temp dir)",
        )

    if resolved.suffix.lower() != ".jsonl":
        raise HTTPException(
            status_code=400,
            detail="Invalid tracing.tribrid_log_path (must end with .jsonl)",
        )

    return resolved


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _is_test_request(request: Request) -> bool:
    """Best-effort guard to avoid contaminating training logs during tests."""
    try:
        if (request.headers.get("x-tribrid-test") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    except Exception:
        pass
    return False


@dataclass
class _LegacyStatus:
    """Process-local status used by the legacy LearningRanker UI polling loop."""

    running: bool = False
    progress: int = 0  # 0-100
    task: RerankerLegacyTask = ""  # mining|training|evaluating|""
    message: str = ""
    result: RerankerLegacyTaskResult | None = None
    live_output: list[str] = field(default_factory=list)
    run_id: str | None = None


_legacy_status = _LegacyStatus()
_legacy_lock = asyncio.Lock()

_train_tasks: dict[str, asyncio.Task[None]] = {}
_train_cancel_events: dict[str, asyncio.Event] = {}
# Serializes a run's terminal transition (completion + promotion) with cancellation requests in
# this API process (training jobs are in-process: single-worker deployment is the contract).
_run_state_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _run_state_lock(run_id: str) -> asyncio.Lock:
    lock = _run_state_locks.get(run_id)
    if lock is None:
        lock = asyncio.Lock()
        _run_state_locks[run_id] = lock
    return lock
_train_start_guard: dict[str, tuple[str, datetime]] = {}
_TRAIN_START_GRACE = timedelta(seconds=2)


def _mark_train_start_guard(corpus_id: str, run_id: str, *, at: datetime | None = None) -> None:
    """Remember a just-started run long enough to block rapid duplicate starts.

    We set the guard before the run is fully persisted to prevent true
    concurrent requests from racing during startup, then refresh it again once
    the background task is actually queued so fast-failing jobs still block
    accidental double-submits from the caller that just received `200 OK`.
    """
    _train_start_guard[str(corpus_id or "").strip()] = (run_id, at or datetime.now(UTC))


async def _resolve_corpus_id(corpus_id: str | None) -> str:
    """Resolve corpus scope for legacy endpoints.

    - If corpus_id is provided, return it.
    - If not provided and exactly one corpus exists, use it.
    - Otherwise, require explicit scope (422).
    """
    if corpus_id and corpus_id.strip():
        return corpus_id.strip()

    cfg = load_config()
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpora = await pg.list_corpora()
        if len(corpora) == 1:
            return str(corpora[0]["repo_id"])
    finally:
        await pg.disconnect()

    raise HTTPException(
        status_code=422,
        detail=(
            "Missing corpus_id (or legacy repo_id). "
            "Pass ?corpus_id=... (or use Training Studio which is corpus-scoped)."
        ),
    )


@router.post("/reranker/click", response_model=OkResponse, responses=DEPENDENCY_UNAVAILABLE_RESPONSES)
async def track_click(
    payload: RerankerClickRequest,
    request: Request,
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope for logging"),
) -> OkResponse:
    """Record a document click for triplet mining.

    Expected payload: {"event_id": str, "doc_id": str}
    """
    if not _is_test_request(request):
        from server.observability.query_log import append_feedback_log

        if corpus_id and corpus_id.strip():
            try:
                cfg = await load_scoped_config(repo_id=corpus_id.strip())
            except CorpusNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except Exception as exc:
                raise_postgres_unavailable_if_applicable(exc, boundary="Reranker click corpus config")
                logger.exception("Failed to resolve scoped config for reranker click")
                raise HTTPException(status_code=500, detail="Failed to resolve corpus config") from exc
        else:
            cfg = load_config()

        try:
            await append_feedback_log(cfg, event_id=payload.event_id, signal="click", doc_id=payload.doc_id)
        except DependencyUnavailableError as exc:
            if exc.dependency == "feedback_log":
                raise dependency_unavailable_http_exception(
                    "feedback_log",
                    boundary="Reranker click feedback",
                    exc=exc,
                ) from exc
            raise
        except Exception as exc:
            logger.exception("Failed to append reranker click feedback")
            raise HTTPException(status_code=500, detail="Failed to record reranker click") from exc

    return OkResponse(ok=True)


def _run_dir(run_id: str) -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR / run_id


def _run_json_path(run_id: str) -> Path:
    return _run_dir(run_id) / "run.json"


def _metrics_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metrics.jsonl"


def _diagnostics_path(run_id: str) -> Path:
    return _run_dir(run_id) / "diagnostics.jsonl"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


def _operator_hint_for_stage(stage: str) -> str | None:
    hints = {
        "load_triplets": "Mine triplets into training.tribrid_triplets_path before starting training or evaluation.",
        "materialize_triplets": "Triplet doc_ids did not resolve under the active corpus root; inspect mined positives and negatives against the current corpus path.",
        "resolve_backend": "The learning reranker path expects MLX on Apple Silicon plus a valid training.learning_reranker_base_model.",
        "baseline_eval": "Baseline evaluation reads the active adapter under training.tribrid_reranker_model_path; verify the adapter manifest matches the configured base model.",
        "train_loop": "Failure happened inside the MLX Qwen3 training loop; inspect MLX dependencies, memory pressure, and LoRA target module compatibility.",
        "final_eval": "Post-train evaluation reads the newly written adapter artifact; verify adapter.npz and adapter_config.json were written cleanly.",
        "promote": "Promotion copies the run artifact into training.tribrid_reranker_model_path and clears the MLX cache; inspect filesystem write access and adapter completeness.",
        "mine_triplets": "Triplet mining depends on tracing.tribrid_log_path containing correlated query and feedback events with matching event_id values.",
        "evaluate_active": "Evaluation uses the active adapter at training.tribrid_reranker_model_path; verify manifest and base-model compatibility plus available triplets.",
        "score_pair": "Debug scoring uses the active MLX adapter; verify the adapter directory exists and matches training.learning_reranker_base_model.",
    }
    return hints.get(str(stage or "").strip())


def _log_reranker_event(
    *,
    level: Literal["debug", "info", "warning", "error"],
    event: str,
    message: str,
    operator_hint: str | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": str(event or "").strip() or "unknown",
        "message": str(message or "").strip(),
        "fields": dict(_json_safe(fields or {})),
    }
    if operator_hint:
        payload["operatorHint"] = str(operator_hint).strip()
    line = json.dumps(payload, sort_keys=True)
    if level == "debug":
        logger.debug(line)
    elif level == "warning":
        logger.warning(line)
    elif level == "error":
        logger.error(line)
    else:
        logger.info(line)


def _append_diagnostic(
    run_id: str,
    *,
    level: Literal["debug", "info", "warning", "error"],
    event: str,
    message: str,
    operator_hint: str | None = None,
    fields: dict[str, Any] | None = None,
) -> None:
    record = RerankerTrainDiagnosticRecord(
        ts=datetime.now(UTC),
        run_id=run_id,
        level=level,
        event=str(event or "").strip() or "unknown",
        message=str(message or "").strip(),
        operator_hint=str(operator_hint or "").strip() or None,
        fields=dict(_json_safe(fields or {})),
    )
    path = _diagnostics_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = record.model_dump(mode="json", by_alias=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    RERANKER_DIAGNOSTIC_EVENTS_TOTAL.labels(level=record.level, event=record.event).inc()
    _log_reranker_event(
        level=level,
        event=record.event,
        message=record.message,
        operator_hint=record.operator_hint,
        fields={"run_id": run_id, **dict(payload.get("fields") or {})},
    )


def _load_diagnostics(run_id: str, limit: int | None = None) -> list[RerankerTrainDiagnosticRecord]:
    path = _diagnostics_path(run_id)
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    out: list[RerankerTrainDiagnosticRecord] = []
    for line in lines:
        try:
            out.append(RerankerTrainDiagnosticRecord.model_validate(json.loads(line)))
        except Exception:
            continue
    return out


def _sync_train_active_runs_gauge() -> None:
    try:
        RERANKER_TRAIN_ACTIVE_RUNS.set(float(len(_train_tasks)))
    except Exception:
        pass


def _set_last_metric_values(metrics: dict[str, float] | None, *, phase: str) -> None:
    if not isinstance(metrics, dict):
        return
    for key, raw in metrics.items():
        try:
            value = float(raw)
        except Exception:
            continue
        metric_name = str(key or "").split("@", 1)[0].strip().lower()
        if metric_name not in {"mrr", "ndcg", "map", "train_loss", "lr", "grad_norm"}:
            continue
        RERANKER_TRAIN_LAST_METRIC.labels(metric=metric_name, phase=str(phase or "stream")).set(value)


def _capture_model_artifact_ref(run_id: str, repo_id: str) -> Any | None:
    path = _run_dir(run_id) / "model"
    if not path.exists():
        return None
    version = capture_path_version(
        kind="reranker_model_artifact",
        path=path,
        repo_id=repo_id,
        source="generated",
        metadata={"run_id": run_id},
    )
    return make_ref("reranker_model_artifact", version.version_id)


def _attach_lineage(run: RerankerTrainRun, cfg: Any, *, promoted: bool = False) -> RerankerTrainRun:
    repo_id = str(run.repo_id)
    model_ref = _capture_model_artifact_ref(run.run_id, repo_id)
    if model_ref is not None:
        run.model_artifact_ref = model_ref
    try:
        dataset_rows = [row.model_dump(mode="json", by_alias=True) for row in _load_dataset(corpus_id=repo_id)]
    except Exception:
        dataset_rows = []
    run_version = capture_training_run_version(
        kind="reranker_train_run",
        run_payload=run.model_dump(mode="json", by_alias=True),
        repo_id=repo_id,
        payload_extras={
            "model_artifact_ref": model_ref.model_dump(mode="json", by_alias=True) if model_ref is not None else None,
            "promotion": {"promoted": bool(promoted)},
        },
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=repo_id,
        cfg=cfg,
        dataset_rows=dataset_rows,
        dataset_path=str(_dataset_path_for_corpus(repo_id)),
        reranker_train_runs=[make_ref("reranker_train_run", run_version.version_id)],
        reranker_model_artifacts=[model_ref] if model_ref is not None else [],
        extra_aliases=("promoted",) if promoted else (),
        preserve_attached_refs=True,
    )
    run.lineage_ref = make_ref("reranker_train_run", run_version.version_id)
    run.bundle_id = bundle.bundle_id
    if promoted:
        run.promoted_bundle_id = bundle.bundle_id
    return run

def _tail_lines(path: Path, *, max_bytes: int = 65536, max_lines: int = 50) -> list[str]:
    """Read up to the last N lines from a potentially large text file."""
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return []
            start = max(0, size - int(max_bytes))
            f.seek(start)
            data = f.read()
    except Exception:
        return []

    try:
        txt = data.decode("utf-8", errors="ignore")
    except Exception:
        return []

    # If we started mid-line, drop the first partial line.
    if start > 0:
        nl = txt.find("\n")
        if nl != -1:
            txt = txt[nl + 1 :]
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _read_last_event(run_id: str) -> RerankerTrainMetricEvent | None:
    """Best-effort read of the most recent metrics event for a run."""
    path = _metrics_path(run_id)
    for line in reversed(_tail_lines(path, max_lines=50)):
        try:
            return RerankerTrainMetricEvent.model_validate(json.loads(line))
        except Exception:
            continue
    return None


async def _transition_run(
    run_id: str,
    *,
    allowed_from: frozenset[str],
    apply: Callable[[RerankerTrainRun], RerankerTrainRun | None],
) -> RerankerTrainRun | None:
    """The one way a run record changes status.

    Under the run's lock, the STORED record is re-read (never a caller's stale copy); when its
    status is not in `allowed_from` nothing is written and None is returned (compare-and-set);
    otherwise `apply` mutates the stored record in a worker thread (it may attach lineage) and
    the result is saved atomically.
    """
    async with _run_state_lock(run_id):
        try:
            stored = await asyncio.to_thread(_load_run, run_id)
        except HTTPException:
            return None
        if str(stored.status) not in allowed_from:
            return None

        def _apply_and_save() -> RerankerTrainRun:
            updated = apply(stored) or stored
            _save_run(updated)
            return updated

        return await asyncio.to_thread(_apply_and_save)


def _finalize_stored_run(
    run: RerankerTrainRun,
    cfg: Any | None,
    *,
    status: str,
    message: str,
    completed_at: datetime | None = None,
    append_events: bool = True,
) -> RerankerTrainRun:
    """Mutate a stored, non-terminal run into its terminal state (caller holds the run lock).

    Reconciliation of a record whose metrics stream already carries the terminal `complete`
    event passes `append_events=False` (the events exist) and the event's timestamp as
    `completed_at`; every finalization still attaches lineage when a config is available.
    """
    now = datetime.now(UTC)
    run.status = status  # type: ignore[assignment]
    run.completed_at = completed_at or now
    if cfg is not None:
        run = _attach_lineage(run, cfg)
    _save_run(run)  # durable before the terminal events below
    if append_events:
        _append_event(
            run.run_id,
            RerankerTrainMetricEvent(
                type="error" if status == "failed" else "state",
                ts=now,
                run_id=run.run_id,
                status=run.status,  # type: ignore[arg-type]
                message=message,
            ),
        )
        _append_event(
            run.run_id,
            RerankerTrainMetricEvent(type="complete", ts=now, run_id=run.run_id, status=run.status),  # type: ignore[arg-type]
        )
    _train_start_guard.pop(str(run.repo_id or "").strip(), None)
    return run


class _ReconcileDecision(NamedTuple):
    status: str
    message: str
    completed_at: datetime | None
    append_events: bool


def _reconcile_decision(run: RerankerTrainRun) -> _ReconcileDecision | None:
    """What (if anything) an explicit reconciliation should do to a stale `running` record.

    Pure with respect to persisted state: it reads the metrics tail and in-process task table
    only. The actual repair goes through `_transition_run` + `_finalize_stored_run`.
    """
    if run.status != "running":
        return None

    last = _read_last_event(run.run_id)
    msg = str(getattr(last, "message", "") or "")
    now = datetime.now(UTC)

    # 1) Legacy stub runs: never actually trained, but were persisted as running.
    if "Training task is a stub" in msg:
        return _ReconcileDecision(
            status="cancelled",
            message="Reconciled legacy stub run (no training ever started).",
            completed_at=None,
            append_events=True,
        )

    # 2) The metrics stream already carries the terminal events; only the record lags.
    terminal = str(getattr(last, "status", "") or "").strip().lower()
    if getattr(last, "type", None) == "complete" and terminal in {"completed", "failed", "cancelled"}:
        return _ReconcileDecision(
            status=terminal,
            message="Reconciled run record with its terminal metrics stream.",
            completed_at=getattr(last, "ts", None) or now,
            append_events=False,
        )

    # 3) Orphaned run after backend restart: mark cancelled after long inactivity.
    if run.run_id not in _train_tasks:
        last_ts = getattr(last, "ts", None) if last is not None else None
        anchor = last_ts or run.started_at
        try:
            idle_secs = float((now - anchor).total_seconds())
        except Exception:
            idle_secs = 0.0
        if idle_secs >= 2 * 60 * 60:
            return _ReconcileDecision(
                status="cancelled",
                message="Reconciled orphaned run (no active task; likely backend restart).",
                completed_at=None,
                append_events=True,
            )
    return None


def _cfg_from_run_snapshot(run: RerankerTrainRun) -> TriBridConfig | None:
    try:
        return TriBridConfig.model_validate(run.config_snapshot)
    except Exception:
        return None


async def reconcile_run(run_id: str) -> RerankerTrainRun:
    """Explicit reconciliation of a persisted run: loading stays read-only, and any repair is
    a transition through the authority, finalized by `_finalize_stored_run`. Lineage is
    attached from the run's own `config_snapshot` (the configuration that governed the run),
    never today's corpus config. Endpoints that list or get runs call this; nothing
    reconciles on load."""
    run = await asyncio.to_thread(_load_run, run_id)
    decision = await asyncio.to_thread(_reconcile_decision, run)
    if decision is None:
        return run
    cfg = _cfg_from_run_snapshot(run)
    result = await _transition_run(
        run_id,
        allowed_from=frozenset({"running"}),
        apply=lambda stored: _finalize_stored_run(
            stored,
            cfg,
            status=decision.status,
            message=decision.message,
            completed_at=decision.completed_at,
            append_events=decision.append_events,
        ),
    )
    if result is not None:
        return result
    try:
        return await asyncio.to_thread(_load_run, run_id)
    except HTTPException:
        return run


def _promotion_recorded(run_id: str) -> bool:
    """Artifact-store recovery's truth for a crashed promotion: did the run record commit?

    A promoted run carries `promoted_bundle_id` (written durably inside the promotion
    transaction's work step). Read-only; an unreadable record means unrecorded, so recovery
    stays conservative and rolls the pointer back.
    """
    try:
        run = _load_run(run_id)
    except Exception:
        return False
    return bool(run.promoted_bundle_id)


def _load_run(run_id: str) -> RerankerTrainRun:
    """Read-only load of the persisted record: no reconciliation, no writes. Status repairs
    happen only through `reconcile_run` / `_transition_run` (the transition authority)."""
    path = _run_json_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read train run: {e}") from e
    return RerankerTrainRun.model_validate(raw)


def _save_run(run: RerankerTrainRun) -> None:
    """Crash-safe: the previous run.json survives a failed write (see server/training/atomic_json.py)."""
    write_json_atomic(_run_json_path(run.run_id), run.model_dump(mode="json", by_alias=True))


def _append_event(run_id: str, event: RerankerTrainMetricEvent) -> None:
    path = _metrics_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json", by_alias=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    try:
        RERANKER_TRAIN_EVENTS_TOTAL.labels(type=str(event.type)).inc()
        if event.step is not None:
            RERANKER_TRAIN_LAST_STEP.set(float(event.step))
        if event.epoch is not None:
            RERANKER_TRAIN_LAST_EPOCH.set(float(event.epoch))
        if event.percent is not None:
            RERANKER_TRAIN_PROGRESS_PERCENT.set(float(event.percent))
        _set_last_metric_values(event.metrics, phase="stream")

        if isinstance(event.metrics, dict):
            train_loss = event.metrics.get("train_loss")
            if train_loss is not None:
                try:
                    RERANKER_TRAIN_LOSS.observe(float(train_loss))
                except Exception:
                    pass
            grad_norm = event.metrics.get("grad_norm")
            if grad_norm is not None:
                try:
                    RERANKER_TRAIN_GRAD_NORM.observe(float(grad_norm))
                except Exception:
                    pass

        if event.loss is not None:
            RERANKER_TRAIN_LOSS.observe(float(event.loss))
            RERANKER_TRAIN_LAST_METRIC.labels(metric="train_loss", phase="stream").set(float(event.loss))
        if event.lr is not None:
            RERANKER_TRAIN_LAST_METRIC.labels(metric="lr", phase="stream").set(float(event.lr))
        if event.grad_norm is not None:
            RERANKER_TRAIN_GRAD_NORM.observe(float(event.grad_norm))
            RERANKER_TRAIN_LAST_METRIC.labels(metric="grad_norm", phase="stream").set(float(event.grad_norm))
        if event.step_time_ms is not None:
            RERANKER_TRAIN_STEP_TIME_SECONDS.observe(float(event.step_time_ms) / 1000.0)
        if event.sample_count is not None and event.sample_count > 0:
            RERANKER_TRAIN_SAMPLES_TOTAL.inc(int(event.sample_count))
    except Exception:
        pass


class UnreadableEvents(NamedTuple):
    count: int
    first_reason: str | None


def _load_events(run_id: str, limit: int | None = None) -> tuple[list[RerankerTrainMetricEvent], UnreadableEvents]:
    """Events of a run plus an honest count of records that no longer validate.

    A NaN written by an older build, or a torn line, is reported — never silently dropped
    so that best/stability figures are not derived from a truncated trace without notice.
    """
    path = _metrics_path(run_id)
    if not path.exists():
        return [], UnreadableEvents(0, None)
    try:
        raw_lines = path.read_bytes().split(b"\n")
    except OSError as exc:
        return [], UnreadableEvents(1, f"{path.name}: {exc}")
    # Every physical line is decoded and validated on its own (one bad byte never hides the
    # rest of the history), the whole file is counted, then the last `limit` valid events win.
    out: list[RerankerTrainMetricEvent] = []
    unreadable = 0
    first_reason: str | None = None
    for number, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            continue
        try:
            out.append(RerankerTrainMetricEvent.model_validate(json.loads(raw_line.decode("utf-8"))))
        except Exception as exc:
            unreadable += 1
            if first_reason is None:
                first_reason = f"line {number}: {' '.join(str(exc).split())[:200]}"
    if limit is not None and limit > 0:
        out = out[-limit:]
    return out, UnreadableEvents(unreadable, first_reason)


def _sse_payload_for_line(run_id: str, raw_line: bytes) -> str | None:
    """The SSE data payload for one persisted metrics line: the validated event, or an `error`
    event naming the corruption. Never a lossy decode, never silence."""
    try:
        line = raw_line.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        return json.dumps(
            RerankerTrainMetricEvent(type="error", ts=datetime.now(UTC), run_id=run_id, message=f"metrics record is not UTF-8: {exc}").model_dump(mode="json", by_alias=True)
        )
    if not line:
        return None
    try:
        event = RerankerTrainMetricEvent.model_validate(json.loads(line))
    except Exception as exc:
        return json.dumps(
            RerankerTrainMetricEvent(type="error", ts=datetime.now(UTC), run_id=run_id, message=f"metrics record could not be read: {' '.join(str(exc).split())[:200]}").model_dump(mode="json", by_alias=True)
        )
    return json.dumps(event.model_dump(mode="json", by_alias=True))


def _primary_metric_key(run: RerankerTrainRun) -> str:
    if run.primary_metric == "map":
        return "map"
    return f"{run.primary_metric}@{run.primary_k}"


def _compute_primary_best_from_events(run: RerankerTrainRun, events: list[RerankerTrainMetricEvent]) -> float | None:
    key = _primary_metric_key(run)
    vals: list[float] = []
    for ev in events:
        if ev.type != "metrics" or not ev.metrics:
            continue
        if key not in ev.metrics:
            continue
        try:
            vals.append(float(ev.metrics[key]))
        except Exception:
            continue
    return max(vals) if vals else None


def _compute_time_to_best_secs_from_events(
    run: RerankerTrainRun, events: list[RerankerTrainMetricEvent]
) -> float | None:
    key = _primary_metric_key(run)
    best = _compute_primary_best_from_events(run, events)
    if best is None:
        return None
    for ev in events:
        if ev.type != "metrics" or not ev.metrics or key not in ev.metrics:
            continue
        try:
            val = float(ev.metrics[key])
        except Exception:
            continue
        if val == best:
            return non_negative_or_none((ev.ts - run.started_at).total_seconds())
    return None


def _compute_stability_stddev_from_events(run: RerankerTrainRun, events: list[RerankerTrainMetricEvent]) -> float | None:
    key = _primary_metric_key(run)
    vals: list[float] = []
    for ev in events:
        if ev.type != "metrics" or not ev.metrics or key not in ev.metrics:
            continue
        try:
            vals.append(float(ev.metrics[key]))
        except Exception:
            continue
    return stability_stddev(vals)


def _allocate_run_id(repo_id: str, started_at: datetime) -> str:
    base = f"{repo_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_id = base
    n = 0
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    while (_RUNS_DIR / run_id).exists():
        n += 1
        run_id = f"{base}__{n}"
    return run_id


def _format_metrics_for_run(run: RerankerTrainRun, raw: Mapping[str, object]) -> dict[str, float]:
    """Map raw proxy metrics {mrr,ndcg,map} to run metrics keys, keeping only finite numbers.

    A missing or NaN/inf metric is absent from the result (never coerced to 0.0), so a
    broken evaluation reads as "no measurement" downstream instead of as a score of zero.
    """
    k = int(run.primary_k)
    finite, _dropped = finite_metrics(raw)
    out: dict[str, float] = {}
    for src, dst in (("mrr", f"mrr@{k}"), ("ndcg", f"ndcg@{k}"), ("map", "map")):
        if src in finite:
            out[dst] = finite[src]
    return out


def build_reranker_progress_event(
    run_id: str, ts: datetime, payload: Mapping[str, Any]
) -> tuple[RerankerTrainMetricEvent, list[str]]:
    """Progress payload -> event. Zero is a value (step 0, epoch 0.0, percent 0.0 survive);
    only absent or non-finite scalars become None, and the dropped metric names are returned."""
    dropped: list[str] = []
    metrics: dict[str, float] | None = None
    raw_metrics = payload.get("metrics")
    if isinstance(raw_metrics, dict):
        finite, dropped = finite_metrics(raw_metrics)
        metrics = finite or None
    event = RerankerTrainMetricEvent(
        type="progress",
        ts=ts,
        run_id=run_id,
        step=step_or_none(payload.get("step")),
        epoch=finite_or_none(payload.get("epoch")),
        percent=finite_or_none(payload.get("percent")),
        message=str(payload.get("message") or ""),
        metrics=metrics,
    )
    return event, dropped


def build_reranker_telemetry_event(run_id: str, ts: datetime, payload: Mapping[str, Any]) -> RerankerTrainMetricEvent:
    sample_count = step_or_none(payload.get("sample_count"))
    return RerankerTrainMetricEvent(
        type="telemetry",
        ts=ts,
        run_id=run_id,
        step=step_or_none(payload.get("step")),
        epoch=finite_or_none(payload.get("epoch")),
        proj_x=finite_or_none(payload.get("proj_x")),
        proj_y=finite_or_none(payload.get("proj_y")),
        loss=finite_or_none(payload.get("loss")),
        lr=finite_or_none(payload.get("lr")),
        grad_norm=finite_or_none(payload.get("grad_norm")),
        step_time_ms=finite_or_none(payload.get("step_time_ms")),
        sample_count=sample_count,
    )


def _non_finite_metric_names(raw: Mapping[str, object]) -> list[str]:
    """Names of the proxy metrics that were present but not finite (for the operator diagnostic)."""
    _finite, dropped = finite_metrics(raw)
    return dropped


def _primary_value(run: RerankerTrainRun, metrics: Mapping[str, object]) -> float | None:
    """The run's primary metric from a metrics mapping, or None when it is absent or not finite."""
    key = f"{run.primary_metric}@{int(run.primary_k)}" if run.primary_metric != "map" else "map"
    return finite_or_none(metrics.get(key))


async def _run_train_job(*, run_id: str, corpus_id: str, cancel_event: asyncio.Event | None = None) -> None:
    """Background training job for /reranker/train/start.

    Uses:
    - Triplets mined into cfg.training.tribrid_triplets_path (JSONL)
    - Base model from cfg.training.learning_reranker_base_model
    - Output model written to both:
      - data/reranker_train_runs/<run_id>/model (artifact)
      - cfg.training.tribrid_reranker_model_path (promoted active model)
    """
    try:
        run = _load_run(run_id)
    except Exception:
        return

    def _emit_log(msg: str) -> None:
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="log", ts=datetime.now(UTC), run_id=run_id, message=str(msg)),
        )

    def _is_cancel_requested() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def _raise_if_cancelled(message: str = "Training cancelled by user.") -> None:
        if _is_cancel_requested():
            raise TrainingCancelledError(message)

    cfg: Any | None = None
    current_stage = "load_scoped_config"
    try:
        _append_diagnostic(
            run_id,
            level="info",
            event="train_run_started",
            message="Starting reranker training run.",
            fields={"corpus_id": corpus_id},
        )
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage="load_scoped_config").time():
            cfg = await load_scoped_config(repo_id=corpus_id)
        _raise_if_cancelled()

        current_stage = "load_triplets"
        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
            triplets = await asyncio.to_thread(load_triplets, triplets_path)
        RERANKER_TRIPLETS_TOTAL.labels(kind="loaded").inc(len(triplets))
        if not triplets:
            raise RuntimeError(f"No triplets found at {cfg.training.tribrid_triplets_path}. Run /api/reranker/mine first.")

        min_count = int(cfg.training.triplets_min_count or 0)
        if min_count > 0 and len(triplets) < min_count:
            raise RuntimeError(
                f"Not enough triplets to train (have {len(triplets)}, need >= {min_count}). "
                "Mine more (or lower training.triplets_min_count)."
            )

        current_stage = "resolve_backend"
        backend = resolve_learning_backend(
            cfg.training,
            artifact_path=str(getattr(cfg.training, "tribrid_reranker_model_path", "") or ""),
        )
        if backend != "mlx_qwen3":
            raise RuntimeError(f"unsupported learning reranker backend: {backend}")
        if not mlx_is_available():
            raise RuntimeError("learning reranker backend resolved to mlx_qwen3 but MLX is not installed")

        base_model = str(cfg.training.learning_reranker_base_model or "").strip()
        if not base_model:
            raise RuntimeError("Missing base model for MLX learning reranker (training.learning_reranker_base_model).")

        # Resolve corpus root path (for reading triplet doc_ids as files).
        current_stage = "resolve_corpus"
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(corpus_id)
            if corpus is None:
                raise RuntimeError(f"Corpus not found: {corpus_id}")
        finally:
            await pg.disconnect()
        corpus_root = Path(str(corpus.get("path") or "")).expanduser()
        if not corpus_root.is_absolute():
            corpus_root = PROJECT_ROOT / corpus_root

        snippet_chars = int(getattr(cfg.reranking, "rerank_input_snippet_chars", 2000) or 2000)
        current_stage = "materialize_triplets"
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
            mats, mat_stats = await asyncio.to_thread(
                materialize_triplets,
                triplets,
                corpus_root=corpus_root,
                snippet_chars=snippet_chars,
            )
        RERANKER_TRIPLETS_TOTAL.labels(kind="materialized").inc(int(mat_stats.get("triplets_out", 0) or 0))
        RERANKER_TRIPLET_SKIPS_TOTAL.labels(reason="missing_positive").inc(int(mat_stats.get("missing_positive", 0) or 0))
        RERANKER_TRIPLET_SKIPS_TOTAL.labels(reason="missing_negative").inc(int(mat_stats.get("missing_negative", 0) or 0))
        RERANKER_TRIPLET_SKIPS_TOTAL.labels(reason="empty_positive").inc(int(mat_stats.get("empty_positive", 0) or 0))
        RERANKER_TRIPLET_SKIPS_TOTAL.labels(reason="empty_negative").inc(int(mat_stats.get("empty_negative", 0) or 0))
        if not mats:
            raise RuntimeError(
                "No usable triplets after materialization. "
                f"Check that positive/negative doc_ids exist under corpus root: {corpus_root}"
            )
        _raise_if_cancelled()

        _append_diagnostic(
            run_id,
            level="info",
            event="materialization_summary",
            message="Materialized reranker triplets for training.",
            fields={
                "triplets_in": int(mat_stats.get("triplets_in", 0) or 0),
                "triplets_out": int(mat_stats.get("triplets_out", 0) or 0),
                "missing_positive": int(mat_stats.get("missing_positive", 0) or 0),
                "missing_negative": int(mat_stats.get("missing_negative", 0) or 0),
                "empty_positive": int(mat_stats.get("empty_positive", 0) or 0),
                "empty_negative": int(mat_stats.get("empty_negative", 0) or 0),
                "corpus_root": str(corpus_root),
            },
        )
        _emit_log(
            f"Training on {mat_stats.get('triplets_out', 0)} materialized triplets "
            f"(skipped_missing_pos={mat_stats.get('missing_positive', 0)}, skipped_missing_neg={mat_stats.get('missing_negative', 0)})."
        )

        model_artifact_dir = _run_dir(run_id) / "model"
        model_artifact_dir.parent.mkdir(parents=True, exist_ok=True)

        train_triplets, dev_triplets = deterministic_split_by_query(mats, dev_split=0.1, seed=0)
        RERANKER_TRIPLETS_TOTAL.labels(kind="train_split").inc(len(train_triplets))
        RERANKER_TRIPLETS_TOTAL.labels(kind="dev_split").inc(len(dev_triplets))
        # The active adapter lives in a versioned store under tribrid_reranker_model_path;
        # resolve the pointer once and read the pinned, immutable version for the baseline.
        active_root = _resolve_path(cfg.training.tribrid_reranker_model_path)
        store_unreadable: str | None = None
        try:
            active_version_dir = await asyncio.to_thread(resolve_active_artifact_dir, active_root)
        except ArtifactStoreError as exc:
            active_version_dir = None
            store_unreadable = str(exc)
        train_batch_size = int(run.batch_size)
        train_grad_accum_steps = int(cfg.training.learning_reranker_grad_accum_steps)
        train_max_length = int(run.max_length)

        if backend == "mlx_qwen3":
            orig_batch = int(train_batch_size)
            orig_grad = int(train_grad_accum_steps)
            orig_maxlen = int(train_max_length)
            # MLX Qwen3 training can spike unified-memory usage on long sequences.
            # Keep a strict safe lane by default on Apple Silicon.
            train_batch_size = max(1, min(orig_batch, 1))
            train_max_length = max(32, min(orig_maxlen, 256))
            # Do NOT preserve effective batch by inflating grad_accum after capping
            # micro-batch size; long accumulation windows make progress appear stuck
            # and can amplify MLX lazy-graph memory pressure.
            train_grad_accum_steps = max(1, min(orig_grad, 8))
            if (
                train_batch_size != orig_batch
                or train_grad_accum_steps != orig_grad
                or train_max_length != orig_maxlen
            ):
                _append_diagnostic(
                    run_id,
                    level="warning",
                    event="mlx_safety_caps_applied",
                    message="Applied MLX safety caps to keep reranker training stable on Apple Silicon.",
                    operator_hint="Training is using capped batch, grad accumulation, or sequence length to reduce unified-memory pressure; inspect these caps before raising throughput aggressively.",
                    fields={
                        "batch_size_before": int(orig_batch),
                        "batch_size_after": int(train_batch_size),
                        "grad_accum_before": int(orig_grad),
                        "grad_accum_after": int(train_grad_accum_steps),
                        "max_length_before": int(orig_maxlen),
                        "max_length_after": int(train_max_length),
                    },
                )
                _emit_log(
                    "Applied MLX safety caps "
                    f"(batch_size {orig_batch}->{train_batch_size}, "
                    f"grad_accum {orig_grad}->{train_grad_accum_steps}, "
                    f"max_length {orig_maxlen}->{train_max_length}) "
                    "to reduce unified-memory pressure on Apple Silicon while keeping progress responsive."
                )

        baseline_primary: float | None = None
        baseline_state: BaselineState = "absent"
        if store_unreadable is not None:
            # Unknown quality is not absence: an unreadable store refuses gated promotion.
            baseline_state = "failed"
            _emit_log(
                f"Active-artifact store at {cfg.training.tribrid_reranker_model_path} is unreadable "
                f"({store_unreadable}); improvement-gated promotion is refused until the operator repairs it."
            )
        elif dev_triplets and active_version_dir is not None:
            _raise_if_cancelled()
            manifest_backend = read_manifest_backend(active_version_dir)
            if not manifest_backend:
                _emit_log("Baseline eval skipped (active artifact manifest missing; treating as no baseline).")
            elif str(manifest_backend) != str(backend):
                baseline_state = "incompatible"
                _emit_log(
                    f"Baseline eval skipped (active manifest backend={manifest_backend} != resolved backend={backend})."
                )
            elif backend == "mlx_qwen3":
                if not is_mlx_qwen3_artifact_compatible(artifact_dir=active_version_dir, base_model=str(base_model)):
                    baseline_state = "incompatible"
                    _emit_log("Baseline eval skipped (active artifact is missing or incompatible with mlx_qwen3).")
                else:
                    try:
                        current_stage = "baseline_eval"
                        baseline_t0 = time.perf_counter()
                        raw_baseline = await asyncio.to_thread(
                            evaluate_mlx_qwen3_reranker,
                            base_model=str(base_model),
                            adapter_dir=active_version_dir,
                            triplets=dev_triplets,
                            max_length=int(train_max_length),
                            lora_rank=int(cfg.training.learning_reranker_lora_rank),
                            lora_alpha=float(cfg.training.learning_reranker_lora_alpha),
                            lora_dropout=float(cfg.training.learning_reranker_lora_dropout),
                            lora_target_modules=list(cfg.training.learning_reranker_lora_target_modules),
                            should_stop=_is_cancel_requested,
                        )
                        RERANKER_EVAL_LATENCY_SECONDS.labels(phase="baseline").observe(time.perf_counter() - baseline_t0)
                        baseline_metrics = _format_metrics_for_run(run, raw_baseline)
                        baseline_primary = _primary_value(run, baseline_metrics)
                        baseline_state = "measured" if baseline_primary is not None else "failed"
                        _set_last_metric_values(baseline_metrics, phase="baseline")
                        RERANKER_EVAL_RUNS_TOTAL.labels(phase="baseline", outcome="ok").inc()
                        _append_diagnostic(
                            run_id,
                            level="info",
                            event="baseline_eval_complete",
                            message="Completed baseline evaluation against the active reranker artifact.",
                            fields={
                                "baseline_primary": baseline_primary,
                                "baseline_state": baseline_state,
                                "dev_triplets": int(len(dev_triplets)),
                                "backend": str(backend),
                                "metrics": baseline_metrics,
                            },
                        )
                        if baseline_primary is None:
                            _emit_log(
                                f"Baseline eval ({backend}) produced no finite primary metric; the active "
                                "artifact's quality is unknown, so improvement-gated promotion is refused for this run."
                            )
                        else:
                            _emit_log(f"Baseline primary={baseline_primary:.6f} ({backend}) on held-out dev split.")
                    except Exception as e:
                        RERANKER_EVAL_RUNS_TOTAL.labels(phase="baseline", outcome="error").inc()
                        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage="baseline_eval").inc()
                        _append_diagnostic(
                            run_id,
                            level="warning",
                            event="baseline_eval_failed",
                            message=f"Baseline evaluation failed: {e}",
                            operator_hint=_operator_hint_for_stage("baseline_eval"),
                            fields={"backend": str(backend), "error": str(e)},
                        )
                        _emit_log(
                            f"Baseline eval failed ({backend}); the active artifact's quality is unknown, "
                            f"so improvement-gated promotion is refused for this run. error={e}"
                        )
                        baseline_primary = None
                        baseline_state = "failed"
        best_primary: float | None = None
        best_step: int | None = None
        best_ts: datetime | None = None
        primary_series: list[float] = []
        loop = asyncio.get_running_loop()

        def _emit(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal best_primary, best_step, best_ts, primary_series
            ts = datetime.now(UTC)
            if event_type == "log":
                try:
                    msg = str(payload.get("message") or "").strip()
                except Exception:
                    msg = ""
                if msg:
                    _append_event(
                        run_id,
                        RerankerTrainMetricEvent(type="log", ts=ts, run_id=run_id, message=msg),
                    )
                return
            if event_type == "progress":
                # Legacy polling hook (best-effort).
                try:
                    pct = int(float(payload.get("percent") or 0.0))
                    msg = str(payload.get("message") or "")
                    def _schedule() -> None:
                        async def _upd() -> None:
                            async with _legacy_lock:
                                if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                                    _legacy_status.running = True
                                    _legacy_status.progress = max(0, min(100, int(pct)))
                                    _legacy_status.message = msg

                        asyncio.create_task(_upd())

                    loop.call_soon_threadsafe(_schedule)
                except Exception:
                    pass

                event, dropped = build_reranker_progress_event(run_id, ts, payload)
                if dropped:
                    _append_diagnostic(
                        run_id,
                        level="warning",
                        event="metrics_not_finite",
                        message="Progress metrics contained non-finite values; they are excluded from the event stream.",
                        fields={"step": payload.get("step"), "dropped": dropped},
                    )
                _append_event(run_id, event)
                return
            if event_type == "metrics":
                raw = payload.get("metrics") or {}
                raw_map = raw if isinstance(raw, dict) else {}
                metrics = _format_metrics_for_run(run, raw_map)
                dropped = _non_finite_metric_names(raw_map)
                if dropped:
                    _append_diagnostic(
                        run_id,
                        level="warning",
                        event="metrics_not_finite",
                        message="A training evaluation produced non-finite metrics; they are excluded from the event and the series.",
                        fields={"step": payload.get("step"), "dropped": dropped, "raw_metrics": {str(k): str(v) for k, v in raw_map.items()}},
                    )
                pv = _primary_value(run, metrics)
                if pv is None:
                    pass  # already diagnosed above (non-finite) or the primary metric was simply not reported
                else:
                    primary_series.append(pv)
                    if best_primary is None or pv > best_primary:
                        best_primary = pv
                        best_step = step_or_none(payload.get("step"))
                        best_ts = ts
                _append_event(
                    run_id,
                    RerankerTrainMetricEvent(
                        type="metrics",
                        ts=ts,
                        run_id=run_id,
                        step=step_or_none(payload.get("step")),
                        epoch=finite_or_none(payload.get("epoch")),
                        metrics=metrics,
                    ),
                )
                return
            if event_type == "telemetry":
                _append_event(run_id, build_reranker_telemetry_event(run_id, ts, payload))
                return

        # Mark run as running through the authority: the stored record is re-read under the
        # run lock (never this coroutine's stale object, which predates the long triplet and
        # baseline work above) and a run that was cancelled meanwhile is honoured.
        _raise_if_cancelled()

        def _to_running(stored: RerankerTrainRun) -> RerankerTrainRun:
            stored.status = "running"
            return stored

        transitioned = await _transition_run(run_id, allowed_from=frozenset({"queued", "running"}), apply=_to_running)
        if transitioned is None:
            raise TrainingCancelledError(f"run {run_id} was ended before training could start")
        run = transitioned
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="state", ts=datetime.now(UTC), run_id=run_id, status=run.status),
        )

        # Train (runs in thread; emits progress/metrics into metrics.jsonl).
        _raise_if_cancelled()
        current_stage = "train_loop"
        _append_diagnostic(
            run_id,
            level="info",
            event="train_loop_started",
            message="Starting MLX Qwen3 reranker training loop.",
            fields={
                "train_triplets": int(len(train_triplets)),
                "dev_triplets": int(len(dev_triplets)),
                "epochs": int(run.epochs),
                "batch_size": int(train_batch_size),
                "grad_accum_steps": int(train_grad_accum_steps),
                "max_length": int(train_max_length),
                "negative_ratio": int(cfg.training.learning_reranker_negative_ratio),
            },
        )
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
            await asyncio.to_thread(
                train_qwen3_lora_reranker,
                run_id=run_id,
                base_model=base_model,
                output_dir=model_artifact_dir,
                train_triplets=train_triplets,
                dev_triplets=dev_triplets,
                epochs=int(run.epochs),
                batch_size=int(train_batch_size),
                gradient_accumulation_steps=int(train_grad_accum_steps),
                lr=float(run.lr),
                warmup_ratio=float(run.warmup_ratio),
                max_length=int(train_max_length),
                negative_ratio=int(cfg.training.learning_reranker_negative_ratio),
                seed=0,
                lora_rank=int(cfg.training.learning_reranker_lora_rank),
                lora_alpha=float(cfg.training.learning_reranker_lora_alpha),
                lora_dropout=float(cfg.training.learning_reranker_lora_dropout),
                lora_target_modules=list(cfg.training.learning_reranker_lora_target_modules),
                telemetry_interval_steps=int(cfg.training.learning_reranker_telemetry_interval_steps),
                emit=_emit,
                should_stop=_is_cancel_requested,
            )

        _raise_if_cancelled()
        # Evaluate trained artifact on the same held-out dev split used for baseline gating.
        if not dev_triplets:
            # Nothing was evaluated: no metrics event, no series value, no fabricated zero.
            proxy = {}
            _append_diagnostic(
                run_id,
                level="warning",
                event="final_eval_skipped",
                message="No held-out dev split exists, so the trained artifact was not evaluated and stays unpromoted.",
                fields={"backend": str(backend), "dev_triplets": 0},
            )
        else:
            current_stage = "final_eval"
            final_eval_t0 = time.perf_counter()
            proxy = await asyncio.to_thread(
                evaluate_mlx_qwen3_reranker,
                base_model=str(base_model),
                adapter_dir=model_artifact_dir,
                triplets=dev_triplets,
                max_length=int(train_max_length),
                lora_rank=int(cfg.training.learning_reranker_lora_rank),
                lora_alpha=float(cfg.training.learning_reranker_lora_alpha),
                lora_dropout=float(cfg.training.learning_reranker_lora_dropout),
                lora_target_modules=list(cfg.training.learning_reranker_lora_target_modules),
                should_stop=_is_cancel_requested,
            )
            RERANKER_EVAL_LATENCY_SECONDS.labels(phase="final").observe(time.perf_counter() - final_eval_t0)
            RERANKER_EVAL_RUNS_TOTAL.labels(phase="final", outcome="ok").inc()

        metrics = _format_metrics_for_run(run, proxy)
        final_dropped = _non_finite_metric_names(proxy)
        pv = _primary_value(run, metrics)
        if dev_triplets:
            _set_last_metric_values(metrics, phase="final")
            if metrics:
                _append_event(
                    run_id,
                    RerankerTrainMetricEvent(type="metrics", ts=datetime.now(UTC), run_id=run_id, metrics=metrics),
                )
            if pv is not None:
                primary_series.append(pv)
            _append_diagnostic(
                run_id,
                level="info" if pv is not None and not final_dropped else "warning",
                event="final_eval_complete",
                message=(
                    "Evaluated the newly trained reranker artifact on the held-out dev split."
                    if pv is not None
                    else "The final evaluation produced no finite primary metric; the artifact stays unpromoted."
                ),
                fields={
                    "backend": str(backend),
                    "dev_triplets": int(len(dev_triplets)),
                    "primary_value": pv,
                    "metrics": metrics,
                    "dropped_non_finite": final_dropped,
                },
            )

        # Promote trained artifact to the active path (atomic), gated on improvement when configured.
        promote_if_improves = cfg.training.learning_reranker_promote_if_improves
        eps = float(cfg.training.learning_reranker_promote_epsilon or 0.0)
        decision = decide_auto_promotion(
            primary_value=pv,
            baseline_primary=baseline_primary,
            baseline_state=baseline_state,
            dev_examples=len(dev_triplets),
            promote_if_improves=bool(promote_if_improves),
            epsilon=eps,
            backend=str(backend),
            artifact_dir=str(model_artifact_dir),
        )
        should_promote = decision.promote
        if decision.notice:
            _emit_log(decision.notice)

        # Populate (and validate) the summary BEFORE any artifact copy: an impossible value
        # fails the run here, while the active artifact is still untouched.
        run.summary.primary_metric_best = best_primary if best_primary is not None else pv
        run.summary.primary_metric_final = pv
        run.summary.best_step = best_step
        if best_ts is not None:
            run.summary.time_to_best_secs = non_negative_or_none((best_ts - run.started_at).total_seconds())
        run.summary.stability_stddev = stability_stddev(primary_series)

        _raise_if_cancelled()

        def _complete_run(promoted: bool) -> None:
            # Everything that must be durable before a promotion counts: status, lineage, run record.
            # Compare-and-set on the STORED record: a run a cancellation already ended is not
            # completed (and, inside the promotion transaction, this rolls the swap back).
            nonlocal run
            stored = _load_run(run_id)
            if str(stored.status) in _TERMINAL_RUN_STATUSES:
                raise TrainingCancelledError(f"run {run_id} was ended as {stored.status} before completion")
            stored.summary = run.summary
            stored.status = "completed"
            stored.completed_at = datetime.now(UTC)
            run = _attach_lineage(stored, cfg, promoted=promoted)
            _save_run(run)

        # Completion (and promotion) is one critical section with cancellation: the check is
        # repeated INSIDE the lock, and a cancel request takes the same lock before signalling.
        completion_lock = _run_state_lock(run_id)
        await completion_lock.acquire()
        try:
            _raise_if_cancelled()
            if should_promote:
                current_stage = "promote"
                swap = VersionedArtifactSwap(
                    model_artifact_dir, active_root, run_id=run_id, promotion_recorded=_promotion_recorded
                )

                def _promotion_work() -> str | None:
                    _complete_run(promoted=True)
                    return run.bundle_id

                with RERANKER_PROMOTION_LATENCY_SECONDS.time():
                    leftover = await await_uncancellable(
                        run_promotion_transaction,
                        swap=swap,
                        repo_id=str(run.repo_id),
                        work=_promotion_work,
                        # the in-process model cache is invalidated INSIDE the transaction (and again on rollback)
                        invalidate=lambda: invalidate_mlx_qwen3_cache_sync(str(active_root)),
                    )
                promotion_fields = {
                    "active_path": str(active_root),
                    "artifact_path": str(model_artifact_dir),
                    "backend": str(backend),
                    "primary_value": pv,
                    "retained_previous_not_removed": str(leftover) if leftover is not None else None,
                }
                promotion_message = (
                    f"Promoted trained artifact to {cfg.training.tribrid_reranker_model_path} (backend={backend}). "
                    f"Run artifact preserved at {model_artifact_dir}."
                )
            else:
                await await_uncancellable(_complete_run, False)
                promotion_fields = {
                    "backend": str(backend),
                    "primary_value": pv,
                    "baseline_primary": baseline_primary,
                    "baseline_state": baseline_state,
                    "epsilon": float(eps),
                }
                promotion_message = decision.message

        finally:
            completion_lock.release()

        # The run is durably completed (and the promotion committed) from here on. Everything
        # below is observability: a failure here must not turn a completed run into a failed one.
        try:
            RERANKER_PROMOTIONS_TOTAL.labels(outcome="promoted" if should_promote else "skipped").inc()
            RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="completed").inc()
            _append_diagnostic(
                run_id,
                level="info",
                event="promotion_complete" if should_promote else "promotion_skipped",
                message=(
                    "Promoted the trained reranker artifact to the active path."
                    if should_promote
                    else "Skipped promotion because the trained artifact did not beat the baseline gate."
                ),
                fields=promotion_fields,
            )
            _emit_log(promotion_message)
            _append_event(
                run_id,
                RerankerTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status=run.status),
            )
            _append_diagnostic(
                run_id,
                level="info",
                event="train_run_completed",
                message="Reranker training run completed successfully.",
                fields={
                    "primary_metric_best": run.summary.primary_metric_best,
                    "primary_metric_final": run.summary.primary_metric_final,
                    "best_step": run.summary.best_step,
                    "stability_stddev": run.summary.stability_stddev,
                    "promoted": bool(should_promote),
                },
            )
            async with _legacy_lock:
                if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                    _legacy_status.running = False
                    _legacy_status.progress = 100
                    _legacy_status.message = "Training complete"
                    _legacy_status.result = RerankerLegacyTaskResult(ok=True, run_id=run_id)
        except Exception as observability_failure:  # noqa: BLE001 - best-effort after the durable commit
            logger.warning(
                json.dumps(
                    {
                        "event": "reranker_train_post_commit_observability_failed",
                        "run_id": run_id,
                        "message": str(observability_failure),
                        "operatorHint": "The run completed and any promotion is committed; only its completion diagnostics/events could not be written.",
                    },
                    sort_keys=True,
                )
            )

    except TrainingCancelledError as e:

        def _end_cancelled(stored: RerankerTrainRun) -> RerankerTrainRun:
            stored.status = "cancelled"
            stored.completed_at = datetime.now(UTC)
            return _attach_lineage(stored, cfg) if cfg is not None else stored

        try:
            # through the authority: a run already terminal (completed, or finalized by
            # reconciliation/cancel) is left exactly as it is
            await _transition_run(run_id, allowed_from=frozenset({"queued", "running"}), apply=_end_cancelled)
        except Exception:
            pass

        _append_event(
            run_id,
            RerankerTrainMetricEvent(
                type="state",
                ts=datetime.now(UTC),
                run_id=run_id,
                message=str(e),
                operator_hint=_operator_hint_for_stage(current_stage),
                status="cancelled",
            ),
        )
        RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="cancelled").inc()
        _append_diagnostic(
            run_id,
            level="warning",
            event="train_run_cancelled",
            message=str(e),
            operator_hint=_operator_hint_for_stage(current_stage),
            fields={"stage": str(current_stage)},
        )
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status="cancelled"),
        )
        async with _legacy_lock:
            if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                _legacy_status.running = False
                _legacy_status.progress = 0
                _legacy_status.message = "Training cancelled"
                _legacy_status.result = RerankerLegacyTaskResult(
                    ok=False,
                    run_id=run_id,
                    error="cancelled",
                    operator_hint=_operator_hint_for_stage(current_stage),
                )
    except Exception as e:
        if _is_cancel_requested():

            def _end_cancelled(stored: RerankerTrainRun) -> RerankerTrainRun:
                stored.status = "cancelled"
                stored.completed_at = datetime.now(UTC)
                return _attach_lineage(stored, cfg) if cfg is not None else stored

            try:
                await _transition_run(run_id, allowed_from=frozenset({"queued", "running"}), apply=_end_cancelled)
            except Exception:
                pass

            _append_event(
                run_id,
                RerankerTrainMetricEvent(
                    type="state",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    message=str(e) or "Training cancelled by user.",
                    operator_hint=_operator_hint_for_stage(current_stage),
                    status="cancelled",
                ),
            )
            RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="cancelled").inc()
            _append_diagnostic(
                run_id,
                level="warning",
                event="train_run_cancelled",
                message=str(e) or "Training cancelled by user.",
                operator_hint=_operator_hint_for_stage(current_stage),
                fields={"stage": str(current_stage)},
            )
            _append_event(
                run_id,
                RerankerTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status="cancelled"),
            )
            async with _legacy_lock:
                if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                    _legacy_status.running = False
                    _legacy_status.progress = 0
                    _legacy_status.message = "Training cancelled"
                    _legacy_status.result = RerankerLegacyTaskResult(
                        ok=False,
                        run_id=run_id,
                        error="cancelled",
                        operator_hint=_operator_hint_for_stage(current_stage),
                    )
        else:

            def _end_failed(stored: RerankerTrainRun) -> RerankerTrainRun:
                stored.status = "failed"
                stored.completed_at = datetime.now(UTC)
                return _attach_lineage(stored, cfg) if cfg is not None else stored

            try:
                # never flips a run that is already terminal (durably completed, or ended by
                # reconciliation/cancel)
                await _transition_run(run_id, allowed_from=frozenset({"queued", "running"}), apply=_end_failed)
            except Exception:
                pass
            RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="failed").inc()
            RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage=str(current_stage)).inc()

            _append_event(
                run_id,
                RerankerTrainMetricEvent(
                    type="error",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    message=str(e),
                    operator_hint=_operator_hint_for_stage(current_stage),
                    status="failed",
                ),
            )
            _append_diagnostic(
                run_id,
                level="error",
                event="train_run_failed",
                message=f"Reranker training run failed during stage={current_stage}: {e}",
                operator_hint=_operator_hint_for_stage(current_stage),
                fields={"stage": str(current_stage), "error": str(e)},
            )
            _append_event(
                run_id,
                RerankerTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status="failed"),
            )
            async with _legacy_lock:
                if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                    _legacy_status.running = False
                    _legacy_status.progress = 0
                    _legacy_status.message = "Training failed"
                    _legacy_status.result = RerankerLegacyTaskResult(
                        ok=False,
                        run_id=run_id,
                        error=str(e),
                        operator_hint=_operator_hint_for_stage(current_stage),
                    )
    finally:
        _train_tasks.pop(run_id, None)
        _train_cancel_events.pop(run_id, None)
        _sync_train_active_runs_gauge()


async def _run_eval_job(*, corpus_id: str) -> None:
    try:
        cfg = await load_scoped_config(repo_id=corpus_id)
        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        triplets = load_triplets(triplets_path)
        if not triplets:
            raise RuntimeError(f"No triplets found at {cfg.training.tribrid_triplets_path}. Run /api/reranker/mine first.")

        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(corpus_id)
            if corpus is None:
                raise RuntimeError(f"Corpus not found: {corpus_id}")
        finally:
            await pg.disconnect()
        corpus_root = Path(str(corpus.get("path") or "")).expanduser()
        if not corpus_root.is_absolute():
            corpus_root = PROJECT_ROOT / corpus_root

        snippet_chars = int(getattr(cfg.reranking, "rerank_input_snippet_chars", 2000) or 2000)
        mats, _ = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=snippet_chars)
        if not mats:
            raise RuntimeError("No usable triplets after materialization (missing/empty docs).")

        backend = resolve_learning_backend(
            cfg.training,
            artifact_path=str(getattr(cfg.training, "tribrid_reranker_model_path", "") or ""),
        )
        model_dir = await asyncio.to_thread(
            resolve_active_artifact_dir, _resolve_path(cfg.training.tribrid_reranker_model_path)
        )
        if model_dir is None:
            raise RuntimeError(
                f"No active reranker artifact is promoted under {cfg.training.tribrid_reranker_model_path}."
            )
        if backend != "mlx_qwen3":
            raise RuntimeError(f"unsupported learning reranker backend: {backend}")
        if not mlx_is_available():
            raise RuntimeError("MLX backend resolved but MLX is not installed")
        if not is_mlx_qwen3_artifact_compatible(
            artifact_dir=model_dir, base_model=str(cfg.training.learning_reranker_base_model)
        ):
            raise RuntimeError("Active artifact is not a compatible MLX Qwen3 adapter (manifest mismatch).")
        metrics = await asyncio.to_thread(
            evaluate_mlx_qwen3_reranker,
            base_model=str(cfg.training.learning_reranker_base_model),
            adapter_dir=model_dir,
            triplets=mats,
            max_length=int(cfg.reranking.tribrid_reranker_maxlen),
            lora_rank=int(cfg.training.learning_reranker_lora_rank),
            lora_alpha=float(cfg.training.learning_reranker_lora_alpha),
            lora_dropout=float(cfg.training.learning_reranker_lora_dropout),
            lora_target_modules=list(cfg.training.learning_reranker_lora_target_modules),
        )
        output = (
            f"Proxy metrics: backend={backend}\n"
            f"MRR: {metrics.get('mrr', 0.0):.4f}\n"
            f"nDCG: {metrics.get('ndcg', 0.0):.4f}\n"
            f"MAP: {metrics.get('map', 0.0):.4f}\n"
            f"Evaluated on {len(mats)} triplets\n"
        )

        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 100
            _legacy_status.message = "Evaluation complete"
            _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=output, metrics=metrics)
    except Exception as e:
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.message = "Evaluation failed"
            _legacy_status.result = RerankerLegacyTaskResult(ok=False, error=str(e))


def _latest_run_id_for_corpus(corpus_id: str) -> str | None:
    """Return the most recent training run_id for corpus_id (best-effort)."""
    cid = str(corpus_id or "").strip()
    if not cid:
        return None
    prefix = f"{cid}__"
    try:
        entries = [p for p in _RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    except Exception:
        return None
    if not entries:
        return None
    # run_id includes a sortable timestamp suffix; name sort is sufficient.
    entries.sort(key=lambda p: p.name, reverse=True)
    return str(entries[0].name)


async def _active_run_id_for_corpus(corpus_id: str) -> str | None:
    """The currently-running run gating a new start. Candidates are reconciled first (through
    the authority) so an orphaned record left `running` by a restart cannot block starts forever."""
    cid = str(corpus_id or "").strip()
    if not cid:
        return None
    guard = _train_start_guard.get(cid)
    if guard:
        run_id, started_at = guard
        try:
            run = await asyncio.to_thread(_load_run, run_id)
            if str(run.status) == "completed":
                _train_start_guard.pop(cid, None)
            elif datetime.now(UTC) - started_at <= _TRAIN_START_GRACE:
                return run_id
        except Exception:
            if datetime.now(UTC) - started_at <= _TRAIN_START_GRACE:
                return run_id
            _train_start_guard.pop(cid, None)
    prefix = f"{cid}__"
    try:
        entries = [p for p in _RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    except Exception:
        return None
    if not entries:
        return None
    entries.sort(key=lambda p: p.name, reverse=True)
    for entry in entries:
        try:
            run = await reconcile_run(entry.name)
        except Exception:
            continue
        if str(run.status) == "running":
            return str(run.run_id)
    return None


async def _status_from_persisted_run(*, corpus_id: str) -> RerankerLegacyStatus | None:
    """Synthesize a legacy polling status from persisted training run files.

    This avoids process-local drift under multi-worker servers: the UI polls
    `/reranker/status`, but the background job may be running in a different
    worker process.
    """
    run_id = _latest_run_id_for_corpus(corpus_id)
    if not run_id:
        return None

    try:
        run = await reconcile_run(run_id)
    except Exception:
        return None

    status = str(getattr(run, "status", "") or "").strip().lower()
    running = status == "running"
    task: Literal["mining", "training", "evaluating", ""] = "training"
    message = ""
    progress = 0
    result: RerankerLegacyTaskResult | None = None

    # Best-effort progress from the last progress event (if present).
    try:
        mp = _metrics_path(run_id)
        if mp.exists():
            lines = [ln for ln in mp.read_text(encoding="utf-8").splitlines() if ln.strip()]
            for ln in reversed(lines[-200:]):
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                if str(obj.get("type") or "") == "progress":
                    try:
                        progress = int(float(obj.get("percent") or 0.0))
                    except Exception:
                        progress = 0
                    message = str(obj.get("message") or "")
                    break
    except Exception:
        pass

    if running:
        if not message:
            message = f"Training run in progress: {run_id}"
        return RerankerLegacyStatus(
            running=True,
            progress=max(0, min(100, int(progress))),
            task=task,
            message=str(message),
            result=None,
            live_output=[],
            run_id=run_id,
        )

    # Completed/failed: keep message stable for legacy UI/tests.
    if status == "completed":
        message = "Training complete"
        result = RerankerLegacyTaskResult(ok=True, run_id=run_id)
        progress = 100
    elif status == "failed":
        message = "Training failed"
        err = None
        operator_hint = None
        try:
            # Find the last error event for a useful message.
            mp = _metrics_path(run_id)
            if mp.exists():
                lines = [ln for ln in mp.read_text(encoding="utf-8").splitlines() if ln.strip()]
                for ln in reversed(lines[-200:]):
                    try:
                        obj = json.loads(ln)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and str(obj.get("type") or "") == "error":
                        err = str(obj.get("message") or "") or None
                        operator_hint = str(obj.get("operator_hint") or "") or None
                        break
        except Exception:
            err = None
        result = RerankerLegacyTaskResult(ok=False, run_id=run_id, error=err, operator_hint=operator_hint)
        progress = 0
    elif status == "cancelled":
        message = "Training cancelled"
        result = RerankerLegacyTaskResult(ok=False, run_id=run_id, error="cancelled")
        progress = 0
    else:
        # Unknown persisted state; treat as not running.
        message = f"Training status: {status or 'unknown'}"
        result = RerankerLegacyTaskResult(ok=False, run_id=run_id, error="unknown status")

    return RerankerLegacyStatus(
        running=False,
        progress=max(0, min(100, int(progress))),
        task=task,
        message=str(message),
        result=result,
        live_output=[],
        run_id=run_id,
    )


@router.get("/reranker/status", response_model=RerankerLegacyStatus)
async def get_reranker_status(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope for stable status across workers"),
) -> RerankerLegacyStatus:
    # Minimal status shape expected by the UI polling loop.
    #
    # Priority:
    # 1) Legacy polling status (mining/training/evaluating)
    # 2) Best-effort *inference* runtime state
    async with _legacy_lock:
        if _legacy_status.running or _legacy_status.result is not None:
            return RerankerLegacyStatus(
                running=bool(_legacy_status.running),
                progress=int(_legacy_status.progress),
                task=_legacy_status.task,
                message=str(_legacy_status.message or ""),
                result=_legacy_status.result,  # validated by response_model
                live_output=list(_legacy_status.live_output),
                run_id=_legacy_status.run_id,
            )

    # If the UI supplies corpus_id (it does), synthesize from persisted training
    # runs so the status doesn't depend on process-local memory.
    if corpus_id and str(corpus_id).strip():
        derived = await _status_from_persisted_run(corpus_id=str(corpus_id).strip())
        if derived is not None:
            return derived

    from server.retrieval.rerank import get_reranker_runtime

    rt = get_reranker_runtime()
    ts = int(rt.last_attempt_ms or 0)
    mode = str(rt.last_mode or "none")
    applied = bool(rt.last_applied)
    ok = bool(rt.last_ok)
    skipped = rt.last_skipped_reason
    err = rt.last_error

    msg_parts = [
        f"mode={mode}",
        f"last_attempt_ms={ts}" if ts else "last_attempt_ms=—",
        f"applied={int(applied)}",
    ]
    if skipped:
        msg_parts.append(f"skipped={skipped}")
    if err:
        msg_parts.append(f"error={err}")

    result: RerankerLegacyTaskResult | None = None
    if ts:
        result = RerankerLegacyTaskResult(
            ok=ok,
            error=str(err) if err else None,
            operator_hint=_operator_hint_for_stage("score_pair") if err else None,
        )

    return RerankerLegacyStatus(
        running=False,
        progress=0,
        task="",
        message=" ".join(msg_parts),
        result=result,
        live_output=[],
        run_id=None,
    )


@router.get("/reranker/info", response_model=RerankerInfoResponse)
async def get_reranker_info() -> RerankerInfoResponse:
    """Return current reranker runtime/config info (no secrets)."""
    cfg = load_config()
    mode = (cfg.reranking.reranker_mode or "none").lower()
    enabled = mode != "none"

    if mode == "learning":
        path = cfg.training.tribrid_reranker_model_path
    elif mode == "cloud":
        path = cfg.reranking.reranker_cloud_model
    else:
        path = ""

    resolved = str(path or "")
    if mode == "learning" and path:
        # The resolved path is the pinned active version, or empty when nothing is promoted
        # or the store is broken — never the root pretending to be an adapter.
        try:
            active = await asyncio.to_thread(resolve_active_artifact_dir, _resolve_path(str(path)))
        except ArtifactStoreError:
            active = None
        resolved = str(active) if active is not None else ""

    return RerankerInfoResponse(
        enabled=enabled,
        reranker_mode=mode,
        reranker_cloud_provider=cfg.reranking.reranker_cloud_provider,
        reranker_cloud_model=cfg.reranking.reranker_cloud_model,
        path=str(path or ""),
        resolved_path=resolved,
        device="mlx" if (mode == "learning" and mlx_is_available()) else "cpu",
        alpha=cfg.reranking.tribrid_reranker_alpha,
        topn=cfg.reranking.tribrid_reranker_topn,
        batch=cfg.reranking.tribrid_reranker_batch,
        maxlen=cfg.reranking.tribrid_reranker_maxlen,
        snippet_chars=cfg.reranking.rerank_input_snippet_chars,
    )


@router.post("/reranker/score", response_model=RerankerScoreResponse)
async def score_reranker(payload: RerankerScoreRequest) -> RerankerScoreResponse:
    """Score one (query, document) pair for debug/proof workflows."""
    cid = str(payload.repo_id or "").strip()
    if not cid:
        return RerankerScoreResponse(
            ok=False,
            error="missing corpus_id",
            operator_hint="Pass corpus_id so debug scoring can resolve the active reranker config and adapter.",
            score=0.0,
        )

    try:
        cfg = await load_scoped_config(repo_id=cid)
    except Exception:
        # Best-effort debug endpoint: allow scoring against the global config when scoped config is unavailable.
        cfg = load_config()
    include_logits = bool(payload.include_logits)
    max_length = int(cfg.reranking.tribrid_reranker_maxlen)
    current_stage = "resolve_backend"

    try:
        backend = resolve_learning_backend(
            cfg.training,
            artifact_path=str(getattr(cfg.training, "tribrid_reranker_model_path", "") or ""),
        )
    except Exception as e:
        operator_hint = _operator_hint_for_stage("score_pair")
        _log_reranker_event(
            level="warning",
            event="reranker_score_failed",
            message=f"Debug reranker scoring failed during stage={current_stage}: {e}",
            operator_hint=operator_hint,
            fields={"corpus_id": cid, "stage": current_stage},
        )
        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage="score_pair").inc()
        return RerankerScoreResponse(ok=False, backend="learning", error=str(e), operator_hint=operator_hint, score=0.0)

    if backend != "mlx_qwen3":
        operator_hint = _operator_hint_for_stage("score_pair")
        return RerankerScoreResponse(
            ok=False,
            backend=str(backend),
            error=f"unsupported backend: {backend}",
            operator_hint=operator_hint,
            score=0.0,
        )
    if not mlx_is_available():
        operator_hint = _operator_hint_for_stage("score_pair")
        return RerankerScoreResponse(
            ok=False,
            backend="mlx_qwen3",
            error="mlx not available",
            operator_hint=operator_hint,
            score=0.0,
        )

    from server.retrieval.mlx_qwen3 import (
        get_mlx_qwen3_reranker,
        read_adapter_config,
        read_manifest,
    )

    try:
        adapter_dir = await asyncio.to_thread(
            resolve_active_artifact_dir, _resolve_path(cfg.training.tribrid_reranker_model_path)
        )
    except ArtifactStoreError as e:
        return RerankerScoreResponse(
            ok=False,
            backend="mlx_qwen3",
            error=f"active-artifact store is unreadable: {e}",
            operator_hint=_operator_hint_for_stage("score_pair"),
            score=0.0,
        )
    if adapter_dir is None:
        return RerankerScoreResponse(
            ok=False,
            backend="mlx_qwen3",
            error=f"no active adapter promoted under: {cfg.training.tribrid_reranker_model_path}",
            operator_hint=_operator_hint_for_stage("score_pair"),
            score=0.0,
        )

    manifest = read_manifest(adapter_dir) or {}
    manifest_base_model = str(manifest.get("base_model") or "").strip()
    base_model = manifest_base_model or str(cfg.training.learning_reranker_base_model)

    adapter_cfg = read_adapter_config(adapter_dir) or {}
    lora_rank = int(adapter_cfg.get("lora_rank") or cfg.training.learning_reranker_lora_rank)
    lora_alpha = float(adapter_cfg.get("lora_alpha") or cfg.training.learning_reranker_lora_alpha)
    lora_dropout = float(adapter_cfg.get("lora_dropout") or cfg.training.learning_reranker_lora_dropout)
    target_modules = adapter_cfg.get("target_modules")
    if not isinstance(target_modules, list) or not target_modules:
        target_modules = list(cfg.training.learning_reranker_lora_target_modules)

    current_stage = "score_pair"
    try:
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
            rr = await get_mlx_qwen3_reranker(
                base_model=str(base_model),
                adapter_dir=str(adapter_dir),
                lora_rank=int(lora_rank),
                lora_alpha=float(lora_alpha),
                lora_dropout=float(lora_dropout),
                lora_target_modules=[str(x) for x in list(target_modules)],
            )
            scores, yes_logits, no_logits = await rr.score_pairs_batched(
                [(str(payload.query), str(payload.document))],
                max_length=max_length,
                include_logits=include_logits,
                reload_on_change=bool(cfg.reranking.tribrid_reranker_reload_on_change),
                reload_period_sec=int(cfg.reranking.tribrid_reranker_reload_period_sec),
                unload_after_sec=int(cfg.training.learning_reranker_unload_after_sec),
            )
    except Exception as e:
        operator_hint = _operator_hint_for_stage("score_pair")
        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage="score_pair").inc()
        _log_reranker_event(
            level="error",
            event="reranker_score_failed",
            message=f"Debug reranker scoring failed during stage={current_stage}: {e}",
            operator_hint=operator_hint,
            fields={"corpus_id": cid, "adapter_dir": str(adapter_dir)},
        )
        return RerankerScoreResponse(
            ok=False,
            backend="mlx_qwen3",
            error=str(e),
            operator_hint=operator_hint,
            score=0.0,
        )
    score = float(scores[0]) if scores else 0.0
    yes_logit = float(yes_logits[0]) if include_logits and yes_logits and yes_logits[0] is not None else None
    no_logit = float(no_logits[0]) if include_logits and no_logits and no_logits[0] is not None else None
    return RerankerScoreResponse(ok=True, backend="mlx_qwen3", score=score, yes_logit=yes_logit, no_logit=no_logit)


def _resolve_mining_eval_run(*, corpus_id: str, eval_run_id: str | None) -> EvalRun | None:
    """Load the eval run whose retrieval results feed mining: an explicit id, or the corpus' latest.

    Explicit ids go through the eval storage owner (422 malformed, 404 unknown) and must
    belong to the corpus; the automatic branch only trusts runs whose validated payload
    names the corpus.
    """
    requested = str(eval_run_id or "").strip()
    if requested:
        run = load_eval_run(requested)
        if str(run.repo_id) != corpus_id:
            raise HTTPException(
                status_code=422,
                detail=f"Eval run {requested} belongs to corpus {run.repo_id!r}, not {corpus_id!r}",
            )
        return run
    return latest_eval_run_for_repo(corpus_id)


_mine_lock = asyncio.Lock()


@router.post("/reranker/mine", response_model=RerankerMineResponse, responses=DEPENDENCY_UNAVAILABLE_RESPONSES)
async def mine_reranker_triplets(
    corpus_id: str | None = Query(default=None, description="Corpus whose feedback log and eval runs are mined (required)."),
    eval_run_id: str | None = Query(
        default=None,
        description="Eval run whose retrieval results are mined for hard negatives (default: the corpus' latest run).",
    ),
) -> RerankerMineResponse:
    """Mine triplets from feedback events and eval-run retrieval results into training.tribrid_triplets_path."""
    cid = (corpus_id or "").strip()
    if not cid:
        raise HTTPException(status_code=422, detail="corpus_id is required: triplets are mined per corpus.")
    current_stage = "mine_triplets"
    async with _mine_lock:
        async with _legacy_lock:
            _legacy_status.running = True
            _legacy_status.progress = 0
            _legacy_status.task = "mining"
            _legacy_status.message = "Mining triplets…"
            _legacy_status.result = None
            _legacy_status.live_output = []
            _legacy_status.run_id = None
        try:
            cfg = await load_scoped_config(repo_id=cid)
            eval_run = await asyncio.to_thread(_resolve_mining_eval_run, corpus_id=cid, eval_run_id=eval_run_id)
            pg = PostgresClient(cfg.indexing.postgres_url)
            await pg.connect()
            try:
                corpus = await pg.get_corpus(cid)
            finally:
                await pg.disconnect()
            if corpus is None:
                raise HTTPException(status_code=404, detail=f"Corpus not found: {cid}")
            corpus_root = Path(str(corpus.get("path") or "")).expanduser()
            if not corpus_root.is_absolute():
                corpus_root = PROJECT_ROOT / corpus_root

            log_path = _resolve_path(cfg.tracing.tribrid_log_path)
            triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
            mine_mode = str(cfg.training.triplets_mine_mode or "replace").strip().lower()
            mine_reset = cfg.training.tribrid_reranker_mine_reset
            if mine_reset:
                mine_mode = "replace"
            if mine_mode not in {"replace", "append"}:
                mine_mode = "replace"

            with RERANKER_MINE_LATENCY_SECONDS.time():
                with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
                    result = await asyncio.to_thread(
                        mine_triplets,
                        log_path=log_path,
                        triplets_path=triplets_path,
                        mine_mode=mine_mode,  # type: ignore[arg-type]
                        corpus_id=cid,
                        eval_results=list(eval_run.results) if eval_run is not None else None,
                        eval_run_id=str(eval_run.run_id) if eval_run is not None else None,
                        negative_ratio=int(cfg.training.learning_reranker_negative_ratio),
                        preserve_existing_on_empty=not mine_reset,
                        corpus_root=corpus_root,
                    )
            created = int(result.get("triplets_mined") or 0)
            from_feedback = int(result.get("triplets_from_feedback") or 0)
            from_eval_run = int(result.get("triplets_from_eval_run") or 0)
            skipped_existing = int(result.get("triplets_skipped_existing") or 0)
            rejected_placeholder = int(result.get("triplets_rejected_placeholder") or 0)
            answer_leaks = int(result.get("negatives_rejected_answer_leak") or 0)
            unverifiable = int(result.get("negatives_rejected_unverifiable") or 0)
            without_answer = int(result.get("entries_without_answer_provenance") or 0)
            total_count = int(result.get("triplets_total") or 0)
            RERANKER_TRIPLETS_TOTAL.labels(kind="mined").inc(created)
            preserved_existing = bool(result.get("preserved_existing"))
            sources = (
                f"{from_feedback} written from {result.get('feedback_with_event_id', 0)} feedback events "
                f"({result.get('query_events', 0)} query events)"
            )
            if eval_run is not None:
                sources += (
                    f", {from_eval_run} written of {result.get('triplets_from_eval_run_candidates', 0)} hard-negative "
                    f"candidates from eval run {eval_run.run_id} ({len(eval_run.results)} results)"
                )
            else:
                sources += ", no persisted eval run for this corpus"
            extras = []
            if skipped_existing:
                extras.append(f"{skipped_existing} already on disk")
            if rejected_placeholder:
                extras.append(f"{rejected_placeholder} placeholder queries rejected")
            if answer_leaks:
                extras.append(f"{answer_leaks} negatives rejected for containing the expected answer")
            if unverifiable:
                extras.append(f"{unverifiable} candidates rejected because their document could not be read")
            if without_answer:
                extras.append(f"{without_answer} results carried no expected answer (leak check skipped)")
            suffix = f"; {', '.join(extras)}" if extras else ""
            if preserved_existing and created == 0:
                msg = (
                    f"Mined 0 new triplets ({sources}{suffix}); kept existing {total_count} triplets in "
                    f"{cfg.training.tribrid_triplets_path} (mode={mine_mode})."
                )
            else:
                msg = (
                    f"Mined {created} triplets ({sources}{suffix}) into {cfg.training.tribrid_triplets_path} "
                    f"(mode={mine_mode}; {total_count} rows now)."
                )

            async with _legacy_lock:
                _legacy_status.running = False
                _legacy_status.progress = 100
                _legacy_status.message = "Mining complete"
                _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=msg)
            RERANKER_MINE_RUNS_TOTAL.labels(outcome="ok").inc()
            _log_reranker_event(
                level="info",
                event="triplet_mine_complete",
                message=msg,
                fields={
                    "corpus_id": cid,
                    "triplets_mined": created,
                    "triplets_from_feedback": from_feedback,
                    "triplets_from_eval_run": from_eval_run,
                    "triplets_skipped_existing": skipped_existing,
                    "triplets_rejected_placeholder": rejected_placeholder,
                    "negatives_rejected_answer_leak": answer_leaks,
                    "negatives_rejected_unverifiable": unverifiable,
                    "entries_without_answer_provenance": without_answer,
                    "eval_run_id": str(eval_run.run_id) if eval_run is not None else None,
                    "query_events": int(result.get("query_events") or 0),
                    "feedback_events": int(result.get("feedback_with_event_id") or 0),
                    "mode": mine_mode,
                },
            )

            return RerankerMineResponse(
                ok=True,
                output=msg,
                error=None,
                triplets_mined=created,
                triplets_from_feedback=from_feedback,
                triplets_from_eval_run=from_eval_run,
                triplets_skipped_existing=skipped_existing,
                triplets_rejected_placeholder=rejected_placeholder,
                negatives_rejected_answer_leak=answer_leaks,
                negatives_rejected_unverifiable=unverifiable,
                entries_without_answer_provenance=without_answer,
                eval_run_id=str(eval_run.run_id) if eval_run is not None else None,
                triplets_total=total_count,
            )
        except HTTPException:
            raise
        except CorpusNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DependencyUnavailableError as exc:
            RERANKER_MINE_RUNS_TOTAL.labels(outcome="error").inc()
            raise dependency_unavailable_http_exception(
                exc.dependency, boundary="Reranker triplet mining", exc=exc
            ) from exc
        except TripletRowsCorruptError as exc:
            RERANKER_MINE_RUNS_TOTAL.labels(outcome="error").inc()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"The triplets file is corrupt and was not modified: {exc}. Repair or replace it, or enable "
                    "training.tribrid_reranker_mine_reset and mine again to rebuild it from scratch."
                ),
            ) from exc
        except Exception as e:
            RERANKER_MINE_RUNS_TOTAL.labels(outcome="error").inc()
            raise_postgres_unavailable_if_applicable(e, boundary="Reranker triplet mining")
            operator_hint = _operator_hint_for_stage(current_stage)
            RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage=current_stage).inc()
            _log_reranker_event(
                level="error",
                event="triplet_mine_failed",
                message=f"Triplet mining failed during stage={current_stage}: {e}",
                operator_hint=operator_hint,
                fields={"corpus_id": cid, "stage": current_stage},
            )
            raise HTTPException(status_code=500, detail=f"Triplet mining failed: {e}") from e
        finally:
            async with _legacy_lock:
                if _legacy_status.running:
                    _legacy_status.running = False
                    _legacy_status.progress = 0
                    _legacy_status.message = "Mining did not complete"


@router.post("/reranker/train", response_model=RerankerTrainLegacyResponse)
async def train_reranker(
    options: RerankerTrainLegacyRequest | None = None,
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerTrainLegacyResponse:
    """Start a learning reranker training run (background)."""
    cid = await _resolve_corpus_id(corpus_id)
    options = options or RerankerTrainLegacyRequest()

    payload: dict[str, Any] = {"repo_id": cid}
    if options.epochs is not None:
        try:
            payload["epochs"] = int(options.epochs)
        except Exception:
            pass
    if options.batch_size is not None:
        try:
            payload["batch_size"] = int(options.batch_size)
        except Exception:
            pass
    if options.max_length is not None:
        try:
            payload["max_length"] = int(options.max_length)
        except Exception:
            pass
    if options.lr is not None:
        try:
            payload["lr"] = float(options.lr)
        except Exception:
            pass
    if options.warmup_ratio is not None:
        try:
            payload["warmup_ratio"] = float(options.warmup_ratio)
        except Exception:
            pass
    req = RerankerTrainStartRequest.model_validate(payload)

    async with _legacy_lock:
        _legacy_status.running = False
        _legacy_status.progress = 0
        _legacy_status.task = "training"
        _legacy_status.message = "Starting training…"
        _legacy_status.result = None
        _legacy_status.live_output = []
        _legacy_status.run_id = None

    try:
        res = await start_train_run(req)
    except HTTPException as e:
        operator_hint = "Training start failed before the background job was queued; inspect the scoped config, active-run guard, and requested training parameters."
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.task = ""
            _legacy_status.message = "Training start failed"
            _legacy_status.result = RerankerLegacyTaskResult(
                ok=False,
                run_id=None,
                error=str(e.detail),
                operator_hint=operator_hint,
            )
            _legacy_status.run_id = None
        _log_reranker_event(
            level="warning",
            event="train_run_start_failed",
            message=f"Failed to queue reranker training run: {e.detail}",
            operator_hint=operator_hint,
            fields={"corpus_id": cid},
        )
        raise

    async with _legacy_lock:
        _legacy_status.running = True
        _legacy_status.run_id = res.run_id
        _legacy_status.message = f"Training run started: {res.run_id}"

    return RerankerTrainLegacyResponse(ok=True, output=f"Run started: {res.run_id}", run_id=res.run_id, error=None)


@router.post("/reranker/evaluate", response_model=RerankerEvaluateResponse)
async def evaluate_reranker(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerEvaluateResponse:
    """Evaluate the current learning reranker model (proxy metrics)."""
    cid = await _resolve_corpus_id(corpus_id)
    current_stage = "evaluate_active"
    async with _legacy_lock:
        _legacy_status.running = True
        _legacy_status.progress = 0
        _legacy_status.task = "evaluating"
        _legacy_status.message = "Evaluating model…"
        _legacy_status.result = None
        _legacy_status.live_output = []
        _legacy_status.run_id = None

    try:
        cfg = await load_scoped_config(repo_id=cid)
        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage="load_triplets").time():
            triplets = load_triplets(triplets_path)
        RERANKER_TRIPLETS_TOTAL.labels(kind="loaded").inc(len(triplets))
        if not triplets:
            raise RuntimeError(f"No triplets found at {cfg.training.tribrid_triplets_path}. Run /api/reranker/mine first.")

        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(cid)
            if corpus is None:
                raise RuntimeError(f"Corpus not found: {cid}")
        finally:
            await pg.disconnect()
        corpus_root = Path(str(corpus.get("path") or "")).expanduser()
        if not corpus_root.is_absolute():
            corpus_root = PROJECT_ROOT / corpus_root

        snippet_chars = int(getattr(cfg.reranking, "rerank_input_snippet_chars", 2000) or 2000)
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage="materialize_triplets").time():
            mats, mat_stats = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=snippet_chars)
        RERANKER_TRIPLETS_TOTAL.labels(kind="materialized").inc(int(mat_stats.get("triplets_out", 0) or 0))
        if not mats:
            raise RuntimeError("No usable triplets after materialization (missing/empty docs).")

        backend = resolve_learning_backend(
            cfg.training,
            artifact_path=str(getattr(cfg.training, "tribrid_reranker_model_path", "") or ""),
        )
        model_dir = await asyncio.to_thread(
            resolve_active_artifact_dir, _resolve_path(cfg.training.tribrid_reranker_model_path)
        )
        if model_dir is None:
            raise RuntimeError(
                f"No active reranker artifact is promoted under {cfg.training.tribrid_reranker_model_path}."
            )
        if backend != "mlx_qwen3":
            raise RuntimeError(f"unsupported learning reranker backend: {backend}")
        if not mlx_is_available():
            raise RuntimeError("MLX backend resolved but MLX is not installed")
        if not is_mlx_qwen3_artifact_compatible(
            artifact_dir=model_dir, base_model=str(cfg.training.learning_reranker_base_model)
        ):
            raise RuntimeError("Active artifact is not a compatible MLX Qwen3 adapter (manifest mismatch).")
        eval_t0 = time.perf_counter()
        with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
            metrics = await asyncio.to_thread(
                evaluate_mlx_qwen3_reranker,
                base_model=str(cfg.training.learning_reranker_base_model),
                adapter_dir=model_dir,
                triplets=mats,
                max_length=int(cfg.reranking.tribrid_reranker_maxlen),
                lora_rank=int(cfg.training.learning_reranker_lora_rank),
                lora_alpha=float(cfg.training.learning_reranker_lora_alpha),
                lora_dropout=float(cfg.training.learning_reranker_lora_dropout),
                lora_target_modules=list(cfg.training.learning_reranker_lora_target_modules),
            )
        RERANKER_EVAL_LATENCY_SECONDS.labels(phase="active").observe(time.perf_counter() - eval_t0)
        RERANKER_EVAL_RUNS_TOTAL.labels(phase="active", outcome="ok").inc()
        _set_last_metric_values(
            {
                "mrr": float(metrics.get("mrr") or 0.0),
                "ndcg": float(metrics.get("ndcg") or 0.0),
                "map": float(metrics.get("map") or 0.0),
            },
            phase="evaluate",
        )
        output = (
            f"Proxy metrics: backend={backend}\n"
            f"MRR: {metrics.get('mrr', 0.0):.4f}\n"
            f"nDCG: {metrics.get('ndcg', 0.0):.4f}\n"
            f"MAP: {metrics.get('map', 0.0):.4f}\n"
            f"Evaluated on {len(mats)} triplets\n"
        )

        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 100
            _legacy_status.message = "Evaluation complete"
            _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=output, metrics=metrics)
        _log_reranker_event(
            level="info",
            event="reranker_eval_complete",
            message="Evaluated the active reranker artifact.",
            fields={"corpus_id": cid, "backend": backend, "triplets": len(mats), "metrics": metrics},
        )
        return RerankerEvaluateResponse(ok=True, output=output, metrics=metrics, error=None)
    except Exception as e:
        operator_hint = _operator_hint_for_stage(current_stage)
        RERANKER_EVAL_RUNS_TOTAL.labels(phase="active", outcome="error").inc()
        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage=str(current_stage)).inc()
        _log_reranker_event(
            level="error",
            event="reranker_eval_failed",
            message=f"Active reranker evaluation failed during stage={current_stage}: {e}",
            operator_hint=operator_hint,
            fields={"corpus_id": cid, "stage": current_stage},
        )
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.message = "Evaluation failed"
            _legacy_status.result = RerankerLegacyTaskResult(ok=False, error=str(e), operator_hint=operator_hint)
        return RerankerEvaluateResponse(ok=False, output=None, metrics=None, error=str(e), operator_hint=operator_hint)


@router.get("/reranker/train/profile", response_model=CorpusEvalProfile)
async def get_train_profile(corpus_id: str = Query(..., description="Corpus identifier")) -> CorpusEvalProfile:
    cfg = await load_scoped_config(repo_id=corpus_id)
    default_k = min(int(cfg.reranking.tribrid_reranker_topn), 10)
    default_k = max(1, default_k)

    dataset = _load_dataset(corpus_id=corpus_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"No eval_dataset entries found for corpus_id={corpus_id}")

    eval_rows: list[dict[str, Any]] = []
    for entry in dataset:
        relevance = {p: 1 for p in (entry.expected_paths or [])}
        eval_rows.append({"query_id": entry.entry_id, "relevance": relevance})

    return infer_corpus_eval_profile(corpus_id, eval_rows, default_k)


@router.get("/reranker/train/runs", response_model=RerankerTrainRunsResponse)
async def list_train_runs(
    corpus_id: str | None = Query(default=None, description="Corpus identifier for corpus scope"),
    scope: Literal["corpus", "all"] = Query(default="corpus"),
    limit: int = Query(default=50, ge=1, le=200),
) -> RerankerTrainRunsResponse:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)

    if scope == "corpus":
        if not corpus_id:
            raise HTTPException(status_code=422, detail="Missing corpus_id")
        prefix = f"{corpus_id}__"
        candidates = [p for p in _RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    else:
        candidates = [p for p in _RUNS_DIR.iterdir() if p.is_dir()]

    metas: list[RerankerTrainRunMeta] = []
    for run_dir in candidates:
        path = run_dir / "run.json"
        if not path.exists():
            continue
        try:
            run = await reconcile_run(run_dir.name)
        except Exception:
            continue
        metas.append(
            RerankerTrainRunMeta(
                run_id=run.run_id,
                repo_id=run.repo_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                primary_metric=run.primary_metric,
                primary_k=run.primary_k,
                primary_metric_best=run.summary.primary_metric_best,
                primary_metric_final=run.summary.primary_metric_final,
                bundle_id=run.bundle_id,
                lineage_ref=run.lineage_ref,
            )
        )

    metas.sort(key=lambda m: m.started_at, reverse=True)
    return RerankerTrainRunsResponse(ok=True, runs=metas[: int(limit)])


@router.post("/reranker/train/start", response_model=RerankerTrainStartResponse)
async def start_train_run(request: RerankerTrainStartRequest) -> RerankerTrainStartResponse:
    corpus_id = request.repo_id

    active_run_id = await _active_run_id_for_corpus(corpus_id)
    if active_run_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"A training run is already active for corpus_id={corpus_id}: run_id={active_run_id}. "
                "Cancel the active run before starting a new one."
            ),
        )

    cfg = await load_scoped_config(repo_id=corpus_id)

    default_k = min(int(cfg.reranking.tribrid_reranker_topn), 10)
    default_k = max(1, default_k)

    dataset = _load_dataset(corpus_id=corpus_id)
    if dataset:
        eval_rows: list[dict[str, Any]] = []
        for entry in dataset:
            relevance = {p: 1 for p in (entry.expected_paths or [])}
            eval_rows.append({"query_id": entry.entry_id, "relevance": relevance})
        profile = infer_corpus_eval_profile(corpus_id, eval_rows, default_k)
    else:
        # Training can still run from mined triplets even if no eval_dataset exists.
        # Profile is used only to choose a stable "headline" metric at start.
        profile = CorpusEvalProfile(
            repo_id=corpus_id,
            label_kind="pairwise",
            avg_relevant_per_query=0.0,
            p95_relevant_per_query=0.0,
            recommended_metric="mrr",
            recommended_k=int(default_k),
            rationale="No eval_dataset entries found; using default metric selection (MRR).",
        )

    primary_metric = request.primary_metric or profile.recommended_metric
    primary_k = request.primary_k or profile.recommended_k

    started_at = datetime.now(UTC)
    run_id = _allocate_run_id(corpus_id, started_at)
    _mark_train_start_guard(corpus_id, run_id, at=started_at)
    current_bundle = ensure_current_bundle(
        repo_id=corpus_id,
        cfg=cfg,
        dataset_rows=[row.model_dump(mode="json", by_alias=True) for row in dataset],
        dataset_path=str(_dataset_path_for_corpus(corpus_id)),
    )

    run = RerankerTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="running",
        started_at=started_at,
        completed_at=None,
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric=primary_metric,
        primary_k=int(primary_k),
        metrics_available=[f"mrr@{int(primary_k)}", f"ndcg@{int(primary_k)}", "map"],
        metric_profile=profile,
        epochs=int(request.epochs) if request.epochs is not None else int(cfg.training.reranker_train_epochs),
        batch_size=int(request.batch_size)
        if request.batch_size is not None
        else int(cfg.training.reranker_train_batch),
        lr=float(request.lr) if request.lr is not None else float(cfg.training.reranker_train_lr),
        warmup_ratio=float(request.warmup_ratio)
        if request.warmup_ratio is not None
        else float(cfg.training.reranker_warmup_ratio),
        max_length=int(request.max_length)
        if request.max_length is not None
        else int(cfg.reranking.tribrid_reranker_maxlen),
        input_bundle_id=current_bundle.bundle_id,
    )

    # Persist immediately
    await asyncio.to_thread(_save_run, run)

    # Create empty metrics.jsonl
    metrics_path = _metrics_path(run_id)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_path.exists():
        metrics_path.write_text("", encoding="utf-8")
    diagnostics_path = _diagnostics_path(run_id)
    diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
    if not diagnostics_path.exists():
        diagnostics_path.write_text("", encoding="utf-8")

    # First event: record chosen metric/k (stable North Star)
    _append_event(
        run_id,
        RerankerTrainMetricEvent(
            type="state",
            ts=started_at,
            run_id=run_id,
            message=f"Primary metric locked: {primary_metric}@{int(primary_k)}",
            status=run.status,
        ),
    )

    _append_event(
        run_id,
        RerankerTrainMetricEvent(
            type="log",
            ts=datetime.now(UTC),
            run_id=run_id,
            message="Queued background training job.",
        ),
    )
    _append_diagnostic(
        run_id,
        level="info",
        event="train_run_queued",
        message="Queued reranker training run.",
        fields={
            "corpus_id": corpus_id,
            "primary_metric": str(primary_metric),
            "primary_k": int(primary_k),
            "epochs": int(run.epochs),
            "batch_size": int(run.batch_size),
            "lr": float(run.lr),
            "max_length": int(run.max_length),
        },
    )

    # Start background training (best-effort).
    if run_id not in _train_tasks:
        cancel_event = asyncio.Event()
        _train_cancel_events[run_id] = cancel_event
        _train_tasks[run_id] = asyncio.create_task(
            _run_train_job(run_id=run_id, corpus_id=corpus_id, cancel_event=cancel_event)
        )
        RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="started").inc()
        _sync_train_active_runs_gauge()

    # Refresh the guard at queue time so callers cannot double-submit a corpus
    # immediately after receiving a successful start response, even if the job
    # fails almost instantly in the background.
    _mark_train_start_guard(corpus_id, run_id)

    return RerankerTrainStartResponse(ok=True, run_id=run_id, run=run)


async def _request_train_run_cancel(*, run_id: str, reason: str) -> bool:
    """Request cancellation for a run and reconcile terminal state when needed.

    The in-process job is signalled on the loop; an orphan's cancellation is persisted off-loop.
    """
    # The event is set under the run's state lock, so a cancellation is linearized with the job's
    # completion: it lands before the in-lock check and wins, or the record is already terminal.
    async with _run_state_lock(run_id):
        try:
            stored = await asyncio.to_thread(_load_run, run_id)
        except HTTPException:
            return False
        if str(stored.status) in _TERMINAL_RUN_STATUSES:
            return True  # nothing to cancel; the terminal record is what the caller sees
        cancel_event = _train_cancel_events.get(run_id)
        if cancel_event is not None:
            cancel_event.set()

        # Active in-process job will observe cancel_event and terminate itself.
        if run_id in _train_tasks:
            return True

        # No in-memory task (orphan, or already stopped): persist the cancellation through the
        # shared finalizer, still under the lock, so the UI does not stay on running forever.
        cfg = _cfg_from_run_snapshot(stored)
        await asyncio.to_thread(
            _finalize_stored_run, stored, cfg, status="cancelled", message=str(reason)
        )
        return True


@router.post("/reranker/train/run/{run_id}/cancel", response_model=OkResponse)
async def cancel_train_run(run_id: str) -> OkResponse:
    run = await reconcile_run(run_id)
    if str(run.status) in {"completed", "failed", "cancelled"}:
        # Explicitly a no-op, not a fresh cancellation: the run already ended.
        return OkResponse(ok=True, message=f"Run already ended with status={run.status}; nothing to cancel.")

    await _request_train_run_cancel(
        run_id=run_id,
        reason="Cancellation requested by user.",
    )
    return OkResponse(ok=True)


@router.post("/reranker/stop", response_model=RerankerTrainLegacyResponse)
async def stop_reranker(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerTrainLegacyResponse:
    cid = await _resolve_corpus_id(corpus_id)
    active_run_id = await _active_run_id_for_corpus(cid)
    if not active_run_id:
        return RerankerTrainLegacyResponse(ok=True, output="No active training run to stop.", run_id=None, error=None)

    await _request_train_run_cancel(
        run_id=active_run_id,
        reason="Cancellation requested by user via /api/reranker/stop.",
    )

    async with _legacy_lock:
        if _legacy_status.task == "training" and (_legacy_status.run_id in {None, active_run_id}):
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.task = ""
            _legacy_status.message = "Training cancellation requested"
            _legacy_status.result = RerankerLegacyTaskResult(
                ok=False,
                run_id=active_run_id,
                error="cancelled",
            )

    return RerankerTrainLegacyResponse(
        ok=True,
        output=f"Cancellation requested for run: {active_run_id}",
        run_id=active_run_id,
        error=None,
    )


@router.get("/reranker/train/run/stream")
async def stream_train_run(
    request: Request,
    run_id: str = Query(..., description="Training run identifier"),
) -> StreamingResponse:
    """SSE stream for training run metrics.jsonl tail-following.

    IMPORTANT: This MUST be declared before `/reranker/train/run/{run_id}` or it will be
    shadowed by Starlette route matching (treating "stream" as a run_id).
    """

    # Ensure run exists (404 if missing)
    _load_run(run_id)

    metrics_path = _metrics_path(run_id)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_path.exists():
        metrics_path.write_text("", encoding="utf-8")

    async def _gen() -> AsyncIterator[str]:
        # Replay the last validated events so the UI can paint immediately; corruption in the
        # persisted stream is announced as an error event instead of being dropped.
        history, unreadable = await asyncio.to_thread(_load_events, run_id, 200)
        if unreadable.count:
            notice = RerankerTrainMetricEvent(
                type="error",
                ts=datetime.now(UTC),
                run_id=run_id,
                message=f"{unreadable.count} persisted metric record(s) could not be read ({unreadable.first_reason}).",
            )
            yield f"data: {json.dumps(notice.model_dump(mode='json', by_alias=True))}\n\n"
        for event in history:
            yield f"data: {json.dumps(event.model_dump(mode='json', by_alias=True))}\n\n"

        # Tail-follow appended lines.
        offset = 0
        try:
            offset = metrics_path.stat().st_size
        except Exception:
            offset = 0
        buf = b""

        while True:
            if await request.is_disconnected():
                return

            # Close when run completes (reconciled through the authority, never on load)
            try:
                run = await reconcile_run(run_id)
            except HTTPException:
                run = None
            if run is not None and run.status in {"completed", "failed", "cancelled"}:
                complete_event = RerankerTrainMetricEvent(
                    type="complete",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    status=run.status,
                )
                yield f"data: {json.dumps(complete_event.model_dump(mode='json', by_alias=True))}\n\n"
                return

            try:
                size = metrics_path.stat().st_size
            except Exception:
                size = 0

            if size < offset:
                offset = 0
                buf = b""

            if size > offset:
                try:
                    with metrics_path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset = size
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        payload = _sse_payload_for_line(run_id, raw_line)
                        if payload is None:
                            continue
                        yield f"data: {payload}\n\n"
                except Exception:
                    # Best-effort tail-following; keep connection alive.
                    pass

            await asyncio.sleep(1.0)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/reranker/train/run/{run_id}/metrics", response_model=RerankerTrainMetricsResponse)
async def get_train_run_metrics(run_id: str, limit: int = Query(default=500, ge=1, le=5000)) -> RerankerTrainMetricsResponse:
    _load_run(run_id)
    events, unreadable = await asyncio.to_thread(_load_events, run_id, int(limit))
    return RerankerTrainMetricsResponse(
        ok=True, events=events, unreadable_events=unreadable.count, unreadable_reason=unreadable.first_reason
    )


@router.get("/reranker/train/run/{run_id}/diagnostics", response_model=RerankerTrainDiagnosticsResponse)
async def get_train_run_diagnostics(
    run_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
) -> RerankerTrainDiagnosticsResponse:
    _load_run(run_id)
    return RerankerTrainDiagnosticsResponse(ok=True, records=_load_diagnostics(run_id, limit=int(limit)))


@router.get("/reranker/train/run/{run_id}/diagnostics/download")
async def download_train_run_diagnostics(run_id: str) -> FileResponse:
    _load_run(run_id)
    path = _diagnostics_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No diagnostics file found")
    return FileResponse(
        str(path),
        media_type="application/jsonl",
        filename=path.name,
    )


@router.get("/reranker/train/run/{run_id}", response_model=RerankerTrainRun)
async def get_train_run(run_id: str) -> RerankerTrainRun:
    return await reconcile_run(run_id)


@router.post("/reranker/train/run/{run_id}/promote", response_model=OkResponse)
async def promote_train_run(run_id: str) -> OkResponse:
    """Atomically promote a run artifact to the active learning reranker path."""
    run = await reconcile_run(run_id)
    if run.status != "completed":
        raise HTTPException(status_code=409, detail=f"Run is not finished (status={run.status})")

    src = _run_dir(run_id) / "model"
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Run artifact not found at {src}")

    cfg = await load_scoped_config(repo_id=str(run.repo_id))
    dst = _resolve_path(cfg.training.tribrid_reranker_model_path)
    src_manifest = read_manifest(src) or {}
    backend = str(src_manifest.get("backend") or "").strip().lower()
    if backend != "mlx_qwen3":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported reranker artifact backend for promotion: {backend or 'unknown'} (expected mlx_qwen3).",
        )

    def _prepare_staged(staged_dir: Path) -> None:
        # Versions are immutable once visible: refresh the manifest on the staged copy,
        # before the pointer switch, never on the published version.
        yes_token_id = src_manifest.get("yes_token_id")
        no_token_id = src_manifest.get("no_token_id")
        if isinstance(yes_token_id, int) and isinstance(no_token_id, int):
            write_mlx_manifest(
                out_dir=staged_dir,
                base_model=str(src_manifest.get("base_model") or cfg.training.learning_reranker_base_model),
                run_id=run_id,
                yes_token_id=int(yes_token_id),
                no_token_id=int(no_token_id),
            )

    def _finish_promotion() -> str | None:
        nonlocal run
        stored = _load_run(run_id)  # never the record loaded before the (long) copy
        run = _attach_lineage(stored, cfg, promoted=True)
        _save_run(run)
        return run.bundle_id

    try:
        with RERANKER_PROMOTION_LATENCY_SECONDS.time():
            async with _run_state_lock(run_id):
                leftover = await await_uncancellable(
                    run_promotion_transaction,
                    swap=VersionedArtifactSwap(
                        src, dst, run_id=run_id, prepare=_prepare_staged, promotion_recorded=_promotion_recorded
                    ),
                    repo_id=str(run.repo_id),
                    work=_finish_promotion,
                    invalidate=lambda: invalidate_mlx_qwen3_cache_sync(str(cfg.training.tribrid_reranker_model_path)),
                )
    except Exception as e:
        RERANKER_PROMOTIONS_TOTAL.labels(outcome="error").inc()
        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage="promote").inc()
        _append_diagnostic(
            run_id,
            level="error",
            event="manual_promotion_failed",
            message=f"Manual reranker promotion failed: {e}",
            operator_hint=_operator_hint_for_stage("promote"),
            fields={"active_path": str(dst), "artifact_path": str(src), "backend": backend},
        )
        raise HTTPException(status_code=500, detail=str(e)) from e

    # Committed: everything below is best-effort and can no longer turn the promotion into a 500.
    try:
        RERANKER_PROMOTIONS_TOTAL.labels(outcome="ok").inc()
        _append_diagnostic(
            run_id,
            level="info",
            event="manual_promotion_complete",
            message="Promoted reranker run artifact from the training API.",
            fields={
                "active_path": str(dst),
                "artifact_path": str(src),
                "backend": backend,
                "retained_previous_not_removed": str(leftover) if leftover is not None else None,
            },
        )
    except Exception as observability_failure:  # noqa: BLE001
        logger.warning(
            json.dumps(
                {
                    "event": "reranker_manual_promotion_diagnostic_failed",
                    "run_id": run_id,
                    "message": str(observability_failure),
                },
                sort_keys=True,
            )
        )
    return OkResponse(ok=True)


@router.post("/reranker/train/diff", response_model=RerankerTrainDiffResponse)
async def diff_train_runs(payload: RerankerTrainDiffRequest) -> RerankerTrainDiffResponse:
    baseline = _load_run(payload.baseline_run_id)
    current = _load_run(payload.current_run_id)

    if baseline.primary_metric != current.primary_metric or baseline.primary_k != current.primary_k:
        return RerankerTrainDiffResponse(
            ok=True,
            compatible=False,
            reason=(
                "Incompatible runs: primary_metric/primary_k differ "
                f"(baseline={baseline.primary_metric}@{baseline.primary_k}, current={current.primary_metric}@{current.primary_k})"
            ),
            primary_metric=None,
            primary_k=None,
        )

    primary_metric = baseline.primary_metric
    primary_k = baseline.primary_k

    baseline_events, baseline_unreadable = await asyncio.to_thread(_load_events, baseline.run_id)
    current_events, current_unreadable = await asyncio.to_thread(_load_events, current.run_id)

    baseline_best = (
        baseline.summary.primary_metric_best
        if baseline.summary.primary_metric_best is not None
        else _compute_primary_best_from_events(baseline, baseline_events)
    )
    current_best = (
        current.summary.primary_metric_best
        if current.summary.primary_metric_best is not None
        else _compute_primary_best_from_events(current, current_events)
    )

    baseline_ttb = (
        baseline.summary.time_to_best_secs
        if baseline.summary.time_to_best_secs is not None
        else _compute_time_to_best_secs_from_events(baseline, baseline_events)
    )
    current_ttb = (
        current.summary.time_to_best_secs
        if current.summary.time_to_best_secs is not None
        else _compute_time_to_best_secs_from_events(current, current_events)
    )

    baseline_stability = (
        baseline.summary.stability_stddev
        if baseline.summary.stability_stddev is not None
        else _compute_stability_stddev_from_events(baseline, baseline_events)
    )
    current_stability = (
        current.summary.stability_stddev
        if current.summary.stability_stddev is not None
        else _compute_stability_stddev_from_events(current, current_events)
    )

    delta_best = finite_or_none(current_best - baseline_best) if (current_best is not None and baseline_best is not None) else None
    delta_ttb = finite_or_none(current_ttb - baseline_ttb) if (current_ttb is not None and baseline_ttb is not None) else None
    delta_stability = (
        finite_or_none(current_stability - baseline_stability)
        if (current_stability is not None and baseline_stability is not None)
        else None
    )

    return RerankerTrainDiffResponse(
        ok=True,
        compatible=True,
        reason=None,
        primary_metric=primary_metric,
        primary_k=primary_k,
        baseline_primary_best=baseline_best,
        current_primary_best=current_best,
        delta_primary_best=delta_best,
        baseline_time_to_best_secs=baseline_ttb,
        current_time_to_best_secs=current_ttb,
        delta_time_to_best_secs=delta_ttb,
        baseline_stability_stddev=baseline_stability,
        current_stability_stddev=current_stability,
        delta_stability_stddev=delta_stability,
        baseline_unreadable_events=baseline_unreadable.count,
        current_unreadable_events=current_unreadable.count,
    )


@router.get("/reranker/logs/count", response_model=CountResponse)
async def get_logs_count(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> CountResponse:
    cid = await _resolve_corpus_id(corpus_id)
    cfg = await load_scoped_config(repo_id=cid)
    log_path = _resolve_safe_log_path(cfg.tracing.tribrid_log_path)
    return CountResponse(count=_count_lines(log_path))


@router.get("/reranker/triplets/count", response_model=CountResponse)
async def get_triplets_count(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> CountResponse:
    cid = await _resolve_corpus_id(corpus_id)
    cfg = await load_scoped_config(repo_id=cid)
    triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
    return CountResponse(count=_count_lines(triplets_path))


@router.get("/reranker/costs", response_model=RerankerCostsResponse)
async def get_costs() -> RerankerCostsResponse:
    # Placeholder until cost accounting is implemented.
    return RerankerCostsResponse(total_24h=0.0, avg_per_query=0.0)


@router.get("/reranker/nohits", response_model=RerankerNoHitsResponse)
async def get_nohits() -> RerankerNoHitsResponse:
    # Placeholder until we log no-hit events explicitly.
    return RerankerNoHitsResponse(queries=[])


@router.get("/reranker/logs", response_model=RerankerLogsResponse)
async def get_logs(
    limit: int = 200,
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerLogsResponse:
    cid = await _resolve_corpus_id(corpus_id)
    cfg = await load_scoped_config(repo_id=cid)
    log_path = _resolve_safe_log_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        return RerankerLogsResponse(logs=[])
    try:
        lines = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        lines = []
    tail = lines[-limit:]
    parsed: list[Any] = []
    for line in tail:
        try:
            parsed.append(json.loads(line))
        except Exception:
            parsed.append({"raw": line})
    return RerankerLogsResponse(logs=parsed)


@router.get("/reranker/logs/download")
async def download_logs(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> FileResponse:
    cid = await _resolve_corpus_id(corpus_id)
    cfg = await load_scoped_config(repo_id=cid)
    log_path = _resolve_safe_log_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No logs file found")
    return FileResponse(
        str(log_path),
        media_type="application/jsonl",
        filename=log_path.name,
    )


@router.post("/reranker/logs/clear", response_model=OkResponse)
async def clear_logs(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> OkResponse:
    cid = await _resolve_corpus_id(corpus_id)
    cfg = await load_scoped_config(repo_id=cid)
    log_path = _resolve_safe_log_path(cfg.tracing.tribrid_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return OkResponse(ok=True)


@router.post("/reranker/promote")
async def promote_model(run_id: str = Query(..., description="Training run id to promote")) -> OkResponse:
    """Legacy promote endpoint (use /reranker/train/run/{run_id}/promote)."""
    await promote_train_run(run_id)
    return OkResponse(ok=True)
