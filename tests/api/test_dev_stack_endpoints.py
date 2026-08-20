"""Status-only API contract for the host-owned development stack."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dev_status_reports_reachability_without_mutating_processes(client: AsyncClient) -> None:
    response = await client.get("/api/dev/status")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["frontend_running"], bool)
    assert isinstance(payload["backend_running"], bool)
    assert isinstance(payload["frontend_port"], int)
    assert isinstance(payload["backend_port"], int)
    assert isinstance(payload["details"], list)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/dev/frontend/restart",
        "/api/dev/backend/restart",
        "/api/dev/backend/clear-cache-restart",
        "/api/dev/stack/restart",
    ],
)
async def test_dev_stack_exposes_no_process_mutation_routes(client: AsyncClient, path: str) -> None:
    response = await client.post(path)

    assert response.status_code == 404
