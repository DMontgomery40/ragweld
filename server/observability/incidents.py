from __future__ import annotations

from datetime import UTC, datetime

from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import (
    ObservabilityIncident,
    ObservabilityIncidentChange,
    ObservabilityIncidentsResponse,
    ObservabilityWorkbenchLink,
    TraceExternalLink,
    TriBridConfig,
)
from server.observability.catalog import build_observability_catalog
from server.observability.ml_quality import (
    build_benchmark_observability_summary,
    build_eval_observability_summary,
    build_prompt_observability_summary,
)
from server.observability.status import build_observability_status
from server.indexing.generations import (
    DeletionIncompleteError,
    PersistedStateCorruptError,
    qdrant_collection_of,
)
from server.retrieval.qdrant_store import QdrantChunkStore

_GROUP_DASHBOARDS: dict[str, list[str]] = {
    "metrics": ["oncall_overview"],
    "logs": ["oncall_overview"],
    "traces": ["oncall_overview"],
    "observability": ["oncall_overview"],
    "gateway": ["gateway_serving", "oncall_overview"],
    "serving": ["gateway_serving", "oncall_overview"],
    "workflow": ["training_workflow", "oncall_overview"],
    "training": ["training_workflow", "oncall_overview"],
    "retrieval": ["retrieval_indexing_graph", "oncall_overview"],
    "cost": ["cost_capacity", "oncall_overview"],
    "frontend": ["frontend_rum", "oncall_overview"],
}

_GROUP_WORKBENCH_PATHS: dict[str, list[str]] = {
    "metrics": ["/grafana?subtab=overview", "/grafana?subtab=dashboards"],
    "logs": ["/grafana?subtab=overview", "/infrastructure?subtab=monitoring"],
    "traces": ["/grafana?subtab=overview", "/eval?subtab=trace"],
    "observability": ["/grafana?subtab=overview", "/grafana?subtab=config"],
    "gateway": ["/grafana?subtab=dashboards", "/benchmark"],
    "serving": ["/grafana?subtab=dashboards", "/benchmark"],
    "workflow": ["/rag?subtab=learning-agent", "/grafana?subtab=overview"],
    "training": ["/rag?subtab=learning-agent", "/grafana?subtab=overview"],
    "retrieval": ["/rag?subtab=retrieval", "/rag?subtab=indexing"],
    "cost": ["/grafana?subtab=dashboards", "/infrastructure?subtab=services"],
    "frontend": ["/grafana?subtab=dashboards", "/chat?subtab=ui"],
}


def _component_workbench_links(
    workbench_by_path: dict[str, ObservabilityWorkbenchLink],
    group: str,
) -> list[ObservabilityWorkbenchLink]:
    return [workbench_by_path[path] for path in _GROUP_WORKBENCH_PATHS.get(group, []) if path in workbench_by_path]


def _link_from_component(label: str, url: str | None, detail: str | None = None) -> list[TraceExternalLink]:
    target = str(url or "").strip()
    if not target:
        return []
    return [TraceExternalLink(label=label, kind="custom", url=target, detail=detail)]


