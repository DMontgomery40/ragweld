# Retrieval Lane: Postgres control rows + Qdrant vectors + Neo4j graph

Date: 2026-08-21 (promotion cutover landed)

This is the canonical retrieval/indexing lane. There is no other lane: the
former Haystack/Docling/Qdrant "pilot" endpoints, sidecar export, and the
Postgres pgvector/FTS legs were removed when this lane was promoted.

## Ownership

- **Postgres** (`server/db/postgres.py`): corpus registry and per-corpus config,
  chunk rows (content, provenance, `metadata.extraction`), chunk summaries,
  semantic/embedding caches, and the recorded index contracts
  (`corpora.embedding_*`, `corpora.sparse_contract`). Chunk rows carry no
  vectors.
- **Qdrant** (`server/retrieval/qdrant_store.py`): one alias per corpus
  (`ragweld_chunks_<corpus>`) pointing at one physical generation that holds
  both the dense vector (`text-dense`) and the IDF-modified BM25 sparse vector
  (`text-sparse`) for every chunk. Writes go through the Haystack
  `QdrantDocumentStore`; reads use the Qdrant client against the alias so a
  missing or wiped generation reads as missing, never as an empty 200.
- **Neo4j**: the graph leg (lexical graph, chunk vector index, optional
  semantic KG) is unchanged and remains the graph leg's own implementation.
- **Docling** (`server/indexing/text_extractors.py`): PDF, DOCX, PPTX, XLSX and
  HTML are converted to markdown by Docling during indexing; chunks record
  `extraction = docling | direct`.

## Index run lifecycle (`server/api/index.py`)

1. A run creates a staged Qdrant generation (`<alias>__<hex>`) and a staged
   Postgres corpus id. Chunk rows go to Postgres, dense + sparse vectors go to
   the staged generation. Nothing is visible to retrieval yet.
2. Postgres staging is promoted (chunk rows, summaries, contracts). The staged
   generation's exact point count must equal the run's chunk count before it
   becomes visible; a mismatch fails the run and drops the staged generation
   while the previous live generation stays in place.
3. The Qdrant alias is then switched to the new generation in one alias
   operation and superseded/orphaned generations of that corpus are deleted.
   Cancelled or failed runs drop their staged generation. The alias is
   injective per corpus (`ragweld_chunks_<safe>_<sha1[:8]>`), so similar
   corpus ids never share generations.
4. `indexing.skip_dense=true` writes sparse-only points (no dense vectors);
   the vector leg returns nothing for such corpora and the corpus records
   `embedding_dimensions = 0`.

Recall (`server/chat/recall_indexer.py`) and the Codex session ingest worker
write incrementally into the live generation through
`QdrantChunkStore.upsert_chunks`, creating and aliasing a generation on first
write.

## Contracts (`server/retrieval/contracts.py`)

- Dense: embedding backend/provider/model/dimensions + tokenization, recorded
  on the corpus row at index time and enforced at query time (typed 409
  `embedding_contract_mismatch`).
- Sparse: `{engine: qdrant_sparse_idf, model: Qdrant/bm25, k1, b, language,
  stemmer}` where `k1`/`b` come from `sparse_search.bm25_k1`/`bm25_b` and
  `language`/`stemmer` from `indexing.bm25_stemmer_lang`/`bm25_tokenizer`.
  These change the stored sparse vectors, so they are part of the recorded
  contract: drift is a typed 409 `sparse_contract_mismatch` until the corpus
  is re-indexed. Config writes that would change either contract on an
  indexed corpus are refused (`index_contract_change_requires_reindex`).

## Query-time legs (`server/retrieval/fusion.py`)

- Vector: embed the query with the corpus contract, `query_points` on the
  alias using `text-dense`.
- Sparse: embed the query with the corpus sparse contract (fastembed
  `Qdrant/bm25`), `query_points` on the alias using `text-sparse`.
- Graph: Neo4j chunk/entity retrieval hydrated from Postgres chunk rows.
- Rerank, scoring boosts, dedup/MMR/neighbor expansion and the semantic cache
  operate on `ChunkMatch` lists and are storage-agnostic. MMR reads dense
  vectors back from Qdrant.
- Rerank (`server/retrieval/rerank.py`): `reranking.reranker_mode` is `none`,
  `cloud` or `learning`. `cloud` with `reranker_cloud_provider=litellm`
  (default) sends the query plus the top-`reranker_cloud_top_n` snippets in one
  request to the gateway alias in `reranker_cloud_model`
  (`server/retrieval/gateway_reranker.py`; prompt
  `system_prompts.gateway_rerank`). Candidates are serialized as JSON data rows
  with opaque per-request ids and the alias must answer with `{id, score}`
  objects forming an exact bijection — a missing, unknown, duplicated or
  non-numeric entry is a rerank failure, not a silent passthrough, and passage
  text cannot impersonate a marker. `cohere` calls the Cohere rerank API. Both
  blend min-max-normalized scores with the fusion score by
  `tribrid_reranker_alpha`, break ties by the fusion score (never the chunk
  id), treat uniform scores (including a single candidate) as neutral
  (`reranker_neutral`, fusion order and scores preserved), and stamp
  `reranker_*` metadata on every candidate. The config schema admits only
  `cloud|learning|none` and `litellm|cohere`; stale aliases such as `local`
  fail validation instead of being normalized. A gateway that cannot be
  resolved (disabled, unknown alias, no credential) is reported as
  `rerank_skipped_reason=gateway_unavailable` in the query log and trace. The
  `learning` mode loads the MLX LoRA reranker on the host; after the 2026-08-22
  crashes the operator rule is to keep reranking on cloud models.
- Failure semantics: Qdrant unreachable -> typed 503 `dependency_unavailable`
  (`qdrant`); alias missing for a corpus that has been indexed -> typed 503
  `required_retrieval_leg_failed`; alias missing for a never-indexed corpus ->
  empty leg (the truthful answer).

## Operator surfaces

- RAG -> Retrieval: vector/sparse enablement and top-k, BM25 k1/b, fusion.
- RAG -> Indexing: sparse stemming/language (contract-locked once indexed),
  skip dense, graph build options.
- Observability status/incidents and the config control plane report the
  `haystack_docling_qdrant` component from a functional Qdrant probe plus the
  active corpus generation (points, dense points, dimensions); a corpus with
  chunk rows but no live generation is a critical retrieval incident.
- Dashboard storage shows Postgres chunk/summary bytes, Qdrant points and an
  estimated dense-vector size (Qdrant does not expose per-collection bytes).

## Verification

- `tests/integration/test_qdrant_chunk_store.py` (store contract: staged
  generations, atomic promotion, both legs, sparse-only, wiped generation).
- `tests/integration/test_index_promoted_lane.py` (API: create -> index ->
  three legs -> storage -> delete).
- `tests/integration/test_required_retrieval_leg_contract.py` (409/503
  semantics including sparse-contract drift and a wiped generation).
- Strict lane: `RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh`
  provisions disposable Postgres, Neo4j, and Qdrant.

## Upgrade note

On the first boot after the cutover the schema migration drops
`chunks.embedding`/`chunks.tsv`; every corpus is then reset to "never
indexed" (no `last_indexed`, no contracts) because its vectors no longer
exist anywhere. Re-run indexing per corpus; Recall recreates its generation on
the next conversation write.
