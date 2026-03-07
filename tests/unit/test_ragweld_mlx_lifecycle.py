from __future__ import annotations

import asyncio

import pytest

from server.chat.ragweld_mlx import RagweldMLXChatModel


@pytest.mark.asyncio
async def test_idle_unload_scheduler_keeps_single_pending_timer() -> None:
    model = RagweldMLXChatModel(base_model="base", adapter_dir="adapter")

    baseline = set(asyncio.all_tasks())
    for _ in range(6):
        model._schedule_idle_unload_locked(unload_after_sec=60, unload_generation=1)

    await asyncio.sleep(0)
    created_pending = [t for t in asyncio.all_tasks() if t not in baseline and not t.done()]
    assert len(created_pending) == 1

    for task in created_pending:
        task.cancel()
    await asyncio.gather(*created_pending, return_exceptions=True)
