"""Request accounting across real validation and cancellation boundaries."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from fastapi import Response
from prometheus_client import REGISTRY

from server.api.chat import chat, chat_stream, set_config
from server.models.chat import ChatRequest
from server.models.tribrid_config_model import TriBridConfig
from server.services.traces import get_trace_store
from server.services.conversation_store import get_conversation_store


MODEL = "openai.gpt-6-luna"
QUESTION = "Which function stores configuration changes in Ragweld?"


def _requests(outcome: str) -> float:
    return REGISTRY.get_sample_value(
        "tribrid_chat_requests_total", {"model": MODEL, "outcome": outcome}
    ) or 0.0


@pytest.fixture
def lifecycle_config():
    config = TriBridConfig()
    config.chat.litellm.default_model = MODEL
    config.chat.recall.enabled = False
    config.semantic_cache.enabled = False
    config.chat.multimodal.vision_enabled = False
    config.tracing.tracing_enabled = True
    config.tracing.tracing_mode = "local"
    config.tracing.trace_sampling_rate = 1.0
    set_config(config)
    try:
        yield config
    finally:
        set_config(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
async def test_image_validation_failure_counts_one_failed_request(
    client: AsyncClient, lifecycle_config: TriBridConfig, route: str
) -> None:
    before = _requests("retrieval_error")
    response = await client.post(
        route,
        json={
            "message": QUESTION,
            "sources": {"corpus_ids": []},
            "images": [{"mime_type": "image/png", "base64": "AA=="}],
        },
    )
    assert response.status_code == 400
    assert "Vision is disabled" in response.text
    assert _requests("retrieval_error") - before == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/api/chat", "/api/chat/stream"])
async def test_cancel_during_trace_setup_counts_disconnect(
    client: AsyncClient, lifecycle_config: TriBridConfig, route: str
) -> None:
    # Hold the actual trace-store lock so cancellation happens before the handler
    # starts, without replacing either the store or the generation pipeline.
    trace_store = get_trace_store()
    before = _requests("client_disconnect")
    await trace_store._lock.acquire()
    request = ChatRequest(
        message=QUESTION,
        sources={"corpus_ids": []},
        conversation_id=f"pytest-lifecycle-{uuid.uuid4().hex}",
    )
    task = asyncio.create_task(
        chat(request, Response()) if route == "/api/chat" else chat_stream(request)
    )
    try:
        async with asyncio.timeout(5):
            while not trace_store._lock._waiters:
                if task.done():
                    await task
                    pytest.fail("Request completed before reaching trace setup")
                await asyncio.sleep(0.001)
        task.cancel()
        trace_store._lock.release()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if trace_store._lock.locked():
            trace_store._lock.release()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert _requests("client_disconnect") - before == 1


@pytest.mark.asyncio
async def test_stream_closed_after_status_counts_disconnect(
    client: AsyncClient, lifecycle_config: TriBridConfig
) -> None:
    before = _requests("client_disconnect")
    response = await chat_stream(ChatRequest(message=QUESTION, sources={"corpus_ids": []}))
    first = await anext(response.body_iterator)
    assert '"type": "status"' in first
    await response.body_iterator.aclose()
    assert _requests("client_disconnect") - before == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("close_boundary", ["unstarted_body", "response_start", "immediate_disconnect"])
async def test_stream_disconnect_before_first_body_finalizes_once(
    client: AsyncClient, lifecycle_config: TriBridConfig, close_boundary: str
) -> None:
    """Exercise the ASGI disconnect boundary without replacing the handler or stores."""
    before = _requests("client_disconnect")
    response = await chat_stream(ChatRequest(message=QUESTION, sources={"corpus_ids": []}))
    latest = await get_trace_store().latest()
    assert latest.trace is not None and latest.trace.ended_at_ms is None
    run_id = latest.run_id
    if close_boundary == "unstarted_body":
        await response.body_iterator.aclose()
    else:
        headers_attempted = asyncio.Event()

        async def receive():
            await headers_attempted.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            assert message["type"] == "http.response.start"
            headers_attempted.set()
            if close_boundary == "response_start":
                raise OSError("Client closed the connection before response headers")
            await asyncio.Event().wait()

        if close_boundary == "response_start":
            from starlette.requests import ClientDisconnect

            with pytest.raises(ClientDisconnect):
                await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        else:
            await response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send)
    # Repeated explicit cleanup must not count or close the trace twice.
    await response.body_iterator.aclose()
    assert _requests("client_disconnect") - before == 1
    closed = await get_trace_store().latest(run_id=run_id)
    assert closed.trace is not None and closed.trace.ended_at_ms is not None
    outcomes = [event.data["outcome"] for event in closed.trace.events if event.kind == "chat.outcome"]
    assert outcomes == ["client_disconnect"]


@pytest.mark.asyncio
@pytest.mark.requires_model_gateway
@pytest.mark.parametrize("discard_conversation", [False, True])
async def test_generation_counts_success_only_after_conversation_commit(
    client: AsyncClient, lifecycle_config: TriBridConfig, discard_conversation: bool
) -> None:
    """Use a real model and the pytest process's own in-memory conversation store."""
    from fastapi import HTTPException

    store = get_conversation_store()
    conversation_id = f"pytest-lifecycle-{uuid.uuid4().hex}"
    before_ok = _requests("ok")
    before_error = _requests("gateway_error")
    request = ChatRequest(
        message=QUESTION, sources={"corpus_ids": []}, conversation_id=conversation_id
    )
    task = asyncio.create_task(chat(request, Response()))
    try:
        if discard_conversation:
            async with asyncio.timeout(10):
                while store.get(conversation_id) is None:
                    if task.done():
                        await task
                        pytest.fail("Chat finished before its conversation was created")
                    await asyncio.sleep(0.001)
            assert store.clear(conversation_id)
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == 500
            assert "Conversation not found" in caught.value.detail
            assert _requests("ok") - before_ok == 0
            assert _requests("gateway_error") - before_error == 1
        else:
            result = await task
            assert result.message.content.strip()
            assert [message.role for message in store.get_messages(conversation_id)] == ["user", "assistant"]
            assert _requests("ok") - before_ok == 1
            assert _requests("gateway_error") - before_error == 0
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        store.clear(conversation_id)


