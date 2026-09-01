"""Live generation isolation and Postgres hydration for Qdrant-seeded GraphRAG."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from neo4j import GraphDatabase
from neo4j_graphrag.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.indexing.generations import build_generation
from server.indexing.graphrag_pipeline import ScopedNeo4jWriter
from server.indexing.official_graphrag import write_lexical_graph_with_graphrag
from server.main import app
from server.models.index import Chunk
from server.retrieval.contracts import sparse_contract_from_config
from server.retrieval.graphrag_retriever import retrieve_graph_chunks
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_QUESTION = "How was Apollo guidance computer software led by Margaret Hamilton?"


def _chunks(*, generation: str) -> list[Chunk]:
    return [
        Chunk(
            chunk_id="shared-seed",
            content=f"{generation} seed about the Apollo guidance computer",
            file_path="apollo.md",
            start_line=1,
            end_line=2,
            token_count=7,
            embedding=[1.0, 0.0, 0.0, 0.0],
            metadata={"chunk_ordinal": 0},
        ),
        Chunk(
            chunk_id="shared-related",
            content=f"{generation} related fact about Margaret Hamilton",
            file_path="apollo.md",
            start_line=3,
            end_line=4,
            token_count=7,
            embedding=[0.0, 1.0, 0.0, 0.0],
            metadata={"chunk_ordinal": 1},
        ),
    ]


async def _write_generation_graph(
    *, driver, database: str, repo_id: str, run_id: str, entity_prefix: str, chunks: list[Chunk]
) -> None:
    lexical, lexical_config = await write_lexical_graph_with_graphrag(
        repo_id=repo_id, run_id=run_id, file_path="apollo.md", chunks=chunks
    )
    seed_entity = f"{entity_prefix}-guidance"
    related_entity = f"{entity_prefix}-hamilton"
    graph = Neo4jGraph(
        nodes=[
            *lexical.nodes,
            Neo4jNode(id=seed_entity, label="Concept", properties={"name": seed_entity}),
            Neo4jNode(id=related_entity, label="Person", properties={"name": related_entity}),
        ],
        relationships=[
            *lexical.relationships,
            Neo4jRelationship(
                start_node_id=seed_entity, end_node_id="shared-seed", type="FROM_CHUNK"
            ),
            Neo4jRelationship(
                start_node_id=related_entity, end_node_id="shared-related", type="FROM_CHUNK"
            ),
            Neo4jRelationship(
                start_node_id=seed_entity,
                end_node_id=related_entity,
                type="ASSOCIATED_WITH",
            ),
        ],
    )
    writer = ScopedNeo4jWriter(
        driver=driver,
        neo4j_database=database,
        repo_id=repo_id,
        run_id=run_id,
    )
    await writer.run(graph, lexical_config)


async def test_manifest_collection_and_graph_prevent_raw_chunk_id_collisions() -> None:
    cfg = load_config()
    corpus_id = f"graph-hydrate-{uuid4().hex[:8]}"
    retired_run = uuid4().hex
    active_run = uuid4().hex
    retired_graph = f"__staging__{corpus_id}__{retired_run}"
    active_graph = f"__staging__{corpus_id}__{active_run}"
    cfg.embedding.embedding_backend = "deterministic"
    cfg.embedding.embedding_dim = 128
    cfg.graph_search.enabled = True
    cfg.graph_search.max_hops = 1
    cfg.graph_search.chunk_neighbor_window = 0
    cfg.vector_search.enabled = True
    cfg.sparse_search.enabled = False
    cfg.reranking.reranker_mode = "none"
    cfg.semantic_cache.enabled = False
    query_vector = await Embedder(cfg.embedding, cfg.tokenization).embed(_QUESTION)
    embedding_dim = len(query_vector)
    inverse_vector = [-value for value in query_vector]
    retired_chunks = [
        chunk.model_copy(update={"embedding": query_vector if index == 0 else inverse_vector})
        for index, chunk in enumerate(_chunks(generation="retired"))
    ]
    active_chunks = [
        chunk.model_copy(update={"embedding": query_vector if index == 0 else inverse_vector})
        for index, chunk in enumerate(_chunks(generation="active"))
    ]
    qdrant = QdrantChunkStore(cfg)
    postgres = PostgresClient(require_env("POSTGRES_DSN"))
    database = cfg.graph_storage.resolve_database(corpus_id)
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        auth=(
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        ),
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
        await postgres.upsert_corpus_config_json(
            corpus_id, cfg.model_dump(mode="serialization")
        )
        await postgres.update_corpus_embedding_meta(
            corpus_id,
            backend=cfg.embedding.embedding_backend,
            provider=cfg.embedding.embedding_type,
            model=cfg.embedding.effective_model,
            dimensions=embedding_dim,
            sparse_contract=sparse_contract_from_config(cfg),
        )
        config_store._store = None
        retired_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=embedding_dim
        )
        active_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=embedding_dim
        )
        await qdrant.write_chunks(
            corpus_id,
            retired_collection,
            retired_chunks,
            embedding_dim=embedding_dim,
            graph_repo_id=retired_graph,
        )
        await qdrant.write_chunks(
            corpus_id,
            active_collection,
            active_chunks,
            embedding_dim=embedding_dim,
            graph_repo_id=active_graph,
        )
        await _write_generation_graph(
            driver=driver,
            database=database,
            repo_id=retired_graph,
            run_id=retired_run,
            entity_prefix="retired",
            chunks=retired_chunks,
        )
        await _write_generation_graph(
            driver=driver,
            database=database,
            repo_id=active_graph,
            run_id=active_run,
            entity_prefix="active",
            chunks=active_chunks,
        )
        await postgres.upsert_chunks(corpus_id, active_chunks)

        retired_manifest = build_generation(
            run_id=retired_run,
            qdrant_collection=retired_collection,
            graph_repo_id=retired_graph,
        )
        active_manifest = build_generation(
            run_id=active_run,
            qdrant_collection=active_collection,
            graph_repo_id=active_graph,
            previous=retired_manifest,
        )
        await postgres.set_generation(corpus_id, active_manifest)
        persisted = await postgres.get_generation(corpus_id)
        assert persisted == active_manifest
        assert {(entry.qdrant_collection, entry.graph_repo_id) for entry in persisted.retired} == {
            (retired_collection, retired_graph)
        }

        qdrant_seeds = await qdrant.vector_search(
            corpus_id, query_vector, 1, physical=active_collection
        )
        seed_ids = {match.chunk_id for match in qdrant_seeds}
        assert seed_ids == {"shared-seed"}

        call = dict(
            neo4j_uri=cfg.graph_storage.neo4j_uri,
            neo4j_user=cfg.graph_storage.neo4j_user,
            neo4j_password=cfg.graph_storage.resolve_password(),
            neo4j_database=database,
            qdrant_url=qdrant.url,
            collection_name=active_collection,
            graph_repo_id=active_graph,
            query_vector=query_vector,
            top_k=1,
            max_hops=1,
            neighbor_window=0,
        )
        first = await retrieve_graph_chunks(**call)
        second = await retrieve_graph_chunks(**{**call, "neighbor_window": 1})
        assert first == second
        assert first.qdrant_seed_chunks == 1
        assert first.relationship_expansion_hits == 1
        assert {chunk_id for chunk_id, _score in first.chunk_scores}.isdisjoint(seed_ids)
        assert [chunk_id for chunk_id, _score in first.chunk_scores] == ["shared-related"]
        assert set(first.resolved_entity_ids) == {
            "active-guidance",
            "active-hamilton",
        }
        assert all(
            not entity_id.startswith("retired-")
            for entity_id in first.resolved_entity_ids
        )

        hydrated = await postgres.get_chunks(
            corpus_id, [chunk_id for chunk_id, _score in first.chunk_scores]
        )
        assert [(chunk.chunk_id, chunk.content) for chunk in hydrated] == [
            ("shared-related", "active related fact about Margaret Hamilton")
        ]

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/search",
                json={
                    "query": _QUESTION,
                    "corpus_id": corpus_id,
                    "top_k": 1,
                    "include_vector": False,
                    "include_sparse": False,
                    "include_graph": True,
                    "cache_mode": "bypass",
                },
            )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [match["chunk_id"] for match in payload["matches"]] == ["shared-related"]
        debug = payload["debug"]
        assert "fusion_graph_entity_hits" not in debug
        assert debug["fusion_graph_qdrant_seed_chunks"] == 1
        assert debug["fusion_graph_resolved_entities"] == 2
        assert debug["fusion_graph_relationship_expansion_hits"] == 1
        assert debug["fusion_graph_community_expansion_hits"] == 0
        assert debug["fusion_graph_hydrated_chunks"] == 1
    finally:
        config_store._store = None
        await qdrant.delete_corpus(corpus_id)
        for graph_id in (active_graph, retired_graph):
            await neo4j.delete_graph(graph_id)
        await postgres.delete_corpus_with_data(corpus_id)
        await neo4j.disconnect()
        await postgres.disconnect()
        await asyncio.to_thread(driver.close)
