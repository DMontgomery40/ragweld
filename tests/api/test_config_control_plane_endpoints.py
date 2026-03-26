"""API tests for the OSS config control plane endpoints."""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

from server.config_control_plane import list_config_leaf_paths


@pytest.mark.asyncio
async def test_get_config_registry_covers_all_leaf_paths(client: AsyncClient) -> None:
    response = await client.get("/api/config/registry")
    assert response.status_code == 200

    payload = response.json()
    field_paths = [item["path"] for item in payload["fields"]]

    assert len(field_paths) == len(set(field_paths))
    assert set(field_paths) == set(list_config_leaf_paths())

    sample = payload["fields"][0]
    assert "path" in sample
    assert "section" in sample
    assert "type" in sample
    assert "scope" in sample
    assert "integration" in sample
    assert "exposure_level" in sample
    assert "impact" in sample
    assert "secret_dependency_ids" in sample
    assert "ui_surface" in sample

    integration_ids = {item["id"] for item in payload["integrations"]}
    assert {
        "litellm",
        "vllm",
        "flyte",
        "haystack_docling_qdrant",
        "neo4j",
        "unsloth",
        "mlflow",
        "ragas",
        "promptfoo",
        "langfuse",
        "otel_grafana_stack",
        "shell_ui",
    }.issubset(integration_ids)


@pytest.mark.asyncio
async def test_get_config_readiness_surfaces_langfuse_secret_blockers(client: AsyncClient) -> None:
    old_public = os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    old_secret = os.environ.pop("LANGFUSE_SECRET_KEY", None)

    try:
        baseline = await client.get("/api/config")
        assert baseline.status_code == 200
        cfg = baseline.json()
        cfg["tracing"]["tracing_mode"] = "otel_langfuse"
        cfg["tracing"]["langfuse_enabled"] = 1
        cfg["tracing"]["langfuse_base_url"] = "http://127.0.0.1:3005"
        cfg["tracing"]["langfuse_project"] = "ragweld"

        saved = await client.put("/api/config", json=cfg)
        assert saved.status_code == 200

        readiness = await client.get("/api/config/readiness")
        assert readiness.status_code == 200
        payload = readiness.json()

        langfuse = next(item for item in payload["integrations"] if item["id"] == "langfuse")
        assert langfuse["state"] == "unconfigured"
        assert sorted(langfuse["missing_secret_ids"]) == ["langfuse_public_key", "langfuse_secret_key"]

        statuses = {
            item["requirement"]["id"]: item
            for item in payload["secrets"]
        }
        assert statuses["langfuse_public_key"]["configured"] is False
        assert "langfuse" in statuses["langfuse_public_key"]["blocker_for_integrations"]
        assert statuses["langfuse_secret_key"]["configured"] is False
    finally:
        if old_public is None:
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
        else:
            os.environ["LANGFUSE_PUBLIC_KEY"] = old_public
        if old_secret is None:
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
        else:
            os.environ["LANGFUSE_SECRET_KEY"] = old_secret
