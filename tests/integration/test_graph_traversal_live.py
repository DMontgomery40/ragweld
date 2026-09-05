"""Live traversal semantics of the Qdrant-seeded GraphRAG leg.

Seeds a small Epstein-flights graph: a hub entity co-mentioned in a chunk with an
entity the extractor never linked to it, TWO entities it really is linked to (more
than the cap under test), and a second seed entity the extractor linked to nothing.
A chunk co-mention must not act as a traversal hop, extracted relationships must,
``graph_search.max_related_entities_per_seed`` must admit exactly that many entities
BESIDES the seed, and every seed entity -- including the one with no semantic edges
at all -- must still contribute its own chunks. Proven through the retriever and
through ``/api/search``.
"""

from __future__ import annotations

import asyncio
import math
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from neo4j import Driver, GraphDatabase
from neo4j_graphrag.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.indexing.generations import build_generation
from server.indexing.graphrag_pipeline import ScopedNeo4jWriter
from server.main import app
from server.models.index import Chunk, ChunkProvenance
from server.retrieval.contracts import sparse_contract_from_config
from server.retrieval.graphrag_retriever import GraphTraversalResult, retrieve_graph_chunks
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.official_graphrag import write_lexical_graph_with_graphrag
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_QUESTION = "Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?"
_FILE = "epstein-flights.md"

HUB = "jeffrey-epstein"
RELATED = "barry-cohen"
PILOT = "larry-visoski"
UNRELATED = "kathy-ruemmler"
# A second seed entity (named in the same seed chunk) that the extractor linked to no
# other entity: it has its own chunk and zero entity-to-entity edges.
LONE = "gulfstream-n212jm"

SEED = "flights-seed"
HUB_ONLY = "flights-hub-only"
SHARED = "flights-shared"
RELATED_CHUNK = "flights-related"
PILOT_CHUNK = "flights-pilot"
AIRCRAFT_CHUNK = "flights-aircraft"
UNRELATED_CHUNK = "flights-unrelated"
FILLER_A = "flights-filler-a"
FILLER_B = "flights-filler-b"
FILLER_C = "flights-filler-c"
FILLER_D = "flights-filler-d"
FILLER_E = "flights-filler-e"

# What the seed entities own outright (distance 0: the hub's two chunks and the lone
# entity's one), and the chunks reached through one extracted relationship each
# (distance 1). The hub is linked to more entities than the cap under test, which is
# what makes the cap observable; the lone entity is linked to none, which is what
# proves a seed with no semantic edges is not dropped from the expansion.
SEED_ENTITY_CHUNKS = (AIRCRAFT_CHUNK, HUB_ONLY, SHARED)
RELATED_ENTITY_CHUNKS = (PILOT_CHUNK, RELATED_CHUNK)
SEED_ENTITIES = (HUB, LONE)


def _chunk(chunk_id: str, content: str, ordinal: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        file_path=_FILE,
        start_line=ordinal * 2 + 1,
        end_line=ordinal * 2 + 2,
        token_count=12,
        embedding=[1.0, 0.0, 0.0, 0.0],
        metadata={"chunk_ordinal": ordinal},
        provenance=ChunkProvenance(extraction="direct"),
    )


def _chunks() -> list[Chunk]:
    return [
        _chunk(SEED, "Jeffrey Epstein asked plane management to arrange October 2017 flights.", 0),
        _chunk(HUB_ONLY, "Jeffrey Epstein confirmed the aircraft schedule with the pilots.", 1),
        _chunk(SHARED, "Jeffrey Epstein forwarded the itinerary to Kathy Ruemmler for review.", 2),
        _chunk(
            RELATED_CHUNK, "Barry Cohen was booked on the October 2017 flight to Palm Beach.", 3
        ),
        _chunk(UNRELATED_CHUNK, "Kathy Ruemmler summarised the legal memo separately.", 4),
        _chunk(
            FILLER_A, "Fuel receipts for the tail number were filed with the October invoices.", 5
        ),
        _chunk(FILLER_B, "The hangar lease renewal was signed the same month.", 6),
        _chunk(FILLER_C, "Catering for the flight was billed to the household account.", 7),
        _chunk(
            PILOT_CHUNK, "Larry Visoski flew the October 2017 leg to Palm Beach.", 8
        ),
        _chunk(
            AIRCRAFT_CHUNK,
            "The Gulfstream N212JM was released from maintenance before the October legs.",
            9,
        ),
        _chunk(FILLER_D, "De-icing was invoiced separately for the return leg.", 10),
        _chunk(FILLER_E, "The crew hotel folio was attached to the same October file.", 11),
    ]


