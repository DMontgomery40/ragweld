from __future__ import annotations

import os
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import Span

from server.models.runtime_gateway import ChatProviderInfo
from server.models.tribrid_config_model import (
    TraceCostSummary,
    TraceExternalLink,
    TraceRouteSummary,
    TracingConfig,
    TriBridConfig,
)

try:
    from langfuse import Langfuse
except Exception:  # pragma: no cover - optional dependency during rollout
    Langfuse = None  # type: ignore[assignment]


def normalize_tracing_mode(value: str | None) -> str:
    mode = str(value or "off").strip().lower()
    if mode in {"none", "off"}:
        return "off"
    if mode in {"langfuse", "otel+langfuse"}:
        return "otel_langfuse"
    if mode == "otel_langfuse":
        return mode
    if mode == "otel":
        return mode
    return "local"


def _parse_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in str(raw or "").split(","):
        chunk = item.strip()
        if not chunk or "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            headers[key] = value
    return headers


@dataclass
class ObservabilityManager:
    tracer_provider: TracerProvider
    tracer: Any
    langfuse_client: Any | None
    mode: str
    tracing_config: TracingConfig


@dataclass
class RequestObservation:
    manager: ObservabilityManager
    route_name: str
    path: str
    method: str
    correlation_id: str
    span: Span
    trace_id: str
    root_span_id: str
    run_id: str | None = None
    repo_id: str | None = None
    route_summary: TraceRouteSummary | None = None
    cost_summary: TraceCostSummary | None = None
    links: list[TraceExternalLink] = field(default_factory=list)


_ACTIVE_REQUEST: ContextVar[RequestObservation | None] = ContextVar("ragweld_active_request", default=None)
_MANAGERS: dict[str, ObservabilityManager] = {}
_MANAGERS_LOCK = threading.Lock()


def _manager_key(tracing_cfg: TracingConfig) -> str:
    return "|".join(
        [
            normalize_tracing_mode(tracing_cfg.tracing_mode),
            str(int(tracing_cfg.otel_export_enabled or 0)),
            str(tracing_cfg.otlp_endpoint or ""),
            str(tracing_cfg.otlp_headers or ""),
            str(tracing_cfg.otel_service_name or ""),
            str(int(tracing_cfg.langfuse_enabled or 0)),
            str(tracing_cfg.langfuse_base_url or ""),
            str(tracing_cfg.langfuse_project or ""),
        ]
    )


def _build_langfuse_client(tracing_cfg: TracingConfig, tracer_provider: TracerProvider) -> Any | None:
    if Langfuse is None:
        return None
    if int(tracing_cfg.langfuse_enabled or 0) != 1:
        return None
    public_key = str(os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = str(os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
    if not public_key or not secret_key or not str(tracing_cfg.langfuse_base_url or "").strip():
        return None
    try:
        return Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=str(tracing_cfg.langfuse_base_url).rstrip("/"),
            tracing_enabled=True,
            tracer_provider=tracer_provider,
        )
    except Exception:
        return None


def get_observability_manager(config: TriBridConfig) -> ObservabilityManager:
    tracing_cfg = config.tracing
    key = _manager_key(tracing_cfg)
    with _MANAGERS_LOCK:
        existing = _MANAGERS.get(key)
        if existing is not None:
            return existing

        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: str(tracing_cfg.otel_service_name or "ragweld-api"),
                "service.namespace": "ragweld",
            }
        )
        provider = TracerProvider(resource=resource)
        if int(tracing_cfg.otel_export_enabled or 0) == 1 and str(tracing_cfg.otlp_endpoint or "").strip():
            exporter = OTLPSpanExporter(
                endpoint=str(tracing_cfg.otlp_endpoint).strip(),
                headers=_parse_headers(str(tracing_cfg.otlp_headers or "")),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))

        tracer = provider.get_tracer("ragweld.observability")
        manager = ObservabilityManager(
            tracer_provider=provider,
            tracer=tracer,
            langfuse_client=_build_langfuse_client(tracing_cfg, provider),
            mode=normalize_tracing_mode(tracing_cfg.tracing_mode),
            tracing_config=tracing_cfg,
        )
        _MANAGERS[key] = manager
        return manager


