"""Observability-domain boundary models (owned here; registered for TypeScript generation through the aggregate)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AlertState = Literal["active", "suppressed", "unprocessed"]


class AlertmanagerAlert(BaseModel):
    """One alert as Alertmanager currently holds it (`GET /api/v2/alerts`).

    Alertmanager is the authority for what is firing right now; nothing here is
    derived from a webhook log or from in-process state, so a restarted API
    still reports the truth.
    """

    fingerprint: str = Field(description="Alertmanager's stable identity for this label set")
    name: str = Field(description="Value of the `alertname` label")
    severity: str = Field(description="Value of the `severity` label, or 'none' when the rule sets none")
    state: AlertState = Field(description="Alertmanager's own state for the alert")
    summary: str | None = Field(default=None, description="`summary` annotation from the alerting rule")
    description: str | None = Field(default=None, description="`description` annotation from the alerting rule")
    starts_at: datetime = Field(description="When the alert started firing")
    ends_at: datetime | None = Field(default=None, description="When the alert is due to resolve if it stops firing")
    silenced: bool = Field(description="Whether a silence currently suppresses this alert")
    inhibited: bool = Field(description="Whether an inhibition rule currently suppresses this alert")
    labels: dict[str, str] = Field(default_factory=dict, description="Full Alertmanager label set")
    generator_url: str | None = Field(default=None, description="Prometheus URL that generated the alert")


class AlertmanagerAlertsResponse(BaseModel):
    """Response payload for /api/observability/alerts."""

    ok: bool = Field(description="True when Alertmanager answered")
    generated_at: datetime = Field(description="When the API read Alertmanager")
    source_url: str = Field(description="Alertmanager base URL that was read")
    alerts: list[AlertmanagerAlert] = Field(default_factory=list, description="Alerts Alertmanager currently holds")
    total_count: int = Field(ge=0, description="Number of alerts returned")
    firing_count: int = Field(ge=0, description="Alerts that are active and neither silenced nor inhibited")
    monitoring_path: str = Field(description="In-app route to the full monitoring surface")


class AlertsUnavailableDetail(BaseModel):
    """Public error detail returned (HTTP 502/503) when Alertmanager cannot be read."""

    code: Literal["alertmanager_unavailable"] = "alertmanager_unavailable"
    source_url: str = Field(description="Alertmanager base URL that was attempted (empty when unconfigured)")
    reason: Literal["not_configured", "unreachable", "bad_status"] = Field(
        description="Which of the three failure shapes occurred"
    )
    message: str = Field(description="Stable, non-sensitive failure summary")
    operator_hint: str = Field(description="What the operator can do next")
    monitoring_path: str = Field(description="In-app route to the full monitoring surface")


class AlertsUnavailableResponse(BaseModel):
    """Envelope FastAPI puts an `AlertsUnavailableDetail` in."""

    detail: AlertsUnavailableDetail


class LangfuseTraceAccess(BaseModel):
    """Whether a Langfuse deep link is worth offering for one trace id.

    `exists` is decided by the ingestion API using this process's server keys.
    Whether the *operator's browser session* may open the link is a separate,
    unknowable-from-here question: Langfuse enforces project membership on the
    signed-in identity, which is why `sign_in_hint` is always carried.
    """

    trace_id: str = Field(description="Canonical trace id that was checked")
    exists: bool = Field(description="Whether Langfuse holds at least one observation for the trace")
    checked: bool = Field(description="Whether the check ran (false when Langfuse is off or unconfigured)")
    url: str | None = Field(default=None, description="Deep link to render, present only when `exists` is true")
    project: str = Field(description="Langfuse project the deep link targets")
    detail: str = Field(description="Why the answer is what it is, in operator terms")
    sign_in_hint: str = Field(description="Tooltip text naming the Langfuse identity requirement")
