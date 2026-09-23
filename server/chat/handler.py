from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar, cast

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import (
    GatewayContentMissingError,
    GenerationResult,
    generate_chat_text,
    stream_chat_text,
)
from server.chat.generation_failure import generation_unavailable_detail, safe_error_message
from server.chat.prompt_budget import (
    PromptBudgetError,
    fit_context_to_budget,
    image_sizes_from_attachments,
    plan_prompt_budget,
)
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import effective_model_override as resolve_effective_model_override
from server.chat.provider_router import select_provider_route
from server.chat.query_record import append_chat_query_record
from server.chat.retrieval_gate import classify_for_recall
from server.chat.source_router import resolve_sources
from server.chat.telemetry import ChatRunTelemetry
from server.db.postgres import PostgresClient
from server.gateway_catalog import OPENROUTER_UPSTREAM_PREFIX, gateway_rows_snapshot
from server.models.chat import Message
from server.models.chat_config import ImageAttachment, RecallConfig, RecallIntensity, RecallPlan
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    ChatProviderInfo,
    ChatRequest,
    ChatWebConfig,
    TriBridConfig,
    WebGroundingMetadata,
)
from server.observability.costing import usage_total_tokens
from server.observability.run_census import RunIdentity
from server.retrieval.cache import CacheMode, SemanticCacheService
from server.services.conversation_store import Conversation, get_conversation_store
from server.services.rag import FusionProtocol

# Once the stream is open, an SSE comment goes out whenever the client has seen nothing for
# this long, well inside Cloudflare's ~100 s origin timeout: a reasoning model can think for
# a minute or more before its first answer token, and every proxy on the public path
# (Cloudflare -> cloudflared -> Caddy) would otherwise idle the request out with a 524.
SSE_KEEPALIVE_INTERVAL_S = 15.0
SSE_KEEPALIVE = ": keepalive\n\n"

_T = TypeVar("_T")


class _SourceExhausted:
    """Marks the end of the source in `with_idle_ticks` (a task cannot raise StopAsyncIteration usefully)."""


_SOURCE_EXHAUSTED = _SourceExhausted()


async def _advance(source: AsyncGenerator[_T, None]) -> _T | _SourceExhausted:
    try:
        return await anext(source)
    except StopAsyncIteration:
        return _SOURCE_EXHAUSTED


def _discard_outcome(task: asyncio.Task[Any]) -> None:
    # The consumer is gone; retrieving the outcome keeps a late failure out of the loop's
    # "exception was never retrieved" log.
    if not task.cancelled():
        task.exception()


async def with_idle_ticks(source: AsyncGenerator[_T, None], *, interval_s: float) -> AsyncGenerator[_T | None, None]:
    """Yield ``source``'s items, and ``None`` each time ``interval_s`` passes without one.

    The source is advanced in a task of its own so a tick can be produced while an item is
    still pending; the consumer's own work (commits, the terminal event) stays in the
    consumer's task. Closing or cancelling this generator cancels the pending advance, which
    reaches the source at its current await exactly as a direct cancellation would.
    """
    pending: asyncio.Task[_T | _SourceExhausted] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.create_task(_advance(source))
            done, _ = await asyncio.wait({pending}, timeout=interval_s)
            if not done:
                yield None
                continue
            finished, pending = pending, None
            item = finished.result()
            if isinstance(item, _SourceExhausted):
                return
            yield item
    finally:
        if pending is not None:
            pending.cancel()
            pending.add_done_callback(_discard_outcome)
        else:
            await source.aclose()


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
    billing_session_id: str,
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
        billing_session_id=billing_session_id,
    )


