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

Status: complete

### Pre-edit impact analysis

- `QdrantChunkStore.write_chunks`: CRITICAL, one direct / 327 total dependants across 55 indexed processes.
- Nested `TriBridFusion._search_single_corpus`: CRITICAL, one direct / four total dependants across 51 indexed processes.
- `Neo4jClient.chunk_vector_search`, `expand_chunks_via_entities`, and `entity_chunk_search`: HIGH, one direct / three total dependants across four indexed processes.
- Backend `ChatDebugInfo`, `GraphSearchConfig`, and `GraphIndexingConfig`: CRITICAL, 96 direct / 123 total dependants each.
- `build_chat_debug_info`: CRITICAL, three direct / 313 total dependants across 55 indexed processes.
- `chat_once` and `chat_stream` were not independently named in the current index, but their two aggregation blocks were treated as the same public debug boundary.

The CRITICAL config/retrieval surface was reported before mutation. Containment is the exact Qdrant payload gate, strict staged-id Cypher, real retained-generation collision proof, typed outage matrix, generated contracts, chat debug regression, and frontend compilation/build.

### TDD and verification evidence

- RED: the new unit/live contract suite failed collection with `ModuleNotFoundError: server.retrieval.graphrag_retriever`.
- Qdrant join GREEN: 8/8 official constructor/query and real payload tests passed. Every staged point receives top-level `graph_join_id=<staged graph id>:<raw chunk id>` only after the Haystack write; promotion now requires its exact count to equal the indexed chunk count.
- Real collision/no-double-credit GREEN: two retained physical collections and graphs reused identical raw chunk ids but different generation-qualified joins. Fresh official `QdrantNeo4jRetriever` calls selected only the manifest collection/graph, excluded every Qdrant seed, traversed `FROM_CHUNK` plus bounded entity relationships, exercised both zero and nonzero `NEXT_CHUNK` windows, and hydrated exact active content from Postgres. The same proof passed through `/api/search` with exact new integer debug fields and no legacy entity-hit field.
- Required-leg/config/API matrix: 43/43 passed in 172.91s across unit contracts, runtime capabilities, index batching, Qdrant, graph hydration, required-leg failures, and asymmetric Qdrant/Neo4j outage attribution.
- Chat public boundary: 3/3 passed; Recall contributes no graph counts and `ChatDebugInfo` exposes seed/resolution/relationship/community/hydration counts.
- Final focused retriever run: 8/8 passed in 36.57s, including the official neighbor-query branch. Changed-file Ruff, banned-pattern validation, generated-type validation, TypeScript lint, and Vite production build passed.
- Obsolete production search is empty for `IN_CHUNK`, `fusion_graph_entity_hits`, `chunk_vector_index_name`, `chunk_seed_overfetch_multiplier`, Neo4j vector search, and entity text-search implementations. Removed persisted names remain only in the explicit config migration strip list; tests retain negative assertions.

### DeepSeek V4 Flash review

- First response id: `resp_z7JsWI6rvuFH2ZxTJGPZHX8lu2kgptToJPBeaceFxYF_jdor_1yEeyw3Q8FbC3XOxkB-aXJ8aN-PAjoe8rTYo78kLBd87NY-OdCaA6kPwEoR-EwVS-yXJtvewBwMpwOeoNNeEiYO5zThyXkoyFzpVJ85ecvWFrQOboawSsKggd2Fca6E1J6iD_m0mq7d9u5hGjBVa_5yFmCL-hG3NXMQtku8GYP1MJOh0Ay3JLQ_Grfm8f5Q_F9larl47PTKuiZH_CpqkyZjm7-JAPDASCfH6BvsVKiqKh2b4tz_0hmWxEBBW-ZeRhsVzxJrbj644xJn5UwOOHlC2MJ18XgOQu6rNKU_Umt9g6Q-PgH0Z3kxAqS-zckX5o9dz-eKLwOV2BmC6TC7_ELKNfAKdkFoDSHZpgvysK89uEyioqFlZD8lXXJYbCaWZspUFZkXpVxndQ==`.
- First verdict: FAIL because the normal tracked-file diff omitted all untracked new files. It therefore incorrectly inferred that `resolved_entity_ids`, `QdrantChunkStore.url`, and client cleanup were absent.
- Resolution: resubmitted the tracked diff plus full `/dev/null` diffs for every new source/test and the existing store constructor. The visible code proved the optional entity-id evidence field, `self.url` initialization, and Qdrant/Neo4j closure in `finally`; no implementation defect existed.
- Re-review response id: `resp_5sP2G879VzvOebDr1MTmxudhmebVBRgoKhh-lBg2NDcel3FWP9l7TauNv3bk_sliUsmMsSP4sE6tLaakCD19vza12uLQI29Tq7aDaIMIa3GHT15m5jkl1R_JeiVQSb-Y3mQlUXAtM3x27lXpoXiinnyXAFM1BXI3MP6wIZ5Bxpm3FpoliG9tu-y21kDGvawM2TRVqVPMC71xsou51LNSvAvTEKDij9GwFPdE1zOuE6FQjPKHulXhsEqweTdM3_BCa3Pwfil0LRYkmAewwEzZUVYNWWP4i4tXvkktg4dFignpYR-4kfkjgogQTQPdvwqvX6DPlmKk8E_629nNh1m1MZ-Nkrdjtp5n-J3ipDHBGnwfjiX20WVgojs5pgy5iTBMzAfGFu9LFf9uHerrJsbnoxV_z3MUFxgnNDiVjWf4FxDgocVM2PECu0ynZBkb3Q==`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Re-review usage: 36,981 input + 7,567 output = 44,548 tokens.
- Re-review cost: `$0.0072961`.
- Final verdict: **PASS**.

### GitNexus scope gate

`detect-changes --scope compare --base-ref main --repo ragweld` reported CRITICAL risk across 26 files, 62 indexed symbols, and 17 affected flows. The named flows are the expected search, benchmark, evaluation, generation, cache-key, and fusion paths reached through `_search_fused`; the public config/debug blast radius matches the pre-edit warning and the verified Task 6 scope.

## Task 7 - GDS Leiden communities

Status: complete

### Pre-edit impact analysis

- `Neo4jClient.detect_communities`: LOW, no indexed upstream caller; `_store_communities`: LOW, one; `_modularity_groups`: UNKNOWN.
- `Neo4jClient.get_communities`, member/subgraph methods, and `list_communities`: LOW or UNKNOWN with the Graph Explorer route as the bounded consumer.
- `Neo4jClient.get_graph_stats`: CRITICAL, 224 total dependants across 55 indexed processes.
- Backend `GraphStorageConfig`: CRITICAL, 96 direct / 123 total dependants; the removed generated config field shares the public generated-type blast radius recorded in Task 2.
- `useGraph` and `GraphSubtab`: LOW, each bounded by the `GraphSubtab` flow. The pre-existing filter-state defect found during the headed drive was fixed across `useGraphStore`, `useGraph`, and `GraphSubtab` under that same surface.
- `_probe_neo4j_readiness` and the new Leiden symbols were not named in the pre-task graph and reported UNKNOWN.

