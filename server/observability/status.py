from __future__ import annotations

import os
from typing import Any

import httpx

from server.models.tribrid_config_model import (
    ObservabilityComponentStatus,
    ObservabilityStatusResponse,
    TraceExternalLink,
    TriBridConfig,
)
from server.observability.runtime import normalize_tracing_mode


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


def _build_operator_hint(cfg: TriBridConfig, mode: str, components: list[ObservabilityComponentStatus]) -> str:
    if mode == "off":
        return "Turn observability on by setting tracing mode to local, OTel, or OTel + Langfuse."
    if (
        mode in {"otel", "otel_langfuse"}
        and int(cfg.tracing.otel_export_enabled or 0) == 1
        and not str(cfg.tracing.otlp_endpoint or "").strip()
    ):
        return "Set an OTLP endpoint or switch tracing mode back to local until your collector path is ready."
    if mode == "otel_langfuse" and not str(cfg.tracing.langfuse_base_url or "").strip():
        return "Set a Langfuse base URL and env keys before enabling OTel + Langfuse mode."
    if mode == "otel_langfuse" and (
        not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY")
    ):
        return "Langfuse mode is selected, but LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are missing."
    down = [item.label for item in components if item.reachable is False and item.enabled]
    if down:
        return f"Configured observability targets are unreachable right now: {', '.join(down)}."
    return "Observability is configured. Next step: run a live request and inspect trace, cost, and external links in the workbench."


async def build_observability_status(config: TriBridConfig) -> ObservabilityStatusResponse:
    mode = normalize_tracing_mode(config.tracing.tracing_mode)

    grafana_url = str(config.ui.grafana_base_url or "").strip()
    tempo_url = str(config.tracing.tempo_base_url or "").strip()
    alloy_url = str(config.tracing.alloy_base_url or "").strip()
    langfuse_url = str(config.tracing.langfuse_base_url or "").strip()

    grafana_reachable, grafana_detail = await _check_url(grafana_url)
    tempo_reachable, tempo_detail = await _check_url(tempo_url)
    alloy_reachable, alloy_detail = await _check_url(alloy_url)
    langfuse_reachable, langfuse_detail = await _check_url(langfuse_url)

    components = [
        ObservabilityComponentStatus(
            id="local_trace_buffer",
            label="Local trace buffer",
            enabled=int(config.tracing.tracing_enabled or 0) == 1 and mode != "off",
            configured=True,
            reachable=True,
            detail="Fallback UI trace buffer used by the workbench.",
        ),
        ObservabilityComponentStatus(
            id="otlp_export",
            label="OTLP export",
            enabled=int(config.tracing.otel_export_enabled or 0) == 1 and mode in {"otel", "otel_langfuse"},
            configured=bool(str(config.tracing.otlp_endpoint or "").strip()),
            reachable=None,
            detail="Exporter readiness is based on endpoint configuration; collector reachability is checked separately.",
            url=str(config.tracing.otlp_endpoint or "").strip() or None,
        ),
        ObservabilityComponentStatus(
            id="alloy",
            label="Grafana Alloy",
            enabled=bool(alloy_url),
            configured=bool(alloy_url),
            reachable=alloy_reachable,
            detail=alloy_detail,
            url=alloy_url or None,
        ),
        ObservabilityComponentStatus(
            id="tempo",
            label="Tempo",
            enabled=bool(tempo_url),
            configured=bool(tempo_url),
            reachable=tempo_reachable,
            detail=tempo_detail,
            url=tempo_url or None,
        ),
        ObservabilityComponentStatus(
            id="langfuse",
            label="Langfuse",
            enabled=int(config.tracing.langfuse_enabled or 0) == 1 and mode == "otel_langfuse",
            configured=bool(langfuse_url),
            reachable=langfuse_reachable,
            detail=langfuse_detail,
            url=langfuse_url or None,
        ),
        ObservabilityComponentStatus(
            id="grafana",
            label="Grafana",
            enabled=int(config.ui.grafana_embed_enabled or 0) == 1,
            configured=bool(grafana_url),
            reachable=grafana_reachable,
            detail=grafana_detail,
            url=grafana_url or None,
        ),
    ]

    links: list[TraceExternalLink] = []
    if grafana_url:
        links.append(
            TraceExternalLink(
                label="Grafana dashboard",
                kind="grafana",
                url=grafana_url,
                detail="Configured Grafana base URL.",
            )
        )
    if tempo_url:
        links.append(
            TraceExternalLink(
                label="Tempo",
                kind="tempo",
                url=tempo_url,
                detail="Tempo or Grafana explore base URL for trace lookup.",
            )
        )
    if langfuse_url:
        links.append(
            TraceExternalLink(
                label="Langfuse",
                kind="langfuse",
                url=langfuse_url,
                detail="Langfuse base URL for generation traces.",
            )
        )

    blockers: list[str] = []
    if mode in {"otel", "otel_langfuse"} and int(config.tracing.otel_export_enabled or 0) == 1:
        if not str(config.tracing.otlp_endpoint or "").strip():
            blockers.append("otlp_endpoint_missing")
    if mode == "otel_langfuse":
        if int(config.tracing.langfuse_enabled or 0) != 1:
            blockers.append("langfuse_disabled")
        if not langfuse_url:
            blockers.append("langfuse_url_missing")
        if not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
            blockers.append("langfuse_keys_missing")
    blockers.extend(
        item.id
        for item in components
        if item.enabled and item.configured and item.reachable is False and item.id != "otlp_export"
    )

    return ObservabilityStatusResponse(
        ok=len(blockers) == 0,
        mode=mode if mode in {"local", "otel", "otel_langfuse", "off"} else "local",
        components=components,
        links=links,
        operator_hint=_build_operator_hint(config, mode, components),
    )
