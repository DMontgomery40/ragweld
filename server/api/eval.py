from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.api.dataset import _load_dataset  # shared file-backed persistence
from server.chat.generation import generate_chat_text
from server.chat.provider_router import select_provider_route
from server.models.eval import (
    EvalAnalyzeComparisonResponse,
    EvalDoc,
    EvalMetrics,
    EvalRequest,
    EvalTestRequest,
    EvalResult,
    EvalRun,
    EvalRunMeta,
    EvalRunsResponse,
)
from server.models.tribrid_config_model import CorpusScope, EvalAnalyzeComparisonRequest
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["eval"])

_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _ROOT / "data" / "eval_runs"

# Module-level status for UI polling / debugging
_EVAL_STATUS: dict[str, Any] = {
    "running": False,
    "progress": 0,
    "total": 0,
    "corpus_id": None,
    "latest_run_id": None,
    "error": None,
}


def _run_path(run_id: str) -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR / f"{run_id}.json"


def _latest_run_id(repo_id: str | None = None) -> str | None:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        rid = path.stem
        if repo_id and not rid.startswith(f"{repo_id}__"):
            continue
        return rid
    return None


def _normalize_path(p: str) -> str:
    return (p or "").replace("\\", "/").strip().lower()


def _path_matches(expected: str, actual: str) -> bool:
    e = _normalize_path(expected)
    a = _normalize_path(actual)
    if not e or not a:
        return False
    if a == e:
        return True
    if a.endswith(e):
        return True
    return e in a


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _recall_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if not expected:
        return 0.0
    top = retrieved[:k]
    matched = sum(1 for exp in expected if any(_path_matches(exp, r) for r in top))
    return float(matched) / float(len(expected))


def _precision_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    hits = sum(1 for r in top if any(_path_matches(exp, r) for exp in expected))
    return float(hits) / float(k)


