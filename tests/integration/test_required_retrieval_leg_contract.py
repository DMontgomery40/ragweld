from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import RetrievalContractMismatchDetail
from server.retrieval.contracts import sparse_contract_from_config
from server.services import config_store
from server.services.conversation_store import get_conversation_store


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("leg", "expected_code"),
    [
        ("vector", "embedding_contract_mismatch"),
        ("sparse", "sparse_contract_mismatch"),
    ],
)
async def test_requested_contract_mismatch_never_returns_partial_success(
    client: AsyncClient,
    leg: str,
    expected_code: str,
) -> None:
    corpus_id = f"{leg}-mismatch-{uuid.uuid4().hex[:10]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])

    try:
        await pg.connect()
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        cfg = load_config()
        cfg.vector_search.enabled = True
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = False
        cfg.chat.litellm.enabled = False
        cfg.embedding.embedding_backend = "deterministic"
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        current_sparse = sparse_contract_from_config(cfg)
        # Sparse drift: the corpus was indexed under a different BM25 contract (k1 + stemming).
        drifted_sparse = {**current_sparse, "k1": float(current_sparse["k1"]) + 0.7, "stemmer": not current_sparse["stemmer"]}
        await pg.update_corpus_embedding_meta(
            corpus_id,
            backend="provider" if leg == "vector" else "deterministic",
            provider="openai" if leg == "vector" else cfg.embedding.embedding_type,
            model="text-embedding-3-large" if leg == "vector" else cfg.embedding.effective_model,
            dimensions=3072 if leg == "vector" else cfg.embedding.embedding_dim,
            sparse_contract=drifted_sparse if leg == "sparse" else current_sparse,
        )
        config_store._store = None

        body = {
            "query": "status",
            "repo_id": corpus_id,
            "include_vector": True,
            "include_sparse": True,
            "include_graph": False,
            "cache_mode": "bypass",
        }
        stream_conversation_id = f"contract-stream-{corpus_id}"
        responses = (
            ("search", await client.post("/api/search", json=body)),
            ("answer", await client.post("/api/answer", json=body)),
            ("answer stream", await client.post("/api/answer/stream", json=body)),
            ("chat", await client.post(
                "/api/chat",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": True,
                    "include_sparse": True,
                    "include_graph": False,
                    "cache_mode": "bypass",
                },
            )),
            ("chat stream", await client.post(
                "/api/chat/stream",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": True,
                    "include_sparse": True,
                    "include_graph": False,
                    "cache_mode": "bypass",
                    "conversation_id": stream_conversation_id,
                },
            )),
            ("MCP search", await client.get(f"/api/mcp/rag_search?q=status&corpus_id={corpus_id}")),
        )

        for label, response in responses:
            assert response.status_code == 409, f"{label}: {response.text}"
            detail = response.json()["detail"]
            assert detail["code"] == expected_code, f"{label}: {response.text}"
            assert detail["leg"] == leg
            assert detail["corpus_id"] == corpus_id
            # The 409 payload is a validated public boundary: it must round-trip
            # through the registered model with actionable contract content.
            parsed = RetrievalContractMismatchDetail.model_validate(detail)
            assert parsed.required_action.strip(), f"{label}: missing required_action"
            assert parsed.expected_contract, f"{label}: missing expected_contract"
            assert parsed.current_contract, f"{label}: missing current_contract"
        assert get_conversation_store().get_messages(stream_conversation_id) == []
    finally:
        config_store._store = None
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()


