from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from server.api.dependency_errors import raise_required_dependency_unavailable_if_applicable
from server.api.retrieval_errors import (
    RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
    required_retrieval_leg_http_exception,
    retrieval_contract_mismatch_http_exception,
)
from server.retrieval.errors import RequiredRetrievalLegError, RetrievalContractMismatchError
from server.chat.benchmark_runner import run_benchmark
from server.config import load_config
from server.lineage import (
    attach_refs_to_current_bundle,
    capture_benchmark_run_version,
    ensure_current_bundle,
    make_ref,
)
from server.observability import metrics
from server.observability.ml_quality import build_benchmark_observability_summary
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    BenchmarkRetrieval,
    BenchmarkObservabilitySummaryResponse,
    BenchmarkRun,
    BenchmarkRunRequest,
    BenchmarkRunsResponse,
    CorpusScope,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.retrieval.fusion import TriBridFusion

router = APIRouter(tags=["benchmark"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()


def _results_dir(path_str: str) -> Path:
    path = Path(str(path_str or "data/benchmarks/"))
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_path(results_path: str, run_id: str) -> Path:
    return _results_dir(results_path) / f"{run_id}.json"


def _load_benchmark_run(path: Path) -> BenchmarkRun | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    raw.setdefault("prompt", "")
    raw.setdefault("models", [str(item.get("model") or "") for item in raw.get("results", []) if isinstance(item, dict)])
    raw.setdefault("corpus_id", raw.get("repo_id"))
    raw.setdefault("input_bundle_id", None)
    raw.setdefault("bundle_id", None)
    raw.setdefault("lineage_ref", None)
    try:
        return BenchmarkRun.model_validate(raw)
    except Exception:
        return None


@router.post("/benchmark/run", response_model=BenchmarkRun, responses=RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES)
async def benchmark_run(
    payload: BenchmarkRunRequest,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> BenchmarkRun:
    """Run the same prompt against multiple models (best-effort).

    This endpoint is intended for local benchmarking and may require provider
    credentials (for example `OPENAI_API_KEY`, `LITELLM_API_KEY`, or
    `LITELLM_API_KEY`) and the managed LiteLLM/vLLM services.
    """
    repo_id = scope.resolved_repo_id
    if repo_id:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    else:
        cfg = load_config()
    if not bool(getattr(cfg.chat.benchmark, "enabled", False)):
        raise HTTPException(status_code=400, detail="Benchmarking is disabled")

    prompt = str(payload.prompt or "").strip()
    models = [str(m).strip() for m in (payload.models or []) if str(m).strip()]

    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt")
    if len(models) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 models")
    if len(models) > int(getattr(cfg.chat.benchmark, "max_concurrent_models", 4) or 4):
        raise HTTPException(status_code=400, detail="Too many models selected")

    input_bundle_id: str | None = None
    if repo_id:
        input_bundle_id = ensure_current_bundle(repo_id=repo_id, cfg=cfg).bundle_id

    # Ground the prompt exactly like chat does (tri-brid fusion on the corpus).
    # A benchmark that silently answered from world knowledge was the 2026-08-25
    # drive finding M8; retrieval failures fail the run instead of degrading.
    context_chunks: list[ChunkMatch] = []
    if repo_id:
        fusion = TriBridFusion()
        try:
            context_chunks = await fusion.search(
                [repo_id],
                prompt,
                cfg.fusion,
                include_vector=True,
                include_sparse=True,
                include_graph=True,
                top_k=None,
                cache_mode="default",
                cache_namespace="benchmark_retrieval",
            )
        except HTTPException:
            raise
        except RetrievalContractMismatchError as exc:
            raise retrieval_contract_mismatch_http_exception(exc) from exc
        except RequiredRetrievalLegError as exc:
            raise required_retrieval_leg_http_exception(exc) from exc
        except Exception as exc:
            raise_required_dependency_unavailable_if_applicable(exc, boundary="Benchmark retrieval")
            raise
        retrieval = BenchmarkRetrieval(
            corpus_id=repo_id,
            grounded=bool(context_chunks),
            chunk_count=len(context_chunks),
            reason=None if context_chunks else "tri-brid retrieval returned no chunks for this prompt on the corpus",
            source_paths=list(
                dict.fromkeys(str(c.file_path) for c in context_chunks if getattr(c, "file_path", None))
            ),
        )
    else:
        retrieval = BenchmarkRetrieval(
            corpus_id=None,
            grounded=False,
            chunk_count=0,
            reason="no corpus scope: the benchmark ran without retrieval",
            source_paths=[],
        )

    run = await run_benchmark(
        prompt=prompt,
        models=models,
        config=cfg,
        repo_id=repo_id,
        context_chunks=context_chunks,
        retrieval=retrieval,
    )
    run.input_bundle_id = input_bundle_id

    # ML-quality metrics for the Eval/Benchmark/Prompt dashboard.
    metrics.BENCHMARK_RUNS_TOTAL.inc()
    latencies = [float(item.latency_ms) for item in (run.results or []) if item.latency_ms is not None]
    if latencies:
        metrics.BENCHMARK_LAST_AVG_LATENCY_MS.set(sum(latencies) / len(latencies))

    if repo_id:
        version = capture_benchmark_run_version(run=run)
        bundle, _aliases = attach_refs_to_current_bundle(
            repo_id=repo_id,
            cfg=cfg,
            benchmark_runs=[make_ref("benchmark_run", version.version_id)],
            preserve_attached_refs=True,
        )
        run.lineage_ref = make_ref("benchmark_run", version.version_id)
        run.bundle_id = bundle.bundle_id
        out_file = _run_path(str(getattr(cfg.chat.benchmark, "results_path", "data/benchmarks/") or "data/benchmarks/"), run.run_id)
        if out_file.exists():
            out_file.write_text(json.dumps(run.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2), encoding="utf-8")

    return run


@router.get("/benchmark/results", response_model=BenchmarkRunsResponse)
async def benchmark_results(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
    limit: int = Query(default=20, ge=1, le=200),
) -> BenchmarkRunsResponse:
    """Return recent benchmark runs (best-effort)."""
    repo_id = scope.resolved_repo_id
    if repo_id:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    else:
        cfg = load_config()
    path = _results_dir(str(getattr(cfg.chat.benchmark, "results_path", "data/benchmarks/") or "data/benchmarks/"))
    if not path.exists():
        return BenchmarkRunsResponse(ok=True, runs=[])

    runs: list[BenchmarkRun] = []
    files = sorted(path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[: int(limit)]:
        run = _load_benchmark_run(f)
        if run is None:
            continue
        if repo_id and str(run.repo_id or "").strip() != str(repo_id).strip():
            continue
        runs.append(run)
    return BenchmarkRunsResponse(ok=True, runs=runs)


@router.get("/benchmark/observability/summary", response_model=BenchmarkObservabilitySummaryResponse)
async def benchmark_observability_summary(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> BenchmarkObservabilitySummaryResponse:
    repo_id = scope.resolved_repo_id
    if repo_id:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except CorpusNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    else:
        cfg = load_config()
    return build_benchmark_observability_summary(cfg, repo_id)
