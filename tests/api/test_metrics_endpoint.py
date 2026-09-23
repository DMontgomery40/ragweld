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
    import uuid
    from datetime import UTC, datetime

    import server.api.index as index_api
    from server.db.postgres import PostgresClient
    from server.models.index import IndexRequest

    repo_id = f"index-error-{uuid.uuid4().hex[:8]}"
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
    req = IndexRequest(repo_id=repo_id, repo_path=f"/nonexistent/{repo_id}", force_reindex=True)
    # `run_id` is keyword-only and supplied by start_index; the shape it generates is
    # "<UTC timestamp>_<hex>", so the run summary this job persists is named the same way a
    # real one is.
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:10]}"
    await index_api._background_index_job(req, queue, run_id=run_id)

    status = index_api._STATUS.get(repo_id)
    assert status is not None and status.status == "error", status
    assert status.error, "the operator must see why the run failed"
    assert repo_id not in index_api._STATS
    # Same constructor every other tests/api/ case uses: the client resolves the DSN from
    # POSTGRES_* like the app does, so this does not additionally require POSTGRES_DSN to
    # be exported. (tests/integration/** still reads it directly; that family is T-hyg2's.)
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        corpora = await pg.list_corpora()
        assert not [c for c in corpora if str(c.get("repo_id", "")).startswith(f"__staging__{repo_id}")]
    finally:
        await pg.disconnect()
    index_api._STATUS.pop(repo_id, None)


def _chunk(corpus_id: str, n: int):  # noqa: ANN202 - server.models.index.Chunk
    from server.models.index import Chunk

    return Chunk(
        chunk_id=f"{corpus_id}-{n}",
        content=f"Calibration step {n}: zero the torque sensor before the load test.",
        file_path=f"docs/calibration_{n}.md",
        start_line=1,
        end_line=1,
        language="markdown",
        token_count=12,
        embedding=None,
        summary=None,
        metadata={"kind": "unit_test"},
    )


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_per_corpus_size_gauges_come_from_a_cache_that_a_scrape_never_bypasses() -> None:
    """`tribrid_corpus_chunks{corpus}` is read from the chunk rows, internal (runtime-managed)
    corpora are left out, a corpus without a graph generation exports no graph series, and
    inside the TTL a scrape serves the cached snapshot without touching Postgres again."""
    import uuid

    from prometheus_client import CollectorRegistry

    from server.config import load_config
    from server.db.postgres import PostgresClient
    from server.observability.metrics import CORPUS_SIZE_CACHE_TTL_S, CorpusIndexSizeCollector

    now = [1_000.0]
    collector = CorpusIndexSizeCollector(clock=lambda: now[0])
    registry = CollectorRegistry()
    registry.register(collector)

    corpus_id = f"pytest_sizes_{uuid.uuid4().hex[:8]}"
    internal_id = f"pytest_sizes_internal_{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(load_config().indexing.postgres_url)
    await pg.connect()
    try:
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        await pg.upsert_chunks(corpus_id, [_chunk(corpus_id, 1), _chunk(corpus_id, 2)])
        await pg.upsert_corpus(internal_id, name=internal_id, root_path=".", meta={"system_kind": "recall"})
        await pg.upsert_chunks(internal_id, [_chunk(internal_id, 1)])

        assert collector.is_stale()
        assert registry.get_sample_value("tribrid_corpus_chunks", {"corpus": corpus_id}) is None
        task = collector.schedule_refresh()
        assert task is not None
        await task
        assert registry.get_sample_value("tribrid_corpus_chunks", {"corpus": corpus_id}) == 2.0
        assert registry.get_sample_value("tribrid_corpus_chunks", {"corpus": internal_id}) is None
        assert registry.get_sample_value("tribrid_corpus_graph_entities", {"corpus": corpus_id}) is None
        assert registry.get_sample_value("tribrid_corpus_graph_relationships", {"corpus": corpus_id}) is None

        # Inside the TTL: no reload is started, the cached count is served.
        await pg.upsert_chunks(corpus_id, [_chunk(corpus_id, 3)])
        now[0] += CORPUS_SIZE_CACHE_TTL_S - 1
        assert collector.schedule_refresh() is None
        assert collector.refresh_count == 1
        assert registry.get_sample_value("tribrid_corpus_chunks", {"corpus": corpus_id}) == 2.0

        # Past the TTL: one reload, and the new row is counted.
        now[0] += 2
        task = collector.schedule_refresh()
        assert task is not None and collector.schedule_refresh() is task  # one reload in flight
        await task
        assert collector.refresh_count == 2
        assert registry.get_sample_value("tribrid_corpus_chunks", {"corpus": corpus_id}) == 3.0
    finally:
        for cid in (corpus_id, internal_id):
            try:
                await pg.delete_corpus(cid)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_metrics_scrape_starts_at_most_one_size_reload_per_ttl(client: AsyncClient) -> None:
    """The production collector: the `/metrics` route schedules the reload, a scrape inside
    the TTL does not start another."""
    from server.observability.metrics import CORPUS_INDEX_SIZES

    first = await client.get("/metrics")
    assert first.status_code == 200
    pending = CORPUS_INDEX_SIZES._refresh_task
    if pending is not None:
        await pending
    reloads = CORPUS_INDEX_SIZES.refresh_count
    assert reloads >= 1
    second = await client.get("/metrics")
    assert second.status_code == 200
    assert CORPUS_INDEX_SIZES.refresh_count == reloads
