"""`GET /api/observability/alerts` reads Alertmanager, and says so when it cannot.

Every test drives the real endpoint through the real ASGI app against a real
HTTP server (a `ThreadingHTTPServer` speaking Alertmanager's `/api/v2/alerts`
wire shape, or the live Alertmanager on the box). Nothing is patched.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest
from httpx import AsyncClient

_WATCHDOG = {
    "annotations": {
        "description": "This alert is always firing.",
        "summary": "Alerting pipeline watchdog",
    },
    "endsAt": "2026-08-30T14:13:46.527Z",
    "fingerprint": "783521f70f269176",
    "receivers": [{"name": "default"}],
    "startsAt": "2026-08-30T07:53:31.527Z",
    "status": {"inhibitedBy": [], "silencedBy": [], "state": "active"},
    "updatedAt": "2026-08-30T14:09:46.528Z",
    "generatorURL": "http://prom:9090/graph?g0.expr=vector%281%29",
    "labels": {"alertname": "RagweldWatchdog", "severity": "none"},
}

_SILENCED = {
    "annotations": {"summary": "Local model server is not being scraped"},
    "endsAt": "2026-08-30T14:13:36.894Z",
    "fingerprint": "e56c3b0a366ce474",
    "receivers": [{"name": "warning"}],
    "startsAt": "2026-08-30T07:58:21.894Z",
    "status": {"inhibitedBy": [], "silencedBy": ["abc"], "state": "suppressed"},
    "updatedAt": "2026-08-30T14:09:36.896Z",
    "labels": {"alertname": "RagweldLocalModelDown", "job": "vllm", "severity": "warning"},
}


class _AlertmanagerHandler(BaseHTTPRequestHandler):
    payload: list[dict[str, object]] = []
    status_code: int = 200

    def do_GET(self) -> None:  # noqa: N802
        if not self.path.startswith("/api/v2/alerts"):
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # noqa: A003
        return


@contextmanager
def _alertmanager(payload: list[dict[str, object]], *, status_code: int = 200) -> Iterator[str]:
    _AlertmanagerHandler.payload = payload
    _AlertmanagerHandler.status_code = status_code
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AlertmanagerHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _set_alertmanager_url(client: AsyncClient, url: str) -> None:
    response = await client.patch("/api/config/tracing", json={"alertmanager_base_url": url})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_alerts_endpoint_returns_what_alertmanager_holds(client: AsyncClient) -> None:
    """The panel's data comes from Alertmanager, not from in-process state."""

    with _alertmanager([_WATCHDOG, _SILENCED]) as base_url:
        await _set_alertmanager_url(client, base_url)
        response = await client.get("/api/observability/alerts")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["source_url"] == base_url
    assert data["total_count"] == 2
    # The silenced alert is held but not firing; the panel must not count it.
    assert data["firing_count"] == 1
    assert data["monitoring_path"] == "/infrastructure?subtab=monitoring"

    names = [alert["name"] for alert in data["alerts"]]
    assert names == ["RagweldWatchdog", "RagweldLocalModelDown"]

    watchdog = data["alerts"][0]
    assert watchdog["severity"] == "none"
    assert watchdog["state"] == "active"
    assert watchdog["silenced"] is False
    assert watchdog["inhibited"] is False
    assert watchdog["summary"] == "Alerting pipeline watchdog"
    assert watchdog["fingerprint"] == "783521f70f269176"
    assert watchdog["labels"]["alertname"] == "RagweldWatchdog"
    assert watchdog["starts_at"].startswith("2026-08-30T07:53:31")

    silenced = data["alerts"][1]
    assert silenced["state"] == "suppressed"
    assert silenced["silenced"] is True
    assert silenced["description"] is None


@pytest.mark.asyncio
async def test_alerts_endpoint_reports_an_empty_alertmanager_as_success(client: AsyncClient) -> None:
    """No alerts is a healthy answer, never an error the panel has to guess at."""

    with _alertmanager([]) as base_url:
        await _set_alertmanager_url(client, base_url)
        response = await client.get("/api/observability/alerts")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["alerts"] == []
    assert data["total_count"] == 0
    assert data["firing_count"] == 0


@pytest.mark.asyncio
async def test_alerts_endpoint_says_alertmanager_is_unconfigured(client: AsyncClient) -> None:
    await _set_alertmanager_url(client, "")
    response = await client.get("/api/observability/alerts")

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "alertmanager_unavailable"
    assert detail["reason"] == "not_configured"
    assert detail["source_url"] == ""
    assert "tracing.alertmanager_base_url" in detail["operator_hint"]
    assert detail["monitoring_path"] == "/infrastructure?subtab=monitoring"


@pytest.mark.asyncio
async def test_alerts_endpoint_says_alertmanager_did_not_answer(client: AsyncClient) -> None:
    with _alertmanager([]) as base_url:
        pass  # the server is torn down before the request, so the port is dead
    await _set_alertmanager_url(client, base_url)
    response = await client.get("/api/observability/alerts")

    assert response.status_code == 503, response.text
    detail = response.json()["detail"]
    assert detail["reason"] == "unreachable"
    assert detail["source_url"] == base_url
    assert base_url in detail["message"]


@pytest.mark.asyncio
async def test_alerts_endpoint_reports_a_bad_alertmanager_status(client: AsyncClient) -> None:
    with _alertmanager([], status_code=500) as base_url:
        await _set_alertmanager_url(client, base_url)
        response = await client.get("/api/observability/alerts")

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["reason"] == "bad_status"
    assert "HTTP 500" in detail["message"]


def _live_alertmanager_url() -> str | None:
    """The deployed Alertmanager, when this box is really running one."""

    url = os.getenv("RAGWELD_TEST_ALERTMANAGER_URL", "http://127.0.0.1:59093").strip()
    if not url:
        return None
    try:
        response = httpx.get(f"{url}/api/v2/status", timeout=2.0)
    except Exception:
        return None
    return url if response.status_code == 200 else None


@pytest.mark.asyncio
async def test_alerts_endpoint_parses_the_live_alertmanager(client: AsyncClient) -> None:
    """Against the real Alertmanager: every alert it holds validates as a wire model."""

    url = _live_alertmanager_url()
    if url is None:
        pytest.skip("no live Alertmanager on this host")

    raw = httpx.get(f"{url}/api/v2/alerts", timeout=5.0).json()
    await _set_alertmanager_url(client, url)
    response = await client.get("/api/observability/alerts")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["source_url"] == url
    assert data["total_count"] == len(raw)
    assert [alert["fingerprint"] for alert in data["alerts"]] == [item["fingerprint"] for item in raw]
    for alert in data["alerts"]:
        assert alert["name"]
        assert alert["state"] in {"active", "suppressed", "unprocessed"}
