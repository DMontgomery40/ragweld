# Neo4j GraphRAG Cross-Corpus Execution Ledger

Date started: 2026-08-31

Status: active

Plan: `docs/superpowers/plans/2026-08-31-neo4j-graphrag-cross-corpus.md`

## Execution contract

- Mac checkout: source edits only.
- LXC100 overlay: `/tmp/ragweld-graphrag` for uncommitted RED/GREEN verification.
- Production checkout: `/opt/ragweld`, changed only after reviewed commits are ready to deploy.
- Every task requires focused LXC100 verification, GitNexus scope detection, and a completed DeepSeek V4 Flash PASS before commit.
- Review alias: `deepseek.deepseek-v4-flash`, temperature `0`.

## Task 1 - Neo4j GraphRAG 1.19 contract

Status: complete

### Pre-edit impact analysis

| Symbol | Risk | Direct callers/importers | Total impacted | Processes/modules | Decision |
|---|---:|---:|---:|---|---|
| `GraphRAGExtractionResult` | LOW | 2 | 6 | no indexed process; import surface reaches API and code graph | proceed |
| `Neo4jClient` | MEDIUM | 10 | 51 | broad DB/API/retrieval import surface; Task 1 changes imports only | proceed with focused boundary tests |
| `extract_code_graph` | LOW | 1 | 4 | API indexing module through `_write_code_graph` | proceed |

GitNexus refresh note: the incremental refresh first failed because the derived `file_fts` index was inconsistent. The derived `.gitnexus` index was cleaned and rebuilt successfully at plan commit `e38cb6ba` (18,443 nodes, 39,144 edges, 300 flows) before rerunning the exact impacts above.

### TDD evidence

- RED: LXC100 overlay, 2026-08-31: collection failed exactly at the new non-experimental import with `ModuleNotFoundError: No module named 'neo4j_graphrag.components'` under installed 1.14.1 (0 tests collected, exit 2).
- GREEN: the contract alone passed 1/1 on LXC100 under installed 1.19.0.
- Focused verification: 10/10 passed across `test_neo4j_graphrag_119_contract.py`, `test_official_graphrag.py`, and `test_code_graph.py` in 0.17s; installed-version assertion printed `1.19.0`; banned-pattern validation passed.
- Overlay diagnostic: copying the production virtualenv preserved a stale `pytest` shebang pointing at `/opt/ragweld/.venv`. The false 1.14 import result was isolated by comparing the console-script interpreter with `uv run python`; final evidence uses the overlay's `.venv/bin/python -m pytest` and imports 1.19.0 from the overlay.

### DeepSeek V4 Flash review

- Response id: `gen-1788203692-CzLk2WXmG1WaQ4qod8q6`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Usage: 588,008 prompt + 1,197 completion = 589,205 tokens.
- Cost: `$0.0401268392`.
- First verdict/findings: FAIL. It raised five P1 and two P2 concerns: lock revision, Neo4j driver major, pypdf movement, missing runtime blocking test, ledger scope, scanner coverage, and GitNexus count scope.
- Accepted finding: unconstrained resolution selected Neo4j driver 6.3.0 even though GraphRAG 1.19 supports driver 5.28.4+. A new RED contract test proved the unwanted major (expected 5, got 6); `pyproject.toml` now pins `neo4j>=5.28.4,<6.0.0`, resolution selected 5.28.5, and 12/12 focused plus live Neo4j tests passed.
- Rejected findings with evidence: GraphRAG 1.19 itself requires `pypdf>=6.14.2,<7`; uv documents lock `revision` as backward-compatible metadata; the approved plan explicitly assigns the actual event-loop write characterization to Task 4, requires this ledger, requires the GitNexus count refresh, and prescribes `uv lock`; `check_banned.py` scans `tests/**/*.py`, while the exact repo-wide deprecated-import search is empty.
- Re-review response id: `gen-1788204208-xNw1UF1KUwEzcmJERvRc`.
- Re-review usage: 589,295 prompt + 1,976 completion = 591,271 tokens.
- Re-review cost: `$0.04800554724`.
- Final verdict: **PASS**.

## Task 2 - Corpus graph policy

Status: complete

### Pre-edit impact analysis