The CRITICAL stats/config blast radius was reported before mutation. Containment is the derived-view API contract, generated types, deployment/readiness tests, real GDS 2.13.7 execution, failure cleanup, out-of-scope sentinels, and the no-interception headed Graph Explorer drive.

### TDD and verification evidence

- RED: the new Leiden contract failed collection with `ModuleNotFoundError: server.graph`. The first real GDS run then failed with the installed 2.13.7 error that Leiden only runs on an undirected graph, proving reciprocal directed arcs alone were insufficient.
- Deployment GREEN: a disposable `neo4j:5.26.20-community` instance installed observed GDS `2.13.7`; its health transitioned to healthy only after the exact `gds.version()` probe matched `2\.13\.`. Compose now installs APOC plus Graph Data Science and allowlists/unrestricts `apoc.*,gds.*`; application readiness fails closed when communities require missing/wrong GDS.
- Algorithm GREEN: the approved scoped bidirectional weighted Cypher projection is converted through the documented `gds.graph.relationships.toUndirected` procedure with `SINGLE` aggregation, then weighted hierarchical Leiden writes `communityPath` with seed 19 and concurrency 1 and derives `communityId`. Unique projection names are dropped in `finally` on success and failure.
- Live GREEN: 3/3 real Neo4j integration tests passed on GDS 2.13.7 in 5.95s. Two weighted cliques remain two identical final communities over repeated runs; an AST relationship graph receives communities; an out-of-scope sentinel remains untouched; no `Community`/`IN_COMMUNITY` ontology exists; and a real temporary uniqueness constraint forces a post-Leiden write failure, proves projection removal, then proves a clean retry. The final review fix deliberately removes `repo_id` from one internal edge and still preserves the stable partition.
- Focused final gate: 179/179 deployment, config, readiness, generated-contract, metadata, graph-stats, and graph-API tests passed in 15.93s. Ruff, banned-pattern validation, generated-type validation, `uv lock --check`, TypeScript compilation, and Vite production build passed. The unused direct `types-networkx` dev dependency and every Ragweld NetworkX/Louvain community implementation are gone.
- Headed Playwright against an isolated overlay API/UI and disposable GDS, no request interception: 1/1 passed in 7.8s with a retained trace. It selected the real six-entity/seven-edge/two-community corpus, clicked a derived community, selected a member and expanded its neighborhood, changed hops, exercised entity and sole-relationship filters, zoomed in/out, fit, panned, reloaded, and selected the second community.
- The browser drive found a real pre-existing filter contradiction: unchecked boxes represented the empty-array sentinel that also meant “show all.” The local store now models all as `null` and none as `[]`; both entity and relationship controls render and filter truthfully, including the one-relationship-type edge case. The same drive removed a React border shorthand/non-shorthand warning. The disposable corpus and graph were deleted by exact id afterwards.
- Obsolete production search is empty for persisted `Community` nodes, `IN_COMMUNITY` writers, `_store_communities`, `_modularity_groups`, Louvain calls, and `community_algorithm`. Removed config names remain only in migration strip lists and negative tests.

### DeepSeek V4 Flash review

- First response id: `resp_C-uf_8inDGodZGImUQKaZ7zp1lUMo2G48MxouUkfOqd3oyQrYx_hnsxocdSrhXOS6PafnO_Fe9Ii2g4S6bHrgteOpPb3O48JcxIEyvMoPGuCgO_4w90xcmbsddNODi44P_w91jK7qmkSgVP8eXk3-kDQFhw-_pTh-PRPSWycQPxvzu5xmFhLf0W5lo4rjR1lop5g8z7VG8iA6pPYBlZbKdfnZurTHDCwJA6HKnW4aSPgaHAFjxH3uwoNKm2-wEmnl2QTXvYkVqTNjEYM89_9T6mBLz9NHigXnBA1_3RCcrLdz0L4DnFKEedpAhQaxVlnyw6sABXKlih56AnNTtoN1u95DiGH88lp22eDbCSP-wXvQShyx6rNh0ykT7wm_h29rsbqyMWnp6Wca2yC7hHSctw-viNUHZ98uzx_fQNL5E7MC_9dkOlZvyJdjSc2mQ==`.
- First verdict: FAIL, one P1. The relationship projection redundantly required `r.repo_id`, which excluded an otherwise correctly scoped legacy internal relationship whose two endpoint entities had the staged repo id.
- Fix: both relationship-property predicates were removed; endpoint scoping remains strict. A unit assertion forbids their return and the live weighted-clique regression strips the property from one edge before two successful stable detections.
- First re-review response id: `resp_3eEwbf5sO1dkqF7hSQUoxx8BxhaRcbJkGJBNeoWTFhQFs2I7acz_GCqBNDRKrvWsAgYHlJGyv6f8ppWbvTDP78etPVOxUY8wWRLzjcEI4aM724rLrOXh47iQ7gcR8JHVQkKx0hJwBWlAKsdxOWPgnnjP_IasUoECyc68pgWaYH1zrH5MZp_QmEZu7RLnz6elx7MGxsug8Fl9dqNPpz2Cnhhe_i7wYNgaFR-a2EiBLwXCQQhAgflKQd0VVa8nzXop4m1Oh0WQLY7YqqF_2czRGzuTUoSDyWcu18YOgjAjDMPydRUzNze0ZNJ_u0YG2pKyZUrprgBUfbTyI4hvJ_LiC5f7V_9nvSzWTJ0pDUtKWb8dpSL-q3xK7ssCaDJkgwbFe9UJw9z1mDBKsF7I_OQ9JAzgu_e6kap8IBHnTumADqf05xZR9VmpY0MpNC5u6Q==`; it exhausted its 10,000-token reasoning ceiling and returned no verdict, so it was explicitly rejected as non-PASS.
- Completed re-review response id: `resp_tSE-nxX8Y5W_YZRYmvUMz_Sm1pf25oWpXVsAINfXjLE0Ya6uJj65fmx4btkWkhdDbGhKN5A-tNDSJB6yAWdUas8nbZsajR1quE_ah1Bzje_EPGlilCbM2QRaDXxXQ4CQVfMBezknkqS6XaNKvnV0r4SpHfTksWtvrwz7wmeTa6uNSn4ROZK3HdIaIh46CR2lnkLKOWhpv0udlTsdaWXSgiT06e-gwfBcUk5Cwj7Kqb23C8x80ZKUlGV_daB4pbGsju7Rqo6CbhXHF6buSf8rbc3u9s-4j3XNfR-eBVHlqZvOCV1ACO0MnFOCMPcsrrrjJ1yjhaa0yP_tD6pMIjGXoFwbWmZNgV87Erca47oLZqBydEXO9PwVSj-5fssoiyqaeW42gvoy159CMZIwzcT8mi13iruH_cTSE9r7PiH_JkKBXa8XjQ8mtsbV2CImcQ==`.
- Resolved model: `deepseek.deepseek-v4-flash`.
- Completed re-review usage: 21,902 input + 873 output = 22,775 tokens.
- Completed re-review cost: `$0.0050883`.
- Final verdict: **PASS**.

