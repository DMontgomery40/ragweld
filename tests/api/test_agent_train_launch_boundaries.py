"""Launch-time backend boundary contract for Learning Agent runs.

Configured-but-unavailable target backends must fail closed with typed 503
details; the launcher never silently substitutes the local lane. Real corpora
and the real config store are used — no mocks.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from server.api import agent as agent_api
from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig


class _MlflowOutageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/2.0/mlflow/runs/get":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps({"message": "tracking unavailable"}).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class _MlflowOutageServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _MlflowOutageHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def tmp_agent_run_store(tmp_path: Path):
    original = agent_api._RUNS_DIR
    agent_api._RUNS_DIR = tmp_path / "agent_train_runs"
    agent_api._RUNS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        yield agent_api._RUNS_DIR
    finally:
        agent_api._RUNS_DIR = original
        agent_api._train_tasks.clear()
        agent_api._train_cancel_events.clear()
        agent_api._train_cancel_outcomes.clear()
        agent_api._train_start_guard.clear()


async def _create_corpus(client: AsyncClient, corpus_id: str) -> None:
    response = await client.post(
        "/api/corpora",
        json={
            "corpus_id": corpus_id,
            "name": corpus_id,
            "path": "tests/fixtures/acceptance_corpus",
        },
    )
    assert response.status_code == 200, response.text


async def _set_training_config(client: AsyncClient, corpus_id: str, updates: dict) -> None:
    response = await client.request(
        "PATCH",
        f"/api/config/training?corpus_id={corpus_id}",
        json=updates,
    )
    assert response.status_code == 200, response.text


async def _delete_corpus(client: AsyncClient, corpus_id: str) -> None:
    await client.delete(f"/api/corpora/{corpus_id}")


async def _load_scoped_cfg(client: AsyncClient, corpus_id: str) -> TriBridConfig:
    response = await client.get("/api/config", params={"corpus_id": corpus_id})
    assert response.status_code == 200, response.text
    return TriBridConfig.model_validate(response.json())


def _persist_agent_run(
    *,
    corpus_id: str,
    cfg: TriBridConfig,
    tracking_run_id: str,
    tracking_experiment_id: str | None,
) -> AgentTrainRun:
    run = AgentTrainRun(
        run_id=f"{corpus_id}__{uuid.uuid4().hex[:12]}",
        corpus_id=corpus_id,
        status="running",
        started_at=datetime.now(UTC),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="eval_loss",
        primary_goal="minimize",
        metrics_available=["train_loss", "eval_loss"],
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
        workflow_backend="local",
        tracking_backend="mlflow",
        execution_backend="mlx_qwen3",
        tracking_run_id=tracking_run_id,
        tracking_experiment_id=tracking_experiment_id,
    )
    agent_api._save_run(run)
    return run


def _run_events(runs_dir: Path, run_id: str) -> list[dict[str, Any]]:
    metrics_path = runs_dir / run_id / "metrics.jsonl"
    if not metrics_path.exists():
        return []
    return [json.loads(line) for line in metrics_path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_flyte_workflow_selection_fails_closed_without_required_config(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_flyte_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(client, corpus_id, {"ragweld_agent_workflow_backend": "flyte"})
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "workflow_backend_unavailable"
        assert detail["backend"] == "flyte"
        assert "required config is empty" in detail["message"].lower()
        assert "ragweld_agent_flyte_admin_base_url" in detail["message"]
        assert "ragweld_agent_flyte_callback_base_url" in detail["message"]
        assert "does not fall back" in detail["operator_hint"].lower()
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_flyte_workflow_selection_fails_closed_when_admin_unreachable(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_flyte_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_workflow_backend": "flyte",
                # Real-but-closed local port: connection is refused.
                "ragweld_agent_flyte_admin_base_url": "http://127.0.0.1:9",
                "ragweld_agent_flyte_project": "ragweld",
                "ragweld_agent_flyte_domain": "development",
                "ragweld_agent_flyte_launchplan": "learning-agent-train",
                "ragweld_agent_flyte_callback_base_url": "http://192.0.2.10:58012",
            },
        )
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "workflow_backend_unavailable"
        assert detail["backend"] == "flyte"
        assert "unreachable" in detail["message"].lower()
        assert "flyte_register_learning_agent" in detail["operator_hint"]
        assert "does not fall back" in detail["operator_hint"].lower()

        runs = await client.get(f"/api/agent/train/runs?corpus_id={corpus_id}")
        assert runs.status_code == 200
        assert runs.json()["runs"] == []
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_unsloth_execution_selection_reports_exact_hardware_blocker(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_unsloth_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(client, corpus_id, {"ragweld_agent_backend": "unsloth"})
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "execution_backend_unavailable"
        assert detail["backend"] == "unsloth"
        assert "cuda" in detail["message"].lower()
        assert detail["operator_hint"]
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_mlflow_tracking_selection_fails_closed_when_unreachable(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_mlflow_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        # Point tracking at a real-but-closed local port: connection is refused.
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_tracking_backend": "mlflow",
                "ragweld_agent_mlflow_tracking_url": "http://127.0.0.1:9",
            },
        )
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "tracking_backend_unavailable"
        assert detail["backend"] == "mlflow"
        assert "unreachable" in detail["message"].lower()
        assert "does not fall back" in detail["operator_hint"].lower()
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_resumed_mlflow_run_fails_closed_without_persisted_experiment_id(
    client: AsyncClient, tmp_agent_run_store: Path
) -> None:
    corpus_id = f"pytest_resume_mlflow_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_tracking_backend": "mlflow",
                "ragweld_agent_mlflow_tracking_url": "http://127.0.0.1:55500",
                "ragweld_agent_mlflow_experiment_name": "ragweld-learning-agent",
            },
        )
        cfg = await _load_scoped_cfg(client, corpus_id)
        run = _persist_agent_run(
            corpus_id=corpus_id,
            cfg=cfg,
            tracking_run_id="ml-missing-experiment",
            tracking_experiment_id=None,
        )

        await agent_api._run_train_job(run_id=run.run_id, corpus_id=corpus_id)

        stored = agent_api._load_run(run.run_id)
        assert stored.status == "failed"
        assert stored.completed_at is not None
        assert not (tmp_agent_run_store / run.run_id / "model").exists()

        events = _run_events(tmp_agent_run_store, run.run_id)
        assert not any(event["type"] in {"progress", "metrics", "telemetry"} for event in events)
        error_event = next(event for event in events if event["type"] == "error")
        assert error_event["status"] == "failed"
        assert "tracking_backend_unavailable" in str(error_event["message"])
        assert "tracking_experiment_id" in str(error_event["message"])
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_resumed_mlflow_run_fails_closed_when_tracking_is_unavailable(
    client: AsyncClient, tmp_agent_run_store: Path
) -> None:
    outage = _MlflowOutageServer()
    corpus_id = f"pytest_resume_mlflow_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_tracking_backend": "mlflow",
                "ragweld_agent_mlflow_tracking_url": outage.base_url,
                "ragweld_agent_mlflow_experiment_name": "ragweld-learning-agent",
            },
        )
        cfg = await _load_scoped_cfg(client, corpus_id)
        run = _persist_agent_run(
            corpus_id=corpus_id,
            cfg=cfg,
            tracking_run_id="ml-503",
            tracking_experiment_id="7",
        )

        await agent_api._run_train_job(run_id=run.run_id, corpus_id=corpus_id)

        stored = agent_api._load_run(run.run_id)
        assert stored.status == "failed"
        assert stored.completed_at is not None
        assert not (tmp_agent_run_store / run.run_id / "model").exists()

        events = _run_events(tmp_agent_run_store, run.run_id)
        assert not any(event["type"] in {"progress", "metrics", "telemetry"} for event in events)
        error_event = next(event for event in events if event["type"] == "error")
        assert error_event["status"] == "failed"
        assert "tracking_backend_unavailable" in str(error_event["message"])
        assert "/runs/get" in str(error_event["message"])
        assert "503" in str(error_event["message"])
    finally:
        outage.close()
        await _delete_corpus(client, corpus_id)
