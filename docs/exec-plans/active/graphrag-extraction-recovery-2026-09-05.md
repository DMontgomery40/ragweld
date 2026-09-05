# GraphRAG Extraction Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve validated semantic extraction work across failed replacements and show accurate chunk progress without changing graph generation or promotion semantics.

**Architecture:** Store official, validated chunk graphs in the existing Postgres database before the official extractor adds lexical and run-specific identity. New runs reuse only exact matching extraction inputs, then pass deep copies through the existing official postprocessor, pruner, scoped writer, resolver, and promotion checks. Native gateway records remain the sole billing evidence.

**Tech Stack:** Python 3.12, Pydantic, asyncpg/Postgres, neo4j-graphrag 1.19.0, Neo4j, existing run records, React/Zustand and generated TypeScript.

**Spec:** `docs/exec-plans/active/graphrag-continuation-2026-09-04.md`, September 5 failed NASA replacement evidence, and the requirements below.

## Global Constraints

- Mac checkout is source only; all execution, databases, tests, builds and browser acceptance run on LXC100.
- Preserve the official extraction/postprocessing/pruning/writing pipeline and current whole-generation promotion invariants.
- Preserve the separate D3 embedding and D13 estimate changes; stage exact owned files or patches.
- No raw prompts, API keys, gateway responses or spend ledger in the checkpoint table. Domain graph data remains in the corpus's existing private Postgres storage.
- No automatic fresh paid dispatch after malformed, mismatched or unreadable checkpoint data.
- Reusable identity excludes run ID, credentials, timeout and concurrency. It includes corpus, source path/file digest, exact chunk content/order/provenance, approved schema, rendered prompt/examples, model alias/upstream/sanitized endpoint, model parameters and implementation recipe versions.
- An unchanged provider model slug cannot prove an unchanged provider implementation. Record this limitation; explicit deindex clears checkpoints.
- A cache hit is an extraction reuse, not a new native request or new spend.
- Run GitNexus impact before edits and detect-changes before committing. Public telemetry impact is CRITICAL; Postgres client impact is HIGH. Review against exact changes, then independent Sol xhigh and the normal PR loop.

## Task 1: Typed and fenced Postgres checkpoints

**Files:** Create `server/models/graph_extraction_checkpoint.py`; modify `server/db/postgres.py`; create `tests/integration/test_graph_extraction_checkpoints.py` in the existing pytest stack.

**Interfaces:** The new Pydantic envelope owns identity and the official `Neo4jGraph`, not a second graph DTO. Define `GraphExtractionCheckpointIdentity`, `GraphExtractionCheckpoint`, `graph_extraction_cache_key(identity)`, and the three Postgres operations below. A separate preparation operation may handle corpus recipe rotation if it keeps the same transaction/fence rule.

```python
async def get_graph_extraction_checkpoint(
    self, repo_id: str, cache_key: str,
) -> GraphExtractionCheckpoint | None: ...

async def put_graph_extraction_checkpoint(
    self, repo_id: str, owner_run_id: str,
    checkpoint: GraphExtractionCheckpoint,
) -> None: ...

async def prepare_graph_extraction_checkpoint_file(
    self, repo_id: str, owner_run_id: str, recipe_hash: str,
    file_path: str, current_keys: list[str],
) -> None: ...
```

- [ ] Add real Postgres tests first: idempotent duplicate write, conflicting duplicate content, wrong corpus/key, malformed payload, absent/replaced run fence, corpus deletion, explicit deindex, and failed staging cleanup retention.
- [ ] Run that suite on the private LXC Postgres and retain the behavioral failure evidence.
- [ ] Add `graph_extraction_checkpoints` with `(repo_id, cache_key)` primary key, a corpus FK with cascade deletion, recipe/file lookup fields, creation time, and JSONB envelope. Register it in corpus-owned deletion inventory.
- [ ] Canonicalize identity to stable sorted JSON and SHA-256. Validate the envelope and official graph on reads. Check current base-corpus fence inside the same transaction for writes and pruning. Reject conflicting rows; preserve identical rows.
- [ ] Keep only the current recipe partition and prune obsolete keys only after a file's full current chunk set is known. Successful completion removes deleted-file entries; failed staging reclamation does not remove matching base-corpus entries.
- [ ] Run the real persistence/lifecycle matrix and Ruff/mypy; independently review transaction ownership and deletion races before integration.

