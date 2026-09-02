from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import GenerationResult, generate_chat_text, stream_chat_text
from server.chat.generation_failure import generation_unavailable_detail
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChatDebugInfo, ChatProviderInfo, TriBridConfig
from server.retrieval.cache import CacheMode, SemanticCacheService

from server.services.rag import FusionProtocol, build_chat_debug_info



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


async def _fusion_search_with_cache(
    *,
    fusion: FusionProtocol,
    corpus_id: str,
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
        [str(corpus_id)],
        query,
        config.fusion,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        top_k=top_k,
        cache_mode=_normalize_cache_mode(cache_mode),
        cache_namespace=str(cache_namespace or "search"),
    )


async def retrieve_best_effort(
    *,
    query: str,
    corpus_id: str,
    config: TriBridConfig,
    fusion: FusionProtocol,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
    cache_mode: str | CacheMode = "default",
) -> tuple[list[ChunkMatch], dict[str, Any]]:
    if not query.strip() or not str(corpus_id or "").strip():
        return ([], {"retrieval_error": "Missing query or corpus_id"})

    # Retrieval either succeeds or raises: a retrieval failure turned into "no context" would
    # let generation answer ungrounded with a 200, which is the substitution this lane forbids.
    chunks = await _fusion_search_with_cache(
        fusion=fusion,
        corpus_id=corpus_id,
        query=query,
        config=config,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        top_k=top_k,
        cache_mode=cache_mode,
        cache_namespace="answer_retrieval",
    )
    retrieval_debug: dict[str, Any] = getattr(fusion, "last_debug", None) or {}
    return (chunks, retrieval_debug)