### GitNexus scope gate

`detect-changes --scope compare --base-ref main --repo ragweld` reported MEDIUM risk across 19 tracked files, 34 indexed symbols, and three affected Graph Explorer flows (`FailureDetail`, `LoadStats`, and `LoadCommunities`). This matches the reviewed Neo4j derived-view, config migration, readiness, and Graph Explorer scope. New untracked Leiden source/tests are separately present in the complete DeepSeek diff and commit inventory.

## Task 8 - Full verification, deployment, reindex, browser acceptance

Status: in progress

### Frozen requirement/evidence matrix

This table is the completion authority for Task 8. `Pending` may become `Proves` only with the named fresh output; no passing lower-level substitute closes a browser or deployment row.

| Requirement | Exact required proof | State |
|---|---|---|
| Neo4j GraphRAG 1.19 source contract | Task 1 PASS plus full-gate installed-version/import contract (`test_neo4j_graphrag_119_contract.py`) | Proves; fresh full gate passed |
| One external semantic/code policy and truthful defaults | Task 2 PASS, full `test_graph_policy.py`/config/API gate, visible NASA/Epstein semantic badges and code badge | Proves: Task 2 PASS + gate; live NASA/Epstein pages show `policy: semantic` badges and the code page shows the **Code AST graph** badge with the AST weights (click ledger 00:12 09-02, `2026-09-02-code-indexing-ast-policy-weights.jpg`) |
| Recall exclusion | Policy/API tests plus live Recall UI showing excluded graph policy with no graph start path | Proves: live Indexing page for `recall_default` shows "Excluded internal corpus", graph toggle disabled, no semantic settings or Generate control (2026-09-01 20:18 UTC, `2026-09-01-recall-01-excluded-policy.jpg`) |
| Reviewed per-corpus schema proposal and persistence | Task 3 PASS, live NASA and Epstein visible generate/expand/approve dialogs, schema hash in run metadata and after reload | Proves: Task 3 PASS; live NASA Luna proposal generated/expanded/approved with the cost dialog (`2026-09-02-nasa-luna-proposal-expanded.jpg`, `…-cost-dialog.jpg`), Epstein proposal reused with hash `ee12e83e…`; both hashes persist in `runs/latest` and on reload (`…-reload-promoted.jpg` for both corpora) |
| Correct official lexical names | Full live GraphRAG/store query: `FROM_DOCUMENT`, `NEXT_CHUNK`, `FROM_CHUNK`; zero `IN_CHUNK` | Proves: store audit 01:22 09-02 on the three promoted generations shows only `FROM_DOCUMENT`/`NEXT_CHUNK`/`FROM_CHUNK` plus schema/AST edges, `IN_CHUNK` = 0 store-wide |
| Official Pipeline and scoped writer | Task 4 PASS, full gate, promoted per-corpus graph metadata/store scoping | Proves; fresh live/batched gate passed |
| Exact-match scoped entity resolution | Task 5 PASS, live run resolution telemetry and zero duplicate groups/cross-generation edges | Proves: Task 5 PASS; live run records `ca5b8d92` (8,956 → 3,003, merged 5,953, duplicate groups 0), `3054ecc2` (306 → 162, merged 144, 0), `43efdd0a` (6,242 → 6,242, merged 0 under the `entity_id` key, 0); zero edges leave any generation; 83 distinct `__init__` entities in the code graph (D7) |
| Fail-closed promotion and RED matrix | Task 5 mutation matrix plus Task 8 visible temporary-corpus refusal, operator hint, no promoted generation/completed badge after reload | Proves: Task 5 mutation matrix + D14 live test; visible negative proof on `task8-negative-graphrag` (5 s timeout → `Request timed out.` / `extraction_failure`, `PROMOTION REFUSED` after reload, corpus deleted through the registry dialog: click ledger 21:48–21:53 09-01); the real Epstein D12 refusal and the code D14 refusal also left the previous generations active |
| Qdrant-seeded traversal and no double credit | Task 6 PASS, retained-generation collision test, live graph search debug fields/API equality and no `fusion_graph_entity_hits` | Proves: Task 6 PASS; live chat footers and Routing Trace disclose `fusion_graph_qdrant_seed_chunks` / `…relationship_expansion_hits` / `…hydrated_chunks` per corpus (NASA 30/30/30, code 30/30/30, Epstein 30/30/30) matching the recorded `/api/search` payloads (6/6/6 each, JSONs in the evidence dir); `fusion_graph_entity_hits` absent everywhere |
| GDS 2.13 deployment | Task 7 PASS, deployed `gds.version()`=`2.13.x`, Neo4j/APOC/GDS readiness, deployment marker | Proves: `/api/ready` true with Neo4j 5.26.20 + GDS 2.13.7 on every deploy (8a4d20c9, c8df2373, b452d435); NASA 215, code 479, negative-fixture 3 Leiden communities written live |
| Weighted deterministic Leiden, including code | Task 7 semantic/code/failure live tests plus nonzero NASA/Epstein/code `communityPath`/`communityId`, counts, derived API/UI after reload | Proves: deployed runs report `gds-leiden-2.13` communities — NASA 105 (modularity 0.889), Epstein 1,142 (0.608), code 276 (0.835) — and the explorer lists/derives them after reload on every corpus (community drives in the click ledger) |
| Dead-surface replacement | Repo search, live Neo4j zero obsolete ontology/vector/embedding state, config/generated UI absence | Proves: repo audit 2026-09-01 (no `IN_CHUNK` writer, `graph_entity_hits`, `IN_COMMUNITY`, `Community` nodes, NetworkX/Louvain; removed config names only in migration strip lists); live store: 0 `Community` nodes, 0 `IN_COMMUNITY`/`IN_CHUNK` edges, 0 chunk embeddings, 0 cross-generation edges, 0 leftover GDS projections; regenerated contract bundle no longer carries `semantic_kg_allowed_entity_types` |
| Per-task and final DeepSeek reviews | Recorded PASS for Tasks 1-7 plus final complete spec-to-main integration PASS after full gate | Tasks 1-7 prove; final pending |
| Full LXC quality gate | Exact Task 8 surfaces: dependency sync, generators, docs ownership, Ruff, mypy, complete 1,989-test collection, TS/build, headed policy/explorer | Proves predeploy through bounded batches; live GDS browser row deferred to postdeploy |
| Push/deploy parity | Mac `HEAD`, `origin/main`, LXC `HEAD`, deployment marker and serving runtime hash identical; clean one-worktree state | Proves for 8a4d20c9, c8df2373 and b452d435 (all four hashes identical at each deploy, `/api/ready` true); the five later commits (0f79a7c3, 17f208b9, f1b613db, 27e28df6, 6d59e05e) are pushed and await the post-Epstein deploy |
| NASA visible rebuild and drive | Screenshot/click ledger: visible schema review/approve/cost/run telemetry/reload, three node types, two neighborhoods, all controls, community, graph search/debug | Proves: Luna rebuild through visible controls (alias change, proposal review, cost dialog, run `3054ecc2`, reload) and the explorer drive (initial graph, three node types, two neighbourhoods, zoom/pan/fit, hops, type/relation filters, community, name search, table properties/provenance, hard reload) — click ledger 22:04–22:26 09-01 and 00:16–01:17 09-02, screenshots `2026-09-01-nasa-explorer-*.jpg`, `2026-09-02-nasa-*.jpg`; chat graph question with footer disclosure 22:01 09-01 |
| Epstein visible rebuild and drive | Same complete screenshot/click/search/debug ledger with flight/communication question | Proves: force rebuild through visible controls (run `ca5b8d92`, D2 panel proof, reload), explorer drive 00:27–00:30 09-02 (`2026-09-02-epstein-explorer-*.jpg`), visible flight/communication chat question with footer + trace disclosure 01:19 09-02 (`2026-09-02-chat-epstein-graph-footer-30-30-30.jpg`) and the recorded `/api/search` JSON |
| `ragweld_code` visible rebuild and drive | Visible code policy/AST types/weights/run telemetry, same full Explorer/search/reload ledger | Proves: visible code policy/AST weights, Index Now dialog, run `43efdd0a` (telemetry: 6,242 entities, 0 merged, 276 communities), explorer drive 00:19–00:27 09-02 (`2026-09-02-code-explorer-*.jpg`) incl. hop limit 22 vs 104 nodes, filters, community, provenance/properties, reload; `/api/search` JSON |
| Deferred Recall Intelligence Graph | Spec section 15 is the owned enterprise RBAC/Kubernetes/GCP roadmap phase and explicitly covers needs/misses/transitions, prompt/cache opportunities, role/team aggregates, tenant isolation, consent, de-identification, retention/deletion, audit, invalidation, anti-surveillance | Proves; roadmap audit complete |
| Final completion audit | Every row above classified `Proves`, with run ids, store counts, screenshot paths/timestamps, hashes, and no active/staged work | Pending |

