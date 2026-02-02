from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
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
)
from server.services.config_store import get_config as load_scoped_config
from server.training.metric_policy import infer_corpus_eval_profile

router = APIRouter(tags=["reranker"])

_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _ROOT / "data" / "reranker_train_runs"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(path_str: str) -> Path:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f)


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


@router.get("/reranker/status")
async def get_reranker_status() -> dict[str, Any]:
    # Minimal status shape expected by the UI polling loop.
    return {
        "running": False,
        "progress": 0,
        "task": "",
        "message": "",
        "result": None,
        "live_output": [],
    }


@router.get("/reranker/info")
async def get_reranker_info() -> dict[str, Any]:
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

    return {
        "enabled": enabled,
        "reranker_mode": mode,
        "reranker_cloud_provider": cfg.reranking.reranker_cloud_provider,
        "reranker_cloud_model": cfg.reranking.reranker_cloud_model,
        "reranker_local_model": cfg.reranking.reranker_local_model,
        "path": path,
        "resolved_path": path,
        "device": "cpu",
        "alpha": cfg.reranking.tribrid_reranker_alpha,
        "topn": cfg.reranking.tribrid_reranker_topn,
        "batch": cfg.reranking.tribrid_reranker_batch,
        "maxlen": cfg.reranking.tribrid_reranker_maxlen,
        "snippet_chars": cfg.reranking.rerank_input_snippet_chars,
        "trust_remote_code": bool(cfg.reranking.transformers_trust_remote_code),
    }


@router.post("/reranker/mine")
async def mine_triplets() -> dict[str, Any]:
    """Mine triplets from logs (minimal file-backed implementation)."""
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
    triplets_path.parent.mkdir(parents=True, exist_ok=True)

    created = 0
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for i, line in enumerate([ln for ln in lines if ln.strip()][:10]):
            try:
                query = json.loads(line).get("query")
            except Exception:
                query = None
            item = {
                "query": query or f"query_{i}",
                "positive": "positive_placeholder",
                "negative": "negative_placeholder",
            }
            with triplets_path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(item) + "\n")
            created += 1

    return {
        "ok": True,
        "output": f"Mined {created} triplets into {cfg.training.tribrid_triplets_path}",
    }


@router.post("/reranker/train")
async def train_reranker(options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Train the learning reranker (minimal stub)."""
    cfg = load_config()
    options = options or {}
    epochs = options.get("epochs", cfg.training.reranker_train_epochs)
    batch_size = options.get("batch_size", cfg.training.reranker_train_batch)
    max_length = options.get("max_length", cfg.reranking.tribrid_reranker_maxlen)
    return {
        "ok": True,
        "output": (
            "Training started (stub).\n"
            f"model_path={cfg.training.tribrid_reranker_model_path}\n"
            f"epochs={epochs} batch_size={batch_size} max_length={max_length}\n"
        ),
    }


@router.post("/reranker/evaluate")
async def evaluate_reranker() -> dict[str, Any]:
    """Evaluate the learning reranker (minimal stub)."""
    return {
        "ok": True,
        "output": "MRR: 0.00\nHit@1: 0.00\nHit@3: 0.00\nHit@5: 0.00\n",
    }


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
    if not dataset:
        raise HTTPException(status_code=404, detail=f"No eval_dataset entries found for corpus_id={corpus_id}")

    eval_rows: list[dict[str, Any]] = []
    for entry in dataset:
        relevance = {p: 1 for p in (entry.expected_paths or [])}
        eval_rows.append({"query_id": entry.entry_id, "relevance": relevance})

    profile = infer_corpus_eval_profile(corpus_id, eval_rows, default_k)

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

    # Stub note (until a real background trainer is wired)
    _append_event(
        run_id,
        RerankerTrainMetricEvent(
            type="log",
            ts=datetime.now(UTC),
            run_id=run_id,
            message="Training task is a stub (no background training is running yet). Run left in status=running.",
        ),
    )

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


@router.get("/reranker/logs/count")
async def get_logs_count() -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    return {"count": _count_lines(log_path)}


@router.get("/reranker/triplets/count")
async def get_triplets_count() -> dict[str, Any]:
    cfg = load_config()
    triplets_path = _resolve_path(cfg.training.tribrid_triplets_path)
    return {"count": _count_lines(triplets_path)}


@router.get("/reranker/costs")
async def get_costs() -> dict[str, Any]:
    # Placeholder until cost accounting is implemented.
    return {"total_24h": 0.0, "avg_per_query": 0.0}


@router.get("/reranker/nohits")
async def get_nohits() -> dict[str, Any]:
    # Placeholder until we log no-hit events explicitly.
    return {"queries": []}


@router.get("/reranker/logs")
async def get_logs(limit: int = 200) -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        return {"logs": []}
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
    return {"logs": parsed}


@router.get("/reranker/logs/download")
async def download_logs() -> FileResponse:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No logs file found")
    return FileResponse(
        str(log_path),
        media_type="application/jsonl",
        filename=log_path.name,
    )


@router.post("/reranker/logs/clear")
async def clear_logs() -> dict[str, Any]:
    cfg = load_config()
    log_path = _resolve_path(cfg.tracing.tribrid_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    return {"ok": True}


@router.get("/reranker/triplets/{repo_id}", response_model=list[dict[str, Any]])
async def get_triplets(repo_id: str, limit: int = 100) -> list[dict[str, Any]]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/triplets/{repo_id}")
async def add_triplet(repo_id: str, query: str, positive: str, negative: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Triplets endpoint not implemented yet")


@router.post("/reranker/promote")
async def promote_model(model_path: str) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Promote endpoint not implemented yet")