async def answer_best_effort(
    *,
    query: str,
    corpus_id: str,
    config: TriBridConfig,
    fusion: FusionProtocol,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
    system_prompt_override: str | None = None,
    model_override: str = "",
    cache_mode: str | CacheMode = "default",
) -> tuple[str, list[ChunkMatch], ChatProviderInfo | None, ChatDebugInfo]:
    normalized_cache_mode = _normalize_cache_mode(cache_mode)
    chunks, _ = await retrieve_best_effort(
        query=query,
        corpus_id=corpus_id,
        config=config,
        fusion=fusion,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
        cache_mode=normalized_cache_mode,
    )

    provider_info: ChatProviderInfo | None = None
    llm_used = True
    llm_error: str | None = None
    cache_debug: dict[str, Any] = {}

    # Prompt + context (Chat 2.0 semantics).
    context_text = format_context_for_llm(rag_chunks=chunks, recall_chunks=[])
    if system_prompt_override is not None and system_prompt_override.strip():
        system_prompt = system_prompt_override.strip()
    else:
        system_prompt = get_system_prompt(
            has_rag_context=bool(chunks),
            has_recall_context=False,
            config=config.chat,
        )
    temperature = float(config.chat.temperature_no_retrieval) if not chunks else float(config.chat.temperature)
    resolved_route = None
    try:
        resolved_route = select_provider_route(
            config=config,
            model_override=(model_override or "").strip(),
        )
    except Exception:
        resolved_route = None

    cache_service = SemanticCacheService(config)
    cache_scope_key = SemanticCacheService.scope_key([corpus_id])
    cache_request_fingerprint = SemanticCacheService.fingerprint(
        {
            "namespace": "answer_generation",
            "corpus_id": str(corpus_id),
            "include_vector": bool(include_vector),
            "include_sparse": bool(include_sparse),
            "include_graph": bool(include_graph),
            "top_k": int(top_k or 0),
            "model_override": str(model_override or ""),
            "route_kind": str(getattr(resolved_route, "kind", "") or ""),
            "route_provider": str(getattr(resolved_route, "provider_name", "") or ""),
            "route_model": str(getattr(resolved_route, "model", "") or ""),
            "route_base_url": str(getattr(resolved_route, "base_url", "") or ""),
            "system_prompt_override": str(system_prompt_override or ""),
            "prompt": str(system_prompt),
            "temperature": float(temperature),
            "max_tokens": int(config.chat.max_tokens),
            "context_fp": SemanticCacheService.context_fingerprint(
                [
                    {
                        "chunk_id": str(c.chunk_id),
                        "score": float(c.score),
                        "corpus_id": str((c.metadata or {}).get("corpus_id") or ""),
                    }
                    for c in chunks
                ]
            ),
        }
    )
    hit = await cache_service.lookup(
        endpoint="answer",
        scope_key=cache_scope_key,
        query=query,
        request_fingerprint=cache_request_fingerprint,
        cache_mode=normalized_cache_mode,
        allow_semantic=True,
    )
    if hit is not None:
        cached_provider = hit.payload.get("provider")
        if isinstance(cached_provider, dict):
            try:
                provider_info = ChatProviderInfo.model_validate(cached_provider)
            except Exception:
                provider_info = None
        answer_text = str(hit.payload.get("answer") or "").strip()
        if answer_text:
            cache_debug = {
                "cache_hit": True,
                "cache_match_type": hit.match_type,
                "cache_similarity": float(hit.similarity),
                "cache_namespace": "answer_generation",
            }
            debug = build_chat_debug_info(
                config=config,
                fusion=fusion,
                include_vector=bool(include_vector),
                include_sparse=bool(include_sparse),
                include_graph=bool(include_graph),
                top_k=top_k,
                sources=chunks,
                recall_plan=None,
                provider=provider_info,
            ).model_copy(
                update={
                    "llm_used": True,
                    "llm_error": None,
                    "fusion_debug": {**(getattr(fusion, "last_debug", None) or {}), **cache_debug},
                }
            )
            return answer_text, chunks, provider_info, debug

    try:
        route = resolved_route or select_provider_route(
            config=config,
            model_override=(model_override or "").strip(),
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )

        generation = _coerce_generation_result(
            await generate_chat_text(
                route=route,
                system_prompt=system_prompt,
            user_message=query,
            images=[],
            image_detail=str(config.chat.multimodal.image_detail or "auto"),
            temperature=temperature,
            max_tokens=int(config.chat.max_tokens),
            context_text=context_text,
            context_chunks=chunks,
            timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
            )
        )
        answer_text = (generation.text or "").strip()
        if not answer_text:
            raise RuntimeError("LLM returned an empty response")
    except Exception:
        # No "retrieval-only" substitute: a generation failure leaves this function as the
        # exception it is, and the API maps it to the typed 503 the chat lane raises.
        raise

    debug = build_chat_debug_info(
        config=config,
        fusion=fusion,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        top_k=top_k,
        sources=chunks,
        recall_plan=None,
        provider=provider_info,
    ).model_copy(
        update={
            "llm_used": bool(llm_used),
            "llm_error": llm_error,
            "fusion_debug": {**(getattr(fusion, "last_debug", None) or {}), **cache_debug},
        }
    )

    if bool(llm_used) and bool(answer_text.strip()) and float(temperature) <= float(
        config.semantic_cache.max_temperature_for_write
    ):
        payload: dict[str, Any] = {
            "answer": answer_text,
            "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
        }
        cache_written = await cache_service.write(
            endpoint="answer",
            scope_key=cache_scope_key,
            query=query,
            request_fingerprint=cache_request_fingerprint,
            payload=payload,
            cache_mode=normalized_cache_mode,
        )
        debug = debug.model_copy(
            update={
                "fusion_debug": {
                    **(debug.fusion_debug or {}),
                    "cache_write": bool(cache_written),
                    "cache_namespace": "answer_generation",
                }
            }
        )

    return answer_text, chunks, provider_info, debug