### Predeployment full-gate evidence

- Static/type/docs GREEN: `uv sync --extra dev`; TypeScript generation and validation for 238 registered public models; banned-pattern and docs-ownership checks; repo-wide Ruff over `server tests scripts`; and mypy over 167 server files all passed on LXC100.
- The first monolithic `pytest -q --no-cov -p no:cacheprovider` attempt was terminated at roughly 42% after the worker retained about 3.6 GiB, LXC swap reached 6.6/8 GiB, and host load exceeded 600. Its failures were therefore treated as contaminated leads, not verdicts. The exact 1,989-item collection was rerun in deterministic file batches with the same flags, production Postgres/Qdrant/LiteLLM/Docling, a disposable Neo4j 5.26.20/GDS 2.13.7 lane, and `RAGWELD_LIVE_GATEWAY=1`.
- Python GREEN: 1,988 passed and one explicit platform skip (`test_mlx_lora_injection.py`: MLX native imports are not usable on Linux). No gateway, Postgres, Qdrant, Neo4j, GDS, or Docling test skipped. Unit groups were 975 pass + one rerun overlay Git-safety pass + 584 pass; API groups were 240 + 110; integration groups were 11 + 20 + 14 + the two promoted-lane tests + 31. The 10m23s promoted-lane test crossed schema-approved semantic indexing, stale-fence takeover, seven generation transitions, mixed retention, post-commit cancellation, MCP/search/chat metrics, tombstone repair, and deletion.
- Root causes repaired from the first full attempt: index-start persisted-state validation now precedes schema approval and is covered across POST plus five readers; the viewer no longer asks a disabled graph leg for hits while the deterministic generation-collision test carries exact Docling page/region provenance through Qdrant -> Neo4j -> Postgres -> API; promoted-lane semantic policy persists a fixed reviewed schema over explicit facts; and the Leiden failure-injection constraint uses a UUID-only label rather than the global `__Entity__` label. Exact live reruns passed.
- Frontend GREEN: TypeScript lint and the Vite production build passed. Headed Playwright, with no route interception, produced nine immediate passes, one expected predeploy skip for the not-yet-reindexed GDS corpus, and one truthful-readiness failure. The drive fixed stale `entity expansion` wording and added the live 1,315 indexed-chunk count to the no-entity-graph readiness card; the exact headed regression then passed in 2.3s. The remaining GDS-corpus test is required again after deployment/reindex.
- Replacement audit GREEN in executable surfaces: no production writer/query hit remains for `IN_CHUNK`, `fusion_graph_entity_hits`, `IN_COMMUNITY`, persisted `Community` nodes, NetworkX/Louvain community code, Neo4j vector search, or heuristic semantic-KG switches. `config_store.py` retains only the two intentional removed-key migration strips (`chunk_seed_overfetch_multiplier`, `chunk_vector_index_name`).
- Recall roadmap audit GREEN: approved spec section 15 remains the owned deferred enterprise phase and explicitly contains repeated needs, misses, exploration transitions, prompt/cache opportunities, cohort-bounded role/team aggregates, tenant/role visibility, consent/notice, de-identification, retention/deletion, audit logs, cache invalidation, and the anti-surveillance constraint. No Recall graph implementation is smuggled into this slice.

### Final DeepSeek integration review loop

- Complete-diff attempt `gen-1788231861-cyKR3PGnBtlHHEUANg3Z` consumed 999,731 prompt + 12,001 completion tokens (1,011,732 total, `$0.08284047436`) entirely as hidden reasoning and emitted no content. It is rejected as a non-review.
- The first larger retry `gen-1788232010-c7NHqJhDmGUkwnXCbEaK` returned an upstream connect timeout with zero usage/cost. It is rejected as a non-review.
- Complete-diff retry `gen-1788232138-HGjesOyVjNDQmQlJNhur` consumed 999,745 prompt + 24,000 completion tokens (1,023,745 total, `$0.1969525`) entirely as hidden reasoning and emitted no content. It is rejected as a non-review.
- The bounded final-integration packet preserved the complete inventory, Tasks 1-7 PASS ledger, all material production/deployment/API/UI seams, and the complete Task 8 diff while excluding lock/generated/mechanical lint noise. Response `gen-1788232718-j1jfghiyQMcDW0VQYZuu` resolved to `deepseek.deepseek-v4-flash`, used 234,470 prompt + 1,707 completion tokens (236,177 total; 1,344 reasoning), and cost `$0.03330376`.
- Verdict: **FAIL**, with five P1 completion blockers and no implementation defect: push/deploy parity, NASA visible rebuild, Epstein visible rebuild, `ragweld_code` visible rebuild, and postdeploy GDS-community browser acceptance remain pending. The reviewer explicitly concluded: “All other integration checks ... pass. The plan's implementation is correct; these remaining operational steps are required to declare full integration successful.”
- Resolution: commit/push/deploy the exact reviewed candidate, complete those five operational rows with store/browser evidence, then resubmit the completed integration packet. No code change is indicated by this verdict.

