from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_train_control_plane_status_endpoint_reports_legacy_local_defaults(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/agent/train/control-plane/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["lane"] == "legacy_local"
    assert body["ready"] is False
    assert body["workflow_backend"] == "local"
    assert body["tracking_backend"] == "local"
    assert body["execution_backend"] == "mlx_qwen3"
    assert isinstance(body["components"], list)