def _ndcg_at_k(expected: list[str], retrieved: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = retrieved[:k]
    rels = [1.0 if any(_path_matches(exp, r) for exp in expected) else 0.0 for r in top]
    dcg = 0.0
    for i, rel in enumerate(rels):
        dcg += rel / math.log2(i + 2)
    ideal_hits = min(len(expected), k)
    if ideal_hits <= 0:
        return 0.0
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return float(dcg / idcg) if idcg > 0 else 0.0


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return float(xs[0])
    p = min(max(p, 0.0), 1.0)
    idx = int(math.ceil(p * (len(xs) - 1)))
    return float(xs[idx])


def _load_run(run_id: str) -> EvalRun:
    path = _run_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read eval run: {e}") from e
    return EvalRun.model_validate(raw)


def _save_run(run: EvalRun) -> None:
    path = _run_path(run.run_id)
    path.write_text(json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")


@router.post("/eval/run", response_model=EvalRun)
async def run_evaluation(request: EvalRequest) -> EvalRun:
    repo_id = request.repo_id
    dataset = _load_dataset(repo_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"No eval_dataset entries found for repo_id={repo_id}")

    # Deterministic sampling (first N)
    entries = dataset[: int(request.sample_size)] if request.sample_size else dataset

    cfg = await load_scoped_config(repo_id=repo_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    final_k = int(cfg.retrieval.eval_final_k)
    use_multi = bool(int(cfg.retrieval.eval_multi))
    k_recall5 = int(cfg.evaluation.recall_at_5_k)
    k_recall10 = int(cfg.evaluation.recall_at_10_k)
    k_recall20 = int(cfg.evaluation.recall_at_20_k)
    k_prec5 = int(cfg.evaluation.precision_at_5_k)
    k_ndcg10 = int(cfg.evaluation.ndcg_at_10_k)
    # Ensure we retrieve enough results to compute all configured metrics.
    eval_k = max(int(final_k), k_recall5, k_recall10, k_recall20, k_prec5, k_ndcg10)

    rr_vals: list[float] = []
    recall5_vals: list[float] = []
    recall10_vals: list[float] = []
    recall20_vals: list[float] = []
    prec5_vals: list[float] = []
    ndcg10_vals: list[float] = []
    latencies: list[float] = []

    results: list[EvalResult] = []

    from datetime import UTC, datetime

    started_at = datetime.now(UTC)

    for entry in entries:
        t0 = perf_counter()
        matches = await fusion.search(
            [repo_id],
            entry.question,
            cfg.fusion,
            include_vector=True,
            include_sparse=True,
            include_graph=True,
            top_k=eval_k,
        )
        latency_ms = (perf_counter() - t0) * 1000.0
        latencies.append(latency_ms)

        retrieved_paths = _dedupe_preserve_order([m.file_path for m in matches if m.file_path])
        expected_paths = list(entry.expected_paths or [])
        top_paths = retrieved_paths[:final_k] if final_k > 0 else retrieved_paths

        docs = [
            EvalDoc(
                file_path=m.file_path,
                start_line=m.start_line,
                score=float(m.score),
                source=m.source,
            )
            for m in matches[: max(1, final_k)]
            if m.file_path
        ]

        # Reciprocal rank: first correct hit among retrieved paths
        rr = 0.0
        for i, rp in enumerate(retrieved_paths, start=1):
            if any(_path_matches(exp, rp) for exp in expected_paths):
                rr = 1.0 / float(i)
                break

        top1_hit = bool(top_paths) and any(_path_matches(exp, top_paths[0]) for exp in expected_paths)
        topk_hit = any(any(_path_matches(exp, rp) for exp in expected_paths) for rp in top_paths)

        recall = _recall_at_k(expected_paths, retrieved_paths, k=len(retrieved_paths) if retrieved_paths else eval_k)
        recall5 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall5)
        recall10 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall10)
        recall20 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall20)
        prec5 = _precision_at_k(expected_paths, retrieved_paths, k=k_prec5)
        ndcg10 = _ndcg_at_k(expected_paths, retrieved_paths, k=k_ndcg10)

        rr_vals.append(rr)
        recall5_vals.append(recall5)
        recall10_vals.append(recall10)
        recall20_vals.append(recall20)
        prec5_vals.append(prec5)
        ndcg10_vals.append(ndcg10)

        results.append(
            EvalResult(
                entry_id=entry.entry_id,
                question=entry.question,
                retrieved_paths=retrieved_paths,
                expected_paths=expected_paths,
                top_paths=top_paths,
                top1_path=top_paths[:1],
                top1_hit=top1_hit,
                topk_hit=topk_hit,
                reciprocal_rank=rr,
                recall=recall,
                latency_ms=latency_ms,
                duration_secs=latency_ms / 1000.0,
                docs=docs,
            )
        )

    metrics = EvalMetrics(
        mrr=float(sum(rr_vals) / len(rr_vals)) if rr_vals else 0.0,
        recall_at_5=float(sum(recall5_vals) / len(recall5_vals)) if recall5_vals else 0.0,
        recall_at_10=float(sum(recall10_vals) / len(recall10_vals)) if recall10_vals else 0.0,
        recall_at_20=float(sum(recall20_vals) / len(recall20_vals)) if recall20_vals else 0.0,
        precision_at_5=float(sum(prec5_vals) / len(prec5_vals)) if prec5_vals else 0.0,
        ndcg_at_10=float(sum(ndcg10_vals) / len(ndcg10_vals)) if ndcg10_vals else 0.0,
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
    )

    completed_at = datetime.now(UTC)
    run_id = f"{repo_id}__{completed_at.strftime('%Y%m%d_%H%M%S')}"
    duration_secs = float((completed_at - started_at).total_seconds())
    total = len(results)
    top1_hits = sum(1 for r in results if r.top1_hit)
    topk_hits = sum(1 for r in results if r.topk_hit)

    run = EvalRun(
        run_id=run_id,
        repo_id=repo_id,
        dataset_id=request.dataset_id or "default",
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        total=total,
        top1_hits=top1_hits,
        topk_hits=topk_hits,
        top1_accuracy=float(top1_hits / total) if total else 0.0,
        topk_accuracy=float(topk_hits / total) if total else 0.0,
        duration_secs=duration_secs,
        use_multi=use_multi,
        final_k=final_k,
        metrics=metrics,
        results=results,
        started_at=started_at,
        completed_at=completed_at,
    )
    _save_run(run)
    return run


