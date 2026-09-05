# GraphRAG and operator acceptance continuation — 2026-09-04

The operator requested continuation of the whole August 31–September 3 effort.
The retired model reference was incidental; completing its removal did not close
the GraphRAG or application acceptance work.

Authority: the cross-corpus design and implementation plan under
`docs/superpowers/`, the evidence ledger
`graphrag-cross-corpus-2026-08-31.md`, and the September 2 Fable conversation.
That conversation's `scratchpad/tasklist.md` was written in a Claude temporary
session directory, not this checkout. Its last nine sections were recovered from
the conversation into `/private/tmp/astra-recovered-fable-tasklist.md`.
Historical completion claims are leads to verify, not current acceptance evidence.

## Work list

- [x] Recover the eight GraphRAG tasks, original D13/D15/D19/D20/D23 completion
  requirements, subsequent S findings, and cost telemetry request.
- [x] Check current NASA, Epstein, code, and Recall policy, approved schema,
  extraction coverage, promoted generation, provenance, and communities.
- [x] Run bounded chunk-level retrieval comparisons with graph disabled/enabled and
  inspect whether graph-only additions answer the query; counts alone do not
  prove useful retrieval. Start without external reranking or generation.
- [x] Audit schema, promotion, generation isolation, and community contracts;
  reproduce and repair substantive remaining failures with family coverage.
- [ ] Drive deployed indexing, Graph Explorer, neighborhoods, sources,
  communities, search/debug, and reload behavior. Record visible failures.
- [x] Reconcile non-graph backlog against current source and live behavior:
  S15 configuration scope, S17 test/deployment config ownership, S21 onboarding,
  S27 disabled backend configuration, S29 run progress, S30 dependencies load,
  S32 document exclusions, S33 model selection, S45 dock navigation.
- [ ] Complete run/index cost attribution through the existing gateway and
  observability stack; preserve provider-reported costs and distinguish actual
  spend from estimates. This was designed, not implemented, last week.
- [ ] Review each major change, run changed-surface and repository gates on
  LXC100, publish, deploy with indexing idle, and verify the live operator path.

## Starting evidence

- Mac and LXC100 source/deployment marker: `70c2461d`; publication still at
  `bde5d1c9` at the start. Existing AGENTS.md/CLAUDE.md edits belong to earlier work.
- Four live registry corpora: NASA, Epstein, ragweld_code, Recall. The last
  completed index timestamps remain September 2–3; no new rebuild is implied.
- The preceding model-policy slice is recorded separately in
  `gpt4-execution-retirement-2026-09-04.md`.
- The earlier NASA excerpt reranking probe was refused by automatic approval
  review. The operator subsequently approved sampled NASA schema generation
  and rebuilding, plus the separate Codex source review, on September 4.

## Findings and proof

### Graph quality and schema sampling

All three promoted graphs have community membership and source provenance on
every existing entity. NASA has 162 entities and 61 semantic relationships, but
only 141/1,002 chunks carry entities. Its approved schema is limited to propulsion
hardware and launch events/sites, omitting guidance, radar, alarms and trajectory
concepts. Epstein has 2,355 entities and 2,669/3,126 linked chunks.

The proposal pipeline sampled nine PDF pages concentrated at the beginning,
middle and end, then reduced a single long report to three chunks. The replacement
uses 36 evenly distributed pages and a total budget of 36 chunks apportioned across
up to 12 documents. Recipe v2 invalidates proposal reuse; historical v1 records
remain readable. Synthetic document/PDF coverage: nine RED failures, then 16 GREEN
cases, including repeated sampling and page-count boundaries. NASA regeneration
and rebuilding are now explicitly approved; production rebuilding is pending.

The final sampling matrix also includes mixed document lengths. Tiny files no
longer strand the remaining sample budget: three additional RED cases now pass,
with deterministic, idempotent allocation of all available slots up to 36.

