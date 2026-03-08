from __future__ import annotations

import asyncio

import pytest

from server.retrieval.mlx_qwen3 import MLXQwen3Reranker


@pytest.mark.asyncio
async def test_idle_unload_scheduler_keeps_single_pending_timer() -> None:
    reranker = MLXQwen3Reranker(
        base_model="base",
        adapter_dir="adapter",
        lora_rank=8,
        lora_alpha=16.0,
        lora_dropout=0.0,
        lora_target_modules=["q_proj"],
    )
    reranker._unload_after_sec = 60

    baseline = set(asyncio.all_tasks())
    async with reranker._lock:
        for generation in range(1, 7):
            reranker._schedule_idle_unload_locked(unload_generation=generation)

    await asyncio.sleep(0)
    created_pending = [t for t in asyncio.all_tasks() if t not in baseline and not t.done()]
    assert len(created_pending) == 1

    for task in created_pending:
        task.cancel()
    await asyncio.gather(*created_pending, return_exceptions=True)