@router.post("/eval/test", response_model=EvalResult)
async def test_eval_entry(request: EvalTestRequest) -> EvalResult:
    """Test a single query against the current index and return a drill-down result."""
    repo_id = request.repo_id
    cfg = await load_scoped_config(repo_id=repo_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    final_k = int(request.final_k) if request.final_k is not None else int(cfg.retrieval.eval_final_k)
    final_k = max(1, final_k)
    k_recall5 = int(cfg.evaluation.recall_at_5_k)
    k_recall10 = int(cfg.evaluation.recall_at_10_k)
    k_recall20 = int(cfg.evaluation.recall_at_20_k)
    k_prec5 = int(cfg.evaluation.precision_at_5_k)
    k_ndcg10 = int(cfg.evaluation.ndcg_at_10_k)
    eval_k = max(int(final_k), k_recall5, k_recall10, k_recall20, k_prec5, k_ndcg10)

    t0 = perf_counter()
    matches = await fusion.search(
        [repo_id],
        request.question,
        cfg.fusion,
        include_vector=True,
        include_sparse=True,
        include_graph=True,
        top_k=eval_k,
    )
    latency_ms = (perf_counter() - t0) * 1000.0

    retrieved_paths = _dedupe_preserve_order([m.file_path for m in matches if m.file_path])
    expected_paths = list(request.expected_paths or [])
    top_paths = retrieved_paths[:final_k]

    docs = [
        EvalDoc(
            file_path=m.file_path,
            start_line=m.start_line,
            score=float(m.score),
            source=m.source,
        )
        for m in matches[:final_k]
        if m.file_path
    ]

    rr = 0.0
    for i, rp in enumerate(retrieved_paths, start=1):
        if any(_path_matches(exp, rp) for exp in expected_paths):
            rr = 1.0 / float(i)
            break

    top1_hit = bool(top_paths) and any(_path_matches(exp, top_paths[0]) for exp in expected_paths)
    topk_hit = any(any(_path_matches(exp, rp) for exp in expected_paths) for rp in top_paths)
    recall = _recall_at_k(expected_paths, retrieved_paths, k=len(retrieved_paths) if retrieved_paths else eval_k)

    return EvalResult(
        entry_id="adhoc",
        question=request.question,
        retrieved_paths=retrieved_paths,
        expected_paths=expected_paths,
        top_paths=top_paths,
        top1_path=top_paths[:1],
        top1_hit=top1_hit,
        topk_hit=topk_hit,
        reciprocal_rank=rr,
        recall=recall,
        latency_ms=latency_ms,
        duration_secs=latency_ms / 1000.0,
        docs=docs,
    )


@router.get("/eval/runs", response_model=EvalRunsResponse)
async def list_eval_runs(
    scope: CorpusScope = Depends(),
    limit: int = Query(default=20, ge=1, le=200),
) -> EvalRunsResponse:
    repo_id = scope.resolved_repo_id
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs: list[EvalRunMeta] = []
    for path in sorted(_RUNS_DIR.glob("*.json"), reverse=True):
        run_id = path.stem
        if repo_id and not run_id.startswith(f"{repo_id}__"):
            continue
        try:
            run = EvalRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            total = int(run.total or len(run.results))
            runs.append(
                EvalRunMeta(
                    run_id=run.run_id,
                    top1_accuracy=float(run.top1_accuracy),
                    topk_accuracy=float(run.topk_accuracy),
                    mrr=float(run.metrics.mrr) if run.metrics else None,
                    total=total,
                    duration_secs=float(run.duration_secs),
                    has_config=bool(run.config),
                )
            )
        except Exception:
            continue
        if len(runs) >= limit:
            break
    return EvalRunsResponse(ok=True, runs=runs)


@router.get("/eval/run/stream")
async def eval_run_stream(
    request: Request,
    scope: CorpusScope = Depends(),
    use_multi: int | None = Query(default=None, description="Override eval_multi (0/1)"),
    final_k: int | None = Query(default=None, description="Override eval_final_k"),
    sample_limit: int | None = Query(default=None, description="Optional sample size limit"),
) -> StreamingResponse:
    """Run evaluation and stream logs/progress via SSE.

    IMPORTANT: This MUST be declared before `/eval/run/{run_id}` or it will be
    shadowed by Starlette route matching (treating "stream" as a run_id).
    """

    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")

    if _EVAL_STATUS.get("running"):
        async def already_running() -> AsyncIterator[str]:
            yield "data: " + json.dumps({"type": "error", "message": "Evaluation already running"}) + "\n\n"
        return StreamingResponse(already_running(), media_type="text/event-stream")

    async def generate() -> AsyncIterator[str]:
        _EVAL_STATUS.update(
            running=True,
            progress=0,
            total=0,
            corpus_id=repo_id,
            latest_run_id=None,
            error=None,
        )
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
            run_use_multi = bool(int(use_multi)) if use_multi is not None else bool(int(cfg.retrieval.eval_multi))
            run_final_k = int(final_k) if final_k is not None else int(cfg.retrieval.eval_final_k)
            run_final_k = max(1, run_final_k)

            dataset = _load_dataset(repo_id)
            if not dataset:
                msg = f"No eval_dataset entries found for repo_id={repo_id}"
                _EVAL_STATUS["error"] = msg
                yield "data: " + json.dumps({"type": "error", "message": msg}) + "\n\n"
                return

            entries = dataset[: int(sample_limit)] if sample_limit else dataset
            total = len(entries)
            _EVAL_STATUS["total"] = total

            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "log",
                        "message": (
                            f"Starting eval: repo_id={repo_id}, use_multi={run_use_multi}, "
                            f"final_k={run_final_k}, sample_limit={sample_limit or 'all'}"
                        ),
                    }
                )
                + "\n\n"
            )
            yield "data: " + json.dumps({"type": "log", "message": f"Loaded {total} eval_dataset entries"}) + "\n\n"

            fusion = TriBridFusion(vector=None, sparse=None, graph=None)

            rr_vals: list[float] = []
            recall5_vals: list[float] = []
            recall10_vals: list[float] = []
            recall20_vals: list[float] = []
            prec5_vals: list[float] = []
            ndcg10_vals: list[float] = []
            latencies: list[float] = []
            results: list[EvalResult] = []

            from datetime import UTC, datetime
            started_at = datetime.now(UTC)

            k_recall5 = int(cfg.evaluation.recall_at_5_k)
            k_recall10 = int(cfg.evaluation.recall_at_10_k)
            k_recall20 = int(cfg.evaluation.recall_at_20_k)
            k_prec5 = int(cfg.evaluation.precision_at_5_k)
            k_ndcg10 = int(cfg.evaluation.ndcg_at_10_k)
            eval_k = max(int(run_final_k), k_recall5, k_recall10, k_recall20, k_prec5, k_ndcg10)

            for idx, entry in enumerate(entries, start=1):
                if await request.is_disconnected():
                    yield "data: " + json.dumps({"type": "error", "message": "Client disconnected"}) + "\n\n"
                    return

                yield (
                    "data: "
                    + json.dumps({"type": "log", "message": f"[{idx}/{total}] {entry.question}"})
                    + "\n\n"
                )

                t0 = perf_counter()
                matches = await fusion.search(
                    [repo_id],
                    entry.question,
                    cfg.fusion,
                    include_vector=True,
                    include_sparse=True,
                    include_graph=True,
                    top_k=eval_k,
                )
                latency_ms = (perf_counter() - t0) * 1000.0
                latencies.append(latency_ms)

                retrieved_paths = _dedupe_preserve_order([m.file_path for m in matches if m.file_path])
                expected_paths = list(entry.expected_paths or [])
                top_paths = retrieved_paths[:run_final_k]
                docs = [
                    EvalDoc(
                        file_path=m.file_path,
                        start_line=m.start_line,
                        score=float(m.score),
                        source=m.source,
                    )
                    for m in matches[:run_final_k]
                    if m.file_path
                ]

                rr = 0.0
                for i, rp in enumerate(retrieved_paths, start=1):
                    if any(_path_matches(exp, rp) for exp in expected_paths):
                        rr = 1.0 / float(i)
                        break

                top1_hit = bool(top_paths) and any(_path_matches(exp, top_paths[0]) for exp in expected_paths)
                topk_hit = any(any(_path_matches(exp, rp) for exp in expected_paths) for rp in top_paths)

                recall = _recall_at_k(expected_paths, retrieved_paths, k=len(retrieved_paths) if retrieved_paths else eval_k)
                recall5 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall5)
                recall10 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall10)
                recall20 = _recall_at_k(expected_paths, retrieved_paths, k=k_recall20)
                prec5 = _precision_at_k(expected_paths, retrieved_paths, k=k_prec5)
                ndcg10 = _ndcg_at_k(expected_paths, retrieved_paths, k=k_ndcg10)

                rr_vals.append(rr)
                recall5_vals.append(recall5)
                recall10_vals.append(recall10)
                recall20_vals.append(recall20)
                prec5_vals.append(prec5)
                ndcg10_vals.append(ndcg10)

                results.append(
                    EvalResult(
                        entry_id=entry.entry_id,
                        question=entry.question,
                        retrieved_paths=retrieved_paths,
                        expected_paths=expected_paths,
                        top_paths=top_paths,
                        top1_path=top_paths[:1],
                        top1_hit=top1_hit,
                        topk_hit=topk_hit,
                        reciprocal_rank=rr,
                        recall=recall,
                        latency_ms=latency_ms,
                        duration_secs=latency_ms / 1000.0,
                        docs=docs,
                    )
                )

                _EVAL_STATUS["progress"] = idx
                percent = (idx / total) * 100.0 if total else 0.0
                yield (
                    "data: "
                    + json.dumps(
                        {"type": "progress", "percent": percent, "message": f"Question {idx}/{total}"}
                    )
                    + "\n\n"
                )

            metrics = EvalMetrics(
                mrr=float(sum(rr_vals) / len(rr_vals)) if rr_vals else 0.0,
                recall_at_5=float(sum(recall5_vals) / len(recall5_vals)) if recall5_vals else 0.0,
                recall_at_10=float(sum(recall10_vals) / len(recall10_vals)) if recall10_vals else 0.0,
                recall_at_20=float(sum(recall20_vals) / len(recall20_vals)) if recall20_vals else 0.0,
                precision_at_5=float(sum(prec5_vals) / len(prec5_vals)) if prec5_vals else 0.0,
                ndcg_at_10=float(sum(ndcg10_vals) / len(ndcg10_vals)) if ndcg10_vals else 0.0,
                latency_p50_ms=_percentile(latencies, 0.50),
                latency_p95_ms=_percentile(latencies, 0.95),
            )

            completed_at = datetime.now(UTC)
            run_id = f"{repo_id}__{completed_at.strftime('%Y%m%d_%H%M%S')}"
            duration_secs = float((completed_at - started_at).total_seconds())
            top1_hits = sum(1 for r in results if r.top1_hit)
            topk_hits = sum(1 for r in results if r.topk_hit)
            top1_accuracy = float(top1_hits / total) if total else 0.0
            topk_accuracy = float(topk_hits / total) if total else 0.0

            run = EvalRun(
                run_id=run_id,
                repo_id=repo_id,
                dataset_id="default",
                config_snapshot=cfg.model_dump(mode="json"),
                config=cfg.to_flat_dict(),
                total=total,
                top1_hits=top1_hits,
                topk_hits=topk_hits,
                top1_accuracy=top1_accuracy,
                topk_accuracy=topk_accuracy,
                duration_secs=duration_secs,
                use_multi=run_use_multi,
                final_k=run_final_k,
                metrics=metrics,
                results=results,
                started_at=started_at,
                completed_at=completed_at,
            )

            _save_run(run)
            _EVAL_STATUS["latest_run_id"] = run_id

            yield "data: " + json.dumps({"type": "log", "message": f"Results saved: {run_id}"}) + "\n\n"
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "log",
                        "message": (
                            f"Complete: top1={top1_hits}/{total}, topk={topk_hits}/{total}, "
                            f"mrr={metrics.mrr:.4f}, duration={duration_secs:.2f}s"
                        ),
                    }
                )
                + "\n\n"
            )
            yield "data: {\"type\": \"complete\"}\n\n"
        except Exception as e:
            _EVAL_STATUS["error"] = str(e)
            yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"
        finally:
            _EVAL_STATUS["running"] = False

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/eval/run/{run_id}", response_model=EvalRun)
async def get_eval_run(run_id: str) -> EvalRun:
    return _load_run(run_id)


