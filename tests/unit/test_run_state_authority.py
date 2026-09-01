"""Run-record loading is read-only; every repair goes through the transition authority.

The follow-up slice `training-run-state-authority-2026-08-23.md`: `_load_run` must never
write (no reconcile-on-load), reconciliation is an explicit `reconcile_run` step that
transitions through the per-run lock with compare-and-set, and both trainers behave the
same way. No mocking: real run/event files under temp run stores drive the real code.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import pytest

from server.api import agent, reranker
from server.models.tribrid_config_model import (
    AgentTrainRun,
    CorpusEvalProfile,
    RerankerTrainRun,
    TriBridConfig,
)


def _agent_run(run_id: str, *, status: str, started_hours_ago: float = 0.0) -> AgentTrainRun:
    cfg = TriBridConfig()
    return AgentTrainRun(
        run_id=run_id,
        corpus_id="pytest_authority",
        status=status,  # type: ignore[arg-type]
        started_at=datetime.now(UTC) - timedelta(hours=started_hours_ago),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
    )


def _reranker_run(run_id: str, *, status: str, started_hours_ago: float = 0.0) -> RerankerTrainRun:
    cfg = TriBridConfig()
    return RerankerTrainRun(
        run_id=run_id,
        repo_id="pytest_authority",
        status=status,  # type: ignore[arg-type]
        started_at=datetime.now(UTC) - timedelta(hours=started_hours_ago),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="mrr",
        primary_k=10,
        metrics_available=["mrr@10", "ndcg@10", "map"],
        metric_profile=CorpusEvalProfile(
            repo_id="pytest_authority",
            label_kind="pairwise",
            avg_relevant_per_query=0.0,
            p95_relevant_per_query=0.0,
            recommended_metric="mrr",
            recommended_k=10,
            rationale="authority-regression",
        ),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
    )


@pytest.fixture
def tmp_stores(tmp_path):
    """Redirect both trainers' run stores and the lineage root to temp dirs."""
    originals = (agent._RUNS_DIR, reranker._RUNS_DIR, os.environ.get("RAGWELD_LINEAGE_ROOT"))
    agent._RUNS_DIR = tmp_path / "agent_train_runs"
    reranker._RUNS_DIR = tmp_path / "reranker_train_runs"
    agent._RUNS_DIR.mkdir(parents=True)
    reranker._RUNS_DIR.mkdir(parents=True)
    os.environ["RAGWELD_LINEAGE_ROOT"] = str(tmp_path / "lineage")
    try:
        yield tmp_path
    finally:
        agent._RUNS_DIR, reranker._RUNS_DIR = originals[0], originals[1]
        if originals[2] is None:
            os.environ.pop("RAGWELD_LINEAGE_ROOT", None)
        else:
            os.environ["RAGWELD_LINEAGE_ROOT"] = originals[2]
        agent._train_start_guard.clear()
        reranker._train_start_guard.clear()


def _events(runs_dir, run_id: str) -> list[dict]:
    path = runs_dir / run_id / "metrics.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_terminal_stream(module, run_id: str, *, status: str, event_ctor) -> datetime:
    ts = datetime.now(UTC) - timedelta(minutes=5)
    module._append_event(run_id, event_ctor(type="state", ts=ts, run_id=run_id, status=status))
    module._append_event(run_id, event_ctor(type="complete", ts=ts, run_id=run_id, status=status))
    return ts


# -- _load_run is read-only ------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_run_never_writes_even_when_the_record_is_stale(tmp_stores) -> None:
    from server.models.tribrid_config_model import AgentTrainMetricEvent, RerankerTrainMetricEvent

    # Agent: a running record whose metrics stream already ended, plus long inactivity.
    a = _agent_run("stale_load__1", status="running", started_hours_ago=5)
    agent._save_run(a)
    _write_terminal_stream(agent, a.run_id, status="completed", event_ctor=AgentTrainMetricEvent)
    run_bytes = (agent._RUNS_DIR / a.run_id / "run.json").read_bytes()
    events_before = _events(agent._RUNS_DIR, a.run_id)
    loaded = agent._load_run(a.run_id)
    assert loaded.status == "running"  # the stale truth, reported as stored
    assert (agent._RUNS_DIR / a.run_id / "run.json").read_bytes() == run_bytes
    assert _events(agent._RUNS_DIR, a.run_id) == events_before

    # Reranker: same contract.
    r = _reranker_run("stale_load__1", status="running", started_hours_ago=5)
    reranker._save_run(r)
    _write_terminal_stream(reranker, r.run_id, status="failed", event_ctor=RerankerTrainMetricEvent)
    run_bytes = (reranker._RUNS_DIR / r.run_id / "run.json").read_bytes()
    events_before = _events(reranker._RUNS_DIR, r.run_id)
    loaded_r = reranker._load_run(r.run_id)
    assert loaded_r.status == "running"
    assert (reranker._RUNS_DIR / r.run_id / "run.json").read_bytes() == run_bytes
    assert _events(reranker._RUNS_DIR, r.run_id) == events_before


# -- reconcile_run: explicit repair through the authority ------------------------------


