import pytest

from server.models.tribrid_config_model import TraceEvent, TriBridConfig
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
