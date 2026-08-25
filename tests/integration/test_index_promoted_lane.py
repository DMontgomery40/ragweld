"""End-to-end: index a corpus through the API onto the promoted Postgres + Qdrant + Neo4j lane.

Runs only against live services (strict lane provisions disposable ones). No mocks.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from server.config import load_config
from server.main import app
from server.db.postgres import PostgresClient
from server.retrieval.contracts import sparse_contract_from_config
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"


def _metric_value(metrics_text: str, name: str) -> float:
    """Return the value of an unlabeled Prometheus series (0.0 when absent)."""
    for line in metrics_text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split(" ", 1)[1].strip())
    return 0.0


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
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


async def test_index_search_and_delete_on_promoted_lane(client: AsyncClient) -> None:
    corpus_id = f"promoted-lane-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    qdrant = QdrantChunkStore(load_config())
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
        )
        assert created.status_code in (200, 201), created.text

        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        cfg.vector_search.enabled = True
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = True
        cfg.graph_search.mode = "chunk"
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_lexical_graph = True
        cfg.graph_indexing.store_chunk_embeddings = True
        cfg.graph_indexing.semantic_kg_enabled = False
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = 0
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        metrics_before = await client.get("/metrics")
        assert metrics_before.status_code == 200
        runs_before = _metric_value(metrics_before.text, "tribrid_index_runs_total")
        duration_count_before = _metric_value(metrics_before.text, "tribrid_index_duration_seconds_count")

        started = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True},
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final

        # Postgres holds the chunk rows + contracts; Qdrant holds a promoted generation with one point per chunk.
        corpus = await pg.get_corpus(corpus_id)
        assert corpus is not None
        assert corpus["embedding_dimensions"] == int(cfg.embedding.embedding_dim)
        assert corpus["sparse_contract"] == sparse_contract_from_config(cfg)
        chunk_rows = await pg.count_chunks(corpus_id)
        assert chunk_rows > 0
        generation = await pg.get_generation(corpus_id)
        assert generation and generation["qdrant_collection"] and generation["graph_repo_id"], generation
        status = await qdrant.status(corpus_id, physical=generation["qdrant_collection"])
        assert status is not None, "promoted Qdrant generation missing"
        assert status.points == chunk_rows
        assert status.dense_points == chunk_rows
        assert status.dense_dimensions == int(cfg.embedding.embedding_dim)
        # A real index run increments the index metrics and sets the chunk gauge to the promoted count.
        metrics_after = await client.get("/metrics")
        assert metrics_after.status_code == 200
        assert _metric_value(metrics_after.text, "tribrid_index_runs_total") == pytest.approx(runs_before + 1.0)
        assert _metric_value(metrics_after.text, "tribrid_index_duration_seconds_count") == pytest.approx(
            duration_count_before + 1.0
        )
        assert _metric_value(metrics_after.text, "tribrid_chunks_indexed_current") == pytest.approx(float(chunk_rows))
        stored_chunks = await pg.list_chunks_for_repo(corpus_id, limit=5)
        assert stored_chunks and all(ch.metadata.get("extraction") == "direct" for ch in stored_chunks)
        assert all(ch.embedding is None for ch in stored_chunks)

        # All three legs return results for a grounded query.
        body = {
            "query": "How often is the salinity sensor calibrated?",
            "corpus_id": corpus_id,
            "top_k": 8,
            "include_vector": True,
            "include_sparse": True,
            "include_graph": True,
            "cache_mode": "bypass",
        }
        search = await client.post("/api/search", json=body)
        assert search.status_code == 200, search.text
        payload = search.json()
        matches = payload["matches"]
        assert matches, payload
        debug = payload["debug"]
        assert int(debug["fusion_vector_results"]) > 0
        assert int(debug["fusion_sparse_results"]) > 0
        assert int(debug["fusion_graph_hydrated_chunks"]) > 0
        per_corpus = debug["fusion_per_corpus"][corpus_id]
        assert per_corpus["fusion_sparse_engine"] == "qdrant_sparse_idf"
        assert any("calibrat" in m["content"].lower() for m in matches)
        assert all(m["metadata"].get("corpus_id") == corpus_id for m in matches)

        # Sparse-only and vector-only requests both succeed on the same generation.
        for legs in ({"include_vector": False, "include_graph": False}, {"include_sparse": False, "include_graph": False}):
            res = await client.post("/api/search", json={**body, **legs})
            assert res.status_code == 200, res.text
            assert res.json()["matches"], legs

        # A NON-forced re-index of an already indexed corpus must rebuild through
        # staging and promote (2026-08-25 drive finding M5: it returned cached
        # stats without writing the staging corpus and the promotion failed with
        # "Staging corpus not found", leaving a permanent error run).
        reindex = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert reindex.status_code == 200, reindex.text
        final_reindex = await _wait_for_index(client, corpus_id)
        assert final_reindex["status"] == "complete", final_reindex
        assert final_reindex.get("error") in (None, ""), final_reindex
        assert await pg.count_chunks(corpus_id) == chunk_rows
        regeneration = await pg.get_generation(corpus_id)
        assert regeneration and regeneration["run_id"] != generation["run_id"], regeneration
        restatus = await qdrant.status(corpus_id, physical=regeneration["qdrant_collection"])
        assert restatus is not None and restatus.points == chunk_rows
        # The superseded generation was retired after the commit (reads as wiped).
        retired = await qdrant.status(corpus_id, physical=generation["qdrant_collection"])
        assert retired is not None and retired.physical_collection is None, retired
        assert (await qdrant.count_points(regeneration["qdrant_collection"])) == chunk_rows
        latest_run = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert latest_run.status_code == 200, latest_run.text
        assert latest_run.json()["status"] == "complete", latest_run.json()
        assert latest_run.json().get("error") in (None, ""), latest_run.json()
        after_reindex = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert after_reindex.status_code == 200 and after_reindex.json()["matches"], after_reindex.text

        # A run that fails before promotion must leave the active index and its
        # process-level stats exactly as they were (stats are published only
        # after the Postgres/Qdrant/Neo4j cutover completes).
        stats_before = (await client.get("/api/index/stats", params={"corpus_id": corpus_id})).json()
        # A path the API cannot read is refused up front (it used to "complete" with 0 files).
        missing = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH / "does-not-exist"), "force_reindex": False},
        )
        assert missing.status_code == 400, missing.text
        # A readable but empty directory starts a run that fails instead of promoting an empty index.
        empty_dir = tempfile.mkdtemp(prefix="ragweld-empty-corpus-")
        try:
            bogus = await client.post(
                "/api/index", json={"corpus_id": corpus_id, "repo_path": empty_dir, "force_reindex": False}
            )
            assert bogus.status_code == 200, bogus.text
            failed = await _wait_for_index(client, corpus_id)
        finally:
            os.rmdir(empty_dir)
        assert failed["status"] == "error", failed
        assert "No indexable files" in str(failed.get("error") or ""), failed
        stats_after = (await client.get("/api/index/stats", params={"corpus_id": corpus_id})).json()
        assert stats_after == stats_before, "a failed run must not touch the active index stats"
        assert await pg.count_chunks(corpus_id) == chunk_rows
        still = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert still.status_code == 200 and still.json()["matches"], still.text

        # The MCP probe goes through the mounted Streamable HTTP transport and the
        # registered `search` tool (mcp.default_mode), not an HTTP shortcut. The
        # MCP session manager lives in the app lifespan, so run this leg under it.
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as mcp_client:
                probe = await mcp_client.post(
                    "/api/mcp/probe",
                    params={"corpus_id": corpus_id},
                    json={"question": "How often is the salinity sensor calibrated?", "top_k": 5},
                )
                assert probe.status_code == 200, probe.text
                probe_payload = probe.json()
                assert probe_payload["tool"] == "search" and probe_payload["transport_url"].endswith("/mcp/")
                assert probe_payload["mode"] == cfg.mcp.default_mode and probe_payload["top_k"] == 5
                assert probe_payload["results"] and any(
                    "calibrat" in r["content"].lower() for r in probe_payload["results"]
                )
                sparse_only = await mcp_client.post(
                    "/api/mcp/probe",
                    params={"corpus_id": corpus_id},
                    json={"question": "How often is the salinity sensor calibrated?", "mode": "sparse_only", "top_k": 3},
                )
                assert sparse_only.status_code == 200, sparse_only.text
                assert sparse_only.json()["mode"] == "sparse_only" and len(sparse_only.json()["results"]) <= 3
                assert all(r["source"] == "sparse" for r in sparse_only.json()["results"])

        # Retrieval request/latency metrics are measured on the shared fusion lane,
        # so chat retrieval counts exactly like /api/search (finding M9: chat never
        # incremented them and the on-call p95 rendered NaN).
        m0 = await client.get("/metrics")
        reqs0 = _metric_value(m0.text, "tribrid_search_requests_total")
        lat0 = _metric_value(m0.text, "tribrid_search_latency_seconds_count")
        counted_search = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert counted_search.status_code == 200, counted_search.text
        chat = await client.post(
            "/api/chat",
            json={
                "message": "How often is the salinity sensor calibrated?",
                "corpus_id": corpus_id,
                "sources": {"corpus_ids": [corpus_id]},
                "stream": False,
                "cache_mode": "bypass",
            },
        )
        # LiteLLM is disabled in this corpus config, so generation fails closed with
        # the typed 503 -- after retrieval ran on the fusion lane.
        assert chat.status_code in (200, 503), chat.text
        m1 = await client.get("/metrics")
        assert _metric_value(m1.text, "tribrid_search_requests_total") == pytest.approx(reqs0 + 2.0)
        assert _metric_value(m1.text, "tribrid_search_latency_seconds_count") == pytest.approx(lat0 + 2.0)

        stats = await client.get("/api/index/stats", params={"corpus_id": corpus_id})
        assert stats.status_code == 200, stats.text
        storage = stats.json()["storage_breakdown"]
        assert int(storage["qdrant_points"]) == chunk_rows
        assert int(storage["qdrant_dense_vector_bytes"]) == chunk_rows * int(cfg.embedding.embedding_dim) * 4
        # Dashboard storage truth on the real stores (replaces the former fake-Postgres test).
        assert int(storage["chunks_bytes"]) > 0
        assert int(storage["postgres_total_bytes"]) >= int(storage["chunks_bytes"])
        assert int(storage["total_storage_bytes"]) == (
            int(storage["postgres_total_bytes"]) + int(storage["qdrant_dense_vector_bytes"]) + int(storage["neo4j_store_bytes"])
        )
        dashboard_status = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert dashboard_status.status_code == 200, dashboard_status.text
        dashboard = dashboard_status.json()
        assert dashboard["running"] is False
        assert dashboard["metadata"]["corpus_id"] == corpus_id
        assert dashboard["metadata"]["current_repo"] == corpus_id
        assert int(dashboard["metadata"]["total_storage"]) == int(storage["total_storage_bytes"])

        # Deleting the index removes the Qdrant generation; the legs then fail closed (chunk rows are gone too).
        deleted = await client.delete(f"/api/index/{corpus_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_chunks"] == chunk_rows
        assert deleted.json()["deleted_vector_collections"] >= 1
        assert await pg.get_generation(corpus_id) is None
        cleared = await pg.get_corpus(corpus_id)
        assert cleared is not None and cleared["last_indexed"] is None and cleared["embedding_dimensions"] == 0
        # A de-indexed corpus reports empty legs, not a missing-generation failure.
        empty = await client.post("/api/search", json=body)
        assert empty.status_code == 200, empty.text
        assert empty.json()["matches"] == []

        removed = await client.delete(f"/api/corpora/{corpus_id}")
        assert removed.status_code == 200, removed.text
    finally:
        config_store._store = None
        try:
            await qdrant.delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()