@pytest.mark.asyncio
async def test_reconcile_adopts_the_terminal_stream_without_duplicating_events(tmp_stores) -> None:
    from server.models.tribrid_config_model import AgentTrainMetricEvent, RerankerTrainMetricEvent

    a = _agent_run("adopt__1", status="running")
    agent._save_run(a)
    ts = _write_terminal_stream(agent, a.run_id, status="completed", event_ctor=AgentTrainMetricEvent)
    events_before = _events(agent._RUNS_DIR, a.run_id)
    result = await agent.reconcile_run(a.run_id)
    assert result.status == "completed"
    assert result.completed_at == ts  # the stream's timestamp, not "now"
    assert agent._load_run(a.run_id).status == "completed"
    assert _events(agent._RUNS_DIR, a.run_id) == events_before  # no duplicate complete event

    r = _reranker_run("adopt__1", status="running")
    reranker._save_run(r)
    ts = _write_terminal_stream(reranker, r.run_id, status="cancelled", event_ctor=RerankerTrainMetricEvent)
    events_before = _events(reranker._RUNS_DIR, r.run_id)
    result_r = await reranker.reconcile_run(r.run_id)
    assert result_r.status == "cancelled"
    assert result_r.completed_at == ts
    assert reranker._load_run(r.run_id).status == "cancelled"
    assert _events(reranker._RUNS_DIR, r.run_id) == events_before


@pytest.mark.asyncio
async def test_reconcile_cancels_a_long_idle_orphan_with_terminal_events(tmp_stores) -> None:
    a = _agent_run("orphan__1", status="running", started_hours_ago=3)
    agent._save_run(a)
    result = await agent.reconcile_run(a.run_id)
    assert result.status == "cancelled"
    events = _events(agent._RUNS_DIR, a.run_id)
    assert any("orphaned" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"

    r = _reranker_run("orphan__1", status="running", started_hours_ago=3)
    reranker._save_run(r)
    result_r = await reranker.reconcile_run(r.run_id)
    assert result_r.status == "cancelled"
    events = _events(reranker._RUNS_DIR, r.run_id)
    assert any("orphaned" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reconcile_leaves_a_recent_running_record_alone(tmp_stores) -> None:
    a = _agent_run("fresh__1", status="running")
    agent._save_run(a)
    result = await agent.reconcile_run(a.run_id)
    assert result.status == "running"
    assert _events(agent._RUNS_DIR, a.run_id) == []

    r = _reranker_run("fresh__1", status="running")
    reranker._save_run(r)
    result_r = await reranker.reconcile_run(r.run_id)
    assert result_r.status == "running"
    assert _events(reranker._RUNS_DIR, r.run_id) == []


@pytest.mark.asyncio
async def test_reconcile_waits_for_the_lock_and_honours_a_completion_that_wins(tmp_stores) -> None:
    """Real interleaving (both trainers): reconciliation of an orphan-eligible record starts
    while the job holds the run lock for its terminal transition; the job completes and
    releases; reconciliation must leave the completed record exactly as it is."""
    for module, make_run in ((agent, _agent_run), (reranker, _reranker_run)):
        run = make_run("race__1", status="running", started_hours_ago=3)
        module._save_run(run)
        lock = module._run_state_lock(run.run_id)
        await lock.acquire()  # the training job is inside its terminal critical section
        reconcile = asyncio.create_task(module.reconcile_run(run.run_id))
        await asyncio.sleep(0.1)
        assert not reconcile.done()  # blocked on the lock, as intended
        completed = module._load_run(run.run_id)
        completed.status = "completed"
        completed.completed_at = datetime.now(UTC)
        module._save_run(completed)
        lock.release()
        result = await reconcile
        assert result.status == "completed"
        assert module._load_run(run.run_id).status == "completed"
        events = _events(module._RUNS_DIR, run.run_id)
        assert not any(e.get("status") == "cancelled" for e in events)


@pytest.mark.asyncio
async def test_cancel_request_waits_for_the_lock_and_honours_a_completion_that_wins(tmp_stores) -> None:
    """Real interleaving (both trainers): a cancel request lands while the run lock is held by
    the completing job (the promotion critical section); once the lock is released the cancel
    must observe the terminal record and change nothing."""
    for module, make_run in ((agent, _agent_run), (reranker, _reranker_run)):
        run = make_run("cancel_race__1", status="running")
        module._save_run(run)
        lock = module._run_state_lock(run.run_id)
        await lock.acquire()  # the job's completion/promotion critical section
        cancel = asyncio.create_task(module._request_train_run_cancel(run_id=run.run_id, reason="operator cancel"))
        await asyncio.sleep(0.1)
        assert not cancel.done()  # linearized behind the completion
        completed = module._load_run(run.run_id)
        completed.status = "completed"
        completed.completed_at = datetime.now(UTC)
        module._save_run(completed)
        lock.release()
        assert await cancel is True  # nothing to cancel; the terminal record stands
        assert module._load_run(run.run_id).status == "completed"
        events = _events(module._RUNS_DIR, run.run_id)
        assert not any(e.get("status") == "cancelled" for e in events)


@pytest.mark.asyncio
async def test_cancel_of_a_non_terminal_orphan_finalizes_through_the_authority(tmp_stores) -> None:
    for module, make_run in ((agent, _agent_run), (reranker, _reranker_run)):
        run = make_run("orphan_cancel__1", status="queued")
        module._save_run(run)
        assert await module._request_train_run_cancel(run_id=run.run_id, reason="operator cancel") is True
        stored = module._load_run(run.run_id)
        assert stored.status == "cancelled"
        assert stored.completed_at is not None
        events = _events(module._RUNS_DIR, run.run_id)
        assert any("operator cancel" in str(e.get("message") or "") for e in events)
        assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_active_run_gate_reconciles_a_stale_orphan_instead_of_blocking_forever(tmp_stores) -> None:
    a = _agent_run("pytest_authority__20260823_010101", status="running", started_hours_ago=3)
    agent._save_run(a)
    assert await agent._active_run_id_for_corpus("pytest_authority") is None  # reconciled to cancelled
    assert agent._load_run(a.run_id).status == "cancelled"

    r = _reranker_run("pytest_authority__20260823_010101", status="running", started_hours_ago=3)
    reranker._save_run(r)
    assert await reranker._active_run_id_for_corpus("pytest_authority") is None
    assert reranker._load_run(r.run_id).status == "cancelled"
