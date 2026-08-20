"""Tests for health endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_returns_pydantic_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["ok"] is True
    assert data["status"] in {"healthy", "unhealthy", "unknown"}
    assert "ts" in data
    assert isinstance(data.get("services"), dict)
    assert data["services"]["api"]["status"] == "up"


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_ready_unknown_corpus_does_not_crash(client: AsyncClient) -> None:
    """GET /api/ready with a missing corpus_id should return 200 + a readiness payload (not 500)."""
    corpora = await client.get("/api/corpora")
    assert corpora.status_code == 200
    existing_ids = {
        (c.get("corpus_id") or c.get("repo_id"))
        for c in corpora.json()
        if isinstance(c, dict)
    }

    missing_id = "does_not_exist_corpus__ready"
    assert missing_id not in existing_ids

    resp = await client.get("/api/ready", params={"corpus_id": missing_id})
    assert resp.status_code == 200

    data = resp.json()
    assert data.get("corpus_id") == missing_id
    assert data.get("ready") is False
    assert "corpus_error" in data
    assert "Corpus not found" in str(data.get("corpus_error"))
