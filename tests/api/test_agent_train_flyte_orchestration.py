"""Flyte-orchestrated Learning Agent launch/status/cancel against the live control plane.

Requires the Compose-owned ``flyte`` service (``./start.sh --with-flyte``) with
the ``learning-agent-train`` launch plan registered
(``scripts/flyte_register_learning_agent.sh``) and a live Postgres for the
corpus registry. Nothing is mocked: the test creates a real Flyte execution,
observes its phase through both Ragweld and flyteadmin, cancels it, and
verifies both sides agree.

The callback URL points at a non-routable TEST-NET address so the workflow
task cannot reach any API: the execution stays RUNNING (pod waiting on the
connect timeout) long enough for the cancel path to be exercised
deterministically. The full callback round trip (Flyte task -> execute
boundary -> MLX training -> SUCCEEDED) is an operator acceptance proof against
the host API, not an in-process test, because the task must reach a real
listening port.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from server.api.agent import _RUNS_DIR
from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig
from server.training.flyte_client import FLYTE_ABORT_PHASES, FlyteAdminClient

FLYTE_ADMIN_URL = os.environ.get("FLYTE_ADMIN_URL", "http://127.0.0.1:30080").rstrip("/")
FLYTE_PROJECT = "ragweld"
FLYTE_DOMAIN = "development"
LAUNCH_PLAN = "learning-agent-train"
UNROUTABLE_CALLBACK = "http://192.0.2.10:58012"


async def _create_corpus(client: AsyncClient, corpus_id: str) -> None:
    response = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": "tests/fixtures/acceptance_corpus"},
    )
    assert response.status_code == 200, response.text


async def _set_training_config(client: AsyncClient, corpus_id: str, updates: dict) -> None:
    response = await client.request("PATCH", f"/api/config/training?corpus_id={corpus_id}", json=updates)
    assert response.status_code == 200, response.text


async def _wait_for(predicate, *, timeout_s: float, interval_s: float = 1.0):
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        last = await predicate()
        if last:
            return last
        await asyncio.sleep(interval_s)
    return last


@pytest.mark.requires_postgres
@pytest.mark.requires_flyte
@pytest.mark.asyncio
async def test_flyte_launch_creates_execution_and_cancel_aborts_both_sides(client: AsyncClient) -> None:
    corpus_id = f"pytest_flyte_orch_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    admin = FlyteAdminClient(FLYTE_ADMIN_URL)
    run_id: str | None = None
    execution_name: str | None = None
    try:
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_workflow_backend": "flyte",
                "ragweld_agent_flyte_admin_base_url": FLYTE_ADMIN_URL,
                "ragweld_agent_flyte_project": FLYTE_PROJECT,
                "ragweld_agent_flyte_domain": FLYTE_DOMAIN,
                "ragweld_agent_flyte_launchplan": LAUNCH_PLAN,
                "ragweld_agent_flyte_callback_base_url": UNROUTABLE_CALLBACK,
            },
        )

        status = await client.get(f"/api/agent/train/control-plane/status?corpus_id={corpus_id}")
        assert status.status_code == 200, status.text
        flyte_component = next(c for c in status.json()["components"] if c["kind"] == "flyte")
        assert flyte_component["state"] == "ready", flyte_component
        assert LAUNCH_PLAN in flyte_component["detail"]

        started = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]

        run = (await client.get(f"/api/agent/train/run/{run_id}")).json()
        assert run["workflow_backend"] == "flyte"
        assert run["status"] == "queued", run
        execution_name = run["workflow_run_id"]
        assert execution_name
        assert any(link["label"] == "Flyte Execution" and execution_name in link["url"] for link in run["external_links"])
        assert "flyte execution" in str(run["operator_hint"]).lower()

        # Flyte owns the execution: it exists in flyteadmin with our inputs.
        state = admin.get_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name)
        assert state.phase in {"UNDEFINED", "QUEUED", "RUNNING", "SUCCEEDING"}, state

        # A second launch for the same corpus is refused while the Flyte run is queued.
        duplicate = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert duplicate.status_code == 409, duplicate.text

        # The execute boundary only accepts the owning execution.
        wrong = await client.post(f"/api/agent/train/run/{run_id}/execute", json={"workflow_run_id": "rabogus0000000000000"})
        assert wrong.status_code == 409, wrong.text
        assert wrong.json()["detail"]["code"] == "workflow_run_mismatch"

        listed = await client.get(f"/api/agent/train/runs?corpus_id={corpus_id}")
        meta = next(item for item in listed.json()["runs"] if item["run_id"] == run_id)
        assert meta["workflow_run_id"] == execution_name
        # flyteadmin reports UNDEFINED for a moment right after creation; the mirror may read it.
        assert meta["workflow_phase"] in {"UNDEFINED", "QUEUED", "RUNNING", "SUCCEEDING"}, meta

        # Wait until propeller has picked the execution up so termination is a real abort.
        async def _running():
            return admin.get_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name).phase == "RUNNING"

        assert await _wait_for(_running, timeout_s=120), admin.get_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name)

        cancelled = await client.post(f"/api/agent/train/run/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text

        run = (await client.get(f"/api/agent/train/run/{run_id}")).json()
        assert run["status"] == "cancelled", run
        assert run["completed_at"]

        async def _aborted():
            current = admin.get_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name)
            return current if current.phase == "ABORTED" else None

        final = await _wait_for(_aborted, timeout_s=120)
        assert final is not None and final.phase in FLYTE_ABORT_PHASES, final
        assert "ragweld operator" in str(final.abort_cause).lower()

        async def _phase_mirrored():
            current = (await client.get(f"/api/agent/train/run/{run_id}")).json()
            return current if current.get("workflow_phase") == "ABORTED" else None

        mirrored = await _wait_for(_phase_mirrored, timeout_s=90, interval_s=2.0)
        assert mirrored is not None, "run record never mirrored the ABORTED Flyte phase"
        assert mirrored["status"] == "cancelled"

        # Executing a terminal run is refused even by the owning execution.
        late = await client.post(f"/api/agent/train/run/{run_id}/execute", json={"workflow_run_id": execution_name})
        assert late.status_code == 409, late.text
        assert late.json()["detail"]["code"] == "run_terminal"

        events = (await client.get(f"/api/agent/train/run/{run_id}/metrics")).json()["events"]
        messages = [str(event.get("message") or "") for event in events]
        assert any("Flyte execution" in message and "created" in message for message in messages)
        assert any("termination requested" in message for message in messages)
        assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"
    finally:
        if execution_name:
            try:
                admin.terminate_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name, cause="pytest cleanup")
            except Exception:
                pass
        if run_id:
            shutil.rmtree(_RUNS_DIR / run_id, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.requires_postgres
@pytest.mark.requires_flyte
@pytest.mark.asyncio
async def test_flyte_side_abort_of_queued_run_follows_into_cancelled(client: AsyncClient) -> None:
    """Flyte terminates first (console/CLI); the queued host run must follow.

    Drives the read-driven reconcile end to end: no /cancel is called on
    Ragweld — the run only becomes cancelled because a GET observes the ABORTED
    Flyte phase and finalizes it with Flyte's cause.
    """
    corpus_id = f"pytest_flyte_side_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    admin = FlyteAdminClient(FLYTE_ADMIN_URL)
    run_id: str | None = None
    execution_name: str | None = None
    try:
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_workflow_backend": "flyte",
                "ragweld_agent_flyte_admin_base_url": FLYTE_ADMIN_URL,
                "ragweld_agent_flyte_project": FLYTE_PROJECT,
                "ragweld_agent_flyte_domain": FLYTE_DOMAIN,
                "ragweld_agent_flyte_launchplan": LAUNCH_PLAN,
                "ragweld_agent_flyte_callback_base_url": UNROUTABLE_CALLBACK,
            },
        )
        started = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert started.status_code == 200, started.text
        run_id = started.json()["run_id"]
        run = (await client.get(f"/api/agent/train/run/{run_id}")).json()
        execution_name = run["workflow_run_id"]
        assert run["status"] == "queued"

        # Terminate out-of-band, as an operator would from the Flyte console/CLI.
        admin.terminate_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name, cause="flyte-side operator abort")

        async def _followed():
            current = (await client.get(f"/api/agent/train/run/{run_id}")).json()
            return current if current["status"] == "cancelled" else None

        followed = await _wait_for(_followed, timeout_s=90, interval_s=2.0)
        assert followed is not None, "queued run never followed the Flyte-side abort into cancelled"
        assert followed["workflow_phase"] in FLYTE_ABORT_PHASES
        assert followed["completed_at"]

        events = (await client.get(f"/api/agent/train/run/{run_id}/metrics")).json()["events"]
        messages = [str(e.get("message") or "") for e in events]
        assert any("abort" in m.lower() for m in messages)
        assert events[-1]["type"] == "complete" and events[-1]["status"] == "cancelled"

        # No new run was started and the corpus is launchable again.
        assert (await client.post("/api/agent/train/start", json={"repo_id": corpus_id})).status_code in {200, 503}
    finally:
        if execution_name:
            try:
                admin.terminate_execution(FLYTE_PROJECT, FLYTE_DOMAIN, execution_name, cause="pytest cleanup")
            except Exception:
                pass
        if run_id:
            shutil.rmtree(_RUNS_DIR / run_id, ignore_errors=True)
        # A follow-up launch may have created a second run; clean the corpus's runs.
        for extra in _RUNS_DIR.glob(f"{corpus_id}__*"):
            shutil.rmtree(extra, ignore_errors=True)
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_execute_boundary_refuses_runs_not_owned_by_flyte(client: AsyncClient) -> None:
    run_id = f"pytest_local_lane_{uuid.uuid4().hex[:8]}__20260821_000000"
    cfg = TriBridConfig()
    run = AgentTrainRun(
        run_id=run_id,
        corpus_id="pytest_local_lane",
        status="queued",
        started_at=datetime.now(UTC),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
        workflow_backend="local",
    )
    run_dir = _RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps(run.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    try:
        response = await client.post(f"/api/agent/train/run/{run_id}/execute", json={"workflow_run_id": "ra00000000000000000a"})
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "workflow_backend_mismatch"

        missing = await client.post("/api/agent/train/run/does-not-exist/execute", json={"workflow_run_id": "ra00000000000000000a"})
        assert missing.status_code == 404

        invalid = await client.post(f"/api/agent/train/run/{run_id}/execute", json={"workflow_run_id": ""})
        assert invalid.status_code == 422
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
