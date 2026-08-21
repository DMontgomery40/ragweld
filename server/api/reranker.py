from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.api.dataset import _dataset_path_for_corpus, _load_dataset
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
    clear_mlx_qwen3_cache,
    is_mlx_qwen3_artifact_compatible,
    mlx_is_available,
    read_manifest,
    read_manifest_backend,
    write_mlx_manifest,
)
from server.retrieval.rerank import resolve_learning_backend
from server.services.config_store import CorpusNotFoundError, get_config as load_scoped_config
from server.training.metric_policy import infer_corpus_eval_profile
from server.training.mlx_qwen3_trainer import (
    TrainingCancelledError,
    deterministic_split,
    evaluate_mlx_qwen3_reranker,
    train_qwen3_lora_reranker,
)
from server.training.reranker_trainer import (
    load_triplets,
    materialize_triplets,
)
from server.training.triplet_miner import mine_triplets_from_query_log

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


def _atomic_copy_dir(src: Path, dst: Path) -> None:
    """Atomically replace dst with a copied version of src.

    Uses rename swaps inside dst.parent to avoid readers seeing partial trees.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(datetime.now(UTC).timestamp())}_{os.getpid()}"
    tmp = dst.parent / f".tmp_{dst.name}_{stamp}"
    bak = dst.parent / f".bak_{dst.name}_{stamp}"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(bak, ignore_errors=True)
    shutil.copytree(src, tmp, dirs_exist_ok=True)
    if dst.exists():
        dst.rename(bak)
    tmp.rename(dst)
    shutil.rmtree(bak, ignore_errors=True)


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


def _maybe_reconcile_run(run: RerankerTrainRun) -> RerankerTrainRun:
    """Reconcile persisted run.json with metrics.jsonl and in-process task state.

    This is intentionally conservative: it fixes known "stub" runs and obvious
    orphaned runs (e.g. server restart) so the UI doesn't show them as running
    forever.
    """
    if run.status != "running":
        return run

    last = _read_last_event(run.run_id)
    msg = str(getattr(last, "message", "") or "")
    now = datetime.now(UTC)

    # 1) Legacy stub runs: never actually trained, but were persisted as running.
    if "Training task is a stub" in msg:
        run.status = "cancelled"
        run.completed_at = now
        _save_run(run)
        _append_event(
            run.run_id,
            RerankerTrainMetricEvent(
                type="state",
                ts=now,
                run_id=run.run_id,
                status=run.status,
                message="Reconciled legacy stub run (no training ever started).",
            ),
        )
        _append_event(run.run_id, RerankerTrainMetricEvent(type="complete", ts=now, run_id=run.run_id, status=run.status))
        return run

    # 2) If the metrics stream already has a terminal status, persist it.
    terminal = str(getattr(last, "status", "") or "").strip().lower()
    if getattr(last, "type", None) == "complete" and terminal in {"completed", "failed", "cancelled"}:
        run.status = terminal  # type: ignore[assignment]
        if run.completed_at is None:
            run.completed_at = getattr(last, "ts", None) or now
        _save_run(run)
        return run

    # 3) Orphaned runs: marked running, but no in-process task is tracking them.
    #    This commonly happens after a server restart (tasks are in-memory only).
    #    Avoid false positives by requiring long inactivity in metrics.
    if run.run_id not in _train_tasks:
        last_ts = getattr(last, "ts", None) if last is not None else None
        anchor = last_ts or run.started_at
        try:
            idle_secs = float((now - anchor).total_seconds())
        except Exception:
            idle_secs = 0.0

        # If there's been no event for a long time, treat this as orphaned.
        if idle_secs >= 2 * 60 * 60:
            run.status = "cancelled"
            run.completed_at = now
            _save_run(run)
            _append_event(
                run.run_id,
                RerankerTrainMetricEvent(
                    type="error",
                    ts=now,
                    run_id=run.run_id,
                    status=run.status,
                    message="Reconciled orphaned run (no active task; likely backend restart).",
                ),
            )
            _append_event(
                run.run_id, RerankerTrainMetricEvent(type="complete", ts=now, run_id=run.run_id, status=run.status)
            )

    return run


def _load_run(run_id: str) -> RerankerTrainRun:
    path = _run_json_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read train run: {e}") from e
    run = RerankerTrainRun.model_validate(raw)
    return _maybe_reconcile_run(run)


def _save_run(run: RerankerTrainRun) -> None:
    path = _run_json_path(run.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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


def _load_events(run_id: str, limit: int | None = None) -> list[RerankerTrainMetricEvent]:
    path = _metrics_path(run_id)
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    out: list[RerankerTrainMetricEvent] = []
    for line in lines:
        try:
            out.append(RerankerTrainMetricEvent.model_validate(json.loads(line)))
        except Exception:
            continue
    return out


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
            return float((ev.ts - run.started_at).total_seconds())
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
    if not vals:
        return None
    tail = vals[-5:]
    if len(tail) == 1:
        return 0.0
    mean = sum(tail) / len(tail)
    var = sum((x - mean) ** 2 for x in tail) / len(tail)
    return float(math.sqrt(var))


def _allocate_run_id(repo_id: str, started_at: datetime) -> str:
    base = f"{repo_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_id = base
    n = 0
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    while (_RUNS_DIR / run_id).exists():
        n += 1
        run_id = f"{base}__{n}"
    return run_id


def _format_metrics_for_run(run: RerankerTrainRun, raw: dict[str, float]) -> dict[str, float]:
    """Map raw proxy metrics {mrr,ndcg,map} to run metrics keys."""
    k = int(run.primary_k)
    return {
        f"mrr@{k}": float(raw.get("mrr") or 0.0),
        f"ndcg@{k}": float(raw.get("ndcg") or 0.0),
        "map": float(raw.get("map") or 0.0),
    }


def _primary_value(run: RerankerTrainRun, metrics: dict[str, float]) -> float:
    key = f"{run.primary_metric}@{int(run.primary_k)}" if run.primary_metric != "map" else "map"
    return float(metrics.get(key) or 0.0)


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
            triplets = load_triplets(triplets_path)
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
            mats, mat_stats = materialize_triplets(
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

        train_triplets, dev_triplets = deterministic_split(mats, dev_split=0.1, seed=0)
        RERANKER_TRIPLETS_TOTAL.labels(kind="train_split").inc(len(train_triplets))
        RERANKER_TRIPLETS_TOTAL.labels(kind="dev_split").inc(len(dev_triplets))
        active_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
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
        if dev_triplets and active_dir.exists():
            _raise_if_cancelled()
            manifest_backend = read_manifest_backend(active_dir)
            if not manifest_backend:
                _emit_log("Baseline eval skipped (active artifact manifest missing; treating as no baseline).")
            elif str(manifest_backend) != str(backend):
                _emit_log(
                    f"Baseline eval skipped (active manifest backend={manifest_backend} != resolved backend={backend})."
                )
            elif backend == "mlx_qwen3":
                if not is_mlx_qwen3_artifact_compatible(artifact_dir=active_dir, base_model=str(base_model)):
                    _emit_log("Baseline eval skipped (active artifact is missing or incompatible with mlx_qwen3).")
                else:
                    try:
                        current_stage = "baseline_eval"
                        baseline_t0 = time.perf_counter()
                        raw_baseline = await asyncio.to_thread(
                            evaluate_mlx_qwen3_reranker,
                            base_model=str(base_model),
                            adapter_dir=active_dir,
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
                        _set_last_metric_values(baseline_metrics, phase="baseline")
                        RERANKER_EVAL_RUNS_TOTAL.labels(phase="baseline", outcome="ok").inc()
                        _append_diagnostic(
                            run_id,
                            level="info",
                            event="baseline_eval_complete",
                            message="Completed baseline evaluation against the active reranker artifact.",
                            fields={
                                "baseline_primary": float(baseline_primary),
                                "dev_triplets": int(len(dev_triplets)),
                                "backend": str(backend),
                                "metrics": baseline_metrics,
                            },
                        )
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
                        _emit_log(f"Baseline eval failed ({backend}); treating baseline as unknown. error={e}")
                        baseline_primary = None
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

                metrics: dict[str, float] | None = None
                raw_metrics = payload.get("metrics")
                if isinstance(raw_metrics, dict):
                    m: dict[str, float] = {}
                    for k, v in raw_metrics.items():
                        try:
                            m[str(k)] = float(v)
                        except Exception:
                            continue
                    metrics = m or None

                _append_event(
                    run_id,
                    RerankerTrainMetricEvent(
                        type="progress",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        percent=float(payload.get("percent") or 0.0) or None,
                        message=str(payload.get("message") or ""),
                        metrics=metrics,
                    ),
                )
                return
            if event_type == "metrics":
                raw = payload.get("metrics") or {}
                if isinstance(raw, dict):
                    metrics = _format_metrics_for_run(run, {str(k): float(v) for k, v in raw.items()})
                else:
                    metrics = _format_metrics_for_run(run, {})
                pv = _primary_value(run, metrics)
                primary_series.append(float(pv))
                if best_primary is None or pv > best_primary:
                    best_primary = float(pv)
                    best_step = int(payload.get("step") or 0) or None
                    best_ts = ts
                _append_event(
                    run_id,
                    RerankerTrainMetricEvent(
                        type="metrics",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        metrics=metrics,
                    ),
                )
                return
            if event_type == "telemetry":
                proj_x_raw = payload.get("proj_x")
                proj_y_raw = payload.get("proj_y")
                loss_raw = payload.get("loss")
                lr_raw = payload.get("lr")
                grad_norm_raw = payload.get("grad_norm")
                step_time_ms_raw = payload.get("step_time_ms")
                sample_count_raw = payload.get("sample_count")
                _append_event(
                    run_id,
                    RerankerTrainMetricEvent(
                        type="telemetry",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        proj_x=float(proj_x_raw) if proj_x_raw is not None else None,
                        proj_y=float(proj_y_raw) if proj_y_raw is not None else None,
                        loss=float(loss_raw) if loss_raw is not None else None,
                        lr=float(lr_raw) if lr_raw is not None else None,
                        grad_norm=float(grad_norm_raw) if grad_norm_raw is not None else None,
                        step_time_ms=float(step_time_ms_raw) if step_time_ms_raw is not None else None,
                        sample_count=int(sample_count_raw) if sample_count_raw is not None else None,
                    ),
                )
                return

        # Mark run as running (in case a previous stub left it inconsistent).
        _raise_if_cancelled()
        run.status = "running"
        _save_run(run)
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
            proxy = {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}
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
        _set_last_metric_values(metrics, phase="final")
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="metrics", ts=datetime.now(UTC), run_id=run_id, metrics=metrics),
        )
        pv = _primary_value(run, metrics)
        primary_series.append(float(pv))
        _append_diagnostic(
            run_id,
            level="info",
            event="final_eval_complete",
            message="Evaluated the newly trained reranker artifact on the held-out dev split.",
            fields={
                "backend": str(backend),
                "dev_triplets": int(len(dev_triplets)),
                "primary_value": float(pv),
                "metrics": metrics,
            },
        )

        # Promote trained artifact to the active path (atomic), gated on improvement when configured.
        promote_if_improves = cfg.training.learning_reranker_promote_if_improves
        eps = float(cfg.training.learning_reranker_promote_epsilon or 0.0)
        should_promote = True
        if promote_if_improves and baseline_primary is not None:
            should_promote = bool(pv > (baseline_primary + eps))

        _raise_if_cancelled()
        if should_promote:
            current_stage = "promote"
            with RERANKER_PROMOTION_LATENCY_SECONDS.time():
                _atomic_copy_dir(model_artifact_dir, active_dir)
                await clear_mlx_qwen3_cache(str(active_dir))
            RERANKER_PROMOTIONS_TOTAL.labels(outcome="promoted").inc()
            _append_diagnostic(
                run_id,
                level="info",
                event="promotion_complete",
                message="Promoted the trained reranker artifact to the active path.",
                fields={
                    "active_path": str(active_dir),
                    "artifact_path": str(model_artifact_dir),
                    "backend": str(backend),
                    "primary_value": float(pv),
                },
            )
            _emit_log(
                f"Promoted trained artifact to {cfg.training.tribrid_reranker_model_path} (backend={backend}). "
                f"Run artifact preserved at {model_artifact_dir}."
            )
        else:
            RERANKER_PROMOTIONS_TOTAL.labels(outcome="skipped").inc()
            _append_diagnostic(
                run_id,
                level="info",
                event="promotion_skipped",
                message="Skipped promotion because the trained artifact did not beat the baseline gate.",
                fields={
                    "backend": str(backend),
                    "primary_value": float(pv),
                    "baseline_primary": float(baseline_primary) if baseline_primary is not None else None,
                    "epsilon": float(eps),
                },
            )
            _emit_log(
                f"Did not promote: primary={pv:.6f} baseline={baseline_primary:.6f} eps={eps:.6f} (backend={backend}). "
                f"Run artifact preserved at {model_artifact_dir}."
            )

        # Populate summary.
        run.summary.primary_metric_best = float(best_primary or pv)
        run.summary.primary_metric_final = float(pv)
        run.summary.best_step = int(best_step or 0) or None
        if best_ts is not None:
            run.summary.time_to_best_secs = float((best_ts - run.started_at).total_seconds())
        tail = primary_series[-5:]
        if tail:
            mean = sum(tail) / len(tail)
            var = sum((x - mean) ** 2 for x in tail) / len(tail)
            run.summary.stability_stddev = float(math.sqrt(var))

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run = _attach_lineage(run, cfg, promoted=bool(should_promote))
        _save_run(run)
        RERANKER_TRAIN_RUNS_TOTAL.labels(outcome="completed").inc()
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
                "primary_metric_best": float(run.summary.primary_metric_best or pv),
                "primary_metric_final": float(run.summary.primary_metric_final or pv),
                "best_step": int(run.summary.best_step or 0) or None,
                "stability_stddev": float(run.summary.stability_stddev or 0.0),
                "promoted": bool(should_promote),
            },
        )

        async with _legacy_lock:
            if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                _legacy_status.running = False
                _legacy_status.progress = 100
                _legacy_status.message = "Training complete"
                _legacy_status.result = RerankerLegacyTaskResult(ok=True, run_id=run_id)

    except TrainingCancelledError as e:
        try:
            run = _load_run(run_id)
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            if cfg is not None:
                run = _attach_lineage(run, cfg)
            _save_run(run)
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
            try:
                run = _load_run(run_id)
                run.status = "cancelled"
                run.completed_at = datetime.now(UTC)
                if cfg is not None:
                    run = _attach_lineage(run, cfg)
                _save_run(run)
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
            try:
                run = _load_run(run_id)
                run.status = "failed"
                run.completed_at = datetime.now(UTC)
                if cfg is not None:
                    run = _attach_lineage(run, cfg)
                _save_run(run)
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


async def _run_mine_job(*, corpus_id: str) -> None:
    try:
        cfg = await load_scoped_config(repo_id=corpus_id)
        log_path = _resolve_path(cfg.tracing.tribrid_log_path)
        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        triplets_path.parent.mkdir(parents=True, exist_ok=True)

        if not log_path.exists():
            msg = f"No log file found at {cfg.tracing.tribrid_log_path} (0 triplets mined)."
            async with _legacy_lock:
                _legacy_status.running = False
                _legacy_status.progress = 100
                _legacy_status.message = msg
                _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=msg)
            return

        mine_mode = str(cfg.training.triplets_mine_mode or "replace").strip().lower()
        mine_reset = cfg.training.tribrid_reranker_mine_reset
        if mine_reset:
            mine_mode = "replace"
        if mine_mode not in {"replace", "append"}:
            mine_mode = "replace"

        result = await asyncio.to_thread(
            mine_triplets_from_query_log,
            log_path=log_path,
            triplets_path=triplets_path,
            mine_mode=mine_mode,  # type: ignore[arg-type]
            corpus_id=corpus_id,
            preserve_existing_on_empty=not mine_reset,
        )
        created = int(result.get("triplets_mined") or 0)
        preserved_existing = bool(result.get("preserved_existing"))
        if preserved_existing and created == 0:
            current_count = _count_lines(triplets_path)
            msg = (
                f"Mined 0 new triplets from {result.get('feedback_with_event_id', 0)} feedback events "
                f"({result.get('query_events', 0)} query events); kept existing {current_count} triplets in "
                f"{cfg.training.tribrid_triplets_path} (mode={mine_mode})."
            )
        else:
            msg = (
                f"Mined {created} triplets from {result.get('feedback_with_event_id', 0)} feedback events "
                f"({result.get('query_events', 0)} query events) into {cfg.training.tribrid_triplets_path} "
                f"(mode={mine_mode})."
            )

        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 100
            _legacy_status.message = "Mining complete"
            _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=msg)

    except Exception as e:
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.message = "Mining failed"
            _legacy_status.result = RerankerLegacyTaskResult(ok=False, error=str(e))


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
        model_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
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


def _active_run_id_for_corpus(corpus_id: str) -> str | None:
    """Return a currently-running run_id for a corpus (best-effort)."""
    cid = str(corpus_id or "").strip()
    if not cid:
        return None
    guard = _train_start_guard.get(cid)
    if guard:
        run_id, started_at = guard
        try:
            run = _load_run(run_id)
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
            run = _load_run(entry.name)
        except Exception:
            continue
        if str(run.status) == "running":
            return str(run.run_id)
    return None


def _status_from_persisted_run(*, corpus_id: str) -> RerankerLegacyStatus | None:
    """Synthesize a legacy polling status from persisted training run files.

    This avoids process-local drift under multi-worker servers: the UI polls
    `/reranker/status`, but the background job may be running in a different
    worker process.
    """
    run_id = _latest_run_id_for_corpus(corpus_id)
    if not run_id:
        return None

    try:
        run = _load_run(run_id)
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
        derived = _status_from_persisted_run(corpus_id=str(corpus_id).strip())
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

    return RerankerInfoResponse(
        enabled=enabled,
        reranker_mode=mode,
        reranker_cloud_provider=cfg.reranking.reranker_cloud_provider,
        reranker_cloud_model=cfg.reranking.reranker_cloud_model,
        path=str(path or ""),
        resolved_path=str(path or ""),
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

    adapter_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
    if not adapter_dir.exists():
        return RerankerScoreResponse(
            ok=False,
            backend="mlx_qwen3",
            error=f"active adapter dir not found: {cfg.training.tribrid_reranker_model_path}",
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


@router.post("/reranker/mine", response_model=RerankerMineResponse)
async def mine_triplets(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerMineResponse:
    """Mine triplets from query logs + feedback into training.tribrid_triplets_path."""
    cid = (corpus_id or "").strip() or None
    current_stage = "mine_triplets"
    async with _legacy_lock:
        _legacy_status.running = True
        _legacy_status.progress = 0
        _legacy_status.task = "mining"
        _legacy_status.message = "Mining triplets…"
        _legacy_status.result = None
        _legacy_status.live_output = []
        _legacy_status.run_id = None

    if cid:
        cfg = await load_scoped_config(repo_id=cid)
    else:
        # Back-compat: allow mining without a corpus scope (writes to global paths).
        cfg = load_config()
    try:
        log_path = _resolve_path(cfg.tracing.tribrid_log_path)
        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        triplets_path.parent.mkdir(parents=True, exist_ok=True)

        if not log_path.exists():
            msg = f"No log file found at {cfg.tracing.tribrid_log_path} (0 triplets mined)."
            async with _legacy_lock:
                _legacy_status.running = False
                _legacy_status.progress = 100
                _legacy_status.message = msg
                _legacy_status.result = RerankerLegacyTaskResult(ok=True, output=msg)
            RERANKER_MINE_RUNS_TOTAL.labels(outcome="ok").inc()
            _log_reranker_event(
                level="info",
                event="triplet_mine_skipped_no_log",
                message=msg,
                operator_hint=_operator_hint_for_stage("mine_triplets"),
                fields={"corpus_id": cid},
            )
            return RerankerMineResponse(ok=True, output=msg, error=None, operator_hint=_operator_hint_for_stage("mine_triplets"))

        mine_mode = str(cfg.training.triplets_mine_mode or "replace").strip().lower()
        mine_reset = cfg.training.tribrid_reranker_mine_reset
        if mine_reset:
            mine_mode = "replace"
        if mine_mode not in {"replace", "append"}:
            mine_mode = "replace"

        with RERANKER_MINE_LATENCY_SECONDS.time():
            with RERANKER_TRAIN_STAGE_LATENCY_SECONDS.labels(stage=current_stage).time():
                result = await asyncio.to_thread(
                    mine_triplets_from_query_log,
                    log_path=log_path,
                    triplets_path=triplets_path,
                    mine_mode=mine_mode,  # type: ignore[arg-type]
                    corpus_id=cid,
                    preserve_existing_on_empty=not mine_reset,
                )
        created = int(result.get("triplets_mined") or 0)
        RERANKER_TRIPLETS_TOTAL.labels(kind="mined").inc(created)
        preserved_existing = bool(result.get("preserved_existing"))
        if preserved_existing and created == 0:
            current_count = _count_lines(triplets_path)
            msg = (
                f"Mined 0 new triplets from {result.get('feedback_with_event_id', 0)} feedback events "
                f"({result.get('query_events', 0)} query events); kept existing {current_count} triplets in "
                f"{cfg.training.tribrid_triplets_path} (mode={mine_mode})."
            )
        else:
            msg = (
                f"Mined {created} triplets from {result.get('feedback_with_event_id', 0)} feedback events "
                f"({result.get('query_events', 0)} query events) into {cfg.training.tribrid_triplets_path} "
                f"(mode={mine_mode})."
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
                "query_events": int(result.get("query_events") or 0),
                "feedback_events": int(result.get("feedback_with_event_id") or 0),
                "mode": mine_mode,
            },
        )

        return RerankerMineResponse(ok=True, output=msg, error=None)
    except Exception as e:
        operator_hint = _operator_hint_for_stage(current_stage)
        RERANKER_MINE_RUNS_TOTAL.labels(outcome="error").inc()
        RERANKER_TRAIN_STAGE_ERRORS_TOTAL.labels(stage=current_stage).inc()
        _log_reranker_event(
            level="error",
            event="triplet_mine_failed",
            message=f"Triplet mining failed during stage={current_stage}: {e}",
            operator_hint=operator_hint,
            fields={"corpus_id": cid, "stage": current_stage},
        )
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.message = "Mining failed"
            _legacy_status.result = RerankerLegacyTaskResult(ok=False, error=str(e), operator_hint=operator_hint)
        return RerankerMineResponse(ok=False, output=None, error=str(e), operator_hint=operator_hint)


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
        model_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
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
            run = RerankerTrainRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            run = _maybe_reconcile_run(run)
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

    active_run_id = _active_run_id_for_corpus(corpus_id)
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
    _save_run(run)

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


def _request_train_run_cancel(*, run_id: str, reason: str) -> bool:
    """Request cancellation for a run and reconcile terminal state when needed."""
    cancel_event = _train_cancel_events.get(run_id)
    if cancel_event is not None:
        cancel_event.set()

    # Active in-process job will observe cancel_event and terminate itself.
    if run_id in _train_tasks:
        return True

    # No in-memory task (orphan / already stopped). Persist cancellation so UI
    # does not remain stuck in running forever.
    try:
        run = _load_run(run_id)
    except HTTPException:
        return False

    if run.status != "running":
        return True

    now = datetime.now(UTC)
    run.status = "cancelled"
    run.completed_at = now
    _save_run(run)
    _append_event(
        run_id,
        RerankerTrainMetricEvent(
            type="state",
            ts=now,
            run_id=run_id,
            status="cancelled",
            message=str(reason),
        ),
    )
    _append_event(
        run_id,
        RerankerTrainMetricEvent(
            type="complete",
            ts=now,
            run_id=run_id,
            status="cancelled",
        ),
    )
    return True


@router.post("/reranker/train/run/{run_id}/cancel", response_model=OkResponse)
async def cancel_train_run(run_id: str) -> OkResponse:
    run = _load_run(run_id)
    if str(run.status) in {"completed", "failed", "cancelled"}:
        return OkResponse(ok=True)

    _request_train_run_cancel(
        run_id=run_id,
        reason="Cancellation requested by user.",
    )
    return OkResponse(ok=True)


@router.post("/reranker/stop", response_model=RerankerTrainLegacyResponse)
async def stop_reranker(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerTrainLegacyResponse:
    cid = await _resolve_corpus_id(corpus_id)
    active_run_id = _active_run_id_for_corpus(cid)
    if not active_run_id:
        return RerankerTrainLegacyResponse(ok=True, output="No active training run to stop.", run_id=None, error=None)

    _request_train_run_cancel(
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
        # Replay last N lines so UI can paint immediately.
        try:
            lines = [ln for ln in metrics_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            lines = []
        for line in lines[-200:]:
            yield f"data: {line}\n\n"

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

            # Close when run completes
            try:
                run = _load_run(run_id)
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
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line:
                            continue
                        yield f"data: {line}\n\n"
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
    events = _load_events(run_id, limit=int(limit))
    return RerankerTrainMetricsResponse(ok=True, events=events)


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
    return _load_run(run_id)


@router.post("/reranker/train/run/{run_id}/promote", response_model=OkResponse)
async def promote_train_run(run_id: str) -> OkResponse:
    """Atomically promote a run artifact to the active learning reranker path."""
    run = _load_run(run_id)
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

    try:
        with RERANKER_PROMOTION_LATENCY_SECONDS.time():
            _atomic_copy_dir(src, dst)
            yes_token_id = src_manifest.get("yes_token_id")
            no_token_id = src_manifest.get("no_token_id")
            if isinstance(yes_token_id, int) and isinstance(no_token_id, int):
                write_mlx_manifest(
                    out_dir=dst,
                    base_model=str(src_manifest.get("base_model") or cfg.training.learning_reranker_base_model),
                    run_id=run_id,
                    yes_token_id=int(yes_token_id),
                    no_token_id=int(no_token_id),
                )
            await clear_mlx_qwen3_cache(str(cfg.training.tribrid_reranker_model_path))
        run = _attach_lineage(run, cfg, promoted=True)
        _save_run(run)
        RERANKER_PROMOTIONS_TOTAL.labels(outcome="ok").inc()
        _append_diagnostic(
            run_id,
            level="info",
            event="manual_promotion_complete",
            message="Promoted reranker run artifact from the training API.",
            fields={"active_path": str(dst), "artifact_path": str(src), "backend": backend},
        )
        return OkResponse(ok=True)
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

    baseline_events = _load_events(baseline.run_id)
    current_events = _load_events(current.run_id)

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

    delta_best = (current_best - baseline_best) if (current_best is not None and baseline_best is not None) else None
    delta_ttb = (current_ttb - baseline_ttb) if (current_ttb is not None and baseline_ttb is not None) else None
    delta_stability = (
        (current_stability - baseline_stability)
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
