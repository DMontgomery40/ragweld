from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import generate_chat_text
from server.chat.handler import fit_context_to_route
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import BenchmarkResult, BenchmarkRetrieval, BenchmarkRun, TriBridConfig

_ROOT = Path(__file__).resolve().parents[2]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _format_error(e: Exception) -> str:
    msg = str(e).strip()
    if msg:
        return f"{type(e).__name__}: {msg}"
    return type(e).__name__


def _results_dir(path_str: str) -> Path:
    path = Path(str(path_str or "data/benchmarks/")).expanduser()
    if not path.is_absolute():
        path = _ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _run_one(
    *,
    prompt: str,
    model: str,
    config: TriBridConfig,
    sem: asyncio.Semaphore,
    context_chunks: list[ChunkMatch],
    corpus_scoped: bool,
) -> BenchmarkResult:
    async with sem:
        try:
            route = select_provider_route(
                config=config,
                model_override=model,
            )
        except Exception as e:
            return BenchmarkResult(
                model=model,
                response="",
                latency_ms=0.0,
                breakdown_ms={"generate": 0.0},
                error=_format_error(e),
            )

        t0 = time.perf_counter()
        try:
            # Same grounding path as chat: fit the retrieved chunks to this
            # alias's context window, then use the RAG system prompt.
            rag_chunks, _recall_chunks, _dropped = await asyncio.to_thread(
                fit_context_to_route,
                config=config,
                route_model=str(route.model),
                user_message=prompt,
                images=[],
                rag_chunks=list(context_chunks),
                recall_chunks=[],
            )
            system_prompt = get_system_prompt(
                has_rag_context=bool(rag_chunks),
                has_recall_context=False,
                config=config.chat,
            )
            context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=[]) if rag_chunks else None
            # Same policy as chat_once: the retrieval temperature applies whenever
            # a corpus was selected, whether or not chunks survived the budget.
            temperature = float(config.chat.temperature) if corpus_scoped else float(config.chat.temperature_no_retrieval)
            result = await generate_chat_text(
                route=route,
                system_prompt=system_prompt,
                user_message=prompt,
                observation_name="benchmark.generation",
                images=[],
                temperature=temperature,
                max_tokens=config.chat.max_tokens,
                context_text=context_text,
                context_chunks=rag_chunks,
            )
            gen_ms = float((time.perf_counter() - t0) * 1000.0)
            return BenchmarkResult(
                model=model,
                response=str(result.text or ""),
                latency_ms=gen_ms,
                breakdown_ms={"generate": gen_ms},
                error=None,
                context_chunks_used=len(rag_chunks),
                model_id=str(route.model),
            )
        except Exception as e:
            gen_ms = float((time.perf_counter() - t0) * 1000.0)
            return BenchmarkResult(
                model=model,
                response="",
                latency_ms=gen_ms,
                breakdown_ms={"generate": gen_ms},
                error=_format_error(e),
                model_id=str(route.model),
            )


async def run_benchmark(
    *,
    prompt: str,
    models: list[str],
    config: TriBridConfig,
    repo_id: str | None = None,
    context_chunks: list[ChunkMatch] | None = None,
    retrieval: BenchmarkRetrieval | None = None,
) -> BenchmarkRun:
    """Run one prompt across models, grounding every model on the same retrieved chunks.

    ``context_chunks`` are the tri-brid retrieval results for ``prompt`` (the API
    layer retrieves them); ``retrieval`` records how grounding went so the
    persisted run and the UI never present an ungrounded answer as corpus-backed.
    """
    run_id = uuid.uuid4().hex
    chunks = list(context_chunks or [])
    if retrieval is None:
        retrieval = BenchmarkRetrieval(
            corpus_id=repo_id,
            grounded=bool(chunks),
            chunk_count=len(chunks),
            reason=None if chunks else "no retrieval context was supplied for this run",
            source_paths=list(dict.fromkeys(str(c.file_path) for c in chunks if getattr(c, "file_path", None))),
        )
    started_at_ms = _now_ms()

    try:
        max_concurrent = int(getattr(config.chat.benchmark, "max_concurrent_models", 1) or 1)
    except Exception:
        max_concurrent = 1
    max_concurrent = max(1, max_concurrent)
    sem = asyncio.Semaphore(max_concurrent)

    tasks = [
        asyncio.create_task(
            _run_one(
                prompt=prompt,
                model=m,
                config=config,
                sem=sem,
                context_chunks=chunks,
                corpus_scoped=bool(retrieval.corpus_id),
            )
        )
        for m in models
    ]
    results = await asyncio.gather(*tasks) if tasks else []

    ended_at_ms = _now_ms()
    payload = BenchmarkRun(
        run_id=run_id,
        repo_id=repo_id,
        prompt=prompt,
        models=list(models),
        started_at_ms=int(started_at_ms),
        ended_at_ms=int(ended_at_ms),
        results=list(results),
        retrieval=retrieval,
    )

    if bool(getattr(config.chat.benchmark, "save_results", False)):
        out_dir = _results_dir(str(config.chat.benchmark.results_path))
        out_file = out_dir / f"{run_id}.json"
        out_file.write_text(json.dumps(payload.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2), encoding="utf-8")

    return payload
