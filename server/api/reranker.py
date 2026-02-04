from __future__ import annotations

import asyncio
import json
import math
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from server.api.dataset import _load_dataset
from server.config import load_config
from server.models.training_eval import (
    CorpusEvalProfile,
    RerankerTrainMetricEvent,
    RerankerTrainRun,
    RerankerTrainRunMeta,
    RerankerTrainRunsResponse,
    RerankerTrainStartRequest,
)
from server.models.tribrid_config_model import (
    RerankerTrainDiffRequest,
    RerankerTrainDiffResponse,
    RerankerTrainMetricsResponse,
    RerankerTrainStartResponse,
    RerankerClickRequest,
    CountResponse,
    OkResponse,
    RerankerCostsResponse,
    RerankerEvaluateResponse,
    RerankerInfoResponse,
    RerankerLegacyTask,
    RerankerLegacyTaskResult,
    RerankerLegacyStatus,
    RerankerLogsResponse,
    RerankerMineResponse,
    RerankerNoHitsResponse,
    RerankerTrainLegacyRequest,
    RerankerTrainLegacyResponse,
)
from server.db.postgres import PostgresClient
from server.services.config_store import get_config as load_scoped_config
from server.training.metric_policy import infer_corpus_eval_profile
from server.training.reranker_trainer import load_triplets, materialize_triplets, train_pairwise_reranker, evaluate_pairwise_reranker
from server.training.triplet_miner import mine_triplets_from_query_log
from server.retrieval.rerank import resolve_reranker_device

router = APIRouter(tags=["reranker"])

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
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".tmp_{dst.name}"
    shutil.rmtree(tmp, ignore_errors=True)
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, dirs_exist_ok=True)
    shutil.rmtree(dst, ignore_errors=True)
    tmp.rename(dst)


@router.post("/reranker/click", response_model=OkResponse)
async def track_click(
    payload: RerankerClickRequest,
    request: Request,
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope for logging"),
) -> OkResponse:
    """Record a document click for triplet mining.

    Expected payload: {"event_id": str, "doc_id": str}
    """
    if not _is_test_request(request):
        try:
            from server.observability.query_log import append_feedback_log

            cfg = None
            if corpus_id and corpus_id.strip():
                try:
                    cfg = await load_scoped_config(repo_id=corpus_id.strip())
                except Exception:
                    cfg = None
            if cfg is None:
                cfg = load_config()
            await append_feedback_log(cfg, event_id=payload.event_id, signal="click", doc_id=payload.doc_id)
        except Exception:
            pass

    return OkResponse(ok=True)


def _run_dir(run_id: str) -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR / run_id


def _run_json_path(run_id: str) -> Path:
    return _run_dir(run_id) / "run.json"


def _metrics_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metrics.jsonl"


def _load_run(run_id: str) -> RerankerTrainRun:
    path = _run_json_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read train run: {e}") from e
    return RerankerTrainRun.model_validate(raw)


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


