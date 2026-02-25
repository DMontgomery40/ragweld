"""Tests for /api/models endpoints.

These tests verify that models.json is correctly served and filtered.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from httpx import AsyncClient

import server.api.models as models_api


@contextmanager
def _temporary_catalog_paths(data_path: Path, web_path: Path):
    old_data_path = models_api.MODELS_PATH
    old_web_path = models_api.WEB_MODELS_PATH
    models_api.MODELS_PATH = data_path
    models_api.WEB_MODELS_PATH = web_path
    try:
        yield
    finally:
        models_api.MODELS_PATH = old_data_path
        models_api.WEB_MODELS_PATH = old_web_path


@pytest.mark.asyncio
async def test_get_all_models(client: AsyncClient) -> None:
    """Verify /api/models returns the full models.json catalog."""
    response = await client.get("/api/models")
    assert response.status_code == 200
    catalog = response.json()
    assert isinstance(catalog, dict)
    assert "models" in catalog
    models = catalog["models"]
    assert isinstance(models, list)
    assert len(models) >= 50, f"Expected 50+ models, got {len(models)}"


@pytest.mark.asyncio
async def test_models_have_required_fields(client: AsyncClient) -> None:
    """Verify each model has required fields."""
    response = await client.get("/api/models")
    assert response.status_code == 200

    catalog = response.json()
    models = catalog.get("models") if isinstance(catalog, dict) else None
    assert isinstance(models, list)

    for model in models:
        assert "provider" in model, f"Model missing 'provider': {model}"
        assert "model" in model, f"Model missing 'model': {model}"
        assert "components" in model, f"Model missing 'components': {model}"
        assert isinstance(model["components"], list), f"'components' should be list: {model}"
        # context is required for GEN models but not embedding-only models
        if "GEN" in model["components"]:
            assert "context" in model, f"GEN model missing 'context': {model}"


@pytest.mark.asyncio
async def test_get_embedding_models(client: AsyncClient) -> None:
    """Verify /api/models/by-type/EMB returns only embedding models."""
    response = await client.get("/api/models/by-type/EMB")
    assert response.status_code == 200
    models = response.json()
    assert len(models) > 0, "Expected at least one embedding model"

    for model in models:
        assert "EMB" in model["components"], f"Model {model['model']} doesn't have EMB component"


@pytest.mark.asyncio
async def test_get_generation_models(client: AsyncClient) -> None:
    """Verify /api/models/by-type/GEN returns only generation models."""
    response = await client.get("/api/models/by-type/GEN")
    assert response.status_code == 200
    models = response.json()
    assert len(models) > 0, "Expected at least one generation model"

    for model in models:
        assert "GEN" in model["components"], f"Model {model['model']} doesn't have GEN component"


@pytest.mark.asyncio
async def test_get_reranker_models(client: AsyncClient) -> None:
    """Verify /api/models/by-type/RERANK returns only reranker models."""
    response = await client.get("/api/models/by-type/RERANK")
    assert response.status_code == 200
    models = response.json()
    assert len(models) > 0, "Expected at least one reranker model"

    for model in models:
        assert "RERANK" in model["components"], f"Model {model['model']} doesn't have RERANK component"


@pytest.mark.asyncio
async def test_get_providers(client: AsyncClient) -> None:
    """Verify /api/models/providers returns unique provider list."""
    response = await client.get("/api/models/providers")
    assert response.status_code == 200
    providers = response.json()
    assert isinstance(providers, list)
    assert len(providers) > 0, "Expected at least one provider"
    # Should be sorted
    assert providers == sorted(providers), "Providers should be sorted"
    # Should be unique
    assert len(providers) == len(set(providers)), "Providers should be unique"


@pytest.mark.asyncio
async def test_invalid_component_type(client: AsyncClient) -> None:
    """Verify invalid component type returns 400."""
    response = await client.get("/api/models/by-type/INVALID")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_case_insensitive_component_type(client: AsyncClient) -> None:
    """Verify component type is case-insensitive."""
    response_upper = await client.get("/api/models/by-type/EMB")
    response_lower = await client.get("/api/models/by-type/emb")
    response_mixed = await client.get("/api/models/by-type/Emb")

    assert response_upper.status_code == 200
    assert response_lower.status_code == 200
    assert response_mixed.status_code == 200

    assert len(response_upper.json()) == len(response_lower.json())


@pytest.mark.asyncio
async def test_models_by_type_matches_catalog_for_ragweld_gen_entries(client: AsyncClient) -> None:
    """Ragweld augmentation in /api/models must be reflected in /api/models/by-type/GEN."""
    all_resp = await client.get("/api/models")
    assert all_resp.status_code == 200
    all_models = all_resp.json()["models"]
    ragweld_gen_models = {
        str(m.get("model"))
        for m in all_models
        if str(m.get("provider", "")).strip().lower() == "ragweld"
    }

    gen_resp = await client.get("/api/models/by-type/GEN")
    assert gen_resp.status_code == 200
    gen_models = gen_resp.json()
    gen_ids = {str(m.get("model")) for m in gen_models}

    assert ragweld_gen_models.issubset(gen_ids)
    for model in gen_models:
        assert "GEN" in model.get("components", [])


@pytest.mark.asyncio
async def test_models_upsert_creates_entry_and_autofills_provider_base_url(
    client: AsyncClient, tmp_path: Path
) -> None:
    """POST /api/models/upsert should create a model and infer base_url from provider peers."""
    data_path = tmp_path / "models.json"
    web_path = tmp_path / "models-web.json"
    seed = {
        "currency": "USD",
        "last_updated": "2026-01-01",
        "sources": ["test"],
        "models": [
            {
                "provider": "openai",
                "family": "gen",
                "model": "gpt-seed",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.001,
                "output_per_1k": 0.002,
                "base_url": "https://proxy.example/v1",
            }
        ],
    }
    data_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    web_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    payload = {
        "provider": "openai",
        "model": "gpt-upserted",
        "family": "gen",
        "unit": "1k_tokens",
        "input_per_1k": 0.003,
        "output_per_1k": 0.004,
    }

    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["action"] == "created"
        assert body["model"]["provider"] == "openai"
        assert body["model"]["model"] == "gpt-upserted"
        assert body["model"]["base_url"] == "https://proxy.example/v1"
        assert "GEN" in body["model"]["components"]

        data_catalog = json.loads(data_path.read_text(encoding="utf-8"))
        web_catalog = json.loads(web_path.read_text(encoding="utf-8"))
        assert data_catalog == web_catalog
        created = [m for m in data_catalog["models"] if m.get("model") == "gpt-upserted"]
        assert len(created) == 1


@pytest.mark.asyncio
async def test_models_upsert_rejects_invalid_family_pricing_combo(
    client: AsyncClient, tmp_path: Path
) -> None:
    """POST /api/models/upsert must reject known invalid capability/unit/pricing combinations."""
    data_path = tmp_path / "models.json"
    web_path = tmp_path / "models-web.json"
    seed = {"currency": "USD", "last_updated": "2026-01-01", "sources": [], "models": []}
    data_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    web_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    invalid_payload = {
        "provider": "openai",
        "model": "bad-embed-model",
        "family": "embed",
        "unit": "request",
        "per_request": 0.01,
    }

    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json=invalid_payload)
        assert response.status_code == 422
        detail = str(response.json().get("detail") or "")
        assert "EMB models must use unit=1k_tokens" in detail
