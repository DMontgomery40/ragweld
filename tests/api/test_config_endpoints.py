"""API tests for config endpoints."""

import asyncio

import pytest
from httpx import AsyncClient

from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.asyncio
async def test_get_config(client: AsyncClient) -> None:
    """Test GET /api/config endpoint."""
    response = await client.get("/api/config")
    assert response.status_code == 200

    data = response.json()
    # Check for LAW's field names (from tribrid_config_model.py)
    assert "embedding" in data
    assert "fusion" in data
    assert "reranking" in data  # LAW uses 'reranking' not 'reranker'
    assert "chunking" in data   # LAW uses 'chunking' not 'chunker'
    assert "retrieval" in data
    assert "scoring" in data


@pytest.mark.asyncio
async def test_update_config(client: AsyncClient, test_config: TriBridConfig) -> None:
    """Test PUT /api/config endpoint."""
    response = await client.put("/api/config", json=test_config.model_dump())
    assert response.status_code == 200

    data = response.json()
    # LAW's EmbeddingConfig uses 'embedding_type' not 'provider'
    assert data["embedding"]["embedding_type"] == test_config.embedding.embedding_type


@pytest.mark.asyncio
async def test_update_config_section(client: AsyncClient) -> None:
    """Test PATCH /api/config/{section} endpoint."""
    updates = {"top_k": 30}
    response = await client.patch("/api/config/vector_search", json=updates)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reset_config(client: AsyncClient) -> None:
    """Test POST /api/config/reset endpoint."""
    response = await client.post("/api/config/reset")
    assert response.status_code == 200

    data = response.json()
    # Should return default config
    assert "embedding" in data


@pytest.mark.asyncio
async def test_invalid_config_section(client: AsyncClient) -> None:
    """Test updating invalid config section."""
    response = await client.patch("/api/config/invalid_section", json={})
    assert response.status_code in [400, 404, 422]


@pytest.mark.asyncio
async def test_get_config_unknown_corpus_does_not_autocreate(client: AsyncClient) -> None:
    """GET /api/config for an unknown corpus must 404 and must not create a corpus row."""
    before = await client.get("/api/corpora")
    assert before.status_code == 200
    before_ids = {c.get("corpus_id") for c in before.json() if isinstance(c, dict)}

    missing_id = "does_not_exist_corpus__should_404"
    resp = await client.get("/api/config", params={"corpus_id": missing_id})
    assert resp.status_code == 404

    after = await client.get("/api/corpora")
    assert after.status_code == 200
    after_ids = {c.get("corpus_id") for c in after.json() if isinstance(c, dict)}

    assert missing_id not in after_ids
    assert after_ids == before_ids


@pytest.mark.asyncio
async def test_concurrent_section_patches_do_not_lose_updates(client: AsyncClient) -> None:
    """Concurrent PATCHes to different sections must not clobber each other."""
    corpus_id = "test_concurrent_config_patches"
    corpus_path = "."

    # Create corpus (idempotent across reruns)
    existing = await client.get("/api/corpora")
    assert existing.status_code == 200
    if not any(c.get("corpus_id") == corpus_id for c in existing.json() if isinstance(c, dict)):
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": corpus_path, "description": "test corpus"},
        )
        assert created.status_code == 200

    try:
        # Seed cache + per-corpus config row.
        seeded = await client.get("/api/config", params={"corpus_id": corpus_id})
        assert seeded.status_code == 200

        # Two different sections patched concurrently should both stick.
        tokenization_patch = client.patch(
            "/api/config/tokenization",
            params={"corpus_id": corpus_id},
            json={"strategy": "whitespace"},
        )
        indexing_patch = client.patch(
            "/api/config/indexing",
            params={"corpus_id": corpus_id},
            json={"large_file_mode": "read_all"},
        )

        tokenization_resp, indexing_resp = await asyncio.gather(tokenization_patch, indexing_patch)
        assert tokenization_resp.status_code == 200
        assert indexing_resp.status_code == 200

        final = await client.get("/api/config", params={"corpus_id": corpus_id})
        assert final.status_code == 200
        cfg = final.json()
        assert str(cfg["tokenization"]["strategy"]).lower() == "whitespace"
        assert str(cfg["indexing"]["large_file_mode"]).lower() == "read_all"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
