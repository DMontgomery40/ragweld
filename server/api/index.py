from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
import multiprocessing
import platform
import re
import sys
import uuid
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from server.chat.provider_router import ProviderRoute, select_provider_route
from server.db.neo4j import Neo4jClient
from server.api.dependency_errors import dependency_unavailable_http_exception
from server.dependency_errors import DependencyUnavailableError
from server.api.retrieval_errors import retrieval_contract_mismatch_http_exception
from server.retrieval.errors import RetrievalContractMismatchError
from server.db.postgres import PostgresClient
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.indexing.loader import FileLoader
from server.indexing.official_graphrag import (
    extract_semantic_kg_with_graphrag,
    write_lexical_graph_with_graphrag,
)
from server.indexing.oss_retrieval_pilot import (
    build_retrieval_pilot_status,
    export_retrieval_pilot,
    ingest_retrieval_pilot_execution,
    search_retrieval_pilot_execution,
    search_retrieval_pilot_preview,
)
from server.indexing.text_extractors import extract_text_for_path
from server.models.index import (
    Chunk,
    IndexRequest,
    IndexRunEvent,
    IndexRunSummary,
    IndexStats,
    IndexStatus,
)
from server.models.tribrid_config_model import (
    CorpusScope,
    DashboardEmbeddingConfigSummary,
    DashboardIndexCosts,
    DashboardIndexStatsResponse,
    DashboardIndexStatusMetadata,
    DashboardIndexStatusResponse,
    DashboardIndexStorageBreakdown,
    IndexEstimate,
    RetrievalPilotExportRequest,
    RetrievalPilotExportResponse,
    RetrievalPilotIngestRequest,
    RetrievalPilotIngestResponse,
    RetrievalPilotSearchRequest,
    RetrievalPilotSearchResponse,
    RetrievalPilotSearchPreviewRequest,
    RetrievalPilotSearchPreviewResponse,
    RetrievalPilotStatusResponse,
    TriBridConfig,
    VocabPreviewResponse,
)
from server.observability.metrics import (
    CHUNKS_INDEXED_CURRENT,
    GRAPH_ENTITIES_CURRENT,
    GRAPH_RELATIONSHIPS_CURRENT,
    INDEX_CHUNKS_CREATED_TOTAL,
    INDEX_DURATION_SECONDS,
    INDEX_ERRORS_TOTAL,
    INDEX_FILES_PROCESSED_TOTAL,
    INDEX_RUNS_TOTAL,
    INDEX_STAGE_ERRORS_TOTAL,
    INDEX_STAGE_LATENCY_SECONDS,
    INDEX_TOKENS_TOTAL,
)
from server.services.config_store import get_config as load_scoped_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["index"])

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_STATUS: dict[str, IndexStatus] = {}
_STATS: dict[str, IndexStats] = {}
_TASKS: dict[str, asyncio.Task[None]] = {}
_EVENT_QUEUES: dict[str, asyncio.Queue[dict[str, Any]]] = {}
_LAST_STARTED_REPO: str | None = None

_MODELS_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"
_INDEX_RUNS_DIR = Path(__file__).parent.parent.parent / "data" / "index_runs"
_STAGING_REPO_PREFIX = "__staging__"

_ACTIVE_RUNS: dict[str, str] = {}
_QUEUE_RUN_CONTEXT: dict[int, tuple[str, str]] = {}

# Index estimate heuristics (intentionally rough).
_EST_BYTES_PER_TOKEN = 4.0  # common rule-of-thumb for English-ish text
_EST_TOKENS_PER_SECOND_CLOUD = 50_000
_EST_TOKENS_PER_SECOND_DETERMINISTIC = 120_000
_EST_OVERHEAD_SECONDS = 12.0
_EST_RANGE_LOW_MULT = 0.6
_EST_RANGE_HIGH_MULT = 1.9

# Local embedding throughput heuristics (tokens/sec) by hardware class.
_LOCAL_EMBED_TPS_TABLE: dict[str, dict[str, int]] = {
    "apple_silicon_mlx": {"mlx": 60_000, "huggingface": 12_000, "local": 10_000, "_default": 12_000},
    "apple_silicon_cpu": {"mlx": 18_000, "huggingface": 9_000, "local": 8_000, "_default": 8_000},
    "cuda_gpu": {"mlx": 25_000, "huggingface": 40_000, "local": 35_000, "_default": 32_000},
    "cpu_only": {"mlx": 6_000, "huggingface": 5_000, "local": 4_000, "_default": 4_500},
}

# Semantic KG LLM extraction throughput heuristic (calls/sec) by provider.
_SEMANTIC_KG_CALLS_PER_SECOND: dict[str, float] = {
    "litellm": 1.0,
}


def _idle_status(repo_id: str) -> IndexStatus:
    return IndexStatus(
        repo_id=repo_id,
        status="idle",
        progress=0.0,
        current_file=None,
        error=None,
        started_at=None,
        completed_at=None,
    )


def _clear_runtime_state_for_repo(repo_id: str, *, queue: asyncio.Queue[dict[str, Any]] | None = None) -> None:
    # Remove task only when this cleanup corresponds to the currently-registered task.
    cur_task = _TASKS.get(repo_id)
    if cur_task is not None and (queue is None or _EVENT_QUEUES.get(repo_id) is queue):
        if cur_task.done():
            _TASKS.pop(repo_id, None)

    # Remove queue only when this cleanup corresponds to the currently-registered queue.
    if queue is None:
        _EVENT_QUEUES.pop(repo_id, None)
    elif _EVENT_QUEUES.get(repo_id) is queue:
        _EVENT_QUEUES.pop(repo_id, None)

    _ACTIVE_RUNS.pop(repo_id, None)
    if queue is not None:
        _QUEUE_RUN_CONTEXT.pop(id(queue), None)


def _sanitize_fs_component(value: str) -> str:
    v = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    v = re.sub(r"_+", "_", v).strip("_")
    return v or "unknown"


def _repo_runs_dir(repo_id: str) -> Path:
    return _INDEX_RUNS_DIR / _sanitize_fs_component(repo_id)


def _run_dir(repo_id: str, run_id: str) -> Path:
    return _repo_runs_dir(repo_id) / _sanitize_fs_component(run_id)


def _run_summary_path(repo_id: str, run_id: str) -> Path:
    return _run_dir(repo_id, run_id) / "summary.json"


def _run_events_path(repo_id: str, run_id: str) -> Path:
    return _run_dir(repo_id, run_id) / "events.jsonl"


async def _resolve_repo_path_from_request(repo_id: str, repo_path: str | None) -> str:
    resolved = str(repo_path or "").strip()
    if resolved:
        return resolved

    cfg_global = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg_global.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
        if corpus is not None:
            resolved = str(corpus.get("path") or "").strip()
    finally:
        await pg.disconnect()

    return resolved


def _persist_run_summary(summary: IndexRunSummary) -> None:
    path = _run_summary_path(summary.repo_id, summary.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary.model_dump_json(by_alias=True, exclude_none=False, indent=2))


def _load_run_summary(repo_id: str, run_id: str) -> IndexRunSummary | None:
    path = _run_summary_path(repo_id, run_id)
    if not path.exists():
        return None
    try:
        return IndexRunSummary.model_validate_json(path.read_text())
    except Exception:
        return None


