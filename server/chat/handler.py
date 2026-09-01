from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import GenerationResult, generate_chat_text, stream_chat_text
from server.chat.prompt_budget import (
    PromptBudgetError,
    fit_context_to_budget,
    image_sizes_from_attachments,
    plan_prompt_budget,
)
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.chat.retrieval_gate import classify_for_recall
from server.chat.source_router import resolve_sources
from server.db.postgres import PostgresClient
from server.gateway_catalog import OPENROUTER_UPSTREAM_PREFIX, gateway_rows_snapshot
from server.models.chat_config import ImageAttachment, RecallConfig, RecallIntensity, RecallPlan
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    ChatProviderInfo,
    ChatRequest,
    ChatWebConfig,
    GenerationUnavailableDetail,
    TriBridConfig,
    WebGroundingMetadata,
)
from server.observability.costing import usage_total_tokens
from server.retrieval.cache import CacheMode, SemanticCacheService
from server.services.conversation_store import Conversation
from server.services.rag import FusionProtocol


def _safe_error_message(e: Exception, *, max_len: int = 400) -> str:
    # Best-effort redaction; keep debugging useful without leaking secrets.
    msg = str(e) or type(e).__name__
    msg = re.sub(r"(sk-[A-Za-z0-9_\\-]{10,})", "sk-REDACTED", msg)
    msg = re.sub(r"(Bearer\\s+)[A-Za-z0-9_.\\-]{10,}", r"\\1REDACTED", msg)
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[: int(max_len)]


def _normalize_cache_mode(cache_mode: str | CacheMode | None) -> CacheMode:
    mode = str(cache_mode or "default").strip().lower()
    if mode == "bypass":
        return "bypass"
    if mode == "refresh":
        return "refresh"
    return "default"


