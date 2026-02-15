from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, cast

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChatDebugInfo, ChatProviderInfo, TriBridConfig
from server.services.rag import FusionProtocol, build_chat_debug_info


def _safe_error_message(e: Exception, *, max_len: int = 400) -> str:
    # Best-effort redaction; keep debugging useful without leaking secrets.
    msg = str(e) or type(e).__name__
    msg = re.sub(r"(sk-[A-Za-z0-9_\\-]{10,})", "sk-REDACTED", msg)
    msg = re.sub(r"(Bearer\\s+)[A-Za-z0-9_.\\-]{10,}", r"\\1REDACTED", msg)
    msg = msg.replace("\n", " ").replace("\r", " ").strip()
    return msg[: int(max_len)]


def _format_retrieval_only_answer(*, query: str, corpus_id: str, chunks: list[ChunkMatch]) -> str:
    # Deterministic, LLM-free fallback that still gives the user something actionable.
    if not chunks:
        return (
            "No LLM is available and retrieval returned no matches.\n\n"
            f"Query: {query}\n"
            f"Corpus: {corpus_id}\n"
            "Tip: verify the corpus is indexed and that at least one retrieval leg is enabled."
        )

    lines: list[str] = [
        "No LLM is available. Returning retrieval-only results.",
        "",
        f"Query: {query}",
        f"Corpus: {corpus_id}",
        "",
        "Top matching sources:",
    ]
    for i, ch in enumerate(chunks[: min(len(chunks), 8)]):
        loc = f"{ch.file_path}:{int(ch.start_line)}-{int(ch.end_line)}"
        score = f"{float(ch.score):.4f}" if ch.score is not None else "0.0000"
        snippet = (ch.content or "").strip()
        snippet = re.sub(r"\\s+", " ", snippet)[:220]
        lines.append(f"{i+1}. {loc} (score {score})")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines).strip()


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
) -> tuple[list[ChunkMatch], dict[str, Any]]:
    if not query.strip() or not str(corpus_id or "").strip():
        return ([], {"retrieval_error": "Missing query or corpus_id"})

    try:
        chunks = await fusion.search(
            [str(corpus_id)],
            query,
            config.fusion,
            include_vector=bool(include_vector),
            include_sparse=bool(include_sparse),
            include_graph=bool(include_graph),
            top_k=top_k,
        )
        retrieval_debug: dict[str, Any] = getattr(fusion, "last_debug", None) or {}
        return (chunks, retrieval_debug)
    except Exception as e:
        return (
            [],
            {
                "retrieval_error": _safe_error_message(e),
                "retrieval_error_kind": type(e).__name__,
            },
        )


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
) -> tuple[str, list[ChunkMatch], ChatProviderInfo | None, ChatDebugInfo]:
    chunks, _ = await retrieve_best_effort(
        query=query,
        corpus_id=corpus_id,
        config=config,
        fusion=fusion,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
    )

    provider_info: ChatProviderInfo | None = None
    llm_used = True
    llm_error: str | None = None

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

    answer_text: str
    try:
        route = select_provider_route(
            chat_config=config.chat,
            model_override=(model_override or "").strip(),
            openai_base_url_override=config.generation.openai_base_url,
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )
        temperature = float(config.chat.temperature_no_retrieval) if not chunks else float(config.chat.temperature)

        answer_text, _provider_id = await generate_chat_text(
            route=route,
            openrouter_cfg=config.chat.openrouter,
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
        answer_text = (answer_text or "").strip()
        if not answer_text:
            raise RuntimeError("LLM returned an empty response")
    except Exception as e:
        llm_used = False
        llm_error = _safe_error_message(e)
        answer_text = _format_retrieval_only_answer(query=query, corpus_id=corpus_id, chunks=chunks)

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
    ).model_copy(update={"llm_used": bool(llm_used), "llm_error": llm_error})

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
    conversation_id: str | None = None,
    run_id: str | None = None,
    started_at_ms: int | None = None,
) -> AsyncIterator[str]:
    chunks, _ = await retrieve_best_effort(
        query=query,
        corpus_id=corpus_id,
        config=config,
        fusion=fusion,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
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

    try:
        route = select_provider_route(
            chat_config=config.chat,
            model_override=(model_override or "").strip(),
            openai_base_url_override=config.generation.openai_base_url,
        )
        provider_info = ChatProviderInfo(
            kind=cast(Any, route.kind),
            provider_name=str(route.provider_name),
            model=str(route.model),
            base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
        )
        temperature = float(config.chat.temperature_no_retrieval) if not chunks else float(config.chat.temperature)

        async for delta in stream_chat_text(
            route=route,
            openrouter_cfg=config.chat.openrouter,
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
            msg = "Error: LLM stream produced no content (check provider compatibility/config)"
            accumulated = msg
            yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"
    except Exception as e:
        llm_used = False
        llm_error = _safe_error_message(e)
        msg = _format_retrieval_only_answer(query=query, corpus_id=corpus_id, chunks=chunks)
        accumulated = msg
        yield f"data: {json.dumps({'type': 'text', 'content': msg})}\n\n"

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
    ).model_copy(update={"llm_used": bool(llm_used), "llm_error": llm_error})

    sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in chunks]
    done_payload: dict[str, Any] = {
        "type": "done",
        "sources": sources_json,
        "provider": provider_info.model_dump(mode="serialization") if provider_info is not None else None,
        "provider_response_id": provider_response_id,
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
