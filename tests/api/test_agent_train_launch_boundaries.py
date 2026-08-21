"""Launch-time backend boundary contract for Learning Agent runs.

Configured-but-unavailable target backends must fail closed with typed 503
details; the launcher never silently substitutes the local lane. Real corpora
and the real config store are used — no mocks.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _create_corpus(client: AsyncClient, corpus_id: str) -> None:
    response = await client.post(
        "/api/corpora",
        json={
            "corpus_id": corpus_id,
            "name": corpus_id,
            "path": "tests/fixtures/acceptance_corpus",
        },
    )
    assert response.status_code == 200, response.text


async def _set_training_config(client: AsyncClient, corpus_id: str, updates: dict) -> None:
    response = await client.request(
        "PATCH",
        f"/api/config/training?corpus_id={corpus_id}",
        json=updates,
    )
    assert response.status_code == 200, response.text


async def _delete_corpus(client: AsyncClient, corpus_id: str) -> None:
    await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_flyte_workflow_selection_fails_closed(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_flyte_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(client, corpus_id, {"ragweld_agent_workflow_backend": "flyte"})
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "workflow_backend_unavailable"
        assert detail["backend"] == "flyte"
        assert "refusing to fake orchestration" in detail["message"].lower()
        assert detail["operator_hint"]
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_unsloth_execution_selection_reports_exact_hardware_blocker(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_unsloth_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        await _set_training_config(client, corpus_id, {"ragweld_agent_backend": "unsloth"})
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "execution_backend_unavailable"
        assert detail["backend"] == "unsloth"
        assert "cuda" in detail["message"].lower()
        assert detail["operator_hint"]
    finally:
        await _delete_corpus(client, corpus_id)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_mlflow_tracking_selection_fails_closed_when_unreachable(client: AsyncClient) -> None:
    corpus_id = f"pytest_launch_mlflow_{uuid.uuid4().hex[:8]}"
    await _create_corpus(client, corpus_id)
    try:
        # Point tracking at a real-but-closed local port: connection is refused.
        await _set_training_config(
            client,
            corpus_id,
            {
                "ragweld_agent_tracking_backend": "mlflow",
                "ragweld_agent_mlflow_tracking_url": "http://127.0.0.1:9",
            },
        )
        response = await client.post("/api/agent/train/start", json={"repo_id": corpus_id})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "tracking_backend_unavailable"
        assert detail["backend"] == "mlflow"
        assert "unreachable" in detail["message"].lower()
        assert "does not fall back" in detail["operator_hint"].lower()
    finally:
        await _delete_corpus(client, corpus_id)
