"""RAG pipeline orchestration service using PydanticAI with OpenAI Responses API."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings

from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, TriBridConfig
from server.services.conversation_store import Conversation


class FusionProtocol(Protocol):
    """Protocol for fusion retrieval service."""

    async def search(
        self,
        repo_id: str,
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
        ctx.deps.repo_id,
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
            ctx.deps.repo_id,
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
            ctx.deps.repo_id,
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
            async for text in response.stream_text():
                accumulated_text += text
                event_data = json.dumps({"type": "text", "content": text})
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
            done_data = json.dumps(
                {
                    "type": "done",
                    "conversation_id": conversation.id,
                    "sources": sources_json,
                }
            )
            yield f"data: {done_data}\n\n"

    except Exception as e:
        error_data = json.dumps({"type": "error", "message": str(e)})
        yield f"data: {error_data}\n\n"