# Alias for UI code that expects /eval/runs/{id}
@router.get("/eval/runs/{run_id}", response_model=EvalRun)
async def get_eval_run_alias(run_id: str) -> EvalRun:
    return _load_run(run_id)


@router.delete("/eval/run/{run_id}")
async def delete_eval_run(run_id: str) -> dict[str, Any]:
    path = _run_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    path.unlink()
    return {"ok": True, "deleted": 1}


@router.delete("/eval/runs/{run_id}")
async def delete_eval_run_alias(run_id: str) -> dict[str, Any]:
    return await delete_eval_run(run_id)


@router.get("/eval/status")
async def eval_status() -> dict[str, Any]:
    """Return in-process eval status (best-effort)."""
    return dict(_EVAL_STATUS)


@router.get("/eval/results", response_model=EvalRun)
async def eval_results(scope: CorpusScope = Depends()) -> EvalRun:
    """Return the most recent eval run results."""
    repo_id = scope.resolved_repo_id
    rid = _latest_run_id(repo_id=repo_id)
    if rid is None:
        raise HTTPException(status_code=404, detail="No eval runs found")
    return _load_run(rid)


@router.get("/eval/results/{run_id}", response_model=EvalRun)
async def eval_results_by_run(run_id: str) -> EvalRun:
    """Return eval results for a specific run."""
    return _load_run(run_id)


