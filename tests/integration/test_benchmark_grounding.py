"""Benchmark runs ground every model on the same retrieved chunks and say so.

Regression for the 2026-08-25 drive finding M8 (the benchmark called generation
with context_chunks=[] and never disclosed it; both models answered the Aurora
question from world knowledge). Real corpus, real index, real gateway spend (two
small paid requests through LiteLLM); skipped with the exact reason when the
gateway is not reachable.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from server.chat.benchmark_runner import run_benchmark
from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"
_QUESTION = "How often is the salinity sensor calibrated?"
_MODELS = [
    os.environ.get("BENCHMARK_E2E_MODEL_A", "openai.gpt-5.6-luna"),
    os.environ.get("BENCHMARK_E2E_MODEL_B", "openai.gpt-5.4-mini"),
]


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
    import asyncio

    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        last = res.json()
        if last.get("status") in {"complete", "error", "cancelled"}:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"index did not finish in time: {last}")


async def _gateway_serves(cfg: TriBridConfig, models: list[str]) -> str | None:
    base = str(cfg.chat.litellm.base_url or "").rstrip("/")
    key = os.environ.get("LITELLM_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=3.0) as probe:
            response = await probe.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    except Exception as exc:
        return f"LiteLLM gateway not reachable at {base}: {exc}"
    if response.status_code != 200:
        return f"LiteLLM gateway at {base} answered HTTP {response.status_code} to /models"
    served = {str(item.get("id")) for item in (response.json().get("data") or [])}
    missing = [m for m in models if m not in served]
    return f"gateway does not serve {missing}" if missing else None


async def test_runner_reports_an_ungrounded_run_without_a_corpus_scope() -> None:
    cfg = TriBridConfig()
    payload = await run_benchmark(prompt=_QUESTION, models=["litellm:not-a-served-alias"], config=cfg)
    assert payload.retrieval is not None
    assert payload.retrieval.grounded is False and payload.retrieval.chunk_count == 0
    assert payload.retrieval.corpus_id is None and payload.retrieval.reason
    assert payload.results[0].context_chunks_used == 0


async def test_benchmark_grounds_every_model_on_the_corpus(client: AsyncClient, tmp_path: Path) -> None:
    cfg = load_config()
    skip_reason = await _gateway_serves(cfg, _MODELS)
    if skip_reason:
        pytest.skip(skip_reason)

    corpus_id = f"pytest_bench_ground_{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)}
        )
        assert created.status_code in (200, 201), created.text
        cfg.embedding.embedding_backend = "deterministic"
        cfg.graph_indexing.enabled = False
        cfg.graph_search.enabled = False
        cfg.reranking.reranker_mode = "none"
        cfg.semantic_cache.enabled = False
        cfg.chat.litellm.enabled = True
        cfg.chat.benchmark.enabled = True
        cfg.chat.benchmark.save_results = True
        cfg.chat.benchmark.results_path = str(tmp_path / "benchmarks")
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        started = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True}
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final

        run = await client.post(
            "/api/benchmark/run", params={"corpus_id": corpus_id}, json={"prompt": _QUESTION, "models": _MODELS}
        )
        assert run.status_code == 200, run.text
        payload = run.json()
        retrieval = payload["retrieval"]
        assert retrieval["grounded"] is True and retrieval["chunk_count"] > 0, retrieval
        assert retrieval["corpus_id"] == corpus_id and retrieval["reason"] is None
        assert any("sensor-calibration" in path for path in retrieval["source_paths"]), retrieval["source_paths"]
        assert [r["model"] for r in payload["results"]] == _MODELS
        for result in payload["results"]:
            assert result["error"] is None, result
            assert result["context_chunks_used"] > 0, result
            assert result["model_id"], result
            assert "calibrat" in result["response"].lower(), result["response"][:300]
        # The persisted record carries the grounding too.
        saved = tmp_path / "benchmarks" / f"{payload['run_id']}.json"
        assert saved.exists()
        assert '"grounded": true' in saved.read_text()
    finally:
        config_store._store = None
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        try:
            await pg.disconnect()
        except Exception:
            pass
