"""A configured reranker that fails takes the request down with it.

``Reranker.try_rerank`` used to catch every exception, log a warning and hand the
unreranked fusion order back; fusion recorded ``rerank_ok=False`` in its debug dict and
``/api/search`` answered 200. A caller who configured cloud reranking got vector/sparse
order and no signal above the debug block, and D26's typed budget/content errors never
reached a request boundary. Now a reranker failure in a configured mode is the typed
503 ``reranker_failed`` on every retrieval surface, exactly like a failed required leg.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.qdrant_store import QdrantChunkStore

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_qdrant]

QUESTION = "How does the login controller validate a session token?"
UNRESOLVABLE_ALIAS = "pytest.no-such-reranker-alias"


async def _seeded_corpus(pg: PostgresClient, cfg: TriBridConfig) -> str:
    repo_id = f"pytest_rerank_closed_{uuid.uuid4().hex[:10]}"
    await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
    await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
    qdrant = QdrantChunkStore(cfg)
    chunks = [
        Chunk(
            chunk_id="c1",
            content="login controller validates the session token before authentication",
            file_path="src/auth/login_controller.py",
            start_line=1,
            end_line=2,
            language="python",
            token_count=9,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        ),
        Chunk(
            chunk_id="c2",
            content="session token refresh happens in the token service",
            file_path="src/auth/token_service.py",
            start_line=1,
            end_line=2,
            language="python",
            token_count=8,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        ),
    ]
    await pg.upsert_chunks(repo_id, chunks)
    await qdrant.upsert_chunks(repo_id, chunks, embedding_dim=int(cfg.embedding.embedding_dim), pg=pg)
    return repo_id


async def _cleanup(pg: PostgresClient, repo_id: str) -> None:
    try:
        await QdrantChunkStore(load_config()).delete_corpus(repo_id)
    except Exception:
        pass
    try:
        await pg.delete_corpus(repo_id)
    except Exception:
        pass


def _search_body(repo_id: str) -> dict[str, object]:
    return {
        "query": QUESTION,
        "repo_id": repo_id,
        "top_k": 5,
        "include_vector": False,
        "include_sparse": True,
        "include_graph": False,
    }


@pytest.mark.asyncio
async def test_search_fails_closed_when_the_configured_cloud_reranker_cannot_run(client: AsyncClient) -> None:
    cfg = load_config()
    cfg.reranking.reranker_mode = "cloud"
    cfg.reranking.reranker_cloud_model = UNRESOLVABLE_ALIAS
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg, cfg)
    try:
        resp = await client.post("/api/search", json=_search_body(repo_id))
        assert resp.status_code == 503, resp.text
        detail = resp.json().get("detail") or {}
        assert detail.get("code") == "reranker_failed"
        assert detail.get("mode") == "cloud"
        assert detail.get("operator_hint")
        assert "matches" not in resp.json()
        # The answer lane sits on the same fusion and must not answer over an unreranked list.
        answer = await client.post("/api/answer", json=_search_body(repo_id))
        assert answer.status_code == 503, answer.text
        assert (answer.json().get("detail") or {}).get("code") == "reranker_failed"
        # Chat, non-stream and stream: retrieval runs before the first SSE byte, so both are
        # the same typed 503, not a generic 500 and not an answer over the unreranked list.
        chat_body = {"message": QUESTION, "sources": {"corpus_ids": [repo_id]}}
        chat = await client.post("/api/chat", json=chat_body)
        assert chat.status_code == 503, chat.text
        assert (chat.json().get("detail") or {}).get("code") == "reranker_failed"
        stream = await client.post("/api/chat/stream", json=chat_body)
        assert stream.status_code == 503, stream.text
        assert (stream.json().get("detail") or {}).get("code") == "reranker_failed"
    finally:
        await _cleanup(pg, repo_id)


@pytest.mark.asyncio
async def test_search_answers_when_reranking_is_off(client: AsyncClient) -> None:
    cfg = load_config()
    cfg.reranking.reranker_mode = "none"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg, cfg)
    try:
        resp = await client.post("/api/search", json=_search_body(repo_id))
        assert resp.status_code == 200, resp.text
        matches = resp.json().get("matches") or []
        assert matches and matches[0]["file_path"] == "src/auth/login_controller.py"
        assert resp.json()["debug"]["rerank_mode"] == "none"
    finally:
        await _cleanup(pg, repo_id)
