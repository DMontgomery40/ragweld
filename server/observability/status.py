from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

from server.chat.gateway_runtime import (
    resolve_litellm_api_key,
    resolve_litellm_base_url,
    resolve_vllm_base_url,
)
from server.db.postgres import PostgresClient
from server.indexing.oss_retrieval_pilot import build_retrieval_pilot_status
from server.models.tribrid_config_model import (
    ObservabilityComponentStatus,
    ObservabilityStatusResponse,
    TraceExternalLink,
    TriBridConfig,
)
from server.observability.runtime import normalize_tracing_mode
from server.training.control_plane import build_agent_control_plane_status

_CRITICAL_GROUPS = {"metrics", "traces", "gateway", "serving", "workflow", "retrieval", "cost", "frontend"}


async def _check_url(url: str) -> tuple[bool | None, str | None]:
    target = str(url or "").strip()
    if not target:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=2.0, follow_redirects=True) as client:
            response = await client.get(target)
        return response.status_code < 500, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


async def _check_model_api(url: str, *, api_key: str | None = None) -> tuple[bool, str]:
    """Probe an OpenAI-compatible model endpoint without leaking credentials."""

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url.rstrip('/')}/models", headers=headers)
        return response.status_code == 200, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, type(exc).__name__


def _append_link(links: list[TraceExternalLink], link: TraceExternalLink) -> None:
    if not str(link.url or "").strip():
        return
    for existing in links:
        if existing.url == link.url and existing.label == link.label:
            return
    links.append(link)


def _make_links(label: str, url: str | None, detail: str | None = None, *, kind: str = "custom") -> list[TraceExternalLink]:
    target = str(url or "").strip()
    if not target:
        return []
    return [TraceExternalLink(label=label, kind=kind, url=target, detail=detail)]


def _component_reachability_from_control_plane(*, enabled: bool, configured: bool, state: str) -> bool | None:
    normalized = str(state or "").strip().lower()
    if normalized == "ready":
        return True
    if enabled and configured and normalized == "degraded":
        return False
    return None


def _component_group(component_id: str) -> str:
    if component_id in {"grafana", "alloy", "mimir"}:
        return "metrics"
    if component_id in {"tempo", "langfuse", "local_trace_buffer", "otlp_export"}:
        return "traces"
    if component_id in {"alertmanager", "pyroscope"}:
        return "observability"
    if component_id in {"litellm"}:
        return "gateway"
    if component_id in {"vllm"}:
        return "serving"
    if component_id in {"flyte"}:
        return "workflow"
    if component_id in {"mlflow", "unsloth"}:
        return "training"
    if component_id in {"haystack_docling_qdrant"}:
        return "retrieval"
    if component_id in {"opencost"}:
        return "cost"
    if component_id in {"faro"}:
        return "frontend"
    return "observability"


def _component_severity(*, group: str, enabled: bool, configured: bool, reachable: bool | None) -> str:
    if enabled and configured and reachable is True:
        return "healthy"
    if enabled and configured and reachable is False:
        return "critical" if group in _CRITICAL_GROUPS else "warning"
    if enabled and not configured:
        return "warning"
    if enabled and configured and reachable is None:
        return "warning"
    return "info"


def _component_slo_state(severity: str) -> str:
    if severity == "healthy":
        return "healthy"
    if severity == "critical":
        return "breached"
    if severity == "warning":
        return "at_risk"
    return "unknown"


def _component_operator_hint(component_id: str, url: str | None, reachable: bool | None) -> str | None:
    if component_id == "otlp_export":
        return "Collector path is required before traces can leave the API process."
    if component_id == "langfuse":
        return "Langfuse should be reachable before operators rely on generation trace drilldown."
    if component_id == "litellm":
        return "Gateway failures block generation routing, policy enforcement, and spend visibility."
    if component_id == "vllm":
        return "Serving failures will page the generation lane even if the rest of the UI looks healthy."
    if component_id == "haystack_docling_qdrant":
        return "Retrieval pilot must be execution-ready before corpus-specific retrieval health is trustworthy."
    if reachable is False and url:
        return f"Check the target at {url} and verify network reachability plus service health."
    return None


