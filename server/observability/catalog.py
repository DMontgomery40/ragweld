from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from server.models.tribrid_config_model import (
    ObservabilityCatalogResponse,
    ObservabilityDashboardFamily,
    ObservabilityDashboardVariable,
    ObservabilityWorkbenchLink,
    TraceExternalLink,
    TriBridConfig,
)

_DASHBOARD_ROOT = Path(__file__).resolve().parents[2] / "infra" / "grafana" / "provisioning" / "dashboards"


def grafana_dashboard_url(config: TriBridConfig, *, uid: str, slug: str) -> str | None:
    base = str(config.ui.grafana_base_url or "").strip().rstrip("/")
    if not base or not uid:
        return None
    org_id = int(config.ui.grafana_org_id or 0)
    suffix = f"/d/{uid}/{slug or uid}"
    if org_id > 0:
        suffix = f"{suffix}?orgId={org_id}"
    return f"{base}{suffix}"


def _route_link(
    *,
    label: str,
    path: str,
    subtab: str | None = None,
    description: str,
) -> ObservabilityWorkbenchLink:
    return ObservabilityWorkbenchLink(
        label=label,
        path=path,
        subtab=subtab,
        description=description,
    )


def build_workbench_links() -> list[ObservabilityWorkbenchLink]:
    return [
        _route_link(
            label="Grafana Overview",
            path="/grafana?subtab=overview",
            subtab="overview",
            description="Primary operator landing surface for the current incident picture.",
        ),
        _route_link(
            label="Grafana Incidents",
            path="/grafana?subtab=incidents",
            subtab="incidents",
            description="Unified incident feed spanning infrastructure, workflow, retrieval, eval, and prompt drift.",
        ),
        _route_link(
            label="Infrastructure Monitoring",
            path="/infrastructure?subtab=monitoring",
            subtab="monitoring",
            description="Cross-stack monitoring view embedded in the infrastructure workspace.",
        ),
        _route_link(
            label="Eval Analysis",
            path="/eval?subtab=analysis",
            subtab="analysis",
            description="Run-to-run eval drilldown and regression analysis.",
        ),
        _route_link(
            label="Benchmark",
            path="/benchmark",
            description="Model and provider benchmark output comparison with latency breakdowns.",
        ),
        _route_link(
            label="System Prompts",
            path="/eval?subtab=prompts",
            subtab="prompts",
            description="Prompt-set editing and change review for downstream regressions.",
        ),
    ]


_DEFAULT_VARIABLES = [
    ObservabilityDashboardVariable(
        id="corpus_id",
        label="Corpus",
        kind="textbox",
        default_value="*",
        description="Corpus or repo scope for the dashboard.",
    ),
    ObservabilityDashboardVariable(
        id="run_id",
        label="Run",
        kind="textbox",
        default_value="*",
        description="Eval, benchmark, or workflow run identifier.",
    ),
    ObservabilityDashboardVariable(
        id="model",
        label="Model",
        kind="textbox",
        default_value="*",
        description="Served or benchmarked model identifier.",
    ),
    ObservabilityDashboardVariable(
        id="provider",
        label="Provider",
        kind="textbox",
        default_value="*",
        description="Gateway/provider route for traffic or benchmark slices.",
    ),
    ObservabilityDashboardVariable(
        id="prompt_set",
        label="Prompt Set",
        kind="textbox",
        default_value="current",
        description="Prompt-set lineage version or alias.",
    ),
    ObservabilityDashboardVariable(
        id="workflow_id",
        label="Workflow",
        kind="textbox",
        default_value="*",
        description="Workflow identifier for Flyte or training runs.",
    ),
    ObservabilityDashboardVariable(
        id="time_range",
        label="Time Range",
        kind="time_range",
        default_value="1h",
        description="Grafana time range for the dashboard view.",
    ),
]

