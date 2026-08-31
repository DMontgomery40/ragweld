"""Alerting rules read live from Prometheus for the Monitoring surface."""

from __future__ import annotations

from typing import Any, Literal

import httpx

from server.models.tribrid_config_model import (
    ObservabilityAlertRule,
    ObservabilityAlertRulesResponse,
    TriBridConfig,
)

_STATE_ORDER = {"firing": 0, "pending": 1, "inactive": 2, "unknown": 3}
_KNOWN_STATES: dict[str, Literal["firing", "pending", "inactive"]] = {
    "firing": "firing",
    "pending": "pending",
    "inactive": "inactive",
}


class MalformedRulesPayload(ValueError):  # noqa: N818 - public payload classification, not a generic error type
    """Prometheus answered, but not with a rules payload."""


def parse_rules_payload(payload: Any) -> list[ObservabilityAlertRule]:
    """Turn a Prometheus ``/api/v1/rules`` body into alert rules; reject anything that is not one."""
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise MalformedRulesPayload(f"unexpected rules payload: status={payload.get('status') if isinstance(payload, dict) else type(payload).__name__!r}")
    data = payload.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        raise MalformedRulesPayload("unexpected rules payload: data.groups is not a list")
    rules: list[ObservabilityAlertRule] = []
    for group in groups:
        if not isinstance(group, dict):
            raise MalformedRulesPayload("unexpected rules payload: group is not an object")
        for raw in group.get("rules") or []:
            if isinstance(raw, dict):
                rule = _rule_from_payload(str(group.get("name") or ""), raw)
                if rule is not None:
                    rules.append(rule)
    rules.sort(key=lambda r: (_STATE_ORDER.get(r.state, 3), r.group, r.name))
    return rules


def _rule_from_payload(group_name: str, raw: dict[str, Any]) -> ObservabilityAlertRule | None:
    if str(raw.get("type") or "alerting") != "alerting":
        return None
    raw_labels = raw.get("labels")
    labels: dict[str, Any] = raw_labels if isinstance(raw_labels, dict) else {}
    raw_annotations = raw.get("annotations")
    annotations: dict[str, Any] = raw_annotations if isinstance(raw_annotations, dict) else {}
    raw_alerts = raw.get("alerts")
    alerts: list[Any] = raw_alerts if isinstance(raw_alerts, list) else []
    severity = labels.get("severity")
    raw_state = str(raw.get("state") or "").strip().lower()
    return ObservabilityAlertRule(
        group=str(group_name),
        name=str(raw.get("name") or ""),
        state=_KNOWN_STATES.get(raw_state, "unknown"),
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
    try:
        rules = parse_rules_payload(payload)
    except MalformedRulesPayload as exc:
        return ObservabilityAlertRulesResponse(
            ok=False,
            source_url=base,
            reachable=True,
            error=f"{base}/api/v1/rules answered, but not with a Prometheus rules payload: {exc}",
        )
    return ObservabilityAlertRulesResponse(
        ok=True,
        source_url=base,
        reachable=True,
        error=None,
        rules=rules,
        firing_count=sum(1 for r in rules if r.state == "firing"),
        pending_count=sum(1 for r in rules if r.state == "pending"),
    )
