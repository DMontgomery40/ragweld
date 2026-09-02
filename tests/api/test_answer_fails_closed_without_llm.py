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

import asyncio
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
from tests.api.fake_gateway import empty_stream_gateway, gateway_env

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


@pytest.mark.asyncio
async def test_answer_stream_with_an_empty_provider_stream_fails_and_writes_no_cache(
    client: AsyncClient,
) -> None:
    """A provider that streams no content is a failed generation: the stream carries the typed
    error event and no prose, and nothing reaches the semantic cache."""
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = f"pytest_ans_empty_{uuid.uuid4().hex[:10]}"
    with empty_stream_gateway() as base_url, gateway_env(base_url):
        try:
            await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
            cfg = load_config()
            cfg.chat.litellm.enabled = True
            cfg.chat.litellm.base_url = base_url
            cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
            cfg.semantic_cache.enabled = 1
            cfg.semantic_cache.mode = "read_write"
            cfg.semantic_cache.min_query_chars = 1
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

            async with client.stream("POST", "/api/answer/stream", json=_request(repo_id)) as resp:
                assert resp.status_code == 200
                events = [event async for event in _sse_events(resp)]
            kinds = [str(e.get("type")) for e in events]
            assert "error" in kinds, kinds
            error = next(e for e in events if e.get("type") == "error")
            assert (error.get("detail") or {}).get("operation") == "Answer stream generation"
            assert "no content" in str((error.get("detail") or {}).get("gateway_reason") or "")
            assert "text" not in kinds, kinds
            done = next(e for e in events if e.get("type") == "done")
            debug = done.get("debug") or {}
            assert debug.get("llm_used") is False
            # The retrieval cache may record its own write; the GENERATION cache write (which
            # tags cache_namespace=answer_generation) must not have happened.
            assert (debug.get("fusion_debug") or {}).get("cache_namespace") != "answer_generation"
            assert "retrieval-only" not in json.dumps(events).lower()
        finally:
            await _cleanup(pg, repo_id)


@pytest.mark.asyncio
async def test_a_failed_retrieval_is_a_typed_503_on_both_answer_routes_never_an_answer(
    client: AsyncClient,
) -> None:
    """An indexed corpus whose stored Qdrant URL is then broken: the vector leg cannot run,
    so both answer routes answer the typed retrieval 503 (``required_retrieval_leg_failed``)
    and no generation happens - never an ungrounded answer, never "generation unavailable".
    (The untyped wrapper for failures no typed error names is covered at the helper in
    ``tests/unit/test_answer_service_retrieval.py``; it has no HTTP trigger without faults.)"""
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg)
    try:
        cfg = load_config()
        cfg.chat.litellm.enabled = True
        cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
        cfg.qdrant.url = "http://127.0.0.1:9"  # nothing listens on the discard port
        await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
        body = {**_request(repo_id), "include_vector": True, "include_sparse": True}

        resp = await client.post("/api/answer", json=body)
        assert resp.status_code == 503, resp.text
        detail = resp.json().get("detail") or {}
        assert detail.get("code") in {"required_retrieval_leg_failed", "dependency_unavailable"}, detail
        assert "answer" not in resp.json()
        assert "generation" not in json.dumps(detail).lower()

        stream = await client.post("/api/answer/stream", json=body)
        assert stream.status_code == 503, stream.text
        detail = stream.json().get("detail") or {}
        assert detail.get("code") in {"required_retrieval_leg_failed", "dependency_unavailable"}, detail
    finally:
        await _cleanup(pg, repo_id)


async def _answer_cache_rows(pg: PostgresClient, corpus_id: str) -> int:
    """Generation-cache rows the answer lane wrote for this corpus (payload carries `answer`)."""
    from server.retrieval.cache import SemanticCacheService

    async with pg._pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM semantic_cache_entries WHERE endpoint = 'answer' AND scope_key = $1;",
            SemanticCacheService.scope_key([corpus_id]),
        )
    count = 0
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, dict) and "answer" in payload:
            count += 1
    return count


@pytest.mark.requires_postgres
@pytest.mark.requires_qdrant
@pytest.mark.asyncio
async def test_answer_stream_closed_on_done_has_its_cache_committed(tmp_path) -> None:
    """The answer stream commits its generation cache before the terminal `done` event: a
    client that reads `done` and leaves finds the answer cached (one generation row), and the
    same question again is served from the cache - the provider sees no second request."""
    import httpx

    from tests.api.fake_gateway import slow_delta_gateway, slow_delta_requests
    from tests.api.live_server import live_app_subprocess

    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    repo_id = await _seeded_corpus(pg)
    with slow_delta_gateway(delay_seconds=0.05) as base_url, gateway_env(base_url):
        cfg = load_config()
        cfg.chat.litellm.enabled = True
        cfg.chat.litellm.base_url = base_url
        cfg.chat.litellm.default_model = "openai.gpt-5.6-luna"
        cfg.semantic_cache.enabled = 1
        cfg.semantic_cache.mode = "read_write"
        cfg.semantic_cache.min_query_chars = 1
        await pg.upsert_corpus_config_json(repo_id, cfg.model_dump(mode="serialization"))
        config_path = tmp_path / "tribrid_config.json"
        config_path.write_text(json.dumps(cfg.model_dump(mode="serialization")), encoding="utf-8")
        try:
            with live_app_subprocess(
                config_path=config_path,
                env={"LITELLM_BASE_URL": base_url, "LITELLM_API_KEY": "pytest-fake-gateway-key"},
            ) as live_url:
                async with httpx.AsyncClient(base_url=live_url, timeout=60.0) as client:
                    done_seen = False
                    async with client.stream("POST", "/api/answer/stream", json=_request(repo_id)) as response:
                        assert response.status_code == 200, response.status_code
                        async for line in response.aiter_lines():
                            if line.startswith("data: ") and '"done"' in line:
                                done_seen = True
                                break
                    assert done_seen
                    await asyncio.sleep(1.0)
                    assert await _answer_cache_rows(pg, repo_id) == 1
                    again = await client.post("/api/answer/stream", json=_request(repo_id))
                    assert again.status_code == 200, again.text
                    assert len(slow_delta_requests()) == 1, len(slow_delta_requests())
                    assert "Jet Aviation" in again.text
        finally:
            await _cleanup(pg, repo_id)
