from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.api.agent import _resume_mlflow_tracking
from server.models.tribrid_config_model import AgentTrainRun, TriBridConfig
from server.retrieval.mlx_qwen3 import mlx_is_available
from server.training.control_plane import (
    build_agent_control_plane_status,
    build_agent_run_links,
    build_agent_run_operator_hint,
)
from server.training.mlflow_client import MlflowUnavailableError


class _ControlPlaneHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/flyte/healthcheck":
            payload = b"{}"
        elif path == "/flyte/api/v1/launch_plans/ragweld/development/learning-agent-train":
            payload = json.dumps(
                {
                    "launchPlans": [
                        {
                            "id": {
                                "project": "ragweld",
                                "domain": "development",
                                "name": "learning-agent-train",
                                "version": "v42",
                            }
                        }
                    ]
                }
            ).encode("utf-8")
        elif path.startswith("/flyte/api/v1/launch_plans/"):
            # flyteadmin lists an unknown launch plan name as an empty page, not a 404.
            payload = b"{}"
        elif path == "/mlflow/api/2.0/mlflow/runs/get":
            payload = json.dumps({"run": {"info": {"run_id": "ml-456"}}}).encode("utf-8")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
        cfg.training.ragweld_agent_flyte_callback_base_url = "http://192.0.2.10:58012"
        cfg.training.ragweld_agent_mlflow_tracking_url = f"{server.base_url}/mlflow"
        cfg.training.ragweld_agent_mlflow_console_base_url = "https://mlflow.ragweld.com"
        cfg.training.ragweld_agent_mlflow_experiment_name = "ragweld-learning-agent"
        cfg.training.ragweld_agent_unsloth_image = "ghcr.io/ragweld/unsloth:latest"

        status = await build_agent_control_plane_status(cfg)
        components = {component.kind: component for component in status.components}

        assert status.lane == "flyte_mlflow_unsloth"
        assert status.ready is True
        assert components["flyte"].state == "ready"
        assert "v42" in str(components["flyte"].detail)
        assert components["mlflow"].state == "ready"
        assert components["unsloth"].state == "ready"
        assert any(link.label == "Flyte Console" for link in status.links)
        assert any(link.label == "MLflow Tracking" and link.url == "https://mlflow.ragweld.com" for link in status.links)
        assert "control plane is ready" in str(status.operator_hint or "").lower()

        cfg.training.ragweld_agent_mlflow_console_base_url = ""
        status_without_console = await build_agent_control_plane_status(cfg)
        assert not any(link.label == "MLflow Tracking" for link in status_without_console.links)
    finally:
        server.close()


def test_agent_run_links_include_flyte_execution_and_mlflow_tracking() -> None:
    cfg = TriBridConfig()
    cfg.training.ragweld_agent_flyte_console_base_url = "http://flyte.example/console"
    cfg.training.ragweld_agent_flyte_project = "ragweld"
    cfg.training.ragweld_agent_flyte_domain = "development"
    cfg.training.ragweld_agent_mlflow_tracking_url = "http://mlflow.example"
    cfg.training.ragweld_agent_mlflow_console_base_url = "https://mlflow.ragweld.com"
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
        tracking_experiment_id="7",
        artifacts_uri="https://artifacts.example/runs/ml-456",
    )

    links = build_agent_run_links(run, cfg)
    operator_hint = build_agent_run_operator_hint(run, cfg)

    assert any(link.label == "Flyte Execution" and link.url.endswith("/executions/wf-123") for link in links)
    assert any(
        link.label == "MLflow Tracking"
        and link.url == "https://mlflow.ragweld.com/#/experiments/7/runs/ml-456"
        for link in links
    )
    assert any(
        link.label == "Artifacts" and link.url == "https://artifacts.example/runs/ml-456"
        for link in links
    )
    assert "flyte owns this run" in str(operator_hint).lower()

    cfg.training.ragweld_agent_mlflow_console_base_url = ""
    links_without_console = build_agent_run_links(run, cfg)
    assert not any(link.label == "MLflow Tracking" for link in links_without_console)

    cfg.training.ragweld_agent_mlflow_console_base_url = "https://mlflow.ragweld.com"
    run.tracking_experiment_id = None
    links_without_experiment = build_agent_run_links(run, cfg)
    assert not any(link.label == "MLflow Tracking" for link in links_without_experiment)

    run.workflow_phase = "RUNNING"
    phased_hint = build_agent_run_operator_hint(run, cfg)
    assert "wf-123" in str(phased_hint) and "RUNNING" in str(phased_hint)


