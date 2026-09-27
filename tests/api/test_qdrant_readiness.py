"""Qdrant readiness uses the configured service and does not change liveness."""

import pytest
from httpx import AsyncClient

from server.config import load_config, save_config


@pytest.mark.asyncio
async def test_unreachable_qdrant_blocks_readiness_but_not_liveness(client: AsyncClient) -> None:
    original = load_config()
    config = original.model_copy(deep=True)
    config.qdrant.url = "http://127.0.0.1:1"
    save_config(config)
    try:
        ready = await client.get("/api/ready")
        live = await client.get("/api/health")
    finally:
        save_config(original)
    assert live.status_code == 200
    assert live.json()["ok"] is True
    assert ready.status_code == 503
    assert ready.json()["ready"] is False
    dependency = ready.json()["dependencies"]["qdrant"]
    assert dependency["ok"] is False
    assert dependency["error"] == "Qdrant vector store is unavailable."
    assert "qdrant.url" in dependency["operator_hint"]


@pytest.mark.asyncio
@pytest.mark.requires_qdrant
async def test_configured_qdrant_can_list_collections(client: AsyncClient) -> None:
    response = await client.get("/api/ready")
    dependency = response.json()["dependencies"]["qdrant"]
    assert dependency["ok"] is True, dependency
    assert dependency["error"] is None
    assert dependency["info"]["status"] == "collections readable"
