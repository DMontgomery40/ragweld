"""Tests for health endpoints."""

import os

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


@pytest.mark.asyncio
async def test_ready_reports_gateway_and_serving_failures_separately(client: AsyncClient) -> None:
    old_litellm = os.environ.get("LITELLM_BASE_URL")
    old_vllm = os.environ.get("VLLM_BASE_URL")
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    try:
        response = await client.get("/api/ready")
    finally:
        if old_litellm is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_litellm
        if old_vllm is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm

    assert response.status_code == 503
    dependencies = response.json()["dependencies"]
    assert dependencies["litellm"]["ok"] is False
    assert dependencies["vllm"]["ok"] is False
    assert "operator_hint" in dependencies["litellm"]
    assert "operator_hint" in dependencies["vllm"]


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
