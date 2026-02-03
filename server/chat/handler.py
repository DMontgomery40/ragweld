from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, cast

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.chat.retrieval_gate import classify_for_recall
from server.chat.source_router import resolve_sources
from server.db.postgres import PostgresClient
from server.models.chat_config import RecallConfig, RecallIntensity, RecallPlan
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChatRequest, TriBridConfig
from server.services.conversation_store import Conversation
from server.services.rag import FusionProtocol


def _conversation_turn_for_request(*, conversation: Conversation, message: str) -> int:
    """Return 0-indexed user turn number for this request.

    - Non-streaming: conversation does not yet include the current user message.
    - Streaming: API layer stores the user message before calling the stream handler.
    """

    user_count = sum(1 for m in (conversation.messages or []) if m.role == "user")
    if conversation.messages:
        last = conversation.messages[-1]
        if last.role == "user" and (last.content or "").strip() == (message or "").strip():
            user_count -= 1
    return max(0, int(user_count))


def _apply_recency_weight(*, chunks: list[ChunkMatch], recency_weight: float) -> list[ChunkMatch]:
    """Blend relevance + recency for Recall chunks and re-sort."""

    if not chunks:
        return chunks

    w = float(recency_weight)
    if w <= 0.0:
        return chunks
    if w > 1.0:
        w = 1.0

    max_rel = max((float(c.score) for c in chunks), default=0.0)
    if max_rel <= 0.0:
        max_rel = 1.0

    parsed: list[tuple[ChunkMatch, datetime | None]] = []
    for c in chunks:
        ts_raw = (c.metadata or {}).get("timestamp")
        ts: datetime | None = None
        if isinstance(ts_raw, str) and ts_raw.strip():
            try:
                ts = datetime.fromisoformat(ts_raw.strip())
            except Exception:
                ts = None
        parsed.append((c, ts))

    valid_times = [t for _c, t in parsed if t is not None]
    if len(valid_times) >= 2:
        t_min = min(valid_times)
        t_max = max(valid_times)
        span = (t_max - t_min).total_seconds()
    else:
        t_min = None
        span = 0.0

    rescored: list[ChunkMatch] = []
    for c, ts in parsed:
        rel_norm = float(c.score) / float(max_rel)
        if ts is None or t_min is None or span <= 0.0:
            rec_norm = 0.0
        else:
            rec_norm = max(0.0, min(1.0, (ts - t_min).total_seconds() / span))
        blended = ((1.0 - w) * rel_norm) + (w * rec_norm)
        rescored.append(c.model_copy(update={"score": float(blended)}))

    rescored.sort(key=lambda c: float(c.score), reverse=True)
    return rescored


async def _ensure_recall_ready(pg: PostgresClient, recall_cfg: RecallConfig) -> None:
    # Ensure Recall corpus exists before any retrieval/indexing attempts.
    await pg.connect()
    from server.chat.recall_indexer import ensure_recall_corpus

    await ensure_recall_corpus(pg, recall_cfg)


def _should_index_recall(*, recall_cfg: RecallConfig, corpus_ids: list[str]) -> bool:
    if not recall_cfg.enabled:
        return False
    recall_id = str(recall_cfg.default_corpus_id or "recall_default")
    return recall_id in set(corpus_ids)


