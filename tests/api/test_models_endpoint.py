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
            "num_retries": 0,
            "max_retries": 0,
        }
        assert all(
            row["litellm_params"]["num_retries"] == row["litellm_params"]["max_retries"] == 0
            for row in rendered["model_list"]
        )


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
@pytest.mark.parametrize("model", ["text-embedding-3-small", "text-embedding-3-large"])
@pytest.mark.parametrize("existing_family", [None, "original", "mission-embedding-family"])
async def test_models_upsert_native_embeddings_preserves_route_and_catalog_trio(
    client: AsyncClient, tmp_path: Path, model: str, existing_family: str | None,
) -> None:
    import yaml

    original = json.loads(models_api.MODELS_PATH.read_text(encoding="utf-8"))
    embedding = next(row for row in original["models"] if row["provider"] == "openai" and row["model"] == model)
    existing = existing_family is not None
    if existing_family not in {None, "original"}:
        embedding["family"] = existing_family
    expected_family = embedding["family"] if existing else model
    generation = next(row for row in original["models"] if row["provider"] == "openai" and row["components"] == ["GEN"])
    rows = [_local_serving_row(), generation, *([embedding] if existing else [])]
    seed = {"currency": "USD", "sources": [], "models": rows}
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    gateway_path = tmp_path / "litellm-config.yaml"
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed), encoding="utf-8")
    gateway_path.write_text("stale: true\n", encoding="utf-8")
    payload = {
        "provider": "openai", "model": model, "family": "embed", "unit": "1k_tokens",
        "embed_per_1k": 0.00012, "dimensions": embedding["dimensions"], "notes": "Updated native embedding price",
    }
    with _temporary_catalog_paths(data_path, web_path):
        first = await client.post("/api/models/upsert", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["action"] == ("updated" if existing else "created")
        assert first.json()["model"]["family"] == expected_family
        # Repeated saves must neither duplicate the alias nor inherit the GEN URL.
        repeated = await client.post("/api/models/upsert", json=payload)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["action"] == "updated"
        result = repeated.json()["model"]
        assert result["family"] == expected_family
        assert result["gateway_alias"] == f"openai.{model}"
        assert result["gateway_upstream"] == f"openai/{model}"
        assert result.get("base_url") is None
        assert result["embed_per_1k"] == payload["embed_per_1k"]
        assert result["dimensions"] == payload["dimensions"]
        assert result["notes"] == payload["notes"]
        catalog = json.loads(data_path.read_text(encoding="utf-8"))
        assert catalog == json.loads(web_path.read_text(encoding="utf-8"))
        persisted = [row for row in catalog["models"] if row["model"] == model]
        assert len(persisted) == 1
        assert persisted[0]["family"] == expected_family
        rendered = yaml.safe_load(gateway_path.read_text(encoding="utf-8"))
        route = next(row for row in rendered["model_list"] if row["model_name"] == f"openai.{model}")
        assert route == {
            "model_name": f"openai.{model}", "model_info": {"mode": "embedding"},
            "litellm_params": {
                "model": f"openai/{model}", "api_key": "os.environ/OPENAI_API_KEY", "num_retries": 0, "max_retries": 0,
            },
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("model,capacity", [("text-embedding-3-small", 1536), ("text-embedding-3-large", 3072)])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("invalid", ["zero", "below_minimum", "shortened", "below_capacity", "above_capacity", "other_model"])
async def test_native_embedding_capacity_upserts_reject_false_capabilities_atomically(
    client: AsyncClient, tmp_path: Path, model: str, capacity: int, existing: bool, invalid: str,
) -> None:
    from server.gateway_catalog import gateway_rows_snapshot, warm_gateway_catalog

    dimensions = {"zero": 0, "below_minimum": 1, "shortened": 128, "below_capacity": capacity - 1,
                  "above_capacity": capacity + 1, "other_model": 3072 if capacity == 1536 else 1536}[invalid]
    embedding = {"provider": "openai", "model": model, "family": model, "components": ["EMB"],
                 "dimensions": capacity, "embed_per_1k": 0.0001,
                 "gateway_alias": f"openai.{model}", "gateway_upstream": f"openai/{model}"}
    seed = {"currency": "USD", "sources": [], "models": [_local_serving_row(), *([embedding] if existing else [])]}
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    gateway_path = tmp_path / "litellm-config.yaml"
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed))
    gateway_path.write_text("unchanged: true\n")
    before = {path: path.read_bytes() for path in (data_path, web_path, gateway_path)}
    warm_gateway_catalog(data_path)
    routes_before = gateway_rows_snapshot(data_path, capability=None)
    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json={
            "provider": "openai", "model": model, "family": "embed", "unit": "1k_tokens",
            "embed_per_1k": 0.00012, "dimensions": dimensions,
        })
    assert response.status_code == 422, response.text
    detail = str(response.json()["detail"]).lower()
    assert "dimensions" in detail
    if dimensions > 0:
        assert "capacity" in detail
    assert {path: path.read_bytes() for path in before} == before
    assert gateway_rows_snapshot(data_path, capability=None) == routes_before


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("payload,components", [
    ({"provider": "openai", "model": "openai/gpt-5.6-sol", "family": "gen", "unit": "1k_tokens",
      "input_per_1k": 0.001, "output_per_1k": 0.002, "context": 128000}, ["GEN"]),
    ({"provider": "cohere", "model": "embed-v4.0", "family": "embed", "unit": "1k_tokens",
      "embed_per_1k": 0.0001, "dimensions": 1024}, ["EMB"]),
    ({"provider": "cohere", "model": "rerank-v3.5", "family": "rerank", "unit": "request",
      "per_request": 0.0001}, ["RERANK"]),
    ({"provider": "acme", "model": "acme/deployment-model", "family": "misc", "unit": "request",
      "per_request": 0.0001}, []),
])
async def test_upsert_capability_selector_never_replaces_model_family(
    client: AsyncClient, tmp_path: Path, existing: bool, payload: dict, components: list[str],
) -> None:
    expected_family = "preserved-domain-family" if existing else payload["model"].rsplit("/", 1)[-1]
    seed_row = {**payload, "family": expected_family, "components": components}
    if components == ["GEN"]:
        seed_row.update({
            "gateway_alias": "openai.gpt-5.6-sol", "gateway_upstream": "openrouter/openai/gpt-5.6-sol",
            "base_url": "https://openrouter.ai/api/v1",
        })
    seed = {"currency": "USD", "sources": [], "models": [_local_serving_row(), *([seed_row] if existing else [])]}
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed), encoding="utf-8")
    with _temporary_catalog_paths(data_path, web_path):
        for expected_action in (("updated" if existing else "created"), "updated"):
            response = await client.post("/api/models/upsert", json=payload)
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["action"] == expected_action
            assert result["model"]["family"] == expected_family
            assert result["model"]["components"] == components
    catalog = json.loads(data_path.read_text(encoding="utf-8"))
    assert catalog == json.loads(web_path.read_text(encoding="utf-8"))
    persisted = [row for row in catalog["models"] if row["model"] == payload["model"]]
    assert len(persisted) == 1
    assert persisted[0]["family"] == expected_family


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["text-embedding-3-small", "text-embedding-3-large"])
@pytest.mark.parametrize("base_url", ["https://api.openai.com/v1", "https://openrouter.ai/api/v1"])
async def test_native_embedding_url_override_is_rejected_without_changing_catalog_trio(
    client: AsyncClient, tmp_path: Path, model: str, base_url: str,
) -> None:
    original = json.loads(models_api.MODELS_PATH.read_text(encoding="utf-8"))
    embedding = next(row for row in original["models"] if row["provider"] == "openai" and row["model"] == model)
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    gateway_path = tmp_path / "litellm-config.yaml"
    seed = {"currency": "USD", "sources": [], "models": [_local_serving_row(), embedding]}
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed), encoding="utf-8")
    gateway_path.write_text("unchanged: true\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (data_path, web_path, gateway_path)}
    with _temporary_catalog_paths(data_path, web_path):
        response = await client.post("/api/models/upsert", json={
            "provider": "openai", "model": model, "family": "embed", "unit": "1k_tokens",
            "embed_per_1k": embedding["embed_per_1k"], "base_url": base_url,
        })
    assert response.status_code == 422
    assert {path: path.read_bytes() for path in before} == before


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


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["text-embedding-ada-002", "text-embedding-future-fixture"])
@pytest.mark.parametrize("existing", [False, True])
async def test_unrouted_openai_embeddings_stay_catalog_only_on_create_update_and_reload(
    client: AsyncClient, tmp_path: Path, model: str, existing: bool,
) -> None:
    import yaml

    row = {"provider": "openai", "model": model, "family": "fixture-lineage",
           "components": ["EMB"], "dimensions": 1536, "embed_per_1k": 0.0001}
    seed = {"currency": "USD", "sources": [], "models": [_local_serving_row(), *([row] if existing else [])]}
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed))
    with _temporary_catalog_paths(data_path, web_path):
        for action in (("updated" if existing else "created"), "updated"):
            response = await client.post("/api/models/upsert", json={
                "provider": "openai", "model": model, "family": "embed", "unit": "1k_tokens",
                "embed_per_1k": 0.0001, "dimensions": 1536,
            })
            assert response.status_code == 200, response.text
            assert response.json()["action"] == action
            saved = response.json()["model"]
            assert saved["selection_status"] == "catalog_only"
            assert "embedding_provider" not in saved["selection_roles"]
            assert "native embedding route" in saved["selection_reason"]
            assert saved["gateway_alias"] is None
        response = await client.get("/api/models")
        saved = next(row for row in response.json()["models"] if row["model"] == model)
        assert saved["selection_status"] == "catalog_only"
        assert "embedding_provider" not in saved["selection_roles"]
    assert json.loads(data_path.read_text()) == json.loads(web_path.read_text())
    routes = yaml.safe_load((tmp_path / "litellm-config.yaml").read_text())["model_list"]
    assert [row["model_name"] for row in routes] == ["ragweld-local"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["PUT", "PATCH"])
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("skip_dense", [False, True])
@pytest.mark.parametrize("catalog_state", ["catalog_only", "missing", "oversized"])
async def test_config_writes_require_an_executable_openai_embedding_route(
    client: AsyncClient, tmp_path: Path, method: str, scoped: bool,
    skip_dense: bool, catalog_state: str,
) -> None:
    from copy import deepcopy
    from uuid import uuid4

    original = (await client.get("/api/config")).json()
    seed = json.loads(models_api.MODELS_PATH.read_text())
    data_path, web_path = tmp_path / "models.json", tmp_path / "models-web.json"
    for path in (data_path, web_path):
        path.write_text(json.dumps(seed))
    corpus = "pytest_embedding_route_" + uuid4().hex if scoped else None
    params = {"corpus_id": corpus} if corpus else {}
    if corpus:
        created = await client.post("/api/corpora", json={"corpus_id": corpus, "name": corpus, "path": "."})
        assert created.status_code == 200, created.text
    try:
        with _temporary_catalog_paths(data_path, web_path):
            valid = deepcopy(original)
            valid["embedding"].update(embedding_backend="provider", embedding_type="openai",
                                      embedding_model="text-embedding-3-small", embedding_dim=128)
            valid["tokenization"]["strategy"] = "tiktoken"
            valid["tokenization"]["tiktoken_encoding"] = "cl100k_base"
            valid["indexing"]["skip_dense"] = skip_dense
            configured = await client.put("/api/config", params=params, json=valid)
            assert configured.status_code == 200, configured.text
            before = (await client.get("/api/config", params=params)).json()
            change: dict = {"embedding_model": "text-embedding-future-fixture"}
            if catalog_state == "catalog_only":
                added = await client.post("/api/models/upsert", json={
                    "provider": "openai", "model": change["embedding_model"], "family": "embed",
                    "unit": "1k_tokens", "embed_per_1k": 0.0001, "dimensions": 1536,
                })
                assert added.status_code == 200, added.text
                assert added.json()["model"]["selection_status"] == "catalog_only"
            elif catalog_state == "missing":
                data_path.unlink()
            else:
                change = {"embedding_dim": 3072}
            desired = deepcopy(before)
            desired["embedding"].update(change)
            result = await client.request(method, "/api/config" if method == "PUT" else "/api/config/embedding",
                                          params=params, json=desired if method == "PUT" else change)
            assert result.status_code == 422, result.text
            assert "embedding" in str(result.json()["detail"]).lower()
            assert (await client.get("/api/config", params=params)).json() == before
    finally:
        if corpus:
            deleted = await client.delete(f"/api/corpora/{corpus}")
            assert deleted.status_code == 200, deleted.text
        else:
            restored = await client.put("/api/config", json=original)
            assert restored.status_code == 200, restored.text
