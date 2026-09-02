"""Live traversal semantics of the Qdrant-seeded GraphRAG leg.

Seeds a small Epstein-flights graph in which a hub entity is co-mentioned in a
chunk with an entity the extractor never linked to it. A chunk co-mention must
not act as a traversal hop, extracted relationships must, and
``graph_search.max_related_entities_per_seed`` must bound what each seed entity
pulls in, both through the retriever and through ``/api/search``.
"""

from __future__ import annotations

import asyncio
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
UNRELATED = "kathy-ruemmler"

SEED = "flights-seed"
HUB_ONLY = "flights-hub-only"
SHARED = "flights-shared"
RELATED_CHUNK = "flights-related"
UNRELATED_CHUNK = "flights-unrelated"
FILLER_A = "flights-filler-a"
FILLER_B = "flights-filler-b"
FILLER_C = "flights-filler-c"


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
    ]


def _embed(chunks: list[Chunk], query_vector: list[float]) -> list[Chunk]:
    """Seed matches the query exactly; fillers are near it; the rest point away."""
    inverse = [-value for value in query_vector]
    near = list(query_vector)
    near[0] = near[0] + 0.25
    near[1] = near[1] - 0.25
    by_id = {SEED: query_vector, FILLER_A: near, FILLER_B: near, FILLER_C: near}
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
            # The only extracted relationship: an entity-to-entity hop.
            Neo4jRelationship(start_node_id=HUB, end_node_id=RELATED, type="ARRANGED_FLIGHTS_FOR"),
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
    # API assertions about the graph leg alone.
    cfg.retrieval.neighbor_window = 0
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

        seeds = await qdrant.vector_search(corpus_id, query_vector, 4, physical=collection)
        assert {match.chunk_id for match in seeds} == {SEED, FILLER_A, FILLER_B, FILLER_C}

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
                top_k=4,
                max_hops=2,
                neighbor_window=0,
                max_related_entities_per_seed=max_related_entities_per_seed,
            )

        # Co-mention is not adjacency: the hub's chunks and the extracted
        # relationship's chunk come back, the co-mentioned entity's own chunk does not.
        open_expansion = await _traverse(50)
        assert open_expansion.qdrant_seed_chunks == 4
        assert [chunk_id for chunk_id, _score in open_expansion.chunk_scores] == [
            HUB_ONLY,
            SHARED,
            RELATED_CHUNK,
        ]
        scores = dict(open_expansion.chunk_scores)
        assert scores[HUB_ONLY] == scores[SHARED] == pytest.approx(1.0, abs=1e-6)
        assert scores[RELATED_CHUNK] == pytest.approx(0.5, abs=1e-6)
        assert open_expansion.resolved_entity_ids == (RELATED, HUB)
        assert UNRELATED not in open_expansion.resolved_entity_ids

        # The cap keeps the seed entity itself (distance 0) and drops the rest.
        capped = await _traverse(1)
        assert [chunk_id for chunk_id, _score in capped.chunk_scores] == [HUB_ONLY, SHARED]
        assert capped.resolved_entity_ids == (HUB,)

        # The typed tunable reaches the traversal through the corpus config.
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for cap, expected_chunks, expected_entities in (
                (1, [HUB_ONLY, SHARED], 1),
                (50, [HUB_ONLY, SHARED, RELATED_CHUNK], 2),
            ):
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
                        "top_k": 4,
                        "include_vector": False,
                        "include_sparse": False,
                        "include_graph": True,
                        "cache_mode": "bypass",
                    },
                )
                assert response.status_code == 200, response.text
                payload = response.json()
                assert [match["chunk_id"] for match in payload["matches"]] == expected_chunks
                assert all(match["source"] == "graph" for match in payload["matches"])
                debug = payload["debug"]
                assert debug["fusion_graph_qdrant_seed_chunks"] == 4
                assert debug["fusion_graph_resolved_entities"] == expected_entities
                assert debug["fusion_graph_relationship_expansion_hits"] == len(expected_chunks)
                assert debug["fusion_graph_hydrated_chunks"] == len(expected_chunks)
    finally:
        config_store._store = None
        await qdrant.delete_corpus(corpus_id)
        await neo4j.delete_graph(graph_id)
        await postgres.delete_corpus_with_data(corpus_id)
        await neo4j.disconnect()
        await postgres.disconnect()
        await asyncio.to_thread(driver.close)
