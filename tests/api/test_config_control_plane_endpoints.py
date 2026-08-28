"""API tests for the OSS config control plane endpoints."""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.config_control_plane import list_config_leaf_paths
from server.db.postgres import PostgresClient


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
        "tribrid_retrieval",
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
async def test_config_registry_exposes_public_operator_link_fields_on_expected_surfaces(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/config/registry")
    assert response.status_code == 200

    fields = {item["path"]: item for item in response.json()["fields"]}
    langfuse_public = fields["tracing.langfuse_public_base_url"]
    mlflow_console = fields["training.ragweld_agent_mlflow_console_base_url"]

    assert langfuse_public["integration"] == "langfuse"
    assert langfuse_public["ui_surface"] == "observability"
    assert langfuse_public["exposure_level"] == "basic"
    assert langfuse_public["secret_dependency_ids"] == ["langfuse_public_key", "langfuse_secret_key"]

    assert mlflow_console["integration"] == "mlflow"
    assert mlflow_console["ui_surface"] == "training"
    assert mlflow_console["exposure_level"] == "basic"
    assert mlflow_console["secret_dependency_ids"] == []


@pytest.mark.asyncio
async def test_get_config_readiness_surfaces_langfuse_secret_blockers(client: AsyncClient) -> None:
    old_public = os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    old_secret = os.environ.pop("LANGFUSE_SECRET_KEY", None)

    try:
        baseline = await client.get("/api/config")
        assert baseline.status_code == 200
        cfg = baseline.json()
        cfg["tracing"]["tracing_mode"] = "otel_langfuse"
        cfg["tracing"]["langfuse_enabled"] = True
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


@pytest.mark.asyncio
async def test_config_readiness_uses_deployment_gateway_urls(client: AsyncClient) -> None:
    old_litellm_url = os.environ.get("LITELLM_BASE_URL")
    old_vllm_url = os.environ.get("VLLM_BASE_URL")
    os.environ["LITELLM_BASE_URL"] = "http://127.0.0.1:7/v1"
    os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:8/v1"
    try:
        readiness = await client.get("/api/config/readiness")
        assert readiness.status_code == 200
        integrations = {item["id"]: item for item in readiness.json()["integrations"]}
    finally:
        if old_litellm_url is None:
            os.environ.pop("LITELLM_BASE_URL", None)
        else:
            os.environ["LITELLM_BASE_URL"] = old_litellm_url
        if old_vllm_url is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm_url

    assert integrations["litellm"]["links"][0]["url"] == "http://127.0.0.1:7/v1"
    assert integrations["vllm"]["links"][0]["url"] == "http://127.0.0.1:8/v1"


@pytest.mark.asyncio
async def test_gateway_registry_owns_only_litellm_client_key(client: AsyncClient) -> None:
    registry = await client.get("/api/config/registry")
    assert registry.status_code == 200
    payload = registry.json()
    fields = {item["path"] for item in payload["fields"]}
    secrets = {item["id"]: item for item in payload["secrets"]}
    integrations = {item["id"]: item for item in payload["integrations"]}

    assert not any(path.startswith("chat.openrouter.") for path in fields)
    assert not any(path.startswith("chat.local_models.") for path in fields)
    assert integrations["litellm"]["required_secret_ids"] == ["litellm_api_key"]
    assert secrets["litellm_api_key"]["optional"] is False
    assert "openrouter_api_key" not in secrets
    assert "anthropic_api_key" not in secrets
    assert "google_api_key" not in secrets
    assert "litellm" not in secrets["openai_api_key"]["integrations"]


@pytest.mark.asyncio
async def test_config_readiness_marks_missing_litellm_key_unconfigured(client: AsyncClient) -> None:
    old_key = os.environ.pop("LITELLM_API_KEY", None)
    try:
        readiness = await client.get("/api/config/readiness")
        assert readiness.status_code == 200
        payload = readiness.json()
    finally:
        if old_key is not None:
            os.environ["LITELLM_API_KEY"] = old_key

    litellm = next(item for item in payload["integrations"] if item["id"] == "litellm")
    assert litellm["state"] == "unconfigured"
    assert litellm["configured"] is False
    assert litellm["reachable"] is None
    assert litellm["missing_secret_ids"] == ["litellm_api_key"]


@pytest.mark.asyncio
@pytest.mark.requires_postgres
async def test_scoped_config_readiness_reports_a_deindexing_manifest_as_degraded(
    client: AsyncClient,
) -> None:
    corpus_id = f"readiness-deindex-{uuid.uuid4().hex[:8]}"
    config = load_config()
    pg = PostgresClient(config.indexing.postgres_url)
    tombstone = None

    try:
        await pg.connect()
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        _, tombstone = await pg.delete_index_state(
            corpus_id,
            lease_seconds=config.indexing.index_run_lease_seconds,
        )

        response = await client.get(f"/api/config/readiness?corpus_id={corpus_id}")

        assert response.status_code == 200, response.text
        retrieval = next(
            item for item in response.json()["integrations"] if item["id"] == "haystack_docling_qdrant"
        )
        assert retrieval["state"] == "degraded"
        assert retrieval["configured"] is True
        assert retrieval["reachable"] is False
        assert "generation_manifest" in retrieval["failing_checks"]
        assert corpus_id in str(retrieval["operator_hint"])
    finally:
        if tombstone is not None:
            await pg.clear_index_tombstone(corpus_id, tombstone)
        await pg.delete_corpus_with_data(corpus_id)
        await pg.disconnect()
