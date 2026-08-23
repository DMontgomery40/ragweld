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
    old_gateway_path = models_api.LITELLM_CONFIG_PATH
    models_api.MODELS_PATH = data_path
    models_api.WEB_MODELS_PATH = web_path
    models_api.LITELLM_CONFIG_PATH = data_path.parent / "litellm-config.yaml"
    try:
        yield
    finally:
        models_api.MODELS_PATH = old_data_path
        models_api.WEB_MODELS_PATH = old_web_path
        models_api.LITELLM_CONFIG_PATH = old_gateway_path


def _local_serving_row() -> dict:
    return {
        "provider": "ragweld",
        "family": "Qwen3.8-27B",
        "model": "mlx-community/Qwen3.8-27B-4bit",
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 32768,
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "base_url": "http://host.docker.internal:58080/v1",
        "gateway_alias": "ragweld-local",
        "gateway_upstream": "openai/ragweld-local",
    }


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
        assert "selection_roles" in model, f"Model missing 'selection_roles': {model}"
        assert isinstance(model["selection_roles"], list), f"'selection_roles' should be list: {model}"
        assert "selection_status" in model, f"Model missing 'selection_status': {model}"
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
async def test_models_by_type_keeps_generation_rows_catalog_only(client: AsyncClient) -> None:
    """Provider GEN rows remain pricing evidence, never runtime route choices."""
    gen_resp = await client.get("/api/models/by-type/GEN")
    assert gen_resp.status_code == 200
    gen_models = gen_resp.json()

    assert gen_models
    for model in gen_models:
        assert "GEN" in model.get("components", [])
        assert "generation" not in model.get("selection_roles", [])


@pytest.mark.asyncio
async def test_models_expose_truthful_selection_metadata(client: AsyncClient) -> None:
    response = await client.get("/api/models")
    assert response.status_code == 200
    models = response.json()["models"]

    openai_embed = next(
        m for m in models
        if str(m.get("provider", "")).strip().lower() == "openai" and "EMB" in m.get("components", [])
    )
    assert openai_embed["selection_status"] == "runtime_selectable"
    assert "embedding_provider" in openai_embed["selection_roles"]

    cohere_rerank = next(
        m for m in models
        if str(m.get("provider", "")).strip().lower() == "cohere" and "RERANK" in m.get("components", [])
    )
    assert cohere_rerank["selection_status"] == "runtime_selectable"
    assert "reranker_cloud" in cohere_rerank["selection_roles"]

    catalog_only_embed = next(
        m for m in models
        if str(m.get("provider", "")).strip().lower() in {"cohere", "voyage", "jina", "google", "mistral"}
        and "EMB" in m.get("components", [])
    )
    assert catalog_only_embed["selection_status"] == "catalog_only"
    assert "embedding_provider" not in catalog_only_embed["selection_roles"]
    assert "Catalog entry only" in str(catalog_only_embed.get("selection_reason") or "")

    catalog_only_rerank = next(
        m for m in models
        if str(m.get("provider", "")).strip().lower() != "cohere" and "RERANK" in m.get("components", [])
    )
    assert catalog_only_rerank["selection_status"] == "catalog_only"
    assert "reranker_cloud" not in catalog_only_rerank["selection_roles"]
    assert "Catalog entry only" in str(catalog_only_rerank.get("selection_reason") or "")


@pytest.mark.asyncio
async def test_models_upsert_gen_row_becomes_gateway_route_and_regenerates_litellm_config(
    client: AsyncClient, tmp_path: Path
) -> None:
    """POST /api/models/upsert for a GEN row derives the gateway fields and rewrites the YAML."""
    data_path = tmp_path / "models.json"
    web_path = tmp_path / "models-web.json"
    gateway_path = tmp_path / "litellm-config.yaml"
    seed = {
        "currency": "USD",
        "last_updated": "2026-01-01",
        "sources": ["test"],
        "models": [
            _local_serving_row(),
            {
                "provider": "openai",
                "family": "gpt-seed",
                "model": "openai/gpt-seed",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.001,
                "output_per_1k": 0.002,
                "context": 128000,
                "base_url": "https://openrouter.ai/api/v1",
                "gateway_alias": "openai.gpt-seed",
                "gateway_upstream": "openrouter/openai/gpt-seed",
            },
        ],
    }
    data_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    web_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    gateway_path.write_text("stale: true\n", encoding="utf-8")

    payload = {
        "provider": "openai",
        "model": "openai/gpt-upserted",
        "family": "gen",
        "unit": "1k_tokens",
        "input_per_1k": 0.003,
        "output_per_1k": 0.004,
        "context": 64000,
    }

    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json=payload)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["action"] == "created"
        assert body["model"]["provider"] == "openai"
        assert body["model"]["model"] == "openai/gpt-upserted"
        assert body["model"]["gateway_alias"] == "openai.gpt-upserted"
        assert body["model"]["gateway_upstream"] == "openrouter/openai/gpt-upserted"
        assert body["model"]["base_url"] == "https://openrouter.ai/api/v1"
        assert "GEN" in body["model"]["components"]
        assert body["model"]["selection_status"] == "catalog_only"
        assert body["model"]["selection_roles"] == []

        data_catalog = json.loads(data_path.read_text(encoding="utf-8"))
        web_catalog = json.loads(web_path.read_text(encoding="utf-8"))
        assert data_catalog == web_catalog
        created = [m for m in data_catalog["models"] if m.get("model") == "openai/gpt-upserted"]
        assert len(created) == 1

        import yaml

        rendered = yaml.safe_load(gateway_path.read_text(encoding="utf-8"))
        assert [row["model_name"] for row in rendered["model_list"]] == [
            "ragweld-local",
            "openai.gpt-seed",
            "openai.gpt-upserted",
        ]
        assert rendered["model_list"][2]["litellm_params"] == {
            "model": "openrouter/openai/gpt-upserted",
            "api_key": "os.environ/OPENROUTER_API_KEY",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "match"),
    [
        (
            {"provider": "openai", "model": "gpt-direct", "family": "gen", "unit": "1k_tokens", "input_per_1k": 0.1, "output_per_1k": 0.2},
            "OpenRouter routes",
        ),
        (
            {"provider": "anthropic", "model": "openai/gpt-5.4-mini", "family": "gen", "unit": "1k_tokens", "input_per_1k": 0.1, "output_per_1k": 0.2},
            "provider to equal",
        ),
    ],
)
async def test_models_upsert_rejects_generation_rows_the_gateway_cannot_serve(
    client: AsyncClient, tmp_path: Path, payload: dict, match: str
) -> None:
    data_path = tmp_path / "models.json"
    web_path = tmp_path / "models-web.json"
    seed = {"currency": "USD", "sources": [], "models": [_local_serving_row()]}
    data_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    web_path.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")

    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json=payload)

    assert response.status_code == 422
    assert match in str(response.json().get("detail") or "")
    assert json.loads(data_path.read_text(encoding="utf-8")) == seed, "a rejected upsert never writes"


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