### Live NASA schema-proposal acceptance defect and review loop

- The first authenticated postdeploy NASA drive selected `NASA` on the visible RAG Indexing page, expanded the semantic-graph policy card, and clicked `Generate graph schema`. Cloudflare returned a visible 524 after the origin synchronously entered full Docling conversion for the single 359-page, 15.9 MiB Apollo 11 mission report; no proposal hash persisted. This was a production acceptance defect that the earlier nine-page extracted-Markdown fixture could not expose.
- GitNexus upstream impact for `build_proposal_from_corpus` was LOW: one direct caller (`propose_graph_schema`) and one affected API process/module. The correction adds a proposal-only PDF sampler: PDFs through 12 pages contribute all pages; larger PDFs contribute the first, middle, and last three pages with explicit page markers. PDF import/open/page/text/close failures return an empty bounded sample, and PDFs never fall through to full Docling/OCR in this synchronous edge request. Non-PDF proposal sampling continues through the established extraction path. If the corpus has no embedded PDF text or other sampleable text, the API now returns a typed 422 that directs the operator to indexing-time OCR.
- TDD RED reproduced the missing bounded sampler, the 12-page boundary error, and a 100-page image-only proposal request exceeding a 20-second outer kill. GREEN passed the generated 1/2/3/8/12/13-page matrix plus the image-only endpoint case: 7/7 in 0.76s. The complete non-egress schema-proposal slice collected 35 tests and passed pytest, mypy, Ruff, and the banned-pattern scan. A full real-Apollo gateway regression is present behind the existing live-gateway marker, but executing sampled mission-report text through the external model gateway remains intentionally unverified until that separate content-egress approval is explicit.
- First review response `gen-1788278390-YCwMCNiS21dhGwygBXrW` resolved to `deepseek.deepseek-v4-flash`, used 2,799 prompt + 4,893 completion tokens (7,692 total), and cost `$0.0009584736`. Verdict: **FAIL**. Its P1 found that post-open PDF exceptions could bypass the fallback; its P2 found that the fallback still recreated the original timeout for image-only PDFs; its P3 requested small-PDF, boundary, malformed/textless coverage. All findings were reproduced or covered and fixed.
- Re-review response `gen-1788278762-2ZOgeh0KbK8SgPcdZZuO` resolved to `deepseek.deepseek-v4-flash`, used 3,318 prompt + 2,120 completion tokens (5,438 total), and cost `$0.000846496`. Verdict: **PASS**, with no P1/P2 findings and all five correction claims verified.

### Live drive defects found after deployment (2026-09-01, continued by Claude/Fable after the Codex thread was paused)

Operator hand-off at 18:17 UTC: the Codex goal thread was stopped right after the NASA run
`c799bd43e94c4a1697ae355b5f9be0f9` completed (18:15:52 UTC, `graph_promotable=true`, 1,002/1,002 chunks,
2,992 entities, 2,112 resolved, 880 merged, 1,938 relationships, 215 Leiden communities, modularity 0.797,
$0.17). Mac/origin/LXC100/marker parity at `8a4d20c9` re-verified. The visible click ledger and screenshots for
everything below live in `output/task8-graphrag-acceptance/click-ledger-2026-09-01.md`.

- **Operator rule recorded mid-drive:** "do not use 4o it's 2026". The Codex NASA rebuild routed schema and
  extraction through `openai.gpt-4o-mini` after GLM (1,002/1,002 "improper format") and DeepSeek 0423 (empty
  schema) / 0731 (edge-cancelled) failed. The operator re-staged Epstein to `openai.gpt-5.6-luna`; the promoted
  NASA generation is still bound to the gpt-4o-mini schema `6667c8fe…c91b` and is listed as a residual below.
- **D1 (fixed):** Graph Explorer showed every NASA entity as "(concept)" and "1 nodes • 0 edges" for a
  `LaunchSite` that holds a `LOCATED_AT` edge in Neo4j. `server/db/neo4j.py` coerced labels outside an AST-era
  `Literal` to `concept` and filtered every edge through `ALL_RELATION_TYPES`; the approved schema's labels and
  relationship types were never in either vocabulary. Fix: `Entity.entity_type` / `Relationship.relation_type`
  are non-empty strings owned by the stored label (public contract regenerated, 298 exports), the closed
  vocabularies and `_coerce_entity_type` are deleted, no explorer query filters by edge type, and the
  neighbourhood walk is confined to `__Entity__` nodes of the generation so provenance edges can never bridge
  two entities through a Chunk. GitNexus: `_coerce_entity_type` LOW, both query methods LOW, `Entity` class
  CRITICAL (96 direct dependants = the shared generated-type blast radius, contained by regeneration + tsc).
  RED on LXC100: 3 unit failures + the new live test; GREEN: 59 unit, 4 live Neo4j/GDS tests (new
  `test_schema_labelled_semantic_graph_keeps_types_and_edges_in_every_explorer_view`), ruff, mypy,
  generate/validate types, banned scan, web tsc. DeepSeek V4 Flash review `gen-1788288811-5G9t0fcHBjx3dPMCYIFx`
  (`deepseek.deepseek-v4-flash`, 11,118 prompt + 6,829 completion = 17,947 tokens, `$0.002774912`):
  **PASS**, no P1/P2. detect-changes: MEDIUM, 7 files / 36 symbols / 3 Graph Explorer flows.
- **D2 (fixed, 0f79a7c3):** after Start indexing from the Indexing page, the "Current run" panel kept the
  previous run's id and its PROMOTION REFUSED metadata under the new `indexing` badge for the whole run
  (reproduced on the Epstein and code rebuilds). `IndexingSubtab.tsx`: a locally owned stream short-circuits the
  status poll and `loadLatestRunReplay` refuses while indexing, so `latestRun` only refreshed at stream end.
  Fix: clear the replayed run at local start and adopt the run id from the stream's "Indexing started …
  (run_id=…)" line via `runs/latest` (accepted only when the API names the same run); `index-run-id` test id.
  `web/tests/e2e/exhaustive/graph_policy.spec.ts` now polls `runs/latest` for the live id after Start and
  requires the panel to show it. RED against the production component (+ test id only): panel never showed
  `run_id: c382a462…`; GREEN with the fix: 2 passed in 29 s — both on LXC100 through an overlay Vite server
  (`VITE_API_PROXY_TARGET` → production API) with the real corpus fixture and Luna. DeepSeek V4 Flash review
  `gen-1788291447-ZovjOR80cKLUxIc8sCO9` (2,158 prompt + 3,672 completion = 5,830 tokens, `$0.00070903924`):
  **PASS**, two P3 notes. Deploy pending until the Epstein run ends (a restart would kill it).
