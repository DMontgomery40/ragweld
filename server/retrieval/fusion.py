from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import FusionConfig, RerankingConfig
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
from server.retrieval.rerank import Reranker
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
        corpus_ids: list[str] | str | None = None,
        query: str = "",
        config: FusionConfig | None = None,
        *,
        # Back-compat: allow older call sites/tests to pass a single corpus id.
        corpus_id: str | None = None,
        repo_id: str | None = None,
        include_vector: bool = True,
        include_sparse: bool = True,
        include_graph: bool = True,
        top_k: int | None = None,
    ) -> list[ChunkMatch]:
        # Resolve corpus_ids from backwards-compatible inputs.
        if corpus_ids is None:
            corpus_ids = corpus_id or repo_id or []
        if isinstance(corpus_ids, str):
            corpus_ids = [corpus_ids]

        # Normalize + de-dupe corpus ids (preserve order).
        corpus_ids = [str(cid).strip() for cid in (corpus_ids or []) if str(cid).strip()]
        corpus_ids = list(dict.fromkeys(corpus_ids))
        if config is None:
            config = FusionConfig()
        if not corpus_ids or not query.strip():
            self.last_debug = {
                "fusion_corpora": corpus_ids,
                "fusion_vector_requested": bool(include_vector),
                "fusion_sparse_requested": bool(include_sparse),
                "fusion_graph_requested": bool(include_graph),
                "fusion_vector_results": 0,
                "fusion_sparse_results": 0,
                "fusion_graph_hydrated_chunks": 0,
            }
            SEARCH_RESULTS_FINAL_COUNT.observe(0)
            return []

        async def _search_single_corpus(
            cid: str,
        ) -> tuple[list[ChunkMatch], list[ChunkMatch], list[ChunkMatch], dict[str, Any], int, RerankingConfig, str]:
            cfg = await load_scoped_config(repo_id=cid)

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
                "fusion_graph_entity_expansion_enabled": bool(
                    getattr(cfg.graph_search, "chunk_entity_expansion_enabled", False)
                ),
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
                                cid, q_emb, int(top_k or cfg.vector_search.top_k)
                            )
                    except Exception:
                        SEARCH_STAGE_ERRORS_TOTAL.labels(stage="vector_leg").inc()
                        raise
                    if cfg.vector_search.similarity_threshold > 0:
                        vector_results = [
                            r for r in vector_results if r.score >= cfg.vector_search.similarity_threshold
                        ]
            debug["fusion_vector_results"] = len(vector_results)

            if include_sparse and cfg.sparse_search.enabled:
                with SPARSE_LEG_LATENCY_SECONDS.time():
                    try:
                        with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_sparse_search").time():
                            sparse_results = await postgres.sparse_search(
                                cid,
                                query,
                                int(top_k or cfg.sparse_search.top_k),
                                ts_config=cfg.indexing.postgres_ts_config,
                            )
                    except Exception:
                        SEARCH_STAGE_ERRORS_TOTAL.labels(stage="sparse_leg").inc()
                        raise
            debug["fusion_sparse_results"] = len(sparse_results)

            # Graph retrieval: query Neo4j for relevant entities, then hydrate to chunks from Postgres.
            if include_graph and cfg.graph_search.enabled:
                debug["fusion_graph_attempted"] = True
                graph_k = int(top_k or cfg.graph_search.top_k)
                db_name = cfg.graph_storage.resolve_database(cid)
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
                                    cid,
                                    q_emb,
                                    index_name=cfg.graph_indexing.chunk_vector_index_name,
                                    top_k=graph_k,
                                    neighbor_window=int(getattr(cfg.graph_search, "chunk_neighbor_window", 0) or 0),
                                    overfetch_multiplier=overfetch,
                                )
                            debug["fusion_graph_entity_hits"] = len(hits)

                            score_by_id = {chunk_id: float(score) for chunk_id, score in hits}

                            # Expand via entities (semantic KG / code entities linked to chunks).
                            if bool(
                                getattr(cfg.graph_search, "chunk_entity_expansion_enabled", False)
                            ) and int(cfg.graph_search.max_hops) > 0:
                                with SEARCH_STAGE_LATENCY_SECONDS.labels(
                                    stage="neo4j_expand_chunks_via_entities"
                                ).time():
                                    exp_hits = await neo4j.expand_chunks_via_entities(
                                        cid,
                                        hits,
                                        max_hops=int(cfg.graph_search.max_hops),
                                        top_k=graph_k,
                                    )
                                debug["fusion_graph_entity_expansion_hits"] = len(exp_hits)
                                w = float(getattr(cfg.graph_search, "chunk_entity_expansion_weight", 1.0) or 0.0)
                                for chunk_id, score in exp_hits:
                                    score_by_id[chunk_id] = max(
                                        float(score_by_id.get(chunk_id) or 0.0), float(score) * w
                                    )

                            chunk_ids = sorted(
                                score_by_id, key=lambda chunk_id: (-float(score_by_id[chunk_id]), chunk_id)
                            )[:graph_k]
                            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_get_chunks").time():
                                hydrated = await postgres.get_chunks(cid, chunk_ids)
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
                                        "corpus_id": cid,
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
                                hits = await neo4j.entity_chunk_search(cid, query, cfg.graph_search.max_hops, graph_k)
                            debug["fusion_graph_entity_hits"] = len(hits)

                            score_by_id = {chunk_id: float(score) for chunk_id, score in hits}
                            chunk_ids = [chunk_id for chunk_id, _score in hits]
                            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="postgres_get_chunks").time():
                                hydrated = await postgres.get_chunks(cid, chunk_ids)
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
                                    metadata={"corpus_id": cid, "graph_mode": "entity"},
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

            # Ensure corpus_id is always present for multi-corpus identity + UI reporting.
            for r in vector_results:
                r.metadata = {**(r.metadata or {}), "corpus_id": cid}
            for r in sparse_results:
                r.metadata = {**(r.metadata or {}), "corpus_id": cid}

            return (
                vector_results,
                sparse_results,
                graph_results,
                debug,
                int(cfg.retrieval.final_k),
                cfg.reranking,
                str(cfg.training.tribrid_reranker_model_path or ""),
            )

        # Run per-corpus retrieval and collect lists for fusion.
        per_corpus_debug: dict[str, Any] = {}
        vector_lists: list[list[ChunkMatch]] = []
        sparse_lists: list[list[ChunkMatch]] = []
        graph_lists: list[list[ChunkMatch]] = []
        final_k_candidates: list[int] = []
        reranking_cfg: RerankingConfig | None = None
        trained_model_path: str | None = None
        rerank_config_corpus_id: str | None = None

        total_vector = 0
        total_sparse = 0
        total_graph = 0
        total_graph_hits = 0
        total_graph_exp_hits = 0
        any_vector_enabled = False
        any_sparse_enabled = False
        any_graph_enabled = False
        any_graph_attempted = False
        graph_errors: list[dict[str, str]] = []

        for cid in corpus_ids:
            v, s, g, dbg, final_k_default, rerank_cfg, train_path = await _search_single_corpus(cid)
            per_corpus_debug[cid] = dbg
            vector_lists.append(v)
            sparse_lists.append(s)
            graph_lists.append(g)
            final_k_candidates.append(int(final_k_default))
            if reranking_cfg is None:
                reranking_cfg = rerank_cfg
                trained_model_path = str(train_path or "").strip() or None
                rerank_config_corpus_id = cid

            total_vector += len(v)
            total_sparse += len(s)
            total_graph += len(g)
            total_graph_hits += int(dbg.get("fusion_graph_entity_hits") or 0)
            total_graph_exp_hits += int(dbg.get("fusion_graph_entity_expansion_hits") or 0)
            any_vector_enabled = any_vector_enabled or bool(dbg.get("fusion_vector_enabled"))
            any_sparse_enabled = any_sparse_enabled or bool(dbg.get("fusion_sparse_enabled"))
            any_graph_enabled = any_graph_enabled or bool(dbg.get("fusion_graph_enabled"))
            any_graph_attempted = any_graph_attempted or bool(dbg.get("fusion_graph_attempted"))
            if dbg.get("fusion_graph_error"):
                graph_errors.append({"corpus_id": cid, "error": str(dbg.get("fusion_graph_error"))})

        graph_modes: list[str] = []
        for cid in corpus_ids:
            try:
                mode = str((per_corpus_debug.get(cid) or {}).get("fusion_graph_mode") or "").strip()
            except Exception:
                mode = ""
            if mode:
                graph_modes.append(mode)
        unique_graph_modes = list(dict.fromkeys(graph_modes))
        graph_mode: str | None
        if not unique_graph_modes:
            graph_mode = None
        elif len(unique_graph_modes) == 1:
            graph_mode = unique_graph_modes[0]
        else:
            graph_mode = "mixed"

        # Aggregate debug (keep legacy top-level keys for existing UI/debug tooling).
        debug: dict[str, Any] = {
            "fusion_corpora": list(corpus_ids),
            "fusion_vector_requested": bool(include_vector),
            "fusion_sparse_requested": bool(include_sparse),
            "fusion_graph_requested": bool(include_graph),
            "fusion_vector_enabled": bool(any_vector_enabled),
            "fusion_sparse_enabled": bool(any_sparse_enabled),
            "fusion_graph_enabled": bool(any_graph_enabled),
            "fusion_vector_results": int(total_vector),
            "fusion_sparse_results": int(total_sparse),
            "fusion_graph_entity_hits": int(total_graph_hits),
            "fusion_graph_mode": graph_mode,
            "fusion_graph_hydrated_chunks": int(total_graph),
            "fusion_graph_attempted": bool(any_graph_attempted),
            "fusion_graph_error": graph_errors[0]["error"] if graph_errors else None,
            "fusion_graph_errors": graph_errors,
            "fusion_graph_entity_expansion_enabled": bool(
                any(bool(d.get("fusion_graph_entity_expansion_enabled")) for d in per_corpus_debug.values())
            ),
            "fusion_graph_entity_expansion_hits": int(total_graph_exp_hits),
            "fusion_per_corpus": per_corpus_debug,
        }

        SEARCH_LEG_RESULTS_COUNT.labels(leg="vector").observe(int(total_vector))
        SEARCH_LEG_RESULTS_COUNT.labels(leg="sparse").observe(int(total_sparse))
        SEARCH_LEG_RESULTS_COUNT.labels(leg="graph").observe(int(total_graph))
        SEARCH_GRAPH_HYDRATED_CHUNKS_COUNT.observe(int(total_graph))

        # Fuse once across all corpora.
        results: list[ChunkMatch]
        if config.method == "rrf":
            all_lists: list[list[ChunkMatch]] = []
            for v, s, g in zip(vector_lists, sparse_lists, graph_lists, strict=False):
                all_lists.extend([v, s, g])
            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="fusion_rrf").time():
                results = self.rrf_fusion(all_lists, k=int(config.rrf_k))
        else:
            v_all = [c for lst in vector_lists for c in lst]
            s_all = [c for lst in sparse_lists for c in lst]
            g_all = [c for lst in graph_lists for c in lst]
            if config.normalize_scores:
                with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="normalize_scores").time():
                    v_all = _normalize(v_all)
                    s_all = _normalize(s_all)
                    g_all = _normalize(g_all)
            with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="fusion_weighted").time():
                results = self.weighted_fusion(
                    [v_all, s_all, g_all],
                    weights=[config.vector_weight, config.sparse_weight, config.graph_weight],
                )

        # Optional reranking stage (best-effort; never fails the search).
        rerank_ok = True
        rerank_error: str | None = None
        rerank_applied = False
        rerank_skipped_reason: str | None = None
        rerank_candidates_reranked = 0
        rerank_mode = ""
        if reranking_cfg is not None:
            try:
                rerank_mode = str(getattr(reranking_cfg, "reranker_mode", "") or "").strip().lower()
            except Exception:
                rerank_mode = ""

        if results and reranking_cfg is not None and rerank_mode and rerank_mode != "none":
            try:
                with SEARCH_STAGE_LATENCY_SECONDS.labels(stage="rerank").time():
                    reranker = Reranker(reranking_cfg, trained_model_path=trained_model_path)
                    rr = await reranker.try_rerank(query, results)
                    results = rr.chunks
                    rerank_ok = bool(rr.ok)
                    rerank_error = rr.error
                    rerank_applied = bool(rr.applied)
                    rerank_skipped_reason = rr.skipped_reason
                    rerank_candidates_reranked = int(getattr(rr, "candidates_reranked", 0) or 0)
            except Exception as e:
                rerank_ok = False
                rerank_error = str(e)
                SEARCH_STAGE_ERRORS_TOTAL.labels(stage="rerank").inc()

        debug.update(
            {
                "rerank_enabled": bool(rerank_mode and rerank_mode != "none"),
                "rerank_mode": rerank_mode or "none",
                "rerank_ok": bool(rerank_ok),
                "rerank_applied": bool(rerank_applied),
                "rerank_candidates_reranked": int(rerank_candidates_reranked),
                "rerank_skipped_reason": rerank_skipped_reason,
                "rerank_error": rerank_error,
                "rerank_config_corpus_id": rerank_config_corpus_id,
            }
        )

        # Apply final_k cap (caller can override with top_k)
        final_k_default = max(final_k_candidates) if final_k_candidates else 0
        final_k = int(top_k or final_k_default)

        self.last_debug = debug
        final_results = results[:final_k] if final_k > 0 else []
        SEARCH_RESULTS_FINAL_COUNT.observe(len(final_results))
        return final_results

    def rrf_fusion(self, results: list[list[ChunkMatch]], k: int) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for result_list in results:
            for rank, chunk in enumerate(result_list):
                key = self._fusion_key(chunk)
                scores[key] += 1.0 / (k + rank + 1)
                chunk_map[key] = chunk
        sorted_keys = sorted(scores, key=lambda key: scores[key], reverse=True)
        return [chunk_map[key].model_copy(update={"score": scores[key]}) for key in sorted_keys]

    def weighted_fusion(self, results: list[list[ChunkMatch]], weights: list[float]) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for weight, result_list in zip(weights, results, strict=False):
            for chunk in result_list:
                key = self._fusion_key(chunk)
                scores[key] += chunk.score * weight
                chunk_map[key] = chunk
        sorted_keys = sorted(scores, key=lambda key: scores[key], reverse=True)
        return [chunk_map[key].model_copy(update={"score": scores[key]}) for key in sorted_keys]

    @staticmethod
    def _fusion_key(chunk: ChunkMatch) -> str:
        """Return a stable identity key for fusion/deduping across multiple corpora."""
        meta = chunk.metadata or {}
        corpus_id = ""
        try:
            corpus_id = str(meta.get("corpus_id") or "").strip()
        except Exception:
            corpus_id = ""
        return f"{corpus_id}::{chunk.chunk_id}" if corpus_id else str(chunk.chunk_id)


def _normalize(chunks: list[ChunkMatch]) -> list[ChunkMatch]:
    if not chunks:
        return chunks
    mx = max((c.score for c in chunks), default=0.0)
    if mx <= 0:
        return chunks
    return [c.model_copy(update={"score": float(c.score) / float(mx)}) for c in chunks]