async def build_observability_incidents(
    config: TriBridConfig,
    *,
    repo_id: str | None = None,
) -> ObservabilityIncidentsResponse:
    status = await build_observability_status(config, repo_id=repo_id)
    catalog = build_observability_catalog(config)
    workbench_by_path = {item.path: item for item in catalog.workbench_links}

    incidents: list[ObservabilityIncident] = []

    for component in status.components:
        needs_attention = (
            (component.enabled and not component.configured)
            or (component.enabled and component.configured and component.reachable is False)
        )
        if not needs_attention:
            continue
        component_links = list(component.links or [])
        if not component_links and component.url:
            component_links = _link_from_component(component.label, component.url, component.detail)
        incidents.append(
            ObservabilityIncident(
                id=f"component:{component.id}",
                title=f"{component.label} needs attention",
                summary=component.detail
                or (
                    f"{component.label} is enabled but not configured."
                    if not component.configured
                    else f"{component.label} is configured but unreachable."
                ),
                source="infrastructure",
                severity=component.severity if component.severity != "healthy" else "warning",
                status="firing",
                started_at=datetime.now(UTC),
                owner="platform-oncall",
                component_ids=[component.id],
                dashboard_ids=_GROUP_DASHBOARDS.get(component.group, ["oncall_overview"]),
                links=component_links,
                workbench_links=_component_workbench_links(workbench_by_path, component.group),
                muted=False,
                slo_state=component.slo_state,
                operator_hint=component.operator_hint or status.operator_hint,
            )
        )

    if repo_id:
        # A corpus with chunk rows in Postgres but no live Qdrant generation
        # cannot serve the vector/sparse legs: that is an incident, not a warning.
        chunk_rows = 0
        state_failure: str | None = None
        try:
            pg = PostgresClient(config.indexing.postgres_url)
            await pg.connect()
            try:
                chunk_rows = await pg.count_chunks(repo_id)
                vector_collection = qdrant_collection_of(await pg.get_generation(repo_id))
            finally:
                await pg.disconnect()
        except (PersistedStateCorruptError, DeletionIncompleteError) as error:
            # Malformed or mid-deletion index state: an incident in its own right.
            state_failure = f"{type(error).__name__}: {error}"
            vector_collection = None
        except Exception as error:
            state_failure = f"control store unavailable ({type(error).__name__}: {error})"
            vector_collection = None
        vector_status = None
        vector_probe_failed = False
        if chunk_rows > 0:
            try:
                vector_status = await QdrantChunkStore(config).status(repo_id, physical=vector_collection)
            except Exception:
                vector_probe_failed = True
        if state_failure is not None:
            incidents.append(
                ObservabilityIncident(
                    id=f"retrieval:{repo_id}",
                    title="Retrieval index state unreadable",
                    summary=(
                        f"Corpus '{repo_id}': its persisted index state could not be resolved "
                        f"({state_failure}); retrieval fails closed until it is repaired or the store answers."
                    ),
                    source="retrieval",
                    severity="critical",
                    status="firing",
                    started_at=datetime.now(UTC),
                    owner="retrieval-oncall",
                    component_ids=["haystack_docling_qdrant"],
                    dashboard_ids=["retrieval_indexing_graph", "oncall_overview"],
                    workbench_links=_component_workbench_links(workbench_by_path, "retrieval"),
                    slo_state="breached",
                    operator_hint=(
                        "Malformed state: de-index the corpus (DELETE /api/index/{corpus_id}) and re-index. "
                        "Mid-deletion: retry the de-index. Store outage: restore Postgres and retry."
                    ),
                    change_correlation=[
                        ObservabilityIncidentChange(
                            kind="retrieval_lane",
                            label="Index state",
                            previous_value="readable",
                            current_value="unreadable",
                            detail=state_failure,
                        )
                    ],
                )
            )
        elif chunk_rows > 0 and (vector_probe_failed or vector_status is None or vector_status.points <= 0):
            current_value = (
                "qdrant_unreachable"
                if vector_probe_failed
                else "generation_missing"
                if vector_status is None
                else "generation_empty"
            )
            incidents.append(
                ObservabilityIncident(
                    id=f"retrieval:{repo_id}",
                    title="Retrieval vector lane degraded",
                    summary=(
                        f"Corpus '{repo_id}' has {chunk_rows} indexed chunk rows but no live Qdrant generation; "
                        "vector and sparse retrieval fail closed."
                    ),
                    source="retrieval",
                    severity="critical",
                    status="firing",
                    started_at=datetime.now(UTC),
                    owner="retrieval-oncall",
                    component_ids=["haystack_docling_qdrant"],
                    dashboard_ids=["retrieval_indexing_graph", "oncall_overview"],
                    workbench_links=_component_workbench_links(workbench_by_path, "retrieval"),
                    slo_state="breached",
                    operator_hint="Re-run indexing for the corpus (force_reindex) to rebuild and promote a Qdrant generation.",
                    change_correlation=[
                        ObservabilityIncidentChange(
                            kind="retrieval_lane",
                            label="Qdrant generation",
                            previous_value="promoted",
                            current_value=current_value,
                            detail=f"chunk_rows={chunk_rows}, points={int(vector_status.points) if vector_status else 0}",
                        )
                    ],
                )
            )

    eval_summary = build_eval_observability_summary(config, repo_id)
    if eval_summary.previous_run_id and (
        int(eval_summary.regressed_count or 0) > 0 or float(eval_summary.top1_accuracy.absolute_delta or 0.0) < 0.0
    ):
        incidents.append(
            ObservabilityIncident(
                id=f"eval:{repo_id or 'global'}",
                title="Eval regression detected",
                summary=(
                    f"Eval top-1 delta {float(eval_summary.top1_accuracy.absolute_delta or 0.0):+.3f}, "
                    f"regressed questions={int(eval_summary.regressed_count or 0)}."
                ),
                source="eval",
                severity="critical" if float(eval_summary.top1_accuracy.absolute_delta or 0.0) <= -0.05 else "warning",
                status="firing",
                started_at=eval_summary.latest_completed_at,
                owner="quality-oncall",
                component_ids=["ragas", "promptfoo"],
                dashboard_ids=["eval_benchmark_prompt_regressions", "oncall_overview"],
                workbench_links=[
                    item
                    for path in ("/eval?subtab=analysis", "/eval?subtab=prompts", "/benchmark")
                    if (item := workbench_by_path.get(path)) is not None
                ],
                slo_state="breached" if float(eval_summary.top1_accuracy.absolute_delta or 0.0) <= -0.05 else "at_risk",
                operator_hint=eval_summary.operator_hint,
                change_correlation=[
                    ObservabilityIncidentChange(
                        kind="prompt_set",
                        label="Prompt set",
                        previous_value=(
                            eval_summary.previous_prompt_set_ref.version_id
                            if eval_summary.previous_prompt_set_ref is not None
                            else None
                        ),
                        current_value=(
                            eval_summary.latest_prompt_set_ref.version_id
                            if eval_summary.latest_prompt_set_ref is not None
                            else None
                        ),
                        detail="Prompt lineage pinned to the compared eval runs.",
                    )
                ],
            )
        )

    benchmark_summary = build_benchmark_observability_summary(config, repo_id)
    if benchmark_summary.previous_run_id and (
        float(benchmark_summary.average_latency_ms.absolute_delta or 0.0) > 250.0
        or int(benchmark_summary.latest_error_count or 0) > int(benchmark_summary.previous_error_count or 0)
    ):
        incidents.append(
            ObservabilityIncident(
                id=f"benchmark:{repo_id or 'global'}",
                title="Benchmark regression detected",
                summary=(
                    f"Average latency delta {float(benchmark_summary.average_latency_ms.absolute_delta or 0.0):+.1f} ms, "
                    f"errors={int(benchmark_summary.latest_error_count or 0)}."
                ),
                source="benchmark",
                severity=(
                    "critical"
                    if int(benchmark_summary.latest_error_count or 0) > int(benchmark_summary.previous_error_count or 0)
                    else "warning"
                ),
                status="firing",
                started_at=benchmark_summary.latest_started_at,
                owner="runtime-oncall",
                component_ids=["litellm", "vllm"],
                dashboard_ids=["eval_benchmark_prompt_regressions", "gateway_serving", "oncall_overview"],
                workbench_links=[
                    item
                    for path in ("/benchmark", "/eval?subtab=analysis", "/eval?subtab=prompts")
                    if (item := workbench_by_path.get(path)) is not None
                ],
                slo_state="breached" if float(benchmark_summary.average_latency_ms.absolute_delta or 0.0) > 1000.0 else "at_risk",
                operator_hint=benchmark_summary.operator_hint,
                change_correlation=[
                    ObservabilityIncidentChange(
                        kind="prompt_set",
                        label="Prompt set",
                        previous_value=(
                            benchmark_summary.previous_prompt_set_ref.version_id
                            if benchmark_summary.previous_prompt_set_ref is not None
                            else None
                        ),
                        current_value=(
                            benchmark_summary.latest_prompt_set_ref.version_id
                            if benchmark_summary.latest_prompt_set_ref is not None
                            else None
                        ),
                        detail="Prompt lineage pinned to the compared benchmark runs.",
                    )
                ],
            )
        )

    prompt_summary = build_prompt_observability_summary(config, repo_id)
    if prompt_summary.pending_verification or prompt_summary.eval_regression_suspected or prompt_summary.benchmark_regression_suspected:
        incidents.append(
            ObservabilityIncident(
                id=f"prompt:{repo_id or 'global'}",
                title="Prompt-set verification required",
                summary=(
                    "Current prompt set is ahead of the latest evidence."
                    if prompt_summary.pending_verification and not prompt_summary.eval_regression_suspected and not prompt_summary.benchmark_regression_suspected
                    else "Prompt change is correlated with downstream regression signals."
                ),
                source="prompt_regression",
                severity="critical" if (prompt_summary.eval_regression_suspected or prompt_summary.benchmark_regression_suspected) else "warning",
                status="firing",
                started_at=datetime.now(UTC),
                owner="quality-oncall",
                component_ids=["promptfoo", "ragas"],
                dashboard_ids=["eval_benchmark_prompt_regressions", "oncall_overview"],
                workbench_links=[
                    item
                    for path in ("/eval?subtab=prompts", "/eval?subtab=analysis", "/benchmark")
                    if (item := workbench_by_path.get(path)) is not None
                ],
                slo_state="at_risk",
                operator_hint=prompt_summary.operator_hint,
                change_correlation=[
                    ObservabilityIncidentChange(
                        kind="prompt_set",
                        label="Current prompt set",
                        previous_value=(
                            prompt_summary.previous_prompt_set_ref.version_id
                            if prompt_summary.previous_prompt_set_ref is not None
                            else None
                        ),
                        current_value=(
                            prompt_summary.current_prompt_set_ref.version_id
                            if prompt_summary.current_prompt_set_ref is not None
                            else None
                        ),
                        detail="Prompt-set lineage currently selected in the bundle.",
                    )
                ],
            )
        )

    critical_count = sum(1 for incident in incidents if incident.severity == "critical")
    return ObservabilityIncidentsResponse(
        ok=True,
        generated_at=datetime.now(UTC),
        incidents=incidents,
        total_count=len(incidents),
        critical_count=critical_count,
    )
