"""Read what Alertmanager currently holds.

Alertmanager's `/api/v2/alerts` is the authority for what is firing. The API
reads it on demand rather than keeping a webhook log, so a restarted process
still reports the truth and a failure to read is reported as a failure, never
as "no alerts".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from server.models.observability import (
    AlertmanagerAlert,
    AlertmanagerAlertsResponse,
    AlertsUnavailableDetail,
)
from server.models.tribrid_config_model import TriBridConfig

# The in-app surface that owns the full alerting controls; every alert payload
# and every alert failure carries it so the panel can always offer a way out.
MONITORING_PATH = "/infrastructure?subtab=monitoring"

_ALERTS_TIMEOUT_SECONDS = 5.0


class AlertmanagerUnavailableError(Exception):
    """Alertmanager could not be read; carries the public detail and its status code."""

    def __init__(self, detail: AlertsUnavailableDetail, status_code: int) -> None:
        super().__init__(detail.message)
        self.detail = detail
        self.status_code = status_code


def _alert_from_payload(row: dict[str, object]) -> AlertmanagerAlert | None:
    """One Alertmanager alert as a wire model, or None when the row is unusable."""

    def _as_dict(value: object) -> dict[Any, Any]:
        return value if isinstance(value, dict) else {}

    labels = {str(key): str(value) for key, value in _as_dict(row.get("labels")).items()}
    name = labels.get("alertname", "").strip()
    starts_at = str(row.get("startsAt") or "").strip()
    if not name or not starts_at:
        return None
    annotations = {str(key): str(value) for key, value in _as_dict(row.get("annotations")).items()}
    status = _as_dict(row.get("status"))
    state = str(status.get("state") or "active").strip()
    ends_at = str(row.get("endsAt") or "").strip()
    try:
        return AlertmanagerAlert(
            fingerprint=str(row.get("fingerprint") or "").strip() or name,
            name=name,
            severity=labels.get("severity", "none"),
            state=state if state in {"active", "suppressed", "unprocessed"} else "active",  # type: ignore[arg-type]
            summary=annotations.get("summary") or None,
            description=annotations.get("description") or None,
            starts_at=starts_at,  # type: ignore[arg-type]
            ends_at=ends_at or None,  # type: ignore[arg-type]
            silenced=bool(status.get("silencedBy")),
            inhibited=bool(status.get("inhibitedBy")),
            labels=labels,
            generator_url=str(row.get("generatorURL") or "").strip() or None,
        )
    except ValueError:
        return None


async def build_alertmanager_alerts(config: TriBridConfig) -> AlertmanagerAlertsResponse:
    """Read Alertmanager, or raise `AlertmanagerUnavailableError` saying exactly why."""

    base_url = str(config.tracing.alertmanager_base_url or "").strip().rstrip("/")
    if not base_url:
        raise AlertmanagerUnavailableError(
            AlertsUnavailableDetail(
                source_url="",
                reason="not_configured",
                message="No Alertmanager is configured, so the API cannot report what is firing.",
                operator_hint=(
                    "Set tracing.alertmanager_base_url on Infrastructure - Monitoring "
                    "to the Alertmanager the Prometheus rules deliver to."
                ),
                monitoring_path=MONITORING_PATH,
            ),
            status_code=503,
        )

    try:
        async with httpx.AsyncClient(timeout=_ALERTS_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{base_url}/api/v2/alerts")
    except Exception as exc:
        raise AlertmanagerUnavailableError(
            AlertsUnavailableDetail(
                source_url=base_url,
                reason="unreachable",
                message=f"Alertmanager at {base_url} did not answer ({type(exc).__name__}: {exc}).",
                operator_hint=(
                    "Check that the Alertmanager container is up and that "
                    "tracing.alertmanager_base_url points at its listener."
                ),
                monitoring_path=MONITORING_PATH,
            ),
            status_code=503,
        ) from exc

    if response.status_code >= 300:
        raise AlertmanagerUnavailableError(
            AlertsUnavailableDetail(
                source_url=base_url,
                reason="bad_status",
                message=f"Alertmanager at {base_url} answered HTTP {response.status_code}.",
                operator_hint="Check the Alertmanager logs; its /api/v2/alerts route is not serving.",
                monitoring_path=MONITORING_PATH,
            ),
            status_code=502,
        )

    try:
        rows = response.json()
    except ValueError as exc:
        raise AlertmanagerUnavailableError(
            AlertsUnavailableDetail(
                source_url=base_url,
                reason="bad_status",
                message=f"Alertmanager at {base_url} answered HTTP 200 with a non-JSON body.",
                operator_hint="Verify tracing.alertmanager_base_url addresses Alertmanager and not another service.",
                monitoring_path=MONITORING_PATH,
            ),
            status_code=502,
        ) from exc

    alerts = [
        alert
        for alert in (_alert_from_payload(row) for row in rows if isinstance(row, dict))
        if alert is not None
    ]
    firing = sum(1 for alert in alerts if alert.state == "active" and not alert.silenced and not alert.inhibited)
    return AlertmanagerAlertsResponse(
        ok=True,
        generated_at=datetime.now(UTC),
        source_url=base_url,
        alerts=alerts,
        total_count=len(alerts),
        firing_count=firing,
        monitoring_path=MONITORING_PATH,
    )