def _decorate_component(
    *,
    component_id: str,
    label: str,
    enabled: bool,
    configured: bool,
    reachable: bool | None,
    detail: str | None,
    url: str | None = None,
    links: list[TraceExternalLink] | None = None,
) -> ObservabilityComponentStatus:
    group = _component_group(component_id)
    severity = _component_severity(group=group, enabled=enabled, configured=configured, reachable=reachable)
    return ObservabilityComponentStatus(
        id=component_id,
        label=label,
        group=group,
        enabled=enabled,
        configured=configured,
        reachable=reachable,
        detail=detail,
        url=url or None,
        severity=severity,  # type: ignore[arg-type]
        slo_state=_component_slo_state(severity),  # type: ignore[arg-type]
        operator_hint=_component_operator_hint(component_id, url, reachable),
        links=list(links or []),
    )


async def _resolve_repo_path(config: TriBridConfig, repo_id: str | None) -> str | None:
    if not repo_id:
        return None
    pg = PostgresClient(str(config.indexing.postgres_url or ""))
    try:
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
    except Exception:
        return None
    finally:
        try:
            await pg.disconnect()
        except Exception:
            pass
    if corpus is None:
        return None
    return str(corpus.get("path") or "").strip() or None


def _build_operator_hint(cfg: TriBridConfig, mode: str, components: list[ObservabilityComponentStatus]) -> str:
    if mode == "off":
        return "Turn observability on by setting tracing mode to local, OTel, or OTel + Langfuse."
    if (
        mode in {"otel", "otel_langfuse"}
        and cfg.tracing.otel_export_enabled
        and not str(cfg.tracing.otlp_endpoint or "").strip()
    ):
        return "Set an OTLP endpoint or switch tracing mode back to local until your collector path is ready."
    if mode == "otel_langfuse" and not str(cfg.tracing.langfuse_base_url or "").strip():
        return "Set a Langfuse base URL and env keys before enabling OTel + Langfuse mode."
    if mode == "otel_langfuse" and (not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY")):
        return "Langfuse mode is selected, but LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are missing."
    down = [item.label for item in components if item.severity in {"warning", "critical"} and item.enabled]
    if down:
        return f"Operator attention needed across: {', '.join(down)}."
    return "Observability is configured. Start with Grafana Overview, then drill into incidents, dashboards, and ML-quality surfaces."


async def build_observability_status(config: TriBridConfig, *, repo_id: str | None = None) -> ObservabilityStatusResponse:
    mode = normalize_tracing_mode(config.tracing.tracing_mode)
    control_plane = await build_agent_control_plane_status(config)

    grafana_url = str(config.ui.grafana_base_url or "").strip()
    otlp_url = str(config.tracing.otlp_endpoint or "").strip()
    tempo_url = str(config.tracing.tempo_base_url or "").strip()
    alloy_url = str(config.tracing.alloy_base_url or "").strip()
    mimir_url = str(config.tracing.mimir_base_url or "").strip()
    pyroscope_url = str(config.tracing.pyroscope_base_url or "").strip()
    faro_url = str(config.tracing.faro_base_url or "").strip()
    opencost_url = str(config.tracing.opencost_base_url or "").strip()
    alertmanager_url = str(config.tracing.alertmanager_base_url or "").strip()
    langfuse_url = str(config.tracing.langfuse_base_url or "").strip()
    litellm_enabled = bool(config.chat.litellm.enabled)
    vllm_enabled = bool(config.chat.vllm.enabled)
    litellm_key: str | None = None
    litellm_resolution_error: str | None = None
    vllm_resolution_error: str | None = None
    if litellm_enabled:
        try:
            litellm_url = resolve_litellm_base_url(configured_url=config.chat.litellm.base_url)
            litellm_key = resolve_litellm_api_key()
        except RuntimeError as exc:
            litellm_url = str(config.chat.litellm.base_url or "").strip()
            litellm_resolution_error = str(exc)
    else:
        litellm_url = str(config.chat.litellm.base_url or "").strip()
    if vllm_enabled:
        try:
            vllm_url = resolve_vllm_base_url(configured_url=config.chat.vllm.base_url)
        except RuntimeError as exc:
            vllm_url = str(config.chat.vllm.base_url or "").strip()
            vllm_resolution_error = str(exc)
    else:
        vllm_url = str(config.chat.vllm.base_url or "").strip()

    otlp_reachable, otlp_detail = await _check_url(otlp_url)
    grafana_reachable, grafana_detail = await _check_url(grafana_url)
    tempo_reachable, tempo_detail = await _check_url(tempo_url)
    alloy_reachable, alloy_detail = await _check_url(alloy_url)
    mimir_reachable, mimir_detail = await _check_url(mimir_url)
    pyroscope_reachable, pyroscope_detail = await _check_url(pyroscope_url)
    faro_reachable, faro_detail = await _check_url(faro_url)
    opencost_reachable, opencost_detail = await _check_url(opencost_url)
    alertmanager_reachable, alertmanager_detail = await _check_url(alertmanager_url)
    langfuse_reachable, langfuse_detail = await _check_url(langfuse_url)
    if not litellm_enabled:
        litellm_reachable, litellm_detail = None, None
    elif litellm_resolution_error:
        litellm_reachable, litellm_detail = False, litellm_resolution_error
    else:
        litellm_reachable, litellm_detail = await _check_model_api(litellm_url, api_key=litellm_key)
    if not vllm_enabled:
        vllm_reachable, vllm_detail = None, None
    elif vllm_resolution_error:
        vllm_reachable, vllm_detail = False, vllm_resolution_error
    else:
        vllm_reachable, vllm_detail = await _check_model_api(vllm_url)

    components = [
        _decorate_component(
            component_id="local_trace_buffer",
            label="Local trace buffer",
            enabled=config.tracing.tracing_enabled and mode != "off",
            configured=True,
            reachable=True,
            detail="Fallback UI trace buffer used by the workbench.",
        ),
        _decorate_component(
            component_id="otlp_export",
            label="OTLP export",
            enabled=config.tracing.otel_export_enabled and mode in {"otel", "otel_langfuse"},
            configured=bool(otlp_url),
            reachable=otlp_reachable,
            detail=otlp_detail or "Configure an OTLP HTTP endpoint so traces can leave the API process.",
            url=otlp_url or None,
            links=_make_links("OTLP export", otlp_url, "Collector HTTP endpoint."),
        ),
        _decorate_component(
            component_id="alloy",
            label="Grafana Alloy",
            enabled=bool(alloy_url),
            configured=bool(alloy_url),
            reachable=alloy_reachable,
            detail=alloy_detail,
            url=alloy_url or None,
            links=_make_links("Grafana Alloy", alloy_url, "Collector or agent endpoint for OTLP ingest."),
        ),
        _decorate_component(
            component_id="tempo",
            label="Tempo",
            enabled=bool(tempo_url),
            configured=bool(tempo_url),
            reachable=tempo_reachable,
            detail=tempo_detail,
            url=tempo_url or None,
            links=_make_links("Tempo", tempo_url, "Tempo or Grafana Explore base URL.", kind="tempo"),
        ),
        _decorate_component(
            component_id="mimir",
            label="Mimir",
            enabled=bool(mimir_url),
            configured=bool(mimir_url),
            reachable=mimir_reachable,
            detail=mimir_detail or "Metrics backend for long-range retention and alert queries.",
            url=mimir_url or None,
            links=_make_links("Mimir", mimir_url, "Metrics backend base URL."),
        ),
        _decorate_component(
            component_id="pyroscope",
            label="Pyroscope",
            enabled=bool(pyroscope_url),
            configured=bool(pyroscope_url),
            reachable=pyroscope_reachable,
            detail=pyroscope_detail or "Continuous profiling backend for hot-path investigation.",
            url=pyroscope_url or None,
            links=_make_links("Pyroscope", pyroscope_url, "Continuous profiling surface."),
        ),
        _decorate_component(
            component_id="faro",
            label="Faro",
            enabled=bool(faro_url),
            configured=bool(faro_url),
            reachable=faro_reachable,
            detail=faro_detail or "Frontend/RUM telemetry collector path.",
            url=faro_url or None,
            links=_make_links("Faro", faro_url, "Frontend/RUM collector endpoint."),
        ),
        _decorate_component(
            component_id="opencost",
            label="OpenCost",
            enabled=bool(opencost_url),
            configured=bool(opencost_url),
            reachable=opencost_reachable,
            detail=opencost_detail or "Cost and capacity backend for infra spend visibility.",
            url=opencost_url or None,
            links=_make_links("OpenCost", opencost_url, "Cost allocation surface."),
        ),
        _decorate_component(
            component_id="alertmanager",
            label="Alertmanager",
            enabled=bool(alertmanager_url),
            configured=bool(alertmanager_url),
            reachable=alertmanager_reachable,
            detail=alertmanager_detail or "Primary routing hub for wake-up paging and incident fanout.",
            url=alertmanager_url or None,
            links=_make_links("Alertmanager", alertmanager_url, "Wake-up routing path."),
        ),
        _decorate_component(
            component_id="langfuse",
            label="Langfuse",
            enabled=config.tracing.langfuse_enabled and mode == "otel_langfuse",
            configured=bool(langfuse_url),
            reachable=langfuse_reachable,
            detail=langfuse_detail or "Generation trace drilldown substrate.",
            url=langfuse_url or None,
            links=_make_links("Langfuse", langfuse_url, "Langfuse base URL.", kind="langfuse"),
        ),
        _decorate_component(
            component_id="grafana",
            label="Grafana",
            enabled=config.ui.grafana_embed_enabled,
            configured=bool(grafana_url),
            reachable=grafana_reachable,
            detail=grafana_detail,
            url=grafana_url or None,
            links=_make_links("Grafana", grafana_url, "Grafana command center base URL.", kind="grafana"),
        ),
        _decorate_component(
            component_id="litellm",
            label="LiteLLM",
            enabled=litellm_enabled,
            configured=bool(litellm_url) and litellm_key is not None,
            reachable=litellm_reachable if litellm_enabled and litellm_url and litellm_key is not None else None,
            detail=(
                litellm_detail
                if litellm_enabled
                else "Gateway routing and spend surface for model/provider traffic."
            ),
            url=litellm_url or None,
            links=_make_links("LiteLLM Gateway", litellm_url, "Gateway routing and provider policy surface."),
        ),
        _decorate_component(
            component_id="vllm",
            label="vLLM",
            enabled=vllm_enabled,
            configured=bool(vllm_url),
            reachable=vllm_reachable if vllm_enabled and vllm_url else None,
            detail=(
                vllm_detail
                if vllm_enabled and vllm_url
                else "Self-hosted serving endpoint for local generation traffic."
            ),
            url=vllm_url or None,
            links=_make_links("vLLM Endpoint", vllm_url, "Self-hosted generation serving endpoint."),
        ),
    ]
    components.extend(
        _decorate_component(
            component_id=component.kind,
            label=component.label,
            enabled=bool(component.enabled),
            configured=bool(component.configured),
            reachable=_component_reachability_from_control_plane(
                enabled=bool(component.enabled),
                configured=bool(component.configured),
                state=str(component.state or ""),
            ),
            detail=component.detail,
            url=(component.links[0].url if component.links else None),
            links=list(component.links or []),
        )
        for component in control_plane.components
    )

    if repo_id:
        repo_path = await _resolve_repo_path(config, repo_id)
        if repo_path:
            try:
                pilot = await build_retrieval_pilot_status(corpus_id=repo_id, repo_path=repo_path)
            except Exception:
                pilot = None
            if pilot is not None:
                pilot_links = []
                if pilot.search_preview_ready:
                    pilot_links.extend(_make_links("Retrieval Monitoring", "/infrastructure?subtab=monitoring", "Workbench monitoring surface."))
                components.append(
                    _decorate_component(
                        component_id="haystack_docling_qdrant",
                        label="Haystack + Docling + Qdrant",
                        enabled=True,
                        configured=bool(pilot.export_exists or pilot.documents_path),
                        reachable=True if pilot.execution_ready else None,
                        detail=(
                            "Retrieval pilot execution-ready for the active corpus."
                            if pilot.execution_ready
                            else "Retrieval pilot export exists but execution is not ready."
                            if pilot.export_exists
                            else "No retrieval pilot export exists for the active corpus."
                        ),
                        url=None,
                        links=pilot_links,
                    )
                )

    links: list[TraceExternalLink] = []
    for component in components:
        for link in component.links:
            _append_link(links, link)
    for link in control_plane.links:
        _append_link(links, link)

    severity_rank = {"healthy": 0, "info": 1, "warning": 2, "critical": 3}
    highest = max((severity_rank.get(item.severity, 1) for item in components), default=1)
    overall_severity = next(label for label, score in severity_rank.items() if score == highest)
    blockers = [item.id for item in components if item.severity in {"warning", "critical"} and item.enabled]

    return ObservabilityStatusResponse(
        ok=len(blockers) == 0,
        generated_at=datetime.now(UTC),
        mode=mode if mode in {"local", "otel", "otel_langfuse", "off"} else "local",
        severity=overall_severity,  # type: ignore[arg-type]
        slo_state=_component_slo_state(overall_severity),  # type: ignore[arg-type]
        components=components,
        links=links,
        operator_hint=_build_operator_hint(config, mode, components),
    )
