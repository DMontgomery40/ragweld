"""Chat API endpoints with PydanticAI-powered RAG."""

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from server.models.chat import ChatRequest, ChatResponse, Message
from server.models.tribrid_config_model import TriBridConfig
from server.services.conversation_store import get_conversation_store
from server.services.rag import FusionProtocol, generate_response, stream_response

router = APIRouter(tags=["chat"])


# Dependency holders (can be overridden for testing)
_config: TriBridConfig | None = None
_fusion: FusionProtocol | None = None


def get_config() -> TriBridConfig:
    """Get the current config. Override with set_config() for testing."""
    if _config is not None:
        return _config
    # Default config - LAW provides all defaults via default_factory
    return TriBridConfig()


def get_fusion() -> FusionProtocol:
    """Get the fusion retrieval service. Override with set_fusion() for testing."""
    if _fusion is not None:
        return _fusion
    raise RuntimeError(
        "Fusion service not initialized. Call set_fusion() or configure dependencies."
    )


def set_config(config: TriBridConfig | None) -> None:
    """Set the config for dependency injection (primarily for testing)."""
    global _config
    _config = config


def set_fusion(fusion: FusionProtocol | None) -> None:
    """Set the fusion service for dependency injection (primarily for testing)."""
    global _fusion
    _fusion = fusion


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a chat message and return RAG-enhanced response.

    Uses PydanticAI with OpenAI Responses API (GPT-5) to generate
    contextual answers based on codebase search.
    """
    store = get_conversation_store()
    conv = store.get_or_create(request.conversation_id)
    config = get_config()
    fusion = get_fusion()

    try:
        response_text, sources, provider_id = await generate_response(
            message=request.message,
            repo_id=request.repo_id,
            conversation=conv,
            config=config,
            fusion=fusion,
        )

        # Store the exchange
        user_msg = Message(role="user", content=request.message)
        assistant_msg = Message(role="assistant", content=response_text)
        store.add_message(conv.id, user_msg, None)
        store.add_message(conv.id, assistant_msg, provider_id)

        return ChatResponse(
            conversation_id=conv.id,
            message=assistant_msg,
            sources=sources,
            tokens_used=0,  # TODO: extract from result.usage() when available
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream a chat response using Server-Sent Events.

    Returns SSE events with:
    - type: "text" - content chunks as they arrive
    - type: "done" - final event with sources
    - type: "error" - if something goes wrong
    """
    store = get_conversation_store()
    conv = store.get_or_create(request.conversation_id)
    config = get_config()
    fusion = get_fusion()

    # Store the user message before streaming
    user_msg = Message(role="user", content=request.message)
    store.add_message(conv.id, user_msg, None)

    return StreamingResponse(
        stream_response(
            message=request.message,
            repo_id=request.repo_id,
            conversation=conv,
            config=config,
            fusion=fusion,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history/{conversation_id}", response_model=list[Message])
async def get_chat_history(conversation_id: str) -> list[Message]:
    """Get the message history for a conversation."""
    store = get_conversation_store()
    messages = store.get_messages(conversation_id)
    return messages


@router.delete("/chat/history/{conversation_id}")
async def clear_chat_history(conversation_id: str) -> dict[str, Any]:
    """Clear a conversation's history."""
    store = get_conversation_store()
    cleared = store.clear(conversation_id)
    if not cleared:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return {"status": "cleared", "conversation_id": conversation_id}