def _embed(chunks: list[Chunk], query_vector: list[float]) -> list[Chunk]:
    """Seed matches the query exactly; fillers are near it; the rest point away."""
    inverse = [-value for value in query_vector]
    near = list(query_vector)
    near[0] = near[0] + 0.25
    near[1] = near[1] - 0.25
    by_id = {
        SEED: query_vector,
        FILLER_A: near,
        FILLER_B: near,
        FILLER_C: near,
        FILLER_D: near,
        FILLER_E: near,
    }
    return [
        chunk.model_copy(update={"embedding": by_id.get(chunk.chunk_id, inverse)})
        for chunk in chunks
    ]


async def _write_graph(
    *, driver: Driver, database: str, repo_id: str, run_id: str, chunks: list[Chunk]
) -> None:
    lexical, lexical_config = await write_lexical_graph_with_graphrag(
        repo_id=repo_id, run_id=run_id, file_path=_FILE, chunks=chunks
    )
    graph = Neo4jGraph(
        nodes=[
            *lexical.nodes,
            Neo4jNode(id=HUB, label="Person", properties={"name": "Jeffrey Epstein"}),
            Neo4jNode(id=RELATED, label="Person", properties={"name": "Barry Cohen"}),
            Neo4jNode(id=PILOT, label="Person", properties={"name": "Larry Visoski"}),
            Neo4jNode(id=LONE, label="Aircraft", properties={"name": "Gulfstream N212JM"}),
            Neo4jNode(id=UNRELATED, label="Person", properties={"name": "Kathy Ruemmler"}),
        ],
        relationships=[
            *lexical.relationships,
            Neo4jRelationship(start_node_id=HUB, end_node_id=SEED, type="FROM_CHUNK"),
            Neo4jRelationship(start_node_id=HUB, end_node_id=HUB_ONLY, type="FROM_CHUNK"),
            Neo4jRelationship(start_node_id=HUB, end_node_id=SHARED, type="FROM_CHUNK"),
            # Co-mentioned with the hub in SHARED, but the extractor linked nothing.
            Neo4jRelationship(start_node_id=UNRELATED, end_node_id=SHARED, type="FROM_CHUNK"),
            Neo4jRelationship(
                start_node_id=UNRELATED, end_node_id=UNRELATED_CHUNK, type="FROM_CHUNK"
            ),
            Neo4jRelationship(start_node_id=RELATED, end_node_id=RELATED_CHUNK, type="FROM_CHUNK"),
            Neo4jRelationship(start_node_id=PILOT, end_node_id=PILOT_CHUNK, type="FROM_CHUNK"),
            # A seed entity (named in the Qdrant-seeded chunk) with no entity-to-entity edge
            # anywhere: its own chunk is all it can contribute, and it must still contribute it.
            Neo4jRelationship(start_node_id=LONE, end_node_id=SEED, type="FROM_CHUNK"),
            Neo4jRelationship(start_node_id=LONE, end_node_id=AIRCRAFT_CHUNK, type="FROM_CHUNK"),
            # The extracted relationships: entity-to-entity hops. The hub has TWO, so a cap
            # of one must admit one of them -- not zero, and not both.
            Neo4jRelationship(start_node_id=HUB, end_node_id=RELATED, type="ARRANGED_FLIGHTS_FOR"),
            Neo4jRelationship(start_node_id=HUB, end_node_id=PILOT, type="FLOWN_BY"),
        ],
    )
    writer = ScopedNeo4jWriter(
        driver=driver,
        neo4j_database=database,
        repo_id=repo_id,
        run_id=run_id,
    )
    await writer.run(graph, lexical_config)