Graph-score ties used chunk-id order, selecting the same first five passages for
three distinct NASA questions. Query-vector relevance now breaks ties strictly
within traversal-derived candidates, without adding seeds or changing structural
scores. Postgres hydration preserves that order. Nineteen real-store/contract
tests pass, including nearby queries with identical graph evidence but opposite
source preferences. The six-query live corpus comparison is saved on LXC100 as
`/tmp/astra-graph-baseline.json` and `/tmp/astra-graph-after.json`. Graph latency
remained 0.12–0.37 seconds after the change. The Epstein event-cancellation query
now retrieves related Germany-event emails rather than unrelated conference
messages; the thin NASA schema continues to limit its results.

Three further code-corpus queries are saved as `/tmp/astra-code-graph-before.json`
and `/tmp/astra-code-graph-after.json` on LXC100. Promotion and community questions
now prefer relevant implementation/tests over unrelated API imports. These nine
queries are a diagnostic comparison, not a complete relevance benchmark. The code
index still retrieves `server/indexing/official_graphrag.py`, removed during last
week's work; refreshing that corpus remains a deployment acceptance requirement.

### Graph integrity and concurrency

- Conflicting duplicate node IDs could be renamed without redirecting provenance;
  suffixes could collide with existing IDs. Ambiguous identities now fail before
  writing; truly identical entities still fold.
- Promotion checked only that some source links existed. It now checks every
  entity for missing provenance, including code graphs and sparse overrides.
- An approved registry directory could be replaced by a different request path.
  Both request acceptance and background approval bind to the resolved source root.
- The official writer's temporary IDs and global cleanup were not generation
  scoped. Interleaving two synthetic graphs created four relationships, including
  cross-generation endpoints. Temporary IDs and cleanup now use scoped namespaces;
  canonical persisted IDs remain unchanged. Three new live tests cover interleaved
  generations, deferred writes and overlapping complete writes in one generation.
- The pinned schema validator reopened additional properties on relationship types
  with no declared attributes. Official GraphPruning then retained undeclared body
  text. A validated schema helper closes these flags after reload while keeping the
  official pruner. Twenty-four contract tests cover serialization, actual Pipeline
  input handling, edge preservation and allowed attribute retention.

### Operator and telemetry follow-ups

- S15: config scope typo/unknown/blank/repeated/conflicting parameters now return
  field-addressable 422 before config access. Six route families covered; 83 config
  and API tests pass.
- S45: dock content, title, reload and Swap follow the selected target; two real
  browser RED cases fixed, five dock tests pass.
- S46: trace links now check again during asynchronous Langfuse ingestion, reset
  when the selected trace changes, and offer manual retry after six checks. Three
  real browser/API/ingestion tests pass without model calls.
- S30: fresh Admin browser contexts displayed meaningful loading content within
  0.85–0.89 seconds; the historical blank-page defect was not reproduced.
- S32: the current document corpora have no chunks excluded by the inherited code
  filters. The historical observation is not a reproduced data-loss defect.
- S33: specialized model names alone do not prove incompatible chat output. The
  existing catalog refresh admits text-output routes and replaces obsolete feed
  rows. Persisting output-modality evidence would strengthen the runtime contract;
  no name-based removal is warranted from the current evidence.
- S17: pytest config isolation is already implemented. Ad hoc overlay processes
  still need explicit config ownership; old deployment recipes remain a risk.
- S21/S27: disabled local serving/training configuration still contains unavailable
  MLX model identifiers. These are separate onboarding/capability work, not an
  observed active GraphRAG route.
- S29: the persisted active-run summary can lag live status at phase boundaries.
  The current panel uses live status; a new progress/persistence contract remains
  open, and no production index was started solely to exercise that observation.
- The old claim that Langfuse model/cost fields were all null was based on an API
  query omitting the model/usage field groups. Correctly scoped reads show data.
  Real defects were doubled benchmark token totals and discarded streaming costs.
- Cost fixes preserve terminal streamed charges, normalize Langfuse token fields,
  and retain per-model and complete aggregate benchmark accounting. Catalog
  estimates remain explicitly distinct from reported charges; missing data stays
  unavailable. The gateway generator enables final streaming cost emission.
- Grafana Cost & Capacity now uses existing LiteLLM/Mimir spend counters for the
  selected range, rolling seven days and model spend rate. Unused corpus/run filters
  are removed. Live Mimir returned nonzero spend for Luna and GPT-5.4-mini. These
  gateway totals do not close per-index-run attribution or direct embedding costs.