- **D7 (fixed):** the rebuilt code generation (run `ad2236ed…`) held exactly one `__init__` node that 81
  classes "contained", one `main`, one `_chunk`, and Leiden named artifact communities ("__init__" 273
  members, "main" 314). `resolve_staged_entities` always keyed the official exact-match resolver on `name`;
  a code symbol's identity is its qualified `entity_id` (unique per generation by the store's constraint).
  Fix: `resolution_property_for_policy` (`name` for semantic, `entity_id` for code, error otherwise);
  `resolve_staged_entities(policy=…)` keys both the resolver and the duplicate-group telemetry on it; the
  promotion path passes the run's recorded policy. RED: ImportError (and the store's uniqueness constraint
  rejected a duplicate `entity_id` seed, which shaped the live test); GREEN: 19 passed (unit mapping,
  live semantic isolation with `policy="semantic"`, live code test keeping two `__init__` of different
  classes apart, communities suite); ruff, mypy (stale `type: ignore` on `ScopedNeo4jWriter` removed),
  banned scan clean. DeepSeek V4 Flash review `gen-1788291924-h7KVGbbg3P4XdG7HZlNk` (3,397 prompt + 2,693
  completion = 6,090 tokens, `$0.000983696`): **PASS**, no findings. A further visible `ragweld_code`
  rebuild is required after deployment for the promoted graph to reflect this.
