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


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_background_index_job_fails_closed_and_cleans_staging_on_a_missing_path() -> None:
    """A run over a path that does not exist ends in status=error, leaves no
    staging corpus behind, and does not publish stats for the failed build."""
    import asyncio
    import os
    import uuid

    import server.api.index as index_api
    from server.db.postgres import PostgresClient
    from server.models.tribrid_config_model import IndexRequest

    repo_id = f"index-error-{uuid.uuid4().hex[:8]}"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    req = IndexRequest(repo_id=repo_id, repo_path=f"/nonexistent/{repo_id}", force_reindex=True)
    await index_api._background_index_job(req, queue)

    status = index_api._STATUS.get(repo_id)
    assert status is not None and status.status == "error", status
    assert status.error, "the operator must see why the run failed"
    assert repo_id not in index_api._STATS
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        corpora = await pg.list_corpora()
        assert not [c for c in corpora if str(c.get("repo_id", "")).startswith(f"__staging__{repo_id}")]
    finally:
        await pg.disconnect()
    index_api._STATUS.pop(repo_id, None)
