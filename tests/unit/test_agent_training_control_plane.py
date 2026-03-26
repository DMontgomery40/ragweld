from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig
from server.training.control_plane import (
    build_agent_control_plane_status,
    build_agent_run_links,
    build_agent_run_operator_hint,
)


class _ControlPlaneHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/flyte/api/v1/openapi":
            payload = json.dumps({"openapi": "3.0.0"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/mlflow/api/2.0/mlflow/experiments/get-by-name":
            payload = json.dumps(
                {"experiment": {"experiment_id": "7", "name": "ragweld-learning-agent"}}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


class _ControlPlaneServer:
    def __init__(self) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ControlPlaneHandler)
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


@pytest.mark.asyncio
async def test_agent_control_plane_status_defaults_to_legacy_local() -> None:
    cfg = TriBridConfig()

    status = await build_agent_control_plane_status(cfg)
    components = {component.kind: component for component in status.components}

    assert status.lane == "legacy_local"
    assert status.ready is False
    assert status.workflow_backend == "local"
    assert status.tracking_backend == "local"
    assert status.execution_backend == "mlx_qwen3"
    assert components["flyte"].state == "disabled"
    assert components["mlflow"].state == "disabled"
    assert components["unsloth"].state == "disabled"
    assert "local training lane" in str(status.operator_hint or "").lower()


@pytest.mark.asyncio
async def test_agent_control_plane_status_reports_ready_flyte_mlflow_unsloth_lane() -> None:
    server = _ControlPlaneServer()
    try:
        cfg = TriBridConfig()
        cfg.training.ragweld_agent_workflow_backend = "flyte"
        cfg.training.ragweld_agent_tracking_backend = "mlflow"
        cfg.training.ragweld_agent_backend = "unsloth"
        cfg.training.ragweld_agent_flyte_admin_base_url = f"{server.base_url}/flyte"
        cfg.training.ragweld_agent_flyte_console_base_url = f"{server.base_url}/console"
        cfg.training.ragweld_agent_flyte_project = "ragweld"
        cfg.training.ragweld_agent_flyte_domain = "development"
        cfg.training.ragweld_agent_flyte_launchplan = "learning-agent-train"
        cfg.training.ragweld_agent_mlflow_tracking_url = f"{server.base_url}/mlflow"
        cfg.training.ragweld_agent_mlflow_experiment_name = "ragweld-learning-agent"
        cfg.training.ragweld_agent_unsloth_image = "ghcr.io/ragweld/unsloth:latest"

        status = await build_agent_control_plane_status(cfg)
        components = {component.kind: component for component in status.components}

        assert status.lane == "flyte_mlflow_unsloth"
        assert status.ready is True
        assert components["flyte"].state == "ready"
        assert components["mlflow"].state == "ready"
        assert components["unsloth"].state == "ready"
        assert any(link.label == "Flyte Console" for link in status.links)
        assert any(link.label == "MLflow Tracking" for link in status.links)
        assert "control plane is ready" in str(status.operator_hint or "").lower()
    finally:
        server.close()


def test_agent_run_links_include_flyte_execution_and_mlflow_tracking() -> None:
    cfg = TriBridConfig()
    cfg.training.ragweld_agent_flyte_console_base_url = "http://flyte.example/console"
    cfg.training.ragweld_agent_flyte_project = "ragweld"
    cfg.training.ragweld_agent_flyte_domain = "development"
    cfg.training.ragweld_agent_mlflow_tracking_url = "http://mlflow.example"
    cfg.training.ragweld_agent_mlflow_experiment_name = "ragweld-learning-agent"
    cfg.training.ragweld_agent_workflow_backend = "flyte"
    cfg.training.ragweld_agent_tracking_backend = "mlflow"
    cfg.training.ragweld_agent_backend = "unsloth"

    run = AgentTrainRun(
        run_id="corpus__20260325_120000",
        corpus_id="corpus",
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
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
        workflow_backend="flyte",
        tracking_backend="mlflow",
        execution_backend="unsloth",
        workflow_run_id="wf-123",
        tracking_run_id="ml-456",
    )

    links = build_agent_run_links(run, cfg)
    operator_hint = build_agent_run_operator_hint(run, cfg)

    assert any(link.label == "Flyte Execution" and link.url.endswith("/executions/wf-123") for link in links)
    assert any(link.label == "MLflow Tracking" and link.url == "http://mlflow.example" for link in links)
    assert operator_hint is None