@pytest.mark.requires_postgres
@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
@pytest.mark.parametrize("leg", ["vector", "sparse", "graph"])
async def test_requested_leg_execution_failure_never_returns_partial_success(
    client: AsyncClient,
    leg: str,
) -> None:
    corpus_id = f"{leg}-execution-failure-{uuid.uuid4().hex[:10]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    missing_model = "/definitely/missing/ragweld-embedding-model"

    try:
        await pg.connect()
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        cfg = load_config()
        cfg.vector_search.enabled = leg == "vector"
        cfg.sparse_search.enabled = leg == "sparse"
        cfg.graph_search.enabled = leg == "graph"
        cfg.graph_search.mode = "chunk"
        cfg.chat.litellm.enabled = False
        if leg in {"vector", "graph"}:
            cfg.embedding.embedding_backend = "provider"
            cfg.embedding.embedding_type = "local"
            cfg.embedding.embedding_model_local = missing_model
        if leg == "sparse":
            cfg.embedding.embedding_backend = "deterministic"

        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        await pg.update_corpus_embedding_meta(
            corpus_id,
            backend=cfg.embedding.embedding_backend,
            provider=cfg.embedding.embedding_type,
            model=cfg.embedding.effective_model,
            dimensions=cfg.embedding.embedding_dim,
            sparse_contract=sparse_contract_from_config(cfg),
        )
        if leg == "sparse":
            # The corpus has indexed chunk rows (last_indexed is set) but its Qdrant
            # generation is gone: the sparse leg must fail closed, never return [].
            await pg.upsert_chunks(
                corpus_id,
                [
                    Chunk(
                        chunk_id="c1",
                        content="status report",
                        file_path="status.md",
                        start_line=1,
                        end_line=1,
                        language=None,
                        token_count=2,
                    )
                ],
            )
        config_store._store = None

        body = {
            "query": "status",
            "repo_id": corpus_id,
            "include_vector": leg == "vector",
            "include_sparse": leg == "sparse",
            "include_graph": leg == "graph",
            "cache_mode": "bypass",
        }
        stream_conversation_id = f"execution-stream-{corpus_id}"
        responses = (
            ("search", await client.post("/api/search", json=body)),
            ("answer", await client.post("/api/answer", json=body)),
            ("answer stream", await client.post("/api/answer/stream", json=body)),
            ("chat", await client.post(
                "/api/chat",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": leg == "vector",
                    "include_sparse": leg == "sparse",
                    "include_graph": leg == "graph",
                    "cache_mode": "bypass",
                },
            )),
            ("chat stream", await client.post(
                "/api/chat/stream",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": leg == "vector",
                    "include_sparse": leg == "sparse",
                    "include_graph": leg == "graph",
                    "cache_mode": "bypass",
                    "conversation_id": stream_conversation_id,
                },
            )),
            ("MCP search", await client.get(f"/api/mcp/rag_search?q=status&corpus_id={corpus_id}")),
        )

        for label, response in responses:
            assert response.status_code == 503, f"{label}: {response.text}"
            detail = response.json()["detail"]
            assert detail["code"] == "required_retrieval_leg_failed", f"{label}: {response.text}"
            assert detail["leg"] == leg
            assert detail["retryable"] is True
            assert detail["operator_hint"]
            assert missing_model not in response.text
        assert get_conversation_store().get_messages(stream_conversation_id) == []
    finally:
        config_store._store = None
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()


@pytest.mark.requires_postgres
@pytest.mark.asyncio
@pytest.mark.parametrize("leg", ["vector", "sparse"])
async def test_unreachable_qdrant_is_a_typed_503_never_a_500_or_partial_success(
    client: AsyncClient,
    leg: str,
) -> None:
    """The vector store is a required dependency: an unreachable Qdrant fails closed with dependency=qdrant."""
    corpus_id = f"{leg}-qdrant-down-{uuid.uuid4().hex[:10]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])

    try:
        await pg.connect()
        await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        cfg = load_config()
        cfg.vector_search.enabled = leg == "vector"
        cfg.sparse_search.enabled = leg == "sparse"
        cfg.graph_search.enabled = False
        cfg.chat.litellm.enabled = False
        cfg.embedding.embedding_backend = "deterministic"
        # Nothing listens on the discard port: every Qdrant call is connection-refused.
        cfg.qdrant.url = "http://127.0.0.1:9"
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        await pg.update_corpus_embedding_meta(
            corpus_id,
            backend="deterministic",
            provider=cfg.embedding.embedding_type,
            model=cfg.embedding.effective_model,
            dimensions=cfg.embedding.embedding_dim,
            sparse_contract=sparse_contract_from_config(cfg),
        )
        await pg.upsert_chunks(
            corpus_id,
            [Chunk(chunk_id="c1", content="status report", file_path="status.md", start_line=1, end_line=1, language=None, token_count=2)],
        )
        config_store._store = None

        body = {
            "query": "status",
            "repo_id": corpus_id,
            "include_vector": leg == "vector",
            "include_sparse": leg == "sparse",
            "include_graph": False,
            "cache_mode": "bypass",
        }
        stream_conversation_id = f"qdrant-down-stream-{corpus_id}"
        responses = (
            ("search", await client.post("/api/search", json=body)),
            ("answer", await client.post("/api/answer", json=body)),
            ("answer stream", await client.post("/api/answer/stream", json=body)),
            ("chat", await client.post(
                "/api/chat",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": leg == "vector",
                    "include_sparse": leg == "sparse",
                    "include_graph": False,
                    "cache_mode": "bypass",
                },
            )),
            ("chat stream", await client.post(
                "/api/chat/stream",
                json={
                    "message": body["query"],
                    "sources": {"corpus_ids": [corpus_id]},
                    "include_vector": leg == "vector",
                    "include_sparse": leg == "sparse",
                    "include_graph": False,
                    "cache_mode": "bypass",
                    "conversation_id": stream_conversation_id,
                },
            )),
            ("MCP search", await client.get(f"/api/mcp/rag_search?q=status&corpus_id={corpus_id}")),
        )

        for label, response in responses:
            assert response.status_code == 503, f"{label}: {response.status_code} {response.text[:300]}"
            detail = response.json()["detail"]
            assert detail["dependency"] == "qdrant", f"{label}: {response.text}"
            assert detail["operator_hint"]
        assert get_conversation_store().get_messages(stream_conversation_id) == []
    finally:
        config_store._store = None
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()
