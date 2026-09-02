"""``/api/answer`` fails closed when generation cannot run.

The answer lane used to swallow every generation failure (no provider, rejected key,
spend limit, timeout, empty reply) and return HTTP 200 with a "retrieval-only" text
assembled from the sources, labelled ``model="retrieval-only"``. That is the hidden
fallback the repository forbids: a caller could not tell an answer from a failure
without reading the debug block. Both paths now carry the same typed generation
failure the chat lane raises (``GenerationUnavailableDetail``): the non-stream route
answers 503, the stream emits a typed ``error`` event before ``done``.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from server.chat.generation_failure import GENERATION_FAILURE_HINTS
from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.qdrant_store import QdrantChunkStore

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_qdrant]

QUESTION = "Which controller handles the login authentication flow?"


def _disable_all_chat_providers(cfg: TriBridConfig) -> TriBridConfig:
    cfg.chat.litellm.enabled = False
    return cfg


async def _seeded_corpus(pg: PostgresClient) -> str:
    repo_id = f"pytest_ans_nollm_{uuid.uuid4().hex[:10]}"
    await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
    cfg = _disable_all_chat_providers(load_config())
    await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
    qdrant = QdrantChunkStore(cfg)
    chunk = Chunk(
        chunk_id="c1",
        content="login controller handles authentication",
        file_path="src/auth/login_controller.py",
        start_line=1,
        end_line=1,
        language="python",
        token_count=5,
        embedding=None,
        summary=None,
        metadata={"kind": "unit_test"},
    )
    await pg.upsert_chunks(repo_id, [chunk])
    await qdrant.upsert_chunks(repo_id, [chunk], embedding_dim=int(cfg.embedding.embedding_dim), pg=pg)
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


def _request(repo_id: str) -> dict[str, object]:
    return {
        "query": QUESTION,
        "repo_id": repo_id,
        "top_k": 5,
        "include_vector": False,
        "include_sparse": True,
        "include_graph": False,
    }


async def _sse_events(response) -> AsyncIterator[dict[str, object]]:
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        try:
            yield json.loads(line[len("data: ") :])
        except Exception:
            continue


@pytest.mark.asyncio
async def test_answer_returns_the_typed_generation_failure_without_a_provider(client: AsyncClient) -> None:
    old_litellm = os.environ.pop("LITELLM_API_KEY", None)
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg)
    try:
        resp = await client.post("/api/answer", json=_request(repo_id))
        assert resp.status_code == 503, resp.text
        detail = resp.json().get("detail") or {}
        assert detail.get("failure_kind") in GENERATION_FAILURE_HINTS
        assert detail.get("operator_hint") == GENERATION_FAILURE_HINTS[detail["failure_kind"]]
        assert detail.get("operation") == "Answer generation"
        assert "retrieval-only" not in resp.text.lower()
        assert "answer" not in resp.json()
    finally:
        await _cleanup(pg, repo_id)
        if old_litellm is not None:
            os.environ["LITELLM_API_KEY"] = old_litellm


@pytest.mark.asyncio
async def test_answer_stream_emits_the_typed_error_event_instead_of_retrieval_only_text(
    client: AsyncClient,
) -> None:
    old_litellm = os.environ.pop("LITELLM_API_KEY", None)
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg)
    try:
        async with client.stream("POST", "/api/answer/stream", json=_request(repo_id)) as resp:
            assert resp.status_code == 200
            events = [event async for event in _sse_events(resp)]
        kinds = [str(e.get("type")) for e in events]
        assert "error" in kinds, kinds
        error = next(e for e in events if e.get("type") == "error")
        detail = error.get("detail") or {}
        assert detail.get("failure_kind") in GENERATION_FAILURE_HINTS
        assert detail.get("operation") == "Answer stream generation"
        done = next(e for e in events if e.get("type") == "done")
        assert (done.get("debug") or {}).get("llm_used") is False
        # No prose stands in for the answer: the only text a client may render is the error.
        assert not [e for e in events if e.get("type") == "text"], events
        assert "retrieval-only" not in json.dumps(events).lower()
    finally:
        await _cleanup(pg, repo_id)
        if old_litellm is not None:
            os.environ["LITELLM_API_KEY"] = old_litellm