The identity model must carry explicit fields for the global constraints above. Avoid opaque caller-provided hashes without retaining their typed provenance. The envelope additionally records its originating run and pruning counts; its graph contains no staging/run/corpus scope properties. SQL identifiers are fixed, values parameterized.

## Task 2: Preserve completed official extraction results

**Files:** Modify `server/indexing/graphrag_pipeline.py`; create a focused `server/indexing/extraction_checkpoint.py` adapter if necessary; extend `tests/unit/test_graphrag_census.py`, `tests/unit/test_graphrag_pipeline.py`, and `tests/integration/test_graphrag_pipeline_live.py`.

**Interfaces:** Build an execution-scoped checkpoint context from the base corpus, owner run, Postgres client, exact approved extraction recipe, file and chunk provenance. Pass it explicitly to the existing extractor. `_DrainingExtractor.extract_for_chunk` consumes that context; the public official return type stays `Neo4jGraph`.

- [ ] Add a real HTTP fixture with several successful domain graphs followed by a timeout/refusal. Restart a separate worker against the same Postgres database and assert that only missing chunk identities are dispatched.
- [ ] Prove each changed identity input prevents reuse, while changing only run ID, timeout or concurrency preserves reuse. Include two corpora with otherwise identical input.
- [ ] Inside `extract_for_chunk` (already admitted by the official semaphore), validate a matching stored envelope. Return a deep copy on a hit. A miss calls the existing official method exactly once; SDK and wrapper retries stay disabled.
- [ ] Validate reserved scope properties, entity-ID consistency and the official graph shape. Apply official `GraphPruning` before persistence, preserving pruning counts. Valid empty graphs can be reused but cannot bypass generation-level nonempty invariants.
- [ ] Persist before counting reusable success. Retain and drain an initiated commit task on cancellation using the existing producer/drain ownership. Never release the fence while a checkpoint writer still owns work.
- [ ] Pass the returned copy through unchanged official lexical postprocessing and final file pipeline. Assert that reused graphs acquire only the new run/staging scope and retain document, `NEXT_CHUNK`, and source links.
- [ ] Exercise cancellation during commit, abrupt worker exit, fence takeover, corrupt rows and storage outage with real components. Failure must not silently issue a replacement paid call.

## Task 3: Accurate persisted progress and operator acceptance

**Files:** Modify `server/models/index.py`, `server/api/index.py`, `server/indexing/run_records.py`, the existing Indexing UI graph summary, its browser fixture/spec, and generated contracts. Keep D13 estimate helpers under their existing owner's control.

**Interfaces:** Extend `GraphExtractionTelemetry` with explicit reuse/cancellation/unfinished counts, defaulting new fields for historical records. A typed progress callback publishes admitted/completed outcomes from the extractor into the existing locked run-summary update path. Existing native census and costs remain independent.

- [ ] Add state-transition tests covering queued, admitted, validated, checkpointed, reused, failed and cancelled chunks. Initial queued tasks must not all count as attempted.
- [ ] Remove semantic-path whole-file `attempted += len(chunks)` and `failed += len(chunks)` on exception. Preserve separate writer/promotion failure evidence and completed extraction counts.
- [ ] Count success after durable acceptance, reuse separately, and worker duration on actual misses. Provider-latency estimates must exclude reused successes from their denominator.
- [ ] Persist progress through existing run-record locks without clobbering later accounting or newer progress. Verify deliberately delayed progress/accounting writes in both orders.
- [ ] Update the Indexing UI to show selected, attempted, reusable successes, reused, failed and unfinished work truthfully after reload. A failed run remains unpromoted even with successful checkpoint rows.
- [ ] Regenerate TypeScript and contract bundles on LXC100; run changed-surface tests, Ruff, mypy, banned patterns, type/contract/config checks, full CI and the real browser matrix.
- [ ] Obtain independent Sol xhigh review, complete the PR loop and deployed-marker verification. Only then change NASA's existing per-chunk timeout to a reviewed value, show the corrected estimate, run the approved replacement, and verify domain retrieval/source provenance in the real browser.

## Self-review and acceptance evidence

The three tasks cover persistence, official-pipeline reuse and operator truth separately. Identity mismatch, stale-writer races, corruption, deletion and cancellation are explicit requirements, not fallback cases. Store interfaces above are shared contracts; rename them coherently if implementation evidence requires a change. Existing native charges for the failed NASA run remain $3.0555729 with incomplete request coverage; this plan cannot recover outputs already lost by that run.
