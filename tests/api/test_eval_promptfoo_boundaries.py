"""Promptfoo regression lane fails closed when its substrate cannot execute.

Real corpus, real config store, real dataset entry with an expected answer.
The test process has no authenticated LiteLLM gateway, so the run must return
the typed 503 for the promptfoo dependency instead of fabricating results.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_promptfoo_run_fails_closed_without_gateway(client: AsyncClient) -> None:
    corpus_id = f"pytest_promptfoo_{uuid.uuid4().hex[:8]}"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": "tests/fixtures/acceptance_corpus"},
    )
    assert created.status_code == 200, created.text
    try:
        entry = await client.post(
            f"/api/dataset?corpus_id={corpus_id}",
            json={
                "entry_id": "q1",
                "question": "How often is the salinity sensor array calibrated?",
                "expected_paths": ["sensor-calibration.md"],
                "expected_answer": "Every 45 days using the Halcyon reference brine.",
            },
        )
        assert entry.status_code == 200, entry.text

        response = await client.post("/api/eval/promptfoo/run", json={"repo_id": corpus_id, "sample_size": 1})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "promptfoo"
        assert "never fabricated" in detail["operator_hint"].lower()
        assert "reason:" in detail["operator_hint"].lower()

        listing = await client.get(f"/api/eval/promptfoo/runs?corpus_id={corpus_id}")
        assert listing.status_code == 200
        assert listing.json()["runs"] == []
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