- `GraphStorageConfig`: CRITICAL, 96 direct / 121 total backend dependants; generated interface 94 direct / 141 total.
- `GraphSearchConfig`: CRITICAL, 96 direct / 121 total backend dependants; generated interface 94 direct / 141 total.
- `GraphIndexingConfig`: CRITICAL, 96 direct / 122 total, eight indexed flows; generated interface 94 direct / 141 total.
- `_run_index_body`: LOW, one direct / five total, `start_index` flow.
- `_run_index`: LOW, two direct / five total.
- `estimate_index`: LOW, no indexed upstream caller.
- `_background_index_job`: LOW, one direct caller (`start_index`).
- `extract_semantic_kg_with_graphrag`: LOW, one direct / four total.
- `IndexingSubtab` and `RetrievalSubtab`: LOW, each one direct caller through `RAGTab`.

The CRITICAL config blast radius was reported before mutation. The change is guarded by boundary serialization tests, generated-contract validation, API tests, TypeScript compilation, build, and a real headed browser flow.

### TDD and verification evidence

- RED 1: policy suite failed collection with `ModuleNotFoundError: server.indexing.graph_policy`.
- RED 2: the semantic ceiling contract failed import because `require_graph_chunk_ceiling` did not exist.
- GREEN: 128/128 focused policy/config/API/indexing/status/GraphRAG tests passed on LXC100.
- Six affected live integration modules collected 11 tests successfully after removed-field cleanup.
- Generated TypeScript validation, glossary mirror validation, banned-pattern check, TypeScript lint, and Vite production build all passed.
- Headed Playwright on the isolated overlay API/UI: 1/1 passed in 5.0s. Visible external corpus badge was `Semantic entity graph`; visible selection of `recall_default` changed it to `Excluded internal corpus`, disabled graph enablement, and removed semantic settings.
- Replacement search: no removed graph-config field remains in production/config/generated/UI code. Only negative assertions and the stale-key API regression payload retain removed names.

### DeepSeek V4 Flash review

- Response id: `gen-1788206832-mje3prsndu5MmjwKOXgt`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Usage: 23,220 prompt + 11,176 completion = 34,396 tokens.
- Cost: `$0.005104064`.
- Findings/fixes: no P1/P2 findings.
- Final verdict: **PASS**.

## Task 3 - Reviewed per-corpus schema

Status: complete

### Pre-edit impact analysis

- Backend `IndexRequest` and `IndexEstimate`: HIGH, 28 direct / 124 total dependants.
- Generated `IndexRequest` and `IndexEstimate` interfaces: CRITICAL, 94 direct / 141 total dependants.
- `GenerationManifest`: MEDIUM, 12 direct / 49 total dependants.
- `PostgresClient.promote_staging_index`, `start_index`, and `IndexingSubtab`: LOW.
- `_background_index_job`, checked separately before manifest metadata wiring: LOW, one direct caller and one affected process.
- The new `build_proposal_from_corpus` symbol does not exist in the pre-task graph and therefore reports UNKNOWN until the post-task GitNexus refresh.

The HIGH/CRITICAL public boundary blast radius was reported before mutation. Containment is generated-contract validation, API/model tests, live Postgres locking proof, TypeScript compilation/build, and the headed operator flow.

### TDD and verification evidence

- RED: missing schema module/models, then a semantic start without an approval hash entered the run path instead of returning typed 409.
- Live RED: the first real proposal exposed an incomplete low-level chunker call. Production now uses public `Chunker.chunk_file`, and an API regression exercises the real chunker over two sampled documents.
- DeepSeek first review found one P1: blocking inventory iteration and chunking in the async proposal path. A new boundary test reproduced both on the API loop thread; both now run through `asyncio.to_thread`.
- GREEN after the review fix: 103/103 focused schema, manifest, proposal API, event-loop, config, official GraphRAG, and batching tests passed on LXC100 in 2.92s.
- Real Apollo subset after the review fix through the production `deepseek.deepseek-v4-flash` alias: 1/1 passed in 54.65s. It proves real inference, persisted readback, stable reuse, concurrent locked meta merge, missing/stale approval refusal, and Recall exclusion.
- Generated TypeScript and validation passed for 238 registered public models. TypeScript lint and Vite production build passed.
- Headed Playwright after the review fix against the isolated overlay API/UI, no request interception: 2/2 passed in 1.9m. The operator visibly reviewed all schema sections and exact hash, approved, observed a real index start response, stopped the disposable run, and cleanup left no test corpus.

