from pathlib import Path

import pytest

from server.models.tribrid_config_model import (
    TraceCostSummary,
    TraceEvent,
    TraceExternalLink,
    TraceRouteSummary,
    TriBridConfig,
)
from server.services.traces import TraceStore


def _persistent_trace_config(path: Path) -> TriBridConfig:
    cfg = TriBridConfig()
    cfg.tracing.tracing_mode = "otel_langfuse"
    cfg.tracing.trace_retention = 10
    cfg.tracing.trace_store_path = str(path)
    return cfg


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


@pytest.mark.asyncio
async def test_completed_traces_reload_with_global_and_repo_indexes_and_retention(tmp_path: Path) -> None:
    path = tmp_path / "traces" / "workbench.json"
    cfg = _persistent_trace_config(path)
    first = TraceStore()

    for run_id, repo_id, started_at_ms in (
        ("repo-a-1", "repo-a", 1),
        ("repo-a-2", "repo-a", 2),
        ("repo-b-1", "repo-b", 3),
    ):
        assert await first.start(
            run_id=run_id,
            repo_id=repo_id,
            started_at_ms=started_at_ms,
            config=cfg,
        )
        await first.add_event(run_id, kind="search.response", data={"run_id": run_id})
        await first.end(run_id, ended_at_ms=started_at_ms + 10)

    reloaded = TraceStore()
    await reloaded.initialize(cfg)
    assert (await reloaded.latest()).run_id == "repo-b-1"
    assert (await reloaded.latest(repo="repo-a")).run_id == "repo-a-2"

    for index in range(3, 12):
        run_id = f"repo-a-{index}"
        assert await reloaded.start(
            run_id=run_id,
            repo_id="repo-a",
            started_at_ms=index,
            config=cfg,
        )
        await reloaded.end(run_id, ended_at_ms=index + 10)

    after_retention_reload = TraceStore()
    await after_retention_reload.initialize(cfg)
    assert await after_retention_reload.get_trace("repo-a-1") is None
    assert (await after_retention_reload.latest(repo="repo-a")).run_id == "repo-a-11"
    assert (await after_retention_reload.latest()).run_id == "repo-a-11"


@pytest.mark.parametrize(
    "corrupt_payload",
    (
        "{not-json",
        "[]",
        '{"version":1,"traces":{}}',
        '{"version":1,"traces":[{"run_id":"incomplete"}]}',
    ),
)
@pytest.mark.asyncio
async def test_corrupt_trace_store_fails_empty_and_recovers_on_next_completed_trace(
    tmp_path: Path,
    corrupt_payload: str,
) -> None:
    path = tmp_path / "traces" / "workbench.json"
    path.parent.mkdir(parents=True)
    path.write_text(corrupt_payload, encoding="utf-8")
    cfg = _persistent_trace_config(path)

    store = TraceStore()
    await store.initialize(cfg)
    assert (await store.latest()).trace is None

    assert await store.start(run_id="recovered", repo_id="repo-a", started_at_ms=1, config=cfg)
    await store.end("recovered", ended_at_ms=2)

    reloaded = TraceStore()
    await reloaded.initialize(cfg)
    latest = await reloaded.latest()
    assert latest.run_id == "recovered"
    assert latest.trace is not None


@pytest.mark.asyncio
async def test_initialized_global_store_path_survives_scoped_config_without_path(tmp_path: Path) -> None:
    path = tmp_path / "traces" / "workbench.json"
    global_cfg = _persistent_trace_config(path)
    scoped_cfg = TriBridConfig()
    scoped_cfg.tracing.tracing_mode = "otel_langfuse"
    assert scoped_cfg.tracing.trace_store_path == ""

    store = TraceStore()
    await store.initialize(global_cfg)
    assert await store.start(
        run_id="scoped-run",
        repo_id="repo-a",
        started_at_ms=1,
        config=scoped_cfg,
    )
    await store.end("scoped-run", ended_at_ms=2)

    reloaded = TraceStore()
    await reloaded.initialize(global_cfg)
    assert (await reloaded.latest(repo="repo-a")).run_id == "scoped-run"


@pytest.mark.asyncio
async def test_persisted_external_links_follow_current_deployment_origins(tmp_path: Path) -> None:
    path = tmp_path / "traces" / "workbench.json"
    old_cfg = _persistent_trace_config(path)
    old_cfg.ui.grafana_base_url = "https://grafana.ragweld.com"
    old_cfg.tracing.langfuse_public_base_url = "https://langfuse.ragweld.com"
    first = TraceStore()
    assert await first.start(run_id="old-links", repo_id="repo-a", started_at_ms=1, config=old_cfg)
    await first.annotate(
        "old-links",
        trace_id="trace-123",
        external_links=[
            TraceExternalLink(
                label="Grafana dashboard",
                kind="grafana",
                url="https://grafana.ragweld.com/d/retrieval/retrieval?from=now-1h",
            ),
            TraceExternalLink(
                label="Tempo trace",
                kind="tempo",
                url="https://grafana.ragweld.com/explore?trace=trace-123",
            ),
            TraceExternalLink(
                label="Langfuse trace",
                kind="langfuse",
                url="https://langfuse.ragweld.com/project/ragweld/traces/trace-123",
            ),
            TraceExternalLink(
                label="Custom",
                kind="custom",
                url="https://custom.example/run/old-links",
            ),
        ],
    )
    await first.end("old-links", ended_at_ms=2)

    current_cfg = _persistent_trace_config(path)
    current_cfg.ui.grafana_base_url = "https://ragweld-grafana.dtmont.com"
    current_cfg.tracing.langfuse_public_base_url = "https://ragweld-langfuse.dtmont.com"
    reloaded = TraceStore()
    await reloaded.initialize(current_cfg)

    latest = await reloaded.latest(run_id="old-links")
    assert latest.trace is not None
    assert [link.url for link in latest.trace.external_links] == [
        "https://ragweld-grafana.dtmont.com/d/retrieval/retrieval?from=now-1h",
        "https://ragweld-grafana.dtmont.com/explore?trace=trace-123",
        "https://ragweld-langfuse.dtmont.com/project/ragweld/traces/trace-123",
        "https://custom.example/run/old-links",
    ]


@pytest.mark.asyncio
async def test_initialized_trace_store_refreshes_link_origins_when_runtime_config_changes() -> None:
    old_cfg = TriBridConfig()
    old_cfg.tracing.tracing_mode = "otel_langfuse"
    old_cfg.ui.grafana_base_url = "https://grafana.ragweld.com"
    store = TraceStore()
    await store.initialize(old_cfg)
    assert await store.start(run_id="runtime-change", repo_id="repo-a", started_at_ms=1, config=old_cfg)
    await store.annotate(
        "runtime-change",
        external_links=[
            TraceExternalLink(
                label="Grafana dashboard",
                kind="grafana",
                url="https://grafana.ragweld.com/d/runtime/runtime",
            )
        ],
    )

    current_cfg = old_cfg.model_copy(deep=True)
    current_cfg.ui.grafana_base_url = "https://ragweld-grafana.dtmont.com"
    await store.initialize(current_cfg)

    latest = await store.latest(run_id="runtime-change")
    assert latest.trace is not None
    assert latest.trace.external_links[0].url == "https://ragweld-grafana.dtmont.com/d/runtime/runtime"
