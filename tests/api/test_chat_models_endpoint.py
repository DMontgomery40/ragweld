"""Contract tests for GET /api/chat/models."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_chat_models_return_canonical_override_contract(client: AsyncClient) -> None:
    response = await client.get("/api/chat/models")
    assert response.status_code == 200

    payload = response.json()
    models = payload.get("models")
    assert isinstance(models, list)

    for row in models:
        override = str(row.get("override") or "")
        source = str(row.get("source") or "")
        components = row.get("components")

        assert override
        assert isinstance(components, list)
        assert "GEN" in components
        assert row.get("id")
        assert row.get("provider")

        if source == "ragweld":
            assert override.startswith("ragweld:")
        elif source == "cloud_direct":
            assert "/" in override
        elif source in {"openrouter", "local", "litellm"}:
            assert ":" in override
