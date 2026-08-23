"""Cancellation must reach the in-flight gateway call, whichever side initiates it."""

from __future__ import annotations

import asyncio

import pytest

from server.synthetic.providers.grounded_qa_provider import _cancellable


async def _slow_gateway_call(state: dict[str, bool]) -> str:
    state["started"] = True
    try:
        await asyncio.sleep(30)
    except asyncio.CancelledError:
        state["cancelled"] = True
        raise
    state["completed"] = True
    return "answer"


@pytest.mark.asyncio
async def test_cancel_event_aborts_the_inflight_call() -> None:
    state: dict[str, bool] = {}
    cancel_event = asyncio.Event()
    wrapper = asyncio.ensure_future(_cancellable(_slow_gateway_call(state), cancel_event))
    await asyncio.sleep(0.05)
    cancel_event.set()
    with pytest.raises(asyncio.CancelledError):
        await wrapper
    assert state.get("started") and state.get("cancelled") and not state.get("completed")


@pytest.mark.asyncio
async def test_outer_cancellation_aborts_the_inflight_call_too() -> None:
    """A TaskGroup cancelling a sibling (or the run task being cancelled) must not orphan the paid call."""
    state: dict[str, bool] = {}
    cancel_event = asyncio.Event()
    wrapper = asyncio.ensure_future(_cancellable(_slow_gateway_call(state), cancel_event))
    await asyncio.sleep(0.05)
    wrapper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await wrapper
    await asyncio.sleep(0.01)
    assert state.get("started") and state.get("cancelled") and not state.get("completed")


@pytest.mark.asyncio
async def test_completed_calls_return_their_result() -> None:
    async def _fast() -> str:
        return "done"

    assert await _cancellable(_fast(), asyncio.Event()) == "done"
    assert await _cancellable(_fast(), None) == "done"
