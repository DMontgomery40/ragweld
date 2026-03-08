from __future__ import annotations

import asyncio

import pytest

from server.chat.benchmark_runner import run_benchmark
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.asyncio
async def test_run_benchmark_clamps_invalid_max_concurrency_to_avoid_deadlock() -> None:
    cfg = TriBridConfig()
    cfg.chat.benchmark.max_concurrent_models = 0

    payload = await asyncio.wait_for(
        run_benchmark(
            prompt="ping",
            models=["openrouter:openai/gpt-4o-mini"],
            config=cfg,
        ),
        timeout=1.0,
    )

    assert len(payload["results"]) == 1
    assert payload["results"][0]["error"]
