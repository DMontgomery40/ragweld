import pytest
from _pytest.monkeypatch import MonkeyPatch
from httpx import AsyncClient

import server.api.cost as cost_api


@pytest.mark.asyncio
async def test_cost_estimate_math(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-01-01",
        "models": [
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.00015,
                "output_per_1k": 0.0006,
            },
            {
                "provider": "openai",
                "model": "text-embedding-3-large",
                "components": ["EMB"],
                "unit": "1k_tokens",
                "embed_per_1k": 0.00013,
            },
            {
                "provider": "cohere",
                "model": "rerank-3.5",
                "components": ["RERANK"],
                "unit": "request",
                "per_request": 0.002,
            },
        ],
    }

    monkeypatch.setattr(cost_api, "_load_models_catalog", lambda: catalog)

    payload = {
        "gen_provider": "openai",
        "gen_model": "gpt-4o-mini",
        "tokens_in": 1000,
        "tokens_out": 2000,
        "embed_provider": "openai",
        "embed_model": "text-embedding-3-large",
        "embeds": 3,
        "rerank_provider": "cohere",
        "rerank_model": "rerank-3.5",
        "reranks": 2,
        "requests_per_day": 100,
    }

    res = await client.post("/api/cost/estimate", json=payload)
    assert res.status_code == 200
    data = res.json()

    # Per-request:
    # GEN: 1k * 0.00015 + 2k * 0.0006 = 0.00135
    # EMB: 3 embeds * 1000 tokens each -> 3k tokens * 0.00013 = 0.00039
    # RERANK: 2 * 0.002 = 0.004
    # total per request = 0.00574
    assert data["currency"] == "USD"
    assert data["models_last_updated"] == "2026-01-01"
    assert data["per_request_usd"] == pytest.approx(0.00574, rel=1e-6)
    assert data["daily"] == pytest.approx(0.574, rel=1e-6)
    assert data["monthly"] == pytest.approx(17.22, rel=1e-6)
    assert isinstance(data.get("breakdown"), dict)
    assert data.get("errors") == []


@pytest.mark.asyncio
async def test_cost_estimate_pipeline_alias(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-01-01",
        "models": [
            {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.001,
                "output_per_1k": 0.003,
            },
        ],
    }
    monkeypatch.setattr(cost_api, "_load_models_catalog", lambda: catalog)

    payload = {
        "gen_provider": "openai",
        "gen_model": "gpt-4o-mini",
        "tokens_in": 1000,
        "tokens_out": 0,
        "requests_per_day": 10,
    }

    res = await client.post("/api/cost/estimate_pipeline", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["per_request_usd"] == pytest.approx(0.001, rel=1e-6)
    assert data["daily"] == pytest.approx(0.01, rel=1e-6)


@pytest.mark.asyncio
async def test_cost_estimate_unknown_model_returns_errors(client: AsyncClient, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(cost_api, "_load_models_catalog", lambda: {"currency": "USD", "models": []})

    payload = {
        "gen_provider": "openai",
        "gen_model": "does-not-exist",
        "tokens_in": 1000,
        "tokens_out": 1000,
        "requests_per_day": 5,
    }

    res = await client.post("/api/cost/estimate", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["per_request_usd"] == 0.0
    assert data["daily"] == 0.0
    assert isinstance(data.get("errors"), list)
    assert any("Unknown GEN model" in e for e in data["errors"])