### DeepSeek V4 Flash review

- First review response id: `gen-1788211612-951KoeTi1yBvk5K4akSg`.
- First review verdict: FAIL, one P1 for blocking inventory/chunking inside the async proposal API.
- Fix: both operations moved through `asyncio.to_thread` with a direct loop-thread regression; all focused/live/browser evidence above was rerun.
- Re-review response id: `gen-1788212397-HELcFZ95gFV34778jSOB`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Re-review usage: 25,860 prompt + 6,361 completion = 32,221 tokens.
- Re-review cost: `$0.00540148`.
- Final verdict: **PASS**.

## Task 4 - Official pipeline and lexical graph

Status: complete

### Pre-edit impact analysis

- `_run_index_body`: LOW, one direct / five total dependants, one `start_index` flow.
- `_write_code_graph`: LOW, one direct / five total dependants.
- `extract_semantic_kg_with_graphrag`: LOW, one direct / four total dependants.
- `write_lexical_graph_with_graphrag`: LOW, one direct / five total dependants.
- `Neo4jClient.upsert_graphrag_graph`: LOW, three direct / nine total dependants.
- `Neo4jClient._upsert_graphrag_nodes` and `_upsert_graphrag_relationships`: LOW, one direct / seven total dependants each.
- `extract_code_graph`: LOW, one direct / four total dependants.
- `start_index`: LOW, no indexed upstream caller.

The first incremental GitNexus update for this task exposed null bytes in the derived index and produced a false CRITICAL blast radius. The derived index was cleaned and fully rebuilt before the exact impacts above were accepted: 18,623 nodes, 39,387 edges, 746 clusters, and 300 flows.

### TDD and verification evidence

- RED: the new official-pipeline contract tests failed collection with `ModuleNotFoundError: server.indexing.graphrag_pipeline`.
- GREEN: 32/32 focused official pipeline, lexical/code graph, API batching, corpus-root, and schema endpoint tests passed on LXC100 in 27.70s; the banned-pattern gate and Ruff passed first.
- Direct live coverage: eight Neo4j integration tests passed in 283.06s across semantic writer, code writer, graph community compatibility, and a deterministic 10,000-node event-loop ticker.
- Full API promotion: 1/1 passed in 97.92s through the production `deepseek.deepseek-v4-flash` alias. A single acceptance document crossed the real ten-chunk vector batch boundary; the promoted manifest retained approved schema metadata and the graph proved complete per-file `FROM_DOCUMENT`/`NEXT_CHUNK` chains, official `FROM_CHUNK`, no chunk embeddings, and no legacy `IN_CHUNK`/`IN_COMMUNITY` relationships.
- Blocking boundaries: synchronous Neo4j GraphRAG driver calls, file inventory/stat/stream reads, chunking, code source reads, and writer execution now run off the API event loop.

### DeepSeek V4 Flash review

- Response id: `gen-1788217082-fGdvujDsB3EUEqZ1Ongt`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Usage: 33,082 prompt + 10,433 completion = 43,515 tokens.
- Cost: `$0.00428239224`.
- Findings: no P1/P2 findings. Five P3 notes covered the still-used `neo4j` cleanup parameter, a source boundary assertion already backed by real Apollo/full-index execution, deletion of a mock-heavy proposal unit test superseded by those live tests, pinned 1.19 pipeline-store cleanup used to bound per-file memory, and no-op semantic writer finalization under `clean_db=False`.
- Final verdict: **PASS**.

## Task 5 - Resolution and promotion invariants

Status: complete

### Pre-edit impact analysis

- `SinglePropertyExactMatchResolver`: external dependency boundary, not present in the repo graph; UNKNOWN until wrapped by the new scoped symbol.
- `_run_index_body`: LOW, one direct / five total dependants, one `start_index` flow.
- `Neo4jClient.get_graph_stats`: LOW, two direct / five total dependants, two API processes.
- `start_index`: LOW, no indexed upstream caller.
- `GenerationManifest`: MEDIUM, 12 direct / 49 total dependants.
- Backend `IndexRunSummary`, `GraphGenerationMetadata`, `GraphResolutionTelemetry`, and `IndexRequest`: CRITICAL, 30 direct / 125 total dependants each.
- Generated `IndexRunSummary`: CRITICAL, 94 direct / 141 total dependants.
- `_background_index_job`: LOW, one direct dependant and one `start_index` flow; `_publish_complete`: LOW, one direct / three total; `_run_index`: LOW, two direct / five total.
- `IndexingSubtab`: LOW, one direct caller through `RAGTab`.

