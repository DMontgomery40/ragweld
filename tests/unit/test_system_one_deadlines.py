"""System One total deadlines and cancellation against real HTTP sockets."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from prometheus_client import REGISTRY

from server.models.system_one import SystemOneConfig, SystemOneNoul
from server.system_one.client import SystemOneClient, SystemOneTimeoutError

pytestmark = pytest.mark.asyncio

STATE = {
    "query": "Which figure shows lunar module pitch attitude during powered descent?",
    "candidate_passage": "Figure 5-5 shows pitch attitude during powered descent.",
}
QUESTIONS = {
    "answers_query": SystemOneNoul(instructions="Does candidate_passage answer query?"),
}
ANSWER = {
    "model": "english",
    "answers": {"answers_query": {"type": "noul", "noul": 0.9}},
}


@dataclass
class _Response:
    status: int = 200
    delay_s: float = 0.0
    chunk_delay_s: float = 0.0
    retry_after_s: float | None = None
    release: asyncio.Event | None = None


@dataclass
class _Backend:
    responses: list[_Response]
    received: asyncio.Queue[dict[str, object]] = field(default_factory=asyncio.Queue)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        assert task is not None
        self.tasks.add(task)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            request_line, *header_lines = headers.decode().split("\r\n")
            assert request_line == "POST /v1/systemone HTTP/1.1"
            length = next(
                int(line.split(":", 1)[1])
                for line in header_lines
                if line.lower().startswith("content-length:")
            )
            body = json.loads(await reader.readexactly(length))
            assert body["state"] == STATE
            assert body["questions"]["answers_query"]["instructions"] == QUESTIONS["answers_query"].instructions
            await self.received.put(body)
            response = self.responses.pop(0)
            if response.release is not None:
                await response.release.wait()
            await asyncio.sleep(response.delay_s)
            raw = json.dumps(ANSWER if response.status == 200 else {"error": "overloaded"}).encode()
            response_headers = [
                f"HTTP/1.1 {response.status} Response",
                "Content-Type: application/json",
                f"Content-Length: {len(raw)}",
                "Connection: close",
            ]
            if response.retry_after_s is not None:
                response_headers.append(f"Retry-After: {response.retry_after_s}")
            writer.write(("\r\n".join(response_headers) + "\r\n\r\n").encode())
            await writer.drain()
            if response.chunk_delay_s:
                for start in range(0, len(raw), 16):
                    await asyncio.sleep(response.chunk_delay_s)
                    writer.write(raw[start : start + 16])
                    await writer.drain()
            else:
                writer.write(raw)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            # A timed-out/cancelled client closes the actual socket mid-response.
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.tasks.discard(task)


@asynccontextmanager
async def _client(responses: list[_Response], *, max_retries: int = 0) -> AsyncIterator[tuple[SystemOneClient, _Backend]]:
    backend = _Backend(responses)
    server = await asyncio.start_server(backend.handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    cfg = SystemOneConfig(
        provider="laya",
        laya_base_url=f"http://127.0.0.1:{port}",
        timeout_s=1.0,
        max_concurrency=1,
        max_retries=max_retries,
    )
    try:
        async with server, SystemOneClient(cfg) as client:
            yield client, backend
    finally:
        tasks = list(backend.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _count(outcome: str) -> float:
    value = REGISTRY.get_sample_value(
        "tribrid_system_one_requests_total", {"provider": "laya", "outcome": outcome}
    )
    return float(value or 0)


async def test_saturated_calls_share_their_own_queue_inclusive_deadlines() -> None:
    """Moving the deadline after semaphore acquisition serializes three full budgets."""
    before = _count("timeout")
    async with _client([_Response(delay_s=2.0) for _ in range(3)]) as (client, _backend):
        started = asyncio.get_running_loop().time()
        results = await asyncio.gather(*(client.ask(STATE, QUESTIONS) for _ in range(3)), return_exceptions=True)
        elapsed = asyncio.get_running_loop().time() - started
    assert all(isinstance(result, SystemOneTimeoutError) for result in results)
    assert elapsed < 1.5, f"Saturated calls consumed {elapsed:.2f}s for a 1s total budget"
    assert _count("timeout") == before + 3


async def test_continuous_response_bytes_cannot_extend_the_total_deadline() -> None:
    """A per-read timeout alone permits a slow response to run beyond the call budget."""
    async with _client([_Response(chunk_delay_s=0.2), _Response()]) as (client, backend):
        started = asyncio.get_running_loop().time()
        with pytest.raises(SystemOneTimeoutError) as caught:
            await client.ask(STATE, QUESTIONS)
        assert asyncio.get_running_loop().time() - started < 1.5
        assert caught.value.outcome == "timeout"
        assert caught.value.provider == "laya"
        response = await client.ask(STATE, QUESTIONS)
        assert response.answers["answers_query"].noul == 0.9
        assert backend.received.qsize() == 2


async def test_queue_wait_retries_and_backoff_consume_one_total_budget() -> None:
    """Starting a fresh retry budget after queueing lets this second call succeed late."""
    async with _client(
        [_Response(delay_s=0.4), _Response(status=429, retry_after_s=0.3), _Response(delay_s=0.5), _Response()],
        max_retries=1,
    ) as (client, backend):
        first = asyncio.create_task(client.ask(STATE, QUESTIONS))
        await asyncio.wait_for(backend.received.get(), timeout=1)
        started = asyncio.get_running_loop().time()
        try:
            with pytest.raises(SystemOneTimeoutError):
                await client.ask(STATE, QUESTIONS)
            assert asyncio.get_running_loop().time() - started < 1.5
            assert (await first).answers["answers_query"].noul == 0.9
            assert (await client.ask(STATE, QUESTIONS)).answers["answers_query"].noul == 0.9
            assert backend.received.qsize() == 3
        finally:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("cancel_queued", [False, True])
async def test_cancellation_propagates_and_releases_capacity_without_counting_success(cancel_queued: bool) -> None:
    """Swallowing cancellation or retaining a slot prevents the following real request."""
    release = asyncio.Event()
    before_ok = _count("ok")
    before_cancelled = _count("cancelled")
    async with _client([_Response(release=release), _Response()]) as (client, backend):
        active = asyncio.create_task(client.ask(STATE, QUESTIONS))
        await asyncio.wait_for(backend.received.get(), timeout=1)
        cancelled = asyncio.create_task(client.ask(STATE, QUESTIONS)) if cancel_queued else active
        try:
            # Run the queued coroutine up to its semaphore wait before cancellation.
            await asyncio.sleep(0)
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            if cancel_queued:
                release.set()
                assert (await active).answers["answers_query"].noul == 0.9
            response = await client.ask(STATE, QUESTIONS)
            assert response.answers["answers_query"].noul == 0.9
            assert backend.received.qsize() == 1
            assert _count("ok") == before_ok + (2 if cancel_queued else 1)
            assert _count("cancelled") == before_cancelled + 1
        finally:
            release.set()
            active.cancel()
            cancelled.cancel()
            await asyncio.gather(active, cancelled, return_exceptions=True)
