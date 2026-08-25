"""Alert rules come from Prometheus, live; unconfigured/unreachable states fail closed.

The Monitoring surface used to post thresholds to a route that did not exist
(2026-08-25 drive finding M10). No mocks: the builder is exercised against an
empty config, a dead port, and -- when the Compose Prometheus answers -- the
real rules API.
"""

from __future__ import annotations

import os

import httpx
import pytest
from httpx import AsyncClient

from server.models.tribrid_config_model import TriBridConfig
from server.observability.alert_rules import MalformedRulesPayload, build_alert_rules, parse_rules_payload

_LIVE_PROMETHEUS = os.environ.get("PROMETHEUS_BASE_URL", "http://127.0.0.1:59090")


@pytest.mark.asyncio
async def test_alert_rules_unconfigured_reports_the_missing_setting() -> None:
    cfg = TriBridConfig()
    cfg.tracing.prometheus_base_url = ""
    out = await build_alert_rules(cfg)
    assert out.ok is False and out.reachable is False
    assert out.rules == [] and out.source_url is None
    assert "tracing.prometheus_base_url" in str(out.error)


@pytest.mark.asyncio
async def test_alert_rules_unreachable_prometheus_fails_closed() -> None:
    cfg = TriBridConfig()
    cfg.tracing.prometheus_base_url = "http://127.0.0.1:9/"
    out = await build_alert_rules(cfg)
    assert out.ok is False and out.reachable is False
    assert out.source_url == "http://127.0.0.1:9"
    assert out.rules == []
    assert "http://127.0.0.1:9" in str(out.error)


def test_rules_parser_rejects_non_rules_payloads_and_normalizes_states() -> None:
    for bad in ({"status": "error", "errorType": "bad_data"}, {"status": "success", "data": {}}, {"status": "success", "data": {"groups": "nope"}}, [], "html"):
        with pytest.raises(MalformedRulesPayload):
            parse_rules_payload(bad)
    rules = parse_rules_payload(
        {
            "status": "success",
            "data": {
                "groups": [
                    {
                        "name": "g",
                        "rules": [
                            {"type": "alerting", "name": "Odd", "state": "weird", "query": "up", "health": "err", "alerts": []},
                            {"type": "recording", "name": "rec", "query": "1"},
                            {"type": "alerting", "name": "Hot", "state": "FIRING", "query": "up == 0", "labels": {"severity": "critical"}, "alerts": [{}]},
                        ],
                    }
                ]
            },
        }
    )
    assert [(r.name, r.state, r.health, r.active_alerts) for r in rules] == [("Hot", "firing", "unknown", 1), ("Odd", "unknown", "err", 0)]
    assert rules[0].severity == "critical"


async def _prometheus_answers(base: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as probe:
            response = await probe.get(f"{base.rstrip('/')}/api/v1/rules")
        return response.status_code == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_alert_rules_read_live_from_prometheus(client: AsyncClient) -> None:
    if not await _prometheus_answers(_LIVE_PROMETHEUS):
        pytest.skip(f"Prometheus rules API not reachable at {_LIVE_PROMETHEUS}; start the observability overlay to run this test")
    cfg = TriBridConfig()
    cfg.tracing.prometheus_base_url = _LIVE_PROMETHEUS
    out = await build_alert_rules(cfg)
    assert out.ok is True and out.reachable is True
    names = {rule.name for rule in out.rules}
    # infra/prometheus-rules.yml ships the always-firing watchdog plus the target-down rules.
    assert "RagweldWatchdog" in names, names
    watchdog = next(rule for rule in out.rules if rule.name == "RagweldWatchdog")
    assert watchdog.state == "firing" and watchdog.query == "vector(1)" and watchdog.severity == "none"
    assert out.firing_count >= 1
    assert all(rule.query for rule in out.rules)
    # firing rules sort first
    states = [rule.state for rule in out.rules]
    assert states == sorted(states, key=lambda s: {"firing": 0, "pending": 1, "inactive": 2}.get(s, 3))

    # The API boundary serialises the same contract (config-scoped, global here).
    response = await client.get("/api/observability/alert-rules")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) >= {"ok", "reachable", "rules", "firing_count", "pending_count", "source_url", "error"}
