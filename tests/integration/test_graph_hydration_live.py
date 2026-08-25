"""Graph-leg hydration modes against the real stores (no fake Postgres/Neo4j/Embedder).

Replaces the three monkeypatched unit tests that used to cover chunk-mode
hydration, chunk-mode entity expansion and entity-mode hydration. The graph
is seeded the way production seeds it: a real index run over the acceptance
corpus with the lexical graph + chunk vector index on, and (for entity modes)
the semantic knowledge graph extracted through the cheap gateway alias.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
from server.services import config_store

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"
_QUESTION = "How often is the salinity sensor calibrated?"
_KG_MODEL = os.environ.get("GRAPH_E2E_KG_MODEL", "openai.gpt-5.6-luna")


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 300.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        last = res.json()
        if last.get("status") in {"complete", "error", "cancelled"}:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"index did not finish in time: {last}")


async def _gateway_serves(base_url: str, model: str) -> str | None:
    key = os.environ.get("LITELLM_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=3.0) as probe:
            response = await probe.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"})
    except Exception as exc:
        return f"LiteLLM gateway not reachable at {base_url}: {exc}"
    if response.status_code != 200:
        return f"LiteLLM gateway answered HTTP {response.status_code}"
    served = {str(item.get("id")) for item in (response.json().get("data") or [])}
    return None if model in served else f"gateway does not serve {model}"


async def _graph_only_search(client: AsyncClient, corpus_id: str, *, top_k: int | None = 8) -> dict:
    # A request top_k caps BOTH the graph seeds and the final list; pass None to
    # let graph_search.top_k seed and retrieval.final_k cap.
    res = await client.post(
        "/api/search",
        json={
            "query": _QUESTION,
            "corpus_id": corpus_id,
            **({"top_k": top_k} if top_k is not None else {}),
            "include_vector": False,
            "include_sparse": False,
            "include_graph": True,
            "cache_mode": "bypass",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _index(client: AsyncClient, corpus_id: str) -> None:
    started = await client.post(
        "/api/index", json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True}
    )
    assert started.status_code == 200, started.text
    final = await _wait_for_index(client, corpus_id)
    assert final["status"] == "complete", final


async def test_graph_leg_hydrates_real_chunks_in_every_mode(client: AsyncClient) -> None:
    corpus_id = f"graph-hydrate-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    cfg = load_config()
    kg_skip = await _gateway_serves(str(cfg.chat.litellm.base_url), _KG_MODEL)
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)}
        )
        assert created.status_code in (200, 201), created.text

        # --- chunk mode: lexical graph + Neo4j chunk vector index, hydrated by chunk_id from Postgres
        cfg.embedding.embedding_backend = "deterministic"
        # Small chunks so the four-file fixture yields well over five chunks and
        # the vector seeds (top_k floor is 5) leave room for entity expansion.
        cfg.chunking.chunking_strategy = "fixed_chars"  # the default `ast` falls back to the greedy target on prose
        cfg.chunking.chunk_size = 200
        cfg.chunking.chunk_overlap = 0
        cfg.vector_search.enabled = True
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = True
        cfg.graph_search.mode = "chunk"
        cfg.graph_search.chunk_entity_expansion_enabled = False
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_lexical_graph = True
        cfg.graph_indexing.store_chunk_embeddings = True
        cfg.graph_indexing.semantic_kg_enabled = False
        cfg.reranking.reranker_mode = "none"
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = 0
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None
        await _index(client, corpus_id)

        rows = await pg.list_chunks_for_repo(corpus_id, limit=None)
        content_by_id = {str(row.chunk_id): row.content for row in rows}
        assert len(content_by_id) > 5, f"fixture must chunk into more than five rows, got {len(content_by_id)}"

        payload = await _graph_only_search(client, corpus_id)
        matches = payload["matches"]
        debug = payload["debug"]
        assert matches, payload
        assert all(m["source"] == "graph" for m in matches)
        # Hydration by chunk_id: every hit is a real Postgres row with that row's content.
        assert all(m["chunk_id"] in content_by_id for m in matches), [m["chunk_id"] for m in matches]
        assert all(m["content"] == content_by_id[m["chunk_id"]] for m in matches)
        assert any("calibrat" in m["content"].lower() for m in matches)
        per_corpus = debug["fusion_per_corpus"][corpus_id]
        assert per_corpus["fusion_graph_mode"] == "chunk"
        # Retrieval shaping may add adjacent chunks after the leg, so the leg's own
        # hydrated count is a lower bound on the final list, never a different source.
        assert 1 <= int(per_corpus["fusion_graph_hydrated_chunks"]) <= len(matches)
        assert int(per_corpus["fusion_graph_entity_expansion_hits"]) == 0
        chunk_mode_ids = {m["chunk_id"] for m in matches}

        if kg_skip:
            pytest.skip(f"entity modes need the semantic KG through the gateway: {kg_skip}")

        # --- chunk mode + entity expansion: entities extracted by the semantic KG add
        # chunks reachable through IN_CHUNK links beyond the vector seeds.
        cfg.graph_indexing.semantic_kg_enabled = True
        cfg.graph_indexing.semantic_kg_mode = "llm"
        cfg.graph_indexing.semantic_kg_llm_model = _KG_MODEL
        cfg.graph_search.chunk_entity_expansion_enabled = True
        cfg.graph_search.top_k = 5  # the floor; fewer seeds than chunks so expansion has room to add
        cfg.retrieval.final_k = 12
        cfg.chat.litellm.enabled = True
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None
        await _index(client, corpus_id)
        graph_stats = await client.get(f"/api/graph/{corpus_id}/stats")
        assert graph_stats.status_code == 200 and graph_stats.json()["total_entities"] > 0, graph_stats.text

        expanded = await _graph_only_search(client, corpus_id, top_k=None)
        exp_matches = expanded["matches"]
        exp_debug = expanded["debug"]["fusion_per_corpus"][corpus_id]
        assert exp_debug["fusion_graph_mode"] == "chunk"
        assert int(exp_debug["fusion_graph_entity_expansion_hits"]) > 0, exp_debug
        rows = await pg.list_chunks_for_repo(corpus_id, limit=None)
        content_by_id = {str(row.chunk_id): row.content for row in rows}
        assert all(m["chunk_id"] in content_by_id and m["content"] == content_by_id[m["chunk_id"]] for m in exp_matches)
        assert len({m["chunk_id"] for m in exp_matches}) > 5, "entity expansion must add chunks beyond the 5 vector seeds"

        # --- entity mode: entities matched by the query text, hydrated to their chunks by chunk_id.
        cfg.graph_search.mode = "entity"
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None
        entity_payload = await _graph_only_search(client, corpus_id, top_k=8)
        ent_matches = entity_payload["matches"]
        ent_debug = entity_payload["debug"]["fusion_per_corpus"][corpus_id]
        assert ent_debug["fusion_graph_mode"] == "entity"
        assert ent_matches, entity_payload
        assert all(m["source"] == "graph" for m in ent_matches)
        assert all(m["chunk_id"] in content_by_id and m["content"] == content_by_id[m["chunk_id"]] for m in ent_matches)
        assert 1 <= int(ent_debug["fusion_graph_hydrated_chunks"]) <= len(ent_matches)
        assert chunk_mode_ids & {m["chunk_id"] for m in ent_matches}, "the calibration chunk is reachable in both modes"
    finally:
        config_store._store = None
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        try:
            await pg.disconnect()
        except Exception:
            pass
