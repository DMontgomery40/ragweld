"""API tests for reranker status + info endpoints (no DB required for /status)."""

import pytest
from httpx import AsyncClient

from server.api.reranker import _reranker_active_status


@pytest.mark.asyncio
async def test_reranker_status_has_message_and_shape(client: AsyncClient) -> None:
    res = await client.get("/api/reranker/status")
    assert res.status_code == 200
    data = res.json()

    assert isinstance(data, dict)
    assert set(["running", "progress", "task", "message"]).issubset(set(data.keys()))
    assert isinstance(data["running"], bool)
    assert isinstance(data["progress"], int) or isinstance(data["progress"], float)
    assert isinstance(data["task"], str)
    assert isinstance(data["message"], str)


def test_reranker_active_status_makes_configured_vs_active_explicit() -> None:
    """The authoritative status distinguishes 'configured' from 'active' with a reason.

    This is the M-06 contract: the page must never say CLOUD while the runtime is
    silently disabled. Each mode resolves to a single (active, reason) pair.
    """
    # Disabled: configured=none => not active, and the reason says why.
    active, reason = _reranker_active_status(
        mode="none", cloud_provider="litellm", cloud_model="openai.gpt-5.6-luna",
        learning_path="", learning_resolved="",
    )
    assert active is False
    assert "disabled" in reason.lower()

    # Cloud fully configured => active, and the reason names provider/model.
    active, reason = _reranker_active_status(
        mode="cloud", cloud_provider="litellm", cloud_model="openai.gpt-5.6-luna",
        learning_path="", learning_resolved="",
    )
    assert active is True
    assert "litellm" in reason and "openai.gpt-5.6-luna" in reason

    # Cloud selected but not configured => the configured-vs-active gap is explained.
    active, reason = _reranker_active_status(
        mode="cloud", cloud_provider="", cloud_model="",
        learning_path="", learning_resolved="",
    )
    assert active is False
    assert "provider/model" in reason

    # Learning selected but no adapter promoted => not active, reason names the path.
    active, reason = _reranker_active_status(
        mode="learning", cloud_provider=None, cloud_model=None,
        learning_path="models/learning-reranker-active", learning_resolved="",
    )
    assert active is False
    assert "models/learning-reranker-active" in reason

    # Learning with a promoted adapter => active.
    active, reason = _reranker_active_status(
        mode="learning", cloud_provider=None, cloud_model=None,
        learning_path="models/learning-reranker-active",
        learning_resolved="models/learning-reranker-active/v3",
    )
    assert active is True


async def _create_corpus(client: AsyncClient, corpus_id: str) -> None:
    response = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": "tests/fixtures/acceptance_corpus"},
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_reranker_info_reflects_corpus_scope_not_global(client: AsyncClient) -> None:
    """M-06 root cause: reranking config is corpus-scoped, but /reranker/info read the
    GLOBAL config and ignored corpus_id - so mode cards said CLOUD while runtime info
    said disabled. Info must reflect the same corpus the cards configure.
    """
    corpus_id = "pytest_m06_reranker_scope"
    await _create_corpus(client, corpus_id)
    try:
        # Configure an allowed CLOUD reranker explicitly for THIS corpus only.
        patch = await client.request(
            "PATCH",
            f"/api/config/reranking?corpus_id={corpus_id}",
            json={
                "reranker_mode": "cloud",
                "reranker_cloud_provider": "litellm",
                "reranker_cloud_model": "openai.gpt-5.6-luna",
            },
        )
        assert patch.status_code == 200, patch.text

        scoped = await client.get(f"/api/reranker/info?corpus_id={corpus_id}")
        assert scoped.status_code == 200, scoped.text
        body = scoped.json()
        # Scoped info reflects the corpus config, not global defaults.
        assert body["reranker_mode"] == "cloud"
        assert body["enabled"] is True
        assert body["active"] is True
        assert "openai.gpt-5.6-luna" in body["active_reason"]

        # Global (no corpus) is independent and stays at its own mode - the two scopes
        # are genuinely different, which is exactly why /info must honor corpus_id.
        glob = await client.get("/api/reranker/info")
        assert glob.status_code == 200
        gbody = glob.json()
        assert "active" in gbody and "active_reason" in gbody
        if gbody["reranker_mode"] == "none":
            assert gbody["active"] is False
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
