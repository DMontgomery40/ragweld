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
async def test_reranker_score_endpoint_accepts_legacy_local_mode(client: AsyncClient) -> None:
    """Back-compat: legacy callers may still send mode='local' or 'hf'."""
    res = await client.post(
        "/api/reranker/score",
        json={
            "corpus_id": "does-not-exist",
            "mode": "local",
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