def _load_latest_run_summary(repo_id: str) -> IndexRunSummary | None:
    repo_dir = _repo_runs_dir(repo_id)
    if not repo_dir.exists():
        return None
    candidates = sorted(
        [p for p in repo_dir.glob("*/summary.json") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        try:
            return IndexRunSummary.model_validate_json(p.read_text())
        except Exception:
            continue
    return None


def _coerce_stale_indexing_run_to_error(repo_id: str, run: IndexRunSummary) -> IndexRunSummary:
    """Coerce a persisted indexing run to an error when no active task owns it.

    This handles process restarts/crashes where in-memory task state is lost and
    a run would otherwise appear to be "indexing" forever.
    """
    if str(getattr(run, "status", "") or "").strip().lower() != "indexing":
        return run

    task = _TASKS.get(repo_id)
    if task is not None and not task.done():
        return run

    msg = (
        "Indexing interrupted before completion (server restart or worker crash). "
        "Start a new indexing run."
    )
    finalized = run.model_copy(
        update={
            "status": "error",
            "completed_at": datetime.now(UTC),
            "error": str(run.error or msg),
        }
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(finalized)

    # Append one terminal event if one has not been recorded yet.
    with contextlib.suppress(Exception):
        tail = _load_run_events(repo_id, run.run_id, limit=5)
        has_terminal = any(ev.type in {"complete", "error", "cancelled"} for ev in tail)
        if not has_terminal:
            _append_run_event(
                repo_id,
                run.run_id,
                {
                    "type": "error",
                    "message": finalized.error,
                    "percent": int(max(0.0, min(1.0, float(finalized.progress or 0.0))) * 100),
                },
            )
    return finalized


def _allow_parallel_chunk_batches(*, indexing_workers: int, batch_count: int, has_graph_upserts: bool) -> bool:
    """Whether chunk upsert batches can safely run concurrently.

    Neo4j chunk/document writes can deadlock under concurrent per-file batch
    upserts. Keep those writes serialized even when indexing_workers > 1.
    """
    if int(batch_count or 0) <= 1:
        return False
    if int(indexing_workers or 0) <= 1:
        return False
    if has_graph_upserts:
        return False
    return True


def _allow_cross_file_chunk_batching(
    *,
    has_graph_upserts: bool,
    semantic_kg_enabled: bool,
) -> bool:
    """Whether small-file chunks can be batched across files before embedding/upsert.

    Cross-file batching is only safe when we do not need per-file graph writes
    or per-file semantic KG extraction queues.
    """
    if has_graph_upserts:
        return False
    if semantic_kg_enabled:
        return False
    return True


def _to_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _append_run_event(repo_id: str, run_id: str, event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "").strip()
    if not event_type:
        return
    evt = IndexRunEvent(
        run_id=run_id,
        ts=datetime.now(UTC),
        type=event_type,
        message=str(event.get("message")) if event.get("message") is not None else None,
        percent=_to_optional_int(event.get("percent")),
        current_file=str(event.get("current_file")) if event.get("current_file") is not None else None,
        meta={
            k: v
            for k, v in event.items()
            if k not in {"type", "message", "percent", "current_file"}
        },
    )
    path = _run_events_path(repo_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(evt.model_dump_json(by_alias=True, exclude_none=True) + "\n")


def _load_run_events(repo_id: str, run_id: str, *, limit: int) -> list[IndexRunEvent]:
    path = _run_events_path(repo_id, run_id)
    if not path.exists():
        return []
    out: list[IndexRunEvent] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(IndexRunEvent.model_validate_json(line))
            except Exception:
                continue
    except Exception:
        return []
    lim = max(1, min(int(limit or 200), 5000))
    return out[-lim:]


def _build_staging_repo_id(repo_id: str, run_id: str) -> str:
    return f"{_STAGING_REPO_PREFIX}{repo_id}__{run_id}"


async def _clear_semantic_cache_for_repo(repo_id: str) -> None:
    """Best-effort corpus cache invalidation used by indexing terminal paths."""
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    try:
        await postgres.semantic_cache_clear_for_corpus(repo_id)
    finally:
        with contextlib.suppress(Exception):
            await postgres.disconnect()


async def _cancel_index_run(repo_id: str) -> IndexStatus:
    repo_id = str(repo_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")

    task = _TASKS.get(repo_id)
    if task is None:
        return _STATUS.get(repo_id) or _idle_status(repo_id)

    prev = _STATUS.get(repo_id)
    queue = _EVENT_QUEUES.get(repo_id)
    _STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="cancelled",
        progress=float(prev.progress) if prev else 0.0,
        current_file=prev.current_file if prev else None,
        error=None,
        started_at=prev.started_at if prev else None,
        completed_at=datetime.now(UTC),
    )
    if queue is not None:
        _emit_event(
            queue,
            {"type": "cancelled", "message": "⚠ Indexing cancelled"},
            guarantee=True,
        )

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task

    _TASKS.pop(repo_id, None)
    _clear_runtime_state_for_repo(repo_id, queue=queue)
    return _STATUS[repo_id]


def _estimate_tokens_from_bytes(total_bytes: int) -> int:
    b = max(0, int(total_bytes or 0))
    return int(float(b) / float(_EST_BYTES_PER_TOKEN)) if b > 0 else 0


def _estimate_chunks_from_tokens(*, tokens: int, target_tokens: int, overlap_tokens: int) -> int:
    t = max(0, int(tokens or 0))
    target = max(1, int(target_tokens or 0))
    overlap = max(0, int(overlap_tokens or 0))
    stride = max(1, target - min(overlap, target - 1))
    # Ceiling division
    return int((t + stride - 1) // stride) if t > 0 else 0


def _looks_cloud_provider(provider: str) -> bool:
    p = (provider or "").strip().lower()
    return p in {"openai", "voyage", "cohere", "google", "mistral", "jina", "deepseek"}


def _norm_key(s: str | None) -> str:
    return str(s or "").strip().lower()


def _to_float(x: Any) -> float | None:
    try:
        v = float(x)
    except Exception:
        return None
    if v != v:  # NaN guard
        return None
    return v


def _model_has_component(spec: dict[str, Any], component: str) -> bool:
    comps = spec.get("components")
    if not isinstance(comps, list):
        return False
    target = str(component or "").strip().upper()
    return any(str(c or "").strip().upper() == target for c in comps)


def _find_model_spec(
    models: list[dict[str, Any]], *, provider: str | None, model: str | None
) -> dict[str, Any] | None:
    """Best-effort model lookup (provider+model, then model, then provider)."""
    prov = _norm_key(provider)
    mdl = _norm_key(model)

    if prov and mdl:
        for m in models:
            if _norm_key(m.get("provider")) == prov and _norm_key(m.get("model")) == mdl:
                return m

    if mdl:
        for m in models:
            if _norm_key(m.get("model")) == mdl:
                return m

    # No provider-only fallback: returning the first model for a provider
    # when the requested model is missing would silently price the wrong model.
    return None


def _semantic_kg_model_override(cfg: TriBridConfig) -> str:
    alias = str(cfg.graph_indexing.semantic_kg_llm_model or cfg.chat.litellm.default_model or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]+", alias) is None:
        raise ValueError("GraphRAG semantic model must be a configured LiteLLM alias.")
    return alias


def _resolve_semantic_kg_route(cfg: TriBridConfig) -> ProviderRoute:
    route = select_provider_route(config=cfg, model_override=_semantic_kg_model_override(cfg))
    if route.kind != "litellm":
        raise ValueError(f"GraphRAG semantic model must resolve through LiteLLM, got {route.kind}.")
    if not str(route.base_url or "").strip():
        raise ValueError("GraphRAG semantic model resolved without a base URL.")
    if not str(route.model or "").strip():
        raise ValueError("GraphRAG semantic model resolved without a model id.")
    return route


def _detect_local_hardware_class() -> str:
    machine = str(platform.machine() or "").strip().lower()
    is_apple_silicon = sys.platform == "darwin" and machine in {"arm64", "aarch64"}

    has_mlx = importlib.util.find_spec("mlx") is not None
    has_cuda = False
    if importlib.util.find_spec("torch") is not None:
        with contextlib.suppress(Exception):
            import torch  # type: ignore[import-not-found,unused-ignore]

            has_cuda = bool(torch.cuda.is_available())

    if is_apple_silicon and has_mlx:
        return "apple_silicon_mlx"
    if is_apple_silicon:
        return "apple_silicon_cpu"
    if has_cuda:
        return "cuda_gpu"
    return "cpu_only"


def _estimate_local_tokens_per_second(*, cfg: TriBridConfig, provider: str) -> int:
    override = getattr(cfg.indexing, "estimated_tokens_per_second_local", None)
    if override is not None:
        with contextlib.suppress(Exception):
            ov = int(override)
            if ov > 0:
                return ov

    hw_class = _detect_local_hardware_class()
    table = _LOCAL_EMBED_TPS_TABLE.get(hw_class, _LOCAL_EMBED_TPS_TABLE["cpu_only"])
    p = _norm_key(provider)
    est = int(table.get(p) or table.get("_default") or _LOCAL_EMBED_TPS_TABLE["cpu_only"]["_default"])
    if hw_class == "cpu_only":
        cores = max(1, multiprocessing.cpu_count())
        if cores >= 24:
            est = max(est, 8_000)
        elif cores >= 12:
            est = max(est, 6_000)
    return est


def _resolve_semantic_kg_model_and_provider(cfg: TriBridConfig) -> tuple[str, str]:
    return _semantic_kg_model_override(cfg), "litellm"


def _estimate_semantic_kg_cost_usd(
    *,
    provider_hint: str,
    model: str,
    chunks_in_scope: int,
    enrich_max_chars: int,
) -> float | None:
    """Estimate semantic KG LLM extraction cost from models.json GEN pricing."""
    count = max(0, int(chunks_in_scope or 0))
    if count <= 0:
        return 0.0
    mname = str(model or "").strip()
    if not mname:
        return None

    # Per chunk heuristic: fixed prompt overhead + bounded chunk text + concise JSON output.
    input_tokens_per_chunk = max(0, 500 + int(max(0, enrich_max_chars) / 4))
    output_tokens_per_chunk = 100
    total_input_tokens = count * input_tokens_per_chunk
    total_output_tokens = count * output_tokens_per_chunk

    spec = _find_model_spec(_load_models_json(), provider=provider_hint, model=mname)
    if not spec or not _model_has_component(spec, "GEN"):
        return None
    if str(spec.get("unit") or "").strip() != "1k_tokens":
        return None

    in_rate = _to_float(spec.get("input_per_1k"))
    out_rate = _to_float(spec.get("output_per_1k"))
    if in_rate is None and out_rate is None:
        return None
    return ((float(total_input_tokens) / 1000.0) * float(in_rate or 0.0)) + (
        (float(total_output_tokens) / 1000.0) * float(out_rate or 0.0)
    )


def _estimate_semantic_kg_seconds(
    *,
    provider: str,
    chunks_in_scope: int,
    indexing_workers: int,
) -> float:
    count = max(0, int(chunks_in_scope or 0))
    if count <= 0:
        return 0.0
    p = _norm_key(provider)
    calls_per_second = float(_SEMANTIC_KG_CALLS_PER_SECOND.get(p, 1.0))
    workers = max(1, int(indexing_workers or 1))
    # Runtime executes semantic extraction in batches up to indexing_workers.
    effective_calls_per_second = max(0.1, calls_per_second * float(min(workers, 8)))
    return float(count) / effective_calls_per_second


@lru_cache(maxsize=1)
def _load_models_json() -> list[dict[str, Any]]:
    """Load models.json (THE LAW for model pricing/metadata)."""
    try:
        raw = json.loads(_MODELS_JSON_PATH.read_text())
    except Exception:
        return []
    if isinstance(raw, dict) and isinstance(raw.get("models"), list):
        return [m for m in raw["models"] if isinstance(m, dict)]
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)]
    return []


def _estimate_embedding_cost_usd(*, provider: str, model: str, total_tokens: int) -> float | None:
    """Estimate embedding cost from models.json (if pricing is available)."""
    if total_tokens <= 0:
        return 0.0
    p = (provider or "").strip().lower()
    mname = (model or "").strip()
    if not p or not mname:
        return None

    for m in _load_models_json():
        if str(m.get("provider", "")).strip().lower() != p:
            continue
        if str(m.get("model", "")).strip() != mname:
            continue
        comps = m.get("components") or []
        if "EMB" not in comps:
            continue
        unit = str(m.get("unit") or "").strip()
        embed_per_1k = m.get("embed_per_1k")
        if unit != "1k_tokens" or embed_per_1k is None:
            return None
        try:
            price = float(embed_per_1k)
        except Exception:
            return None
        return (float(total_tokens) / 1000.0) * price
    return None


async def _resolve_dashboard_repo_id(scope: CorpusScope) -> str:
    """Resolve a corpus_id for dashboard endpoints.

    Priority:
    1) explicit scope (corpus_id/repo_id/repo)
    2) last started repo (legacy UX)
    3) only-corpus in Postgres (best-effort for single-corpus setups)
    """
    repo_id = (scope.resolved_repo_id or _LAST_STARTED_REPO or "").strip()
    if repo_id:
        return repo_id

    # Best-effort fallback: only allow implicit selection when there is exactly one corpus.
    cfg = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpora = await pg.list_corpora()
    finally:
        await pg.disconnect()

    if corpora:
        # If multiple corpora exist, never guess — callers must pass corpus_id explicitly.
        if len(corpora) > 1:
            raise HTTPException(
                status_code=400,
                detail="Missing corpus_id (or legacy repo/repo_id) query parameter. "
                "Multiple corpora exist; select a corpus explicitly.",
            )
        rid = str(corpora[0].get("repo_id") or "").strip()
        if rid:
            return rid

    raise HTTPException(
        status_code=400,
        detail="Missing corpus_id (or legacy repo/repo_id) query parameter and no corpora exist yet. Create a corpus first.",
    )


async def _compute_dashboard_storage_breakdown(*, repo_id: str) -> DashboardIndexStorageBreakdown:
    """Compute a dashboard-friendly storage breakdown (bytes) for a corpus."""
    cfg = await load_scoped_config(repo_id=repo_id)

    # Postgres (pgvector + FTS + chunk_summaries)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        breakdown = await pg.get_dashboard_storage_breakdown(repo_id)
    finally:
        await pg.disconnect()

    # Neo4j (store size via JMX)
    neo4j_store_bytes = 0
    try:
        db_name = cfg.graph_storage.resolve_database(repo_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=db_name,
        )
        await neo4j.connect()
        try:
            neo4j_store_bytes = int(await neo4j.get_store_size_bytes())
        finally:
            await neo4j.disconnect()
    except Exception:
        # Graph layer is optional; never fail dashboard rendering for missing graph.
        neo4j_store_bytes = 0

    chunks_bytes = int(breakdown.get("chunks_bytes") or 0)
    embeddings_bytes = int(breakdown.get("embeddings_bytes") or 0)
    pgvector_index_bytes = int(breakdown.get("pgvector_index_bytes") or 0)
    bm25_index_bytes = int(breakdown.get("bm25_index_bytes") or 0)
    chunk_summaries_bytes = int(breakdown.get("chunk_summaries_bytes") or 0)

    postgres_total = chunks_bytes + embeddings_bytes + pgvector_index_bytes + bm25_index_bytes + chunk_summaries_bytes
    total_storage = postgres_total + int(neo4j_store_bytes or 0)

    return DashboardIndexStorageBreakdown(
        chunks_bytes=chunks_bytes,
        embeddings_bytes=embeddings_bytes,
        pgvector_index_bytes=pgvector_index_bytes,
        bm25_index_bytes=bm25_index_bytes,
        chunk_summaries_bytes=chunk_summaries_bytes,
        neo4j_store_bytes=int(neo4j_store_bytes or 0),
        postgres_total_bytes=postgres_total,
        total_storage_bytes=total_storage,
    )


def _normalize_index_probe_text(value: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return clipped.rstrip(" ,;:.")


def _derive_post_index_dense_retrieval_queries(
    *,
    repo_id: str,
    repo_path: str,
    corpus_name: str,
    corpus_description: str | None,
    corpus_meta: dict[str, Any] | None,
    sample_chunks: list[Chunk],
    max_queries: int = 4,
) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()

    def _add(raw: str, *, max_chars: int = 220) -> None:
        text = _normalize_index_probe_text(raw, max_chars=max_chars)
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        queries.append(text)

    for chunk in sample_chunks:
        _add(chunk.content, max_chars=220)
        if len(queries) >= max_queries:
            return queries[:max_queries]

    keywords = (corpus_meta or {}).get("keywords") if isinstance(corpus_meta, dict) else None
    if isinstance(keywords, list):
        for item in keywords:
            kw = str(item or "").strip()
            if not kw:
                continue
            _add(kw, max_chars=120)
            if len(queries) >= max_queries:
                return queries[:max_queries]

    _add(str(corpus_description or ""), max_chars=160)
    if len(queries) >= max_queries:
        return queries[:max_queries]

    repo_tail = Path(repo_path).name.strip()
    for candidate in (corpus_name, repo_id, repo_tail):
        _add(str(candidate or ""), max_chars=96)
        if len(queries) >= max_queries:
            break

    return queries[:max_queries]


async def _prepare_dense_retrieval_after_indexing(
    *,
    repo_id: str,
    repo_path: str,
    cfg: TriBridConfig,
    stats: IndexStats,
    queue: asyncio.Queue[dict[str, Any]] | None,
) -> dict[str, Any]:
    if not bool(getattr(cfg.indexing, "auto_prepare_dense_retrieval", True)):
        return {"status": "disabled"}
    if getattr(cfg.indexing, "skip_dense", False):
        return {"status": "skip_dense"}
    if int(getattr(stats, "embedding_dimensions", 0) or 0) <= 0:
        return {"status": "no_dense_vectors"}

    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    try:
        embedded_chunks = await postgres.count_chunks_with_embeddings(repo_id)
        if embedded_chunks <= 0:
            return {"status": "no_embedded_chunks"}

        corpus = await postgres.get_corpus(repo_id)
        corpus_name = str((corpus or {}).get("name") or repo_id)
        corpus_description = (corpus or {}).get("description")
        corpus_meta = (corpus.get("meta") or {}) if corpus else {}

        _emit_event(
            queue,
            {
                "type": "progress",
                "percent": 99,
                "message": "Preparing dense retrieval",
                "current_file": None,
            },
            drop_oldest=True,
        )
        _emit_event(
            queue,
            {
                "type": "log",
                "message": "⚙️ Post-index dense retrieval prep: building pgvector index and warming query embeddings",
            },
            drop_oldest=True,
        )

        with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_ensure_vector_index").time():
            index_name = await postgres.ensure_vector_index(repo_id)

        sample_chunks = await postgres.list_chunks_for_repo(repo_id, limit=3)
        queries = _derive_post_index_dense_retrieval_queries(
            repo_id=repo_id,
            repo_path=repo_path,
            corpus_name=corpus_name,
            corpus_description=str(corpus_description) if corpus_description is not None else None,
            corpus_meta=corpus_meta if isinstance(corpus_meta, dict) else {},
            sample_chunks=sample_chunks,
        )

        embedder = Embedder(cfg.embedding, cfg.tokenization)
        configure_postgres_embedding_cache_backend(embedder, postgres)
        query_vectors: list[list[float]] = []
        if queries:
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="warm_query_embedding_cache").time():
                query_vectors = await embedder.embed_batch(queries)

        smoke_hits = 0
        smoke_queries = min(len(queries), len(query_vectors), 3)
        best_score = 0.0
        if smoke_queries > 0:
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="post_index_vector_smoke").time():
                for query, vector in zip(queries[:smoke_queries], query_vectors[:smoke_queries], strict=True):
                    results = await postgres.vector_search(
                        repo_id,
                        vector,
                        1,
                        expected_dimensions=int(embedder.dim),
                    )
                    if results:
                        smoke_hits += 1
                        best_score = max(best_score, float(results[0].score or 0.0))
                    else:
                        logger.warning("Dense retrieval smoke query returned no hits for corpus '%s': %s", repo_id, query)

        _emit_event(
            queue,
            {
                "type": "log",
                "message": (
                    "⚡ Dense retrieval prep complete: "
                    f"index={index_name} "
                    f"warmed_queries={len(queries)} "
                    f"smoke_hits={smoke_hits}/{smoke_queries} "
                    f"best_score={best_score:.3f}"
                ),
                "meta": {
                    "stage": "post_index_dense_retrieval",
                    "index_name": index_name,
                    "warmed_queries": int(len(queries)),
                    "smoke_hits": int(smoke_hits),
                    "smoke_queries": int(smoke_queries),
                    "best_score": float(best_score),
                },
            },
            drop_oldest=True,
        )
        return {
            "status": "ok",
            "index_name": index_name,
            "warmed_queries": int(len(queries)),
            "smoke_hits": int(smoke_hits),
            "smoke_queries": int(smoke_queries),
            "best_score": float(best_score),
        }
    except Exception as exc:
        logger.warning("Post-index dense retrieval prep failed for corpus '%s': %s", repo_id, exc, exc_info=True)
        _emit_event(
            queue,
            {
                "type": "warning",
                "message": f"Dense retrieval prep incomplete: {exc}",
            },
            drop_oldest=True,
        )
        return {"status": "error", "error": str(exc)}
    finally:
        with contextlib.suppress(Exception):
            await postgres.disconnect()


def _emit_event(
    queue: asyncio.Queue[dict[str, Any]] | None,
    event: dict[str, Any],
    *,
    drop_oldest: bool = False,
    guarantee: bool = False,
) -> None:
    """Best-effort event emission without blocking indexing.

    Indexing can run for many thousands of files. If no SSE client is consuming
    events, a bounded asyncio.Queue will fill and `await queue.put(...)` will
    deadlock the indexing task. We always emit events non-blockingly and drop
    old events when requested.
    """
    if queue is None:
        return

    ctx = _QUEUE_RUN_CONTEXT.get(id(queue))
    if ctx is not None:
        repo_id, run_id = ctx
        with contextlib.suppress(Exception):
            _append_run_event(repo_id, run_id, event)

    if guarantee:
        # Ensure this event is delivered by dropping older events until there is room.
        while True:
            try:
                queue.put_nowait(event)
                return
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        if not drop_oldest:
            return
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            return


async def _run_index(
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    *,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
    run_id: str,
    write_repo_id: str | None = None,
) -> IndexStats:
    cfg = await load_scoped_config(repo_id=repo_id)
    target_repo_id = str(write_repo_id or repo_id)

    if not force_reindex and repo_id in _STATS:
        return _STATS[repo_id]

    # Build ignore patterns from config
    ignore_patterns: list[str] = []
    exts = (cfg.indexing.index_excluded_exts or "").split(",")
    for ext in exts:
        ext = ext.strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        ignore_patterns.append(f"*{ext}")

    chunker = Chunker(cfg.chunking, cfg.tokenization)
    # Enforce a strict max file size before reading/chunking.
    # LAW sources:
    # - cfg.chunking.max_indexable_file_size (bytes)
    # - cfg.indexing.index_max_file_size_mb (MB)
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )
    skip_dense = cfg.indexing.skip_dense
    embedder = None if skip_dense else Embedder(cfg.embedding, cfg.tokenization)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    active_corpus = await postgres.get_corpus(repo_id)
    active_meta = (active_corpus.get("meta") or {}) if active_corpus else {}
    active_name = str((active_corpus or {}).get("name") or repo_id)
    active_description = (active_corpus or {}).get("description")
    await postgres.upsert_corpus(
        target_repo_id,
        name=active_name,
        root_path=repo_path,
        description=str(active_description) if active_description is not None else None,
        meta={**active_meta, "internal_staging": target_repo_id != repo_id},
    )
    if embedder is not None:
        configure_postgres_embedding_cache_backend(embedder, postgres)

    # Corpus-level exclude paths (stored in Postgres corpora.meta.exclude_paths)
    extra_gitignore_patterns: list[str] = []
    corpus: dict[str, Any] | None = None
    try:
        corpus = await postgres.get_corpus(repo_id)
        meta = (corpus.get("meta") or {}) if corpus else {}
        raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
        if isinstance(raw, list):
            extra_gitignore_patterns = [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        extra_gitignore_patterns = []

    # ---- Embedding mismatch guard ----
    # Detect when the current embedding config differs from what was used to
    # build the existing index.  Mixed-dimension vectors in the same corpus
    # cause pgvector query errors (unhandled 500s) and silently corrupt search
    # results.  Block the run unless force_reindex is set.
    # NOTE: Only guard when the corpus actually has non-null embeddings.
    # After a delete operation, embedding metadata lingers on the corpora row
    # even though vectors may be gone, so the guard must not block a fresh run.
    if corpus and not force_reindex and not skip_dense and embedder is not None:
        meta = corpus.get("meta") if isinstance(corpus.get("meta"), dict) else {}
        stored_backend = str((meta or {}).get("embedding_backend") or "").strip().lower()
        if not stored_backend:
            # Legacy corpora did not persist backend identity. Treat as deterministic
            # to avoid silently mixing deterministic and provider vectors.
            stored_backend = "deterministic"
        stored_model = str(corpus.get("embedding_model") or "").strip()
        stored_dim = int(corpus.get("embedding_dimensions") or 0)
        stored_provider = str(corpus.get("embedding_provider") or "").strip()

        # Only check if the corpus has been indexed before (non-empty metadata)
        # AND still contains embedded vectors. If vectors were deleted but
        # metadata was not cleared, there is nothing to protect.
        has_embeddings = False
        if stored_model and stored_dim > 0:
            embedding_chunks = await postgres.count_chunks_with_embeddings(repo_id)
            has_embeddings = embedding_chunks > 0
        if stored_model and stored_dim > 0 and has_embeddings:
            current_model = str(cfg.embedding.effective_model or "").strip()
            current_dim = int(embedder.dim)
            current_backend = str(cfg.embedding.embedding_backend or "").strip().lower() or "deterministic"
            current_provider = str(cfg.embedding.embedding_type or "").strip()
            both_deterministic = current_backend == "deterministic" and stored_backend == "deterministic"

            mismatches: list[str] = []
            if stored_dim != current_dim:
                mismatches.append(f"dimensions: stored={stored_dim}, config={current_dim}")
            if not both_deterministic and stored_model != current_model:
                mismatches.append(f"model: stored={stored_model}, config={current_model}")
            if stored_backend != current_backend:
                mismatches.append(f"backend: stored={stored_backend}, config={current_backend}")
            if not both_deterministic and stored_provider != current_provider:
                mismatches.append(f"provider: stored={stored_provider}, config={current_provider}")

            if mismatches:
                detail = "; ".join(mismatches)
                msg = (
                    f"Embedding configuration mismatch for corpus '{repo_id}': {detail}. "
                    "Re-indexing without force_reindex would mix incompatible vectors. "
                    "Set force_reindex=true to clear the existing index first, "
                    "or restore the embedding config to match the current index."
                )
                if event_queue is not None:
                    _emit_event(
                        event_queue,
                        {"type": "error", "message": msg},
                        guarantee=True,
                    )
                raise RuntimeError(msg)

    loader = FileLoader(ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra_gitignore_patterns)

    neo4j: Neo4jClient | None = None
    try:
        if cfg.graph_indexing.enabled:
            db_name = cfg.graph_storage.resolve_database(repo_id)
            neo4j = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.resolve_password(),
                database=db_name,
            )
            await neo4j.connect()
            try:
                await neo4j.ensure_schema()
            except Exception as exc:
                _emit_event(
                    event_queue,
                    {"type": "error", "message": f"Neo4j schema initialization failed: {exc}"},
                    guarantee=True,
                )
                raise RuntimeError(f"Neo4j schema initialization failed: {exc}") from exc
            # Lexical chunk vector index (Neo4j native vector indexes)
            if cfg.graph_indexing.build_lexical_graph and cfg.graph_indexing.store_chunk_embeddings and not skip_dense:
                try:
                    assert embedder is not None
                    online = await neo4j.ensure_vector_index(
                        index_name=cfg.graph_indexing.chunk_vector_index_name,
                        label="Chunk",
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                        dimensions=int(embedder.dim),
                        similarity_function=cfg.graph_indexing.vector_similarity_function,
                        wait_online=cfg.graph_indexing.wait_vector_index_online,
                        timeout_s=float(cfg.graph_indexing.vector_index_online_timeout_s),
                    )
                    if not online:
                        _emit_event(
                            event_queue,
                            {
                                "type": "warning",
                                "message": (
                                    "Neo4j chunk vector index did not reach ONLINE state "
                                    f"({cfg.graph_indexing.chunk_vector_index_name})"
                                ),
                            },
                            drop_oldest=True,
                        )
                except Exception:
                    logger.warning("Neo4j vector index ensure failed", exc_info=True)
                    _emit_event(
                        event_queue,
                        {"type": "warning", "message": "Neo4j chunk vector index setup failed for this run"},
                        drop_oldest=True,
                    )
    except Exception as exc:
        # Explicitly fail when graph indexing was requested but cannot initialize.
        logger.warning("Neo4j graph initialization failed for repo_id=%s: %s", repo_id, exc, exc_info=True)
        raise

    try:
        return await _run_index_body(
            repo_id=repo_id,
            repo_path=repo_path,
            force_reindex=force_reindex,
            run_id=run_id,
            cfg=cfg,
            chunker=chunker,
            max_indexable_bytes=max_indexable_bytes,
            skip_dense=skip_dense,
            embedder=embedder,
            postgres=postgres,
            neo4j=neo4j,
            loader=loader,
            event_queue=event_queue,
            write_repo_id=target_repo_id,
        )
    finally:
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.disconnect()


async def _run_index_body(
    *,
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    run_id: str,
    cfg: TriBridConfig,
    chunker: Chunker,
    max_indexable_bytes: int,
    skip_dense: bool,
    embedder: Embedder | None,
    postgres: PostgresClient,
    neo4j: Neo4jClient | None,
    loader: FileLoader,
    event_queue: asyncio.Queue[dict[str, Any]] | None,
    write_repo_id: str,
) -> IndexStats:
    """Core indexing loop -- extracted to allow _run_index() to guarantee Neo4j cleanup via finally."""
    total_files = 0
    total_chunks = 0
    total_tokens = 0
    file_breakdown: dict[str, int] = defaultdict(int)

    prev_status = _STATUS.get(repo_id)
    started_at = prev_status.started_at if prev_status and prev_status.started_at else datetime.now(UTC)

    # Collect file paths once so we can report progress deterministically,
    # without loading every file's contents into memory.
    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="collect_file_paths").time():
        file_entries = list(loader.iter_repo_files(repo_path))
    total_files = len(file_entries)

    if force_reindex:
        await postgres.delete_chunks(write_repo_id)
        if neo4j is not None:
            await neo4j.delete_graph(write_repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": "🧹 Cleared existing index (force_reindex=1)"},
                drop_oldest=True,
            )

    # If skip_dense is enabled, ensure no stale embeddings remain from previous runs.
    # This makes graph-only / sparse-only workflows deterministic.
    if skip_dense:
        deleted = await postgres.delete_embeddings(write_repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": f"⚡ skip_dense=1 → skipping embeddings (cleared {deleted} existing vectors)"},
                drop_oldest=True,
            )

    semantic_budget = int(cfg.graph_indexing.semantic_kg_max_chunks) if cfg.graph_indexing.semantic_kg_enabled else 0
    semantic_processed = 0
    semantic_entities_total = 0
    semantic_relations_total = 0
    semantic_empty_chunks = 0
    contextual_mode = str(getattr(cfg.embedding, "contextual_chunk_embeddings", "off") or "off").strip().lower()
    indexing_workers = max(1, int(getattr(cfg.indexing, "indexing_workers", 1) or 1))
    has_graph_upserts = bool(neo4j is not None and cfg.graph_indexing.build_lexical_graph)
    cross_file_chunk_batching = _allow_cross_file_chunk_batching(
        has_graph_upserts=has_graph_upserts,
        semantic_kg_enabled=bool(neo4j is not None and cfg.graph_indexing.semantic_kg_enabled),
    )
    pending_cross_file_chunks: list[Chunk] = []
    indexing_batch = max(10, int(getattr(cfg.indexing, "indexing_batch_size", 100) or 100))
    cross_file_flush_size = max(indexing_batch, indexing_batch * max(1, indexing_workers))

    async def _upsert_chunk_batch(chunks: list[Chunk]) -> list[Chunk]:
        nonlocal total_chunks, total_tokens
        if not chunks:
            return []
        total_chunks += len(chunks)
        chunk_tokens = sum(int(c.token_count or 0) for c in chunks)
        total_tokens += chunk_tokens
        INDEX_CHUNKS_CREATED_TOTAL.inc(len(chunks))
        INDEX_TOKENS_TOTAL.inc(chunk_tokens)

        if skip_dense:
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_fts").time():
                await postgres.upsert_fts(write_repo_id, chunks, ts_config=cfg.indexing.postgres_ts_config)
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                batch_paths = {str(ch.file_path or "") for ch in chunks}
                if len(batch_paths) != 1:
                    raise RuntimeError("Lexical graph upserts require a single-file chunk batch")
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_document_chunks").time():
                    graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
                        repo_id=write_repo_id,
                        run_id=run_id,
                        file_path=next(iter(batch_paths)),
                        chunks=chunks,
                    )
                    await neo4j.upsert_graphrag_graph(
                        write_repo_id,
                        graph,
                        lexical_graph_config=lexical_graph_config,
                    )
            return chunks

        assert embedder is not None
        if all(c.embedding is not None for c in chunks):
            embedded = chunks
        else:
            contextual_inputs: list[str] | None = None
            if contextual_mode == "prepend_context":
                contextual_inputs = [
                    (
                        f"[file_path={c.file_path}] [line_range={int(c.start_line)}-{int(c.end_line)}]\n"
                        f"{c.content}"
                    )
                    for c in chunks
                ]
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="embed_chunks").time():
                embedded = await embedder.embed_chunks(chunks, embed_texts=contextual_inputs)
        with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_embeddings").time():
            await postgres.upsert_embeddings(write_repo_id, embedded)
        with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_fts").time():
            await postgres.upsert_fts(write_repo_id, embedded, ts_config=cfg.indexing.postgres_ts_config)
        if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
            batch_paths = {str(ch.file_path or "") for ch in embedded}
            if len(batch_paths) != 1:
                raise RuntimeError("Lexical graph upserts require a single-file chunk batch")
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_document_chunks").time():
                graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
                    repo_id=write_repo_id,
                    run_id=run_id,
                    file_path=next(iter(batch_paths)),
                    chunks=embedded,
                )
                await neo4j.upsert_graphrag_graph(
                    write_repo_id,
                    graph,
                    lexical_graph_config=lexical_graph_config,
                )
        return embedded

    async def _upsert_chunk_batches(
        chunks: list[Chunk],
        *,
        _indexing_batch: int = indexing_batch,
        _indexing_workers: int = indexing_workers,
    ) -> list[Chunk]:
        if not chunks:
            return []
        batches = [chunks[i0 : i0 + _indexing_batch] for i0 in range(0, len(chunks), _indexing_batch)]
        if not _allow_parallel_chunk_batches(
            indexing_workers=_indexing_workers,
            batch_count=len(batches),
            has_graph_upserts=has_graph_upserts,
        ):
            out: list[Chunk] = []
            for b in batches:
                out.extend(await _upsert_chunk_batch(b))
            return out

        sem = asyncio.Semaphore(_indexing_workers)
        results: list[list[Chunk] | None] = [None] * len(batches)

        async def _run_batch(i: int, batch: list[Chunk]) -> None:
            async with sem:
                results[i] = await _upsert_chunk_batch(batch)

        await asyncio.gather(*(_run_batch(i, batch) for i, batch in enumerate(batches)))
        merged: list[Chunk] = []
        for r in results:
            if r:
                merged.extend(r)
        return merged

    async def _flush_pending_cross_file_chunks(*, force: bool = False) -> None:
        nonlocal pending_cross_file_chunks
        if not cross_file_chunk_batching or not pending_cross_file_chunks:
            return
        while pending_cross_file_chunks and (force or len(pending_cross_file_chunks) >= cross_file_flush_size):
            batch_len = len(pending_cross_file_chunks) if force else cross_file_flush_size
            batch = pending_cross_file_chunks[:batch_len]
            pending_cross_file_chunks = pending_cross_file_chunks[batch_len:]
            await _upsert_chunk_batches(batch)

    for idx, (rel_path, abs_path) in enumerate(file_entries, start=1):
        ext = "." + rel_path.split(".")[-1] if "." in rel_path else ""
        file_breakdown[ext] += 1

        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="indexing",
            progress=idx / max(1, total_files),
            current_file=rel_path,
            started_at=started_at,
        )
        if event_queue is not None:
            _emit_event(
                event_queue,
                {
                    "type": "progress",
                    "percent": int((_STATUS[repo_id].progress) * 100),
                    "message": rel_path,
                    "current_file": rel_path,
                },
                drop_oldest=True,
            )

        try:
            size_bytes = int(abs_path.stat().st_size)
        except Exception:
            size_bytes = None
        if size_bytes is not None and size_bytes > max_indexable_bytes:
            if event_queue is not None:
                _emit_event(
                    event_queue,
                    {
                        "type": "log",
                        "message": (
                            f"⏭️ Skipping large file ({size_bytes} bytes > {max_indexable_bytes} bytes): {rel_path}"
                        ),
                    },
                    drop_oldest=True,
                )
            continue

        # Large text files: allow a streaming ingestion mode to avoid loading the entire file into memory.
        ext_lower = abs_path.suffix.lower()
        stream_mode = str(getattr(cfg.indexing, "large_file_mode", "read_all") or "read_all").strip().lower()
        stream_block_chars = int(getattr(cfg.indexing, "large_file_stream_chunk_chars", 2_000_000) or 2_000_000)
        use_stream = (
            stream_mode == "stream"
            and ext_lower in {".txt", ".md", ".rst", ".log"}
            and size_bytes is not None
            and size_bytes >= stream_block_chars
        )

        # Chunks queued for semantic KG extraction during this file iteration.
        # Keep this as a per-iteration queue; reprocessing prior chunks on every
        # file causes quadratic work and makes indexing appear stalled.
        semantic_pending_chunks: list[Chunk] = []

        if use_stream:
            await _flush_pending_cross_file_chunks(force=True)

        if use_stream:
            base_char = 0
            base_line = 1
            ordinal = 0
            try:
                INDEX_FILES_PROCESSED_TOTAL.inc()
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="file_read_stream").time():
                    with abs_path.open("r", encoding="utf-8", errors="ignore") as f:
                        while True:
                            block = f.read(stream_block_chars)
                            if not block:
                                break
                            if "\x00" in block:
                                break
                            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="chunk").time():
                                chunks = chunker.chunk_text(
                                    rel_path,
                                    block,
                                    base_char_offset=base_char,
                                    base_line=base_line,
                                    starting_ordinal=ordinal,
                                )
                            ordinal += len(chunks)
                            base_char += len(block)
                            base_line += block.count("\n")
                            if not chunks:
                                continue
                            embedded_batches = await _upsert_chunk_batches(chunks)
                            if (
                                semantic_budget > 0
                                and semantic_processed < semantic_budget
                                and cfg.graph_indexing.semantic_kg_enabled
                                and neo4j is not None
                            ):
                                remaining = max(0, semantic_budget - semantic_processed)
                                semantic_pending_chunks.extend(embedded_batches[:remaining])
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read_stream").inc()
                _emit_event(
                    event_queue,
                    {
                        "type": "warning",
                        "message": f"Skipping file due to stream read/chunk failure: {rel_path} ({exc})",
                        "current_file": rel_path,
                    },
                    drop_oldest=True,
                )
                continue
        else:
            try:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="file_read").time():
                    content = extract_text_for_path(
                        abs_path,
                        parquet_max_rows=int(getattr(cfg.indexing, "parquet_extract_max_rows", 5000) or 5000),
                        parquet_max_chars=int(getattr(cfg.indexing, "parquet_extract_max_chars", 2_000_000) or 2_000_000),
                        parquet_max_cell_chars=int(
                            getattr(cfg.indexing, "parquet_extract_max_cell_chars", 20_000) or 20_000
                        ),
                        parquet_text_columns_only=bool(getattr(cfg.indexing, "parquet_extract_text_columns_only", True)),
                        parquet_include_column_names=bool(getattr(cfg.indexing, "parquet_extract_include_column_names", True)),
                    )
                    if content is None:
                        content = abs_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read").inc()
                _emit_event(
                    event_queue,
                    {
                        "type": "warning",
                        "message": f"Skipping file due to read/extract failure: {rel_path} ({exc})",
                        "current_file": rel_path,
                    },
                    drop_oldest=True,
                )
                continue
            if "\x00" in content:
                continue

            # Local-only "late chunking": embed the full doc segment once, then pool per chunk span.
            # This is experimental and only applies when explicitly enabled via config.
            late_mode = (
                not skip_dense
                and str(getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic").strip().lower()
                == "provider"
                and str(getattr(cfg.embedding, "contextual_chunk_embeddings", "off") or "off").strip().lower()
                == "late_chunking_local_only"
            )
            if late_mode:
                await _flush_pending_cross_file_chunks(force=True)
                from server.indexing.late_chunking import late_chunk_document

                strat = str(getattr(cfg.chunking, "chunking_strategy", "") or "").strip().lower()
                if strat not in {"fixed_tokens"}:
                    raise RuntimeError("late_chunking_local_only requires chunking.chunking_strategy='fixed_tokens'")
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="late_chunking").time():
                    chunks = late_chunk_document(rel_path, content, chunking=cfg.chunking, embedding=cfg.embedding)
                INDEX_FILES_PROCESSED_TOTAL.inc()
                if not chunks:
                    continue
                embedded_batches = await _upsert_chunk_batches(chunks)
                if (
                    semantic_budget > 0
                    and semantic_processed < semantic_budget
                    and cfg.graph_indexing.semantic_kg_enabled
                    and neo4j is not None
                ):
                    remaining = max(0, semantic_budget - semantic_processed)
                    semantic_pending_chunks.extend(embedded_batches[:remaining])
                continue

            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="chunk").time():
                chunks = chunker.chunk_file(rel_path, content)
            INDEX_FILES_PROCESSED_TOTAL.inc()
            if not chunks:
                continue
            if cross_file_chunk_batching:
                pending_cross_file_chunks.extend(chunks)
                await _flush_pending_cross_file_chunks(force=False)
                continue
            embedded_batches = await _upsert_chunk_batches(chunks)
            if (
                semantic_budget > 0
                and semantic_processed < semantic_budget
                and cfg.graph_indexing.semantic_kg_enabled
                and neo4j is not None
            ):
                remaining = max(0, semantic_budget - semantic_processed)
                semantic_pending_chunks.extend(embedded_batches[:remaining])

        # Optional semantic KG extraction (typed entities + relations linked to chunk_ids).
        if (
            neo4j is not None
            and cfg.graph_indexing.semantic_kg_enabled
            and semantic_budget > 0
            and semantic_processed < semantic_budget
        ):
            try:
                remaining_budget = max(0, semantic_budget - semantic_processed)
                chunks_for_semantic = semantic_pending_chunks[:remaining_budget]
                if chunks_for_semantic:
                    semantic_processed += len(chunks_for_semantic)
                    semantic_route = _resolve_semantic_kg_route(cfg)
                    graphrag_result = await extract_semantic_kg_with_graphrag(
                        repo_id=write_repo_id,
                        run_id=run_id,
                        cfg=cfg,
                        chunks=chunks_for_semantic,
                        route_model=str(semantic_route.model or "").strip(),
                        route_base_url=str(semantic_route.base_url or "").strip(),
                        route_api_key=str(semantic_route.api_key or "").strip() or None,
                    )

                    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_semantic_graph").time():
                        await neo4j.upsert_graphrag_graph(
                            write_repo_id,
                            graphrag_result.graph,
                            lexical_graph_config=graphrag_result.lexical_graph_config,
                        )

                    semantic_entities_total += graphrag_result.entity_count
                    semantic_relations_total += graphrag_result.relationship_count
                    semantic_empty_chunks += graphrag_result.empty_chunks

                    if event_queue is not None:
                        _emit_event(
                            event_queue,
                            {
                                "type": "log",
                                "message": (
                                "🧠 GraphRAG semantic batch: "
                                f"chunks={graphrag_result.processed_chunks} "
                                f"entities={graphrag_result.entity_count} "
                                f"relations={graphrag_result.relationship_count} "
                                f"empty_chunks={graphrag_result.empty_chunks}"
                            ),
                            },
                            drop_oldest=True,
                        )
            except Exception as exc:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="semantic_kg").inc()
                if bool(cfg.graph_indexing.semantic_kg_require_llm_success):
                    raise
                logger.warning(
                    "GraphRAG semantic extraction failed for repo_id=%s run_id=%s: %s",
                    repo_id,
                    run_id,
                    exc,
                    exc_info=True,
                )
                if event_queue is not None:
                    _emit_event(
                        event_queue,
                        {
                            "type": "warning",
                            "message": f"GraphRAG semantic extraction failed: {exc}",
                        },
                        drop_oldest=True,
                    )
            finally:
                # Important: only process each queued chunk once.
                semantic_pending_chunks.clear()

    await _flush_pending_cross_file_chunks(force=True)

    if neo4j is not None and cfg.graph_indexing.semantic_kg_enabled:
        try:
            await neo4j.detect_communities(write_repo_id)
        except Exception as exc:
            logger.warning("Graph community detection failed for repo_id=%s: %s", repo_id, exc, exc_info=True)
            _emit_event(
                event_queue,
                {"type": "warning", "message": f"Graph community detection incomplete: {exc}"},
                drop_oldest=True,
            )

    if skip_dense:
        await postgres.update_corpus_embedding_meta(
            write_repo_id,
            backend="deterministic",
            provider="",
            model="",
            dimensions=0,
            ts_config=str(cfg.indexing.postgres_ts_config or ""),
        )
    else:
        assert embedder is not None
        await postgres.update_corpus_embedding_meta(
            write_repo_id,
            backend=str(cfg.embedding.embedding_backend or "deterministic"),
            provider=str(cfg.embedding.embedding_type or ""),
            model=str(cfg.embedding.effective_model or ""),
            dimensions=int(embedder.dim),
            ts_config=str(cfg.indexing.postgres_ts_config or ""),
        )
    # Invalidate semantic cache for this corpus after indexing to prevent stale
    # retrieval/generation payloads from pre-index content.
    try:
        await postgres.semantic_cache_clear_for_corpus(repo_id)
    except Exception:
        pass

    if event_queue is not None and cfg.graph_indexing.semantic_kg_enabled:
        _emit_event(
            event_queue,
            {
                "type": "log",
                "message": (
                    "🧠 GraphRAG summary: "
                    f"processed_chunks={semantic_processed} "
                    f"entities={semantic_entities_total} "
                    f"relations={semantic_relations_total} "
                    f"empty_chunks={semantic_empty_chunks}"
                ),
            },
            drop_oldest=True,
        )

    stats = IndexStats(
        repo_id=repo_id,
        total_files=total_files,
        total_chunks=total_chunks,
        total_tokens=total_tokens,
        embedding_provider="" if skip_dense else str(cfg.embedding.embedding_type or ""),
        embedding_model="" if skip_dense else cfg.embedding.effective_model,
        embedding_dimensions=0 if skip_dense else (embedder.dim if embedder is not None else 0),
        last_indexed=datetime.now(UTC),
        file_breakdown=dict(file_breakdown),
    )
    _STATS[repo_id] = stats
    return stats


