"""Prometheus metrics route contract tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_only_canonical_metrics_route_is_exposed(client: AsyncClient) -> None:
    canonical = await client.get("/metrics")
    assert canonical.status_code == 200
    assert "text/plain" in canonical.headers["content-type"]

    removed_alias = await client.get("/api/metrics")
    assert removed_alias.status_code == 404
