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
| One external semantic/code policy and truthful defaults | Task 2 PASS, full `test_graph_policy.py`/config/API gate, visible NASA/Epstein semantic badges and code badge | Automated proves; live pending |
| Recall exclusion | Policy/API tests plus live Recall UI showing excluded graph policy with no graph start path | Automated proves; live pending |
| Reviewed per-corpus schema proposal and persistence | Task 3 PASS, live NASA and Epstein visible generate/expand/approve dialogs, schema hash in run metadata and after reload | Automated proves; live pending |
| Correct official lexical names | Full live GraphRAG/store query: `FROM_DOCUMENT`, `NEXT_CHUNK`, `FROM_CHUNK`; zero `IN_CHUNK` | Automated proves; live pending |
| Official Pipeline and scoped writer | Task 4 PASS, full gate, promoted per-corpus graph metadata/store scoping | Proves; fresh live/batched gate passed |
| Exact-match scoped entity resolution | Task 5 PASS, live run resolution telemetry and zero duplicate groups/cross-generation edges | Automated proves; live pending |
| Fail-closed promotion and RED matrix | Task 5 mutation matrix plus Task 8 visible temporary-corpus refusal, operator hint, no promoted generation/completed badge after reload | Automated proves; visible negative pending |
| Qdrant-seeded traversal and no double credit | Task 6 PASS, retained-generation collision test, live graph search debug fields/API equality and no `fusion_graph_entity_hits` | Automated proves; live pending |
| GDS 2.13 deployment | Task 7 PASS, deployed `gds.version()`=`2.13.x`, Neo4j/APOC/GDS readiness, deployment marker | Isolated proves; deployed pending |
| Weighted deterministic Leiden, including code | Task 7 semantic/code/failure live tests plus nonzero NASA/Epstein/code `communityPath`/`communityId`, counts, derived API/UI after reload | Isolated proves; deployed pending |
| Dead-surface replacement | Repo search, live Neo4j zero obsolete ontology/vector/embedding state, config/generated UI absence | Source proves; live cleanup pending |
| Per-task and final DeepSeek reviews | Recorded PASS for Tasks 1-7 plus final complete spec-to-main integration PASS after full gate | Tasks 1-7 prove; final pending |
| Full LXC quality gate | Exact Task 8 surfaces: dependency sync, generators, docs ownership, Ruff, mypy, complete 1,989-test collection, TS/build, headed policy/explorer | Proves predeploy through bounded batches; live GDS browser row deferred to postdeploy |
| Push/deploy parity | Mac `HEAD`, `origin/main`, LXC `HEAD`, deployment marker and serving runtime hash identical; clean one-worktree state | Pending |
| NASA visible rebuild and drive | Screenshot/click ledger: visible schema review/approve/cost/run telemetry/reload, three node types, two neighborhoods, all controls, community, graph search/debug | Pending |
| Epstein visible rebuild and drive | Same complete screenshot/click/search/debug ledger with flight/communication question | Pending |
| `ragweld_code` visible rebuild and drive | Visible code policy/AST types/weights/run telemetry, same full Explorer/search/reload ledger | Pending |
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

### Final precommit GitNexus scope

- Task 8 uncommitted range: HIGH risk across 55 files, 99 indexed symbols, eight affected flows. The named flows are `start_index` persisted/config resolution, mechanical docs automation helpers, and `RetrievalSubtab` config/readiness loading.
- Complete approved-plan range from `e38cb6ba`: CRITICAL risk across 126 files, 637 indexed symbols, and 38 affected flows. The named paths are the expected proposal/estimate/status/start, search/benchmark/eval fusion, Postgres schema metadata, and Graph Explorer/config consumers already bounded by Tasks 1-7 reviews and the fresh full gate.
