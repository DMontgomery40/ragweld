"""Tests for GET /api/config/validate endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_validate_config_returns_200(client: AsyncClient) -> None:
    """GET /api/config/validate should return 200 with valid/warnings shape."""
    response = await client.get("/api/config/validate")
    assert response.status_code == 200
    data = response.json()
    assert "valid" in data
    assert "warnings" in data
    assert isinstance(data["valid"], bool)
    assert isinstance(data["warnings"], list)


@pytest.mark.asyncio
async def test_validate_config_warns_when_gen_alias_is_not_a_catalog_gateway_alias(client: AsyncClient) -> None:
    """A syntactically valid alias the catalog does not serve is a warning: generation would fail closed."""
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()
    original = cfg["generation"]["gen_model"]

    cfg["generation"]["gen_model"] = "totally-fake-model-xyz-9999"
    put_resp = await client.put("/api/config", json=cfg)
    assert put_resp.status_code == 200
    try:
        validate_resp = await client.get("/api/config/validate")
        assert validate_resp.status_code == 200
        result = validate_resp.json()
        gen_model_warnings = [w for w in result["warnings"] if w["field"] == "generation.gen_model"]
        assert len(gen_model_warnings) == 1
        assert "not a gateway alias in data/models.json" in gen_model_warnings[0]["message"]

        cfg["generation"]["gen_model"] = "openai.gpt-5.4-mini"
        assert (await client.put("/api/config", json=cfg)).status_code == 200
        result = (await client.get("/api/config/validate")).json()
        assert [w for w in result["warnings"] if w["field"] == "generation.gen_model"] == []
    finally:
        cfg["generation"]["gen_model"] = original
        await client.put("/api/config", json=cfg)


@pytest.mark.asyncio
async def test_validate_config_no_warning_for_empty_optional_field(client: AsyncClient) -> None:
    """Empty optional model fields should not produce warnings."""
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    cfg = baseline.json()

    cfg["generation"]["gen_model_http"] = ""
    put_resp = await client.put("/api/config", json=cfg)
    assert put_resp.status_code == 200

    validate_resp = await client.get("/api/config/validate")
    assert validate_resp.status_code == 200
    result = validate_resp.json()

    http_warnings = [
        w for w in result["warnings"]
        if w["field"] == "generation.gen_model_http"
    ]
    assert len(http_warnings) == 0
