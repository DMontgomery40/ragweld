from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from server.chat.benchmark_runner import run_benchmark
from server.config import load_config

router = APIRouter(tags=["benchmark"])


@router.post("/benchmark/run")
async def benchmark_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the same prompt against multiple models (best-effort).

    This endpoint is intended for local benchmarking and may require provider
    credentials (e.g., OPENROUTER_API_KEY) or local inference servers.
    """
    cfg = load_config()
    if not bool(getattr(cfg.chat.benchmark, "enabled", False)):
        raise HTTPException(status_code=400, detail="Benchmarking is disabled")

    prompt = str(payload.get("prompt") or "").strip()
    models_raw = payload.get("models")
    models = [str(m).strip() for m in (models_raw or []) if str(m).strip()] if isinstance(models_raw, list) else []

    if not prompt:
        raise HTTPException(status_code=400, detail="Missing prompt")
    if len(models) < 2:
        raise HTTPException(status_code=400, detail="Select at least 2 models")
    if len(models) > int(getattr(cfg.chat.benchmark, "max_concurrent_models", 4) or 4):
        raise HTTPException(status_code=400, detail="Too many models selected")

    return await run_benchmark(prompt=prompt, models=models, config=cfg)


@router.get("/benchmark/results")
async def benchmark_results(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    """Return recent benchmark runs (best-effort)."""
    cfg = load_config()
    path = Path(str(getattr(cfg.chat.benchmark, "results_path", "data/benchmarks/") or "data/benchmarks/"))
    if not path.exists():
        return {"runs": []}

    runs: list[dict[str, Any]] = []
    files = sorted(path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[: int(limit)]:
        try:
            runs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return {"runs": runs}