@router.post("/eval/analyze_comparison", response_model=EvalAnalyzeComparisonResponse)
async def analyze_eval_comparison(
    payload: EvalAnalyzeComparisonRequest,
    scope: CorpusScope = Depends(),
) -> EvalAnalyzeComparisonResponse:
    """LLM-backed comparison analysis for the Eval drill-down UI."""

    repo_id = scope.resolved_repo_id
    if not repo_id:
        return EvalAnalyzeComparisonResponse(
            ok=False,
            analysis=None,
            model_used=None,
            error="Missing corpus scope (pass ?corpus_id=...).",
        )

    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except Exception as e:
        return EvalAnalyzeComparisonResponse(ok=False, analysis=None, model_used=None, error=str(e))

    def pct(x: float) -> str:
        return f"{float(x) * 100.0:.1f}%"

    def json_one_line(x: Any) -> str:
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)

    current = payload.current_run
    baseline = payload.compare_run

    delta_top1 = (float(current.top1_accuracy) - float(baseline.top1_accuracy)) * 100.0
    delta_topk = (float(current.topk_accuracy) - float(baseline.topk_accuracy)) * 100.0

    # Format config diffs and question lists for the model. Keep the prompt bounded.
    max_diffs = 80
    diffs_lines: list[str] = []
    for d in list(payload.config_diffs or [])[:max_diffs]:
        if not isinstance(d, dict):
            continue
        key = str(d.get("key") or d.get("path") or d.get("name") or "").strip() or "(unknown)"
        prev = d.get("previous")
        cur = d.get("current")
        diffs_lines.append(f"- {key}: {json_one_line(prev)} -> {json_one_line(cur)}")
    if len(payload.config_diffs or []) > max_diffs:
        diffs_lines.append(f"- ... ({len(payload.config_diffs) - max_diffs} more)")

    max_q = 25
    regressed_qs = [q.question for q in (payload.topk_regressions or []) if q.question][:max_q]
    improved_qs = [q.question for q in (payload.topk_improvements or []) if q.question][:max_q]

    user_prompt = "\n".join(
        [
            "You are analyzing a retrieval evaluation comparison between two runs of the same corpus.",
            "",
            "## Runs",
            f"- Baseline run: `{baseline.run_id}` (n={baseline.total}, top1={pct(baseline.top1_accuracy)}, topk={pct(baseline.topk_accuracy)}, duration={baseline.duration_secs:.1f}s)",
            f"- Current run: `{current.run_id}` (n={current.total}, top1={pct(current.top1_accuracy)}, topk={pct(current.topk_accuracy)}, duration={current.duration_secs:.1f}s)",
            "",
            "## Metric deltas (Current - Baseline)",
            f"- Top-1: {delta_top1:+.1f}%",
            f"- Top-K: {delta_topk:+.1f}%",
            "",
            "## Config changes",
            f"- Total changes detected: {len(payload.config_diffs or [])}",
            *(diffs_lines if diffs_lines else ["- (none)"]),
            "",
            "## Question-level changes",
            f"- Top-K regressions: {len(payload.topk_regressions or [])}",
            f"- Top-K improvements: {len(payload.topk_improvements or [])}",
            f"- Top-1 regressions count: {int(payload.top1_regressions_count)}",
            f"- Top-1 improvements count: {int(payload.top1_improvements_count)}",
            "",
            "### Example regressed questions (Top-K)",
            *(["- (none)"] if not regressed_qs else [f"- {q}" for q in regressed_qs]),
            "",
            "### Example improved questions (Top-K)",
            *(["- (none)"] if not improved_qs else [f"- {q}" for q in improved_qs]),
            "",
            "## What to do",
            "- Explain likely root causes, but be skeptical and call out confounding variables.",
            "- Suggest concrete next experiments and which config knobs to try.",
            "- If the results are surprising, say so and propose validation steps (e.g., verify index rebuild, dataset drift).",
        ]
    )

    def provider_setup_checklist(reason: str, *, selected_model: str | None = None, selected_kind: str | None = None) -> str:
        model_line = ""
        if selected_kind or selected_model:
            model_line = (
                "\n"
                f"Selected route: {selected_kind or '(unknown)'}\n"
                f"Selected model: {selected_model or '(unknown)'}\n"
            )

        openrouter_default = str(getattr(cfg.chat.openrouter, "default_model", "") or "").strip()
        local_default = str(getattr(cfg.chat.local_models, "default_chat_model", "") or "").strip()
        gen_model = str(getattr(cfg.generation, "gen_model", "") or "").strip()
        openai_base_url = str(getattr(cfg.generation, "openai_base_url", "") or "").strip()

        extra = [
            "",
            "Provider setup checklist:",
            "1) OpenAI (cloud-direct): set `OPENAI_API_KEY` in `.env` and restart the backend.",
            "   - If you use a proxy, set `generation.openai_base_url` in config (not `OPENAI_BASE_URL`).",
            "2) OpenRouter: set `OPENROUTER_API_KEY` in `.env` and set `chat.openrouter.enabled=true`.",
            "3) Local: start Ollama/llama.cpp and ensure `chat.local_models.providers` includes an enabled provider.",
            "",
            "Model selection notes:",
            f"- chat.openrouter.default_model: {openrouter_default or '(empty)'}",
            f"- chat.local_models.default_chat_model: {local_default or '(empty)'}",
            f"- generation.gen_model: {gen_model or '(empty)'}",
            f"- generation.openai_base_url: {openai_base_url or '(default)'}",
        ]
        return f"{reason}{model_line}\n" + "\n".join(extra)

    try:
        route = select_provider_route(
            chat_config=cfg.chat,
            # Use the configured generation model for evaluation analysis.
            model_override=str(cfg.generation.gen_model or "").strip(),
            openai_base_url_override=cfg.generation.openai_base_url,
        )
    except Exception as e:
        return EvalAnalyzeComparisonResponse(
            ok=False,
            analysis=None,
            model_used=str(getattr(cfg.generation, "gen_model", "") or "").strip() or None,
            error=provider_setup_checklist(str(e)),
        )

    try:
        text, _provider_response_id = await generate_chat_text(
            route=route,
            openrouter_cfg=cfg.chat.openrouter,
            system_prompt=cfg.system_prompts.eval_analysis,
            user_message=user_prompt,
            images=[],
            temperature=float(cfg.generation.gen_temperature),
            max_tokens=int(cfg.generation.gen_max_tokens),
            # Prevent "No relevant context found." injection; this endpoint provides all context in user_prompt.
            context_text="",
            context_chunks=[],
            timeout_s=float(cfg.generation.gen_timeout),
        )
    except Exception as e:
        return EvalAnalyzeComparisonResponse(
            ok=False,
            analysis=None,
            model_used=str(route.model),
            error=provider_setup_checklist(
                f"Eval AI analysis failed: {e}",
                selected_kind=str(route.kind),
                selected_model=str(route.model),
            ),
        )

    return EvalAnalyzeComparisonResponse(
        ok=True,
        analysis=str(text or "").strip(),
        model_used=str(route.model),
        error=None,
    )
