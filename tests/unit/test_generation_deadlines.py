"""Generation deadlines over real sockets, including stream task handoff."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from server.chat.generation import ChatStreamDelta, generate_chat_text, stream_chat_text
from server.chat.provider_router import ProviderRoute
from server.gateway_catalog import warm_gateway_catalog

QUERY = "Which figure shows lunar module pitch attitude during powered descent?"
ANSWER = "Figure 5-5 shows pitch attitude during powered descent."


@pytest.fixture(autouse=True)
def _warm_catalog() -> None:
    warm_gateway_catalog()


@dataclass
class _Gateway:
    tick_s: float = 0.0
    status: int = 200
    release: asyncio.Event | None = None
    received: asyncio.Event = field(default_factory=asyncio.Event)
    disconnected: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        watch: asyncio.Task[Any] | None = None
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            lines = headers.decode().split("\r\n")
            assert lines[0] == "POST /v1/chat/completions HTTP/1.1"
            length = next(int(line.split(":", 1)[1]) for line in lines if line.lower().startswith("content-length:"))
            payload = json.loads(await reader.readexactly(length))
            assert payload["messages"][-1]["content"] == QUERY
            assert payload["model"] == "openai.gpt-6-luna"
            self.received.set()
            watch = asyncio.create_task(reader.read())
            watch.add_done_callback(lambda _task: self.disconnected.set())
            if self.release is not None:
                await self.release.wait()
            if self.status != 200:
                raw = json.dumps({"error": {"message": "Gateway has no serving capacity."}}).encode()
                parts = [raw[start : start + 8] for start in range(0, len(raw), 8)]
            elif payload["stream"]:
                parts = [
                    ("data: " + json.dumps({"choices": [{"delta": {"content": word + " "}}]}) + "\n\n").encode()
                    for word in ANSWER.split()
                ] + [b"data: [DONE]\n\n"]
            else:
                raw = json.dumps({"choices": [{"message": {"content": ANSWER}}]}).encode()
                parts = [raw[start : start + 8] for start in range(0, len(raw), 8)]
            raw_headers = (
                f"HTTP/1.1 {self.status} Response\r\n"
                f"Content-Length: {sum(map(len, parts))}\r\n"
                "Content-Type: text/event-stream\r\nConnection: close\r\n\r\n"
            )
            writer.write(raw_headers.encode())
            await writer.drain()
            for part in parts:
                await asyncio.sleep(self.tick_s)
                writer.write(part)
                await writer.drain()
            await watch
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            if watch is not None:
                watch.cancel()
                await asyncio.gather(watch, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)


@asynccontextmanager
async def _gateway(**options: Any) -> AsyncIterator[tuple[dict[str, Any], _Gateway]]:
    gateway = _Gateway(**options)
    server = await asyncio.start_server(gateway.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    kwargs = {
        "route": ProviderRoute(kind="litellm", provider_name="LiteLLM", model="openai.gpt-6-luna",
                               base_url=f"http://127.0.0.1:{port}/v1", api_key="deadline-fixture-key"),
        "system_prompt": "Answer the lunar module document question from its figure description.",
        "user_message": QUERY,
        "images": [],
        "temperature": 0,
        "max_tokens": 64,
        "context_chunks": [],
        "timeout_s": 0.5,
    }
    try:
        async with server:
            yield kwargs, gateway
    finally:
        tasks = list(gateway.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _consume(stream: AsyncIterator[ChatStreamDelta]) -> list[ChatStreamDelta]:
    return [delta async for delta in stream]


@pytest.mark.asyncio
async def test_nonstream_trickling_body_expires_and_closes_the_socket() -> None:
    async with _gateway(tick_s=0.1) as (kwargs, gateway):
        started = asyncio.get_running_loop().time()
        with pytest.raises(TimeoutError):
            await generate_chat_text(**kwargs)
        assert asyncio.get_running_loop().time() - started < 0.9
        await asyncio.wait_for(gateway.disconnected.wait(), timeout=0.5)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 503])
async def test_stream_trickling_body_expires_after_task_handoff(status: int) -> None:
    async with _gateway(tick_s=0.1, status=status) as (kwargs, gateway):
        stream = stream_chat_text(**kwargs)
        started = asyncio.get_running_loop().time()
        try:
            assert await asyncio.create_task(anext(stream)) == ChatStreamDelta(kind="request")
            if status == 200:
                # Handoff while the HTTP response and detached span are already open.
                assert (await asyncio.create_task(anext(stream))).content == "Figure "
            with pytest.raises(TimeoutError):
                await asyncio.create_task(_consume(stream))
            assert asyncio.get_running_loop().time() - started < 0.9
            await asyncio.wait_for(gateway.disconnected.wait(), timeout=0.5)
        finally:
            await stream.aclose()


@pytest.mark.asyncio
async def test_stream_task_handoff_preserves_a_successful_answer_within_budget() -> None:
    async with _gateway() as (kwargs, _backend):
        stream = stream_chat_text(**kwargs)
        try:
            assert await asyncio.create_task(anext(stream)) == ChatStreamDelta(kind="request")
            first = await asyncio.create_task(anext(stream))
            deltas = await asyncio.create_task(_consume(stream))
            assert "".join(delta.content for delta in [first, *deltas]).strip() == ANSWER
        finally:
            await stream.aclose()


@pytest.mark.asyncio
async def test_delayed_stream_consumer_cannot_reset_budget_after_request_marker() -> None:
    async with _gateway() as (kwargs, gateway):
        stream = stream_chat_text(**kwargs)
        try:
            assert await anext(stream) == ChatStreamDelta(kind="request")
            await asyncio.sleep(0.6)
            with pytest.raises(TimeoutError):
                await asyncio.create_task(_consume(stream))
            assert not gateway.received.is_set()
        finally:
            await stream.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_cancelling_generation_closes_the_inflight_socket(streaming: bool) -> None:
    release = asyncio.Event()
    async with _gateway(release=release) as (kwargs, gateway):
        stream = stream_chat_text(**kwargs) if streaming else None
        task = asyncio.create_task(_consume(stream) if stream is not None else generate_chat_text(**kwargs))
        try:
            await asyncio.wait_for(gateway.received.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(gateway.disconnected.wait(), timeout=0.5)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if stream is not None:
                await stream.aclose()
            release.set()


@pytest.mark.parametrize("streaming", [False, True])
def test_prompt_guard_executor_queue_is_part_of_total_generation_budget(streaming: bool) -> None:
    """Use an isolated loop and a genuinely occupied worker; no patched guard or clock."""
    async def exercise() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        release = threading.Event()
        occupied = threading.Event()

        def occupy_worker() -> None:
            occupied.set()
            release.wait()

        worker = loop.run_in_executor(None, occupy_worker)
        while not occupied.is_set():
            await asyncio.sleep(0)
        async with _gateway() as (kwargs, gateway):
            stream = stream_chat_text(**kwargs) if streaming else None
            call = asyncio.create_task(_consume(stream) if stream is not None else generate_chat_text(**kwargs))
            try:
                done, _pending = await asyncio.wait({call}, timeout=0.9)
                assert call in done, "Prompt guard queue ignored the 0.5s generation budget"
                with pytest.raises(TimeoutError):
                    await call
                assert not gateway.received.is_set()
            finally:
                call.cancel()
                release.set()
                await asyncio.gather(call, return_exceptions=True)
                await worker
                if stream is not None:
                    await stream.aclose()

    asyncio.run(exercise())