async def test_co_mention_is_not_a_hop_and_hub_expansion_is_capped() -> None:
    cfg = load_config()
    cfg.graph_storage.neo4j_uri = os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri)
    cfg.graph_storage.neo4j_user = os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user)
    corpus_id = f"pytest_graph_traversal_{uuid4().hex[:8]}"
    run_id = uuid4().hex
    graph_id = f"__staging__{corpus_id}__{run_id}"
    cfg.embedding.embedding_backend = "deterministic"
    cfg.embedding.embedding_dim = 128
    cfg.graph_search.enabled = True
    cfg.graph_search.max_hops = 2
    cfg.graph_search.chunk_neighbor_window = 0
    cfg.graph_search.max_related_entities_per_seed = 50
    # Result shaping by chunk ordinal would re-add neighbours of graph hits; keep the
    # API assertions about the graph leg alone. Every chunk here lives in one file, so the
    # per-file shaping cap (default 3) would trim the graph leg's own output before the
    # assertions could see it -- this test is about the traversal cap, not that one.
    cfg.retrieval.neighbor_window = 0
    cfg.retrieval.max_chunks_per_file = 10
    cfg.vector_search.enabled = True
    cfg.sparse_search.enabled = False
    cfg.reranking.reranker_mode = "none"
    cfg.semantic_cache.enabled = False
    query_vector = await Embedder(cfg.embedding, cfg.tokenization).embed(_QUESTION)
    embedding_dim = len(query_vector)
    chunks = _embed(_chunks(), query_vector)

    qdrant = QdrantChunkStore(cfg)
    postgres = PostgresClient(require_env("POSTGRES_DSN"))
    database = cfg.graph_storage.resolve_database(corpus_id)
    driver = GraphDatabase.driver(
        cfg.graph_storage.neo4j_uri,
        auth=(cfg.graph_storage.neo4j_user, cfg.graph_storage.resolve_password()),
    )
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.resolve_password(),
        database=database,
    )
    await postgres.connect()
    await neo4j.connect()
    try:
        await postgres.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
        await postgres.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        await postgres.update_corpus_embedding_meta(
            corpus_id,
            backend=cfg.embedding.embedding_backend,
            provider=cfg.embedding.embedding_type,
            model=cfg.embedding.effective_model,
            dimensions=embedding_dim,
            sparse_contract=sparse_contract_from_config(cfg),
        )
        config_store._store = None
        collection = await qdrant.create_generation(corpus_id, embedding_dim=embedding_dim)
        await qdrant.write_chunks(
            corpus_id, collection, chunks, embedding_dim=embedding_dim, graph_repo_id=graph_id
        )
        await _write_graph(
            driver=driver, database=database, repo_id=graph_id, run_id=run_id, chunks=chunks
        )
        await postgres.upsert_chunks(corpus_id, chunks)
        await postgres.set_generation(
            corpus_id,
            build_generation(run_id=run_id, qdrant_collection=collection, graph_repo_id=graph_id),
        )

        seeds = await qdrant.vector_search(corpus_id, query_vector, 6, physical=collection)
        assert {match.chunk_id for match in seeds} == {
            SEED,
            FILLER_A,
            FILLER_B,
            FILLER_C,
            FILLER_D,
            FILLER_E,
        }

        async def _traverse(max_related_entities_per_seed: int) -> GraphTraversalResult:
            return await retrieve_graph_chunks(
                neo4j_uri=cfg.graph_storage.neo4j_uri,
                neo4j_user=cfg.graph_storage.neo4j_user,
                neo4j_password=cfg.graph_storage.resolve_password(),
                neo4j_database=database,
                qdrant_url=qdrant.url,
                collection_name=collection,
                graph_repo_id=graph_id,
                query_vector=query_vector,
                top_k=6,
                max_hops=2,
                neighbor_window=0,
                max_related_entities_per_seed=max_related_entities_per_seed,
            )

        # Co-mention is not adjacency: both seed entities' own chunks and BOTH extracted
        # relationships' chunks come back, the co-mentioned entity's own chunk does not.
        open_expansion = await _traverse(50)
        assert open_expansion.qdrant_seed_chunks == 6
        assert [chunk_id for chunk_id, _score in open_expansion.chunk_scores] == [
            AIRCRAFT_CHUNK,
            HUB_ONLY,
            SHARED,
            PILOT_CHUNK,
            RELATED_CHUNK,
        ]
        scores = dict(open_expansion.chunk_scores)
        assert (
            scores[AIRCRAFT_CHUNK]
            == scores[HUB_ONLY]
            == scores[SHARED]
            == pytest.approx(1.0, abs=1e-6)
        )
        assert scores[PILOT_CHUNK] == scores[RELATED_CHUNK] == pytest.approx(0.5, abs=1e-6)
        assert set(open_expansion.resolved_entity_ids) == {HUB, LONE, RELATED, PILOT}
        assert UNRELATED not in open_expansion.resolved_entity_ids

        # The cap counts RELATED entities: with the hub linked to two of them, a cap of one
        # admits exactly one, and the seed entity's own chunks (distance 0) still come back.
        # The cap used to be applied to a row set that included the seed's own distance-0 row,
        # so a cap of one admitted ZERO related entities and the hub answered alone.
        for cap in (1, 2):
            capped = await _traverse(cap)
            capped_ids = [chunk_id for chunk_id, _score in capped.chunk_scores]
            # Every seed entity keeps its own chunks -- the hub's two AND the lone entity's
            # one, which is the whole contribution of a seed the extractor linked to nothing.
            assert set(SEED_ENTITY_CHUNKS) <= set(capped_ids), capped_ids
            assert len([c for c in capped_ids if c in RELATED_ENTITY_CHUNKS]) == cap, capped_ids
            assert len(capped_ids) == len(SEED_ENTITY_CHUNKS) + cap
            # Both seed entities + exactly `cap` related ones, and never the co-mentioned one.
            assert set(SEED_ENTITIES) <= set(capped.resolved_entity_ids)
            assert len(capped.resolved_entity_ids) == len(SEED_ENTITIES) + cap, (
                capped.resolved_entity_ids
            )
            assert UNRELATED not in capped.resolved_entity_ids

        # The typed tunable reaches the traversal through the corpus config.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for cap in (1, 2):
                cfg.graph_search.max_related_entities_per_seed = cap
                await postgres.upsert_corpus_config_json(
                    corpus_id, cfg.model_dump(mode="serialization")
                )
                config_store._store = None
                response = await client.post(
                    "/api/search",
                    json={
                        "query": _QUESTION,
                        "corpus_id": corpus_id,
                        "top_k": 6,
                        "include_vector": False,
                        "include_sparse": False,
                        "include_graph": True,
                        "cache_mode": "bypass",
                    },
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                matched = [match["chunk_id"] for match in payload["matches"]]
                assert set(SEED_ENTITY_CHUNKS) <= set(matched), (cap, matched)
                assert len([c for c in matched if c in RELATED_ENTITY_CHUNKS]) == cap, (cap, matched)
                assert len(matched) == len(SEED_ENTITY_CHUNKS) + cap, (cap, matched)
                assert all(match["source"] == "graph" for match in payload["matches"])
                debug = payload["debug"]
                assert debug["fusion_graph_qdrant_seed_chunks"] == 6
                assert debug["fusion_graph_resolved_entities"] == len(SEED_ENTITIES) + cap
                assert debug["fusion_graph_relationship_expansion_hits"] == len(matched)
                assert debug["fusion_graph_hydrated_chunks"] == len(matched)
    finally:
        config_store._store = None
        await qdrant.delete_corpus(corpus_id)
        await neo4j.delete_graph(graph_id)
        await postgres.delete_corpus_with_data(corpus_id)
        await neo4j.disconnect()
        await postgres.disconnect()
        await asyncio.to_thread(driver.close)


async def test_equal_graph_evidence_uses_query_relevance_before_chunk_id() -> None:
    """A shared entity must not return an alphabetically fixed set for every query.

    Two nearby query vectors share the same seeds and graph evidence, but prefer
    different source chunks. Both direct traversal and API fusion must preserve
    that order, without reintroducing seeds as graph credit.
    """
    cfg = load_config()
    cid = f"pytest_graph_relevance_{uuid4().hex[:8]}"
    run_id = uuid4().hex
    graph_id = f"__staging__{cid}__{run_id}"
    cfg.embedding.embedding_backend = "deterministic"
    cfg.embedding.embedding_dim = 128
    cfg.graph_search.enabled = True
    cfg.graph_search.max_hops = 1
    cfg.graph_search.chunk_neighbor_window = 0
    cfg.retrieval.neighbor_window = 0
    cfg.retrieval.max_chunks_per_file = 10
    cfg.sparse_search.enabled = False
    cfg.reranking.reranker_mode = "none"
    cfg.semantic_cache.enabled = False
    question = "Which source explains the spacecraft guidance alarm?"
    query = await Embedder(cfg.embedding, cfg.tokenization).embed(question)
    norm = math.sqrt(sum(value * value for value in query))
    unit = [value / norm for value in query]
    # An exactly perpendicular direction, without a model or random fixture.
    axis = min(range(len(unit)), key=lambda i: abs(unit[i]))
    perpendicular = [-unit[axis] * value for value in unit]
    perpendicular[axis] += 1.0
    length = math.sqrt(sum(value * value for value in perpendicular))
    perpendicular = [value / length for value in perpendicular]

    def shifted(offset: float) -> list[float]:
        return [value + offset * noise for value, noise in zip(unit, perpendicular, strict=True)]

    vectors = {
        "seed": shifted(-0.1), "seed-filler": shifted(-0.11),
        "z-guidance": shifted(0.4), "a-propulsion": shifted(-0.6),
        "b-unrelated": shifted(2.0),
    }
    chunks = [
        _chunk(chunk_id, f"Synthetic source {chunk_id}.", i).model_copy(update={"embedding": vector})
        for i, (chunk_id, vector) in enumerate(vectors.items())
    ]
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    store = QdrantChunkStore(cfg)
    database = cfg.graph_storage.resolve_database(cid)
    driver = GraphDatabase.driver(cfg.graph_storage.neo4j_uri,
        auth=(cfg.graph_storage.neo4j_user, cfg.graph_storage.resolve_password()))
    neo4j = Neo4jClient(cfg.graph_storage.neo4j_uri, cfg.graph_storage.neo4j_user,
        cfg.graph_storage.resolve_password(), database=database)
    await pg.connect()
    await neo4j.connect()
    try:
        await pg.upsert_corpus(cid, name=cid, root_path=".")
        await pg.upsert_corpus_config_json(cid, cfg.model_dump(mode="serialization"))
        await pg.update_corpus_embedding_meta(cid, backend=cfg.embedding.embedding_backend,
            provider=cfg.embedding.embedding_type, model=cfg.embedding.effective_model,
            dimensions=len(query), sparse_contract=sparse_contract_from_config(cfg))
        config_store._store = None
        collection = await store.create_generation(cid, embedding_dim=len(query))
        await store.write_chunks(cid, collection, chunks, embedding_dim=len(query), graph_repo_id=graph_id)
        lexical, lexical_cfg = await write_lexical_graph_with_graphrag(
            repo_id=graph_id, run_id=run_id, file_path=_FILE, chunks=chunks)
        graph = Neo4jGraph(nodes=[*lexical.nodes, Neo4jNode(id="hub", label="Spacecraft", properties={"name":"Lander"})],
            relationships=[*lexical.relationships, *[
                Neo4jRelationship(start_node_id="hub", end_node_id=chunk.chunk_id, type="FROM_CHUNK")
                for chunk in chunks if chunk.chunk_id != "seed-filler"
            ]])
        await ScopedNeo4jWriter(driver=driver, neo4j_database=database,
            repo_id=graph_id, run_id=run_id).run(graph, lexical_cfg)
        await pg.upsert_chunks(cid, chunks)
        await pg.set_generation(cid, build_generation(run_id=run_id,
            qdrant_collection=collection, graph_repo_id=graph_id))

        for vector, expected in [(query, ["z-guidance", "a-propulsion"]),
                                 (shifted(-0.2), ["a-propulsion", "z-guidance"])]:
            seeds = await store.vector_search(cid, vector, 2, physical=collection)
            assert {chunk.chunk_id for chunk in seeds} == {"seed", "seed-filler"}
            result = await retrieve_graph_chunks(neo4j_uri=cfg.graph_storage.neo4j_uri,
                neo4j_user=cfg.graph_storage.neo4j_user,
                neo4j_password=cfg.graph_storage.resolve_password(), neo4j_database=database,
                qdrant_url=store.url, collection_name=collection, graph_repo_id=graph_id,
                query_vector=vector, top_k=2, max_hops=0, neighbor_window=0,
                max_related_entities_per_seed=1)
            assert [chunk_id for chunk_id, _ in result.chunk_scores] == expected
            assert result.chunk_scores[0][1] == result.chunk_scores[1][1]
            assert result.qdrant_seed_chunks == 2

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/search", json={"query":question, "corpus_id":cid,
                "top_k":2, "include_vector":False, "include_sparse":False,
                "include_graph":True, "cache_mode":"bypass"})
            assert response.status_code == 200, response.text
            assert [row["chunk_id"] for row in response.json()["matches"]] == ["z-guidance", "a-propulsion"]
    finally:
        config_store._store = None
        await store.delete_corpus(cid)
        await neo4j.delete_graph(graph_id)
        await pg.delete_corpus_with_data(cid)
        await neo4j.disconnect()
        await pg.disconnect()
        await asyncio.to_thread(driver.close)