async def chat_once(
    *,
    request: ChatRequest,
    config: TriBridConfig,
    fusion: FusionProtocol,
    conversation: Conversation,
    telemetry: ChatRunTelemetry,
    billing_session_id: str | None = None,
) -> ChatOnceResult:
    """Non-streaming chat handler. Reports its generation phase, usage and cost to `telemetry`;
    the caller finishes it with the request's outcome."""
    billing_session_id = billing_session_id or str(uuid.uuid4())

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
            billing_session_id=billing_session_id,
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
                    billing_session_id=billing_session_id,
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
    # chat.multimodal.vision_model_override is "force model for vision": it wins over the picker.
    effective_model_override = resolve_effective_model_override(request=request, config=config)
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
    cache_service = SemanticCacheService(
        config, identity=RunIdentity(billing_session_id, corpus_ids[0] if corpus_ids else "global", "cache_embeddings"),
    )
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

    telemetry.begin_generation()
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
        telemetry.record_usage(generation.usage)
        telemetry.record_cost(generation.cost_summary)
        if not str(text or "").strip():
            raise RuntimeError("LLM returned an empty response")
    except PromptBudgetError:
        # Typed, non-retryable request refusal; the API maps it to a 422 detail.
        raise
    except Exception as e:
        if isinstance(e, GatewayContentMissingError):
            # Billed although it produced no answer (a reasoning model out of budget).
            telemetry.record_usage(e.usage)
            telemetry.record_cost(e.cost_summary)
        llm_used = False
        llm_error = safe_error_message(e)
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
    telemetry: ChatRunTelemetry,
) -> AsyncIterator[str]:
    """Streaming chat handler that yields SSE events. Reports its generation phase, usage,
    cost and generation failure to `telemetry`; the endpoint marks events and finishes it.

    ``status`` (stage ``generating``, once the prompt is accepted and the request is about to
    go to the gateway), ``thinking`` (the model's reasoning, only when
    ``ui.chat_stream_include_thinking`` is on), ``text``, ``error`` and the terminal ``done``;
    plus ``: keepalive`` comments while the model is silent after ``status``. Only ``text``
    is the answer: reasoning is never persisted, cached or counted as content.
    """

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
            billing_session_id=run_id,
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
                    billing_session_id=run_id,
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
    # chat.multimodal.vision_model_override is "force model for vision": it wins over the picker.
    effective_model_override = resolve_effective_model_override(request=request, config=config)
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
    cache_service = SemanticCacheService(
        config, identity=RunIdentity(run_id, corpus_ids[0] if corpus_ids else "global", "cache_embeddings"),
    )
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
            # Commit the exchange (messages, provider chaining, query record) before `done`.
            async def _commit_cached_exchange() -> None:
                store = get_conversation_store()
                store.add_message(conversation.id, Message(role="user", content=request.message), None)
                store.add_message(conversation.id, Message(role="assistant", content=cached_text), provider_response_id)
                if provider_response_id:
                    conversation.last_provider_response_id = provider_response_id
                try:
                    await append_chat_query_record(
                        config=config,
                        fusion=fusion,
                        event_id=run_id,
                        conversation_id=conversation.id,
                        corpus_ids=list(corpus_ids),
                        query=request.message,
                        sources=sources,
                        outcome="ok",
                    )
                except Exception:
                    pass

            try:
                await asyncio.shield(_commit_cached_exchange())
            except asyncio.CancelledError:
                pass
            yield f"data: {json.dumps(done_payload)}\n\n"
            return

    def _capture_provider_response_id(val: str) -> None:
        nonlocal provider_response_id
        if isinstance(val, str) and val.strip():
            provider_response_id = val.strip()

    def _capture_usage(value: dict[str, Any]) -> None:
        nonlocal provider_usage
        provider_usage = dict(value)
        telemetry.record_usage(value)

    def _capture_web_grounding(value: WebGroundingMetadata) -> None:
        nonlocal web_grounding
        web_grounding = value

    telemetry.begin_generation()
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

        # The first event this handler yields is what lets the endpoint send its response
        # headers, so nothing goes out before `status`: until the transport reports the prompt
        # accepted, a refusal is still an HTTP status (a prompt-budget 413), not a stream.
        generation_started = False
        gateway_stream = stream_chat_text(
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
            on_cost_summary=telemetry.record_cost,
            on_web_grounding=_capture_web_grounding,
            web_config=web_config,
            include_reasoning=bool(config.ui.chat_stream_include_thinking),
        )
        async with aclosing(with_idle_ticks(gateway_stream, interval_s=SSE_KEEPALIVE_INTERVAL_S)) as events:
            async for event in events:
                if event is None:
                    if generation_started:
                        yield SSE_KEEPALIVE
                    continue
                if event.kind == "request":
                    generation_started = True
                    status = {"type": "status", "stage": "generating", "sources_count": len(sources)}
                    yield f"data: {json.dumps(status)}\n\n"
                    continue
                if event.kind == "reasoning":
                    yield f"data: {json.dumps({'type': 'thinking', 'content': event.content})}\n\n"
                    continue
                accumulated += event.content
                yield f"data: {json.dumps({'type': 'text', 'content': event.content})}\n\n"

        if not accumulated.strip():
            # A provider that streams no text is a failed generation, reported through the
            # same typed error event as every other one, never as an assistant message.
            raise RuntimeError("LLM stream produced no content (check provider compatibility/config)")
    except PromptBudgetError:
        # The transport refuses before any network I/O and before its `request` item, so
        # `status` has not gone out and nothing has been streamed: the API maps it to the 413.
        raise
    except Exception as e:
        llm_used = False
        telemetry.generation_error = e
        # One classifier for every generation surface: the card carries the sanitised
        # provider reason and a hint chosen from it (spend limit, rejected key, lane down).
        error_detail = generation_unavailable_detail(e, operation="Chat stream generation")
        llm_error = error_detail.gateway_reason
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
        # No exchange to commit. Retrieval did happen, and its query/source record is a
        # retrieval record for feedback and triplet mining, written the same shielded way.
        # Its outcome says the run produced no answer, so feedback on it is refused.
        failed_outcome = telemetry.classify(e)

        async def _record_failed_retrieval() -> None:
            try:
                await append_chat_query_record(
                    config=config,
                    fusion=fusion,
                    event_id=run_id,
                    conversation_id=conversation.id,
                    corpus_ids=list(corpus_ids),
                    query=request.message,
                    sources=sources,
                    outcome=failed_outcome,
                )
            except Exception:
                pass

        try:
            await asyncio.shield(_record_failed_retrieval())
        except asyncio.CancelledError:
            pass
        yield f"data: {json.dumps(done_event_payload)}\n\n"
        return

    cache_written = False
    # The answer is complete: commit the exchange's generation state (provider chaining and
    # the semantic cache) before the terminal event goes out, shielded from the cancellation a
    # closing client causes, so no state is left half-written in either direction.
    async def _commit_generation_state() -> None:
        """Commit the exchange atomically: the messages (synchronous, first), provider
        chaining, the generation cache and the query/source record, all before the
        terminal event goes out and all under one shield."""
        nonlocal cache_written
        store = get_conversation_store()
        store.add_message(conversation.id, Message(role="user", content=request.message), None)
        store.add_message(conversation.id, Message(role="assistant", content=accumulated), provider_response_id)
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
            await append_chat_query_record(
                config=config,
                fusion=fusion,
                event_id=run_id,
                conversation_id=conversation.id,
                corpus_ids=list(corpus_ids),
                query=request.message,
                sources=sources,
                outcome="ok",
            )
        except Exception:
            pass

    try:
        await asyncio.shield(_commit_generation_state())
    except asyncio.CancelledError:
        pass
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