- Benchmark browser acceptance covers reported tiny/zero charges, aggregate
  estimates, charged empty responses and unknown costs from saved isolated runs.
- Live NASA Graph Explorer loads the Fuel Tank 2 neighborhood (six entities, five
  edges) and Table mode, but filenames are plain text and every edge says "No
  provenance." The repair now opens actual FROM_CHUNK mentions in the existing
  document viewer from both Visualization and Table. Browser acceptance opened
  NASA's captured PDF page, source regions and exact cited text. A second real
  browser fixture verifies a generation change invalidates old pagination links,
  then reloads and paginates without duplication. Entity mentions are explicitly
  distinguished from evidence for an individual edge.

The source endpoint binds entity, provenance edge and chunk to one graph
generation; the manifest token fences pagination even when a newer index reuses
an older graph. Location metadata is enriched only when Postgres has identical
indexed source text and coordinates. Missing, unlinked, foreign and stale cases
pass against real stores. A live census found no forbidden document-text
properties on entities/semantic relationships in the three current graphs.

### Gates still open

The first combined backend gate completed with 2,369 passes, two fixture failures,
10 skips and two NASA tests deselected for pending egress approval. Both failures
were old fixtures relying on now-rejected generation/path mismatches. Corrections
retain isolation assertions and expand empty-input coverage; all four correction
tests passed, including the complete promotion/retirement/cancellation path.
The final merged suite passed: **2,385 passed, 9 skipped, 2 deselected** in
618.92 seconds. The two deselections were the real NASA schema-proposal tests whose
content transmission awaited approval at that time. No test failure remains in this snapshot.

Strict mypy, docs/banned/capability/type checks, changed-file Ruff, web lint, 21 web
unit tests and build pass on the merged tree. Repository-wide Ruff has 35 existing
findings; an isolated checkout of starting HEAD has 41. GitNexus analyzed the final
source and mapped the staged overlay diff to 58 intended files, 230 symbols and
123 affected processes (critical impact due to shared retrieval/config/graph
boundaries). Runtime symlinks are excluded from that staged diff.

Evidence on LXC100:

- `/tmp/astra-continuation-final-full.log`
- `/tmp/astra-continuation-final-static.log`
- `/tmp/astra-continuation-final-web.log`
- `/tmp/astra-continuation-detect-changes.log`
- `/var/tmp/astra-followup-acceptance/graph-sources-browser.log`
- `/var/tmp/astra-followup-acceptance/langfuse-green.log`
- `/tmp/astra-cost-browser-final.log`

The tested source matched the Mac patch by SHA-256 before this evidence update.
Private acceptance API/Vite/preview processes have been stopped; overlays and logs
are retained for review. All four live corpora report complete after the final
gate, and `/api/ready` reports `ready: true`. Production's deployment marker
remains `70c2461d`; this patch is uncommitted
and undeployed. Independent review, publication/deployment, production acceptance,
NASA rebuilding, code-corpus refresh and indexing-wide cost reconciliation remain
open. The prepared review prompt is `/private/tmp/astra-review-continuation.txt`
on the Mac.

Automatic approval review initially refused the separate Codex review command
for repository-source egress and the NASA content transmission. The operator
explicitly approved both on September 4. Both previously deselected Apollo tests passed on LXC100 in
29.06 seconds, including the full report's public-edge timeout contract and
persist/reuse/invalidation behavior. Evidence:
`/tmp/astra-continuation-nasa-approved-tests.log`. No production reindex has
started yet.

### Approved follow-through and independent review

Sol xhigh reviewed the complete continuation patch and returned one blocking P2:
an empty or missing entity-source result bypassed the manifest recheck during
promotion. The recheck now follows every completed Neo4j lookup, including a
manifest that reuses the same graph under a new run. A transparent Bolt transport
barrier pauses actual Neo4j responses while the test changes the real Postgres
manifest. The four-case race matrix failed three cases before the fix; all five
source integration tests pass afterward (3.06 seconds). No other blocking defect
was reported. Review output: `/private/tmp/astra-review-continuation.out` on Mac.