_DASHBOARD_MANIFEST: tuple[dict[str, object], ...] = (
    {
        "id": "oncall_overview",
        "file_name": "oncall-overview.json",
        "title": "On-call Overview",
        "uid": "ragweld-oncall-overview",
        "slug": "on-call-overview",
        "category": "oncall",
        "default": True,
        "description": "Landing dashboard for active incidents, SLO breaches, service health, alert state, and recent change context.",
        "workbench_paths": ["/grafana?subtab=overview", "/grafana?subtab=incidents", "/infrastructure?subtab=monitoring"],
    },
    {
        "id": "gateway_serving",
        "file_name": "gateway-serving.json",
        "title": "Gateway & Serving",
        "uid": "ragweld-gateway-serving",
        "slug": "gateway-serving",
        "category": "runtime",
        "default": False,
        "description": "LiteLLM routing, vLLM serving, request latency, errors, and gateway/provider health.",
        "workbench_paths": ["/grafana?subtab=dashboards", "/benchmark"],
    },
    {
        "id": "retrieval_indexing_graph",
        "file_name": "retrieval-indexing-graph.json",
        "title": "Retrieval/Indexing/Graph",
        "uid": "ragweld-retrieval-indexing-graph",
        "slug": "retrieval-indexing-graph",
        "category": "retrieval",
        "default": False,
        "description": "Haystack, Docling, Qdrant, indexing export, and graph-parity operator signals.",
        "workbench_paths": ["/rag?subtab=indexing", "/rag?subtab=retrieval", "/rag?subtab=graph"],
    },
    {
        "id": "training_workflow",
        "file_name": "training-workflow.json",
        "title": "Training & Workflow",
        "uid": "ragweld-training-workflow",
        "slug": "training-workflow",
        "category": "training",
        "default": False,
        "description": "Flyte, MLflow, Unsloth, and training workflow state for the Learning Agent lane.",
        "workbench_paths": ["/rag?subtab=learning-agent", "/grafana?subtab=overview"],
    },
    {
        "id": "eval_benchmark_prompt_regressions",
        "file_name": "eval-benchmark-prompt-regressions.json",
        "title": "Eval/Benchmark/Prompt Regressions",
        "uid": "ragweld-eval-benchmark-prompt-regressions",
        "slug": "eval-benchmark-prompt-regressions",
        "category": "quality",
        "default": False,
        "description": "ML-quality dashboard for eval deltas, benchmark shifts, prompt-set changes, and regression triage.",
        "workbench_paths": ["/eval?subtab=analysis", "/benchmark", "/eval?subtab=prompts"],
    },
    {
        "id": "cost_capacity",
        "file_name": "cost-capacity.json",
        "title": "Cost & Capacity",
        "uid": "ragweld-cost-capacity",
        "slug": "cost-capacity",
        "category": "cost",
        "default": False,
        "description": "OpenCost-style cost and saturation surface for gateway spend, infra usage, and capacity pressure.",
        "workbench_paths": ["/grafana?subtab=dashboards", "/infrastructure?subtab=services"],
    },
    {
        "id": "frontend_rum",
        "file_name": "frontend-rum.json",
        "title": "Frontend/RUM",
        "uid": "ragweld-frontend-rum",
        "slug": "frontend-rum",
        "category": "frontend",
        "default": False,
        "description": "Frontend telemetry, Faro/RUM, and browser-to-backend operator visibility.",
        "workbench_paths": ["/grafana?subtab=dashboards", "/chat?subtab=ui"],
    },
)


def _load_dashboard_json(file_name: str) -> dict[str, object] | None:
    path = _DASHBOARD_ROOT / file_name
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _links_for_dashboard(config: TriBridConfig, *, uid: str, slug: str, title: str) -> list[TraceExternalLink]:
    link = grafana_dashboard_url(config, uid=uid, slug=slug)
    if not link:
        return []
    return [
        TraceExternalLink(
            label=title,
            kind="grafana",
            url=link,
            detail="Provisioned Grafana dashboard.",
        )
    ]


def build_observability_catalog(config: TriBridConfig) -> ObservabilityCatalogResponse:
    workbench_links = build_workbench_links()
    workbench_by_path = {item.path: item for item in workbench_links}

    dashboards: list[ObservabilityDashboardFamily] = []
    for item in _DASHBOARD_MANIFEST:
        raw = _load_dashboard_json(str(item["file_name"]))
        title = str((raw or {}).get("title") or item["title"])
        uid = str((raw or {}).get("uid") or item["uid"])
        slug = str(item["slug"])
        tags = [str(tag) for tag in ((raw or {}).get("tags") or []) if str(tag).strip()]
        dashboards.append(
            ObservabilityDashboardFamily(
                id=str(item["id"]),
                title=title,
                description=str(item["description"]),
                uid=uid,
                slug=slug,
                category=str(item["category"]),
                default=bool(item["default"]),
                tags=tags,
                variables=list(_DEFAULT_VARIABLES),
                links=_links_for_dashboard(config, uid=uid, slug=slug, title=title),
                workbench_links=[
                    workbench_by_path[path]
                    for path in item.get("workbench_paths", [])
                    if isinstance(path, str) and path in workbench_by_path
                ],
            )
        )

    external_links: list[TraceExternalLink] = []
    grafana_url = str(config.ui.grafana_base_url or "").strip()
    if grafana_url:
        external_links.append(
            TraceExternalLink(
                label="Grafana",
                kind="grafana",
                url=grafana_url,
                detail="Grafana command center base URL.",
            )
        )

    return ObservabilityCatalogResponse(
        ok=True,
        generated_at=datetime.now(UTC),
        dashboards=dashboards,
        workbench_links=workbench_links,
        external_links=external_links,
    )