async def _background_index_job(request: IndexRequest, queue: asyncio.Queue[dict[str, Any]]) -> None:
    repo_id = request.repo_id
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"
    staging_repo_id = _build_staging_repo_id(repo_id, run_id)
    started_at = datetime.now(UTC)
    this_task = asyncio.current_task()
    _ACTIVE_RUNS[repo_id] = run_id
    _QUEUE_RUN_CONTEXT[id(queue)] = (repo_id, run_id)

    summary = IndexRunSummary(
        run_id=run_id,
        repo_id=repo_id,
        status="indexing",
        started_at=started_at,
        completed_at=None,
        progress=0.0,
        error=None,
        total_files=0,
        total_chunks=0,
        total_tokens=0,
        embedding_provider=None,
        embedding_model=None,
        embedding_dimensions=None,
    )
    with contextlib.suppress(Exception):
        _persist_run_summary(summary)

    try:
        INDEX_RUNS_TOTAL.inc()
        _emit_event(
            queue,
            {"type": "log", "message": f"🚀 Indexing started: {repo_id} (run_id={run_id})"},
            drop_oldest=True,
        )
        with INDEX_DURATION_SECONDS.time():
            stats = await _run_index(
                repo_id,
                request.repo_path,
                request.force_reindex,
                event_queue=queue,
                run_id=run_id,
                write_repo_id=staging_repo_id,
            )
        cfg = await load_scoped_config(repo_id=repo_id)
        postgres = PostgresClient(cfg.indexing.postgres_url)
        await postgres.connect()
        try:
            active_corpus = await postgres.get_corpus(repo_id)
            active_name = str((active_corpus or {}).get("name") or repo_id)
            active_description = (active_corpus or {}).get("description")
            active_meta = (active_corpus.get("meta") or {}) if active_corpus else {}
            await postgres.promote_staging_index(
                active_repo_id=repo_id,
                staging_repo_id=staging_repo_id,
                active_name=active_name,
                active_root_path=request.repo_path,
                active_description=str(active_description) if active_description is not None else None,
                active_meta=active_meta,
            )
        finally:
            with contextlib.suppress(Exception):
                await postgres.disconnect()

        if cfg.graph_indexing.enabled:
            db_name = cfg.graph_storage.resolve_database(repo_id)
            neo4j = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.resolve_password(),
                database=db_name,
            )
            await neo4j.connect()
            try:
                await neo4j.promote_repo_graph(active_repo_id=repo_id, staging_repo_id=staging_repo_id)
            finally:
                await neo4j.disconnect()
        await _prepare_dense_retrieval_after_indexing(
            repo_id=repo_id,
            repo_path=request.repo_path,
            cfg=cfg,
            stats=stats,
            queue=queue,
        )
        # Update process-level “size” gauges (best-effort; no per-corpus labels).
        try:
            CHUNKS_INDEXED_CURRENT.set(int(getattr(stats, "total_chunks", 0) or 0))
        except Exception:
            pass
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
            if not cfg.graph_indexing.enabled:
                GRAPH_ENTITIES_CURRENT.set(0)
                GRAPH_RELATIONSHIPS_CURRENT.set(0)
            else:
                db_name = cfg.graph_storage.resolve_database(repo_id)
                neo4j = Neo4jClient(
                    cfg.graph_storage.neo4j_uri,
                    cfg.graph_storage.neo4j_user,
                    cfg.graph_storage.resolve_password(),
                    database=db_name,
                )
                await neo4j.connect()
                try:
                    gstats = await neo4j.get_graph_stats(repo_id)
                    GRAPH_ENTITIES_CURRENT.set(int(getattr(gstats, "total_entities", 0) or 0))
                    GRAPH_RELATIONSHIPS_CURRENT.set(int(getattr(gstats, "total_relationships", 0) or 0))
                finally:
                    await neo4j.disconnect()
        except Exception:
            # Never fail indexing due to gauge update issues.
            pass
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="complete",
            progress=1.0,
            current_file=None,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        summary = IndexRunSummary(
            run_id=run_id,
            repo_id=repo_id,
            status="complete",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            progress=1.0,
            error=None,
            total_files=int(getattr(stats, "total_files", 0) or 0),
            total_chunks=int(getattr(stats, "total_chunks", 0) or 0),
            total_tokens=int(getattr(stats, "total_tokens", 0) or 0),
            embedding_provider=str(getattr(stats, "embedding_provider", "") or ""),
            embedding_model=str(getattr(stats, "embedding_model", "") or ""),
            embedding_dimensions=int(getattr(stats, "embedding_dimensions", 0) or 0),
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(summary)
        _emit_event(queue, {"type": "complete", "message": "✓ Indexing complete"}, guarantee=True)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            cfg = await load_scoped_config(repo_id=repo_id)
            pg = PostgresClient(cfg.indexing.postgres_url)
            await pg.connect()
            try:
                await pg.delete_corpus_with_data(staging_repo_id)
            finally:
                await pg.disconnect()
            if cfg.graph_indexing.enabled:
                db_name = cfg.graph_storage.resolve_database(repo_id)
                neo4j = Neo4jClient(
                    cfg.graph_storage.neo4j_uri,
                    cfg.graph_storage.neo4j_user,
                    cfg.graph_storage.resolve_password(),
                    database=db_name,
                )
                await neo4j.connect()
                try:
                    await neo4j.delete_graph(staging_repo_id)
                finally:
                    await neo4j.disconnect()
        # Cancelled tasks cannot rely on direct awaits for cleanup, so shield
        # invalidation to let it continue even while this task is cancelled.
        try:
            await asyncio.shield(_clear_semantic_cache_for_repo(repo_id))
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        prev = _STATUS.get(repo_id)
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="cancelled",
            progress=float(prev.progress) if prev else 0.0,
            current_file=prev.current_file if prev else None,
            error=None,
            started_at=prev.started_at if prev else started_at,
            completed_at=datetime.now(UTC),
        )
        summary = IndexRunSummary(
            run_id=run_id,
            repo_id=repo_id,
            status="cancelled",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            progress=float(prev.progress) if prev else 0.0,
            error=None,
            total_files=0,
            total_chunks=0,
            total_tokens=0,
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(summary)
        _emit_event(queue, {"type": "cancelled", "message": "⚠ Indexing cancelled"}, guarantee=True)
        raise
    except Exception as e:
        with contextlib.suppress(Exception):
            cfg = await load_scoped_config(repo_id=repo_id)
            pg = PostgresClient(cfg.indexing.postgres_url)
            await pg.connect()
            try:
                await pg.delete_corpus_with_data(staging_repo_id)
            finally:
                await pg.disconnect()
            if cfg.graph_indexing.enabled:
                db_name = cfg.graph_storage.resolve_database(repo_id)
                neo4j = Neo4jClient(
                    cfg.graph_storage.neo4j_uri,
                    cfg.graph_storage.neo4j_user,
                    cfg.graph_storage.resolve_password(),
                    database=db_name,
                )
                await neo4j.connect()
                try:
                    await neo4j.delete_graph(staging_repo_id)
                finally:
                    await neo4j.disconnect()
        # If indexing failed after deleting/updating chunks, stale cache entries can
        # point to content that no longer exists. Best-effort clear on errors.
        with contextlib.suppress(Exception):
            await _clear_semantic_cache_for_repo(repo_id)
        INDEX_ERRORS_TOTAL.inc()
        prev = _STATUS.get(repo_id)
        _STATUS[repo_id] = IndexStatus(
            repo_id=repo_id,
            status="error",
            progress=float(prev.progress) if prev else 0.0,
            current_file=prev.current_file if prev else None,
            error=str(e),
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        summary = IndexRunSummary(
            run_id=run_id,
            repo_id=repo_id,
            status="error",
            started_at=started_at,
            completed_at=datetime.now(UTC),
            progress=float(prev.progress) if prev else 0.0,
            error=str(e),
            total_files=0,
            total_chunks=0,
            total_tokens=0,
            embedding_provider=None,
            embedding_model=None,
            embedding_dimensions=None,
        )
        with contextlib.suppress(Exception):
            _persist_run_summary(summary)
        _emit_event(queue, {"type": "error", "message": str(e)}, guarantee=True)
    finally:
        # Avoid clearing a newer task/queue for the same repo if a new run already started.
        if _TASKS.get(repo_id) is this_task:
            _TASKS.pop(repo_id, None)
        _clear_runtime_state_for_repo(repo_id, queue=queue)


@router.post("/index/estimate", response_model=IndexEstimate)
async def estimate_index(request: IndexRequest) -> IndexEstimate:
    """Estimate indexing cost/time for a corpus before running the indexer."""
    repo_id = str(request.repo_id or "").strip()
    repo_path = str(request.repo_path or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")

    if not repo_path:
        # Best-effort: resolve from corpus registry.
        cfg_global = await load_scoped_config(repo_id=None)
        pg = PostgresClient(cfg_global.indexing.postgres_url)
        await pg.connect()
        try:
            corpus = await pg.get_corpus(repo_id)
            if corpus is not None:
                repo_path = str(corpus.get("path") or "").strip()
        finally:
            await pg.disconnect()

    if not repo_path:
        raise HTTPException(status_code=422, detail="repo_path is required (or create corpus first)")

    cfg = await load_scoped_config(repo_id=repo_id)

    # Build ignore patterns from config (same as indexer).
    ignore_patterns: list[str] = []
    exts = (cfg.indexing.index_excluded_exts or "").split(",")
    for ext in exts:
        ext = ext.strip()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = "." + ext
        ignore_patterns.append(f"*{ext}")

    # Enforce a strict max file size before reading/chunking (same as indexer).
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )

    # Corpus-level exclude paths (stored in Postgres corpora.meta.exclude_paths).
    extra_gitignore_patterns: list[str] = []
    try:
        pg2 = PostgresClient(cfg.indexing.postgres_url)
        await pg2.connect()
        try:
            corpus = await pg2.get_corpus(repo_id)
            meta = (corpus.get("meta") or {}) if corpus else {}
            raw = meta.get("exclude_paths") if isinstance(meta, dict) else None
            if isinstance(raw, list):
                extra_gitignore_patterns = [str(x).strip() for x in raw if str(x).strip()]
        finally:
            await pg2.disconnect()
    except Exception:
        extra_gitignore_patterns = []

    loader = FileLoader(ignore_patterns=ignore_patterns, extra_gitignore_patterns=extra_gitignore_patterns)

    total_files = 0
    total_bytes = 0
    skipped_large_files = 0

    root = Path(repo_path).expanduser().resolve()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"repo_path not found: {repo_path}")

    for _rel, p in loader.iter_repo_files(str(root)):
        try:
            size_bytes = int(p.stat().st_size)
        except Exception:
            size_bytes = 0
        if size_bytes > max_indexable_bytes:
            skipped_large_files += 1
            continue
        total_files += 1
        total_bytes += max(0, size_bytes)

    est_tokens = _estimate_tokens_from_bytes(total_bytes)
    est_chunks = _estimate_chunks_from_tokens(
        tokens=est_tokens,
        target_tokens=int(getattr(cfg.chunking, "target_tokens", 512) or 512),
        overlap_tokens=int(getattr(cfg.chunking, "overlap_tokens", 64) or 64),
    )

    skip_dense = bool(getattr(cfg.indexing, "skip_dense", False))
    embedding_backend = str(getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic").strip()
    embedding_provider = str(getattr(cfg.embedding, "embedding_type", "") or "").strip()
    embedding_model = str(getattr(cfg.embedding, "effective_model", "") or "").strip()

    semantic_kg_enabled = bool(cfg.graph_indexing.semantic_kg_enabled)
    semantic_kg_chunks = min(est_chunks, max(0, int(cfg.graph_indexing.semantic_kg_max_chunks or 0))) if semantic_kg_enabled else 0
    semantic_model, semantic_provider_hint = _resolve_semantic_kg_model_and_provider(cfg)

    # Pricing (models.json): deterministic backend and skip_dense imply $0 external embedding cost.
    embedding_cost: float | None
    if skip_dense or embedding_backend != "provider":
        embedding_cost = 0.0
    else:
        embedding_cost = _estimate_embedding_cost_usd(
            provider=embedding_provider,
            model=embedding_model,
            total_tokens=est_tokens,
        )

    semantic_kg_cost: float | None = None
    if semantic_kg_enabled:
        semantic_kg_cost = _estimate_semantic_kg_cost_usd(
            provider_hint=semantic_provider_hint,
            model=semantic_model,
            chunks_in_scope=semantic_kg_chunks,
            enrich_max_chars=int(cfg.enrichment.enrich_max_chars or 1000),
        )

    total_cost: float | None
    if semantic_kg_enabled:
        total_cost = None if embedding_cost is None or semantic_kg_cost is None else float(embedding_cost) + float(semantic_kg_cost)
    else:
        total_cost = embedding_cost

    # Time estimate (rough): embedding throughput + optional semantic KG extraction phase + overhead.
    est_low: float | None = None
    est_high: float | None = None
    estimated_seconds_semantic_kg: float | None = None
    assumptions: list[str] = [
        f"tokens≈bytes/{_EST_BYTES_PER_TOKEN:g}",
        "time range is a heuristic (very rough)",
    ]
    if skipped_large_files > 0:
        assumptions.append(f"skips files > {max_indexable_bytes} bytes")

    if skip_dense:
        tps = _EST_TOKENS_PER_SECOND_DETERMINISTIC
        assumptions.append("skip_dense=1 → dense embedding phase skipped")
    elif embedding_backend != "provider":
        tps = _EST_TOKENS_PER_SECOND_DETERMINISTIC
        assumptions.append("embedding_backend=deterministic → $0 external cost")
    else:
        if _looks_cloud_provider(embedding_provider):
            tps = _EST_TOKENS_PER_SECOND_CLOUD
            assumptions.append(f"embedding tokens/sec≈{tps:,} (cloud heuristic)")
        else:
            tps = _estimate_local_tokens_per_second(cfg=cfg, provider=embedding_provider)
            override_tps = getattr(cfg.indexing, "estimated_tokens_per_second_local", None)
            if override_tps is not None and int(override_tps or 0) > 0:
                assumptions.append(f"embedding tokens/sec≈{tps:,} (indexing.estimated_tokens_per_second_local override)")
            else:
                assumptions.append(
                    f"embedding tokens/sec≈{tps:,} (local hardware={_detect_local_hardware_class()} provider={embedding_provider or 'local'})"
                )

    if est_tokens > 0 and tps > 0:
        base_embedding_seconds = float(est_tokens) / float(tps)
        base_total_seconds = base_embedding_seconds
        if semantic_kg_enabled and semantic_kg_chunks > 0:
            semantic_provider_for_time = semantic_provider_hint
            resolved_semantic_spec = _find_model_spec(
                _load_models_json(),
                provider=semantic_provider_hint,
                model=semantic_model,
            )
            if resolved_semantic_spec is not None:
                semantic_provider_for_time = str(resolved_semantic_spec.get("provider") or semantic_provider_for_time)
            estimated_seconds_semantic_kg = _estimate_semantic_kg_seconds(
                provider=semantic_provider_for_time,
                chunks_in_scope=semantic_kg_chunks,
                indexing_workers=int(getattr(cfg.indexing, "indexing_workers", 1) or 1),
            )
            base_total_seconds += float(estimated_seconds_semantic_kg)
            assumptions.append(
                f"semantic_graphrag≈{semantic_kg_chunks:,} chunks using {semantic_provider_for_time or 'unknown'}"
            )
        est_low = max(0.0, (base_total_seconds * _EST_RANGE_LOW_MULT) + float(_EST_OVERHEAD_SECONDS))
        est_high = max(est_low, (base_total_seconds * _EST_RANGE_HIGH_MULT) + float(_EST_OVERHEAD_SECONDS) * 2.0)

    return IndexEstimate(
        repo_id=repo_id,
        repo_path=str(root),
        total_files=int(total_files),
        total_size_bytes=int(total_bytes),
        skipped_large_files=int(skipped_large_files),
        estimated_total_tokens=int(est_tokens),
        estimated_total_chunks=int(est_chunks),
        embedding_backend="provider" if embedding_backend == "provider" else "deterministic",
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        skip_dense=bool(skip_dense),
        embedding_cost_usd=embedding_cost,
        semantic_kg_cost_usd=semantic_kg_cost,
        total_cost_usd=total_cost,
        estimated_seconds_low=est_low,
        estimated_seconds_high=est_high,
        estimated_seconds_semantic_kg=estimated_seconds_semantic_kg,
        assumptions=assumptions,
    )


@router.get("/index/{corpus_id}/pilot/status", response_model=RetrievalPilotStatusResponse)
async def get_retrieval_pilot_status(
    corpus_id: str,
    repo_path: str | None = Query(default=None, description="Optional corpus path override for the pilot."),
) -> RetrievalPilotStatusResponse:
    resolved_repo_path = await _resolve_repo_path_from_request(corpus_id, repo_path)
    return await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=resolved_repo_path)


@router.post("/index/{corpus_id}/pilot/export", response_model=RetrievalPilotExportResponse)
async def run_retrieval_pilot_export(
    corpus_id: str,
    request: RetrievalPilotExportRequest,
) -> RetrievalPilotExportResponse:
    if str(request.repo_id or "").strip() != str(corpus_id or "").strip():
        raise HTTPException(status_code=422, detail="corpus_id path and payload must match")

    resolved_repo_path = await _resolve_repo_path_from_request(corpus_id, request.repo_path)
    if not resolved_repo_path:
        raise HTTPException(status_code=422, detail="repo_path is required (or create corpus first)")

    try:
        return await export_retrieval_pilot(
            corpus_id=corpus_id,
            repo_path=resolved_repo_path,
            force_rebuild=bool(request.force_rebuild),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/index/{corpus_id}/pilot/search-preview", response_model=RetrievalPilotSearchPreviewResponse)
async def search_retrieval_pilot(
    corpus_id: str,
    request: RetrievalPilotSearchPreviewRequest,
    repo_path: str | None = Query(default=None, description="Optional corpus path override for status context."),
) -> RetrievalPilotSearchPreviewResponse:
    if str(request.repo_id or "").strip() != str(corpus_id or "").strip():
        raise HTTPException(status_code=422, detail="corpus_id path and payload must match")

    resolved_repo_path = await _resolve_repo_path_from_request(corpus_id, repo_path)
    try:
        return await search_retrieval_pilot_preview(
            corpus_id=corpus_id,
            repo_path=resolved_repo_path,
            query=str(request.query or ""),
            top_k=int(request.top_k),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/index/{corpus_id}/pilot/ingest", response_model=RetrievalPilotIngestResponse)
async def ingest_retrieval_pilot(
    corpus_id: str,
    request: RetrievalPilotIngestRequest,
    repo_path: str | None = Query(default=None, description="Optional corpus path override for status context."),
) -> RetrievalPilotIngestResponse:
    if str(request.repo_id or "").strip() != str(corpus_id or "").strip():
        raise HTTPException(status_code=422, detail="corpus_id path and payload must match")

    resolved_repo_path = await _resolve_repo_path_from_request(corpus_id, repo_path)
    try:
        return await ingest_retrieval_pilot_execution(
            corpus_id=corpus_id,
            repo_path=resolved_repo_path,
            force_rebuild=bool(request.force_rebuild),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RetrievalContractMismatchError as exc:
        raise retrieval_contract_mismatch_http_exception(exc) from exc
    except DependencyUnavailableError as exc:
        raise dependency_unavailable_http_exception(exc.dependency, boundary=exc.operation, exc=exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/index/{corpus_id}/pilot/search", response_model=RetrievalPilotSearchResponse)
async def search_retrieval_pilot_execution_route(
    corpus_id: str,
    request: RetrievalPilotSearchRequest,
    repo_path: str | None = Query(default=None, description="Optional corpus path override for status context."),
) -> RetrievalPilotSearchResponse:
    if str(request.repo_id or "").strip() != str(corpus_id or "").strip():
        raise HTTPException(status_code=422, detail="corpus_id path and payload must match")

    resolved_repo_path = await _resolve_repo_path_from_request(corpus_id, repo_path)
    try:
        return await search_retrieval_pilot_execution(
            corpus_id=corpus_id,
            repo_path=resolved_repo_path,
            query=str(request.query or ""),
            top_k=int(request.top_k),
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RetrievalContractMismatchError as exc:
        raise retrieval_contract_mismatch_http_exception(exc) from exc
    except DependencyUnavailableError as exc:
        raise dependency_unavailable_http_exception(exc.dependency, boundary=exc.operation, exc=exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/index", response_model=IndexStatus)
async def start_index(request: IndexRequest) -> IndexStatus:
    global _LAST_STARTED_REPO

    # If already running, return current status.
    if request.repo_id in _TASKS and request.repo_id in _STATUS:
        return _STATUS[request.repo_id]

    started_at = datetime.now(UTC)
    _STATUS[request.repo_id] = IndexStatus(
        repo_id=request.repo_id,
        status="indexing",
        progress=0.0,
        current_file=None,
        started_at=started_at,
    )

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
    _EVENT_QUEUES[request.repo_id] = queue
    _LAST_STARTED_REPO = request.repo_id

    task = asyncio.create_task(_background_index_job(request, queue))
    _TASKS[request.repo_id] = task
    return _STATUS[request.repo_id]


@router.post("/index/start", response_model=IndexStatus)
async def start_index_compat(payload: dict[str, Any] | None = None) -> IndexStatus:
    """Compatibility endpoint for legacy dashboard UI.

    Expected payload: {"repo_id": "...", "repo_path": "...", "force_reindex": bool}
    """
    payload = payload or {}
    repo_id = str(payload.get("repo_id") or payload.get("repo") or "").strip()
    repo_path = str(payload.get("repo_path") or payload.get("path") or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id is required")
    if not repo_path:
        # Try to resolve from corpus registry
        cfg = await load_scoped_config(repo_id=None)
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
        if corpus is not None:
            repo_path = str(corpus.get("path") or "")
    if not repo_path:
        raise HTTPException(status_code=422, detail="repo_path is required (or create corpus first)")
    force_reindex = bool(payload.get("force_reindex") or payload.get("force") or False)
    return await start_index(IndexRequest(repo_id=repo_id, repo_path=repo_path, force_reindex=force_reindex))


@router.post("/index/{corpus_id}/stop", response_model=IndexStatus)
async def stop_index_for_corpus(corpus_id: str) -> IndexStatus:
    """Cancel an active indexing run for a specific corpus."""
    repo_id = str(corpus_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    return await _cancel_index_run(repo_id)


@router.post("/index/stop", response_model=IndexStatus)
async def stop_index_compat(
    payload: dict[str, Any] | None = None,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> IndexStatus:
    """Legacy-compatible stop endpoint for dashboard callers."""
    payload = payload or {}
    repo_id = str(
        payload.get("corpus_id")
        or payload.get("repo_id")
        or payload.get("repo")
        or (scope.resolved_repo_id or "")
        or (_LAST_STARTED_REPO or "")
    ).strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="repo_id (or corpus_id) is required")
    return await _cancel_index_run(repo_id)


@router.get("/index/status", response_model=DashboardIndexStatusResponse)
async def get_dashboard_index_status(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> DashboardIndexStatusResponse:
    """Dashboard index summary (legacy-compatible endpoint).

    This endpoint exists for the Dashboard System tab's full index summary panel.
    It is distinct from the corpus-scoped `/api/index/{corpus_id}/status` endpoint.
    """
    repo_id = await _resolve_dashboard_repo_id(scope)

    # In-memory indexing state (best-effort; only present for this process)
    s = _STATUS.get(repo_id)
    running = bool(repo_id in _TASKS) or (s is not None and s.status == "indexing")
    progress = float(s.progress) if s is not None else None
    current_file = s.current_file if s is not None else None

    # Corpus metadata (name/branch/keywords)
    cfg_global = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg_global.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
    finally:
        await pg.disconnect()

    current_repo = str((corpus or {}).get("name") or repo_id)
    meta = (corpus or {}).get("meta") or {}
    current_branch = str(meta.get("branch") or "") or None
    keywords = meta.get("keywords") if isinstance(meta, dict) else None
    keywords_count = len(keywords) if isinstance(keywords, list) else 0

    # Config + costs + storage breakdown (best-effort)
    cfg = await load_scoped_config(repo_id=repo_id)
    embedding_model = cfg.embedding.effective_model
    embedding_provider = cfg.embedding.embedding_type
    embedding_dim = int(cfg.embedding.embedding_dim)
    skip_dense = bool(getattr(cfg.indexing, "skip_dense", False))
    embedding_backend = str(getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic").strip()
    total_tokens = 0
    total_chunks = 0
    try:
        pg2 = PostgresClient(cfg.indexing.postgres_url)
        await pg2.connect()
        try:
            stats = await pg2.get_index_stats(repo_id)
            total_chunks = int(stats.total_chunks or 0)
            total_tokens = int(stats.total_tokens or 0)
        finally:
            await pg2.disconnect()
    except Exception:
        total_chunks = 0
        total_tokens = 0

    embedding_cost: float | None
    if skip_dense or embedding_backend != "provider":
        embedding_cost = 0.0
    else:
        embedding_cost = _estimate_embedding_cost_usd(
            provider=embedding_provider,
            model=embedding_model,
            total_tokens=total_tokens,
        )

    semantic_kg_cost: float | None = None
    total_cost: float | None = embedding_cost
    semantic_kg_enabled = bool(cfg.graph_indexing.semantic_kg_enabled)
    if semantic_kg_enabled:
        semantic_model, semantic_provider_hint = _resolve_semantic_kg_model_and_provider(cfg)
        semantic_chunks = min(total_chunks, max(0, int(cfg.graph_indexing.semantic_kg_max_chunks or 0)))
        semantic_kg_cost = _estimate_semantic_kg_cost_usd(
            provider_hint=semantic_provider_hint,
            model=semantic_model,
            chunks_in_scope=semantic_chunks,
            enrich_max_chars=int(cfg.enrichment.enrich_max_chars or 1000),
        )
        total_cost = None if embedding_cost is None or semantic_kg_cost is None else float(embedding_cost) + float(semantic_kg_cost)

    storage_breakdown = await _compute_dashboard_storage_breakdown(repo_id=repo_id)

    metadata = DashboardIndexStatusMetadata(
        repo_id=repo_id,
        current_repo=current_repo,
        current_branch=current_branch,
        timestamp=datetime.now(UTC),
        embedding_config=DashboardEmbeddingConfigSummary(
            provider=embedding_provider,
            model=embedding_model,
            dimensions=embedding_dim,
            precision="float32",
        ),
        costs=DashboardIndexCosts(
            total_tokens=total_tokens,
            embedding_cost=embedding_cost,
            semantic_kg_cost=semantic_kg_cost,
            total_cost=total_cost,
        ),
        storage_breakdown=storage_breakdown,
        keywords_count=keywords_count,
        total_storage=int(storage_breakdown.total_storage_bytes),
    )

    lines: list[str] = []
    if s is not None and s.status == "error":
        lines = [f"Index error: {s.error or 'unknown error'}"]
    elif running:
        pct = int((progress or 0.0) * 100)
        lines = [f"Indexing… {pct}%"]
        if current_file:
            lines.append(current_file)
    elif s is not None and s.status == "complete":
        lines = ["✓ Indexing complete"]
    else:
        lines = ["Ready to index…"]

    return DashboardIndexStatusResponse(
        lines=lines,
        metadata=metadata,
        running=running,
        progress=progress,
        current_file=current_file,
    )


@router.get("/index/stats", response_model=DashboardIndexStatsResponse)
async def get_dashboard_index_stats(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> DashboardIndexStatsResponse:
    """Dashboard storage metrics (legacy-compatible endpoint)."""
    repo_id = await _resolve_dashboard_repo_id(scope)

    cfg_global = await load_scoped_config(repo_id=None)
    pg = PostgresClient(cfg_global.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
    finally:
        await pg.disconnect()

    meta = (corpus or {}).get("meta") or {}
    keywords = meta.get("keywords") if isinstance(meta, dict) else None
    keywords_count = len(keywords) if isinstance(keywords, list) else 0

    storage_breakdown = await _compute_dashboard_storage_breakdown(repo_id=repo_id)

    return DashboardIndexStatsResponse(
        repo_id=repo_id,
        storage_breakdown=storage_breakdown,
        keywords_count=keywords_count,
        total_storage=int(storage_breakdown.total_storage_bytes),
    )


@router.get("/index/{corpus_id}/runs/latest", response_model=IndexRunSummary)
async def get_latest_index_run(corpus_id: str) -> IndexRunSummary:
    repo_id = str(corpus_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    run = _load_latest_run_summary(repo_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No persisted index runs found for repo_id={repo_id}")
    return _coerce_stale_indexing_run_to_error(repo_id, run)


@router.get("/index/{corpus_id}/runs/{run_id}/events", response_model=list[IndexRunEvent])
async def get_index_run_events(corpus_id: str, run_id: str, limit: int = Query(default=200, ge=1, le=5000)) -> list[IndexRunEvent]:
    repo_id = str(corpus_id or "").strip()
    rid = str(run_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=422, detail="corpus_id is required")
    if not rid:
        raise HTTPException(status_code=422, detail="run_id is required")
    events = _load_run_events(repo_id, rid, limit=limit)
    return events


@router.get("/index/{corpus_id}/status", response_model=IndexStatus)
async def get_index_status(corpus_id: str) -> IndexStatus:
    repo_id = corpus_id
    if repo_id in _STATUS:
        return _STATUS[repo_id]
    persisted_run = _load_latest_run_summary(repo_id)
    if persisted_run is not None:
        persisted_run = _coerce_stale_indexing_run_to_error(repo_id, persisted_run)
        return IndexStatus(
            repo_id=repo_id,
            status=persisted_run.status,
            progress=float(persisted_run.progress or 0.0),
            current_file=None,
            error=persisted_run.error,
            started_at=persisted_run.started_at,
            completed_at=persisted_run.completed_at,
        )
    # In-memory status is lost on server reload; infer "complete" from persisted
    # index stats so clients don't see a misleading "idle" state.
    if repo_id in _STATS and int(getattr(_STATS[repo_id], "total_chunks", 0) or 0) > 0:
        s = _STATS[repo_id]
        return IndexStatus(
            repo_id=repo_id,
            status="complete",
            progress=1.0,
            current_file=None,
            error=None,
            started_at=None,
            completed_at=getattr(s, "last_indexed", None),
        )
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
        postgres = PostgresClient(cfg.indexing.postgres_url)
        await postgres.connect()
        try:
            persisted = await postgres.get_index_stats(repo_id)
        finally:
            await postgres.disconnect()
        if int(getattr(persisted, "total_chunks", 0) or 0) > 0:
            return IndexStatus(
                repo_id=repo_id,
                status="complete",
                progress=1.0,
                current_file=None,
                error=None,
                started_at=None,
                completed_at=getattr(persisted, "last_indexed", None),
            )
    except Exception:
        pass
    return _idle_status(repo_id)


@router.get("/index/{corpus_id}/stats", response_model=IndexStats)
async def get_index_stats(corpus_id: str) -> IndexStats:
    repo_id = corpus_id
    if repo_id in _STATS:
        return _STATS[repo_id]
    # Read from Postgres (source of truth)
    cfg = await load_scoped_config(repo_id=None)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    stats = await postgres.get_index_stats(repo_id)
    if stats.total_chunks == 0:
        raise HTTPException(status_code=404, detail=f"No index found for repo_id={repo_id}")
    return stats


@router.delete("/index/{corpus_id}")
async def delete_index(corpus_id: str) -> dict[str, Any]:
    repo_id = corpus_id
    if repo_id in _TASKS:
        await _cancel_index_run(repo_id)
    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    deleted_vec = await postgres.delete_embeddings(repo_id)
    deleted_fts = await postgres.delete_fts(repo_id)
    deleted_rows = await postgres.delete_chunks(repo_id)
    try:
        await postgres.semantic_cache_clear_for_corpus(repo_id)
    except Exception:
        pass

    try:
        db_name = cfg.graph_storage.resolve_database(repo_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=db_name,
        )
        await neo4j.connect()
        await neo4j.delete_graph(repo_id)
        await neo4j.disconnect()
    except Exception:
        # Graph layer optional
        pass
    _STATUS.pop(repo_id, None)
    _STATS.pop(repo_id, None)
    _TASKS.pop(repo_id, None)
    _EVENT_QUEUES.pop(repo_id, None)
    # Best-effort gauges (process-level; no per-corpus labels).
    # Reset to zero to avoid stale dashboards in single-corpus dev flows.
    try:
        CHUNKS_INDEXED_CURRENT.set(0)
        GRAPH_ENTITIES_CURRENT.set(0)
        GRAPH_RELATIONSHIPS_CURRENT.set(0)
    except Exception:
        pass
    return {
        "ok": True,
        "deleted_chunks": deleted_rows,
        "deleted_embeddings": deleted_vec,
        "deleted_fts": deleted_fts,
    }


@router.get("/index/vocab-preview", response_model=VocabPreviewResponse)
async def get_vocab_preview(
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
    top_n: int = Query(default=100, ge=10, le=500, description="Number of top terms to return"),
) -> VocabPreviewResponse:
    """Return a vocabulary preview from Postgres FTS (chunks.tsv).

    This powers the Indexing tab “Vocabulary Preview” tooling.
    """
    repo_id = (scope.resolved_repo_id or "").strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="Missing corpus_id (or legacy repo/repo_id) query parameter")

    cfg = await load_scoped_config(repo_id=repo_id)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    terms, total_terms = await postgres.vocab_preview(repo_id, top_n=top_n)

    # Config-derived Postgres text search configuration label (LAW).
    tokenizer = str(cfg.indexing.bm25_tokenizer or "").strip() or "stemmer"
    ts_config = cfg.indexing.postgres_ts_config

    return VocabPreviewResponse(
        repo_id=repo_id,
        top_n=int(top_n),
        tokenizer=tokenizer,
        stemmer_lang=str(cfg.indexing.bm25_stemmer_lang or "") or None,
        ts_config=ts_config,
        total_terms=int(total_terms),
        terms=terms,
    )


@router.get("/stream/operations/index")
async def stream_index_operation(scope: CorpusScope = _CORPUS_SCOPE_DEP) -> StreamingResponse:
    """SSE stream for indexing logs/progress (TerminalService.streamOperation compatibility)."""
    repo_id = (scope.resolved_repo_id or _LAST_STARTED_REPO or "").strip()
    if not repo_id:
        raise HTTPException(status_code=400, detail="Missing repo query parameter")
    queue = _EVENT_QUEUES.get(repo_id)
    task = _TASKS.get(repo_id)
    if queue is None or task is None or task.done():
        raise HTTPException(status_code=404, detail=f"No active stream for repo_id={repo_id}")

    async def _gen() -> AsyncGenerator[str, None]:
        # Immediately emit a status snapshot
        if repo_id in _STATUS:
            s = _STATUS[repo_id]
            yield f"data: {json.dumps({'type': 'progress', 'percent': int(s.progress * 100), 'message': s.current_file or ''})}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                active = _TASKS.get(repo_id)
                if active is None or active.done():
                    break
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in {"complete", "error", "cancelled"}:
                break

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