async def _run_train_job(*, run_id: str, corpus_id: str) -> None:
    """Background training job for /reranker/train/start.

    Uses:
    - Triplets mined into cfg.training.tribrid_triplets_path (JSONL)
    - Base model from cfg.reranking.reranker_local_model
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

    try:
        cfg = await load_scoped_config(repo_id=corpus_id)

        triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
        triplets = load_triplets(triplets_path)
        if not triplets:
            raise RuntimeError(f"No triplets found at {cfg.training.tribrid_triplets_path}. Run /api/reranker/mine first.")

        min_count = int(cfg.training.triplets_min_count or 0)
        if min_count > 0 and len(triplets) < min_count:
            raise RuntimeError(
                f"Not enough triplets to train (have {len(triplets)}, need >= {min_count}). "
                "Mine more (or lower training.triplets_min_count)."
            )

        base_model = str(cfg.reranking.reranker_local_model or "").strip()
        if not base_model:
            raise RuntimeError(
                "Missing base model for training. Set reranking.reranker_local_model "
                "(e.g., 'cross-encoder/ms-marco-MiniLM-L-6-v2' or a local path)."
            )

        # Resolve corpus root path (for reading triplet doc_ids as files).
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
        mats, mat_stats = materialize_triplets(
            triplets,
            corpus_root=corpus_root,
            snippet_chars=snippet_chars,
        )
        if not mats:
            raise RuntimeError(
                "No usable triplets after materialization. "
                f"Check that positive/negative doc_ids exist under corpus root: {corpus_root}"
            )

        _emit_log(
            f"Training on {mat_stats.get('triplets_out', 0)} materialized triplets "
            f"(skipped_missing_pos={mat_stats.get('missing_positive', 0)}, skipped_missing_neg={mat_stats.get('missing_negative', 0)})."
        )

        model_artifact_dir = _run_dir(run_id) / "model"
        model_artifact_dir.parent.mkdir(parents=True, exist_ok=True)

        best_primary: float | None = None
        best_step: int | None = None
        best_ts: datetime | None = None
        primary_series: list[float] = []
        loop = asyncio.get_running_loop()

        def _emit(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal best_primary, best_step, best_ts, primary_series
            ts = datetime.now(UTC)
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

        # Mark run as running (in case a previous stub left it inconsistent).
        run.status = "running"
        _save_run(run)
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="state", ts=datetime.now(UTC), run_id=run_id, status=run.status),
        )

        # Train (runs in thread; emits progress/metrics into metrics.jsonl).
        await asyncio.to_thread(
            train_pairwise_reranker,
            base_model=base_model,
            output_dir=model_artifact_dir,
            triplets=mats,
            epochs=int(run.epochs),
            batch_size=int(run.batch_size),
            lr=float(run.lr),
            warmup_ratio=float(run.warmup_ratio),
            max_length=int(run.max_length),
            dev_split=0.1,
            seed=0,
            emit=_emit,
        )

        # Promote trained artifact to the active model path.
        active_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
        _atomic_copy_dir(model_artifact_dir, active_dir)
        _emit_log(f"Saved trained model to {cfg.training.tribrid_reranker_model_path} and run artifact {model_artifact_dir}.")

        # Final evaluation (proxy) on all materialized triplets.
        proxy = await asyncio.to_thread(
            evaluate_pairwise_reranker,
            model_dir=model_artifact_dir,
            triplets=mats,
            max_length=int(run.max_length),
        )
        metrics = _format_metrics_for_run(run, proxy)
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="metrics", ts=datetime.now(UTC), run_id=run_id, metrics=metrics),
        )
        pv = _primary_value(run, metrics)
        primary_series.append(float(pv))

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
        _save_run(run)
        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status=run.status),
        )

        async with _legacy_lock:
            if _legacy_status.run_id == run_id and _legacy_status.task == "training":
                _legacy_status.running = False
                _legacy_status.progress = 100
                _legacy_status.message = "Training complete"
                _legacy_status.result = RerankerLegacyTaskResult(ok=True, run_id=run_id)

    except Exception as e:
        try:
            run = _load_run(run_id)
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            _save_run(run)
        except Exception:
            pass

        _append_event(
            run_id,
            RerankerTrainMetricEvent(type="error", ts=datetime.now(UTC), run_id=run_id, message=str(e), status="failed"),
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
                _legacy_status.result = RerankerLegacyTaskResult(ok=False, run_id=run_id, error=str(e))
    finally:
        _train_tasks.pop(run_id, None)


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
        if int(cfg.training.tribrid_reranker_mine_reset or 0) == 1:
            mine_mode = "replace"
        if mine_mode not in {"replace", "append"}:
            mine_mode = "replace"

        result = await asyncio.to_thread(
            mine_triplets_from_query_log,
            log_path=log_path,
            triplets_path=triplets_path,
            mine_mode=mine_mode,  # type: ignore[arg-type]
            corpus_id=corpus_id,
        )
        created = int(result.get("triplets_mined") or 0)
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

        model_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
        if not model_dir.exists():
            raise RuntimeError(f"No trained model found at {cfg.training.tribrid_reranker_model_path}. Train first.")

        metrics = await asyncio.to_thread(
            evaluate_pairwise_reranker,
            model_dir=model_dir,
            triplets=mats,
            max_length=int(cfg.reranking.tribrid_reranker_maxlen),
        )
        output = (
            f"Proxy metrics (pairwise):\n"
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


@router.get("/reranker/status", response_model=RerankerLegacyStatus)
async def get_reranker_status() -> RerankerLegacyStatus:
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
        result = RerankerLegacyTaskResult(ok=ok, error=str(err) if err else None)

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
    elif mode == "local":
        path = cfg.reranking.reranker_local_model
    elif mode == "cloud":
        path = cfg.reranking.reranker_cloud_model
    else:
        path = ""

    return RerankerInfoResponse(
        enabled=enabled,
        reranker_mode=mode,
        reranker_cloud_provider=cfg.reranking.reranker_cloud_provider,
        reranker_cloud_model=cfg.reranking.reranker_cloud_model,
        reranker_local_model=cfg.reranking.reranker_local_model,
        path=str(path or ""),
        resolved_path=str(path or ""),
        device=resolve_reranker_device(),
        alpha=cfg.reranking.tribrid_reranker_alpha,
        topn=cfg.reranking.tribrid_reranker_topn,
        batch=cfg.reranking.tribrid_reranker_batch,
        maxlen=cfg.reranking.tribrid_reranker_maxlen,
        snippet_chars=cfg.reranking.rerank_input_snippet_chars,
        trust_remote_code=bool(cfg.reranking.transformers_trust_remote_code),
    )


@router.post("/reranker/mine", response_model=RerankerMineResponse)
async def mine_triplets(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerMineResponse:
    """Mine triplets from query logs + feedback into training.tribrid_triplets_path."""
    cid = (corpus_id or "").strip() or None
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
        return RerankerMineResponse(ok=True, output=msg, error=None)

    mine_mode = str(cfg.training.triplets_mine_mode or "replace").strip().lower()
    if int(cfg.training.tribrid_reranker_mine_reset or 0) == 1:
        mine_mode = "replace"
    if mine_mode not in {"replace", "append"}:
        mine_mode = "replace"

    result = await asyncio.to_thread(
        mine_triplets_from_query_log,
        log_path=log_path,
        triplets_path=triplets_path,
        mine_mode=mine_mode,  # type: ignore[arg-type]
        corpus_id=cid,
    )
    created = int(result.get("triplets_mined") or 0)
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

    return RerankerMineResponse(ok=True, output=msg, error=None)


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
        _legacy_status.running = True
        _legacy_status.progress = 0
        _legacy_status.task = "training"
        _legacy_status.message = "Starting training…"
        _legacy_status.result = None
        _legacy_status.live_output = []
        _legacy_status.run_id = None

    res = await start_train_run(req)
    async with _legacy_lock:
        _legacy_status.run_id = res.run_id
        _legacy_status.message = f"Training run started: {res.run_id}"

    return RerankerTrainLegacyResponse(ok=True, output=f"Run started: {res.run_id}", run_id=res.run_id, error=None)


@router.post("/reranker/evaluate", response_model=RerankerEvaluateResponse)
async def evaluate_reranker(
    corpus_id: str | None = Query(default=None, description="Optional corpus_id scope (required when multiple corpora)"),
) -> RerankerEvaluateResponse:
    """Evaluate the current learning reranker model (proxy metrics)."""
    cid = await _resolve_corpus_id(corpus_id)
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
        triplets = load_triplets(triplets_path)
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
        mats, _ = materialize_triplets(triplets, corpus_root=corpus_root, snippet_chars=snippet_chars)
        if not mats:
            raise RuntimeError("No usable triplets after materialization (missing/empty docs).")

        model_dir = _resolve_path(cfg.training.tribrid_reranker_model_path)
        if not model_dir.exists():
            raise RuntimeError(f"No trained model found at {cfg.training.tribrid_reranker_model_path}. Train first.")

        metrics = await asyncio.to_thread(
            evaluate_pairwise_reranker,
            model_dir=model_dir,
            triplets=mats,
            max_length=int(cfg.reranking.tribrid_reranker_maxlen),
        )
        output = (
            f"Proxy metrics (pairwise):\n"
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
        return RerankerEvaluateResponse(ok=True, output=output, metrics=metrics, error=None)
    except Exception as e:
        async with _legacy_lock:
            _legacy_status.running = False
            _legacy_status.progress = 0
            _legacy_status.message = "Evaluation failed"
            _legacy_status.result = RerankerLegacyTaskResult(ok=False, error=str(e))
        return RerankerEvaluateResponse(ok=False, output=None, metrics=None, error=str(e))


@router.get("/reranker/train/profile", response_model=CorpusEvalProfile)
async def get_train_profile(corpus_id: str = Query(..., description="Corpus identifier")) -> CorpusEvalProfile:
    cfg = await load_scoped_config(repo_id=corpus_id)
    default_k = min(int(cfg.reranking.tribrid_reranker_topn), 10)
    default_k = max(1, default_k)

    dataset = _load_dataset(corpus_id)
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
            )
        )

    metas.sort(key=lambda m: m.started_at, reverse=True)
    return RerankerTrainRunsResponse(ok=True, runs=metas[: int(limit)])


@router.post("/reranker/train/start", response_model=RerankerTrainStartResponse)
async def start_train_run(request: RerankerTrainStartRequest) -> RerankerTrainStartResponse:
    corpus_id = request.repo_id
    cfg = await load_scoped_config(repo_id=corpus_id)

    default_k = min(int(cfg.reranking.tribrid_reranker_topn), 10)
    default_k = max(1, default_k)

    dataset = _load_dataset(corpus_id)
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
    )

    # Persist immediately
    _save_run(run)

    # Create empty metrics.jsonl
    metrics_path = _metrics_path(run_id)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_path.exists():
        metrics_path.write_text("", encoding="utf-8")

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

    # Start background training (best-effort).
    if run_id not in _train_tasks:
        _train_tasks[run_id] = asyncio.create_task(_run_train_job(run_id=run_id, corpus_id=corpus_id))

    return RerankerTrainStartResponse(ok=True, run_id=run_id, run=run)


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


@router.get("/reranker/train/run/{run_id}", response_model=RerankerTrainRun)
async def get_train_run(run_id: str) -> RerankerTrainRun:
    return _load_run(run_id)


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


@router.get("/reranker/triplets/{repo_id}", response_model=list[dict[str, Any]])
async def get_triplets(repo_id: str, limit: int = 100) -> list[dict[str, Any]]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/triplets/{repo_id}")
async def add_triplet(repo_id: str, query: str, positive: str, negative: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/promote")
async def promote_model(model_path: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Promote endpoint not implemented yet")
