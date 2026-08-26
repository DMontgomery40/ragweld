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
- **Qdrant** (`server/retrieval/qdrant_store.py`): physical generation
  collections per corpus (`ragweld_chunks_<safe>_<sha1[:8]>__<hex>`), each
  holding both the dense vector (`text-dense`) and the IDF-modified BM25 sparse
  vector (`text-sparse`) for every chunk. Which generation is live is not a
  Qdrant alias: it is named by the corpus's **generation manifest** in Postgres
  (`corpora.meta.generation`, `server/indexing/generations.py`). Writes go
  through the Haystack `QdrantDocumentStore`; reads use the Qdrant client
  against the manifest's collection so a missing or wiped generation reads as
  missing, never as an empty 200.
- **Neo4j**: the graph leg (lexical graph, chunk vector index, optional
  semantic KG) is unchanged and remains the graph leg's own implementation.
- **Docling** (`server/indexing/text_extractors.py`): PDF, DOCX, PPTX, XLSX and
  HTML are converted to markdown by Docling during indexing; chunks record
  `extraction = docling | direct`.

## Index run lifecycle (`server/api/index.py`)

1. A run creates a staged Qdrant generation (`<prefix>__<hex>`), a staged
   Postgres corpus id (`__staging__<corpus>__<run>`) and, when graph indexing
   is on, writes the graph under that staging id in Neo4j. Chunk rows go to
   Postgres, dense + sparse vectors go to the staged generation. Nothing is
   visible to retrieval yet.
2. Every staged resource is verified before anything changes: the staged
   generation's exact point count must equal the run's chunk count, and a
   lexical graph must hold one Chunk node per chunk; a mismatch fails the run
   and drops the staged resources while the live generation stays in place.
3. **The commit is one Postgres transaction**: it swaps the chunk rows,
   summaries and contracts onto the corpus id and writes the generation
   manifest `{run_id, qdrant_collection, graph_repo_id}` on the corpus row.
   Retrieval, the graph API, index stats and the incremental writers resolve
   the physical Qdrant collection and the Neo4j graph id from that manifest,
   so there is no per-store swap (no alias switch, no Neo4j relabel) and no
   window in which new chunk rows pair with old vectors or an old graph.
   Retention: the generation being replaced joins the manifest's `retired`
   list and stays readable for `indexing.generation_retention_seconds` (a
   reader that resolved the manifest before the commit keeps finding its
   collection and graph); a later commit drops the entries whose grace elapsed,
   by exact id, and prunes them from the manifest (best-effort: a failure
   leaves the entry for the next commit to retry, never an inconsistent index).
   A durable per-corpus run fence on the corpus row (`corpora.meta.index_run`:
   run id, owner `host:pid`, heartbeat, compare-and-set) rejects a second run
   or a de-index with a typed 409 (`index_run_in_progress`) while one is
   building; the run heartbeats it, a fence whose heartbeat is older than
   `indexing.index_run_lease_seconds` belongs to a crashed worker and is taken
   over by the next run (or released by the stop route), and the promotion
   transaction re-checks ownership under the row lock and a per-corpus
   advisory lock shared with the incremental writers (first generation is
   set-if-absent). Cancelled or failed runs drop their staged resources only
   after proving, against the manifest, that nothing was committed; once the
   manifest is written the run is complete whatever happens afterwards.
   De-indexing records the exact collections and graph ids to drop as a
   tombstone (`corpora.meta.index_tombstone`) in the same transaction that
   clears the rows and the manifest, answers a typed 503 until every external
   cleanup succeeded, and only then clears the tombstone.
4. `indexing.skip_dense=true` writes sparse-only points (no dense vectors);
   the vector leg returns nothing for such corpora and the corpus records
   `embedding_dimensions = 0`.

Recall (`server/chat/recall_indexer.py`) and the Codex session ingest worker
write incrementally into the live generation through
`QdrantChunkStore.upsert_chunks`, creating a generation and recording its
manifest on first write. Corpora indexed before the manifest existed are
upgraded once at API startup (`ensure_generation_manifests`: their alias
target becomes the manifest's collection, their own id the graph id).

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
  manifest's collection using `text-dense`.
- Sparse: embed the query with the corpus sparse contract (fastembed
  `Qdrant/bm25`), `query_points` on the manifest's collection using
  `text-sparse`.
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
  (`qdrant`); the manifest's collection missing for a corpus that has been
  indexed -> typed 503 `required_retrieval_leg_failed`; no manifest for a
  never-indexed corpus -> empty leg (the truthful answer).

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
