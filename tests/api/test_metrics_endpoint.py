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


@pytest.mark.asyncio
async def test_metrics_exports_expected_series(client: AsyncClient) -> None:
    """Ensure newly added low-cardinality series are exported on /metrics."""
    r = await client.get("/metrics")
    assert r.status_code == 200
    text = r.text

    # Search stage metrics
    assert "tribrid_search_stage_latency_seconds_bucket" in text
    assert "tribrid_search_stage_errors_total" in text
    assert "tribrid_search_leg_results_count_bucket" in text

    # Indexing stage metrics
    assert "tribrid_index_runs_total" in text
    assert "tribrid_index_duration_seconds_bucket" in text
    assert "tribrid_index_stage_latency_seconds_bucket" in text

    # Process-level “size” gauges
    assert "tribrid_chunks_indexed_current" in text
    assert "tribrid_graph_entities_current" in text
    assert "tribrid_graph_relationships_current" in text


@pytest.mark.asyncio
async def test_metrics_increment_on_index_job(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running an index job should increment index metrics and update size gauges."""
    import asyncio
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.models.tribrid_config_model import IndexRequest, IndexStats, TriBridConfig

    async def _fake_run_index(*_args: object, **_kwargs: object) -> IndexStats:
        return IndexStats(
            repo_id="test-repo",
            total_files=1,
            total_chunks=3,
            total_tokens=42,
            embedding_model="test",
            embedding_dimensions=3,
            last_indexed=datetime.now(UTC),
            file_breakdown={".py": 1},
        )

    async def _fake_load_scoped_config(*, repo_id: str | None = None) -> TriBridConfig:
        base = TriBridConfig()
        # Disable graph indexing to avoid Neo4j in unit tests.
        return base.model_copy(update={"graph_indexing": base.graph_indexing.model_copy(update={"enabled": False})})

    monkeypatch.setattr(index_api, "_run_index", _fake_run_index, raising=True)
    monkeypatch.setattr(index_api, "load_scoped_config", _fake_load_scoped_config, raising=True)

    r0 = await client.get("/metrics")
    assert r0.status_code == 200
    before_runs = _metric_value(r0.text, "tribrid_index_runs_total")
    before_count = _metric_value(r0.text, "tribrid_index_duration_seconds_count")

    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    req = IndexRequest(repo_id="test-repo", repo_path=".", force_reindex=False)
    await index_api._background_index_job(req, queue)

    r1 = await client.get("/metrics")
    assert r1.status_code == 200
    after_runs = _metric_value(r1.text, "tribrid_index_runs_total")
    after_count = _metric_value(r1.text, "tribrid_index_duration_seconds_count")
    chunks_gauge = _metric_value(r1.text, "tribrid_chunks_indexed_current")

    assert after_runs == pytest.approx(before_runs + 1.0)
    assert after_count == pytest.approx(before_count + 1.0)
    assert chunks_gauge == pytest.approx(3.0)
