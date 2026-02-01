"""Tests for /api/models endpoints.

These tests verify that models.json is correctly served and filtered.
"""
import pytest
from httpx import AsyncClient


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