The CRITICAL public model surface was reported before mutation. Containment is generated-contract validation, replay/API coverage, the live refusal/override matrix, TypeScript compilation/build, and visible browser proof.

Post-task GitNexus refresh completed at 18,738 nodes, 39,779 edges, 749 clusters, and 300 flows. `detect-changes --scope compare --base-ref main` reported MEDIUM risk across 45 symbols and one affected `IndexingSubtab → Api` flow, matching the reviewed public-boundary/UI scope.

### TDD and verification evidence

- RED 1: the invariant/resolver suites failed collection because `server.indexing.graph_invariants` and `resolve_staged_entities` did not exist.
- RED 2: persisted run replay dropped graph verdict/telemetry because `IndexRunSummary` did not own those fields.
- RED 3: 20 spaces passed the override reason's raw length constraint; a field validator now trims and requires 20 visible characters.
- Core GREEN: 54/54 focused invariant, official pipeline, generation metadata, run summary, replay, batching, corpus-root, schema, and metrics tests passed on LXC100 in 29.15s; banned-pattern and generated-type validation passed first.
- Live GREEN: the resolver plus full promotion/refusal/override matrix passed 10/10 in 39.43s after moving new Cypher subqueries to the non-deprecated scoped syntax. It covers official resolver isolation across two colliding generations, all eight typed mutation failures with the prior manifest unchanged, a real DeepSeek semantic run refused for zero entities, its anonymous override rejected before the fence, and its authenticated override promoting chunk/vector retrieval only with audited metadata.
- Mixed code corpus regression: RED showed a non-AST Markdown file was skipped by the code graph writer (`attempted_chunks=0`); GREEN writes its official lexical Document/Chunk graph while reserving AST entities for supported languages (1/1 in 0.26s).
- Normal semantic promotion: an inference-driven schema proposal made the first final rerun honestly refuse a zero-relationship graph. The success-path fixture now persists a fixed approved domain schema and uses explicit repeated `Person WORKS_FOR Organization LOCATED_IN Location` facts, separating pipeline/promotion proof from Task 3's already-covered proposal inference. The corrected multi-batch run passed 1/1 in 88.61s.
- Generated types remained in sync for 238 registered models. TypeScript lint and the Vite production build passed after the final UI correction.
- Headed in-app browser against isolated overlay API/UI: page identity `RAG · Indexing — task5-refusal-browser — ragweld`; visible refused state showed exact schema, 1/1 successful extraction, zero entities/relations/provenance, zero duplicate groups, no community phase, typed failure codes, and the prior error state after reload. The drive found and fixed a reloaded-page retry bug by reusing the persisted approved schema hash. A 20+ character reason enabled the retry and opened the danger-styled audited override confirmation; cancelling left the run in error and started nothing. No application API console errors were present; isolated-dev Faro receiver noise and the pre-existing Three.js duplicate-instance warning were unrelated.
- Disposable browser and leaked failed-fixture corpora were resolved by exact id and deleted; a read-back found no `promotion-active-*`, `promotion-refusal-*`, `pipeline-index-*`, or Task 5 browser corpus left behind.

### DeepSeek V4 Flash review

- Response id: `gen-1788219968-RUcoQvsC88LhAr3AqaRc`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Usage: 25,973 prompt + 5,880 completion = 31,853 tokens.
- Cost: `$0.00528262`.
- Findings: no P1/P2 findings. Two P3 notes covered the scoped Cypher literal and APOC use. The literal receives only the strict server-generated staging-id allowlist and is the exact installed-1.19 `filter_query` contract required by the approved plan; APOC is already required by the official resolver's `apoc.refactor.mergeNodes`, so neither is an unowned production dependency.
- Final verdict: **PASS**.

## Task 6 - Qdrant-seeded traversal

Status: pending

## Task 7 - GDS Leiden communities

Status: pending

## Task 8 - Full verification, deployment, reindex, browser acceptance

Status: pending
