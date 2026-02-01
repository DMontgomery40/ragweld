"""API tests for Prometheus metrics exposure."""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient


def _metric_value(text: str, name: str) -> float:
    """Extract a single Prometheus metric sample value from /metrics text.

    Returns 0.0 if the metric isn't present yet.
    """
    m = re.search(rf"^{re.escape(name)}\s+([0-9eE+.-]+)$", text, flags=re.MULTILINE)
    if not m:
        return 0.0
    return float(m.group(1))


@pytest.mark.asyncio
async def test_metrics_increment_on_search(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling /api/search should increment search metrics and expose them on /metrics."""
    import server.api.search as search_api
    from server.models.retrieval import ChunkMatch
    from server.models.tribrid_config_model import TriBridConfig
    from server.retrieval.fusion import TriBridFusion

    class _FakePostgres:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def connect(self) -> None:
            return None

        async def get_corpus(self, repo_id: str) -> dict[str, str]:
            return {"repo_id": repo_id}

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        return TriBridConfig()

    async def _fake_fusion_search(
        self: TriBridFusion, repo_id: str, query: str, *_args: object, **_kwargs: object
    ) -> list[ChunkMatch]:
        assert repo_id
        assert query
        return []

    monkeypatch.setattr(search_api, "PostgresClient", _FakePostgres, raising=True)
    monkeypatch.setattr(search_api, "load_scoped_config", _fake_load_scoped_config, raising=True)
    monkeypatch.setattr(TriBridFusion, "search", _fake_fusion_search, raising=True)

    # Baseline scrape
    r0 = await client.get("/metrics")
    assert r0.status_code == 200
    before_reqs = _metric_value(r0.text, "tribrid_search_requests_total")
    before_count = _metric_value(r0.text, "tribrid_search_latency_seconds_count")

    # Exercise endpoint
    r = await client.post(
        "/api/search",
        json={
            "query": "hello",
            "repo_id": "test-repo",
            "top_k": 5,
            "include_vector": False,
            "include_sparse": False,
            "include_graph": False,
        },
    )
    assert r.status_code == 200

    # Verify metrics incremented
    r1 = await client.get("/metrics")
    assert r1.status_code == 200
    after_reqs = _metric_value(r1.text, "tribrid_search_requests_total")
    after_count = _metric_value(r1.text, "tribrid_search_latency_seconds_count")

    assert after_reqs == pytest.approx(before_reqs + 1.0)
    assert after_count == pytest.approx(before_count + 1.0)
