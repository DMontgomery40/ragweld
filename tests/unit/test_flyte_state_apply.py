"""_apply_flyte_state: the loop-thread half of the Flyte phase reconcile.

Covers the Flyte-INITIATED termination direction (Flyte reaches a terminal
phase first and the host run must follow), which the read-driven reconcile
exists to handle. No mocking: real ``FlyteExecutionState`` value objects and
real run/event files under a temp ``_RUNS_DIR`` drive the real code, including
the cross-thread-critical branch that signals a live ``asyncio.Event``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from server.api import agent
from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig
from server.training.flyte_client import FlyteExecutionState


def _write_run(tmp_runs, run_id: str, *, status: str, phase: str | None) -> AgentTrainRun:
    cfg = TriBridConfig()
    run = AgentTrainRun(
        run_id=run_id,
        corpus_id="pytest_apply",
        status=status,  # type: ignore[arg-type]
        started_at=datetime.now(UTC),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
        workflow_backend="flyte",
        workflow_run_id="ra0000000000000000aa",
        workflow_phase=phase,
    )
    (tmp_runs / run_id).mkdir(parents=True, exist_ok=True)
    (tmp_runs / run_id / "run.json").write_text(
        json.dumps(run.model_dump(mode="json", by_alias=True)), encoding="utf-8"
    )
    (tmp_runs / run_id / "metrics.jsonl").write_text("", encoding="utf-8")
    return run


@pytest.fixture
def tmp_runs(tmp_path):
    # Redirect the module run store to a temp dir by save/restore of the module attribute
    # directly. No fixtures that fake behavior are used.
    original = agent._RUNS_DIR
    agent._RUNS_DIR = tmp_path / "agent_train_runs"
    agent._RUNS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        yield agent._RUNS_DIR
    finally:
        agent._RUNS_DIR = original
        agent._flyte_reconcile_at.clear()
        agent._train_cancel_outcomes.clear()


def _events(tmp_runs, run_id: str) -> list[dict]:
    path = tmp_runs / run_id / "metrics.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.asyncio
async def test_flyte_abort_finalizes_queued_run_as_cancelled(tmp_runs) -> None:
    run = _write_run(tmp_runs, "abort_queued__1", status="queued", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="ABORTED", abort_cause="operator stop"
    )
    result = await agent._apply_flyte_state(run, state)
    assert result.status == "cancelled"
    assert result.completed_at is not None
    events = _events(tmp_runs, run.run_id)
    assert any("operator stop" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_flyte_failure_finalizes_queued_run_as_failed(tmp_runs) -> None:
    run = _write_run(tmp_runs, "fail_queued__1", status="queued", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="FAILED", error_message="node crashed"
    )
    result = await agent._apply_flyte_state(run, state)
    assert result.status == "failed"
    events = _events(tmp_runs, run.run_id)
    assert any("node crashed" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "failed"


@pytest.mark.asyncio
async def test_flyte_succeeded_while_running_is_recorded_as_inconsistency(tmp_runs) -> None:
    run = _write_run(tmp_runs, "succeed_incon__1", status="running", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="SUCCEEDED"
    )
    result = await agent._apply_flyte_state(run, state)
    assert result.status == "failed"
    events = _events(tmp_runs, run.run_id)
    assert any("refusing to infer a completed training run" in str(e.get("message") or "") for e in events)


@pytest.mark.asyncio
async def test_flyte_abort_of_running_job_signals_cancel_event_on_loop_thread(tmp_runs) -> None:
    """The branch the thread-split protects: a live in-process job must be cancelled.

    _apply_flyte_state runs on the loop thread, so setting the asyncio.Event is
    loop-safe; here we assert it is set and the outcome is recorded, and that
    the run is NOT finalized directly (the job owns finalization).
    """
    run = _write_run(tmp_runs, "abort_running__1", status="running", phase="RUNNING")
    cancel_event = asyncio.Event()
    agent._train_tasks[run.run_id] = asyncio.current_task()  # type: ignore[assignment]
    agent._train_cancel_events[run.run_id] = cancel_event
    try:
        state = FlyteExecutionState(
            project="ragweld",
            domain="development",
            name=run.workflow_run_id,
            phase="ABORTED",
            abort_cause="console abort",
        )
        result = await agent._apply_flyte_state(run, state)
        # Job-owned finalization: status stays running here; the job will apply the outcome.
        assert result.status == "running"
        assert cancel_event.is_set()
        assert agent._train_cancel_outcomes[run.run_id][0] == "cancelled"
        assert "console abort" in agent._train_cancel_outcomes[run.run_id][1]
    finally:
        agent._train_tasks.pop(run.run_id, None)
        agent._train_cancel_events.pop(run.run_id, None)
        agent._train_cancel_outcomes.pop(run.run_id, None)


@pytest.mark.asyncio
async def test_phase_only_mirror_appends_no_event_after_terminal(tmp_runs) -> None:
    run = _write_run(tmp_runs, "terminal_mirror__1", status="completed", phase="RUNNING")
    # Seed the run's own terminal complete event, as a finished run has.
    agent._append_event(
        run.run_id,
        agent.AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run.run_id, status="completed"),
    )
    before = _events(tmp_runs, run.run_id)
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="SUCCEEDED"
    )
    result = await agent._apply_flyte_state(run, state)
    assert result.status == "completed"  # terminal status is never changed by a mirror
    assert result.workflow_phase == "SUCCEEDED"
    after = _events(tmp_runs, run.run_id)
    # No log event appended after the run's complete event.
    assert len(after) == len(before)
    assert after[-1]["type"] == "complete"


@pytest.mark.asyncio
async def test_flyte_reconcile_never_overwrites_a_run_that_completed_meanwhile(tmp_runs) -> None:
    # Codex pass 17: the phase save yielded, the job completed durably, and reconciliation resumed
    # with stale `running` state and finalized the completed run as cancelled. The stored record is
    # re-read after every off-loop step and a terminal record is never overwritten.
    stale = _write_run(tmp_runs, "race__1", status="running", phase="RUNNING")
    completed = stale.model_copy(update={"status": "completed", "completed_at": datetime.now(UTC)})
    agent._save_run(completed)  # the job finished between the Flyte fetch and the apply
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=stale.workflow_run_id, phase="ABORTED", abort_cause="operator stop"
    )
    result = await agent._apply_flyte_state(stale, state)
    assert result.status == "completed"
    assert agent._load_run(stale.run_id).status == "completed"
    events = _events(tmp_runs, stale.run_id)
    assert not any(e.get("status") == "cancelled" for e in events)


@pytest.mark.asyncio
async def test_flyte_reconcile_waits_for_the_lock_and_then_honours_the_completed_record(tmp_runs) -> None:
    # Codex pass 18: a real interleaving. Reconciliation starts while the job holds the run lock
    # for its terminal transition; the job completes and releases; reconciliation then re-reads
    # the stored record and must not finalize the completed run as cancelled.
    stale = _write_run(tmp_runs, "race__2", status="running", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=stale.workflow_run_id, phase="ABORTED", abort_cause="operator stop"
    )
    lock = agent._run_state_lock(stale.run_id)
    await lock.acquire()  # the training job is inside its terminal critical section
    reconcile = asyncio.create_task(agent._apply_flyte_state(stale, state))
    await asyncio.sleep(0.05)
    assert not reconcile.done()  # blocked on the lock, as intended
    agent._save_run(stale.model_copy(update={"status": "completed", "completed_at": datetime.now(UTC)}))
    lock.release()
    result = await reconcile
    assert result.status == "completed"
    assert agent._load_run(stale.run_id).status == "completed"


@pytest.mark.asyncio
async def test_transition_authority_refuses_terminal_and_mutates_the_stored_record(tmp_runs) -> None:
    # Codex pass 18: every status change goes through one compare-and-set authority that never
    # writes a caller's stale object.
    run = _write_run(tmp_runs, "authority__1", status="queued", phase=None)

    def _to_running(stored):
        stored.status = "running"
        return stored

    updated = await agent._transition_run(run.run_id, allowed_from=frozenset({"queued"}), apply=_to_running)
    assert updated is not None and updated.status == "running"
    refused = await agent._transition_run(run.run_id, allowed_from=frozenset({"queued"}), apply=_to_running)
    assert refused is None  # CAS: the stored record is no longer queued
    assert agent._load_run(run.run_id).status == "running"
