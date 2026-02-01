"""API tests for dev stack orchestration endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dev_status_reports_frontend_and_backend_running(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.docker as docker_api

    monkeypatch.setattr(docker_api, "_resolve_dev_ports", lambda: (5173, 8012), raising=True)

    async def _ok(_url: str, timeout_s: float = 1.5) -> bool:  # noqa: ARG001
        return True

    monkeypatch.setattr(docker_api, "_http_ok", _ok, raising=True)

    r = await client.get("/api/dev/status")
    assert r.status_code == 200
    payload = r.json()

    assert payload["frontend_running"] is True
    assert payload["backend_running"] is True
    assert payload["frontend_port"] == 5173
    assert payload["backend_port"] == 8012
    assert payload["details"] == []


@pytest.mark.asyncio
async def test_dev_status_includes_details_when_frontend_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.docker as docker_api

    monkeypatch.setattr(docker_api, "_resolve_dev_ports", lambda: (5173, 8012), raising=True)

    async def _fake_ok(url: str, timeout_s: float = 1.5) -> bool:  # noqa: ARG001
        # Only the backend health probe is reachable in this scenario.
        return url.endswith("/api/health")

    monkeypatch.setattr(docker_api, "_http_ok", _fake_ok, raising=True)

    r = await client.get("/api/dev/status")
    assert r.status_code == 200
    payload = r.json()

    assert payload["frontend_running"] is False
    assert payload["backend_running"] is True
    assert any("Frontend not reachable" in d for d in payload["details"])


@pytest.mark.asyncio
async def test_dev_status_probes_multiple_hosts_and_returns_resolved_urls(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.docker as docker_api

    monkeypatch.setattr(docker_api, "_resolve_dev_ports", lambda: (5173, 8012), raising=True)

    async def _fake_ok(url: str, timeout_s: float = 1.5) -> bool:  # noqa: ARG001
        # Simulate a common dev scenario: the frontend is reachable via localhost but not 127.0.0.1.
        if url == "http://localhost:5173/web":
            return True
        # Backend health is reachable via 127.0.0.1 as normal.
        if url == "http://127.0.0.1:8012/api/health":
            return True
        return False

    monkeypatch.setattr(docker_api, "_http_ok", _fake_ok, raising=True)

    r = await client.get("/api/dev/status")
    assert r.status_code == 200
    payload = r.json()

    assert payload["frontend_running"] is True
    assert payload["backend_running"] is True
    assert payload["frontend_url"] == "http://localhost:5173/web"
    assert payload["backend_url"] == "http://127.0.0.1:8012/api"
    assert any("preferred http://127.0.0.1:5173/web failed" in d for d in payload["details"])


@pytest.mark.asyncio
async def test_dev_restart_frontend_rejects_non_local_clients(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.docker as docker_api

    monkeypatch.setattr(docker_api, "_is_local_client", lambda _req: False, raising=True)

    r = await client.post("/api/dev/frontend/restart")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dev_restart_backend_returns_success_and_is_idempotent_under_test(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import server.api.docker as docker_api

    # Allow orchestration in this test environment.
    monkeypatch.setattr(docker_api, "_is_local_client", lambda _req: True, raising=True)
    monkeypatch.setattr(docker_api, "_resolve_dev_ports", lambda: (5173, 8012), raising=True)

    # Avoid real side effects from background tasks.
    monkeypatch.setattr(docker_api, "_dev_lock_try_acquire", lambda: True, raising=True)
    monkeypatch.setattr(docker_api, "_dev_lock_release", lambda: None, raising=True)
    monkeypatch.setattr(docker_api, "_touch_reload_trigger", lambda: None, raising=True)

    r = await client.post("/api/dev/backend/restart")
    assert r.status_code == 200
    payload = r.json()
    assert payload["success"] is True
    assert payload["backend_port"] == 8012


@pytest.mark.asyncio
async def test_dev_restart_returns_409_when_busy(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import server.api.docker as docker_api

    monkeypatch.setattr(docker_api, "_is_local_client", lambda _req: True, raising=True)
    monkeypatch.setattr(docker_api, "_dev_lock_try_acquire", lambda: False, raising=True)

    r = await client.post("/api/dev/frontend/restart")
    assert r.status_code == 409

