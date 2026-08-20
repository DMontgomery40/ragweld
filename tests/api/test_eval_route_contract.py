"""Evaluation route replacement contract tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_eval_run_item_uses_only_canonical_singular_route(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]
    assert "/api/eval/run/{run_id}" in paths
    assert {"get", "delete"}.issubset(paths["/api/eval/run/{run_id}"])
    assert "/api/eval/runs/{run_id}" not in paths
