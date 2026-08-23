from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reranker_score_endpoint_shape_without_scoped_config(client: AsyncClient) -> None:
    """The debug endpoint must be stable even when corpus-scoped config is unavailable."""
    res = await client.post(
        "/api/reranker/score",
        json={
            "corpus_id": "does-not-exist",
            "query": "auth flow",
            "document": "OAuth2 authorization code exchange",
            "include_logits": 0,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body, dict)
    assert "ok" in body
    assert "backend" in body
    assert "score" in body
    assert "error" in body
    assert body["ok"] in {True, False}


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_mode", ["local", "hf"])
async def test_reranker_score_endpoint_rejects_legacy_modes(client: AsyncClient, legacy_mode: str) -> None:
    """Stale mode aliases are not normalized: the schema rejects them so callers migrate."""
    res = await client.post(
        "/api/reranker/score",
        json={
            "corpus_id": "does-not-exist",
            "mode": legacy_mode,
            "query": "Which plane management company did Barry Cohen consider switching to from Jet Aviation?",
            "document": "Thinking of switching from Jet Aviation to EJM. EJM is more expensive.",
            "include_logits": 0,
        },
    )
    assert res.status_code == 422
    assert "mode" in str(res.json().get("detail", ""))
