from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from typing import Any

import httpx

from server.gateway_catalog import LOCAL_GATEWAY_ALIAS, gateway_rows_snapshot
from server.chat.gateway_runtime import (
    resolve_litellm_api_key,
    resolve_litellm_base_url,
    resolve_vllm_base_url,
)
from server.models.tribrid_config_model import (
    ObservabilityComponentStatus,
    ObservabilityStatusResponse,
    TraceExternalLink,
    TriBridConfig,
)
from server.observability.probe_history import ProbeSample, probe_key, record_probe, sample_for
from server.observability.profiling import profiling_state
from server.observability.runtime import (
    langfuse_client_blockers,
    langfuse_ingestion_state,
    normalize_tracing_mode,
)


def _langfuse_ingestion_detail(config: TriBridConfig) -> str:
    blockers = langfuse_client_blockers(config.tracing)
    if blockers:
        return f"blocked ({'; '.join(blockers)})"
    return langfuse_ingestion_state()
from server.db.postgres import PostgresClient
from server.indexing.generations import (
    DeletionIncompleteError,
    PersistedStateCorruptError,
    qdrant_collection_of,
)
from server.retrieval.qdrant_store import QdrantChunkStore
from server.training.control_plane import build_agent_control_plane_status

_CRITICAL_GROUPS = {"metrics", "traces", "gateway", "serving", "workflow", "retrieval", "cost", "frontend"}


_READINESS_PATHS: dict[str, str] = {
    "tempo": "/ready",
    "alloy": "/-/ready",
    "mimir": "/ready",
    "pyroscope": "/ready",
    "opencost": "/healthz",
    "alertmanager": "/-/ready",
    "langfuse": "/api/public/health",
    "grafana": "/api/health",
}


def readiness_probe_url(component_id: str, base_url: str) -> str:
    """Functional readiness URL for a component base URL (base itself when unknown)."""
    target = str(base_url or "").strip().rstrip("/")
    if not target:
        return ""
    path = _READINESS_PATHS.get(component_id)
    if not path or target.endswith(path):
        return target
    return target + path


@dataclass(frozen=True)
class ProbeResult:
    """One readiness probe: what it found, and whether it could look at all.

    `probeable=False` is a third answer, distinct from "unreachable": an
    Authelia-protected ingress redirects the API off-host, so the probe proves
    nothing about the service. Counting that against the operator gives a
    permanent attention item no operator can ever clear.
    """

    reachable: bool | None = None
    detail: str | None = None
    probeable: bool = True


async def _check_url(url: str, *, component_id: str | None = None) -> ProbeResult:
    target = readiness_probe_url(component_id, url) if component_id else str(url or "").strip()
    if not target:
        return ProbeResult(reachable=None, detail=None, probeable=False)
    try:
        async with httpx.AsyncClient(timeout=2.0, follow_redirects=False) as client:
            next_target = target
            for _ in range(5):
                response = await client.get(next_target)
                status = response.status_code
                if status in {301, 302, 303, 307, 308}:
                    location = str(response.headers.get("location") or "").strip()
                    if not location:
                        return ProbeResult(reachable=False, detail=f"HTTP {status}")
                    redirect_target = str(response.url.join(location))
                    redirect_host = response.url.join(location).host
                    current_host = response.url.host
                    if redirect_host and current_host and redirect_host != current_host:
                        return ProbeResult(
                            reachable=None,
                            detail=(
                                f"redirected to {redirect_host}; protected ingress cannot be probed from the API, "
                                "verify the local listener"
                            ),
                            probeable=False,
                        )
                    next_target = redirect_target
                    continue
                if component_id in {"otlp_export", "faro"} and status in {405, 415}:
                    # OTLP/Faro intake endpoints are POST-only; a method rejection proves the listener.
                    return ProbeResult(reachable=True, detail=f"listener present (HTTP {status} to GET)")
                # Readiness is a 2xx on the readiness path; 4xx means the path or service is wrong.
                return ProbeResult(reachable=status < 300, detail=f"HTTP {status}")
    except Exception as exc:
        return ProbeResult(reachable=False, detail=str(exc))
    return ProbeResult(reachable=False, detail="HTTP redirect loop")


async def _check_model_api(url: str, *, api_key: str | None = None) -> tuple[bool, str]:
    """Probe an OpenAI-compatible model endpoint without leaking credentials."""

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url.rstrip('/')}/models", headers=headers)
        return response.status_code == 200, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, type(exc).__name__


