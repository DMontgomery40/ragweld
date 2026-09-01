from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.generations import build_generation
from server.services import config_store
from tests.mcp_probe_subprocess import call_mcp_probe
from tests.service_requirements import require_env


def _assert_dependency_503(response, dependency: str, *, label: str = "request") -> None:
    assert response.status_code == 503, f"{label}: {response.text}"
    detail = response.json()["detail"]
    assert detail["code"] == "dependency_unavailable"
    assert detail["dependency"] == dependency, f"{label}: {response.text}"
    assert detail["retryable"] is True
    assert detail["operator_hint"]


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_neo4j_outage_is_attributed_and_does_not_delete_corpus(client: AsyncClient) -> None:
    corpus_id = f"neo4j-outage-{uuid.uuid4().hex[:10]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    old_neo4j_uri = os.environ.get("NEO4J_URI")

    try:
        await pg.connect()
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        cfg = load_config()
        cfg.graph_storage.neo4j_uri = "bolt://127.0.0.1:1"
        cfg.graph_search.enabled = True
        cfg.vector_search.enabled = False
        cfg.sparse_search.enabled = False
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        await pg.set_generation(
            corpus_id,
            build_generation(
                run_id=f"{corpus_id}-promoted",
                qdrant_collection="missing-graph-seed-generation",
                graph_repo_id=(
                    f"__staging__{corpus_id}__0123456789abcdef0123456789abcdef"
                ),
            ),
        )

        config_store._store = None
        os.environ["NEO4J_URI"] = "bolt://127.0.0.1:1"

        graph_disabled = await client.post(
            "/api/search",
            json={
                "query": "status",
                "repo_id": corpus_id,
                "include_vector": False,
                "include_sparse": False,
                "include_graph": False,
                "cache_mode": "bypass",
            },
        )
        assert graph_disabled.status_code == 200, graph_disabled.text

        requests = (
            ("graph stats", await client.get(f"/api/graph/{corpus_id}/stats")),
            ("corpus stats", await client.get(f"/api/corpora/{corpus_id}/stats")),
            ("search", await client.post(
                "/api/search",
                json={
                    "query": "status",
                    "repo_id": corpus_id,
                    "include_vector": False,
                    "include_sparse": False,
                    "include_graph": True,
                    "cache_mode": "bypass",
                },
            )),
            ("answer", await client.post(
                "/api/answer",
                json={
                    "query": "status",
                    "repo_id": corpus_id,
                    "include_vector": False,
                    "include_sparse": False,
                    "include_graph": True,
                    "cache_mode": "bypass",
                },
            )),
            ("answer stream", await client.post(
                "/api/answer/stream",
                json={
                    "query": "status",
                    "repo_id": corpus_id,
                    "include_vector": False,
                    "include_sparse": False,
                    "include_graph": True,
                    "cache_mode": "bypass",
                },
            )),
        )
        for label, response in requests:
            _assert_dependency_503(response, "neo4j", label=label)

        mcp_status, mcp_body = await call_mcp_probe(corpus_id, "graph_only")
        assert mcp_status == 503, mcp_body
        mcp_detail = mcp_body["detail"]
        assert mcp_detail["code"] == "dependency_unavailable"
        assert mcp_detail["dependency"] == "neo4j"
        assert mcp_detail["operator_hint"]

        ready = await client.get(f"/api/ready?corpus_id={corpus_id}")
        assert ready.status_code == 503
        assert ready.json()["dependencies"]["postgres"]["ok"] is True
        assert ready.json()["dependencies"]["neo4j"]["ok"] is False

        delete = await client.delete(f"/api/corpora/{corpus_id}")
        _assert_dependency_503(delete, "neo4j")
        assert await pg.get_corpus(corpus_id) is not None
    finally:
        if old_neo4j_uri is None:
            os.environ.pop("NEO4J_URI", None)
        else:
            os.environ["NEO4J_URI"] = old_neo4j_uri
        config_store._store = None
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()
