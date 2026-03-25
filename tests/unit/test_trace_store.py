import pytest

from server.models.tribrid_config_model import (
    TraceCostSummary,
    TraceEvent,
    TraceExternalLink,
    TraceRouteSummary,
    TriBridConfig,
)
from server.services.traces import TraceStore


@pytest.mark.asyncio
async def test_latest_by_run_id_returns_detached_trace_copy() -> None:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "local"
    store = TraceStore()

    started = await store.start(run_id="run-1", repo_id="repo-1", started_at_ms=1, config=cfg)
    assert started is True
    await store.add_event("run-1", kind="router.decide", msg="first")

    latest = await store.latest(run_id="run-1")
    assert latest.trace is not None
    latest.trace.events.append(TraceEvent(kind="mutated", ts=2, msg="leak", data={}))

    reloaded = await store.latest(run_id="run-1")
    assert reloaded.trace is not None
    assert [ev.kind for ev in reloaded.trace.events] == ["router.decide"]


@pytest.mark.asyncio
async def test_start_reused_run_id_keeps_latest_trace_after_retention() -> None:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "local"
    cfg.tracing.trace_retention = 10
    store = TraceStore()

    for i in range(11):
        started = await store.start(run_id="dup-run", repo_id="repo-1", started_at_ms=i, config=cfg)
        assert started is True

    latest = await store.latest(repo="repo-1")
    assert latest.run_id == "dup-run"
    assert latest.trace is not None
    assert latest.trace.started_at_ms == 10


@pytest.mark.asyncio
async def test_trace_annotations_round_trip_full_observability_payload() -> None:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "otel_langfuse"
    store = TraceStore()

    started = await store.start(run_id="run-annotated", repo_id="repo-1", started_at_ms=1, config=cfg)
    assert started is True
    await store.annotate(
        "run-annotated",
        trace_id="trace-123",
        root_span_id="span-456",
        correlation_id="corr-789",
        route_summary=TraceRouteSummary(
            route_name="chat",
            path="/api/chat",
            method="POST",
            corpus_ids=["repo-1"],
            include_vector=True,
            include_sparse=False,
            include_graph=True,
            final_results=3,
            llm_used=True,
        ),
        external_links=[
            TraceExternalLink(
                label="Tempo trace",
                kind="tempo",
                url="http://tempo.local/trace/trace-123",
                detail="Trace deep link",
            )
        ],
        cost_summary=TraceCostSummary(
            provider="litellm",
            model="openai/gpt-4.1-mini",
            total_tokens=42,
            estimated_cost_usd=0.0123,
            cost_source="catalog",
            authoritative=False,
        ),
    )

    latest = await store.latest(run_id="run-annotated")
    assert latest.trace is not None
    assert latest.trace.trace_id == "trace-123"
    assert latest.trace.root_span_id == "span-456"
    assert latest.trace.correlation_id == "corr-789"
    assert latest.trace.route_summary is not None
    assert latest.trace.route_summary.route_name == "chat"
    assert latest.trace.route_summary.final_results == 3
    assert latest.trace.external_links[0].kind == "tempo"
    assert latest.trace.cost_summary is not None
    assert latest.trace.cost_summary.total_tokens == 42
    assert latest.trace.cost_summary.cost_source == "catalog"
