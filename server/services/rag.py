"""RAG pipeline orchestration service using PydanticAI with OpenAI Responses API."""

import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings

from server.models.chat_config import RecallPlan
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import (
    ChatDebugInfo,
    ChatProviderInfo,
    FusionConfig,
    RerankDebugInfo,
    TriBridConfig,
)
from server.services.conversation_store import Conversation


class FusionProtocol(Protocol):
    """Protocol for fusion retrieval service."""

    async def search(
        self,
        corpus_ids: list[str],
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        ...


@dataclass
class RAGDeps:
    """Dependencies for the RAG agent."""

    fusion: FusionProtocol
    config: TriBridConfig
    repo_id: str
    include_vector: bool = True
    include_sparse: bool = True
    include_graph: bool = True
    top_k: int | None = None


def _format_chunks_for_context(chunks: list[ChunkMatch]) -> str:
    """Format chunks into context string for the LLM.

    Args:
        chunks: List of matched code chunks.

    Returns:
        Formatted string with file paths, line numbers, and content.
    """
    if not chunks:
        return "No relevant code found."

    formatted_parts = []
    for chunk in chunks:
        header = f"## {chunk.file_path}:{chunk.start_line}-{chunk.end_line}"
        if chunk.language:
            header += f" ({chunk.language})"
        formatted_parts.append(f"{header}\n```\n{chunk.content}\n```")

    return "\n\n".join(formatted_parts)


def _build_system_prompt(repo_id: str) -> str:
    """Build the system prompt for the RAG agent.

    Args:
        repo_id: The repository being queried.

    Returns:
        System prompt string.
    """
    return f"""You are a code assistant for the {repo_id} repository.

Your role is to help developers understand and work with the codebase by:
1. Using the retrieve_context tool to search for relevant code before answering
2. Providing accurate, specific answers based on the actual code
3. Always citing sources with file paths and line numbers (e.g., src/main.py:42)
4. Explaining code patterns, architecture, and implementation details

When answering questions:
- First retrieve relevant context using the tool
- Reference specific files and line numbers in your answers
- If the codebase doesn't contain relevant information, say so clearly
- Provide code examples when helpful"""


# -----------------------------------------------------------------------------
# NOTE: Chat model + prompt are config-driven (TriBridConfig is the law).
# We keep a default agent instance for compatibility, but all real request
# execution builds an agent per request using the scoped config passed in.
# -----------------------------------------------------------------------------
_DEFAULT_CONFIG = TriBridConfig()
_default_model = OpenAIResponsesModel(_DEFAULT_CONFIG.ui.chat_default_model)

rag_agent: Agent[RAGDeps, str] = Agent(
    _default_model,
    deps_type=RAGDeps,
    system_prompt=_DEFAULT_CONFIG.system_prompts.main_rag_chat,
)


@rag_agent.tool
async def retrieve_context(ctx: RunContext[RAGDeps], query: str) -> str:
    """Search the codebase for relevant code chunks.

    Args:
        ctx: Run context with dependencies.
        query: The search query to find relevant code.

    Returns:
        Formatted string with matching code chunks and their locations.
    """
    chunks = await ctx.deps.fusion.search(
        [ctx.deps.repo_id],
        query,
        ctx.deps.config.fusion,
        include_vector=ctx.deps.include_vector,
        include_sparse=ctx.deps.include_sparse,
        include_graph=ctx.deps.include_graph,
        top_k=ctx.deps.top_k,
    )
    return _format_chunks_for_context(chunks)


def _extract_sources(result: Any) -> list[ChunkMatch]:
    """Extract source chunks from agent result.

    This inspects the tool calls in the result to find the chunks
    that were retrieved during the conversation.

    Args:
        result: The agent run result.

    Returns:
        List of ChunkMatch objects used as sources.
    """
    # For now, return empty list - sources are tracked via tool call history
    # In production, you'd parse the tool call results to extract chunks
    return []


def _resolve_chat_model(config: TriBridConfig) -> OpenAIResponsesModel:
    model_name = str(getattr(config.ui, "chat_default_model", "") or "").strip()
    if not model_name:
        model_name = str(TriBridConfig().ui.chat_default_model)
    return OpenAIResponsesModel(model_name)


def _resolve_model_settings(config: TriBridConfig, prev_response_id: str) -> OpenAIResponsesModelSettings:
    # OpenAIResponsesModelSettings is a TypedDict in pydantic-ai.
    return {
        "openai_previous_response_id": prev_response_id,
        "temperature": float(config.generation.gen_temperature),
        "top_p": float(config.generation.gen_top_p),
        "max_tokens": int(config.generation.gen_max_tokens),
        "timeout": float(config.ui.chat_stream_timeout),
    }


async def generate_response(
    message: str,
    repo_id: str,
    conversation: Conversation,
    config: TriBridConfig,
    fusion: FusionProtocol,
    *,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
) -> tuple[str, list[ChunkMatch], str | None]:
    """Run the RAG agent and return response with sources.

    Args:
        message: User's query.
        repo_id: Repository to search.
        conversation: Conversation with history and provider response ID.
        config: TriBrid configuration.
        fusion: Fusion retrieval service.

    Returns:
        Tuple of (response_text, sources, provider_response_id).
    """
    deps = RAGDeps(
        fusion=fusion,
        config=config,
        repo_id=repo_id,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
    )
    collected_sources: list[ChunkMatch] = []
    seen_chunk_ids: set[str] = set()

    # Build model settings with previous response ID for conversation continuity
    # Use 'auto' if no previous response ID (for first message in conversation)
    prev_response_id: str = conversation.last_provider_response_id or "auto"
    model_settings = _resolve_model_settings(config, prev_response_id)

    # Create a fresh agent with the correct repo_id in system prompt
    model = _resolve_chat_model(config)
    agent: Agent[RAGDeps, str] = Agent(
        model,
        deps_type=RAGDeps,
        system_prompt=config.system_prompts.main_rag_chat,
    )

    # Register the tool on the fresh agent
    @agent.tool
    async def retrieve_context_inner(ctx: RunContext[RAGDeps], query: str) -> str:
        """Search the codebase for relevant code chunks."""
        chunks = await ctx.deps.fusion.search(
            [ctx.deps.repo_id],
            query,
            ctx.deps.config.fusion,
            include_vector=ctx.deps.include_vector,
            include_sparse=ctx.deps.include_sparse,
            include_graph=ctx.deps.include_graph,
            top_k=ctx.deps.top_k,
        )
        for ch in chunks:
            if ch.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(ch.chunk_id)
            collected_sources.append(ch)
        return _format_chunks_for_context(chunks)

    # Run the agent (no message_history - use openai_previous_response_id for context)
    result = await agent.run(
        message,
        deps=deps,
        model_settings=model_settings,
    )

    # Extract provider response ID for next turn (if available)
    provider_id: str | None = None
    all_messages = result.all_messages()
    if all_messages:
        last_msg = all_messages[-1]
        # Access provider_response_id if it exists
        if hasattr(last_msg, "provider_response_id"):
            provider_id = getattr(last_msg, "provider_response_id", None)

    return result.output, collected_sources, provider_id


async def stream_response(
    message: str,
    repo_id: str,
    conversation: Conversation,
    config: TriBridConfig,
    fusion: FusionProtocol,
    *,
    include_vector: bool = True,
    include_sparse: bool = True,
    include_graph: bool = True,
    top_k: int | None = None,
    run_id: str | None = None,
    started_at_ms: int | None = None,
) -> AsyncIterator[str]:
    """Stream the RAG agent response as SSE events.

    Args:
        message: User's query.
        repo_id: Repository to search.
        conversation: Conversation with history.
        config: TriBrid configuration.
        fusion: Fusion retrieval service.

    Yields:
        SSE-formatted event strings.
    """
    deps = RAGDeps(
        fusion=fusion,
        config=config,
        repo_id=repo_id,
        include_vector=include_vector,
        include_sparse=include_sparse,
        include_graph=include_graph,
        top_k=top_k,
    )
    collected_sources: list[ChunkMatch] = []
    seen_chunk_ids: set[str] = set()
    accumulated_text = ""

    # Create a fresh agent with the correct system prompt + model
    model = _resolve_chat_model(config)
    agent: Agent[RAGDeps, str] = Agent(
        model,
        deps_type=RAGDeps,
        system_prompt=config.system_prompts.main_rag_chat,
    )

    # Register the tool on the fresh agent
    @agent.tool
    async def retrieve_context_stream(ctx: RunContext[RAGDeps], query: str) -> str:
        """Search the codebase for relevant code chunks."""
        chunks = await ctx.deps.fusion.search(
            [ctx.deps.repo_id],
            query,
            ctx.deps.config.fusion,
            include_vector=ctx.deps.include_vector,
            include_sparse=ctx.deps.include_sparse,
            include_graph=ctx.deps.include_graph,
            top_k=ctx.deps.top_k,
        )
        for ch in chunks:
            if ch.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(ch.chunk_id)
            collected_sources.append(ch)
        return _format_chunks_for_context(chunks)

    # Build model settings with previous response ID
    prev_response_id: str = conversation.last_provider_response_id or "auto"
    model_settings = _resolve_model_settings(config, prev_response_id)

    try:
        async with agent.run_stream(
            message,
            deps=deps,
            model_settings=model_settings,
        ) as response:
            # IMPORTANT: pydantic-ai's stream_text yields cumulative text by default.
            # We want deltas for SSE so the UI can safely append without duplication.
            async for delta in response.stream_text(delta=True):
                accumulated_text += delta
                event_data = json.dumps({"type": "text", "content": delta})
                yield f"data: {event_data}\n\n"

            # Best-effort provider response ID for conversation continuity
            provider_id: str | None = None
            all_messages = response.all_messages()
            if all_messages:
                last_msg = all_messages[-1]
                if hasattr(last_msg, "provider_response_id"):
                    provider_id = getattr(last_msg, "provider_response_id", None)
            if provider_id:
                conversation.last_provider_response_id = provider_id

            # Persist assistant message in conversation history
            from server.models.chat import Message  # local import to avoid module import cycles
            from server.services.conversation_store import get_conversation_store

            store = get_conversation_store()
            store.add_message(conversation.id, Message(role="assistant", content=accumulated_text), provider_id)

            # Final event with sources + conversation_id
            sources_json = [s.model_dump(mode="serialization", by_alias=True) for s in collected_sources]

            done_payload: dict[str, Any] = {
                "type": "done",
                "conversation_id": conversation.id,
                "sources": sources_json,
            }

            if run_id:
                ended_at_ms = int(time.time() * 1000)
                debug = build_chat_debug_info(
                    config=config,
                    fusion=fusion,
                    include_vector=include_vector,
                    include_sparse=include_sparse,
                    include_graph=include_graph,
                    top_k=top_k,
                    sources=collected_sources,
                )
                done_payload.update(
                    {
                        "run_id": run_id,
                        "started_at_ms": int(started_at_ms or ended_at_ms),
                        "ended_at_ms": int(ended_at_ms),
                        "debug": debug.model_dump(mode="serialization", by_alias=True),
                    }
                )

            done_data = json.dumps(
                done_payload
            )
            yield f"data: {done_data}\n\n"

    except Exception as e:
        error_data = json.dumps({"type": "error", "message": str(e)})
        yield f"data: {error_data}\n\n"


def build_chat_debug_info(
    *,
    config: TriBridConfig,
    fusion: Any,
    include_vector: bool,
    include_sparse: bool,
    include_graph: bool,
    top_k: int | None,
    sources: list[ChunkMatch],
    recall_plan: RecallPlan | None = None,
    provider: ChatProviderInfo | None = None,
) -> ChatDebugInfo:
    """Build ChatDebugInfo from fusion debug + config."""
    fusion_debug: dict[str, Any] = getattr(fusion, "last_debug", None) or {}

    scores = [float(s.score) for s in sources if s.score is not None]
    top1 = scores[0] if scores else None
    top5 = scores[:5]
    avg5 = (sum(top5) / len(top5)) if top5 else None

    method = str(getattr(config.fusion, "method", "") or "").strip().lower()
    fusion_method: str | None = method if method in {"rrf", "weighted"} else None

    # Determine which legs actually contributed (requested + enabled + non-empty)
    vector_ok = bool(include_vector) and bool(fusion_debug.get("fusion_vector_enabled")) and int(
        fusion_debug.get("fusion_vector_results") or 0
    ) > 0
    sparse_ok = bool(include_sparse) and bool(fusion_debug.get("fusion_sparse_enabled")) and int(
        fusion_debug.get("fusion_sparse_results") or 0
    ) > 0
    graph_ok = bool(include_graph) and bool(fusion_debug.get("fusion_graph_enabled")) and int(
        fusion_debug.get("fusion_graph_hydrated_chunks") or 0
    ) > 0
    legs_used = int(vector_ok) + int(sparse_ok) + int(graph_ok)

    confidence: float | None = None
    if top1 is not None and fusion_method == "rrf":
        k = int(getattr(config.fusion, "rrf_k", 60) or 60)
        denom = float(legs_used) / float(k + 1) if legs_used > 0 else 0.0
        if denom > 0.0:
            confidence = max(0.0, min(1.0, float(top1) / denom))
    elif top1 is not None and fusion_method == "weighted":
        confidence = max(0.0, min(1.0, float(top1)))

    # Cast fusion_method to the expected Literal type
    typed_fusion_method: Literal["rrf", "weighted"] | None = None
    if fusion_method == "rrf":
        typed_fusion_method = "rrf"
    elif fusion_method == "weighted":
        typed_fusion_method = "weighted"

    # Safely extract int values from fusion_debug
    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    # Best-effort reranker status (prefer non-Recall/RAG retrieval when available).
    rerank: RerankDebugInfo | None = None
    try:
        rag_debug: dict[str, Any] = {}
        if isinstance(fusion_debug, dict):
            candidate = fusion_debug.get("chat_rag_fusion")
            if isinstance(candidate, dict):
                rag_debug = candidate
            else:
                rag_debug = fusion_debug

        if isinstance(rag_debug, dict) and (
            "rerank_mode" in rag_debug
            or "rerank_enabled" in rag_debug
            or "rerank_ok" in rag_debug
            or "rerank_error" in rag_debug
            or "rerank_skipped_reason" in rag_debug
        ):
            enabled = bool(rag_debug.get("rerank_enabled"))
            mode = str(rag_debug.get("rerank_mode") or "none")
            ok = bool(rag_debug.get("rerank_ok", True))
            applied = bool(rag_debug.get("rerank_applied", False))

            skipped_reason_raw = rag_debug.get("rerank_skipped_reason")
            skipped_reason: str | None
            if isinstance(skipped_reason_raw, str):
                skipped_reason = skipped_reason_raw.strip() or None
            else:
                skipped_reason = None

            error_raw = rag_debug.get("rerank_error")
            error: str | None
            if isinstance(error_raw, str):
                error = error_raw.strip() or None
            else:
                error = None

            candidates_reranked = _safe_int(rag_debug.get("rerank_candidates_reranked")) or 0
            candidates_reranked = int(max(0, candidates_reranked))

            config_corpus_raw = rag_debug.get("rerank_config_corpus_id")
            config_corpus_id: str | None
            if isinstance(config_corpus_raw, str):
                config_corpus_id = config_corpus_raw.strip() or None
            else:
                config_corpus_id = None

            # Summarize error for user-facing UI (when available).
            error_message: str | None = None
            debug_trace_id: str | None = None
            if error:
                # Common in Cohere errors: "x-debug-trace-id': '...'"
                m = re.search(r"x-debug-trace-id['\"]?:\\s*['\"]([0-9a-fA-F]+)['\"]", error)
                if m:
                    debug_trace_id = str(m.group(1))

                # Common in provider bodies: "message": "..."
                m = re.search(r"\"message\"\\s*:\\s*\"([^\"]+)\"", error)
                if m:
                    error_message = str(m.group(1)).strip() or None
                else:
                    # Python dict repr: 'message': "..."
                    m = re.search(r"'message'\\s*:\\s*\"([^\"]+)\"", error)
                    if m:
                        error_message = str(m.group(1)).strip() or None

                if not error_message:
                    error_message = error if len(error) <= 240 else f"{error[:240]}…"

            rerank = RerankDebugInfo(
                enabled=bool(enabled),
                mode=mode,
                ok=bool(ok),
                applied=bool(applied),
                candidates_reranked=candidates_reranked,
                skipped_reason=skipped_reason,
                error=error,
                error_message=error_message,
                debug_trace_id=debug_trace_id,
                config_corpus_id=config_corpus_id,
            )
    except Exception:
        rerank = None

    return ChatDebugInfo(
        confidence=confidence,
        provider=provider,
        recall_plan=recall_plan,
        include_vector=bool(include_vector),
        include_sparse=bool(include_sparse),
        include_graph=bool(include_graph),
        vector_enabled=(bool(fusion_debug.get("fusion_vector_enabled")) if "fusion_vector_enabled" in fusion_debug else None),
        sparse_enabled=(bool(fusion_debug.get("fusion_sparse_enabled")) if "fusion_sparse_enabled" in fusion_debug else None),
        graph_enabled=(bool(fusion_debug.get("fusion_graph_enabled")) if "fusion_graph_enabled" in fusion_debug else None),
        fusion_method=typed_fusion_method,
        rrf_k=(int(getattr(config.fusion, "rrf_k", 60)) if typed_fusion_method == "rrf" else None),
        vector_weight=(float(getattr(config.fusion, "vector_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        sparse_weight=(float(getattr(config.fusion, "sparse_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        graph_weight=(float(getattr(config.fusion, "graph_weight", 0.0)) if typed_fusion_method == "weighted" else None),
        normalize_scores=(bool(getattr(config.fusion, "normalize_scores", False)) if typed_fusion_method == "weighted" else None),
        final_k_used=int(top_k or config.retrieval.final_k),
        vector_results=_safe_int(fusion_debug.get("fusion_vector_results")) if "fusion_vector_results" in fusion_debug else None,
        sparse_results=_safe_int(fusion_debug.get("fusion_sparse_results")) if "fusion_sparse_results" in fusion_debug else None,
        graph_entity_hits=_safe_int(fusion_debug.get("fusion_graph_entity_hits")) if "fusion_graph_entity_hits" in fusion_debug else None,
        graph_hydrated_chunks=_safe_int(fusion_debug.get("fusion_graph_hydrated_chunks")) if "fusion_graph_hydrated_chunks" in fusion_debug else None,
        final_results=len(sources),
        top1_score=(float(top1) if top1 is not None else None),
        avg5_score=(float(avg5) if avg5 is not None else None),
        conf_top1_thresh=float(config.retrieval.conf_top1),
        conf_avg5_thresh=float(config.retrieval.conf_avg5),
        rerank=rerank,
        fusion_debug=fusion_debug,
    )
