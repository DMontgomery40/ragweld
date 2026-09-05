from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from server.db.postgres import PostgresClient
from tests.service_requirements import require_env
from tests.unit.test_graphrag_schema_transport import proposal_gateway

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_postgres]


@pytest.fixture(autouse=True)
def _corpus_scoped_gateway_environment() -> Iterator[None]:
    original = os.environ.pop("LITELLM_BASE_URL", None)
    try:
        yield
    finally:
        if original is not None:
            os.environ["LITELLM_BASE_URL"] = original


async def _create_corpus(client: AsyncClient, path: Path, gateway_url: str) -> str:
    assert not os.environ.get("LITELLM_BASE_URL"), "controlled HTTP fixtures require the corpus-scoped gateway URL"
    corpus_id = f"pytest_schema_transport_{uuid4().hex[:8]}"
    (path / "mission.md").write_text("The orbital survey mission uses a radar altimeter. The altimeter measures surface altitude.")
    created = await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(path)})
    assert created.status_code in (200, 201), created.text
    chat = await client.patch(f"/api/config/chat?corpus_id={corpus_id}", json={"litellm": {"base_url": gateway_url}})
    assert chat.status_code == 200, chat.text
    graph = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={
        "enabled": True, "build_code_graph": False, "semantic_kg_llm_model": "openai.gpt-5.6-sol",
    })
    assert graph.status_code == 200, graph.text
    return corpus_id


@pytest.mark.parametrize(("scenario", "status", "code"), [
    ("malformed", 502, "graph_schema_generation_failed"),
    ("truncated", 502, "graph_schema_generation_failed"),
    ("oversized", 502, "graph_schema_generation_failed"),
    ("429", 502, "graph_schema_generation_failed"),
    ("503", 502, "graph_schema_generation_failed"),
    ("disconnect", 502, "graph_schema_generation_failed"),
    ("slow", 504, "graph_schema_deadline_exceeded"),
])
async def test_proposal_failure_is_typed_and_preserves_the_previous_proposal(
    client: AsyncClient, tmp_path: Path, scenario: str, status: int, code: str,
) -> None:
    with proposal_gateway("valid") as (url, _requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        try:
            endpoint = f"/api/index/{corpus_id}/graph-schema/proposal"
            first = await client.post(endpoint, json={"force_refresh": True})
            assert first.status_code == 200, first.text
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/scenario", json={"scenario": scenario})
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json={"schema_proposal_timeout_s": 5})
            assert configured.status_code == 200, configured.text
            started = asyncio.get_running_loop().time()
            failed = await client.post(endpoint, json={"force_refresh": True})
            elapsed = asyncio.get_running_loop().time() - started
            assert failed.status_code == status, failed.text
            assert failed.json()["detail"]["code"] == code
            assert "operator_hint" in failed.json()["detail"]
            assert "PRIVATE PROVIDER DETAIL" not in failed.text
            assert elapsed < 7
            pg = PostgresClient(require_env("POSTGRES_DSN"))
            await pg.connect()
            try:
                persisted = await pg.get_graph_schema_proposal(corpus_id)
                assert persisted is not None
                assert persisted.schema_hash == first.json()["schema_hash"]
                assert persisted.created_at.isoformat() == first.json()["created_at"].replace("Z", "+00:00")
            finally:
                await pg.disconnect()
        finally:
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize("changed_context", ["output_budget", "proposal_reasoning", "policy"])
async def test_inflight_proposal_cannot_persist_after_its_context_changes(
    client: AsyncClient, tmp_path: Path, changed_context: str,
) -> None:
    with proposal_gateway("held_valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        pending = asyncio.create_task(client.post(f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True}))
        try:
            async with asyncio.timeout(30):
                while not requests:
                    await asyncio.sleep(0.01)
            changes = {
                "output_budget": {"schema_proposal_max_output_tokens": 8192},
                "proposal_reasoning": {"schema_proposal_reasoning_effort": "high"},
                "policy": {"enabled": False},
            }[changed_context]
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json=changes)
            assert configured.status_code == 200, configured.text
            async with AsyncClient() as control:
                await control.post(f"{url}/__fixture__/release", json={})
            response = await pending
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "graph_schema_context_changed"
            pg = PostgresClient(require_env("POSTGRES_DSN"))
            await pg.connect()
            try:
                assert await pg.get_graph_schema_proposal(corpus_id) is None
            finally:
                await pg.disconnect()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await client.delete(f"/api/corpora/{corpus_id}")


@pytest.mark.parametrize("effort", [None, "minimal", "low", "medium", "high", "xhigh"])
async def test_proposal_uses_its_own_persisted_reasoning_effort(
    client: AsyncClient, tmp_path: Path, effort: str | None,
) -> None:
    with proposal_gateway("valid") as (url, requests):
        corpus_id = await _create_corpus(client, tmp_path, url)
        try:
            changes = {"semantic_kg_reasoning_effort": "high"}
            if effort is not None:
                changes["schema_proposal_reasoning_effort"] = effort
            configured = await client.patch(f"/api/config/graph_indexing?corpus_id={corpus_id}", json=changes)
            assert configured.status_code == 200, configured.text
            proposal = await client.post(f"/api/index/{corpus_id}/graph-schema/proposal", json={"force_refresh": True})
            assert proposal.status_code == 200, proposal.text
            assert len(requests) == 1
            assert requests[0]["reasoning"] == {"effort": effort or "low"}
            reloaded = await client.get(f"/api/config?corpus_id={corpus_id}")
            assert reloaded.status_code == 200, reloaded.text
            assert reloaded.json()["graph_indexing"]["schema_proposal_reasoning_effort"] == (effort or "low")
            assert reloaded.json()["graph_indexing"]["semantic_kg_reasoning_effort"] == "high"
        finally:
            await client.delete(f"/api/corpora/{corpus_id}")
