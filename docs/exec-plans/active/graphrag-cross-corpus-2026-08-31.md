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

Status: in progress

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

Status: in progress

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

Status: pending

## Task 4 - Official pipeline and lexical graph

Status: pending

## Task 5 - Resolution and promotion invariants

Status: pending

## Task 6 - Qdrant-seeded traversal

Status: pending

## Task 7 - GDS Leiden communities

Status: pending

## Task 8 - Full verification, deployment, reindex, browser acceptance

Status: pending
