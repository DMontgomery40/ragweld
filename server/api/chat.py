"""Chat API endpoints with PydanticAI-powered RAG."""
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi import Query
from starlette.responses import StreamingResponse

from server.models.chat import ChatRequest, ChatResponse, Message
from server.models.tribrid_config_model import TracesLatestResponse
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config
from server.services.conversation_store import get_conversation_store
from server.services.rag import FusionProtocol, build_chat_debug_info, generate_response, stream_response
from server.services.traces import get_trace_store

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
    # Default: real tri-brid fusion over Postgres + Neo4j using per-corpus config.
    return TriBridFusion(vector=None, sparse=None, graph=None)


def set_config(config: TriBridConfig | None) -> None:
    """Set the config for dependency injection (primarily for testing)."""
    global _config
    _config = config


def set_fusion(fusion: FusionProtocol | None) -> None:
    """Set the fusion service for dependency injection (primarily for testing)."""
    global _fusion
    _fusion = fusion


@router.get("/traces/latest", response_model=TracesLatestResponse)
async def get_latest_trace(
    repo: str | None = Query(default=None, description="Optional corpus_id to filter by"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    run_id: str | None = Query(default=None, description="Optional run_id to fetch"),
) -> TracesLatestResponse:
    """Return the latest local trace (dev tooling)."""
    repo_id = (repo or corpus_id or "").strip() or None
    store = get_trace_store()
    return await store.latest(repo=repo_id, run_id=(run_id or "").strip() or None)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a chat message and return RAG-enhanced response.

    Uses PydanticAI with OpenAI Responses API (GPT-5) to generate
    contextual answers based on codebase search.
    """
    store = get_conversation_store()
    conv = store.get_or_create(request.conversation_id)
    config = _config if _config is not None else await load_scoped_config(repo_id=request.repo_id)
    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=request.repo_id,
        started_at_ms=started_at_ms,
        config=config,
    )
    if trace_enabled:
        await trace_store.add_event(
            run_id,
            kind="chat.request",
            data={
                "conversation_id": request.conversation_id,
                "corpus_id": request.repo_id,
                "include_vector": bool(request.include_vector),
                "include_sparse": bool(request.include_sparse),
                "include_graph": bool(request.include_graph),
                "top_k_override": request.top_k,
                "stream": False,
            },
        )

    try:
        response_text, sources, provider_id = await generate_response(
            message=request.message,
            repo_id=request.repo_id,
            conversation=conv,
            config=config,
            fusion=fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
        )
        ended_at_ms = int(time.time() * 1000)
        debug = build_chat_debug_info(
            config=config,
            fusion=fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=request.top_k,
            sources=sources,
        )
        if trace_enabled:
            await trace_store.add_event(
                run_id,
                kind="retrieval.fusion",
                data={
                    "fusion_debug": getattr(fusion, "last_debug", None) or {},
                    "chat_debug": debug.model_dump(mode="serialization", by_alias=True),
                    "sources": [
                        {
                            "file_path": s.file_path,
                            "start_line": int(s.start_line),
                            "end_line": int(s.end_line),
                            "score": float(s.score),
                            "source": str(s.source),
                        }
                        for s in sources
                    ],
                },
            )
            await trace_store.add_event(
                run_id,
                kind="chat.response",
                data={
                    "sources_count": len(sources),
                    "tokens_used": 0,
                },
            )
            await trace_store.end(run_id, ended_at_ms=ended_at_ms)

        # Store the exchange
        user_msg = Message(role="user", content=request.message)
        assistant_msg = Message(role="assistant", content=response_text)
        store.add_message(conv.id, user_msg, None)
        store.add_message(conv.id, assistant_msg, provider_id)

        return ChatResponse(
            run_id=run_id,
            started_at_ms=started_at_ms,
            ended_at_ms=ended_at_ms,
            debug=debug,
            conversation_id=conv.id,
            message=assistant_msg,
            sources=sources,
            tokens_used=0,  # TODO: extract from result.usage() when available
        )

    except Exception as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            await trace_store.end(run_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


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
    config = _config if _config is not None else await load_scoped_config(repo_id=request.repo_id)
    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=request.repo_id,
        started_at_ms=started_at_ms,
        config=config,
    )
    if trace_enabled:
        await trace_store.add_event(
            run_id,
            kind="chat.request",
            data={
                "conversation_id": request.conversation_id,
                "corpus_id": request.repo_id,
                "include_vector": bool(request.include_vector),
                "include_sparse": bool(request.include_sparse),
                "include_graph": bool(request.include_graph),
                "top_k_override": request.top_k,
                "stream": True,
            },
        )

    # Store the user message before streaming
    user_msg = Message(role="user", content=request.message)
    store.add_message(conv.id, user_msg, None)

    async def wrapped_stream() -> Any:
        ended_at_ms: int | None = None
        try:
            async for sse in stream_response(
                message=request.message,
                repo_id=request.repo_id,
                conversation=conv,
                config=config,
                fusion=fusion,
                include_vector=bool(request.include_vector),
                include_sparse=bool(request.include_sparse),
                include_graph=bool(request.include_graph),
                top_k=request.top_k,
                run_id=run_id,
                started_at_ms=started_at_ms,
            ):
                if trace_enabled and '"type": "done"' in sse:
                    ended_at_ms = int(time.time() * 1000)
                    try:
                        payload = json.loads(sse.replace("data: ", "").strip())
                    except Exception:
                        payload = {}
                    sources = payload.get("sources") or []
                    await trace_store.add_event(
                        run_id,
                        kind="retrieval.fusion",
                        data={
                            "fusion_debug": getattr(fusion, "last_debug", None) or {},
                            "sources": sources,
                        },
                    )
                    await trace_store.add_event(
                        run_id,
                        kind="chat.response",
                        data={
                            "sources_count": len(sources),
                        },
                    )
                yield sse
        except Exception as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            raise
        finally:
            if trace_enabled:
                await trace_store.end(run_id, ended_at_ms=ended_at_ms)

    return StreamingResponse(
        wrapped_stream(),
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
