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


def _time_range_variable(raw: dict[str, object] | None) -> ObservabilityDashboardVariable:
    time_block = (raw or {}).get("time")
    start = str(time_block.get("from") or "") if isinstance(time_block, dict) else ""
    if start == "now/d":
        default_value = "today"
    elif start.startswith("now-"):
        default_value = start[len("now-") :]
    else:
        default_value = start or "1h"
    return ObservabilityDashboardVariable(
        id="time_range",
        label="Time Range",
        kind="time_range",
        default_value=default_value,
        description="Grafana time range for the dashboard view.",
    )


def _dashboard_variables(raw: dict[str, object] | None) -> list[ObservabilityDashboardVariable]:
    """The template variables the provisioned dashboard actually declares, plus its time range.

    Read from the dashboard JSON so the catalog can never advertise a filter the panels do
    not apply. A Grafana `query` variable has no kind of its own in the catalog contract; it
    is reported as `custom` (a choice list) whose choices Grafana loads from its definition.
    """

    templating = (raw or {}).get("templating")
    items = templating.get("list") if isinstance(templating, dict) else None
    variables: list[ObservabilityDashboardVariable] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        grafana_type = str(item.get("type") or "textbox")
        raw_current = item.get("current")
        current_value = raw_current.get("value") if isinstance(raw_current, dict) else None
        if isinstance(current_value, list):
            current_value = current_value[0] if current_value else ""
        default_value = "All" if current_value in ("$__all", None, "") and item.get("includeAll") else str(current_value or "")
        definition = str(item.get("definition") or item.get("query") or "").strip()
        values: list[str] = []
        if grafana_type == "custom":
            values = [part.strip() for part in str(item.get("query") or "").split(",") if part.strip()]
        variables.append(
            ObservabilityDashboardVariable(
                id=str(item["name"]),
                label=str(item.get("label") or item["name"]),
                kind="textbox" if grafana_type == "textbox" else "custom",
                default_value=default_value or "*",
                description=str(item.get("description") or "").strip()
                or (f"Choices from {definition}." if grafana_type == "query" and definition else None),
                values=values,
            )
        )
    variables.append(_time_range_variable(raw))
    return variables

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
        "id": "chat",
        "file_name": "chat.json",
        "title": "Chat",
        "uid": "ragweld-chat",
        "slug": "chat",
        "category": "runtime",
        "default": False,
        "description": "Chat requests by outcome and error ratio, time to first event and first text, duration, spend and cost per chat, tokens and reasoning share, feedback, and Recall gate decisions.",
        "workbench_paths": ["/grafana?subtab=dashboards", "/chat?subtab=ui"],
    },
    {
        "id": "gateway_serving",
        "file_name": "gateway-serving.json",
        "title": "Gateway & Serving",
        "uid": "ragweld-gateway-serving",
        "slug": "gateway-serving",
        "category": "runtime",
        "default": False,
        "description": "LiteLLM traffic, failures, time to first token, reasoning share, queue and overhead latency, deployment health, and the local-model lane when it runs.",
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
        "description": "Retrieval traffic and latency by leg, graph traversal and rerank, semantic cache outcomes, and index size per corpus.",
        "workbench_paths": ["/rag?subtab=indexing", "/rag?subtab=retrieval", "/rag?subtab=graph"],
    },
    {
        "id": "tribrid_overview",
        "file_name": "tribrid_overview.json",
        "title": "TriBrid Overview",
        "uid": "tribrid-overview",
        "slug": "tribrid-overview",
        "category": "retrieval",
        "default": False,
        "description": "Retrieval latency, rate and success, latency by leg with rerank, and index size per corpus.",
        "workbench_paths": ["/grafana?subtab=overview"],
    },
    {
        "id": "tribrid_rag_metrics",
        "file_name": "rag-metrics.json",
        "title": "TriBridRAG Metrics",
        "uid": "tribrid-rag-metrics",
        "slug": "tribridrag-metrics",
        "category": "retrieval",
        "default": False,
        "description": "Every search and indexing stage's latency and errors, index throughput, runs, and index size per corpus.",
        "workbench_paths": ["/grafana?subtab=dashboards"],
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
        "id": "reranker_training",
        "file_name": "reranker-training.json",
        "title": "Reranker Training",
        "uid": "reranker-training",
        "slug": "reranker-training",
        "category": "training",
        "default": False,
        "description": "Learning Reranker training runs, stage and step latency, triplets, evaluations, promotions, and inference latency.",
        "workbench_paths": ["/grafana?subtab=dashboards"],
    },
    {
        "id": "eval_benchmark_prompt_regressions",
        "file_name": "eval-benchmark-prompt-regressions.json",
        "title": "Eval/Benchmark/Prompt Regressions",
        "uid": "ragweld-eval-regressions",
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
        raw_tags = (raw or {}).get("tags")
        tags = [str(tag) for tag in (raw_tags if isinstance(raw_tags, list) else []) if str(tag).strip()]
        raw_workbench_paths = item.get("workbench_paths")
        workbench_paths = raw_workbench_paths if isinstance(raw_workbench_paths, list) else []
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
                variables=_dashboard_variables(raw),
                links=_links_for_dashboard(config, uid=uid, slug=slug, title=title),
                workbench_links=[
                    workbench_by_path[path]
                    for path in workbench_paths
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
