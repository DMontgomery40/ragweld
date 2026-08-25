from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from server.chat.benchmark_runner import run_benchmark
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.asyncio
async def test_run_benchmark_clamps_invalid_max_concurrency_to_avoid_deadlock() -> None:
    cfg = TriBridConfig()
    cfg.chat.benchmark.max_concurrent_models = 0

    payload = await asyncio.wait_for(
        run_benchmark(
            prompt="How often is the salinity sensor calibrated?",
            models=["litellm:ragweld-local"],
            config=cfg,
        ),
        timeout=1.0,
    )

    assert len(payload.results) == 1
    assert payload.results[0].error


@pytest.mark.asyncio
async def test_run_benchmark_saves_relative_results_path_from_repo_root(tmp_path: Path) -> None:
    cfg = TriBridConfig()
    cfg.chat.benchmark.save_results = True
    repo_root = Path(__file__).resolve().parents[2]
    results_dir = tmp_path / "benchmarks"
    cfg.chat.benchmark.results_path = os.path.relpath(results_dir, repo_root)

    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir(parents=True, exist_ok=True)
    previous_cwd = Path.cwd()
    try:
        os.chdir(other_cwd)
        payload = await asyncio.wait_for(
            run_benchmark(
                prompt="How often is the salinity sensor calibrated?",
                models=["litellm:ragweld-local"],
                config=cfg,
            ),
            timeout=1.0,
        )
    finally:
        os.chdir(previous_cwd)

    assert (results_dir / f"{payload.run_id}.json").exists()