@pytest.mark.asyncio
@pytest.mark.requires_model_gateway
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("cancel_boundary", ["waiting_terminal_lock", "terminal_committed"])
async def test_cancel_during_success_trace_close_keeps_committed_outcome(
    client: AsyncClient, lifecycle_config: TriBridConfig, streaming: bool, cancel_boundary: str
) -> None:
    """Cancel between real trace writes after the real gateway commits an answer."""
    trace_store = get_trace_store()
    conversation_store = get_conversation_store()
    conversation_id = f"pytest-lifecycle-{uuid.uuid4().hex}"
    request = ChatRequest(
        message=QUESTION, sources={"corpus_ids": []}, conversation_id=conversation_id
    )
    before_ok = _requests("ok")
    before_disconnect = _requests("client_disconnect")
    response = None

    async def consume_request() -> None:
        nonlocal response
        if streaming:
            response = await chat_stream(request)
            async for _ in response.body_iterator:
                pass
        else:
            await chat(request, Response())

    await trace_store._lock.acquire()
    task = asyncio.create_task(consume_request())
    run_id = None
    try:
        async with asyncio.timeout(90):
            while True:
                # Hand the real FIFO lock to exactly one trace operation, then
                # reacquire ahead of its next operation to inspect the boundary.
                while not trace_store._lock._waiters:
                    if task.done():
                        await task
                        pytest.fail("Chat completed before reaching success trace closure")
                    await asyncio.sleep(0.001)
                trace_store._lock.release()
                await trace_store._lock.acquire()
                for candidate in trace_store._traces.values():
                    if any(
                        event.kind == "chat.request"
                        and event.data.get("conversation_id") == conversation_id
                        for event in candidate.events
                    ):
                        pending = response._stream.ag_await if response is not None else task.get_coro()
                        waiting_for_end = False
                        while pending is not None:
                            code = getattr(pending, "cr_code", None)
                            if code is not None and code.co_name == "end":
                                waiting_for_end = True
                            pending = getattr(pending, "cr_await", None) or getattr(pending, "ag_await", None)
                        at_boundary = (
                            waiting_for_end if cancel_boundary == "waiting_terminal_lock"
                            else any(event.kind == "chat.outcome" for event in candidate.events)
                        )
                        if at_boundary:
                            run_id = candidate.run_id
                            break
                if run_id is not None:
                    break
            assert [message.role for message in conversation_store.get_messages(conversation_id)] == [
                "user", "assistant"
            ]
            cancelled = task.cancel()
            await asyncio.sleep(0)
            trace_store._lock.release()
            if cancelled:
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await task
        if response is not None:
            await response.body_iterator.aclose()
        closed = await trace_store.latest(run_id=run_id)
        assert closed.trace is not None and closed.trace.ended_at_ms is not None
        outcomes = [event.data["outcome"] for event in closed.trace.events if event.kind == "chat.outcome"]
        if cancel_boundary == "waiting_terminal_lock":
            assert cancelled
            assert outcomes == ["client_disconnect"]
            assert _requests("ok") - before_ok == 0
            assert _requests("client_disconnect") - before_disconnect == 1
        else:
            assert outcomes == ["ok"]
            assert _requests("ok") - before_ok == 1
            assert _requests("client_disconnect") - before_disconnect == 0
    finally:
        if trace_store._lock.locked():
            trace_store._lock.release()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if response is not None:
            await response.body_iterator.aclose()
        conversation_store.clear(conversation_id)