- **D8 (fixed):** a corpus whose sampled text carries no extractable domain (numeric-only, or a names-only
  list) makes the proposer return an empty / relationship-less schema; `validate_domain_schema` raised and
  `POST /api/index/{corpus}/graph-schema/proposal` surfaced it as an unhandled 500 ("Internal Server Error"
  under the Generate button, reproduced twice). Fix: the endpoint maps the validator's ValueError to a typed
  422 `graph_schema_unusable` (corpus_id, model_alias, message, operator_hint). RED: the new live test
  `test_numeric_only_corpus_proposal_is_a_typed_422_not_a_500` surfaced the raw ValueError; GREEN: live
  proposal tests (3, real gateway, Luna) + API schema tests = 13 passed in 50.7 s, ruff, mypy. DeepSeek V4
  Flash review `gen-1788292482-Qv5sUy9C7hdYvqCMSGgm` (1,463 prompt + 4,221 completion = 5,684 tokens,
  `$0.0007238574`): **PASS**, three P3 notes (corpus_id assertion added; the corpus-scoped config is removed
  with the corpus; `_MODEL` is the file's module constant).
- **D9 (fixed):** the Indexing page's "Per-chunk timeout (seconds)" and "Reasoning effort" controls never reached
  the pipeline: `build_semantic_pipeline` and `derive_graph_schema_proposal` built `OpenAILLM(model_params=
  {"temperature": 0})` with no request timeout, so a visible 5 s / `xhigh` setting on the disposable corpus still
  let a 13 s Luna extraction promote (run `4e6f9312…`). Fix: `semantic_extraction_llm` builds the official
  OpenAILLM with `timeout=` (both OpenAI clients, per the 1.19 kwargs contract) and `reasoning_effort` in the
  model params; the pipeline and the proposal deriver take the operator values from the corpus-scoped config
  (the proposal carries the effort only). RED: TypeError (and Neo4jWriter's constructor touching the driver,
  which is why the factory is unit-tested directly); GREEN: 42 unit/API tests, live proposal tests 3/3 through
  the real gateway with the effort sent, ruff, mypy, banned scan. Review: a first DeepSeek response
  `gen-1788293253-ZjVKXIVu0caO4ec9BH7T` spent its whole 12,000-token ceiling on reasoning and emitted no content
  (`$0.00378`, rejected as a non-review); the retry `gen-1788293443-lmFBWWP4ZQhCqYZTdyR0` (3,000 prompt +
  570 completion = 3,570 tokens, `$0.0003726`): **PASS**, four P3 notes (proposal call intentionally carries
  the effort but not the per-chunk timeout; duplicate route validation removed; effort validation lives in the
  factory; refusal test renamed).
- **D10 (fixed):** no operator surface rendered the graph leg's traversal accounting after the Task 6 contract
  replacement (the chat debug footer printed only run/provider/trace ids and `llm_used`), so step 7's "visible
  debug disclosure" had nowhere to be read. Fix: the chat footer prints one line from the message's own
  `ChatDebugInfo` (`graph: graph_enabled=… graph_qdrant_seed_chunks=… graph_relationship_expansion_hits=…
  graph_hydrated_chunks=…`, test id `chat-debug-graph`); no entity-hit figure exists in either contract. A real
  NASA search recorded 6 seeds / 24 resolved entities / 6 expansions / 6 hydrated chunks with no
  `fusion_graph_entity_hits` key. Regression `chat_workbench.spec.ts` T8-7 builds a real promoted semantic graph
  on the exhaustive fixture through the API (Luna proposal, approved run, 16 entities / 12 relations / 4
  communities), searches with include_graph (top_k 2: 2 seeds / 9 resolved / 2 expansions / 2 hydrated; at
  top_k 4 every chunk is a seed and nothing is left to hydrate, by design), seeds the assistant message with the
  recorded values under the chat contract names and requires the footer to equal them. RED: element missing on
  the production component; GREEN: 1 passed in 42.9 s; tsc clean. DeepSeek V4 Flash: first review
  `gen-1788293719` FAIL (two P1 / two P2 / one P3, all about test strength: graph_enabled never asserted true,
  counters possibly undefined; plus two misreadings of fixture auth and `dispose`), fixed by the real-graph
  build and explicit assertions; re-review `gen-1788294337-kB9sMnjDMZcxNTNAmJEt` (2,703 prompt + 4,003
  completion = 6,706 tokens, `$0.00076762112`): **PASS**, no findings.
- **ragweld_code visible rebuild (done, superseded by D7 rebuild):** the first Index Now failed closed on the same
  `stored=deterministic` embedding contract (run `4ef886da…`); the visible Force reindex run
  `ad2236ed255a4086b286e1c0dbae8eb2` (19:26:39–19:32:48 UTC) promoted: 894 files, 7,092 chunks, 6,225 AST
  entities → 5,683 resolved (542 merged), 9,856 relations, 6,227 provenance links, 479 Leiden communities
  (5 levels, modularity 0.960). Live stats: module 668 / function 4,429 / class 586; contains 5,486 /
  calls 4,235 / inherits 2.
- **D3 (corpus/provider, not code):** the Epstein force run `0d70ababe9ac4424af6a3353b7b3ebcc` failed closed at
  its third file (`extraction_failure`, "LLM response has improper format") after two files extracted
  correctly. Reproduced 4/4 with the persisted Luna schema: the proposal carries an `Email.body` STRING
  property, the model copies the whole email into the JSON, and OpenRouter returns
  `finish_reason=content_filter` with the JSON cut mid-string (luna, terra and sol alike; independent of
  max_tokens). With the same schema minus `body`, Luna returns a valid graph (finish=stop, 464 tokens);
  DeepSeek 0731 also validates but spends ~4.5k reasoning tokens per chunk. Evidence:
  `output/task8-graphrag-acceptance/2026-09-01-epstein-D3-model-probe.txt`. The pipeline's fail-closed
  behaviour is the specified one; the remedy is a schema without free-text body properties.
- **D4 (fixed with D3):** `Tank` (1,037) and `PressureTransducerAssembly` (984) nodes of the promoted NASA
  generation carry no `name` property because the gpt-4o-mini proposal never typed one; the official
  `SinglePropertyExactMatchResolver(resolve_property="name")` skips null names (`WHERE prop IS NOT NULL`), so
  2,021 of 2,112 entities never resolve, and the explorer API returned the literal string "None" for them.
  Terra's Epstein proposal (`888b0614…56bc`) repeated both shapes (`Email.body`, `Email` without `name`), so the
  defect is the deriver's, not a model's. Fix: `normalize_domain_schema` in `server/indexing/graphrag_schema.py`
  runs before hashing and gives every node type a STRING `name` identity property plus a mandatory EXISTENCE
  constraint (a KEY on `name` already suffices; the official pruner then drops anonymous extractions), and drops
  document-text properties (body, content, text, full_text, raw_text, html, message, message_body, email_body,
  transcript) together with constraints that reference them; `validate_domain_schema` enforces both invariants
  at every boundary; the explorer maps a null stored name to "" and labels legacy entities by entity id.
  RED: ImportError + `name == "None"`; GREEN on LXC100: 85 unit/API tests (12 in `test_graphrag_schema.py`),
  live `test_graph_schema_proposal_live.py` 2/2 in 46 s through the real gateway with
  `GRAPH_E2E_KG_MODEL=openai.gpt-5.6-luna`, ruff, mypy, banned scan. DeepSeek V4 Flash review
  `gen-1788289806-exEgjFS3aglG2AFbBoe1` (`deepseek.deepseek-v4-flash`, 5,648 prompt + 5,382 completion =
  11,030 tokens, `$0.00229768`): **PASS**, three P3 notes (existing non-STRING `name` is rejected by validation
  rather than coerced; the unit test pins the identity property at index 0; `fulltext` and `full_text` both
  blocked). detect-changes: CRITICAL, 8 files / 14 symbols / 282 affected because the schema validator gates every
  index-start flow (intended containment).

- **D12 (fixed):** the Epstein force rebuild `eba9b356…` (3,123 chunks, Luna extraction) died at progress
  0.9985 after 2 h 07 min with `Neo.ClientError.Schema.ConstraintValidationFailed … __Entity__ repo_id=…,
  entity_id='HOUSE_OVERSIGHT_030209__msg_001__row_002631.txt:12-15:4800:0'`. Extraction telemetry: 3,113
  succeeded, 10 failed (all ten = the chunks of that one file), 8,992 entities, 4,670 relationships; 1,996
  distinct files, none processed twice; the file's ten chunk ids are unique in Postgres. Cause: the official
  1.19 writer (`neo4j_queries.upsert_node_query`) is `UNWIND $rows AS row CREATE (n:__KGBuilder__
  {__tmp_internal_id: row.id})`, one node per extracted row, and the extractor prefixes every model node id
  with the chunk id, so a response that repeats a node id inside one chunk yields two rows with the same
  stamped `entity_id` and the store's `rw_entity_repo_entity` uniqueness constraint aborts the run
  (`extraction_failure`, staged generation reclaimed). Fix: `fold_duplicate_node_ids` in
  `server/indexing/graphrag_pipeline.py`, called by `ScopedNeo4jWriter.run` before scope stamping;
  same-label duplicates fold into the first occurrence (properties merged, first value wins), a duplicate with
  a different label is re-keyed with a deterministic ordinal suffix (`…:0#2`), relationships keep the ids the
  model wrote, and the counts are logged. RED: `ImportError` (unit) and, before the fold, the live writer path
  raised the same constraint error; GREEN on LXC100: 39 tests (`test_graphrag_pipeline.py`,
  `test_graphrag_schema.py`, `test_graph_communities_live.py` incl. the new
  `test_scoped_writer_survives_a_repeated_node_id_inside_one_chunk` through the real writer and a live Neo4j,
  `test_graph_resolution_isolation_live.py`), ruff, mypy. DeepSeek V4 Flash review
  `gen-1788298743-sSyYImO8re6zBva9SU5J` (9,529 prompt + 1,517 completion = 11,046 tokens, `$0.00252`):
  **PASS**, three P3 notes (the live test proves the fixed path rather than the pre-fix failure; a warning, not
  a typed error, because the run continues; formatting noise, which was removed before commit so the diff is
  165 added lines and no deletions). detect-changes (stale index, hunks mapped by line): low, 6 files, no
  affected flows. Run record: `output/task8-graphrag-acceptance/2026-09-01-epstein-run-eba9b356-error.json`.

- **D14 (fixed):** the first code-corpus force rebuild after D7 (run `c58050a6…`, 7,132 chunks, 6,237
  entities, 9,876 relationships, resolver telemetry `unresolved_duplicate_groups: 0`) was refused at promotion
  with `unresolved_duplicate_entity`; the previous generation stayed active. Cause:
  `Neo4jClient.get_graph_invariant_counts` grouped `__Entity__` nodes by `name` + domain labels for every policy,
  while D7 keys code resolution on `entity_id`, so a code graph with two `__init__` methods can never promote
  and the invariant contradicts the resolver on the same run. Fix: the count takes
  `identity_property` (parameterised `entity[$identity_property]`, blank refused) and `verify_graph_promotion`
  derives it from `resolution_property_for_policy(policy)`. RED: the new live
  `test_code_policy_keeps_same_name_entities_with_distinct_ids_promotable` raised the exact live refusal;
  GREEN on LXC100: 33 tests (promotion-invariant matrix, invariant unit tests, explorer, resolution isolation,
  communities), ruff, mypy. DeepSeek V4 Flash review `gen-1788299720-xX7oJ1hKkabrOmt1Eflz` (2,467 prompt + 700
  completion = 3,167 tokens, `$0.00028511`): **PASS**, no findings (its remark that the unit tests were updated to
  pass the parameter is inaccurate: they exercise `evaluate_graph_invariants` on a counts mapping and did not
  change). GitNexus detect-changes: low, `Neo4jClient.get_graph_invariant_counts` + `verify_graph_promotion`, no
  affected flows beyond `start_index`. Deploy waits for the Epstein run `ca5b8d92…` (restart ban during an active
  run); the code corpus is rebuilt again afterwards. Run record:
  `output/task8-graphrag-acceptance/2026-09-01-code-run-c58050a6-refused.json`.

- **D16 / D17 (fixed):** the NASA Graph Explorer drive (Table view) showed `File: —` for every entity and never
  showed extracted properties, while the API returned `file_path: null` but `properties: {ullage: 30.0,
  pressure: 150.0, communityId: 797, communityPath: […]}` and the store holds a FROM_CHUNK edge to a chunk whose
  `file_path` is `A11_MissionReport.pdf`. Cause D16: all six explorer projections in `server/db/neo4j.py`
  returned `n.file_path` verbatim, which only code entities carry. Cause D17: `GraphSubtab` rendered
  name/type/file/connections only. Fix: `entity_source_file_expr` (`coalesce(n.file_path, head([(n)-[:FROM_CHUNK]->
  (provenance_chunk:Chunk {repo_id: $repo_id}) | provenance_chunk.file_path]))`) in every projection; the details
  block renders a `graph-entity-properties` line (every extracted property) and a separate
  `graph-entity-community` line (derived membership). Test honesty repair found on the way: the live explorer-view
  test never wrote its lexical Document/Chunk nodes, so its FROM_CHUNK `MATCH … CREATE` silently created nothing and
  the D1 co-mention premise was vacuous; it now writes the lexical graph through the scoped writer and asserts
  `relationships_created == 2`. RED: `assert None == 'A11_MissionReport.md'`; GREEN on LXC100: 33 tests (twice; one
  unrelated single failure in the first 5-file run did not recur on two reruns and its name was not captured),
  ruff, mypy, `tsc`; Playwright exhaustive `graph_explorer.spec.ts` M-65 extended (File, `qualname: Reranker`,
  `kind: class`, `start_line`, no `communityId` among properties, `Community:` line) and passed against the overlay
  Vite build through the live API. DeepSeek V4 Flash review `gen-1788301230-pW6e16e829UqbW0rPHot` (4,984 prompt +
  1,814 completion = 6,798 tokens, `$0.00096454`): **PASS**, no P1 (its P2-labelled items are confirmations, not
  findings). detect-changes (stale index): medium, 6 files, three `GraphSubtab` flows. Deploy waits for the Epstein
  run like D14.

- **D18 (fixed):** the journal showed 708 "repeated node ids … rekeyed=1" warnings from the D12 fold during the
  code-corpus run `c58050a6`. Cypher on the active code generation `ad2236ed` (built before D12) exposed the cause:
  the lexical `Document` node and the code `module` entity of every file share the bare file path as writer id
  (668 collisions), and the official writer resolves relationship endpoints by `__tmp_internal_id` regardless of
  label, so Document nodes carry 4,154 `contains`→function, 592 `contains`→class and 707 FROM_CHUNK edges copied
  from the modules while 3,677 chunk FROM_DOCUMENT edges point at `module` entities; under D12's re-key the module
  would instead become `<file>#2` and lose its edges. Fix: `document_node_id` (`document::<file>`) is the Document
  writer id (`document_info` uid; the builder uses it for the chunks' FROM_DOCUMENT endpoints too, `file_path` stays
  on the node), `assemble_code_file_graph` builds the per-file graph and refuses any shared writer id, and the
  test-facing `official_graphrag.write_lexical_graph_with_graphrag` now calls the shared `document_info` instead of
  building its own uid (one owner). Code entity ids are unchanged. RED: live
  `test_code_entity_ids_round_trip…` (now writing lexical + code nodes in one graph like production) reported
  `document_id 'server/retrieval/rerank.py', outgoing 1, modules 0`; unit test `ImportError`. GREEN on LXC100: 63
  tests across pipeline/code-graph/schema/1.19-contract/explorer/communities/resolution/invariants/schema-proposal
  suites, then 29 after rebuilding the module diff without format noise; ruff, mypy. DeepSeek V4 Flash review
  `gen-1788307689-ksqVrBrVpeuv5dZmqAy8` (4,170 prompt + 1,789 completion = 5,959 tokens, `$0.00068652`): **PASS**,
  no blockers (P3: empty-path ValueError is new but fail-fast; P2 remark on the test's hard-coded path needs no
  change). GitNexus impact on `document_info`: CRITICAL by transitive reach (2 direct callers, depth-3 fan-out via
  `start_index`); detect-changes: critical, 6 files, 9 symbols, 289 affected. Proceeding because only the Document
  writer id changes; the code corpus is rebuilt after deploy and the Epstein/NASA graphs are rebuilt on the same
  code.

- **Observations recorded, not fixed (D13, D15, D19, D20, D21):** D13 the pre-run estimate dialog predicts ~12 min for
  a semantic run that takes ~2 h (per-token model, not per-gateway-call at four workers); D15 the cloud reranker
  hit a LiteLLM `ReadTimeout` while the Epstein extraction held four concurrent Luna calls on the same gateway
  (the chat answered unreranked with a visible toast); D19 Luna named many Epstein `Email` entities with OCR-noise
  fragments because `name` is free text and `subject` was typed optional; D20 the URL corpus parameter does not
  change an existing chat conversation's Sources (per-conversation setting, visible in the Sources picker); D21
  the Docling PDF conversion runs inside the API process, and starting the NASA rebuild on a process that had
  grown to 3.5 GiB over the Epstein run drove pve1 into full swap (load 500+, public health 530, chat 502) —
  recovered from pve1 with a run stop and an API restart, then retried on a fresh process; the click ledger holds
  the timeline. These are product/ops follow-ups outside the Task 8 gates.

- **D22 (fixed):** the Task 8 full gate failed the real end-to-end
  `test_index_search_and_delete_on_promoted_lane` (KG model `deepseek.deepseek-v4-flash`) with
  `LLM response has improper format`, the official extractor's rejection of a structured-output reply. A probe of
  `LLMEntityRelationExtractor(use_structured_output=True)` on the failing chunk through the gateway: with the D9
  binding `model_params={"temperature": 0, "reasoning_effort": "medium"}` DeepSeek answered 1 of 3 attempts with
  `"embedding_properties": null` on every node (pydantic `dict_type` error); with `{"temperature": 0}` 3 of 3
  validated. `reasoning_effort` is OpenAI's request parameter (the config field says so). Fix:
  `_semantic_kg_reasoning_effort(cfg, route_model)` in `server/api/index.py` binds the operator's effort only when
  the catalog row for the route alias has `provider == "openai"`, else `None`; `semantic_extraction_llm` and
  `derive_graph_schema_proposal` take `str | None` and omit the parameter for `None` (blank still refused). RED:
  `ImportError`; GREEN on LXC100: 40 unit tests (incl. the catalog-backed provider test and the `None` binding
  test), ruff, mypy, live `test_graph_schema_proposal_live.py` + `test_graphrag_pipeline_live.py`. DeepSeek V4
  Flash review `gen-1788315853-jPkHunHXSBdQ5tgMmWPL` (3,277 prompt + 1,225 completion = 4,502 tokens,
  `$0.00080178`): **PASS** (P2 remarks are confirmations; a per-model capability flag is noted as a possible future
  refinement, not required). The promoted-lane test then passed once and was refused once more at promotion with a
  code the `-q` output elided; a verbose repeat loop is capturing it (recorded below under D23 when known).

### Final precommit GitNexus scope

- Task 8 uncommitted range: HIGH risk across 55 files, 99 indexed symbols, eight affected flows. The named flows are `start_index` persisted/config resolution, mechanical docs automation helpers, and `RetrievalSubtab` config/readiness loading.
- Complete approved-plan range from `e38cb6ba`: CRITICAL risk across 126 files, 637 indexed symbols, and 38 affected flows. The named paths are the expected proposal/estimate/status/start, search/benchmark/eval fusion, Postgres schema metadata, and Graph Explorer/config consumers already bounded by Tasks 1-7 reviews and the fresh full gate.
