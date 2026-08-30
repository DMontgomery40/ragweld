"""A run queued behind the process-wide document extractor has to say so.

Docling conversion is serialized through one process-wide lock, so a second index run's
every file waits there with nothing in its run log: on LXC100 a 2-page corpus took 24m49s
instead of 1.8 min, ~19 minutes of it with zero events at 99% idle CPU, while its status
still read `indexing`.

These tests drive the real lock with real blocking callables and read the real run-event
sink (the JSONL run log `_emit_event` writes through), so nothing here can pass on a mock
that agrees with itself.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Generator
from typing import Any

import pytest

import server.api.index as index_api
from server.api.index import (
    DoclingConversion,
    _flush_run_events_sync,
    _load_run_events,
    _run_docling_extraction_locked,
)

HOLDER_CORPUS = "corpus-holder"
HOLDER_RUN = "0d3f9a71-holder"
WAITER_CORPUS = "corpus-waiter"
WAITER_RUN = "7be21c04-waiter"


@pytest.fixture(autouse=True)
def isolate_index_run_storage(tmp_path) -> Generator[None, None, None]:
    """Give each test its own run log, extractor lock and queue registry.

    `asyncio.Lock` binds to the first event loop that ever contends it, and every test here
    runs its own loop, so the process-wide extractor lock has to be a fresh one of the same
    real lock per test -- otherwise a contended acquire raises "bound to a different event
    loop" as soon as any other module contends it first. `_QUEUE_RUN_CONTEXT` is keyed by
    `id(queue)`, which CPython reuses, so a leaked entry would route a later test's events
    into this test's run.
    """
    old_runs_dir = index_api._INDEX_RUNS_DIR
    old_lock = index_api._DOCLING_EXTRACTION_LOCK
    old_context = dict(index_api._QUEUE_RUN_CONTEXT)
    index_api._INDEX_RUNS_DIR = tmp_path
    index_api._DOCLING_EXTRACTION_LOCK = asyncio.Lock()
    try:
        yield
    finally:
        index_api._INDEX_RUNS_DIR = old_runs_dir
        index_api._DOCLING_EXTRACTION_LOCK = old_lock
        index_api._QUEUE_RUN_CONTEXT.clear()
        index_api._QUEUE_RUN_CONTEXT.update(old_context)
        index_api._DOCLING_LOCK_HOLDER = None


def _register(queue: asyncio.Queue[dict[str, Any]], repo_id: str, run_id: str) -> None:
    """Bind a queue to its run exactly as `_run_index` does, so events reach the run log."""
    index_api._QUEUE_RUN_CONTEXT[id(queue)] = (repo_id, run_id)


def _messages(repo_id: str, run_id: str) -> list[str]:
    _flush_run_events_sync()
    return [str(event.message or "") for event in _load_run_events(repo_id, run_id, limit=500)]


def _matching(messages: list[str], needle: str) -> list[str]:
    return [message for message in messages if needle in message]


async def _await_message(repo_id: str, run_id: str, needle: str, *, timeout: float) -> str:
    """The first run-log message containing `needle`, or a failure naming what was logged."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _matching(_messages(repo_id, run_id), needle)
        if found:
            return found[0]
        await asyncio.sleep(0.05)
    raise AssertionError(f"{needle!r} never reached the run log: {_messages(repo_id, run_id)}")


def test_a_run_queued_behind_the_extractor_names_the_run_that_holds_it() -> None:
    """The whole defect: waiting on the extractor produced no run event at all."""

    async def scenario() -> tuple[list[str], list[str]]:
        holder_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        waiter_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _register(holder_queue, HOLDER_CORPUS, HOLDER_RUN)
        _register(waiter_queue, WAITER_CORPUS, WAITER_RUN)
        release = threading.Event()

        def _hold() -> str:
            release.wait(timeout=30)
            return "held"

        holding = asyncio.create_task(
            _run_docling_extraction_locked(
                _hold,
                event_queue=holder_queue,
                conversion=DoclingConversion(
                    repo_id=HOLDER_CORPUS, run_id=HOLDER_RUN, file="apollo-11-mission-report.pdf"
                ),
                wait_notice_seconds=0.2,
            )
        )
        # The holder has to own the lock before the waiter asks for it, or the test is
        # measuring nothing. Poll the published holder record rather than sleeping blind.
        while index_api._DOCLING_LOCK_HOLDER is None:
            await asyncio.sleep(0.01)

        queued = asyncio.create_task(
            _run_docling_extraction_locked(
                lambda: "converted",
                event_queue=waiter_queue,
                conversion=DoclingConversion(
                    repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="two-pager.pdf"
                ),
                wait_notice_seconds=0.2,
            )
        )
        waiting = await _await_message(
            WAITER_CORPUS, WAITER_RUN, "Waiting for the document extractor", timeout=10.0
        )
        release.set()
        assert await holding == "held"
        assert await queued == "converted"
        acquired = await _await_message(
            WAITER_CORPUS, WAITER_RUN, "Document extractor acquired after", timeout=10.0
        )
        return [waiting, acquired], _messages(HOLDER_CORPUS, HOLDER_RUN)

    waiter_messages, holder_messages = asyncio.run(scenario())

    waiting, acquired = waiter_messages
    assert "another index run is converting" in waiting
    assert HOLDER_CORPUS in waiting, waiting
    assert HOLDER_RUN[:8] in waiting, waiting
    assert "queued" in waiting, waiting
    assert acquired.endswith("s"), acquired

    # The run that owns the extractor never waited for it.
    assert not _matching(holder_messages, "Waiting for the document extractor"), holder_messages
    assert not _matching(holder_messages, "Document extractor acquired after"), holder_messages
    # The record is published only while the lock is held.
    assert index_api._DOCLING_LOCK_HOLDER is None


def test_an_uncontended_extraction_logs_no_waiting_event() -> None:
    """A run that owns the extractor immediately must not narrate a queue it never joined."""

    async def scenario() -> list[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _register(queue, WAITER_CORPUS, WAITER_RUN)
        result = await _run_docling_extraction_locked(
            lambda: "converted",
            event_queue=queue,
            conversion=DoclingConversion(
                repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="two-pager.pdf"
            ),
            wait_notice_seconds=0.2,
        )
        assert result == "converted"
        return _messages(WAITER_CORPUS, WAITER_RUN)

    messages = asyncio.run(scenario())

    assert not _matching(messages, "Waiting for the document extractor"), messages
    assert not _matching(messages, "Document extractor acquired after"), messages
