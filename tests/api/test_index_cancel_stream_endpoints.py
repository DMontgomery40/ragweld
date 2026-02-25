"""Index cancel + stream contract tests (no mocks)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Generator

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.models.index import IndexStatus


@pytest.fixture(autouse=True)
def isolate_index_runtime_state() -> Generator[None, None, None]:
    """Isolate process-global index runtime dictionaries for this test module."""
    old_status = dict(index_api._STATUS)
    old_stats = dict(index_api._STATS)
    old_tasks = dict(index_api._TASKS)
    old_queues = dict(index_api._EVENT_QUEUES)
    old_last_started = index_api._LAST_STARTED_REPO

    index_api._STATUS.clear()
    index_api._STATS.clear()
    index_api._TASKS.clear()
    index_api._EVENT_QUEUES.clear()
    index_api._LAST_STARTED_REPO = None

    try:
        yield
    finally:
        for task in list(index_api._TASKS.values()):
            task.cancel()
        index_api._STATUS.clear()
        index_api._STATS.clear()
        index_api._TASKS.clear()
        index_api._EVENT_QUEUES.clear()
        index_api._STATUS.update(old_status)
        index_api._STATS.update(old_stats)
        index_api._TASKS.update(old_tasks)
        index_api._EVENT_QUEUES.update(old_queues)
        index_api._LAST_STARTED_REPO = old_last_started


async def _sleep_forever() -> None:
    while True:
        await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_stop_endpoint_cancels_task_and_cleans_runtime_state(client: AsyncClient) -> None:
    repo_id = "cancel-repo-1"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    task = asyncio.create_task(_sleep_forever())

    index_api._STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="indexing",
        progress=0.45,
        current_file="src/foo.py",
        error=None,
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    index_api._TASKS[repo_id] = task
    index_api._EVENT_QUEUES[repo_id] = queue

    response = await client.post(f"/api/index/{repo_id}/stop")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["corpus_id"] == repo_id

    assert repo_id not in index_api._TASKS
    assert repo_id not in index_api._EVENT_QUEUES
    assert task.done()

    drained: list[dict[str, object]] = []
    while True:
        try:
            drained.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    assert any(ev.get("type") == "cancelled" for ev in drained)


@pytest.mark.asyncio
async def test_stop_compat_alias_uses_repo_scope_fields(client: AsyncClient) -> None:
    repo_id = "cancel-repo-2"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    task = asyncio.create_task(_sleep_forever())

    index_api._STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="indexing",
        progress=0.1,
        current_file=None,
        error=None,
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    index_api._TASKS[repo_id] = task
    index_api._EVENT_QUEUES[repo_id] = queue

    response = await client.post("/api/index/stop", json={"repo": repo_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["corpus_id"] == repo_id
    assert repo_id not in index_api._TASKS
    assert repo_id not in index_api._EVENT_QUEUES


@pytest.mark.asyncio
async def test_stream_rejects_stale_queue_when_task_is_done(client: AsyncClient) -> None:
    repo_id = "stale-stream-repo"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    queue.put_nowait({"type": "complete", "message": "old completion"})

    task = asyncio.create_task(asyncio.sleep(0))
    await task

    index_api._STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="complete",
        progress=1.0,
        current_file=None,
        error=None,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )
    index_api._TASKS[repo_id] = task
    index_api._EVENT_QUEUES[repo_id] = queue
    index_api._LAST_STARTED_REPO = repo_id

    response = await client.get("/api/stream/operations/index", params={"corpus_id": repo_id})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_accepts_cancelled_terminal_event(client: AsyncClient) -> None:
    repo_id = "cancel-stream-terminal"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    queue.put_nowait({"type": "cancelled", "message": "cancelled from backend"})
    task = asyncio.create_task(_sleep_forever())

    index_api._STATUS[repo_id] = IndexStatus(
        repo_id=repo_id,
        status="indexing",
        progress=0.33,
        current_file="src/bar.py",
        error=None,
        started_at=datetime.now(UTC),
        completed_at=None,
    )
    index_api._TASKS[repo_id] = task
    index_api._EVENT_QUEUES[repo_id] = queue

    try:
        async with client.stream("GET", "/api/stream/operations/index", params={"corpus_id": repo_id}) as response:
            assert response.status_code == 200
            payload = ""
            async for chunk in response.aiter_text():
                payload += chunk
        assert '"type": "cancelled"' in payload
    finally:
        task.cancel()
