"""Ragas eval lane fails closed when its substrate cannot execute.

Uses a real corpus, the real config store, and a real dataset entry. The judge
gateway is unavailable to the test process (no authenticated LiteLLM in the
test environment), so an eval run with Ragas enabled must return the typed
503 instead of skipping scoring silently.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_eval_run_with_ragas_enabled_fails_closed_without_judge(client: AsyncClient) -> None:
    corpus_id = f"pytest_ragas_{uuid.uuid4().hex[:8]}"
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
            },
        )
        assert entry.status_code == 200, entry.text

        patched = await client.request(
            "PATCH",
            f"/api/config/evaluation?corpus_id={corpus_id}",
            json={"ragas_enabled": True, "ragas_judge_model": "ragweld-alias-that-does-not-exist"},
        )
        assert patched.status_code == 200, patched.text

        response = await client.post("/api/eval/run", json={"repo_id": corpus_id, "sample_size": 1})
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "dependency_unavailable"
        assert detail["dependency"] == "ragas"
        assert "never faked" in detail["operator_hint"].lower()
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
