from __future__ import annotations

import asyncio
import fcntl
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from server.chat.benchmark_runner import run_benchmark
from server.config import load_config
from server.models.tribrid_config_model import TriBridConfig
from tests.api.live_server import live_app_subprocess

pytest_plugins = ("tests.unit.test_embedder",)


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


@contextmanager
def _performance_benchmark_app(tmp_path: Path, gateway_url: str, model: str):
    cfg = load_config()
    cfg.embedding.embedding_backend = "provider"
    cfg.embedding.embedding_type = "openai"
    cfg.embedding.embedding_model = model
    cfg.embedding.embedding_dim = 128
    cfg.embedding.embedding_retry_max = 1
    cfg.embedding.embedding_cache_enabled = False
    cfg.tokenization.strategy = "tiktoken"
    cfg.tokenization.tiktoken_encoding = "cl100k_base"
    cfg.chunking.chunking_strategy = "fixed_tokens"
    cfg.graph_indexing.enabled = False
    cfg.graph_search.enabled = False
    cfg.indexing.figures.enabled = False
    cfg.indexing.skip_dense = False
    cfg.reranking.reranker_mode = "none"
    cfg.semantic_cache.enabled = False
    cfg.chat.recall.enabled = False
    cfg.chat.litellm.base_url = gateway_url
    config_path = tmp_path / "runtime.json"
    config_path.write_text(cfg.model_dump_json())
    config_path.chmod(0o600)
    source = tmp_path / "corpus"
    source.mkdir()
    (source / "calibration.txt").write_text("The Aurora salinity sensor is calibrated every seven days using a reference solution.")
    corpus = "pytest_benchmark_cli_" + uuid4().hex
    with live_app_subprocess(config_path=config_path, env={
        "LITELLM_BASE_URL": gateway_url, "LITELLM_API_KEY": "synthetic-benchmark-client",
    }) as base_url, httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
        response = client.post("/api/corpora", json={"corpus_id": corpus, "name": corpus, "path": str(source)})
        assert response.status_code == 200, response.text
        try:
            yield client, corpus, source, base_url
        finally:
            # The CLI deadline does not cancel the server's owned index job.
            deadline = time.monotonic() + 60
            while client.get(f"/api/index/{corpus}/status").json()["status"] == "indexing":
                assert time.monotonic() < deadline, "benchmark fixture index did not drain"
                time.sleep(0.1)
            response = client.delete(f"/api/corpora/{corpus}")
            assert response.status_code == 200, response.text


def _performance_benchmark_cli(base_url: str, corpus: str, source: Path, output: Path, *extra: str):
    return subprocess.run([
        sys.executable, "-m", "scripts.benchmark_perf", "--api-base-url", base_url,
        "--corpus-id", corpus, "--corpus-path", str(source), "--out-json", str(output),
        "--query", "How often is the Aurora salinity sensor calibrated?",
        "--iterations", "1", "--warmup", "0", "--no-graph", "--no-sparse",
        "--request-timeout", "30", "--index-timeout", "60", *extra,
    ], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=90)


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.parametrize("model", ["text-embedding-3-small", "text-embedding-3-large"])
def test_performance_benchmark_cli_indexes_and_searches_through_initialized_api(
    tmp_path: Path, embedding_http, model: str,
) -> None:
    with _performance_benchmark_app(tmp_path, embedding_http.base_url, model) as (client, corpus, source, base_url):
        output = tmp_path / "benchmark.json"
        indexed = _performance_benchmark_cli(base_url, corpus, source, output)
        assert indexed.returncode == 0, indexed.stderr
        report = json.loads(output.read_text())
        assert report["measurement"] == "application_http"
        assert report["indexing"]["stats"]["total_chunks"] > 0
        assert report["search"]["summary"]["total_calls"] == 1
        assert report["search"]["per_query"][0]["matches"]["min"] > 0
        before = client.get(f"/api/index/{corpus}/runs/latest").json()
        assert before["run_id"] == report["indexing"]["run_id"]
        assert before["status"] == "complete"
        first_request_count = len(embedding_http.requests)
        repeated = _performance_benchmark_cli(base_url, corpus, source, output, "--skip-index")
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(output.read_text())["indexing"] == {"skipped": True}
        assert client.get(f"/api/index/{corpus}/runs/latest").json()["run_id"] == before["run_id"]
        requests = embedding_http.requests
        assert len(requests) > first_request_count > 0
        assert {item["body"]["model"] for item in requests} == {f"openai.{model}"}
        assert all(item["body"]["dimensions"] == 128 for item in requests)
        metadata = [json.loads({key.lower(): value for key, value in item["headers"].items()}[
            "x-litellm-spend-logs-metadata"]) for item in requests]
        assert {item["lane"] for item in metadata} >= {"index_embeddings", "retrieval_embeddings"}
        assert {item["corpus_id"] for item in metadata} == {corpus}


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.parametrize("outcome", ["failed", "deadline"])
@pytest.mark.parametrize("previous_success", [False, True])
def test_performance_benchmark_cli_refuses_failed_or_unfinished_index(
    tmp_path: Path, embedding_http, outcome: str, previous_success: bool,
) -> None:
    with _performance_benchmark_app(tmp_path, embedding_http.base_url, "text-embedding-3-small") as (
        client, corpus, source, base_url,
    ):
        try:
            output = tmp_path / "not-a-success.json"
            if previous_success:
                previous = _performance_benchmark_cli(base_url, corpus, source, output)
                assert previous.returncode == 0, previous.stderr
                assert json.loads(output.read_text())["search"]["summary"]["total_calls"] == 1
                embedding_http.requests.clear()
                embedding_http.received.clear()
            embedding_http.mode = "invalid_request" if outcome == "failed" else "held"
            result = _performance_benchmark_cli(base_url, corpus, source, output,
                                                *(["--index-timeout", "0.05"] if outcome == "deadline" else []))
            assert result.returncode != 0
            assert not output.exists()
            assert ("timed out" if outcome == "deadline" else "Index run failed") in result.stderr
            # A client wait deadline leaves the accepted server job alive. Observe
            # its real provider dispatch before releasing it; an empty call list
            # cannot satisfy this contract through a shared embedding cache.
            assert embedding_http.received.wait(10), "accepted index never dispatched to the provider"
            assert embedding_http.requests
            if outcome == "deadline":
                assert not embedding_http.release.is_set()
                run = client.get(f"/api/index/{corpus}/runs/latest").json()
                assert run["status"] == "indexing"
                assert "server" in result.stderr
            assert all(json.loads({key.lower(): value for key, value in item["headers"].items()}[
                "x-litellm-spend-logs-metadata"])["lane"] == "index_embeddings" for item in embedding_http.requests)
        finally:
            embedding_http.release.set()


def test_performance_benchmark_cli_refuses_another_writer_for_the_same_report(tmp_path: Path) -> None:
    output = tmp_path / "owned-report.json"
    previous = b'{"measurement": "application_http", "owner": "active-writer"}\n'
    output.write_bytes(previous)
    with output.with_name(output.name + ".lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _performance_benchmark_cli(
            "http://127.0.0.1:1", "pytest_benchmark_output_owner", tmp_path, output, "--skip-index",
        )
        assert result.returncode != 0
        assert "Report output is already owned by another benchmark" in result.stderr
        assert output.read_bytes() == previous