The approved 36-chunk NASA preview exposed a further quality limit: the official
minimal-schema instruction omitted diagnostic domains present in the sample.
The supported official prompt-template override now retains distinct sampled
concepts and explicit causal/diagnostic/operational relationships while preserving
the upstream JSON contract. No NASA ontology is hard-coded. A controlled full
sample preview returned 32 node types, 40 relationship types and 49 patterns in
24.08 seconds. Counts alone are not a quality verdict.

Approval fingerprints now bind to the exact proposal prompt, resolved root,
chunking, tokenization, reasoning effort and Parquet extraction settings, as well
as the existing file inventory, model alias and sampling recipe. Seven initial
regressions failed before this change; the schema/API/live suite then passed all
60 cases in 70.06 seconds, including the full report's 90-second request contract.
Additional tokenizer/Parquet context coverage is included in the final gate.

The broader schema also revealed unsupported extraction: causal inference from
neighboring event-table rows and a closed-anomaly status carried across a section
heading. Grounding repairs and exact-default prompt migration passed 67 narrow
tests, including four real-model cases and four migration/customization cases.
The uniform sample still misses some detailed explanations
(including the full alarm explanation); bounded sampling is not complete document
coverage. Preview/diagnostic artifacts are on LXC100 under
`/tmp/astra-nasa-schema-*.json` and `/tmp/astra-nasa-schema-quality-audit.json`.

Force-reindex wording also described obsolete destructive behavior. The current
implementation builds a staging generation and swaps after validation; the UI,
request description and log/error messages now describe that behavior. Changing
the saved embedding/sparse contract can still interrupt retrieval until the
replacement is active, which the UI states. Web lint/build and schema checks pass.

Publication must preserve the two newly fetched daily catalog commits on
`origin/main` (`bed4e439`); they are independent of this continuation patch.

The bounded Sol xhigh follow-up review returned **APPROVE, no findings**. Its
launcher explicitly used `gpt-5.6-sol` with xhigh effort; the review's caution
about not invoking a second nested reviewer does not change that recorded model.
Evidence: `/private/tmp/astra-review-graph-quality-delta.{log,out}` on Mac.

The final six-chunk comparison held prompt, schema and source text fixed. Luna
produced 59 entities/10 edges and retained an unsupported telescope-measures-
velocity edge plus other weakly supported analysis/measurement edges. Sol produced
57 entities/7 edges: it preserved the five clearly supported Luna relationship
meanings, removed the unsupported measurement edges, and added supported retainer-
failure/gear and reaction-control/component relationships. No clearly unsupported
Sol semantic edge was found in these six excerpts; it also omitted an explicitly
mentioned telescope. This supports a NASA-specific extraction-model change for
precision, not a claim of corpus-wide superiority. Evidence on LXC100:
`/tmp/astra-nasa-grounding-{full_schema,sol_full_schema}.json`.

GitHub's preceding main CI failed at backend linting; frontend and docs ownership
passed. Nine files now have import-only repairs with identical executable ASTs.
The existing exporter refreshed the stale OpenAPI and JSON-schema bundles. A
separate LXC overlay passed server Ruff, strict mypy, configuration reality,
contract validation, banned-pattern checks and 25 targeted tests. This does not
waive the pending full-suite result or GitHub checks for publication.

The next full run completed with 2,406 passes, nine skips and two NASA failures
in 701.99 seconds. Both were typed 422 responses: the proposer used the forbidden
generic label `ASSOCIATED_WITH`, but the prompt had never stated that existing
validator rule. Rule 7.1 now renders the validator's own reserved-label sets,
and the prompt fingerprint invalidates earlier approvals. Three new RED prompt
contract assertions now pass, as do all 62 schema/API/live cases (75.55 seconds),
including both failed NASA cases. No timeout was involved in these failures.

A third, bounded Sol xhigh review **APPROVED** the reserved-label instruction,
mechanical CI import repairs and regenerated contracts with no findings.
Evidence: `/private/tmp/astra-review-publication-delta.out` on Mac and
`/tmp/astra-schema-label-rules-{red,green}.log` on LXC100.

The prospective catalog merge preserves all allowed upstream model/price updates
and reapplies the already approved execution policy through the canonical
catalog-trio writer. It retains 431 rows; all 100 model-policy/catalog/refresh
tests pass. The full final merged-tree gate and publication are next.
