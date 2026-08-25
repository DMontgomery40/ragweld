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
async def test_background_index_job_clears_semantic_cache_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failed index runs should clear semantic cache to avoid stale retrieval hits."""
    import asyncio

    import server.api.index as index_api
    from server.models.tribrid_config_model import IndexRequest

    repo_id = "index-error-clears-cache"
    cleared: list[str] = []

    async def _fake_run_index(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("index failed")

    async def _fake_clear_semantic_cache(target_repo_id: str) -> None:
        cleared.append(target_repo_id)

    monkeypatch.setattr(index_api, "_run_index", _fake_run_index, raising=True)
    monkeypatch.setattr(index_api, "_clear_semantic_cache_for_repo", _fake_clear_semantic_cache, raising=True)

    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    req = IndexRequest(repo_id=repo_id, repo_path=".", force_reindex=True)
    await index_api._background_index_job(req, queue)

    assert cleared == [repo_id]
    status = index_api._STATUS.get(repo_id)
    assert status is not None
    assert status.status == "error"

    index_api._STATUS.pop(repo_id, None)