def current_observation() -> RequestObservation | None:
    return _ACTIVE_REQUEST.get()


def current_header_values() -> dict[str, str]:
    obs = current_observation()
    if obs is None:
        return {}
    return {
        "X-Correlation-ID": obs.correlation_id,
        "X-Trace-ID": obs.trace_id,
        "X-Root-Span-ID": obs.root_span_id,
    }


def current_trace_ids() -> tuple[str | None, str | None, str | None]:
    obs = current_observation()
    if obs is None:
        return None, None, None
    return obs.trace_id, obs.root_span_id, obs.correlation_id


def apply_default_links(config: TriBridConfig) -> None:
    obs = current_observation()
    if obs is None:
        return
    if str(config.ui.grafana_base_url or "").strip():
        base = str(config.ui.grafana_base_url).rstrip("/")
        uid = str(config.ui.grafana_dashboard_uid or "").strip()
        slug = str(config.ui.grafana_dashboard_slug or uid).strip() or uid
        if uid:
            add_external_link(
                label="Grafana dashboard",
                kind="grafana",
                url=f"{base}/d/{uid}/{slug}",
                detail="Provisioned dashboard for request metrics and logs.",
            )
    if str(config.tracing.tempo_base_url or "").strip() and obs.trace_id:
        add_external_link(
            label="Tempo trace",
            kind="tempo",
            url=f"{str(config.tracing.tempo_base_url).rstrip('/')}/trace/{obs.trace_id}",
            detail="Trace lookup for the current canonical trace id.",
        )


@contextmanager
def start_request_observation(
    *,
    config: TriBridConfig,
    route_name: str,
    path: str,
    method: str,
    correlation_id: str | None = None,
    run_id: str | None = None,
    repo_id: str | None = None,
) -> Iterator[RequestObservation | None]:
    if int(getattr(config.tracing, "tracing_enabled", 1) or 0) != 1:
        yield None
        return
    if normalize_tracing_mode(config.tracing.tracing_mode) == "off":
        yield None
        return

    manager = get_observability_manager(config)
    request_correlation_id = str(correlation_id or uuid.uuid4())
    span_name = f"ragweld.{route_name}"
    with manager.tracer.start_as_current_span(span_name) as span:
        span.set_attribute("ragweld.route_name", route_name)
        span.set_attribute("http.route", path)
        span.set_attribute("http.request.method", method.upper())
        span.set_attribute("ragweld.correlation_id", request_correlation_id)
        if run_id:
            span.set_attribute("ragweld.run_id", run_id)
        if repo_id:
            span.set_attribute("ragweld.repo_id", repo_id)
        ctx = span.get_span_context()
        trace_id = f"{ctx.trace_id:032x}" if ctx.trace_id else ""
        root_span_id = f"{ctx.span_id:016x}" if ctx.span_id else ""
        observation = RequestObservation(
            manager=manager,
            route_name=route_name,
            path=path,
            method=method.upper(),
            correlation_id=request_correlation_id,
            span=span,
            trace_id=trace_id,
            root_span_id=root_span_id,
            run_id=run_id,
            repo_id=repo_id,
            route_summary=TraceRouteSummary(route_name=route_name, path=path, method=method.upper()),
        )
        token = _ACTIVE_REQUEST.set(observation)
        try:
            yield observation
        except Exception as exc:
            span.record_exception(exc)
            raise
        finally:
            if observation.route_summary is not None:
                if observation.route_summary.provider is not None:
                    span.set_attribute("ragweld.provider.kind", observation.route_summary.provider.kind)
                    span.set_attribute("ragweld.provider.name", observation.route_summary.provider.provider_name)
                    span.set_attribute("ragweld.provider.model", observation.route_summary.provider.model)
                if observation.route_summary.final_results is not None:
                    span.set_attribute("ragweld.final_results", int(observation.route_summary.final_results))
                if observation.route_summary.llm_used is not None:
                    span.set_attribute("ragweld.llm_used", bool(observation.route_summary.llm_used))
            if observation.cost_summary is not None:
                if observation.cost_summary.estimated_cost_usd is not None:
                    span.set_attribute("ragweld.cost.usd", float(observation.cost_summary.estimated_cost_usd))
                if observation.cost_summary.total_tokens is not None:
                    span.set_attribute("ragweld.cost.total_tokens", int(observation.cost_summary.total_tokens))
            try:
                _ACTIVE_REQUEST.reset(token)
            except ValueError:
                _ACTIVE_REQUEST.set(None)


