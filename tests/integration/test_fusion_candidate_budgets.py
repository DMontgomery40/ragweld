"""Candidate budgets remain independent of response limits across real stores."""

from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.indexing.generations import build_generation, staging_repo_id
from server.models.index import Chunk
from server.retrieval.contracts import sparse_contract_from_config
from server.retrieval.fusion import TriBridFusion
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.requires_postgres,
    pytest.mark.requires_qdrant,
    pytest.mark.requires_neo4j,
]


@pytest.mark.parametrize(
    ("requested", "returned", "dense", "sparse", "graph"),
    [(1, 1, 10, 11, 5), (15, 15, 15, 15, 15), (None, 3, 10, 11, 5)],
)
async def test_response_limit_preserves_each_configured_candidate_pool(
    requested: int | None, returned: int, dense: int, sparse: int, graph: int,
) -> None:
    """A small output limit must not discard candidates before fusion/reranking."""
    cfg = load_config()
    cfg.embedding.embedding_backend = "deterministic"
    cfg.embedding.embedding_cache_enabled = False
    cfg.vector_search.top_k = 10
    cfg.sparse_search.top_k = 11
    cfg.graph_search.top_k = 5
    cfg.graph_search.chunk_neighbor_window = 0
    cfg.vector_search.enabled = cfg.sparse_search.enabled = cfg.graph_search.enabled = True
    cfg.reranking.reranker_mode = "none"
    cfg.semantic_cache.enabled = False
    cfg.retrieval.final_k = 3
    cfg.retrieval.neighbor_window = 0
    cfg.retrieval.enable_mmr = False
    cfg.vector_search.similarity_threshold = 0
    cfg.retrieval.min_score_vector = cfg.retrieval.min_score_sparse = cfg.retrieval.min_score_graph = 0
    cid = f"pytest_candidate_budget_{uuid4().hex}"
    graph_id = staging_repo_id(cid, uuid4().hex)
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    qdrant = QdrantChunkStore(cfg)
    neo = AsyncGraphDatabase.driver(
        require_env("NEO4J_URI"),
        auth=(require_env("NEO4J_USER"), require_env("NEO4J_PASSWORD")),
    )
    try:
        await pg.connect()
        await pg.upsert_corpus(cid, name=cid, root_path=".")
        await pg.upsert_corpus_config_json(cid, cfg.model_dump(mode="json"))
        embedder = Embedder(cfg.embedding, cfg.tokenization)
        chunks = await embedder.embed_chunks([
            Chunk(
                chunk_id=f"budget-{i}", file_path=f"notes/{i}.md",
                content=f"Salinity sensor calibration record number {i}.",
                start_line=1, end_line=1, language="markdown", token_count=7,
            )
            for i in range(30)
        ])
        await pg.upsert_chunks(cid, chunks)
        await pg.update_corpus_embedding_meta(
            cid, backend="deterministic", provider=cfg.embedding.embedding_type,
            model=cfg.embedding.effective_model, dimensions=embedder.dim,
            sparse_contract=sparse_contract_from_config(cfg),
        )
        physical = await qdrant.create_generation(cid, embedding_dim=embedder.dim)
        await qdrant.write_chunks(cid, physical, chunks, embedding_dim=embedder.dim, graph_repo_id=graph_id)
        manifest = build_generation(run_id=uuid4().hex, qdrant_collection=physical, graph_repo_id=graph_id)
        await pg.update_corpus_meta(cid, {"generation": manifest.model_dump(mode="json")})
        # One real shared entity makes non-seed chunks reachable by traversal.
        await neo.execute_query(
            "CREATE (e:__Entity__ {repo_id: $repo_id, entity_id: $repo_id}) "
            "WITH e UNWIND $chunks AS chunk_id "
            "CREATE (c:Chunk {repo_id: $repo_id, chunk_id: chunk_id, "
            "graphJoinId: $repo_id + ':' + chunk_id}) "
            "CREATE (e)-[:FROM_CHUNK {repo_id: $repo_id}]->(c)",
            parameters_={"repo_id": graph_id, "chunks": [chunk.chunk_id for chunk in chunks]},
            database_=cfg.graph_storage.resolve_database(cid),
        )
        fusion = TriBridFusion()
        result = await fusion.search(
            corpus_id=cid, query="Salinity sensor calibration", config=cfg.fusion,
            top_k=requested, cache_mode="bypass",
        )
        assert len(result) == returned
        assert fusion.last_debug["fusion_vector_results"] == dense
        assert fusion.last_debug["fusion_sparse_results"] == sparse
        assert fusion.last_debug["fusion_graph_qdrant_seed_chunks"] == graph
        assert fusion.last_debug["fusion_graph_hydrated_chunks"] == graph
    finally:
        try:
            await neo.execute_query(
                "MATCH (n {repo_id: $repo_id}) DETACH DELETE n",
                parameters_={"repo_id": graph_id},
                database_=cfg.graph_storage.resolve_database(cid),
            )
        finally:
            await neo.close()
            await qdrant.delete_corpus(cid)
            await pg.delete_corpus_with_data(cid)
            await pg.disconnect()
            if config_store._store is not None:
                config_store._store.clear_cache(cid)