def _coerce_generation_result(result: Any) -> GenerationResult:
    if isinstance(result, GenerationResult):
        return result
    if isinstance(result, tuple):
        text = result[0] if len(result) > 0 else ""
        provider_response_id = result[1] if len(result) > 1 else None
        return GenerationResult(
            text=str(text or ""),
            provider_response_id=(str(provider_response_id).strip() if isinstance(provider_response_id, str) else None),
        )
    return GenerationResult(
        text=str(getattr(result, "text", "") or ""),
        provider_response_id=(
            str(getattr(result, "provider_response_id", "")).strip()
            if isinstance(getattr(result, "provider_response_id", None), str)
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class ChatOnceResult:
    text: str
    sources: list[ChunkMatch]
    provider_response_id: str | None
    recall_plan: RecallPlan | None
    provider: ChatProviderInfo | None
    llm_used: bool
    llm_error: str | None
    tokens_used: int
    web_grounding: WebGroundingMetadata


def _web_config_for_route(
    *, request: ChatRequest, config: TriBridConfig, route: Any
) -> ChatWebConfig | None:
    if not request.web_enabled:
        return None
    if not config.chat.web.enabled:
        raise RuntimeError("Web search is disabled by the server chat configuration")
    row = gateway_rows_snapshot().get(str(route.model))
    if row is None or not str(row.upstream).startswith(OPENROUTER_UPSTREAM_PREFIX):
        raise RuntimeError(
            f"Web search requires an OpenRouter-backed gateway alias; {route.model!r} is unsupported"
        )
    return config.chat.web


def fit_context_to_route(
    *,
    config: TriBridConfig,
    route_model: str,
    user_message: str,
    images: list[ImageAttachment],
    rag_chunks: list[ChunkMatch],
    recall_chunks: list[ChunkMatch],
) -> tuple[list[ChunkMatch], list[ChunkMatch], int]:
    """Trim retrieved context so the assembled prompt fits the alias's catalog context window.

    Blocking (tokenizes every chunk once); callers run it via `asyncio.to_thread`. An alias
    without a known window raises `PromptBudgetError` (fail closed, never unlimited).
    """

    system_prompt = get_system_prompt(
        has_rag_context=bool(rag_chunks),
        has_recall_context=bool(recall_chunks),
        config=config.chat,
    )
    budget = plan_prompt_budget(
        alias=route_model,
        system_prompt=system_prompt,
        user_message=user_message,
        max_tokens=int(config.chat.max_tokens),
        image_sizes=image_sizes_from_attachments(images),
    )
    return fit_context_to_budget(
        budget,
        rag_chunks=rag_chunks,
        recall_chunks=recall_chunks,
        render=lambda rag, recall: format_context_for_llm(rag_chunks=rag, recall_chunks=recall),
    )


class ChatGenerationError(RuntimeError):
    """Raised when chat generation cannot complete on the real provider path."""


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


def _history_for_cache(
    *,
    conversation: Conversation,
    message: str,
    max_messages: int,
    exclude_current_user_tail: bool,
) -> list[dict[str, str]]:
    msgs = list(conversation.messages or [])
    # Streaming path stores current user message before calling handler; exclude it
    # so non-stream and stream cache fingerprints align.
    if exclude_current_user_tail and msgs:
        last = msgs[-1]
        if last.role == "user" and (last.content or "").strip() == (message or "").strip():
            msgs = msgs[:-1]
    window = int(max_messages or 0)
    if window <= 0:
        msgs = []
    else:
        msgs = msgs[-window:]
    return [
        {
            "role": str(m.role),
            "content": str(m.content or ""),
        }
        for m in msgs
    ]


def _images_for_cache(images: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for image in images:
        mime = str(getattr(image, "mime_type", "") or "").strip().lower()
        detail = str(getattr(image, "detail", "") or "").strip().lower()
        raw_b64 = str(getattr(image, "base64", "") or "").strip()
        raw_url = str(getattr(image, "url", "") or "").strip()
        if raw_b64:
            source = "base64"
            content = raw_b64
        elif raw_url:
            source = "url"
            content = raw_url
        else:
            source = "none"
            content = ""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        out.append(
            {
                "mime_type": mime,
                "detail": detail,
                "source": source,
                "content_hash": content_hash,
            }
        )
    return out


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


async def _fusion_search_with_cache(
    *,
    fusion: FusionProtocol,
    corpus_ids: list[str],
    query: str,
    config: TriBridConfig,
    include_vector: bool,
    include_sparse: bool,
    include_graph: bool,
    top_k: int | None,
    cache_mode: str | CacheMode,
    cache_namespace: str,
) -> list[ChunkMatch]:
    return await fusion.search(
        corpus_ids,
        query,
        config.fusion,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
        cache_mode=_normalize_cache_mode(cache_mode),
        cache_namespace=str(cache_namespace or "search"),
    )


async def chat_once(
    *,
    request: ChatRequest,
    config: TriBridConfig,
    fusion: FusionProtocol,
    conversation: Conversation,
) -> ChatOnceResult:
    """Non-streaming chat handler."""

    corpus_ids = resolve_sources(request.sources)
    request_cache_mode = _normalize_cache_mode(request.cache_mode)
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
        rag_chunks = await _fusion_search_with_cache(
            fusion=fusion,
            corpus_ids=rag_corpus_ids,
            query=request.message,
            config=config,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
            cache_mode=request_cache_mode,
            cache_namespace="chat_retrieval",
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
                recall_chunks = await _fusion_search_with_cache(
                    fusion=fusion,
                    corpus_ids=[recall_id],
                    query=request.message,
                    config=config,
                    include_vector=include_vector,
                    include_sparse=include_sparse,
                    include_graph=False,  # Graph is never enabled for Recall.
                    top_k=top_k,
                    cache_mode=request_cache_mode,
                    cache_namespace="chat_recall_retrieval",
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
            "fusion_graph_qdrant_seed_chunks": int(rag_debug.get("fusion_graph_qdrant_seed_chunks") or 0),
            "fusion_graph_resolved_entities": int(rag_debug.get("fusion_graph_resolved_entities") or 0),
            "fusion_graph_relationship_expansion_hits": int(rag_debug.get("fusion_graph_relationship_expansion_hits") or 0),
            "fusion_graph_community_expansion_hits": int(rag_debug.get("fusion_graph_community_expansion_hits") or 0),
            "fusion_graph_hydrated_chunks": int(rag_debug.get("fusion_graph_hydrated_chunks") or 0),
            "chat_rag_fusion": rag_debug,
            "chat_recall_fusion": recall_debug,
        }
        cast(Any, fusion).last_debug = combined_debug
    except Exception:
        pass

    # Provider + prompt. The route is resolved first so the retrieved context can be
    # trimmed to the selected alias's context window (lowest-ranked chunks first).
    effective_model_override = (request.model_override or "").strip()
    if request.images or []:
        # chat.multimodal.vision_model_override is "force model for vision": it wins over the picker.
        vision_override = str(config.chat.multimodal.vision_model_override or "").strip()
        if vision_override:
            effective_model_override = vision_override
    resolved_route = None
    try:
        resolved_route = select_provider_route(
            config=config,
            model_override=effective_model_override,
        )
    except Exception:
        resolved_route = None
    context_dropped = 0
    if resolved_route is not None:
        # No route means generation fails closed with its own typed 503; nothing to budget.
        rag_chunks, recall_chunks, context_dropped = await asyncio.to_thread(
            fit_context_to_route,
            config=config,
            route_model=str(resolved_route.model),
            user_message=request.message,
            images=list(request.images or []),
            rag_chunks=rag_chunks,
            recall_chunks=recall_chunks,
        )
    if context_dropped:
        try:
            dbg = dict(getattr(fusion, "last_debug", None) or {})
            dbg["context_chunks_dropped_for_window"] = int(context_dropped)
            cast(Any, fusion).last_debug = dbg
        except Exception:
            pass
    sources: list[ChunkMatch] = [*rag_chunks, *recall_chunks]
    context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=recall_chunks)
    system_prompt = get_system_prompt(
        has_rag_context=bool(rag_chunks),
        has_recall_context=bool(recall_chunks),
        config=config.chat,
    )

    llm_used = True
    llm_error: str | None = None
    provider_info: ChatProviderInfo | None = None
    provider_id: str | None = None
    temperature = (
        float(config.chat.temperature_no_retrieval) if not corpus_ids else float(config.chat.temperature)
    )
    cache_service = SemanticCacheService(config)
    cache_scope_key = SemanticCacheService.scope_key(corpus_ids or ["direct_chat"])
    cache_allowed = not request.web_enabled and not (
        bool(request.images) and config.semantic_cache.bypass_if_images
    )
    # Hashing up to five 20 MiB attachments is CPU work: do it off the loop, and only when the
    # cache can be consulted at all.
    images_fp = (
        await asyncio.to_thread(
            lambda: SemanticCacheService.context_fingerprint(_images_for_cache(list(request.images or [])))
        )
        if (cache_allowed and request.images)
        else SemanticCacheService.context_fingerprint([])
    )
    cache_request_fingerprint = SemanticCacheService.fingerprint(
        {
            "namespace": "chat_generation",
            "sources": list(corpus_ids),
            "include_vector": bool(request.include_vector),
            "include_sparse": bool(request.include_sparse),
            "include_graph": bool(request.include_graph),
            "top_k": int(request.top_k or 0),
            "recall_intensity_override": (
                str(request.recall_intensity.value)
                if isinstance(request.recall_intensity, RecallIntensity)
                else (str(request.recall_intensity) if request.recall_intensity else "")
            ),
            "recall_plan_intensity": (
                str(recall_plan.intensity.value)
                if isinstance(recall_plan, RecallPlan)
                else (str(recall_plan.intensity) if recall_plan is not None else "")
            ),
            "model_override": str(effective_model_override or ""),
            "route_kind": str(getattr(resolved_route, "kind", "") or ""),
            "route_provider": str(getattr(resolved_route, "provider_name", "") or ""),
            "route_model": str(getattr(resolved_route, "model", "") or ""),
            "route_base_url": str(getattr(resolved_route, "base_url", "") or ""),
            "prompt": str(system_prompt),
            "temperature": float(temperature),
            "max_tokens": int(config.chat.max_tokens),
            "images_fp": images_fp,
            "history_fp": SemanticCacheService.context_fingerprint(
                _history_for_cache(
                    conversation=conversation,
                    message=request.message,
                    max_messages=max(0, int(config.semantic_cache.chat_history_window or 0)),
                    exclude_current_user_tail=False,
                )
            ),
            "context_fp": SemanticCacheService.context_fingerprint(
                [
                    {
                        "chunk_id": str(s.chunk_id),
                        "score": float(s.score),
                        "corpus_id": str((s.metadata or {}).get("corpus_id") or ""),
                    }
                    for s in sources
                ]
            ),
        }
    )
    if cache_allowed:
        hit = await cache_service.lookup(
            endpoint="chat",
            scope_key=cache_scope_key,
            query=request.message,
            request_fingerprint=cache_request_fingerprint,
            cache_mode=request_cache_mode,
            allow_semantic=True,
        )
    else:
        hit = None
    if hit is not None:
        cached_provider = hit.payload.get("provider")
        if isinstance(cached_provider, dict):
            try:
                provider_info = ChatProviderInfo.model_validate(cached_provider)
            except Exception:
                provider_info = None
        cached_text = str(hit.payload.get("message") or "").strip()
        cached_provider_id = hit.payload.get("provider_response_id")
        provider_id = str(cached_provider_id).strip() if isinstance(cached_provider_id, str) else None
        if cached_text:
            try:
                dbg = dict(getattr(fusion, "last_debug", None) or {})
                dbg.update(
                    {
                        "cache_hit": True,
                        "cache_match_type": hit.match_type,
                        "cache_similarity": float(hit.similarity),
                        "cache_namespace": "chat_generation",
                    }
                )
                cast(Any, fusion).last_debug = dbg
            except Exception:
                pass
            if provider_id:
                conversation.last_provider_response_id = provider_id
            return ChatOnceResult(
                text=cached_text,
                sources=sources,
                provider_response_id=provider_id,
                recall_plan=recall_plan,
                provider=provider_info,
                llm_used=True,
                llm_error=None,
                tokens_used=0,
                web_grounding=WebGroundingMetadata(),
            )

    try:
        route = resolved_route or select_provider_route(
            config=config,
            model_override=effective_model_override,
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )
        web_config = _web_config_for_route(request=request, config=config, route=route)

        generation = _coerce_generation_result(
            await generate_chat_text(
                route=route,
                system_prompt=system_prompt,
                user_message=request.message,
                images=list(request.images or []),
                image_detail=str(config.chat.multimodal.image_detail or "auto"),
                temperature=temperature,
                max_tokens=int(config.chat.max_tokens),
                context_text=context_text,
                context_chunks=sources,
                timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
                web_config=web_config,
            )
        )
        text = generation.text
        provider_id = generation.provider_response_id
        if not str(text or "").strip():
            raise RuntimeError("LLM returned an empty response")
    except PromptBudgetError:
        # Typed, non-retryable request refusal; the API maps it to a 422 detail.
        raise
    except Exception as e:
        llm_used = False
        llm_error = _safe_error_message(e)
        raise ChatGenerationError(llm_error) from e

    # Update in-memory conversation continuity (best-effort for local providers)
    if provider_id:
        conversation.last_provider_response_id = provider_id

    if (
        bool(llm_used)
        and bool(str(text or "").strip())
        and cache_allowed
        and float(temperature) <= float(config.semantic_cache.max_temperature_for_write)
    ):
        cache_written = await cache_service.write(
            endpoint="chat",
            scope_key=cache_scope_key,
            query=request.message,
            request_fingerprint=cache_request_fingerprint,
            payload={
                "message": str(text),
                "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
                "provider_response_id": provider_id,
            },
            cache_mode=request_cache_mode,
        )
        try:
            dbg = dict(getattr(fusion, "last_debug", None) or {})
            dbg.update(
                {
                    "cache_write": bool(cache_written),
                    "cache_namespace": "chat_generation",
                }
            )
            cast(Any, fusion).last_debug = dbg
        except Exception:
            pass

    return ChatOnceResult(
        text=text,
        sources=sources,
        provider_response_id=provider_id,
        recall_plan=recall_plan,
        provider=provider_info,
        llm_used=llm_used,
        llm_error=llm_error,
        tokens_used=usage_total_tokens(generation.usage),
        web_grounding=(
            generation.web_grounding
            or WebGroundingMetadata(web_requested=bool(request.web_enabled))
        ),
    )


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
    request_cache_mode = _normalize_cache_mode(request.cache_mode)
    recall_id = str(config.chat.recall.default_corpus_id or "recall_default")
    recall_selected = bool(config.chat.recall.enabled) and recall_id in set(corpus_ids)
    rag_corpus_ids = [cid for cid in corpus_ids if cid != recall_id]

    pg = PostgresClient(config.indexing.postgres_url)
    if _should_index_recall(recall_cfg=config.chat.recall, corpus_ids=corpus_ids):
        await _ensure_recall_ready(pg, config.chat.recall)

    rag_chunks: list[ChunkMatch] = []
    rag_debug: dict[str, Any] = {}
    if rag_corpus_ids and request.message.strip():
        rag_chunks = await _fusion_search_with_cache(
            fusion=fusion,
            corpus_ids=rag_corpus_ids,
            query=request.message,
            config=config,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
            cache_mode=request_cache_mode,
            cache_namespace="chat_retrieval",
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
                recall_chunks = await _fusion_search_with_cache(
                    fusion=fusion,
                    corpus_ids=[recall_id],
                    query=request.message,
                    config=config,
                    include_vector=include_vector,
                    include_sparse=include_sparse,
                    include_graph=False,
                    top_k=top_k,
                    cache_mode=request_cache_mode,
                    cache_namespace="chat_recall_retrieval",
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
            "fusion_graph_qdrant_seed_chunks": int(rag_debug.get("fusion_graph_qdrant_seed_chunks") or 0),
            "fusion_graph_resolved_entities": int(rag_debug.get("fusion_graph_resolved_entities") or 0),
            "fusion_graph_relationship_expansion_hits": int(rag_debug.get("fusion_graph_relationship_expansion_hits") or 0),
            "fusion_graph_community_expansion_hits": int(rag_debug.get("fusion_graph_community_expansion_hits") or 0),
            "fusion_graph_hydrated_chunks": int(rag_debug.get("fusion_graph_hydrated_chunks") or 0),
            "chat_rag_fusion": rag_debug,
            "chat_recall_fusion": recall_debug,
        }
        cast(Any, fusion).last_debug = combined_debug
    except Exception:
        pass

    # Provider + prompt. The route is resolved first so the retrieved context can be
    # trimmed to the selected alias's context window (lowest-ranked chunks first).
    effective_model_override = (request.model_override or "").strip()
    if request.images or []:
        # chat.multimodal.vision_model_override is "force model for vision": it wins over the picker.
        vision_override = str(config.chat.multimodal.vision_model_override or "").strip()
        if vision_override:
            effective_model_override = vision_override
    resolved_route = None
    try:
        resolved_route = select_provider_route(
            config=config,
            model_override=effective_model_override,
        )
    except Exception:
        resolved_route = None
    context_dropped = 0
    if resolved_route is not None:
        # No route means generation fails closed with its own typed 503; nothing to budget.
        rag_chunks, recall_chunks, context_dropped = await asyncio.to_thread(
            fit_context_to_route,
            config=config,
            route_model=str(resolved_route.model),
            user_message=request.message,
            images=list(request.images or []),
            rag_chunks=rag_chunks,
            recall_chunks=recall_chunks,
        )
    if context_dropped:
        try:
            dbg = dict(getattr(fusion, "last_debug", None) or {})
            dbg["context_chunks_dropped_for_window"] = int(context_dropped)
            cast(Any, fusion).last_debug = dbg
        except Exception:
            pass
    sources: list[ChunkMatch] = [*rag_chunks, *recall_chunks]
    context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=recall_chunks)
    system_prompt = get_system_prompt(
        has_rag_context=bool(rag_chunks),
        has_recall_context=bool(recall_chunks),
        config=config.chat,
    )

    llm_used = True
    llm_error: str | None = None
    provider_info: ChatProviderInfo | None = None
    accumulated = ""
    provider_response_id: str | None = None
    provider_usage: dict[str, Any] = {}
    web_grounding = WebGroundingMetadata(web_requested=bool(request.web_enabled))
    temperature = (
        float(config.chat.temperature_no_retrieval) if not corpus_ids else float(config.chat.temperature)
    )
    cache_service = SemanticCacheService(config)
    cache_scope_key = SemanticCacheService.scope_key(corpus_ids or ["direct_chat"])
    cache_allowed = not request.web_enabled and not (
        bool(request.images) and config.semantic_cache.bypass_if_images
    )
    # Hashing up to five 20 MiB attachments is CPU work: do it off the loop, and only when the
    # cache can be consulted at all.
    images_fp = (
        await asyncio.to_thread(
            lambda: SemanticCacheService.context_fingerprint(_images_for_cache(list(request.images or [])))
        )
        if (cache_allowed and request.images)
        else SemanticCacheService.context_fingerprint([])
    )
    cache_request_fingerprint = SemanticCacheService.fingerprint(
        {
            "namespace": "chat_generation",
            "sources": list(corpus_ids),
            "include_vector": bool(request.include_vector),
            "include_sparse": bool(request.include_sparse),
            "include_graph": bool(request.include_graph),
            "top_k": int(request.top_k or 0),
            "recall_intensity_override": (
                str(request.recall_intensity.value)
                if isinstance(request.recall_intensity, RecallIntensity)
                else (str(request.recall_intensity) if request.recall_intensity else "")
            ),
            "recall_plan_intensity": (
                str(recall_plan.intensity.value)
                if isinstance(recall_plan, RecallPlan)
                else (str(recall_plan.intensity) if recall_plan is not None else "")
            ),
            "model_override": str(effective_model_override or ""),
            "route_kind": str(getattr(resolved_route, "kind", "") or ""),
            "route_provider": str(getattr(resolved_route, "provider_name", "") or ""),
            "route_model": str(getattr(resolved_route, "model", "") or ""),
            "route_base_url": str(getattr(resolved_route, "base_url", "") or ""),
            "prompt": str(system_prompt),
            "temperature": float(temperature),
            "max_tokens": int(config.chat.max_tokens),
            "images_fp": images_fp,
            "history_fp": SemanticCacheService.context_fingerprint(
                _history_for_cache(
                    conversation=conversation,
                    message=request.message,
                    max_messages=max(0, int(config.semantic_cache.chat_history_window or 0)),
                    exclude_current_user_tail=True,
                )
            ),
            "context_fp": SemanticCacheService.context_fingerprint(
                [
                    {
                        "chunk_id": str(s.chunk_id),
                        "score": float(s.score),
                        "corpus_id": str((s.metadata or {}).get("corpus_id") or ""),
                    }
                    for s in sources
                ]
            ),
        }
    )
    if cache_allowed:
        hit = await cache_service.lookup(
            endpoint="chat",
            scope_key=cache_scope_key,
            query=request.message,
            request_fingerprint=cache_request_fingerprint,
            cache_mode=request_cache_mode,
            allow_semantic=True,
        )
    else:
        hit = None
    if hit is not None:
        cached_provider = hit.payload.get("provider")
        if isinstance(cached_provider, dict):
            try:
                provider_info = ChatProviderInfo.model_validate(cached_provider)
            except Exception:
                provider_info = None
        cached_text = str(hit.payload.get("message") or "").strip()
        cached_provider_id = hit.payload.get("provider_response_id")
        provider_response_id = str(cached_provider_id).strip() if isinstance(cached_provider_id, str) else None
        if cached_text:
            if provider_response_id:
                conversation.last_provider_response_id = provider_response_id
            try:
                dbg = dict(getattr(fusion, "last_debug", None) or {})
                dbg.update(
                    {
                        "cache_hit": True,
                        "cache_match_type": hit.match_type,
                        "cache_similarity": float(hit.similarity),
                        "cache_namespace": "chat_generation",
                    }
                )
                cast(Any, fusion).last_debug = dbg
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'text', 'content': cached_text})}\n\n"
            ended_at_ms = int(time.time() * 1000)
            sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in sources]
            done_payload: dict[str, Any] = {
                "type": "done",
                "run_id": run_id,
                "started_at_ms": int(started_at_ms),
                "ended_at_ms": int(ended_at_ms),
                "conversation_id": conversation.id,
                "sources": sources_json,
                "recall_plan": (
                    recall_plan.model_dump(mode="serialization", by_alias=True) if recall_plan is not None else None
                ),
                "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
                "provider_response_id": provider_response_id,
                "llm_used": True,
                "llm_error": None,
                "tokens_used": 0,
                "web_grounding": WebGroundingMetadata().model_dump(mode="json"),
            }
            yield f"data: {json.dumps(done_payload)}\n\n"
            return

    def _capture_provider_response_id(val: str) -> None:
        nonlocal provider_response_id
        if isinstance(val, str) and val.strip():
            provider_response_id = val.strip()

    def _capture_usage(value: dict[str, Any]) -> None:
        nonlocal provider_usage
        provider_usage = dict(value)

    def _capture_web_grounding(value: WebGroundingMetadata) -> None:
        nonlocal web_grounding
        web_grounding = value

    try:
        route = resolved_route or select_provider_route(
            config=config,
            model_override=effective_model_override,
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )
        web_config = _web_config_for_route(request=request, config=config, route=route)

        async for delta in stream_chat_text(
            route=route,
            system_prompt=system_prompt,
            user_message=request.message,
            images=list(request.images or []),
            image_detail=str(config.chat.multimodal.image_detail or "auto"),
            temperature=temperature,
            max_tokens=int(config.chat.max_tokens),
            context_text=context_text,
            context_chunks=sources,
            timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
            on_provider_response_id=_capture_provider_response_id,
            on_usage=_capture_usage,
            on_web_grounding=_capture_web_grounding,
            web_config=web_config,
        ):
            accumulated += delta
            yield f"data: {json.dumps({'type': 'text', 'content': delta})}\n\n"

        if not accumulated.strip():
            # Avoid "silent" blank assistant bubbles when a provider streams no text (or a test stub yields nothing).
            msg = "Error: LLM stream produced no content (check provider compatibility/config)"
            accumulated = msg
            llm_used = False
            llm_error = "empty_stream"
            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
    except PromptBudgetError:
        # The transport refuses before any network I/O and before the first delta is
        # yielded, so nothing has been streamed yet: let the API map it to the typed 413.
        raise
    except Exception as e:
        llm_used = False
        llm_error = _safe_error_message(e)
        error_detail = GenerationUnavailableDetail(
            operation="Chat stream generation",
            message="The generation gateway could not complete the chat request.",
            operator_hint=(
                "Verify the scoped LiteLLM gateway, client key, and selected model alias, then retry. "
                "Ragweld did not substitute a direct provider fallback."
            ),
        )
        yield (
            "data: "
            + json.dumps(
                {
                    "type": "error",
                    "message": llm_error,
                    "detail": error_detail.model_dump(mode="json"),
                }
            )
            + "\n\n"
        )
        ended_at_ms = int(time.time() * 1000)
        sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in sources]
        done_event_payload: dict[str, Any] = {
            "type": "done",
            "run_id": run_id,
            "started_at_ms": int(started_at_ms),
            "ended_at_ms": int(ended_at_ms),
            "conversation_id": conversation.id,
            "sources": sources_json,
            "recall_plan": (
                recall_plan.model_dump(mode="serialization", by_alias=True) if recall_plan is not None else None
            ),
            "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
            "provider_response_id": provider_response_id,
            "llm_used": False,
            "llm_error": llm_error,
            "tokens_used": usage_total_tokens(provider_usage),
            "web_grounding": web_grounding.model_dump(mode="json"),
        }
        yield f"data: {json.dumps(done_event_payload)}\n\n"
        return

    if provider_response_id:
        conversation.last_provider_response_id = provider_response_id

    if (
        bool(llm_used)
        and bool(accumulated.strip())
        and cache_allowed
        and float(temperature) <= float(config.semantic_cache.max_temperature_for_write)
    ):
        cache_written = await cache_service.write(
            endpoint="chat",
            scope_key=cache_scope_key,
            query=request.message,
            request_fingerprint=cache_request_fingerprint,
            payload={
                "message": accumulated,
                "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
                "provider_response_id": provider_response_id,
            },
            cache_mode=request_cache_mode,
        )
        try:
            dbg = dict(getattr(fusion, "last_debug", None) or {})
            dbg.update(
                {
                    "cache_write": bool(cache_written),
                    "cache_namespace": "chat_generation",
                }
            )
            cast(Any, fusion).last_debug = dbg
        except Exception:
            pass

    ended_at_ms = int(time.time() * 1000)
    sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in sources]
    done_event_payload = {
        "type": "done",
        "run_id": run_id,
        "started_at_ms": int(started_at_ms),
        "ended_at_ms": int(ended_at_ms),
        "conversation_id": conversation.id,
        "sources": sources_json,
        "recall_plan": recall_plan.model_dump(mode="serialization", by_alias=True) if recall_plan is not None else None,
        "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
        "provider_response_id": provider_response_id,
        "llm_used": bool(llm_used),
        "llm_error": llm_error,
        "tokens_used": usage_total_tokens(provider_usage),
        "web_grounding": web_grounding.model_dump(mode="json"),
    }
    yield f"data: {json.dumps(done_event_payload)}\n\n"
