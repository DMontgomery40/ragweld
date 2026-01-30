"""RAG pipeline orchestration service using PydanticAI with OpenAI Responses API."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings

from server.models.chat import Message
from server.models.tribrid_config_model import FusionConfig, TriBridConfig
from server.models.retrieval import ChunkMatch
from server.services.conversation_store import Conversation


class FusionProtocol(Protocol):
    """Protocol for fusion retrieval service."""

    async def search(
        self, repo_id: str, query: str, config: FusionConfig
    ) -> list[ChunkMatch]:
        ...


@dataclass
class RAGDeps:
    """Dependencies for the RAG agent."""

    fusion: FusionProtocol
    config: TriBridConfig
    repo_id: str


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


# Create the agent with OpenAI Responses API (GPT-5)
_model = OpenAIResponsesModel("gpt-5")

rag_agent: Agent[RAGDeps, str] = Agent(
    _model,
    deps_type=RAGDeps,
    system_prompt=_build_system_prompt("{repo_id}"),  # Placeholder, overridden at runtime
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


async def generate_response(
    message: str,
    repo_id: str,
    conversation: Conversation,
    config: TriBridConfig,
    fusion: FusionProtocol,
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
    deps = RAGDeps(fusion=fusion, config=config, repo_id=repo_id)

    # Build model settings with previous response ID for conversation continuity
    # Use 'auto' if no previous response ID (for first message in conversation)
    prev_response_id: str = conversation.last_provider_response_id or "auto"
    model_settings = OpenAIResponsesModelSettings(
        openai_previous_response_id=prev_response_id,
    )

    # Create a fresh agent with the correct repo_id in system prompt
    agent: Agent[RAGDeps, str] = Agent(
        _model,
        deps_type=RAGDeps,
        system_prompt=_build_system_prompt(repo_id),
    )

    # Register the tool on the fresh agent
    @agent.tool
    async def retrieve_context_inner(ctx: RunContext[RAGDeps], query: str) -> str:
        """Search the codebase for relevant code chunks."""
        chunks = await ctx.deps.fusion.search(
            ctx.deps.repo_id,
            query,
            ctx.deps.config.fusion,
        )
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

    sources = _extract_sources(result)
    return result.output, sources, provider_id


async def stream_response(
    message: str,
    repo_id: str,
    conversation: Conversation,
    config: TriBridConfig,
    fusion: FusionProtocol,
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
    deps = RAGDeps(fusion=fusion, config=config, repo_id=repo_id)

    # Create a fresh agent with the correct repo_id in system prompt
    agent: Agent[RAGDeps, str] = Agent(
        _model,
        deps_type=RAGDeps,
        system_prompt=_build_system_prompt(repo_id),
    )

    # Register the tool on the fresh agent
    @agent.tool
    async def retrieve_context_stream(ctx: RunContext[RAGDeps], query: str) -> str:
        """Search the codebase for relevant code chunks."""
        chunks = await ctx.deps.fusion.search(
            ctx.deps.repo_id,
            query,
            ctx.deps.config.fusion,
        )
        return _format_chunks_for_context(chunks)

    # Build model settings with previous response ID
    prev_response_id: str = conversation.last_provider_response_id or "auto"
    model_settings = OpenAIResponsesModelSettings(
        openai_previous_response_id=prev_response_id,
    )

    try:
        async with agent.run_stream(
            message,
            deps=deps,
            model_settings=model_settings,
        ) as response:
            async for text in response.stream_text():
                event_data = json.dumps({"type": "text", "content": text})
                yield f"data: {event_data}\n\n"

            # Final event with sources (empty for now since we can't extract from stream)
            done_data = json.dumps({
                "type": "done",
                "sources": [],
            })
            yield f"data: {done_data}\n\n"

    except Exception as e:
        error_data = json.dumps({"type": "error", "message": str(e)})
        yield f"data: {error_data}\n\n"