def test_resume_mlflow_tracking_uses_persisted_experiment_id_and_requires_it() -> None:
    server = _ControlPlaneServer()
    try:
        cfg = TriBridConfig()
        cfg.training.ragweld_agent_mlflow_tracking_url = f"{server.base_url}/mlflow"
        run = AgentTrainRun(
            run_id="corpus__20260325_120000",
            corpus_id="corpus",
            status="running",
            started_at=datetime.now(UTC),
            config_snapshot=cfg.model_dump(mode="json"),
            config=cfg.to_flat_dict(),
            epochs=1,
            batch_size=1,
            lr=0.0001,
            warmup_ratio=0.0,
            max_length=128,
            tracking_backend="mlflow",
            tracking_run_id="ml-456",
            tracking_experiment_id="7",
        )

        client, handle = _resume_mlflow_tracking(run, cfg)
        assert client.tracking_url == f"{server.base_url}/mlflow"
        assert handle.run_url == f"{server.base_url}/mlflow/#/experiments/7/runs/ml-456"

        run.tracking_experiment_id = None
        with pytest.raises(MlflowUnavailableError, match="tracking_experiment_id"):
            _resume_mlflow_tracking(run, cfg)
    finally:
        server.close()


@pytest.mark.asyncio
async def test_agent_control_plane_flyte_requires_callback_and_registered_launch_plan() -> None:
    server = _ControlPlaneServer()
    try:
        cfg = TriBridConfig()
        cfg.training.ragweld_agent_workflow_backend = "flyte"
        cfg.training.ragweld_agent_flyte_admin_base_url = f"{server.base_url}/flyte"
        cfg.training.ragweld_agent_flyte_project = "ragweld"
        cfg.training.ragweld_agent_flyte_domain = "development"
        cfg.training.ragweld_agent_flyte_launchplan = "learning-agent-train"

        status = await build_agent_control_plane_status(cfg)
        flyte = next(component for component in status.components if component.kind == "flyte")
        assert flyte.state == "unconfigured"
        assert "callback base URL" in str(flyte.detail)
        assert "resolve flyte" in str(status.operator_hint).lower()

        cfg.training.ragweld_agent_flyte_callback_base_url = "http://192.0.2.10:58012"
        cfg.training.ragweld_agent_flyte_launchplan = "not-registered"
        status = await build_agent_control_plane_status(cfg)
        flyte = next(component for component in status.components if component.kind == "flyte")
        assert flyte.state == "degraded"
        assert "not registered" in str(flyte.detail)

        cfg.training.ragweld_agent_flyte_launchplan = "learning-agent-train"
        status = await build_agent_control_plane_status(cfg)
        flyte = next(component for component in status.components if component.kind == "flyte")
        assert flyte.state == "ready"
        assert status.lane == "legacy_local"
        assert "flyte orchestrates launch/status/cancel" in str(status.operator_hint).lower()
        assert "mlx_qwen3" in str(status.operator_hint)
    finally:
        server.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mlx_available", [True, False])
async def test_agent_control_plane_hint_names_the_training_lane_this_host_really_has(mlx_available: bool) -> None:
    """The deck's Learning Agent line must not advertise host execution the host cannot do."""
    cfg = TriBridConfig()

    status = await build_agent_control_plane_status(cfg, mlx_available=mlx_available)
    hint = str(status.operator_hint or "")

    assert status.execution_backend == "mlx_qwen3"
    assert "runs use the local training lane without an orchestrator" in hint
    if mlx_available:
        assert "training executes on the host mlx_qwen3 backend" in hint
        assert "fail closed" not in hint
    else:
        assert "training backend mlx_qwen3 is not available on this host; runs will fail closed" in hint
        assert "executes on the host" not in hint


@pytest.mark.asyncio
async def test_agent_control_plane_default_probe_matches_the_real_mlx_runtime_on_this_host() -> None:
    status = await build_agent_control_plane_status(TriBridConfig())
    hint = str(status.operator_hint or "")

    expected = "training executes on the host mlx_qwen3 backend" if mlx_is_available() else "runs will fail closed"
    assert expected in hint