def vllm_serving_mismatch(payload: Any, *, expected_model: str, expected_context: int | None) -> str | None:
    """Compare vLLM's `/v1/models` card with the configured model and catalog context.

    vLLM reports the loaded checkpoint as `root` and the context window as
    `max_model_len`; `chat.vllm.default_model` and the catalog `ragweld-local`
    row are expectations that readiness must verify, never assume.
    """

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return "vLLM reports no served model"
    served = rows[0]
    root = str(served.get("root") or "").strip()
    max_model_len = served.get("max_model_len")
    problems: list[str] = []
    expected = str(expected_model or "").strip()
    if expected and root != expected:
        problems.append(f"serving {root or '(unknown)'} but chat.vllm.default_model expects {expected}")
    if expected_context is not None and max_model_len != expected_context:
        problems.append(
            f"max_model_len is {max_model_len} but the catalog {LOCAL_GATEWAY_ALIAS} row expects {expected_context}"
        )
    return "; ".join(problems) or None


def _local_serving_context() -> int | None:
    try:
        row = gateway_rows_snapshot().get(LOCAL_GATEWAY_ALIAS)
    except Exception:
        return None
    return int(row.context) if row is not None and row.context is not None else None


async def _check_vllm_serving(url: str, *, expected_model: str, expected_context: int | None) -> tuple[bool, str]:
    """Probe vLLM and verify it serves the configured model at the catalog context."""

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{url.rstrip('/')}/models")
    except Exception as exc:
        return False, type(exc).__name__
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return False, "HTTP 200 with a non-JSON model list"
    mismatch = vllm_serving_mismatch(payload, expected_model=expected_model, expected_context=expected_context)
    if mismatch:
        return False, mismatch
    served = payload["data"][0]
    return True, f"HTTP 200; serving {served.get('root')} (max_model_len {served.get('max_model_len')})"


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


def _component_severity(
    *,
    group: str,
    enabled: bool,
    configured: bool,
    reachable: bool | None,
    probeable: bool,
    consecutive_failures: int,
    failure_threshold: int,
) -> str:
    if not enabled:
        return "info"
    if not configured:
        return "warning"
    if not probeable:
        # The probe could not look. That is not a fault to page on, and it must
        # not sit permanently on the operator-attention line.
        return "info"
    if reachable is True:
        return "healthy"
    if reachable is None:
        return "warning"
    if consecutive_failures < failure_threshold:
        # A missed probe is worth showing, never worth paging on.
        return "warning"
    return "critical" if group in _CRITICAL_GROUPS else "warning"


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
        return "Qdrant holds every corpus's dense and sparse vectors; an unreachable or empty collection fails the vector and sparse legs closed."
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
    failure_threshold: int,
    probeable: bool = True,
    url: str | None = None,
    links: list[TraceExternalLink] | None = None,
) -> ObservabilityComponentStatus:
    group = _component_group(component_id)
    sample: ProbeSample = sample_for(reachable, probeable=probeable)
    history, consecutive_failures = record_probe(probe_key(component_id, url), sample)
    severity = _component_severity(
        group=group,
        enabled=enabled,
        configured=configured,
        reachable=reachable,
        probeable=probeable,
        consecutive_failures=consecutive_failures,
        failure_threshold=failure_threshold,
    )
    if reachable is False and 0 < consecutive_failures < failure_threshold:
        # Say which sample this is, so the card's status word and its body text
        # rest on the same evidence.
        streak = f"failed probe {consecutive_failures} of {failure_threshold}"
        detail = f"{detail} ({streak})" if detail else streak.capitalize()
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
        probeable=probeable,
        consecutive_failures=consecutive_failures,
        probe_history=history,
    )


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
    down = [
        item.label
        for item in components
        if item.severity in {"warning", "critical"} and item.enabled and item.probeable
    ]
    if down:
        return f"Operator attention needed across: {', '.join(down)}."
    return "Observability is configured. Start with Grafana Overview, then drill into incidents, dashboards, and ML-quality surfaces."


