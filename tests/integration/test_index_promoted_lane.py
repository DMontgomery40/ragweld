"""End-to-end: index a corpus through the API onto the promoted Postgres + Qdrant + Neo4j lane.

Runs only against live services (strict lane provisions disposable ones). No mocks.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.config import load_config
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
        status = await qdrant.status(corpus_id)
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

        stats = await client.get("/api/index/stats", params={"corpus_id": corpus_id})
        assert stats.status_code == 200, stats.text
        storage = stats.json()["storage_breakdown"]
        assert int(storage["qdrant_points"]) == chunk_rows
        assert int(storage["qdrant_dense_vector_bytes"]) == chunk_rows * int(cfg.embedding.embedding_dim) * 4

        # Deleting the index removes the Qdrant generation; the legs then fail closed (chunk rows are gone too).
        deleted = await client.delete(f"/api/index/{corpus_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_chunks"] == chunk_rows
        assert deleted.json()["deleted_vector_collections"] >= 1
        assert await qdrant.status(corpus_id) is None
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
