from __future__ import annotations

import asyncio
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from server.models.tribrid_config_model import (
    AgentTrainControlPlaneStatusResponse,
    AgentTrainRun,
    TraceExternalLink,
    TrainingControlPlaneComponentStatus,
    TriBridConfig,
)
from server.training.flyte_client import FlyteAdminClient, FlyteUnavailableError

_TIMEOUT = httpx.Timeout(3.0, connect=2.0)


def _clean_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def _join_url(base: str, suffix: str) -> str:
    clean = _clean_url(base)
    if not clean:
        return ""
    return f"{clean}/{str(suffix or '').lstrip('/')}"


def _guess_flyte_console_base(admin_base_url: str) -> str:
    admin = _clean_url(admin_base_url)
    if not admin:
        return ""
    parts = urlsplit(admin)
    path = parts.path or ""
    for suffix in ("/api/v1", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    path = f"{path.rstrip('/')}/console"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _flyte_console_execution_url(console_base_url: str, project: str, domain: str, execution_name: str) -> str:
    base = _clean_url(console_base_url)
    if not (base and project and domain and execution_name):
        return ""
    return (
        f"{base}/projects/{quote(project, safe='')}"
        f"/domains/{quote(domain, safe='')}"
        f"/executions/{quote(execution_name, safe='')}"
    )


def _mlflow_console_run_url(console_base_url: str, experiment_id: str, run_id: str) -> str:
    base = _clean_url(console_base_url)
    experiment = str(experiment_id or "").strip()
    tracking_run = str(run_id or "").strip()
    if not (base and experiment and tracking_run):
        return ""
    return (
        f"{base}/#/experiments/{quote(experiment, safe='')}"
        f"/runs/{quote(tracking_run, safe='')}"
    )


async def _probe_flyte_launch_plan(admin_base_url: str, project: str, domain: str, launchplan: str) -> tuple[bool, str]:
    """Functional readiness: admin healthy AND the launch plan is registered."""

    def _probe() -> str:
        client = FlyteAdminClient(admin_base_url, timeout_s=3.0)
        client.healthcheck()
        return client.resolve_launch_plan(project, domain, launchplan).version

    try:
        version = await asyncio.to_thread(_probe)
    except FlyteUnavailableError as exc:
        return False, str(exc)
    return True, f"Launch plan {launchplan} v{version} registered in {project}/{domain}."



async def _probe_mlflow_experiment(tracking_url: str, experiment_name: str) -> tuple[bool, str]:
    base = _clean_url(tracking_url)
    name = str(experiment_name or "").strip()
    if not base:
        return False, "MLflow tracking URL is empty."
    if not name:
        return False, "MLflow experiment name is empty."
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                _join_url(base, "/api/2.0/mlflow/experiments/get-by-name"),
                params={"experiment_name": name},
            )
        if response.status_code < 400:
            return True, f"Experiment '{name}' reachable."
        if response.status_code == 404:
            # Server reachable; experiment will be created on first tracked run.
            return True, f"MLflow reachable; experiment '{name}' will be created on first run."
        return False, f"HTTP {response.status_code} for experiment '{name}'."
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _top_level_links(components: list[TrainingControlPlaneComponentStatus]) -> list[TraceExternalLink]:
    links: list[TraceExternalLink] = []
    seen: set[tuple[str, str]] = set()
    for component in components:
        for link in component.links:
            key = (link.kind, link.url)
            if key in seen:
                continue
            seen.add(key)
            links.append(link)
    return links


def build_agent_run_links(run: AgentTrainRun, cfg: TriBridConfig) -> list[TraceExternalLink]:
    links: list[TraceExternalLink] = list(run.external_links or [])
    seen = {(link.kind, link.url) for link in links}

    if str(run.workflow_backend or "").strip() == "flyte" and str(run.workflow_run_id or "").strip():
        console_base = _clean_url(cfg.training.ragweld_agent_flyte_console_base_url) or _guess_flyte_console_base(
            cfg.training.ragweld_agent_flyte_admin_base_url
        )
        flyte_url = _flyte_console_execution_url(
            console_base,
            str(cfg.training.ragweld_agent_flyte_project or "").strip(),
            str(cfg.training.ragweld_agent_flyte_domain or "").strip(),
            str(run.workflow_run_id or "").strip(),
        )
        if flyte_url and ("custom", flyte_url) not in seen:
            seen.add(("custom", flyte_url))
            links.append(
                TraceExternalLink(
                    label="Flyte Execution",
                    kind="custom",
                    url=flyte_url,
                    detail=f"Workflow execution {run.workflow_run_id}",
                )
            )

    mlflow_console_url = _clean_url(cfg.training.ragweld_agent_mlflow_console_base_url)
    if str(run.tracking_backend or "").strip() == "mlflow" and mlflow_console_url:
        run_link_url = mlflow_console_url
        tracking_run_id = str(run.tracking_run_id or "").strip()
        tracking_experiment_id = str(run.tracking_experiment_id or "").strip()
        if tracking_run_id and tracking_experiment_id:
            run_link_url = _mlflow_console_run_url(mlflow_console_url, tracking_experiment_id, tracking_run_id)
            detail = f"MLflow run {run.tracking_run_id}"
            key: tuple[Literal["grafana", "tempo", "langfuse", "custom"], str] = ("custom", run_link_url)
            if key not in seen:
                seen.add(key)
                links.append(
                    TraceExternalLink(
                        label="MLflow Tracking",
                        kind="custom",
                        url=run_link_url,
                        detail=detail,
                    )
                )

    artifacts_uri = str(run.artifacts_uri or "").strip()
    if artifacts_uri.startswith("http://") or artifacts_uri.startswith("https://"):
        key = ("custom", artifacts_uri)
        if key not in seen:
            links.append(
                TraceExternalLink(
                    label="Artifacts",
                    kind="custom",
                    url=artifacts_uri,
                    detail="Run artifact location",
                )
            )

    return links


