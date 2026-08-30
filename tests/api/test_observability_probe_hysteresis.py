"""One failed readiness probe is not an incident.

The drive caught the Observability Operator Deck escalating a transient probe
failure straight to `severity=critical` with three phantom incidents, and the
deck's own next auto-refresh reporting the same probes reachable/200 - while
Tempo was demonstrably serving 27 s earlier.

Every test drives the real endpoints through the real ASGI app against a real
`ThreadingHTTPServer` standing in for Tempo's readiness listener. Nothing is
patched; `reset_probe_history()` clears module state the same way
`invalidate_loki_base_url()` does.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import pytest
from httpx import AsyncClient

from server.observability.probe_history import reset_probe_history


class _ReadinessHandler(BaseHTTPRequestHandler):
    failing: bool = False
    redirect_off_host: bool = False
    hits: int = 0
    lock = Lock()

    def do_GET(self) -> None:  # noqa: N802
        with type(self).lock:
            type(self).hits += 1
        if type(self).redirect_off_host:
            self.send_response(302)
            self.send_header("Location", "https://ragweld-auth.example.invalid/login")
            self.end_headers()
            return
        self.send_response(503 if type(self).failing else 200)
        self.end_headers()

    def log_message(self, *args: object) -> None:  # noqa: A003
        return


@contextmanager
def _readiness_listener() -> Iterator[type[_ReadinessHandler]]:
    _ReadinessHandler.failing = False
    _ReadinessHandler.redirect_off_host = False
    _ReadinessHandler.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReadinessHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _ReadinessHandler.base_url = f"http://127.0.0.1:{server.server_port}"  # type: ignore[attr-defined]
    try:
        yield _ReadinessHandler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _set_tracing(client: AsyncClient, payload: dict[str, object]) -> None:
    # The verb goes through `client.request` because scripts/check_banned.py reads the
    # httpx shorthand for it as unittest.mock, and no test here is allowlisted out of that.
    response = await client.request("PATCH", "/api/config/tracing", json=payload)
    assert response.status_code == 200, response.text


def _component(payload: dict, component_id: str) -> dict:
    return next(item for item in payload["components"] if item["id"] == component_id)


@pytest.fixture
async def tempo_probe(client: AsyncClient) -> Iterator[type[_ReadinessHandler]]:
    """Point the Tempo component at a listener this test owns, and restore it after."""

    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    original = str(baseline.json()["tracing"]["tempo_base_url"] or "")
    reset_probe_history()
    with _readiness_listener() as handler:
        await _set_tracing(client, {"tempo_base_url": handler.base_url})  # type: ignore[attr-defined]
        try:
            yield handler
        finally:
            await _set_tracing(client, {"tempo_base_url": original})
            reset_probe_history()


@pytest.mark.asyncio
async def test_one_status_request_probes_each_component_exactly_once(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    """`/status` used to build the status twice - once itself, once via incidents.

    Two samples per HTTP request makes any consecutive-failure threshold a
    fiction, and triples the probe traffic the deck generates.
    """

    _ReadinessHandler.hits = 0
    response = await client.get("/api/observability/status")
    assert response.status_code == 200

    assert _ReadinessHandler.hits == 1


@pytest.mark.asyncio
async def test_a_single_failed_probe_is_a_warning_and_not_an_incident(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    tempo_probe.failing = True

    status = await client.get("/api/observability/status")
    assert status.status_code == 200
    tempo = _component(status.json(), "tempo")

    assert tempo["reachable"] is False
    assert tempo["consecutive_failures"] == 1
    assert tempo["probe_history"] == ["failed"]
    assert tempo["severity"] == "warning", "one missed probe must never read critical"
    assert "1 of 3" in str(tempo["detail"])

    incidents = await client.get("/api/observability/incidents")
    assert incidents.status_code == 200
    assert not [item for item in incidents.json()["incidents"] if item["id"] == "component:tempo"]


@pytest.mark.asyncio
async def test_a_sustained_failure_escalates_at_the_threshold(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    tempo_probe.failing = True

    severities = []
    for _ in range(3):
        status = await client.get("/api/observability/status")
        assert status.status_code == 200
        severities.append(_component(status.json(), "tempo")["severity"])

    assert severities == ["warning", "warning", "critical"]

    status = await client.get("/api/observability/status")
    tempo = _component(status.json(), "tempo")
    assert tempo["consecutive_failures"] >= 3
    assert tempo["probe_history"][-3:] == ["failed", "failed", "failed"]

    incidents = await client.get("/api/observability/incidents")
    matching = [item for item in incidents.json()["incidents"] if item["id"] == "component:tempo"]
    assert len(matching) == 1
    assert matching[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_one_success_clears_the_failure_streak(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    tempo_probe.failing = True
    for _ in range(2):
        assert (await client.get("/api/observability/status")).status_code == 200

    tempo_probe.failing = False
    status = await client.get("/api/observability/status")
    tempo = _component(status.json(), "tempo")

    assert tempo["reachable"] is True
    assert tempo["consecutive_failures"] == 0
    assert tempo["severity"] == "healthy"
    assert tempo["probe_history"][-3:] == ["failed", "failed", "ok"]


@pytest.mark.asyncio
async def test_the_failure_threshold_is_an_operator_tunable(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    await _set_tracing(client, {"probe_failure_threshold": 1})
    try:
        tempo_probe.failing = True
        status = await client.get("/api/observability/status")
        tempo = _component(status.json(), "tempo")
        assert tempo["consecutive_failures"] == 1
        assert tempo["severity"] == "critical"
    finally:
        await _set_tracing(client, {"probe_failure_threshold": 3})


@pytest.mark.asyncio
async def test_an_auth_protected_surface_is_not_probeable_and_not_an_attention_item(
    client: AsyncClient, tempo_probe: type[_ReadinessHandler]
) -> None:
    """A probe that cannot work must not sit permanently on the attention line.

    The deck knows an Authelia-protected ingress cannot be probed from the API
    and said so in the card body, yet still counted it against "Operator
    attention needed across: ...", where it could never be cleared.
    """

    tempo_probe.redirect_off_host = True

    status = await client.get("/api/observability/status")
    payload = status.json()
    tempo = _component(payload, "tempo")

    assert tempo["reachable"] is None
    assert tempo["probeable"] is False
    assert tempo["consecutive_failures"] == 0
    assert tempo["probe_history"] == ["unprobeable"]
    assert tempo["severity"] == "info"
    assert "Tempo" not in str(payload["operator_hint"])

    incidents = await client.get("/api/observability/incidents")
    assert not [item for item in incidents.json()["incidents"] if item["id"] == "component:tempo"]