async def chat_once(
    *,
    request: ChatRequest,
    config: TriBridConfig,
    fusion: FusionProtocol,
    conversation: Conversation,
) -> tuple[str, list[ChunkMatch], str | None, RecallPlan | None]:
    """Non-streaming chat handler."""

    corpus_ids = resolve_sources(request.sources)
    recall_id = str(config.chat.recall.default_corpus_id or "recall_default")
    recall_selected = bool(config.chat.recall.enabled) and recall_id in set(corpus_ids)
    rag_corpus_ids = [cid for cid in corpus_ids if cid != recall_id]

    # Ensure recall corpus exists before retrieval/indexing if enabled + selected.
    pg = PostgresClient(config.indexing.postgres_url)
    if _should_index_recall(recall_cfg=config.chat.recall, corpus_ids=corpus_ids):
        await _ensure_recall_ready(pg, config.chat.recall)

    rag_chunks: list[ChunkMatch] = []
    rag_debug: dict[str, Any] = {}
    if rag_corpus_ids and request.message.strip():
        rag_chunks = await fusion.search(
            rag_corpus_ids,
            request.message,
            config.fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
        )
        rag_debug = getattr(fusion, "last_debug", None) or {}

    recall_chunks: list[ChunkMatch] = []
    recall_plan: RecallPlan | None = None
    recall_debug: dict[str, Any] = {}
    if recall_selected and request.message.strip():
        recall_plan = classify_for_recall(
            message=request.message,
            conversation_turn=_conversation_turn_for_request(conversation=conversation, message=request.message),
            last_recall_had_results=bool(getattr(conversation, "last_recall_had_results", True)),
            rag_corpora_active=bool(rag_corpus_ids),
            config=config.chat.recall_gate,
            user_override=request.recall_intensity,
        )

        if recall_plan.intensity != RecallIntensity.skip:
            ovr = recall_plan.fusion_overrides
            include_vector = bool(request.include_vector) and (ovr.include_vector is not False)
            include_sparse = bool(request.include_sparse) and (ovr.include_sparse is not False)
            top_k = ovr.top_k if ovr.top_k is not None else request.top_k

            # If the user disabled both legs, treat as effectively skipped.
            if include_vector or include_sparse:
                recall_chunks = await fusion.search(
                    [recall_id],
                    request.message,
                    config.fusion,
                    include_vector=include_vector,
                    include_sparse=include_sparse,
                    include_graph=False,  # Graph is never enabled for Recall.
                    top_k=top_k,
                )
                recall_debug = getattr(fusion, "last_debug", None) or {}
                if ovr.recency_weight is not None:
                    recall_chunks = _apply_recency_weight(
                        chunks=recall_chunks,
                        recency_weight=float(ovr.recency_weight),
                    )
                conversation.last_recall_had_results = len(recall_chunks) > 0

    # Aggregate fusion debug for ChatDebugInfo. Keep per-call payloads under explicit keys.
    try:
        combined_debug = {
            "fusion_vector_enabled": bool(rag_debug.get("fusion_vector_enabled") or recall_debug.get("fusion_vector_enabled")),
            "fusion_sparse_enabled": bool(rag_debug.get("fusion_sparse_enabled") or recall_debug.get("fusion_sparse_enabled")),
            "fusion_graph_enabled": bool(rag_debug.get("fusion_graph_enabled") or recall_debug.get("fusion_graph_enabled")),
            "fusion_vector_results": int(rag_debug.get("fusion_vector_results") or 0) + int(recall_debug.get("fusion_vector_results") or 0),
            "fusion_sparse_results": int(rag_debug.get("fusion_sparse_results") or 0) + int(recall_debug.get("fusion_sparse_results") or 0),
            "fusion_graph_entity_hits": int(rag_debug.get("fusion_graph_entity_hits") or 0) + int(recall_debug.get("fusion_graph_entity_hits") or 0),
            "fusion_graph_hydrated_chunks": int(rag_debug.get("fusion_graph_hydrated_chunks") or 0) + int(recall_debug.get("fusion_graph_hydrated_chunks") or 0),
            "chat_rag_fusion": rag_debug,
            "chat_recall_fusion": recall_debug,
        }
        cast(Any, fusion).last_debug = combined_debug
    except Exception:
        pass

    sources: list[ChunkMatch] = [*rag_chunks, *recall_chunks]

    # Provider + prompt
    context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=recall_chunks)
    system_prompt = get_system_prompt(
        has_rag_context=bool(rag_chunks),
        has_recall_context=bool(recall_chunks),
        config=config.chat,
    )
    route = select_provider_route(chat_config=config.chat, model_override=request.model_override)
    temperature = (
        float(config.chat.temperature_no_retrieval) if not corpus_ids else float(config.chat.temperature)
    )

    text, provider_id = await generate_chat_text(
        route=route,
        openrouter_cfg=config.chat.openrouter,
        system_prompt=system_prompt,
        user_message=request.message,
        images=list(request.images or []),
        temperature=temperature,
        max_tokens=int(config.chat.max_tokens),
        context_text=context_text,
        context_chunks=sources,
        timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
    )

    # Update in-memory conversation continuity (best-effort for local providers)
    if provider_id:
        conversation.last_provider_response_id = provider_id

    return text, sources, provider_id, recall_plan


