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


def test_flyte_abort_finalizes_queued_run_as_cancelled(tmp_runs) -> None:
    run = _write_run(tmp_runs, "abort_queued__1", status="queued", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="ABORTED", abort_cause="operator stop"
    )
    result = agent._apply_flyte_state(run, state)
    assert result.status == "cancelled"
    assert result.completed_at is not None
    events = _events(tmp_runs, run.run_id)
    assert any("operator stop" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"


def test_flyte_failure_finalizes_queued_run_as_failed(tmp_runs) -> None:
    run = _write_run(tmp_runs, "fail_queued__1", status="queued", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="FAILED", error_message="node crashed"
    )
    result = agent._apply_flyte_state(run, state)
    assert result.status == "failed"
    events = _events(tmp_runs, run.run_id)
    assert any("node crashed" in str(e.get("message") or "") for e in events)
    assert events[-1]["type"] == "complete" and events[-1]["status"] == "failed"


def test_flyte_succeeded_while_running_is_recorded_as_inconsistency(tmp_runs) -> None:
    run = _write_run(tmp_runs, "succeed_incon__1", status="running", phase="RUNNING")
    state = FlyteExecutionState(
        project="ragweld", domain="development", name=run.workflow_run_id, phase="SUCCEEDED"
    )
    result = agent._apply_flyte_state(run, state)
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
        result = agent._apply_flyte_state(run, state)
        # Job-owned finalization: status stays running here; the job will apply the outcome.
        assert result.status == "running"
        assert cancel_event.is_set()
        assert agent._train_cancel_outcomes[run.run_id][0] == "cancelled"
        assert "console abort" in agent._train_cancel_outcomes[run.run_id][1]
    finally:
        agent._train_tasks.pop(run.run_id, None)
        agent._train_cancel_events.pop(run.run_id, None)
        agent._train_cancel_outcomes.pop(run.run_id, None)


def test_phase_only_mirror_appends_no_event_after_terminal(tmp_runs) -> None:
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
    result = agent._apply_flyte_state(run, state)
    assert result.status == "completed"  # terminal status is never changed by a mirror
    assert result.workflow_phase == "SUCCEEDED"
    after = _events(tmp_runs, run.run_id)
    # No log event appended after the run's complete event.
    assert len(after) == len(before)
    assert after[-1]["type"] == "complete"
