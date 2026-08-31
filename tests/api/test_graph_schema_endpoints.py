import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

import server.api.index as index_api


def test_proposal_builder_keeps_inventory_and_chunking_off_the_api_loop() -> None:
    source = inspect.getsource(index_api.build_proposal_from_corpus)
    assert "await asyncio.to_thread(lambda: list(loader.iter_repo_files" in source
    assert "await asyncio.to_thread(chunker.chunk_file" in source


@pytest.mark.asyncio
async def test_graph_schema_proposal_refuses_graph_off_policy_with_typed_conflict(
    client: AsyncClient,
) -> None:
    corpus_id = f"schema-off-{uuid4().hex[:8]}"
    corpus_path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        patched = await client.patch(
            f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"enabled": False}
        )
        assert patched.status_code == 200, patched.text

        response = await client.post(
            f"/api/index/{corpus_id}/graph-schema/proposal",
            json={"force_refresh": False},
        )
        assert response.status_code == 409, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "graph_schema_policy_not_semantic"
        assert detail["policy"] == "off"
        assert "operator_hint" in detail
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.asyncio
async def test_semantic_index_refuses_missing_schema_approval_before_taking_a_run_fence(
    client: AsyncClient,
) -> None:
    corpus_id = f"schema-required-{uuid4().hex[:8]}"
    corpus_path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    try:
        response = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(corpus_path), "force_reindex": True},
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "graph_schema_approval_required"

        status = await client.get(f"/api/index/{corpus_id}/status")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "idle"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