async def stream_answer_best_effort(
    *,
    query: str,
    corpus_id: str,
    config: TriBridConfig,
    fusion: FusionProtocol,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
    system_prompt_override: str | None = None,
    model_override: str = "",
    cache_mode: str | CacheMode = "default",
    prefetched_chunks: list[ChunkMatch] | None = None,
    conversation_id: str | None = None,
    run_id: str | None = None,
    started_at_ms: int | None = None,
) -> AsyncIterator[str]:
    normalized_cache_mode = _normalize_cache_mode(cache_mode)
    if prefetched_chunks is not None:
        chunks = list(prefetched_chunks)
    else:
        chunks, _ = await retrieve_best_effort(
            query=query,
            corpus_id=corpus_id,
            config=config,
            fusion=fusion,
            include_vector=include_vector,
            include_sparse=include_sparse,
            include_graph=include_graph,
            top_k=top_k,
            cache_mode=normalized_cache_mode,
        )

    provider_info: ChatProviderInfo | None = None
    provider_response_id: str | None = None

    def _capture_provider_response_id(val: str) -> None:
        nonlocal provider_response_id
        if isinstance(val, str) and val.strip():
            provider_response_id = val.strip()

    llm_used = True
    llm_error: str | None = None
    accumulated = ""

    context_text = format_context_for_llm(rag_chunks=chunks, recall_chunks=[])
    if system_prompt_override is not None and system_prompt_override.strip():
        system_prompt = system_prompt_override.strip()
    else:
        system_prompt = get_system_prompt(
            has_rag_context=bool(chunks),
            has_recall_context=False,
            config=config.chat,
        )
    temperature = float(config.chat.temperature_no_retrieval) if not chunks else float(config.chat.temperature)
    resolved_route = None
    try:
        resolved_route = select_provider_route(
            config=config,
            model_override=(model_override or "").strip(),
        )
    except Exception:
        resolved_route = None

    cache_service = SemanticCacheService(config)
    cache_scope_key = SemanticCacheService.scope_key([corpus_id])
    cache_request_fingerprint = SemanticCacheService.fingerprint(
        {
            "namespace": "answer_generation",
            "corpus_id": str(corpus_id),
            "include_vector": bool(include_vector),
            "include_sparse": bool(include_sparse),
            "include_graph": bool(include_graph),
            "top_k": int(top_k or 0),
            "model_override": str(model_override or ""),
            "route_kind": str(getattr(resolved_route, "kind", "") or ""),
            "route_provider": str(getattr(resolved_route, "provider_name", "") or ""),
            "route_model": str(getattr(resolved_route, "model", "") or ""),
            "route_base_url": str(getattr(resolved_route, "base_url", "") or ""),
            "system_prompt_override": str(system_prompt_override or ""),
            "prompt": str(system_prompt),
            "temperature": float(temperature),
            "max_tokens": int(config.chat.max_tokens),
            "context_fp": SemanticCacheService.context_fingerprint(
                [
                    {
                        "chunk_id": str(c.chunk_id),
                        "score": float(c.score),
                        "corpus_id": str((c.metadata or {}).get("corpus_id") or ""),
                    }
                    for c in chunks
                ]
            ),
        }
    )
    hit = await cache_service.lookup(
        endpoint="answer",
        scope_key=cache_scope_key,
        query=query,
        request_fingerprint=cache_request_fingerprint,
        cache_mode=normalized_cache_mode,
        allow_semantic=True,
    )
    if hit is not None:
        cached_provider = hit.payload.get("provider")
        if isinstance(cached_provider, dict):
            try:
                provider_info = ChatProviderInfo.model_validate(cached_provider)
            except Exception:
                provider_info = None
        cached_text = str(hit.payload.get("answer") or "").strip()
        if cached_text:
            accumulated = cached_text
            yield f"data: {json.dumps({'type': 'text', 'content': cached_text})}\n\n"

            ended_at_ms = int(time.time() * 1000)
            debug = build_chat_debug_info(
                config=config,
                fusion=fusion,
                include_vector=bool(include_vector),
                include_sparse=bool(include_sparse),
                include_graph=bool(include_graph),
                top_k=top_k,
                sources=chunks,
                recall_plan=None,
                provider=provider_info,
            ).model_copy(
                update={
                    "llm_used": True,
                    "llm_error": None,
                    "fusion_debug": {
                        **(getattr(fusion, "last_debug", None) or {}),
                        "cache_hit": True,
                        "cache_match_type": hit.match_type,
                        "cache_similarity": float(hit.similarity),
                        "cache_namespace": "answer_generation",
                    },
                }
            )
            sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in chunks]
            done_payload: dict[str, Any] = {
                "type": "done",
                "sources": sources_json,
                "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
                "provider_response_id": None,
                "debug": debug.model_dump(mode="serialization", by_alias=True),
            }
            if conversation_id:
                done_payload["conversation_id"] = str(conversation_id)
            if run_id:
                done_payload["run_id"] = str(run_id)
            if started_at_ms is not None:
                done_payload["started_at_ms"] = int(started_at_ms)
            done_payload["ended_at_ms"] = int(ended_at_ms)
            yield f"data: {json.dumps(done_payload)}\n\n"
            return

    try:
        route = resolved_route or select_provider_route(
            config=config,
            model_override=(model_override or "").strip(),
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )

        async for delta in stream_chat_text(
            route=route,
            system_prompt=system_prompt,
            user_message=query,
            images=[],
            image_detail=str(config.chat.multimodal.image_detail or "auto"),
            temperature=temperature,
            max_tokens=int(config.chat.max_tokens),
            context_text=context_text,
            context_chunks=chunks,
            timeout_s=float(getattr(config.ui, "chat_stream_timeout", 120) or 120),
            on_provider_response_id=_capture_provider_response_id,
        ):
            accumulated += delta
            yield f"data: {json.dumps({'type': 'text', 'content': delta})}\n\n"

        if not accumulated.strip():
            raise RuntimeError("LLM stream produced no content (check provider compatibility/config)")
    except Exception as e:
        # The same typed error event the chat stream emits; no prose stands in for the
        # answer and nothing reaches the semantic cache (llm_used stays False below).
        llm_used = False
        error_detail = generation_unavailable_detail(e, operation="Answer stream generation")
        llm_error = error_detail.gateway_reason
        accumulated = ""
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
    debug = build_chat_debug_info(
        config=config,
        fusion=fusion,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        top_k=top_k,
        sources=chunks,
        recall_plan=None,
        provider=provider_info,
    ).model_copy(
        update={
            "llm_used": bool(llm_used),
            "llm_error": llm_error,
            "fusion_debug": {**(getattr(fusion, "last_debug", None) or {})},
        }
    )

    if bool(llm_used) and bool(accumulated.strip()) and float(temperature) <= float(
        config.semantic_cache.max_temperature_for_write
    ):
        cache_written = await cache_service.write(
            endpoint="answer",
            scope_key=cache_scope_key,
            query=query,
            request_fingerprint=cache_request_fingerprint,
            payload={
                "answer": accumulated,
                "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
            },
            cache_mode=normalized_cache_mode,
        )
        debug = debug.model_copy(
            update={
                "fusion_debug": {
                    **(debug.fusion_debug or {}),
                    "cache_write": bool(cache_written),
                    "cache_namespace": "answer_generation",
                }
            }
        )

    sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in chunks]
    done_event_payload: dict[str, Any] = {
        "type": "done",
        "sources": sources_json,
        "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
        "provider_response_id": provider_response_id,
        "debug": debug.model_dump(mode="serialization", by_alias=True),
    }
    if conversation_id:
        done_event_payload["conversation_id"] = str(conversation_id)
    if run_id:
        done_event_payload["run_id"] = str(run_id)
    if started_at_ms is not None:
        done_event_payload["started_at_ms"] = int(started_at_ms)
    done_event_payload["ended_at_ms"] = int(ended_at_ms)

    yield f"data: {json.dumps(done_event_payload)}\n\n"
