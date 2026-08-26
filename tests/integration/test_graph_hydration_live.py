"""Graph-leg hydration modes against the real stores (no fake Postgres/Neo4j/Embedder).

Replaces the three monkeypatched unit tests that used to cover chunk-mode
hydration, chunk-mode entity expansion and entity-mode hydration. The graph
is seeded once per module the way production seeds it: a real index run over
the acceptance corpus with the lexical graph + chunk vector index on and (when
the gateway serves the cheap alias) the semantic knowledge graph extracted
through it. Each test then flips only search-time graph settings.

Both neighbor windows are zero for the whole module so every hit on the final
list is one the graph leg itself hydrated. The reference ranking is the Qdrant
dense leg over the corpus-isolated collection (exact below Qdrant's full-scan
threshold, same deterministic vectors). Neo4j's chunk vector index is shared by
every corpus of the same dimension and over-fetches a global top-N before
filtering by corpus, so the graph leg may return FEWER seeds than requested;
what it returns must be a subset of the corpus's exact top-k, never a chunk
outside it.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.gateway_catalog import warm_gateway_catalog
from server.indexing.embedder import Embedder
from server.main import app
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
_SEED_K = 5  # graph_search.top_k floor: the number of vector seeds in chunk mode


@dataclass(frozen=True)
class SeededGraph:
    corpus_id: str
    content_by_id: dict[str, str]
    vector_seed_ids: list[str]  # the Qdrant dense leg's top-_SEED_K chunk ids for _QUESTION
    kg_skip: str | None  # None when the semantic knowledge graph was extracted


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
            response = await probe.get(
                f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {key}"}
            )
    except Exception as exc:
        return f"LiteLLM gateway not reachable at {base_url}: {exc}"
    if response.status_code != 200:
        return f"LiteLLM gateway answered HTTP {response.status_code}"
    served = {str(item.get("id")) for item in (response.json().get("data") or [])}
    return None if model in served else f"gateway does not serve {model}"


async def _search(
    client: AsyncClient, corpus_id: str, *, leg: str, top_k: int | None = _SEED_K
) -> dict:
    # A request top_k caps BOTH the graph seeds and the final list; pass None to
    # let graph_search.top_k seed and retrieval.final_k cap.
    res = await client.post(
        "/api/search",
        json={
            "query": _QUESTION,
            "corpus_id": corpus_id,
            **({"top_k": top_k} if top_k is not None else {}),
            "include_vector": leg == "vector",
            "include_sparse": False,
            "include_graph": leg == "graph",
            "cache_mode": "bypass",
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _set_graph_mode(
    pg: PostgresClient,
    corpus_id: str,
    *,
    mode: str,
    entity_expansion: bool,
    seed_overfetch_multiplier: int = 10,
) -> None:
    cfg = await config_store.get_config(repo_id=corpus_id)
    cfg.graph_search.mode = mode
    cfg.graph_search.chunk_entity_expansion_enabled = entity_expansion
    # Neo4j's chunk vector index is shared by every corpus of the same dimension:
    # the leg takes the global top-(k x multiplier) and keeps this corpus's chunks.
    cfg.graph_search.chunk_seed_overfetch_multiplier = seed_overfetch_multiplier
    await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
    config_store._store = None


@pytest_asyncio.fixture(scope="module")
async def seeded() -> AsyncIterator[SeededGraph]:
    corpus_id = f"graph-hydrate-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    cfg = load_config()
    kg_skip = await _gateway_serves(str(cfg.chat.litellm.base_url), _KG_MODEL)
    # ASGITransport does not run the lifespan: warm the gateway catalog the way
    # the shared client fixture does, or semantic-KG route resolution has no catalog.
    await asyncio.to_thread(warm_gateway_catalog)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            await pg.connect()
            created = await client.post(
                "/api/corpora",
                json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
            )
            assert created.status_code in (200, 201), created.text

            cfg.embedding.embedding_backend = "deterministic"
            # Small chunks so the four-file fixture yields well over five chunks and
            # the vector seeds (top_k floor is 5) leave room for entity expansion.
            cfg.chunking.chunking_strategy = (
                "fixed_chars"  # the default `ast` falls back to the greedy target on prose
            )
            cfg.chunking.chunk_size = 200
            cfg.chunking.chunk_overlap = 0
            cfg.vector_search.enabled = True
            cfg.sparse_search.enabled = True
            cfg.graph_search.enabled = True
            cfg.graph_search.mode = "chunk"
            cfg.graph_search.chunk_entity_expansion_enabled = False
            cfg.graph_search.top_k = _SEED_K
            cfg.graph_search.chunk_neighbor_window = (
                0  # no NEXT_CHUNK padding: hits are seeds (or expansion)
            )
            cfg.retrieval.neighbor_window = 0  # no ordinal padding after the leg
            cfg.retrieval.final_k = 12
            cfg.graph_indexing.enabled = True
            cfg.graph_indexing.build_lexical_graph = True
            cfg.graph_indexing.store_chunk_embeddings = True
            cfg.graph_indexing.semantic_kg_enabled = kg_skip is None
            if kg_skip is None:
                cfg.graph_indexing.semantic_kg_mode = "llm"
                cfg.graph_indexing.semantic_kg_llm_model = _KG_MODEL
                # The seed must be real: a failed extraction fails the run, never an empty graph.
                cfg.graph_indexing.semantic_kg_require_llm_success = True
            cfg.chat.litellm.enabled = kg_skip is None
            cfg.reranking.reranker_mode = "none"
            cfg.semantic_cache.enabled = 0
            await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
            config_store._store = None

            started = await client.post(
                "/api/index",
                json={
                    "corpus_id": corpus_id,
                    "repo_path": str(_CORPUS_PATH),
                    "force_reindex": True,
                },
            )
            assert started.status_code == 200, started.text
            final = await _wait_for_index(client, corpus_id)
            assert final["status"] == "complete", final
            if kg_skip is None:
                graph_stats = await client.get(f"/api/graph/{corpus_id}/stats")
                assert (
                    graph_stats.status_code == 200 and graph_stats.json()["total_entities"] > 0
                ), graph_stats.text

            rows = await pg.list_chunks_for_repo(corpus_id, limit=None)
            content_by_id = {str(row.chunk_id): row.content for row in rows}
            assert len(content_by_id) > _SEED_K, (
                f"fixture must chunk into more than five rows, got {len(content_by_id)}"
            )

            # The reference seeds: the Qdrant dense leg over the same deterministic
            # vectors, capped at the graph seed count.
            vector = await _search(client, corpus_id, leg="vector")
            vector_seed_ids = [m["chunk_id"] for m in vector["matches"]]
            assert len(vector_seed_ids) == _SEED_K and all(
                m["source"] == "vector" for m in vector["matches"]
            ), vector

            yield SeededGraph(
                corpus_id=corpus_id,
                content_by_id=content_by_id,
                vector_seed_ids=vector_seed_ids,
                kg_skip=kg_skip,
            )
        finally:
            config_store._store = None
            await client.delete(f"/api/index/{corpus_id}")
            await client.delete(f"/api/corpora/{corpus_id}")
            try:
                await pg.disconnect()
            except Exception:
                pass


def _assert_hydrated_from_postgres(matches: list[dict], seeded: SeededGraph) -> None:
    # Hydration by chunk_id: every hit is a real Postgres row carrying that row's content.
    assert matches
    assert all(m["source"] == "graph" for m in matches)
    assert all(m["chunk_id"] in seeded.content_by_id for m in matches), [
        m["chunk_id"] for m in matches
    ]
    assert all(m["content"] == seeded.content_by_id[m["chunk_id"]] for m in matches)


async def test_chunk_mode_hydrates_exactly_the_vector_seeds(
    client: AsyncClient, seeded: SeededGraph
) -> None:
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        # Multiplier 1: the global top-k filtered to this corpus can only be a subset
        # of the corpus's own exact top-k (the oracle below).
        await _set_graph_mode(
            pg, seeded.corpus_id, mode="chunk", entity_expansion=False, seed_overfetch_multiplier=1
        )
        payload = await _search(client, seeded.corpus_id, leg="graph")
        matches = payload["matches"]
        debug = payload["debug"]["fusion_per_corpus"][seeded.corpus_id]
        _assert_hydrated_from_postgres(matches, seeded)
        assert any("calibrat" in m["content"].lower() for m in matches)
        assert debug["fusion_graph_mode"] == "chunk"
        assert int(debug["fusion_graph_entity_expansion_hits"]) == 0
        # With both neighbor windows at zero the leg's hydrated hits ARE the final list ...
        assert int(debug["fusion_graph_hydrated_chunks"]) == len(matches), debug
        assert 1 <= len(matches) <= _SEED_K, [m["chunk_id"] for m in matches]
        # ... and they are exactly the seeds the same engine returns for the same
        # query: Neo4j's chunk vector index on the manifest's graph id, same top-k,
        # same overfetch, same neighbor window (a same-engine oracle; ANN order and
        # cross-engine rankings are not invariants, this is).
        scoped = await config_store.get_config(repo_id=seeded.corpus_id)
        query_vector = await Embedder(scoped.embedding, scoped.tokenization).embed(_QUESTION)
        graph_id = (await pg.get_generation(seeded.corpus_id)).graph_repo_id
        assert graph_id
        neo4j = Neo4jClient(
            scoped.graph_storage.neo4j_uri,
            scoped.graph_storage.neo4j_user,
            scoped.graph_storage.resolve_password(),
            database=scoped.graph_storage.resolve_database(seeded.corpus_id),
        )
        await neo4j.connect()
        try:
            direct = await neo4j.chunk_vector_search(
                graph_id,
                query_vector,
                index_name=scoped.graph_indexing.chunk_vector_index_name,
                top_k=_SEED_K,
                neighbor_window=0,
                overfetch_multiplier=1,
            )
        finally:
            await neo4j.disconnect()
        direct_ids = {chunk_id for chunk_id, _score in direct}
        hit_ids = {m["chunk_id"] for m in matches}
        assert direct_ids, "the same-engine oracle returned no seeds"
        assert hit_ids == direct_ids, (sorted(hit_ids), sorted(direct_ids))
        # With the multiplier at 1 the global top-k filtered to this corpus can only be a
        # subset of the corpus's own exact top-k (Qdrant dense leg): a second, engine-
        # independent bound on the same hits.
        assert hit_ids <= set(seeded.vector_seed_ids), (sorted(hit_ids), seeded.vector_seed_ids)
        # The corpus's own dense ranking (Qdrant) is exact on this small collection:
        # every graph seed is one of its chunks (never a chunk outside the corpus).
        assert hit_ids <= set(seeded.content_by_id)
    finally:
        await pg.disconnect()


async def test_chunk_mode_entity_expansion_adds_chunks_beyond_the_seeds(
    client: AsyncClient, seeded: SeededGraph
) -> None:
    if seeded.kg_skip:
        pytest.skip(f"entity expansion needs the semantic KG through the gateway: {seeded.kg_skip}")
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        await _set_graph_mode(pg, seeded.corpus_id, mode="chunk", entity_expansion=True)
        payload = await _search(client, seeded.corpus_id, leg="graph", top_k=None)
        matches = payload["matches"]
        debug = payload["debug"]["fusion_per_corpus"][seeded.corpus_id]
        _assert_hydrated_from_postgres(matches, seeded)
        assert debug["fusion_graph_mode"] == "chunk"
        assert int(debug["fusion_graph_entity_expansion_hits"]) > 0, debug
        ids = {m["chunk_id"] for m in matches}
        # Entities extracted by the semantic KG add chunks reachable through IN_CHUNK
        # links on top of the vector seeds; nothing else pads the list, so the leg's
        # hydrated count is the whole list. The baseline is the SAME engine with
        # expansion off (Neo4j seeds for this query on the manifest graph): at least
        # one final chunk must lie outside it.
        assert int(debug["fusion_graph_hydrated_chunks"]) == len(matches), debug
        scoped = await config_store.get_config(repo_id=seeded.corpus_id)
        query_vector = await Embedder(scoped.embedding, scoped.tokenization).embed(_QUESTION)
        graph_id = (await pg.get_generation(seeded.corpus_id)).graph_repo_id
        neo4j = Neo4jClient(
            scoped.graph_storage.neo4j_uri,
            scoped.graph_storage.neo4j_user,
            scoped.graph_storage.resolve_password(),
            database=scoped.graph_storage.resolve_database(seeded.corpus_id),
        )
        await neo4j.connect()
        try:
            baseline = await neo4j.chunk_vector_search(
                graph_id,
                query_vector,
                index_name=scoped.graph_indexing.chunk_vector_index_name,
                top_k=scoped.graph_search.top_k,
                neighbor_window=0,
                overfetch_multiplier=scoped.graph_search.chunk_seed_overfetch_multiplier,
            )
        finally:
            await neo4j.disconnect()
        baseline_ids = {chunk_id for chunk_id, _score in baseline}
        assert baseline_ids, "the same-engine baseline returned no seeds"
        assert ids & baseline_ids, (sorted(ids), sorted(baseline_ids))
        assert ids - baseline_ids, (
            "expansion must add at least one chunk outside the same-engine seeds"
        )
    finally:
        await pg.disconnect()


async def test_entity_mode_hydrates_the_matched_entities_chunks(
    client: AsyncClient, seeded: SeededGraph
) -> None:
    if seeded.kg_skip:
        pytest.skip(f"entity mode needs the semantic KG through the gateway: {seeded.kg_skip}")
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        await _set_graph_mode(pg, seeded.corpus_id, mode="entity", entity_expansion=False)
        payload = await _search(client, seeded.corpus_id, leg="graph", top_k=8)
        matches = payload["matches"]
        debug = payload["debug"]["fusion_per_corpus"][seeded.corpus_id]
        _assert_hydrated_from_postgres(matches, seeded)
        assert debug["fusion_graph_mode"] == "entity"
        # Entities matched by the question text hydrate to their chunks by chunk_id;
        # the calibration chunk is reachable through entities as it is through vectors.
        assert int(debug["fusion_graph_hydrated_chunks"]) == len(matches), debug
        assert {m["chunk_id"] for m in matches} & set(seeded.vector_seed_ids), (
            [m["chunk_id"] for m in matches],
            seeded.vector_seed_ids,
        )
    finally:
        await pg.disconnect()