@contextmanager
def stage_span(name: str, **attrs: Any) -> Iterator[Span | None]:
    obs = current_observation()
    if obs is None:
        yield None
        return
    with obs.manager.tracer.start_as_current_span(name) as span:
        for key, value in attrs.items():
            if value is None:
                continue
            span.set_attribute(str(key), value)
        yield span


def update_route_summary(**updates: Any) -> None:
    obs = current_observation()
    if obs is None:
        return
    current = obs.route_summary or TraceRouteSummary(route_name=obs.route_name, path=obs.path, method=obs.method)
    obs.route_summary = current.model_copy(update=updates)


def set_provider_route(provider: ChatProviderInfo | None) -> None:
    update_route_summary(provider=provider)


def set_cost_summary(summary: TraceCostSummary | None) -> None:
    obs = current_observation()
    if obs is None:
        return
    obs.cost_summary = summary


def add_external_link(*, label: str, kind: str, url: str, detail: str | None = None) -> None:
    obs = current_observation()
    if obs is None:
        return
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return
    if any(link.url == normalized_url for link in obs.links):
        return
    obs.links.append(
        TraceExternalLink(
            label=str(label or "").strip() or "Link",
            kind=kind if kind in {"grafana", "tempo", "langfuse", "custom"} else "custom",
            url=normalized_url,
            detail=detail,
        )
    )


def current_trace_payload_fields() -> dict[str, Any]:
    obs = current_observation()
    if obs is None:
        return {}
    return {
        "trace_id": obs.trace_id or None,
        "root_span_id": obs.root_span_id or None,
        "correlation_id": obs.correlation_id or None,
        "route_summary": obs.route_summary,
        "external_links": list(obs.links),
        "cost_summary": obs.cost_summary,
    }


def record_langfuse_generation(
    *,
    name: str,
    model: str,
    input_payload: Any,
    output_text: str,
    usage_details: dict[str, Any] | None,
    cost_details: dict[str, Any] | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    obs = current_observation()
    if obs is None or obs.manager.langfuse_client is None:
        return
    try:
        obs.manager.langfuse_client.update_current_generation(
            name=name,
            model=model,
            input=input_payload,
            output=output_text,
            usage_details=usage_details or {},
            cost_details=cost_details or {},
            metadata=metadata or {},
        )
        trace_id = obs.trace_id or None
        current_trace_id_fn = getattr(obs.manager.langfuse_client, "get_current_trace_id", None)
        if callable(current_trace_id_fn):
            current_trace_id = current_trace_id_fn()
            if isinstance(current_trace_id, str) and current_trace_id.strip():
                trace_id = current_trace_id.strip()
        trace_url_fn = getattr(obs.manager.langfuse_client, "get_trace_url", None)
        if callable(trace_url_fn):
            trace_url = trace_url_fn(trace_id=trace_id)
            if isinstance(trace_url, str) and trace_url.strip():
                add_external_link(
                    label="Langfuse trace",
                    kind="langfuse",
                    url=trace_url.strip(),
                    detail="LLM-native generation trace for this request.",
                )
    except Exception:
        return
