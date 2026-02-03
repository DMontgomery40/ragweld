from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from server.chat.generation import generate_chat_text
from server.chat.provider_router import select_provider_route
from server.models.tribrid_config_model import TriBridConfig


def _now_ms() -> int:
    return int(time.time() * 1000)


def _format_error(e: Exception) -> str:
    msg = str(e).strip()
    if msg:
        return f"{type(e).__name__}: {msg}"
    return type(e).__name__


async def _run_one(
    *,
    prompt: str,
    model: str,
    config: TriBridConfig,
    sem: asyncio.Semaphore,
) -> dict[str, Any]:
    async with sem:
        try:
            route = select_provider_route(chat_config=config.chat, model_override=model)
        except Exception as e:
            return {
                "model": model,
                "response": "",
                "latency_ms": 0.0,
                "breakdown_ms": {"generate": 0.0},
                "error": _format_error(e),
            }

        t0 = time.perf_counter()
        try:
            text, _provider_id = await generate_chat_text(
                route=route,
                openrouter_cfg=config.chat.openrouter,
                system_prompt=config.chat.system_prompt_base,
                user_message=prompt,
                images=[],
                temperature=config.chat.temperature_no_retrieval,
                max_tokens=config.chat.max_tokens,
                context_chunks=[],
            )
            gen_ms = float((time.perf_counter() - t0) * 1000.0)
            return {
                "model": model,
                "response": str(text or ""),
                "latency_ms": gen_ms,
                "breakdown_ms": {"generate": gen_ms},
                "error": None,
            }
        except Exception as e:
            gen_ms = float((time.perf_counter() - t0) * 1000.0)
            return {
                "model": model,
                "response": "",
                "latency_ms": gen_ms,
                "breakdown_ms": {"generate": gen_ms},
                "error": _format_error(e),
            }


async def run_benchmark(*, prompt: str, models: list[str], config: TriBridConfig) -> dict[str, Any]:
    run_id = uuid.uuid4().hex
    started_at_ms = _now_ms()

    max_concurrent = int(getattr(config.chat.benchmark, "max_concurrent_models", 1) or 1)
    sem = asyncio.Semaphore(max_concurrent)

    tasks = [asyncio.create_task(_run_one(prompt=prompt, model=m, config=config, sem=sem)) for m in models]
    results = await asyncio.gather(*tasks) if tasks else []

    ended_at_ms = _now_ms()
    payload: dict[str, Any] = {
        "run_id": run_id,
        "started_at_ms": int(started_at_ms),
        "ended_at_ms": int(ended_at_ms),
        "results": list(results),
    }

    if bool(getattr(config.chat.benchmark, "save_results", False)):
        out_dir = Path(str(config.chat.benchmark.results_path))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{run_id}.json"
        out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return payload

