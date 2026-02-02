from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.provider_router import select_provider_route
from server.chat.source_router import resolve_sources
from server.db.postgres import PostgresClient
from server.models.chat_config import RecallConfig
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChatRequest, TriBridConfig
from server.services.conversation_store import Conversation
from server.services.rag import FusionProtocol


def _build_system_prompt(*, config: TriBridConfig, corpus_ids: list[str]) -> str:
    chat_cfg = config.chat
    prompt = str(chat_cfg.system_prompt_base or "")

    recall_id = str(chat_cfg.recall.default_corpus_id or "recall_default")
    has_recall = recall_id in set(corpus_ids)
    has_rag = any(cid and cid != recall_id for cid in corpus_ids)

    if has_recall:
        prompt += str(chat_cfg.system_prompt_recall_suffix or "")
    if has_rag:
        prompt += str(chat_cfg.system_prompt_rag_suffix or "")
    return prompt.strip() or "You are a helpful assistant."


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
) -> tuple[str, list[ChunkMatch], str | None]:
    """Non-streaming chat handler."""

    corpus_ids = resolve_sources(request.sources)

    # Ensure recall corpus exists before retrieval/indexing if enabled + selected.
    pg = PostgresClient(config.indexing.postgres_url)
    if _should_index_recall(recall_cfg=config.chat.recall, corpus_ids=corpus_ids):
        await _ensure_recall_ready(pg, config.chat.recall)

    # Retrieval (skip when nothing checked)
    sources: list[ChunkMatch] = []
    if corpus_ids:
        sources = await fusion.search(
            corpus_ids,
            request.message,
            config.fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
        )

    # Provider + prompt
    system_prompt = _build_system_prompt(config=config, corpus_ids=corpus_ids)
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
        context_chunks=sources,
        timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
    )

    # Update in-memory conversation continuity (best-effort for local providers)
    if provider_id:
        conversation.last_provider_response_id = provider_id

    return text, sources, provider_id


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

    pg = PostgresClient(config.indexing.postgres_url)
    if _should_index_recall(recall_cfg=config.chat.recall, corpus_ids=corpus_ids):
        await _ensure_recall_ready(pg, config.chat.recall)

    # Retrieval (skip when nothing checked)
    sources: list[ChunkMatch] = []
    if corpus_ids:
        sources = await fusion.search(
            corpus_ids,
            request.message,
            config.fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
        )

    system_prompt = _build_system_prompt(config=config, corpus_ids=corpus_ids)
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
        }
        yield f"data: {json.dumps(done_payload)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