async def chat_stream(
    *,
    request: ChatRequest,
    config: TriBridConfig,
    fusion: FusionProtocol,
    conversation: Conversation,
    run_id: str,
    started_at_ms: int,
) -> AsyncIterator[str]:
    """Streaming chat handler that yields SSE events (type=text/done/error)."""

    corpus_ids = resolve_sources(request.sources)
    recall_id = str(config.chat.recall.default_corpus_id or "recall_default")
    recall_selected = bool(config.chat.recall.enabled) and recall_id in set(corpus_ids)
    rag_corpus_ids = [cid for cid in corpus_ids if cid != recall_id]

    pg = PostgresClient(config.indexing.postgres_url)
    if _should_index_recall(recall_cfg=config.chat.recall, corpus_ids=corpus_ids):
        await _ensure_recall_ready(pg, config.chat.recall)

    rag_chunks: list[ChunkMatch] = []
    rag_debug: dict[str, Any] = {}
    if rag_corpus_ids and request.message.strip():
        rag_chunks = await fusion.search(
            rag_corpus_ids,
            request.message,
            config.fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
        )
        rag_debug = getattr(fusion, "last_debug", None) or {}

    recall_chunks: list[ChunkMatch] = []
    recall_plan: RecallPlan | None = None
    recall_debug: dict[str, Any] = {}
    if recall_selected and request.message.strip():
        recall_plan = classify_for_recall(
            message=request.message,
            conversation_turn=_conversation_turn_for_request(conversation=conversation, message=request.message),
            last_recall_had_results=bool(getattr(conversation, "last_recall_had_results", True)),
            rag_corpora_active=bool(rag_corpus_ids),
            config=config.chat.recall_gate,
            user_override=request.recall_intensity,
        )

        if recall_plan.intensity != RecallIntensity.skip:
            ovr = recall_plan.fusion_overrides
            include_vector = bool(request.include_vector) and (ovr.include_vector is not False)
            include_sparse = bool(request.include_sparse) and (ovr.include_sparse is not False)
            top_k = ovr.top_k if ovr.top_k is not None else request.top_k

            if include_vector or include_sparse:
                recall_chunks = await fusion.search(
                    [recall_id],
                    request.message,
                    config.fusion,
                    include_vector=include_vector,
                    include_sparse=include_sparse,
                    include_graph=False,
                    top_k=top_k,
                )
                recall_debug = getattr(fusion, "last_debug", None) or {}
                if ovr.recency_weight is not None:
                    recall_chunks = _apply_recency_weight(
                        chunks=recall_chunks,
                        recency_weight=float(ovr.recency_weight),
                    )
                conversation.last_recall_had_results = len(recall_chunks) > 0

    try:
        combined_debug = {
            "fusion_vector_enabled": bool(rag_debug.get("fusion_vector_enabled") or recall_debug.get("fusion_vector_enabled")),
            "fusion_sparse_enabled": bool(rag_debug.get("fusion_sparse_enabled") or recall_debug.get("fusion_sparse_enabled")),
            "fusion_graph_enabled": bool(rag_debug.get("fusion_graph_enabled") or recall_debug.get("fusion_graph_enabled")),
            "fusion_vector_results": int(rag_debug.get("fusion_vector_results") or 0) + int(recall_debug.get("fusion_vector_results") or 0),
            "fusion_sparse_results": int(rag_debug.get("fusion_sparse_results") or 0) + int(recall_debug.get("fusion_sparse_results") or 0),
            "fusion_graph_entity_hits": int(rag_debug.get("fusion_graph_entity_hits") or 0) + int(recall_debug.get("fusion_graph_entity_hits") or 0),
            "fusion_graph_hydrated_chunks": int(rag_debug.get("fusion_graph_hydrated_chunks") or 0) + int(recall_debug.get("fusion_graph_hydrated_chunks") or 0),
            "chat_rag_fusion": rag_debug,
            "chat_recall_fusion": recall_debug,
        }
        cast(Any, fusion).last_debug = combined_debug
    except Exception:
        pass

    sources: list[ChunkMatch] = [*rag_chunks, *recall_chunks]

    context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=recall_chunks)
    system_prompt = get_system_prompt(
        has_rag_context=bool(rag_chunks),
        has_recall_context=bool(recall_chunks),
        config=config.chat,
    )
    route = select_provider_route(chat_config=config.chat, model_override=request.model_override)
    temperature = (
        float(config.chat.temperature_no_retrieval) if not corpus_ids else float(config.chat.temperature)
    )

    accumulated = ""
    try:
        async for delta in stream_chat_text(
            route=route,
            openrouter_cfg=config.chat.openrouter,
            system_prompt=system_prompt,
            user_message=request.message,
            images=list(request.images or []),
            temperature=temperature,
            max_tokens=int(config.chat.max_tokens),
            context_text=context_text,
            context_chunks=sources,
            timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
        ):
            accumulated += delta
            yield f"data: {json.dumps({'type': 'text', 'content': delta})}\n\n"

        ended_at_ms = int(time.time() * 1000)
        sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in sources]
        done_payload = {
            "type": "done",
            "run_id": run_id,
            "started_at_ms": int(started_at_ms),
            "ended_at_ms": int(ended_at_ms),
            "conversation_id": conversation.id,
            "sources": sources_json,
            "recall_plan": (
                recall_plan.model_dump(mode="serialization", by_alias=True) if recall_plan is not None else None
            ),
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
