"""Alerting rules read live from Prometheus for the Monitoring surface."""

from __future__ import annotations

from typing import Any

import httpx

from server.models.tribrid_config_model import (
    ObservabilityAlertRule,
    ObservabilityAlertRulesResponse,
    TriBridConfig,
)

_STATE_ORDER = {"firing": 0, "pending": 1, "inactive": 2}


def _rule_from_payload(group_name: str, raw: dict[str, Any]) -> ObservabilityAlertRule | None:
    if str(raw.get("type") or "alerting") != "alerting":
        return None
    labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    annotations = raw.get("annotations") if isinstance(raw.get("annotations"), dict) else {}
    alerts = raw.get("alerts") if isinstance(raw.get("alerts"), list) else []
    severity = labels.get("severity")
    return ObservabilityAlertRule(
        group=str(group_name),
        name=str(raw.get("name") or ""),
        state=str(raw.get("state") or "inactive"),
        severity=str(severity) if severity is not None else None,
        query=str(raw.get("query") or ""),
        duration_seconds=float(raw.get("duration") or 0.0),
        summary=str(annotations["summary"]) if annotations.get("summary") else None,
        description=str(annotations["description"]) if annotations.get("description") else None,
        health=str(raw.get("health") or "unknown"),
        active_alerts=len(alerts),
    )


async def build_alert_rules(config: TriBridConfig) -> ObservabilityAlertRulesResponse:
    """Read the alerting rules Prometheus is evaluating; fail closed when it is unconfigured or down."""
    base = str(config.tracing.prometheus_base_url or "").strip().rstrip("/")
    if not base:
        return ObservabilityAlertRulesResponse(
            ok=False,
            source_url=None,
            reachable=False,
            error="tracing.prometheus_base_url is not configured; set it to the Prometheus base URL to read alert rules.",
        )
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base}/api/v1/rules", params={"type": "alert"})
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return ObservabilityAlertRulesResponse(
            ok=False,
            source_url=base,
            reachable=False,
            error=f"Prometheus rules API unavailable at {base}: {exc}",
        )
    groups = (payload.get("data") or {}).get("groups") if isinstance(payload, dict) else None
    rules: list[ObservabilityAlertRule] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        for raw in group.get("rules") or []:
            if isinstance(raw, dict):
                rule = _rule_from_payload(str(group.get("name") or ""), raw)
                if rule is not None:
                    rules.append(rule)
    rules.sort(key=lambda r: (_STATE_ORDER.get(r.state, 3), r.group, r.name))
    return ObservabilityAlertRulesResponse(
        ok=True,
        source_url=base,
        reachable=True,
        error=None,
        rules=rules,
        firing_count=sum(1 for r in rules if r.state == "firing"),
        pending_count=sum(1 for r in rules if r.state == "pending"),
    )
