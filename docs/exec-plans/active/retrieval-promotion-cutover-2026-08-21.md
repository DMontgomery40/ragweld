# Retrieval Promotion Cutover (Haystack/Docling/Qdrant)

Date: 2026-08-21

Status: active — pilot parity gates proven; atomic cutover designed, not yet
executed.

## Proven so far (all committed on main, each slice gate-verified)

- Pilot embeds under the operator's real embedding config; dense + sparse
  (IDF-modified BM25 via fastembed `Qdrant/bm25`) contracts are recorded in
  the manifest; search and re-ingest fail closed (typed 409) on drift, and
  legacy manifests without contracts fail closed too.
- Qdrant is a Compose-owned service (`qdrant`, pinned v1.17.1, project volume,
  healthcheck, disposable random-port provisioning in the strict lane).
- Docling genuinely extracts rich documents (pdf/docx/pptx/xlsx/html) during
  export with per-chunk `extraction` provenance; code/text stays direct.
- Pilot search runs per-leg dense/sparse retrieval with config-driven fusion
  (`fusion.method`/`rrf_k`/weights) and honest per-leg provenance; pilot
  answer produces a grounded LiteLLM→vLLM answer with ChunkMatch citations
  (proven live on the aurora acceptance corpus, and pilot search proven in the
  rendered browser).
- Ingest stages a fresh physical generation and promotes it atomically via a
  Qdrant alias; superseded generations are removed; corpus deletion cleans
  pilot state; wiped generations read as not-ready, never an empty 200.

## Cutover design (the remaining atomic slice)

Key insight from the lane mapping: rerank, scoring boosts, MMR/dedup/neighbor
expansion, and the semantic cache all operate on post-leg `ChunkMatch` lists
and are storage-agnostic. The cutover is therefore a **leg swap inside the
retrieval orchestration plus an index-write swap**, not a rewrite of the whole
fusion module.

1. **Index write path** (`server/api/index.py` job): chunk rows continue to be
   written to Postgres as control/state (hydration, summaries, neighbor
   expansion, graph hydration) but WITHOUT dense embeddings; dense + sparse
   vectors are written to a staged Qdrant generation and alias-promoted
   (reuse/generalize the pilot machinery). Corpus embedding meta in Postgres
   remains the recorded dense contract; the sparse contract becomes
   `qdrant_sparse_idf`/`Qdrant/bm25` (replacing ts_config/bm25_tokenizer
   semantics).
2. **Fusion legs** (`server/retrieval/fusion.py`): vector leg queries Qdrant
   (dense vector over the corpus alias) and maps point payloads to
   `ChunkMatch`; sparse leg queries Qdrant sparse vectors (fastembed query
   embedding); graph leg (Neo4j) unchanged — gate 5 decision: Neo4j keeps its
   own chunk-vector index as the graph leg's implementation detail; it is not
   the primary vector engine.
3. **Deletions in the same slice**: `PostgresClient.vector_search`,
   `sparse_search*`, `fts_search*`, `bm25_search_pg_search`,
   `pg_search_available`, `file_path_search`, embedding writes in
   `upsert_embeddings` (chunk-row writes survive under an honest name),
   `ensure_vector_index`, sparse-engine config
   (`sparse_search.engine`/bm25 tunables that no longer drive anything),
   the pilot's separate endpoints/UI once the canonical index/search paths ARE
   the new lane, plus their tests/docs/glossary entries. Regenerate
   `generated.ts` + contract bundle.
4. **Recall lane**: recall writes move to the same Qdrant write path (recall
   is a corpus like any other); its contract enforcement continues to work.
5. **Contract tests**: `tests/integration/test_required_retrieval_leg_contract.py`
   keeps its 409/503 semantics; the sparse mismatch fixture changes from
   ts_config drift to sparse-model drift. Strict lane already provisions
   disposable Qdrant.
6. **Acceptance to close the slice**: full clean flow on the promoted lane for
   the aurora corpus (index → three legs → grounded answer + citations →
   rendered browser), plus the strict integration lane and full local gates.

Do NOT start this slice without the time to land it green atomically.

## Out-of-scope kept-alive surfaces

- Postgres remains control/config/state storage (corpus registry, chunk rows,
  summaries, caches, lineage, query log, trace store).
- Neo4j remains the graph-parity substrate, including its chunk-vector index.
- The reranker (`server/reranker/`, `server/retrieval/rerank.py`) and
  observability fabric are untouched by the cutover.
