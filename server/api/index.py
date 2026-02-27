from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from server.chat.generation import generate_chat_text
from server.chat.provider_router import select_provider_route
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder
from server.indexing.graph_builder import GraphBuilder
from server.indexing.loader import FileLoader
from server.indexing.text_extractors import extract_text_for_path
from server.models.graph import Entity, Relationship
from server.models.index import Chunk, IndexRequest, IndexStats, IndexStatus
from server.models.tribrid_config_model import (
    CorpusScope,
    DashboardEmbeddingConfigSummary,
    DashboardIndexCosts,
    DashboardIndexStatsResponse,
    DashboardIndexStatusMetadata,
    DashboardIndexStatusResponse,
    DashboardIndexStorageBreakdown,
    IndexEstimate,
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

_SEM_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")
_SEM_STOPWORDS: set[str] = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "return",
    "true",
    "false",
    "none",
    "null",
    "import",
    "export",
    "class",
    "function",
    "const",
    "let",
    "var",
    "async",
    "await",
}

_MODELS_JSON_PATH = Path(__file__).parent.parent.parent / "data" / "models.json"

# Index estimate heuristics (intentionally rough).
_EST_BYTES_PER_TOKEN = 4.0  # common rule-of-thumb for English-ish text
_EST_TOKENS_PER_SECOND_CLOUD = 50_000
_EST_TOKENS_PER_SECOND_LOCAL = 8_000
_EST_TOKENS_PER_SECOND_DETERMINISTIC = 120_000
_EST_OVERHEAD_SECONDS = 12.0
_EST_RANGE_LOW_MULT = 0.6
_EST_RANGE_HIGH_MULT = 1.9


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
            cfg.graph_storage.neo4j_password,
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


def _extract_semantic_concepts(text: str, *, min_len: int, max_terms: int) -> list[str]:
    """Deterministic concept extraction (fallback for tests/offline)."""
    if max_terms <= 0:
        return []
    toks = [t.lower() for t in _SEM_TOKEN_RE.findall(text or "")]
    freq: dict[str, int] = defaultdict(int)
    for t in toks:
        if len(t) < min_len:
            continue
        if t in _SEM_STOPWORDS:
            continue
        freq[t] += 1
    # Stable ordering: by frequency desc, then token asc.
    items = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _v in items[:max_terms]]


