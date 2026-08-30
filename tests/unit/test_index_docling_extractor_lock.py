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
import re
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime
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


def _heartbeat_times(repo_id: str, run_id: str) -> list[datetime]:
    """Emit timestamps of the heartbeat events, so the interval is measured, not parsed."""
    _flush_run_events_sync()
    return [
        event.ts
        for event in _load_run_events(repo_id, run_id, limit=500)
        if "still running" in str(event.message or "")
    ]


async def _await_holder(holding: asyncio.Task[Any], *, timeout: float = 10.0) -> None:
    """Block until the holder owns the extractor, on a deadline.

    The holder has to own the lock before a waiter asks for it, or the test measures nothing.
    Without the deadline a holder that died -- or one that never published itself -- left this
    spinning until the whole suite timed out, reported as a hang rather than as this failure.
    """
    deadline = time.monotonic() + timeout
    while index_api._DOCLING_LOCK_HOLDER is None:
        assert time.monotonic() < deadline, (
            f"the holder never took the extractor lock (task={holding!r})"
        )
        if holding.done():
            await holding  # re-raise whatever killed it instead of waiting out the deadline
        await asyncio.sleep(0.01)


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
        await _await_holder(holding)

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


HEARTBEAT_PATTERN = re.compile(
    r"^Converting (?P<file>.+): still running \((?P<elapsed>\d+)s elapsed\)$"
)


def test_a_long_conversion_says_it_is_still_running_then_backs_off() -> None:
    """One Docling conversion can outlive every other event, so it has to report itself.

    The Apollo run spent 32 minutes inside single-file conversions. Between them the run
    log said nothing, which is indistinguishable from a wedged worker. But one line a minute
    for forty minutes is forty identical lines, which buries every other event in the run
    log: the first beat lands quickly, and after that the interval widens.
    """

    async def scenario() -> tuple[list[str], list[str], list[datetime], datetime]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _register(queue, WAITER_CORPUS, WAITER_RUN)
        started = datetime.now(UTC)
        # 6.0s against 0.6 + 2.0 puts beats at ~0.6/2.6/4.6 with ~1.4s of slack before the
        # third one is at risk. At 5.0s the slack was 0.4s, which is thin for a shared box.
        await _run_docling_extraction_locked(
            time.sleep,
            6.0,
            event_queue=queue,
            conversion=DoclingConversion(
                repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="apollo-11-mission-report.pdf"
            ),
            wait_notice_seconds=0.0,
            heartbeat_seconds=0.6,
            heartbeat_backoff_seconds=2.0,
        )
        during = _matching(_messages(WAITER_CORPUS, WAITER_RUN), "still running")
        times = _heartbeat_times(WAITER_CORPUS, WAITER_RUN)
        # The beat has to stop with the conversion, not outlive it as a leaked task.
        await asyncio.sleep(2.5)
        after = _matching(_messages(WAITER_CORPUS, WAITER_RUN), "still running")
        return during, after, times, started

    during, after, times, started = asyncio.run(scenario())

    assert len(during) >= 3, during
    elapsed: list[int] = []
    for message in during:
        match = HEARTBEAT_PATTERN.match(message)
        assert match is not None, message
        assert match.group("file") == "apollo-11-mission-report.pdf", message
        elapsed.append(int(match.group("elapsed")))
    assert elapsed == sorted(set(elapsed)), elapsed
    assert after == during, (during, after)

    # The shape is the whole point: the first beat lands on the short interval, and every
    # beat after it waits the backoff. At 60s/60s a 40-minute conversion wrote 40 lines.
    assert (times[0] - started).total_seconds() < 1.6, (times, started)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    assert gaps, times
    assert all(gap >= 1.5 for gap in gaps), gaps


def test_a_heartbeat_without_a_backoff_reports_once_and_stops() -> None:
    """`heartbeat_backoff_seconds <= 0` means one notice, like `wait_repeat_seconds <= 0`."""

    async def scenario() -> list[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _register(queue, WAITER_CORPUS, WAITER_RUN)
        await _run_docling_extraction_locked(
            time.sleep,
            2.5,
            event_queue=queue,
            conversion=DoclingConversion(
                repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="apollo-11-mission-report.pdf"
            ),
            wait_notice_seconds=0.0,
            heartbeat_seconds=0.5,
            heartbeat_backoff_seconds=0.0,
        )
        return _matching(_messages(WAITER_CORPUS, WAITER_RUN), "still running")

    messages = asyncio.run(scenario())

    assert len(messages) == 1, messages


def test_a_short_conversion_emits_no_heartbeat() -> None:
    """A conversion that finishes inside one interval must not narrate itself at all."""

    async def scenario() -> list[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        _register(queue, WAITER_CORPUS, WAITER_RUN)
        result = await _run_docling_extraction_locked(
            lambda: "converted",
            event_queue=queue,
            conversion=DoclingConversion(
                repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="two-pager.pdf"
            ),
            wait_notice_seconds=0.0,
            heartbeat_seconds=1.0,
        )
        assert result == "converted"
        await asyncio.sleep(1.5)
        return _messages(WAITER_CORPUS, WAITER_RUN)

    messages = asyncio.run(scenario())

    assert not _matching(messages, "still running"), messages


QUEUED_PATTERN = re.compile(r"— queued (?P<elapsed>\d+)s$")


def test_a_long_queue_keeps_reporting_how_long_it_has_waited() -> None:
    """One notice at the front of a 19-minute queue goes stale and reads as a hang.

    The wait is reported until it ends, and each notice carries the MEASURED elapsed wait --
    repeating the threshold would say "queued 15s" twenty times over twenty minutes, which is
    the same lie as saying nothing.
    """

    async def scenario() -> list[str]:
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
                wait_notice_seconds=0.0,
            )
        )
        await _await_holder(holding)

        queued = asyncio.create_task(
            _run_docling_extraction_locked(
                lambda: "converted",
                event_queue=waiter_queue,
                conversion=DoclingConversion(
                    repo_id=WAITER_CORPUS, run_id=WAITER_RUN, file="two-pager.pdf"
                ),
                wait_notice_seconds=1.0,
                wait_repeat_seconds=1.0,
            )
        )
        deadline = time.monotonic() + 20.0
        while len(_matching(_messages(WAITER_CORPUS, WAITER_RUN), "queued")) < 3:
            assert time.monotonic() < deadline, _messages(WAITER_CORPUS, WAITER_RUN)
            await asyncio.sleep(0.05)
        notices = _matching(_messages(WAITER_CORPUS, WAITER_RUN), "queued")

        release.set()
        assert await holding == "held"
        assert await queued == "converted"
        return notices

    notices = asyncio.run(scenario())

    assert len(notices) >= 3, notices
    elapsed: list[int] = []
    for message in notices:
        match = QUEUED_PATTERN.search(message)
        assert match is not None, message
        assert HOLDER_CORPUS in message, message
        elapsed.append(int(match.group("elapsed")))
    # Strictly increasing is the whole point: a repeated constant would be flat.
    assert elapsed == sorted(set(elapsed)), elapsed
    assert elapsed[0] >= 1, elapsed
