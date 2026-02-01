from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig
from server.observability.metrics import (
    GRAPH_LEG_LATENCY_SECONDS,
    SEARCH_GRAPH_HYDRATED_CHUNKS_COUNT,
    SEARCH_LEG_RESULTS_COUNT,
    SEARCH_RESULTS_FINAL_COUNT,
    SEARCH_STAGE_ERRORS_TOTAL,
    SEARCH_STAGE_LATENCY_SECONDS,
    SPARSE_LEG_LATENCY_SECONDS,
    VECTOR_LEG_LATENCY_SECONDS,
)
from server.services.config_store import get_config as load_scoped_config

if TYPE_CHECKING:
    from server.retrieval.graph import GraphRetriever
    from server.retrieval.sparse import SparseRetriever
    from server.retrieval.vector import VectorRetriever


class TriBridFusion:
    def __init__(self, vector: VectorRetriever | None, sparse: SparseRetriever | None, graph: GraphRetriever | None):
        self.vector = vector
        self.sparse = sparse
        self.graph = graph
        # Populated after each search() call; used by API layers to expose deterministic debug.
        self.last_debug: dict[str, Any] = {}

    async def search(
        self,
        corpus_id: str,
        query: str,
        config: FusionConfig,
        *,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        cfg = await load_scoped_config(repo_id=corpus_id)

        # Use real storage backends per corpus config.
        postgres = PostgresClient(cfg.indexing.postgres_url)
        await postgres.connect()

        embedder = Embedder(cfg.embedding)

        # Reuse query embeddings across legs when possible (vector + graph chunk-mode).
        q_emb: list[float] | None = None

        vector_results: list[ChunkMatch] = []
        sparse_results: list[ChunkMatch] = []
        graph_results: list[ChunkMatch] = []
        debug: dict[str, Any] = {
            "fusion_vector_requested": bool(include_vector),
            "fusion_sparse_requested": bool(include_sparse),
            "fusion_graph_requested": bool(include_graph),
            "fusion_vector_enabled": bool(cfg.vector_search.enabled),
            "fusion_sparse_enabled": bool(cfg.sparse_search.enabled),
            "fusion_graph_enabled": bool(cfg.graph_search.enabled),
            "fusion_vector_results": 0,
            "fusion_sparse_results": 0,
            "fusion_graph_entity_hits": 0,
            "fusion_graph_hydrated_chunks": 0,
            "fusion_graph_attempted": False,
            "fusion_graph_error": None,
            "fusion_graph_mode": str(getattr(cfg.graph_search, "mode", "entity")),
            "fusion_graph_entity_expansion_enabled": bool(getattr(cfg.graph_search, "chunk_entity_expansion_enabled", False)),
            "fusion_graph_entity_expansion_hits": 0,
        }

        # Run legs (request toggles + config.*.enabled)
        if include_vector and cfg.vector_search.enabled:
            with VECTOR_LEG_LATENCY_SECONDS.time():
                try:
                    if q_emb is None:
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="embed_query").time():
                            q_emb = await embedder.embed(query)
                    with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_vector_search").time():
                        vector_results = await postgres.vector_search(
                            corpus_id, q_emb, int(top_k or cfg.vector_search.top_k)
                        )
                except Exception:
                    SEARCH_STAGE_ERRORS_TOTAL.labels(stage="vector_leg").inc()
                    raise
                if cfg.vector_search.similarity_threshold > 0:
                    vector_results = [
                        r for r in vector_results if r.score >= cfg.vector_search.similarity_threshold
                    ]
        debug["fusion_vector_results"] = len(vector_results)
        SEARCH_LEG_RESULTS_COUNT.labels(leg="vector").observe(len(vector_results))

        if include_sparse and cfg.sparse_search.enabled:
            with SPARSE_LEG_LATENCY_SECONDS.time():
                try:
                    with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_sparse_search").time():
                        sparse_results = await postgres.sparse_search(
                            corpus_id,
                            query,
                            int(top_k or cfg.sparse_search.top_k),
                            ts_config=cfg.indexing.postgres_ts_config,
                        )
                except Exception:
                    SEARCH_STAGE_ERRORS_TOTAL.labels(stage="sparse_leg").inc()
                    raise
        debug["fusion_sparse_results"] = len(sparse_results)
        SEARCH_LEG_RESULTS_COUNT.labels(leg="sparse").observe(len(sparse_results))

        # Graph retrieval: query Neo4j for relevant entities, then hydrate to chunks from Postgres.
        if include_graph and cfg.graph_search.enabled:
            debug["fusion_graph_attempted"] = True
            graph_k = int(top_k or cfg.graph_search.top_k)
            db_name = cfg.graph_storage.resolve_database(corpus_id)
            neo4j: Neo4jClient | None = None
            try:
                with GRAPH_LEG_LATENCY_SECONDS.time():
                    neo4j = Neo4jClient(
                        cfg.graph_storage.neo4j_uri,
                        cfg.graph_storage.neo4j_user,
                        cfg.graph_storage.neo4j_password,
                        database=db_name,
                    )
                    with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="neo4j_connect").time():
                        await neo4j.connect()
                    if getattr(cfg.graph_search, "mode", "entity") == "chunk":
                        # Chunk-level graph retrieval: Neo4j vector index over Chunk nodes.
                        if q_emb is None:
                            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="embed_query").time():
                                q_emb = await embedder.embed(query)
                        overfetch = (
                            int(getattr(cfg.graph_search, "chunk_seed_overfetch_multiplier", 1) or 1)
                            if cfg.graph_storage.neo4j_database_mode == "shared"
                            else 1
                        )
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="neo4j_chunk_vector_search").time():
                            hits = await neo4j.chunk_vector_search(
                                corpus_id,
                                q_emb,
                                index_name=cfg.graph_indexing.chunk_vector_index_name,
                                top_k=graph_k,
                                neighbor_window=int(getattr(cfg.graph_search, "chunk_neighbor_window", 0) or 0),
                                overfetch_multiplier=overfetch,
                            )
                        debug["fusion_graph_entity_hits"] = len(hits)

                        score_by_id = {cid: float(score) for cid, score in hits}

                        # Expand via entities (semantic KG / code entities linked to chunks).
                        if bool(
                            getattr(cfg.graph_search, "chunk_entity_expansion_enabled", False)
                        ) and int(cfg.graph_search.max_hops) > 0:
                            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="neo4j_expand_chunks_via_entities").time():
                                exp_hits = await neo4j.expand_chunks_via_entities(
                                    corpus_id,
                                    hits,
                                    max_hops=int(cfg.graph_search.max_hops),
                                    top_k=graph_k,
                                )
                            debug["fusion_graph_entity_expansion_hits"] = len(exp_hits)
                            w = float(
                                getattr(cfg.graph_search, "chunk_entity_expansion_weight", 1.0) or 0.0
                            )
                            for cid, score in exp_hits:
                                score_by_id[cid] = max(
                                    float(score_by_id.get(cid) or 0.0), float(score) * w
                                )

                        chunk_ids = sorted(score_by_id, key=lambda cid: (-float(score_by_id[cid]), cid))[
                            :graph_k
                        ]
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_get_chunks").time():
                            hydrated = await postgres.get_chunks(corpus_id, chunk_ids)
                        graph_results = [
                            ChunkMatch(
                                chunk_id=ch.chunk_id,
                                content=ch.content,
                                file_path=ch.file_path,
                                start_line=ch.start_line,
                                end_line=ch.end_line,
                                language=ch.language,
                                score=float(score_by_id.get(ch.chunk_id) or 0.0),
                                source="graph",
                                metadata={
                                    "graph_mode": "chunk",
                                    "graph_index": cfg.graph_indexing.chunk_vector_index_name,
                                },
                            )
                            for ch in hydrated
                            if ch.chunk_id in score_by_id
                        ]
                        debug["fusion_graph_hydrated_chunks"] = len(graph_results)
                    else:
                        # Entity-mode graph retrieval: return real chunk_ids via Entity-[:IN_CHUNK]->Chunk.
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="neo4j_entity_chunk_search").time():
                            hits = await neo4j.entity_chunk_search(
                                corpus_id, query, cfg.graph_search.max_hops, graph_k
                            )
                        debug["fusion_graph_entity_hits"] = len(hits)

                        score_by_id = {cid: float(score) for cid, score in hits}
                        chunk_ids = [cid for cid, _score in hits]
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_get_chunks").time():
                            hydrated = await postgres.get_chunks(corpus_id, chunk_ids)
                        graph_results = [
                            ChunkMatch(
                                chunk_id=ch.chunk_id,
                                content=ch.content,
                                file_path=ch.file_path,
                                start_line=ch.start_line,
                                end_line=ch.end_line,
                                language=ch.language,
                                score=float(score_by_id.get(ch.chunk_id) or 0.0),
                                source="graph",
                                metadata={"graph_mode": "entity"},
                            )
                            for ch in hydrated
                            if ch.chunk_id in score_by_id
                        ]
                        debug["fusion_graph_hydrated_chunks"] = len(graph_results)
            except Exception as e:
                debug["fusion_graph_error"] = str(e)
                SEARCH_STAGE_ERRORS_TOTAL.labels(stage="graph_leg").inc()
            finally:
                if neo4j is not None:
                    try:
                        await neo4j.disconnect()
                    except Exception:
                        pass
        SEARCH_LEG_RESULTS_COUNT.labels(leg="graph").observe(len(graph_results))
        SEARCH_GRAPH_HYDRATED_CHUNKS_COUNT.observe(len(graph_results))

        # Fuse
        results: list[ChunkMatch]
        if config.method == "rrf":
            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="fusion_rrf").time():
                results = self.rrf_fusion([vector_results, sparse_results, graph_results], k=int(config.rrf_k))
        else:
            v = list(vector_results)
            s = list(sparse_results)
            g = list(graph_results)
            if config.normalize_scores:
                with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="normalize_scores").time():
                    v = _normalize(v)
                    s = _normalize(s)
                    g = _normalize(g)
            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="fusion_weighted").time():
                results = self.weighted_fusion(
                    [v, s, g], weights=[config.vector_weight, config.sparse_weight, config.graph_weight]
                )

        # Apply final_k cap (caller can override with top_k)
        final_k = int(top_k or cfg.retrieval.final_k)
        self.last_debug = debug
        final_results = results[:final_k]
        SEARCH_RESULTS_FINAL_COUNT.observe(len(final_results))
        return final_results

    def rrf_fusion(self, results: list[list[ChunkMatch]], k: int) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for result_list in results:
            for rank, chunk in enumerate(result_list):
                scores[chunk.chunk_id] += 1.0 / (k + rank + 1)
                chunk_map[chunk.chunk_id] = chunk
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [chunk_map[cid].model_copy(update={"score": scores[cid]}) for cid in sorted_ids]

    def weighted_fusion(self, results: list[list[ChunkMatch]], weights: list[float]) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for weight, result_list in zip(weights, results, strict=False):
            for chunk in result_list:
                scores[chunk.chunk_id] += chunk.score * weight
                chunk_map[chunk.chunk_id] = chunk
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [chunk_map[cid].model_copy(update={"score": scores[cid]}) for cid in sorted_ids]


def _normalize(chunks: list[ChunkMatch]) -> list[ChunkMatch]:
    if not chunks:
        return chunks
    mx = max((c.score for c in chunks), default=0.0)
    if mx <= 0:
        return chunks
    return [c.model_copy(update={"score": float(c.score) / float(mx)}) for c in chunks]
