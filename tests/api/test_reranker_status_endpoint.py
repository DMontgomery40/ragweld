"""API tests for reranker status endpoint (no DB required)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reranker_status_has_message_and_shape(client: AsyncClient) -> None:
    res = await client.get("/api/reranker/status")
    assert res.status_code == 200
    data = res.json()

    assert isinstance(data, dict)
    assert set(["running", "progress", "task", "message"]).issubset(set(data.keys()))
    assert isinstance(data["running"], bool)
    assert isinstance(data["progress"], int) or isinstance(data["progress"], float)
    assert isinstance(data["task"], str)
    assert isinstance(data["message"], str)