async def build_observability_status(config: TriBridConfig, *, repo_id: str | None = None) -> ObservabilityStatusResponse:
    mode = normalize_tracing_mode(config.tracing.tracing_mode)
    failure_threshold = int(config.tracing.probe_failure_threshold)
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
    langfuse_public_url = str(config.tracing.langfuse_public_base_url or "").strip()
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

    otlp_probe = await _check_url(otlp_url, component_id="otlp_export")
    grafana_probe = await _check_url(grafana_url, component_id="grafana")
    tempo_probe = await _check_url(tempo_url, component_id="tempo")
    alloy_probe = await _check_url(alloy_url, component_id="alloy")
    mimir_probe = await _check_url(mimir_url, component_id="mimir")
    pyroscope_probe = await _check_url(pyroscope_url, component_id="pyroscope")
    faro_probe = await _check_url(faro_url, component_id="faro")
    opencost_probe = await _check_url(opencost_url, component_id="opencost")
    alertmanager_probe = await _check_url(alertmanager_url, component_id="alertmanager")
    langfuse_probe = await _check_url(langfuse_url, component_id="langfuse")
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
        vllm_reachable, vllm_detail = await _check_vllm_serving(
            vllm_url,
            expected_model=str(config.chat.vllm.default_model or "").strip(),
            expected_context=_local_serving_context(),
        )

    components = [
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="local_trace_buffer",
            label="Local trace buffer",
            enabled=config.tracing.tracing_enabled and mode != "off",
            configured=True,
            reachable=True,
            detail="In-process trace buffer feeding the workbench trace views.",
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="otlp_export",
            label="OTLP export",
            enabled=config.tracing.otel_export_enabled and mode in {"otel", "otel_langfuse"},
            configured=bool(otlp_url),
            reachable=otlp_probe.reachable,
            probeable=otlp_probe.probeable,
            detail=otlp_probe.detail or "Configure an OTLP HTTP endpoint so traces can leave the API process.",
            url=otlp_url or None,
            links=_make_links("OTLP export", otlp_url, "Collector HTTP endpoint."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="alloy",
            label="Grafana Alloy",
            enabled=bool(alloy_url),
            configured=bool(alloy_url),
            reachable=alloy_probe.reachable,
            probeable=alloy_probe.probeable,
            detail=alloy_probe.detail,
            url=alloy_url or None,
            links=_make_links("Grafana Alloy", alloy_url, "Collector or agent endpoint for OTLP ingest."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="tempo",
            label="Tempo",
            enabled=bool(tempo_url),
            configured=bool(tempo_url),
            reachable=tempo_probe.reachable,
            probeable=tempo_probe.probeable,
            detail=tempo_probe.detail,
            url=tempo_url or None,
            links=_make_links("Tempo", tempo_url, "Tempo or Grafana Explore base URL.", kind="tempo"),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="mimir",
            label="Mimir",
            enabled=bool(mimir_url),
            configured=bool(mimir_url),
            reachable=mimir_probe.reachable,
            probeable=mimir_probe.probeable,
            detail=mimir_probe.detail or "Metrics backend for long-range retention and alert queries.",
            url=mimir_url or None,
            links=_make_links("Mimir", mimir_url, "Metrics backend base URL."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="pyroscope",
            label="Pyroscope",
            enabled=bool(pyroscope_url),
            # A failed host agent degrades the component (severity=warning)
            # even when the server itself answers /ready — a reachable server
            # receiving nothing is not healthy profiling.
            configured=bool(pyroscope_url) and not profiling_state().startswith("failed"),
            reachable=pyroscope_probe.reachable,
            probeable=pyroscope_probe.probeable,
            detail=(
                f"{pyroscope_probe.detail or 'Continuous profiling backend for hot-path investigation.'}"
                f"; host agent: {profiling_state()}"
            ),
            url=pyroscope_url or None,
            links=_make_links("Pyroscope", pyroscope_url, "Continuous profiling surface."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="faro",
            label="Faro",
            enabled=bool(faro_url),
            configured=bool(faro_url),
            reachable=faro_probe.reachable,
            probeable=faro_probe.probeable,
            detail=faro_probe.detail or "Frontend/RUM telemetry collector path.",
            url=faro_url or None,
            links=_make_links("Faro", faro_url, "Frontend/RUM collector endpoint."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="opencost",
            label="OpenCost",
            enabled=bool(opencost_url),
            configured=bool(opencost_url),
            reachable=opencost_probe.reachable,
            probeable=opencost_probe.probeable,
            detail=opencost_probe.detail or "Cost and capacity backend for infra spend visibility.",
            url=opencost_url or None,
            links=_make_links("OpenCost", opencost_url, "Cost allocation surface."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="alertmanager",
            label="Alertmanager",
            enabled=bool(alertmanager_url),
            configured=bool(alertmanager_url),
            reachable=alertmanager_probe.reachable,
            probeable=alertmanager_probe.probeable,
            detail=(
                f"{alertmanager_probe.detail or 'Alert aggregation and routing for Prometheus rules.'}"
                "; delivery receivers (webhook/email/pager) are operator-configured in infra/alertmanager.yml"
            ),
            url=alertmanager_url or None,
            links=_make_links("Alertmanager", alertmanager_url, "Alert routing surface."),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="langfuse",
            label="Langfuse",
            enabled=config.tracing.langfuse_enabled and mode == "otel_langfuse",
            # A reachable web UI is not enough: this process must also be able
            # to build an ingestion client (keys + SDK), or generations are
            # silently dropped while the health endpoint stays green.
            configured=bool(langfuse_url) and not langfuse_client_blockers(config.tracing),
            reachable=langfuse_probe.reachable,
            probeable=langfuse_probe.probeable,
            detail=(
                f"{langfuse_probe.detail or 'Generation trace drilldown substrate.'}"
                f"; ingestion: {_langfuse_ingestion_detail(config)}"
            ),
            url=langfuse_public_url or None,
            links=_make_links("Langfuse", langfuse_public_url, "Langfuse base URL.", kind="langfuse"),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="grafana",
            label="Grafana",
            enabled=config.ui.grafana_embed_enabled,
            configured=bool(grafana_url),
            reachable=grafana_probe.reachable,
            probeable=grafana_probe.probeable,
            detail=grafana_probe.detail,
            url=grafana_url or None,
            links=_make_links(
                "Grafana",
                grafana_url,
                (
                    "Grafana command center. Anonymous access is provisioned, so it opens read-only: "
                    "saving a panel, adding an annotation or silencing an alert needs a Grafana sign-in."
                ),
                kind="grafana",
            ),
        ),
        _decorate_component(
            failure_threshold=failure_threshold,
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
            failure_threshold=failure_threshold,
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
            failure_threshold=failure_threshold,
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

    qdrant_store = QdrantChunkStore(config)
    qdrant_url = qdrant_store.url
    qdrant_reachable = await qdrant_store.ping()
    qdrant_detail = (
        f"Qdrant reachable at {qdrant_url}."
        if qdrant_reachable
        else f"Qdrant unreachable at {qdrant_url}; vector and sparse retrieval legs cannot run."
    )
    corpus_reachable: bool | None = qdrant_reachable
    if repo_id and qdrant_reachable:
        manifest_failure: str | None = None
        try:
            pg = PostgresClient(config.indexing.postgres_url)
            await pg.connect()
            try:
                corpus_collection = qdrant_collection_of(await pg.get_generation(repo_id))
            finally:
                await pg.disconnect()
            corpus_status = await qdrant_store.status(repo_id, physical=corpus_collection)
        except (PersistedStateCorruptError, DeletionIncompleteError) as error:
            # Malformed or mid-deletion index state is an incident of its own,
            # never rendered as "not indexed".
            corpus_status = None
            manifest_failure = f"{type(error).__name__}: {error}"
            corpus_reachable = False
        except Exception as error:
            corpus_status = None
            manifest_failure = f"manifest lookup failed ({type(error).__name__}: {error})"
            corpus_reachable = False
        if manifest_failure is not None:
            qdrant_detail = f"{qdrant_detail} Corpus '{repo_id}': {manifest_failure}."
        elif corpus_status is None:
            qdrant_detail = f"{qdrant_detail} Corpus '{repo_id}' has no vector generation yet (not indexed)."
            corpus_reachable = None
        elif corpus_status.points <= 0:
            qdrant_detail = f"{qdrant_detail} Corpus '{repo_id}' has a generation manifest but its collection is empty or wiped."
            corpus_reachable = False
        else:
            qdrant_detail = (
                f"{qdrant_detail} Corpus '{repo_id}': {corpus_status.points} points, "
                f"{corpus_status.dense_points} dense ({corpus_status.dense_dimensions}-d), generation "
                f"{corpus_status.physical_collection}."
            )
    components.append(
        _decorate_component(
            failure_threshold=failure_threshold,
            component_id="haystack_docling_qdrant",
            label="Haystack + Docling + Qdrant",
            enabled=True,
            configured=bool(qdrant_url),
            reachable=corpus_reachable,
            detail=qdrant_detail,
            url=qdrant_url or None,
            links=_make_links("Qdrant", f"{qdrant_url}/dashboard" if qdrant_url else "", "Qdrant collections dashboard."),
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
    blockers = [
        item.id
        for item in components
        if item.severity in {"warning", "critical"} and item.enabled and item.probeable
    ]

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