def build_agent_run_operator_hint(run: AgentTrainRun, cfg: TriBridConfig) -> str | None:
    target_lane = (
        str(cfg.training.ragweld_agent_workflow_backend) == "flyte"
        and str(cfg.training.ragweld_agent_tracking_backend) == "mlflow"
        and str(cfg.training.ragweld_agent_backend) == "unsloth"
    )
    if target_lane and str(run.workflow_backend or "").strip() != "flyte":
        return (
            "Learning Agent target stack is configured for Flyte + MLflow + Unsloth, "
            "but this run still used the local training lane."
        )
    if str(run.workflow_backend or "").strip() == "flyte":
        phase = str(run.workflow_phase or "").strip()
        execution = str(run.workflow_run_id or "").strip()
        if phase and execution:
            return (
                f"Flyte execution {execution} owns this run's workflow state (phase {phase}); "
                f"training executes on the host {run.execution_backend} backend through the execute boundary."
            )
        return "Flyte owns this run's workflow state; training executes on the host through the execute boundary."
    if str(run.workflow_backend or "").strip() == "local":
        return "Local Learning Agent lane active; select workflow=flyte in Training Center to orchestrate runs through Flyte."
    return None


async def build_agent_control_plane_status(cfg: TriBridConfig) -> AgentTrainControlPlaneStatusResponse:
    workflow_backend = str(cfg.training.ragweld_agent_workflow_backend or "local").strip() or "local"
    tracking_backend = str(cfg.training.ragweld_agent_tracking_backend or "local").strip() or "local"
    execution_backend = str(cfg.training.ragweld_agent_backend or "mlx_qwen3").strip() or "mlx_qwen3"

    flyte_admin = _clean_url(cfg.training.ragweld_agent_flyte_admin_base_url)
    flyte_console = _clean_url(cfg.training.ragweld_agent_flyte_console_base_url) or _guess_flyte_console_base(flyte_admin)
    flyte_project = str(cfg.training.ragweld_agent_flyte_project or "").strip()
    flyte_domain = str(cfg.training.ragweld_agent_flyte_domain or "").strip()
    flyte_launchplan = str(cfg.training.ragweld_agent_flyte_launchplan or "").strip()
    flyte_callback = _clean_url(cfg.training.ragweld_agent_flyte_callback_base_url)
    mlflow_tracking_url = _clean_url(cfg.training.ragweld_agent_mlflow_tracking_url)
    mlflow_console_url = _clean_url(cfg.training.ragweld_agent_mlflow_console_base_url)
    mlflow_experiment = str(cfg.training.ragweld_agent_mlflow_experiment_name or "").strip()
    unsloth_image = str(cfg.training.ragweld_agent_unsloth_image or "").strip()

    components: list[TrainingControlPlaneComponentStatus] = []

    flyte_enabled = workflow_backend == "flyte"
    flyte_links: list[TraceExternalLink] = []
    if flyte_console:
        flyte_links.append(
            TraceExternalLink(
                label="Flyte Console",
                kind="custom",
                url=flyte_console,
                detail="Workflow execution UI",
            )
        )
    elif flyte_admin:
        flyte_links.append(
            TraceExternalLink(
                label="Flyte Admin",
                kind="custom",
                url=flyte_admin,
                detail="Flyte control-plane endpoint",
            )
        )
    flyte_missing = [
        name
        for name, value in (
            ("admin base URL", flyte_admin),
            ("project", flyte_project),
            ("domain", flyte_domain),
            ("launch plan", flyte_launchplan),
            ("callback base URL", flyte_callback),
        )
        if not value
    ]
    if not flyte_enabled:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="flyte",
                label="Flyte",
                enabled=False,
                configured=bool(flyte_admin or flyte_console or flyte_launchplan),
                state="disabled",
                detail="Local workflow lane active; runs execute in-process without an orchestrator.",
                links=flyte_links,
            )
        )
    elif flyte_missing:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="flyte",
                label="Flyte",
                enabled=True,
                configured=False,
                state="unconfigured",
                detail=f"Missing: {', '.join(flyte_missing)}.",
                links=flyte_links,
            )
        )
    else:
        ok, detail = await _probe_flyte_launch_plan(flyte_admin, flyte_project, flyte_domain, flyte_launchplan)
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="flyte",
                label="Flyte",
                enabled=True,
                configured=True,
                state="ready" if ok else "degraded",
                detail=detail,
                links=flyte_links,
            )
        )

    mlflow_enabled = tracking_backend == "mlflow"
    mlflow_links = (
        [
            TraceExternalLink(
                label="MLflow Tracking",
                kind="custom",
                url=mlflow_console_url,
                detail=f"Experiment {mlflow_experiment or 'unconfigured'}",
            )
        ]
        if mlflow_console_url
        else []
    )
    mlflow_missing = [
        name
        for name, value in (
            ("tracking URL", mlflow_tracking_url),
            ("experiment name", mlflow_experiment),
        )
        if not value
    ]
    if not mlflow_enabled:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="mlflow",
                label="MLflow",
                enabled=False,
                configured=bool(mlflow_tracking_url),
                state="disabled",
                detail="Local run/artifact truth still active.",
                links=mlflow_links,
            )
        )
    elif mlflow_missing:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="mlflow",
                label="MLflow",
                enabled=True,
                configured=False,
                state="unconfigured",
                detail=f"Missing: {', '.join(mlflow_missing)}.",
                links=mlflow_links,
            )
        )
    else:
        ok, detail = await _probe_mlflow_experiment(mlflow_tracking_url, mlflow_experiment)
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="mlflow",
                label="MLflow",
                enabled=True,
                configured=True,
                state="ready" if ok else "degraded",
                detail=detail,
                links=mlflow_links,
            )
        )

    unsloth_enabled = execution_backend == "unsloth"
    if not unsloth_enabled:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="unsloth",
                label="Unsloth",
                enabled=False,
                configured=bool(unsloth_image),
                state="disabled",
                detail=f"Execution backend is {execution_backend or 'unconfigured'}.",
                links=[],
            )
        )
    else:
        components.append(
            TrainingControlPlaneComponentStatus(
                kind="unsloth",
                label="Unsloth",
                enabled=True,
                configured=bool(unsloth_image),
                state="ready" if unsloth_image else "unconfigured",
                detail=(
                    f"Image {unsloth_image}"
                    if unsloth_image
                    else "Configure an Unsloth image or artifact reference for the Flyte task."
                ),
                links=[],
            )
        )

    lane: Literal["legacy_local", "flyte_mlflow_unsloth"] = (
        "flyte_mlflow_unsloth"
        if workflow_backend == "flyte" and tracking_backend == "mlflow" and execution_backend == "unsloth"
        else "legacy_local"
    )
    ready = lane == "flyte_mlflow_unsloth" and all(
        component.state == "ready" for component in components if component.enabled
    )

    degraded = [component.label for component in components if component.enabled and component.state != "ready"]
    if degraded:
        operator_hint = (
            f"Resolve {', '.join(degraded)} readiness before launching Learning Agent runs; "
            "launch refuses with a typed 503 until every selected backend is reachable."
        )
    elif lane == "flyte_mlflow_unsloth":
        operator_hint = (
            "Control plane is ready: Flyte orchestrates launch/status/cancel, MLflow records runs, "
            "and Unsloth executes training."
        )
    else:
        workflow_text = (
            "Flyte orchestrates launch/status/cancel"
            if workflow_backend == "flyte"
            else "runs use the local training lane without an orchestrator"
        )
        tracking_text = "MLflow records runs" if tracking_backend == "mlflow" else "run truth stays in local run files"
        execution_text = (
            f"training executes on the host {execution_backend} backend"
            if execution_backend != "unsloth"
            else "Unsloth executes training"
        )
        operator_hint = (
            f"Learning Agent: {workflow_text}; {tracking_text}; {execution_text}. "
            "The full target lane is workflow=flyte, tracking=mlflow, execution=unsloth (Unsloth needs a CUDA host)."
        )

    return AgentTrainControlPlaneStatusResponse(
        ok=True,
        lane=lane,
        ready=ready,
        workflow_backend=workflow_backend,
        tracking_backend=tracking_backend,
        execution_backend=execution_backend,
        components=components,
        links=_top_level_links(components),
        operator_hint=operator_hint,
    )
