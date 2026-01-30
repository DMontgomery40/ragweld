"""API tests for config endpoints."""

import pytest
from httpx import AsyncClient


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
async def test_update_config(client: AsyncClient, test_config) -> None:
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