async def _extract_semantic_kg_llm(
    text: str,
    *,
    cfg: TriBridConfig,
    prompt: str,
    model: str,
    timeout_s: float,
    reasoning_effort: str,
    typed_entities_enabled: bool,
    allowed_entity_types: set[str],
    require_success: bool = False,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """LLM-assisted semantic KG extraction (best-effort).

    Returns:
    - entities: list[dict] with keys: name, entity_type
    - relations: list[dict] with keys: source, target, relation_type
    """
    # Route via Chat 2.0 providers so semantic KG extraction can use ragweld/local/openrouter
    # as well as cloud_direct.
    safe_text = (text or "").strip()
    if "json" not in safe_text.lower():
        safe_text = f"{safe_text}\n\nReturn JSON.".strip()

    def _try_parse_json_object(raw: str) -> dict[str, Any] | None:
        s = (raw or "").strip()
        if not s:
            return None
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

        # Common case: model wraps JSON in a fenced block.
        m = re.search(r"```(?:json)?\\s*(\\{.*?\\})\\s*```", s, flags=re.DOTALL | re.IGNORECASE)
        if m:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

        # Last resort: take the outermost braces.
        i0 = s.find("{")
        i1 = s.rfind("}")
        if i0 != -1 and i1 != -1 and i1 > i0:
            try:
                obj = json.loads(s[i0 : i1 + 1])
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
        return None

    def _normalize_entity_type(value: str) -> str | None:
        v = (value or "").strip().lower()
        aliases = {"organization": "org", "organisation": "org"}
        v = aliases.get(v, v)
        if not typed_entities_enabled:
            v = "concept"
        if v not in {"person", "org", "location", "event", "concept"}:
            return None
        if allowed_entity_types and v not in allowed_entity_types:
            return None
        return v

    def _clean_entity_name(value: str) -> str:
        out = re.sub(r"\s+", " ", str(value or "").replace("_", " ").strip())
        return out

    llm_attempts = 3
    last_err: Exception | None = None
    for attempt in range(llm_attempts):
        try:
            route = select_provider_route(config=cfg, model_override=str(model or "").strip())
            data: dict[str, Any] | None = None

            is_openai_responses = (
                route.kind == "cloud_direct"
                and str(getattr(route, "provider_name", "") or "").strip().lower() == "openai"
                and str(getattr(route, "openai_protocol", "") or "").strip().lower() == "responses"
            )

            if is_openai_responses:
                try:
                    import openai as _openai
                except Exception:
                    _openai = None  # type: ignore[assignment]

                openai_client_cls = getattr(_openai, "AsyncOpenAI", None) if _openai is not None else None
                if openai_client_cls is not None and getattr(route, "api_key", None):
                    client = openai_client_cls(api_key=str(route.api_key), base_url=str(route.base_url or "") or None)
                    req: dict[str, Any] = {
                        "model": str(route.model),
                        "instructions": str(prompt or "").strip(),
                        "input": safe_text,
                        "text": {"format": {"type": "json_object"}},
                        "timeout": float(timeout_s),
                    }
                    effort = (reasoning_effort or "").strip().lower()
                    if effort in {"minimal", "low", "medium", "high", "xhigh"}:
                        req["reasoning"] = {"effort": effort}
                    resp = await client.responses.create(**req)
                    raw = str(getattr(resp, "output_text", "") or "").strip()
                    data = _try_parse_json_object(raw)

            if data is None:
                raw, _provider_id = await generate_chat_text(
                    route=route,
                    openrouter_cfg=cfg.chat.openrouter,
                    system_prompt=str(prompt or "").strip(),
                    user_message=safe_text,
                    images=[],
                    temperature=0.0,
                    max_tokens=512,
                    context_text="",
                    context_chunks=[],
                    timeout_s=float(timeout_s),
                )
                data = _try_parse_json_object(str(raw or ""))

            if not data:
                if require_success:
                    raise RuntimeError("Semantic KG LLM returned non-JSON or empty JSON output")
                return ([], [])
            break
        except Exception as exc:
            last_err = exc
            if attempt < (llm_attempts - 1):
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if require_success:
                raise
            return ([], [])

    entities_raw = data.get("entities") if isinstance(data, dict) else None
    concepts_raw = data.get("concepts") if isinstance(data, dict) else None
    relations_raw = data.get("relations") if isinstance(data, dict) else None

    entities: list[dict[str, str]] = []
    seen_entities: set[tuple[str, str]] = set()

    if isinstance(entities_raw, list):
        for item in entities_raw:
            if not isinstance(item, dict):
                continue
            name = _clean_entity_name(str(item.get("name") or ""))
            et = _normalize_entity_type(str(item.get("entity_type") or "concept"))
            if not name or not et:
                continue
            key = (et, name.lower())
            if key in seen_entities:
                continue
            seen_entities.add(key)
            entities.append({"name": name, "entity_type": et})

    if not entities and isinstance(concepts_raw, list):
        for c in concepts_raw:
            name = _clean_entity_name(str(c or ""))
            et = _normalize_entity_type("concept")
            if not name or not et:
                continue
            key = (et, name.lower())
            if key in seen_entities:
                continue
            seen_entities.add(key)
            entities.append({"name": name, "entity_type": et})

    relations: list[dict[str, str]] = []
    if isinstance(relations_raw, list):
        for r in relations_raw:
            if not isinstance(r, dict):
                continue
            src = _clean_entity_name(str(r.get("source") or ""))
            tgt = _clean_entity_name(str(r.get("target") or ""))
            rel_type = str(r.get("relation_type") or "related_to").strip().lower()
            if not src or not tgt or src == tgt:
                continue
            if rel_type not in {"related_to", "references"}:
                continue
            relations.append({"source": src, "target": tgt, "relation_type": rel_type})

    return (entities, relations)


async def _run_index(
    repo_id: str,
    repo_path: str,
    force_reindex: bool,
    *,
    event_queue: asyncio.Queue[dict[str, Any]] | None = None,
) -> IndexStats:
    cfg = await load_scoped_config(repo_id=repo_id)

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
    skip_dense = bool(int(cfg.indexing.skip_dense or 0) == 1)
    embedder = None if skip_dense else Embedder(cfg.embedding, cfg.tokenization)
    postgres = PostgresClient(cfg.indexing.postgres_url)
    await postgres.connect()
    await postgres.upsert_corpus(repo_id, name=repo_id, root_path=repo_path)

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
    # NOTE: Only guard when the corpus actually has chunks.  After a delete
    # operation, embedding metadata lingers on the corpora row even though no
    # vectors exist, so the guard must not block a fresh re-index.
    if corpus and not force_reindex and not skip_dense and embedder is not None:
        stored_model = str(corpus.get("embedding_model") or "").strip()
        stored_dim = int(corpus.get("embedding_dimensions") or 0)
        stored_provider = str(corpus.get("embedding_provider") or "").strip()

        # Only check if the corpus has been indexed before (non-empty metadata)
        # AND actually contains chunks (vectors).  If chunks were deleted but
        # metadata was not cleared, there is nothing to protect.
        has_chunks = False
        if stored_model and stored_dim > 0:
            stats = await postgres.get_index_stats(repo_id)
            has_chunks = stats.total_chunks > 0
        if stored_model and stored_dim > 0 and has_chunks:
            current_model = str(cfg.embedding.effective_model or "").strip()
            current_dim = int(embedder.dim)
            current_provider = str(cfg.embedding.embedding_type or "").strip()

            mismatches: list[str] = []
            if stored_dim != current_dim:
                mismatches.append(f"dimensions: stored={stored_dim}, config={current_dim}")
            if stored_model != current_model:
                mismatches.append(f"model: stored={stored_model}, config={current_model}")
            if stored_provider != current_provider:
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
    graph_builder: GraphBuilder | None = None
    try:
        if cfg.graph_indexing.enabled:
            db_name = cfg.graph_storage.resolve_database(repo_id)
            neo4j = Neo4jClient(
                cfg.graph_storage.neo4j_uri,
                cfg.graph_storage.neo4j_user,
                cfg.graph_storage.neo4j_password,
                database=db_name,
            )
            await neo4j.connect()
            graph_builder = GraphBuilder(neo4j, cfg.graph_indexing)

            # Lexical chunk vector index (Neo4j native vector indexes)
            if cfg.graph_indexing.build_lexical_graph and cfg.graph_indexing.store_chunk_embeddings and not skip_dense:
                try:
                    assert embedder is not None
                    await neo4j.ensure_vector_index(
                        index_name=cfg.graph_indexing.chunk_vector_index_name,
                        label="Chunk",
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                        dimensions=int(embedder.dim),
                        similarity_function=cfg.graph_indexing.vector_similarity_function,
                        wait_online=cfg.graph_indexing.wait_vector_index_online,
                        timeout_s=float(cfg.graph_indexing.vector_index_online_timeout_s),
                    )
                except Exception:
                    # Graph indexing should never block dense/sparse indexing.
                    pass
    except Exception as exc:
        # Graph layer is optional at runtime; vector + sparse indexing should still work.
        logger.warning("Neo4j graph initialization failed; graph indexing disabled for this run: %s", exc, exc_info=True)
        _emit_event(
            event_queue,
            {"type": "warning", "message": f"Graph indexing disabled: {exc}"},
            drop_oldest=True,
        )
        neo4j = None
        graph_builder = None

    try:
        return await _run_index_body(
            repo_id=repo_id,
            repo_path=repo_path,
            force_reindex=force_reindex,
            cfg=cfg,
            chunker=chunker,
            max_indexable_bytes=max_indexable_bytes,
            skip_dense=skip_dense,
            embedder=embedder,
            postgres=postgres,
            neo4j=neo4j,
            graph_builder=graph_builder,
            loader=loader,
            event_queue=event_queue,
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
    cfg: TriBridConfig,
    chunker: Chunker,
    max_indexable_bytes: int,
    skip_dense: bool,
    embedder: Embedder | None,
    postgres: PostgresClient,
    neo4j: Neo4jClient | None,
    graph_builder: GraphBuilder | None,
    loader: FileLoader,
    event_queue: asyncio.Queue[dict[str, Any]] | None,
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

    # GraphBuilder consumes (path, content) and currently only supports Python AST.
    graph_files: list[tuple[str, str]] = []

    if force_reindex:
        await postgres.delete_chunks(repo_id)
        if neo4j is not None:
            await neo4j.delete_graph(repo_id)
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": "🧹 Cleared existing index (force_reindex=1)"},
                drop_oldest=True,
            )

    # If skip_dense is enabled, ensure no stale embeddings remain from previous runs.
    # This makes graph-only / sparse-only workflows deterministic.
    if skip_dense:
        deleted = await postgres.delete_embeddings(repo_id)
        await postgres.update_corpus_embedding_meta(
            repo_id, provider="", model="", dimensions=0,
            ts_config=str(cfg.indexing.postgres_ts_config or ""),
        )
        if event_queue is not None:
            _emit_event(
                event_queue,
                {"type": "log", "message": f"⚡ skip_dense=1 → skipping embeddings (cleared {deleted} existing vectors)"},
                drop_oldest=True,
            )

    semantic_budget = int(cfg.graph_indexing.semantic_kg_max_chunks) if cfg.graph_indexing.semantic_kg_enabled else 0
    semantic_processed = 0

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
                {"type": "progress", "percent": int((_STATUS[repo_id].progress) * 100), "message": rel_path},
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

        async def _upsert_chunks_for_file(chunks: list[Chunk], rel_path: str = rel_path) -> list[Chunk]:
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
                    await postgres.upsert_fts(repo_id, chunks, ts_config=cfg.indexing.postgres_ts_config)
                if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_document_chunks").time():
                        await neo4j.upsert_document_and_chunks(
                            repo_id,
                            rel_path,
                            chunks,
                            store_embeddings=False,
                            embedding_property=cfg.graph_indexing.chunk_embedding_property,
                        )
                return chunks

            assert embedder is not None
            if all(c.embedding is not None for c in chunks):
                embedded = chunks
            else:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="embed_chunks").time():
                    embedded = await embedder.embed_chunks(chunks)
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_embeddings").time():
                await postgres.upsert_embeddings(repo_id, embedded)
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="postgres_upsert_fts").time():
                await postgres.upsert_fts(repo_id, embedded, ts_config=cfg.indexing.postgres_ts_config)
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_document_chunks").time():
                    await neo4j.upsert_document_and_chunks(
                        repo_id,
                        rel_path,
                        embedded,
                        store_embeddings=bool(cfg.graph_indexing.store_chunk_embeddings),
                        embedding_property=cfg.graph_indexing.chunk_embedding_property,
                    )
            return embedded

        indexing_batch = max(10, int(getattr(cfg.indexing, "indexing_batch_size", 100) or 100))

        chunks_for_semantic: list[Chunk] = []

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
                            for i0 in range(0, len(chunks), indexing_batch):
                                embedded_batch = await _upsert_chunks_for_file(chunks[i0 : i0 + indexing_batch])
                                if (
                                    semantic_budget > 0
                                    and semantic_processed < semantic_budget
                                    and cfg.graph_indexing.semantic_kg_enabled
                                    and neo4j is not None
                                ):
                                    remaining = max(0, semantic_budget - semantic_processed)
                                    chunks_for_semantic.extend(embedded_batch[:remaining])
            except Exception:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read_stream").inc()
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
                        parquet_text_columns_only=bool(
                            int(getattr(cfg.indexing, "parquet_extract_text_columns_only", 1) or 0) == 1
                        ),
                        parquet_include_column_names=bool(
                            int(getattr(cfg.indexing, "parquet_extract_include_column_names", 1) or 0) == 1
                        ),
                    )
                    if content is None:
                        content = abs_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="file_read").inc()
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
                from server.indexing.late_chunking import late_chunk_document

                strat = str(getattr(cfg.chunking, "chunking_strategy", "") or "").strip().lower()
                if strat not in {"fixed_tokens"}:
                    raise RuntimeError("late_chunking_local_only requires chunking.chunking_strategy='fixed_tokens'")
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="late_chunking").time():
                    chunks = late_chunk_document(rel_path, content, chunking=cfg.chunking, embedding=cfg.embedding)
                INDEX_FILES_PROCESSED_TOTAL.inc()
                if not chunks:
                    continue
                for i0 in range(0, len(chunks), indexing_batch):
                    embedded_batch = await _upsert_chunks_for_file(chunks[i0 : i0 + indexing_batch])
                    if (
                        semantic_budget > 0
                        and semantic_processed < semantic_budget
                        and cfg.graph_indexing.semantic_kg_enabled
                        and neo4j is not None
                    ):
                        remaining = max(0, semantic_budget - semantic_processed)
                        chunks_for_semantic.extend(embedded_batch[:remaining])
                continue

            if graph_builder is not None and rel_path.lower().endswith(".py"):
                graph_files.append((rel_path, content))

            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="chunk").time():
                chunks = chunker.chunk_file(rel_path, content)
            INDEX_FILES_PROCESSED_TOTAL.inc()
            if not chunks:
                continue
            for i0 in range(0, len(chunks), indexing_batch):
                embedded_batch = await _upsert_chunks_for_file(chunks[i0 : i0 + indexing_batch])
                if (
                    semantic_budget > 0
                    and semantic_processed < semantic_budget
                    and cfg.graph_indexing.semantic_kg_enabled
                    and neo4j is not None
                ):
                    remaining = max(0, semantic_budget - semantic_processed)
                    chunks_for_semantic.extend(embedded_batch[:remaining])

        # Optional semantic KG extraction (typed entities + relations linked to chunk_ids).
        if (
            neo4j is not None
            and cfg.graph_indexing.semantic_kg_enabled
            and semantic_budget > 0
            and semantic_processed < semantic_budget
        ):
            try:
                mode = str(cfg.graph_indexing.semantic_kg_mode or "heuristic").strip().lower()
                max_terms = int(cfg.graph_indexing.semantic_kg_max_concepts_per_chunk)
                min_len = int(cfg.graph_indexing.semantic_kg_min_concept_len)
                max_rels_per_chunk = int(cfg.graph_indexing.semantic_kg_max_relations_per_chunk)
                llm_model = str(cfg.graph_indexing.semantic_kg_llm_model or "").strip() or str(cfg.generation.enrich_model)
                llm_prompt = str(cfg.system_prompts.semantic_kg_extraction or "").strip()
                llm_timeout_s = float(cfg.graph_indexing.semantic_kg_llm_timeout_s)
                llm_max_chars = int(cfg.enrichment.enrich_max_chars)
                typed_entities_enabled = bool(cfg.graph_indexing.semantic_kg_typed_entities_enabled)
                require_llm_success = bool(cfg.graph_indexing.semantic_kg_require_llm_success)
                reasoning_effort = str(cfg.graph_indexing.semantic_kg_reasoning_effort or "medium").strip().lower()

                allowed_entity_types = {
                    str(t).strip().lower() for t in (cfg.graph_indexing.semantic_kg_allowed_entity_types or [])
                }
                if not allowed_entity_types:
                    allowed_entity_types = {"concept"}

                def _normalize_semantic_entity(name: str, entity_type: str) -> tuple[str, str] | None:
                    et = str(entity_type or "").strip().lower()
                    raw = str(name or "").strip()
                    if not raw:
                        return None
                    if et == "concept":
                        v = raw.lower()
                        v = re.sub(r"[^a-z0-9_]+", "_", v).strip("_")
                        if len(v) < min_len:
                            return None
                        if v in _SEM_STOPWORDS:
                            return None
                        if not _SEM_TOKEN_RE.fullmatch(v):
                            return None
                        return (v, v)
                    v = re.sub(r"[_-]+", " ", raw)
                    v = re.sub(r"\s+", " ", v).strip()
                    if len(v) < 2:
                        return None
                    key = v.lower()
                    return (v, key)

                semantic_entities: dict[str, Entity] = {}
                rels: list[Relationship] = []
                link_set: set[tuple[str, str]] = set()

                for ch in chunks_for_semantic:
                    if semantic_processed >= semantic_budget:
                        break
                    semantic_processed += 1

                    entities_raw: list[dict[str, str]]
                    relations_raw: list[dict[str, str]]
                    if mode == "llm" and llm_prompt:
                        entities_raw, relations_raw = await _extract_semantic_kg_llm(
                            (ch.content or "")[: max(0, llm_max_chars)],
                            cfg=cfg,
                            prompt=llm_prompt,
                            model=llm_model,
                            timeout_s=llm_timeout_s,
                            reasoning_effort=reasoning_effort,
                            typed_entities_enabled=typed_entities_enabled,
                            allowed_entity_types=allowed_entity_types,
                            require_success=require_llm_success,
                        )
                        if not entities_raw:
                            if require_llm_success:
                                raise RuntimeError("semantic_kg_require_llm_success=true and LLM extraction returned no entities")
                            concepts = _extract_semantic_concepts(ch.content, min_len=min_len, max_terms=max_terms)
                            entities_raw = [{"name": c, "entity_type": "concept"} for c in concepts]
                            relations_raw = []
                    else:
                        concepts = _extract_semantic_concepts(ch.content, min_len=min_len, max_terms=max_terms)
                        entities_raw = [{"name": c, "entity_type": "concept"} for c in concepts]
                        relations_raw = []

                    chunk_entity_ids: list[str] = []
                    chunk_name_to_id: dict[str, str] = {}
                    seen_entities: set[tuple[str, str]] = set()
                    for entry in entities_raw:
                        if not isinstance(entry, dict):
                            continue
                        et = str(entry.get("entity_type") or "concept").strip().lower()
                        if et not in {"person", "org", "location", "event", "concept"}:
                            continue
                        if et not in allowed_entity_types:
                            continue
                        normalized = _normalize_semantic_entity(str(entry.get("name") or ""), et)
                        if not normalized:
                            continue
                        display_name, stable_name = normalized
                        entity_key = (et, stable_name)
                        if entity_key in seen_entities:
                            continue
                        seen_entities.add(entity_key)
                        ent_id = GraphBuilder._stable_id(repo_id, "", et, stable_name)
                        if ent_id not in semantic_entities:
                            semantic_entities[ent_id] = Entity(
                                entity_id=ent_id,
                                name=display_name,
                                entity_type=et,  # type: ignore[arg-type]
                                file_path=None,
                                description=None,
                                properties={"source": "semantic", "mode": "llm" if mode == "llm" else "heuristic"},
                            )
                        chunk_entity_ids.append(ent_id)
                        chunk_name_to_id[stable_name] = ent_id
                        link_set.add((ent_id, ch.chunk_id))
                        if len(chunk_entity_ids) >= max_terms and et == "concept":
                            break

                    if not chunk_entity_ids:
                        continue

                    if max_rels_per_chunk > 0:
                        rels_added = 0
                        if mode == "llm" and relations_raw:
                            for r in relations_raw:
                                if rels_added >= max_rels_per_chunk:
                                    break
                                src_raw = str(r.get("source") or "")
                                tgt_raw = str(r.get("target") or "")
                                rel_type = str(r.get("relation_type") or "related_to").strip().lower()
                                if rel_type not in {"related_to", "references"}:
                                    continue
                                src_norm = _normalize_semantic_entity(src_raw, "concept")
                                tgt_norm = _normalize_semantic_entity(tgt_raw, "concept")
                                if not src_norm or not tgt_norm:
                                    continue
                                src_key = src_norm[1]
                                tgt_key = tgt_norm[1]
                                src_id = chunk_name_to_id.get(src_key)
                                tgt_id = chunk_name_to_id.get(tgt_key)
                                # If relation names are not in extracted entity list, materialize as concept entities.
                                for key, norm in ((src_key, src_norm), (tgt_key, tgt_norm)):
                                    if key in chunk_name_to_id:
                                        continue
                                    if "concept" not in allowed_entity_types:
                                        continue
                                    eid = GraphBuilder._stable_id(repo_id, "", "concept", key)
                                    if eid not in semantic_entities:
                                        semantic_entities[eid] = Entity(
                                            entity_id=eid,
                                            name=norm[0],
                                            entity_type="concept",
                                            file_path=None,
                                            description=None,
                                            properties={"source": "semantic", "mode": "llm"},
                                        )
                                    chunk_name_to_id[key] = eid
                                    chunk_entity_ids.append(eid)
                                    link_set.add((eid, ch.chunk_id))
                                src_id = chunk_name_to_id.get(src_key)
                                tgt_id = chunk_name_to_id.get(tgt_key)
                                if not src_id or not tgt_id or src_id == tgt_id:
                                    continue
                                rels.append(
                                    Relationship(
                                        source_id=src_id,
                                        target_id=tgt_id,
                                        relation_type=rel_type,  # type: ignore[arg-type]
                                        weight=float(cfg.graph_indexing.semantic_kg_relation_weight_llm),
                                        properties={"source": "semantic", "mode": "llm"},
                                    )
                                )
                                rels_added += 1
                        if rels_added == 0 and len(chunk_entity_ids) >= 2 and not require_llm_success:
                            root = chunk_entity_ids[0]
                            for tgt in chunk_entity_ids[1:]:
                                rels.append(
                                    Relationship(
                                        source_id=root,
                                        target_id=tgt,
                                        relation_type="related_to",
                                        weight=float(cfg.graph_indexing.semantic_kg_relation_weight_heuristic),
                                        properties={"source": "semantic", "mode": "heuristic"},
                                    )
                                )
                                rels_added += 1
                                if rels_added >= max_rels_per_chunk:
                                    break

                if semantic_entities:
                    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_semantic_entities").time():
                        await neo4j.upsert_entities(repo_id, list(semantic_entities.values()))
                if rels:
                    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_upsert_semantic_relationships").time():
                        await neo4j.upsert_relationships(repo_id, rels)
                if link_set:
                    with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_link_entities_to_chunks").time():
                        await neo4j.link_entities_to_chunks(
                            repo_id,
                            links=[{"entity_id": eid, "chunk_id": cid} for (eid, cid) in sorted(link_set)],
                        )
            except Exception:
                INDEX_STAGE_ERRORS_TOTAL.labels(stage="semantic_kg").inc()
                if bool(cfg.graph_indexing.semantic_kg_require_llm_success):
                    raise
                # Semantic KG is optional unless strict mode is enabled.
                pass

    if graph_builder is not None:
        try:
            if event_queue is not None:
                _emit_event(
                    event_queue,
                    {"type": "log", "message": "🧠 Building Neo4j graph (entities + relationships)..."},
                    drop_oldest=True,
                )
            with INDEX_STAGE_LATENCY_SECONDS.labels(stage="graph_build").time():
                await graph_builder.build_graph_for_files(
                    repo_id,
                    graph_files,
                    batch_size=int(cfg.indexing.indexing_batch_size),
                )
            # Link entities to chunk_ids so the graph leg can hydrate deterministically.
            if neo4j is not None and cfg.graph_indexing.build_lexical_graph:
                with INDEX_STAGE_LATENCY_SECONDS.labels(stage="neo4j_rebuild_entity_chunk_links").time():
                    await neo4j.rebuild_entity_chunk_links(repo_id)
        except Exception as exc:
            INDEX_STAGE_ERRORS_TOTAL.labels(stage="graph_build").inc()
            logger.warning("Graph AST build failed for repo_id=%s: %s", repo_id, exc, exc_info=True)
            _emit_event(
                event_queue,
                {"type": "warning", "message": f"Graph build incomplete: {exc}"},
                drop_oldest=True,
            )

    if not skip_dense:
        assert embedder is not None
        await postgres.update_corpus_embedding_meta(
            repo_id,
            provider=str(cfg.embedding.embedding_type or ""),
            model=str(cfg.embedding.effective_model or ""),
            dimensions=int(embedder.dim),
            ts_config=str(cfg.indexing.postgres_ts_config or ""),
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
    started_at = datetime.now(UTC)
    this_task = asyncio.current_task()
    try:
        INDEX_RUNS_TOTAL.inc()
        _emit_event(queue, {"type": "log", "message": f"🚀 Indexing started: {repo_id}"}, drop_oldest=True)
        with INDEX_DURATION_SECONDS.time():
            stats = await _run_index(
                repo_id,
                request.repo_path,
                request.force_reindex,
                event_queue=queue,
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
                    cfg.graph_storage.neo4j_password,
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
        _emit_event(queue, {"type": "complete", "message": "✓ Indexing complete"}, guarantee=True)
    except asyncio.CancelledError:
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
        _emit_event(queue, {"type": "cancelled", "message": "⚠ Indexing cancelled"}, guarantee=True)
        raise
    except Exception as e:
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

    skip_dense = bool(int(getattr(cfg.indexing, "skip_dense", 0) or 0) == 1)
    embedding_backend = str(getattr(cfg.embedding, "embedding_backend", "deterministic") or "deterministic").strip()
    embedding_provider = str(getattr(cfg.embedding, "embedding_type", "") or "").strip()
    embedding_model = str(getattr(cfg.embedding, "effective_model", "") or "").strip()

    # Pricing (models.json): deterministic backend and skip_dense imply $0 external cost.
    embedding_cost: float | None
    if skip_dense or embedding_backend != "provider":
        embedding_cost = 0.0
    else:
        embedding_cost = _estimate_embedding_cost_usd(
            provider=embedding_provider,
            model=embedding_model,
            total_tokens=est_tokens,
        )

    # Time estimate (rough): token throughput + small overhead.
    est_low: float | None = None
    est_high: float | None = None
    assumptions: list[str] = [
        f"tokens≈bytes/{_EST_BYTES_PER_TOKEN:g}",
        "time range is a heuristic (very rough)",
    ]
    if skipped_large_files > 0:
        assumptions.append(f"skips files > {max_indexable_bytes} bytes")

    if embedding_backend != "provider":
        tps = _EST_TOKENS_PER_SECOND_DETERMINISTIC
        assumptions.append("embedding_backend=deterministic → $0 external cost")
    else:
        tps = _EST_TOKENS_PER_SECOND_CLOUD if _looks_cloud_provider(embedding_provider) else _EST_TOKENS_PER_SECOND_LOCAL
        assumptions.append(f"tokens/sec≈{tps:,}")

    if est_tokens > 0 and tps > 0:
        base = float(est_tokens) / float(tps)
        est_low = max(0.0, (base * _EST_RANGE_LOW_MULT) + float(_EST_OVERHEAD_SECONDS))
        est_high = max(est_low, (base * _EST_RANGE_HIGH_MULT) + float(_EST_OVERHEAD_SECONDS) * 2.0)

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
        estimated_seconds_low=est_low,
        estimated_seconds_high=est_high,
        assumptions=assumptions,
    )


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
    total_tokens = 0
    try:
        pg2 = PostgresClient(cfg.indexing.postgres_url)
        await pg2.connect()
        try:
            stats = await pg2.get_index_stats(repo_id)
            total_tokens = int(stats.total_tokens or 0)
        finally:
            await pg2.disconnect()
    except Exception:
        total_tokens = 0

    embedding_cost = _estimate_embedding_cost_usd(
        provider=embedding_provider,
        model=embedding_model,
        total_tokens=total_tokens,
    )

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
        costs=DashboardIndexCosts(total_tokens=total_tokens, embedding_cost=embedding_cost),
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


@router.get("/index/{corpus_id}/status", response_model=IndexStatus)
async def get_index_status(corpus_id: str) -> IndexStatus:
    repo_id = corpus_id
    if repo_id in _STATUS:
        return _STATUS[repo_id]
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
        db_name = cfg.graph_storage.resolve_database(repo_id)
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.neo4j_password,
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
        stopwords_lang=str(cfg.indexing.bm25_stopwords_lang or "") or None,
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
            except asyncio.TimeoutError:
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
