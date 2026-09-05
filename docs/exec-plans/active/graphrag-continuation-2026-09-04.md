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

### PR review and fresh-install verification

The continuation patch was committed as `cca5019e`, merged with the two catalog
updates as `9c08c37e`, and published in PR #89:
<https://github.com/DMontgomery40/ragweld/pull/89>. All 431 allowed upstream model
rows and their metadata were preserved. The production runtime remains unchanged.

The merged-tree backend run produced 2,407 passes, nine skips and one failure
in 686.92 seconds. Both NASA proposal regressions passed. Luna dropped a clearly
confirmed causal relation in the negation/uncertainty extraction case, returning
only a Chunk. This is retained as a model-quality failure; the assertion was not
weakened. Sol then passed all four grounding cases, and a combined real-provider
run passed those four plus all three NASA proposal cases (147.04 seconds). The
final full suite will use the existing `GRAPH_E2E_KG_MODEL` selector with Sol,
the model supported by the bounded NASA comparison. This does not establish
equivalent Luna quality or justify a global model-default change.

Server lint, strict mypy, type/config/contract checks, catalog/gateway lockstep,
web lint, all 21 web unit tests and the web build passed on the merged snapshot.
GitHub frontend and docs checks also passed, but backend CI exposed missing
clean-install dependencies and a genuine control-store deletion bug. CI provides
Postgres but omitted Qdrant; compose-contract tests also lacked the nonsecret
repository environment template. Fresh control-mode Postgres creates registry
tables only, while corpus and staging cleanup unconditionally deleted absent
chunk tables. The isolated empty-database regression reproduced both failures
before the repair; full-schema and old-schema-without-FK cases already passed.
Repairs retain explicit child-first cleanup and inspect only existing allowlisted
tables in the intended schema. Their final verification is pending.

GitHub Codex review additionally found that migrated corpus-keyed graphs returned
500 from source navigation. Such graphs now receive a typed reindex-required
response, and the source panel directs the operator to Indexing. It does not
guess an unscoped source relationship. Current-generation pagination keeps its
separate reload behavior. Initial API and browser regressions pass; the complete
final review/gate remains open before merging or deployment.

The legacy source family passes all eight real-store API tests (4.93 seconds).
Its browser acceptance exposed a separate default-width dock problem: the fixed
320px Communities column squeezed entity controls out of reach. The existing
container measurement now selects one column below 656px. All five source-viewing
browser scenarios pass (32 seconds), including a real NASA PDF, initial and
continuation legacy recovery, generation-change reload, and entity selection plus
Open Indexing at the default 360px dock width without resizing or forced clicks.
Dock navigation preserves the main page URL. Web lint/build pass after this fix.

The fresh-install repair passes 91 targeted tests. The seven-case final cleanup
matrix verifies direct and pooled connections use the intended search path,
preserves similarly named tables in another schema, and retains sibling corpus
data. The renderer regression now independently covers repository, two retired,
current and customized extraction prompts. Overlay subprocesses explicitly use
the current source via `PYTHONPATH`, avoiding a false pass from the installed old
production checkout. Final complete real-service and clean-CI suites are running.

Sol xhigh approved the legacy-source, initial cleanup, renderer, generated-contract
and narrow-dock delta, then separately approved the final three-store CI service
configuration. Evidence: `/private/tmp/astra-review-pr-fixes.out` and
`/private/tmp/astra-review-ci-services.out` on Mac. CI now provisions pinned
Qdrant 1.17.1 and Neo4j 5.26.20 with actual APOC/GDS readiness alongside Postgres.

The empty-install audit subsequently found the same absent-table assumption in
deindexing, reclaim-backlog cleanup and `delete_chunks`. The expanded real-store
matrix covers five operations across fresh control, full and no-FK schemas,
including fences, tombstones, repeated counts and sibling isolation. Three new
RED cases were reproduced; all 17 cleanup/document tests pass after repair.
That extension is undergoing its own bounded review.

The next real-service full run finished with 2,419 passes, nine skips and two
failures in 1,180.32 seconds. Sol's full-report proposal passed, but the reuse
test's first model response contained roughly 4.4 MB of malformed JSON, mostly
whitespace, and raised an unhandled official `SchemaExtractionError` after a long
wait. Proposal response limits, deadline and typed error handling remain a real
blocker; earlier focused Sol passes do not override this failure. The second
failure is the corpus-reaper parity check: its source-regex view does not represent
the new inventory loop. Shared cleanup behavior and its category coverage must
be reconciled rather than weakening that safety contract.

The clean-CI reproduction also requires actual environmental isolation on LXC:
unset optional service URLs otherwise discover existing local services, and the
literal NASA source path is present although GitHub lacks it. The final disposable
run uses only three isolated fixture stores, unused endpoints for absent optional
services, and a private mount namespace hiding corpus files from that process.
The host NASA PDF remains present. No test skips were added. Four pytest Flyte
executions created before this discovery are verified terminal by their own IDs;
no unrelated executions were cancelled.

### Proposal reliability and final gates

The final proposal reliability slice now has two typed operator limits: a
60-second default deadline (5–80 allowed) and a 16,384-token output budget
(256–32,768 allowed). The official extractor makes one attempt; decoded HTTP
responses are bounded, and malformed, truncated, refused and failed responses
produce sanitized 502/504 errors. Context changes produce 409 before persistence.
Output budget participates in approval identity. Existing proposal and approval
records survive failure. Final context validation is not atomic across filesystem
configuration and Postgres; index-start fingerprint validation remains authoritative.

All 14 Indexing browser cases pass, including limits through Apply/API/reload,
readable 502/504 recovery, and held provider responses after corpus/settings
changes. Five source browser cases also pass. The fixture uses real local HTTP,
not intercepted Playwright routes. Successful error screenshots are preserved on
Mac as `/private/tmp/astra-schema-proposal-{502,504}.png`.

The combined source passes server Ruff, mypy (171 files), type synchronization,
contract export validation, configuration reality (453 leaves), catalog/gateway
lockstep (431 rows/391 aliases), glossary validation (454 terms), frontend lint,
21 frontend unit tests and build. GitNexus maps 94 intended files to 372 symbols
and 144 processes, with critical shared-config/retrieval impact.

The final real-service run completed with 2,473 passes, nine skips and four
failures in 887.75 seconds. Three were stale policy tests missing the proposer's
new mandatory budget arguments. The fourth was the NASA reuse test's initial
provider request reaching the 60-second deadline and returning the intended typed
504. A fresh attempt with unchanged limits passed in 57 seconds. The full-report
NASA case and grounding cases passed in the broad run. This is evidence of bounded
recovery, not a claim that external model requests never time out. Logs on LXC100:
`/tmp/astra-final-reliability-full.log` and `/tmp/astra-nasa-bounded-retry.log`.

The isolated clean-CI run produced 2,443 passes, 39 skips and four failures in
510.70 seconds: the same three stale policy calls and a source-default Loki test
reading the deliberately isolated runtime URL. The 24 cleanup matrix cases,
actual no-FK API deletion sequence and redaction sweep passed. Sol's final review
reported no production-code finding in this delta, but blocked two harness gaps:
redaction corpus provisioning depended on fixture order, and configured broken
model gateways could be skipped. Reproduced RED cases cover both, plus inconsistent
strict-mode truth parsing. Focused repairs and another clean-CI gate are underway;
the PR remains unmerged and production unchanged.

The harness repair passed 106 focused cases, followed by a clean full run of
2,455 passes and 39 skips in 524.53 seconds. A subsequent review found that the
redaction fixture seeded only global credentials after corpus creation had
snapshotted the clean config. Both global and corpus stores are now seeded and
restored in the ordered lifecycle. Two no-environment-override regressions failed
before repair; all 17 redaction cases pass, including normal and exceptional exits.

Strict paid acceptance then passed nine graph cases but both NASA proposals again
hit the 60-second deadline. A controlled comparison held the full 36-chunk sample,
Sol route and 16,384-token output budget fixed: medium reasoning exceeded an
80-second model deadline (83.901 seconds including sampling); low reasoning
completed in 33.745 seconds with 29 node types, 37 relationship types and 108
patterns. The schema includes alarms, computer programs, anomalies, causes,
corrective actions and trajectories, with no forbidden document-text properties.
Evidence: `/tmp/astra-nasa-budget-{comparison,low}.json` on LXC100.

Schema planning now has its own typed `schema_proposal_reasoning_effort`, default
`low`. Semantic KG extraction retains its separate existing effort. Both effort
settings participate in approval identity; sampling, 60-second deadline,
16,384-token output limit and all NASA success/deadline assertions are unchanged.
All three strict NASA cases pass in 75.04 seconds on this change, including full
report completion and persisted approval reuse/invalidation. Evidence:
`/tmp/astra-final-strict-nasa.log`. The UI exposes all five supported efforts;
real browser/provider checks verify persistence and that KG effort remains medium.
Final combined browser, CI and bounded review gates are still running.

The final combined proposal snapshot passes 2,480 clean-CI tests with 39 skips in
524.34 seconds, plus all standard source/contract gates (454 config leaves and
455 glossary terms). The complete Indexing browser suite passes 16 cases, including
all effort choices, provider payloads, persistence and stale-reasoning cancellation.
Sol reported no source finding for the effort change. Its remaining fixture
finding was unnecessary Neo4j/Qdrant dependency on the baseline redaction sweep.
The baseline now uses canonical Postgres cleanup for its own never-indexed corpus;
additional marked cases retain real API-deletion coverage. Absent optional stores,
the old file skipped the sweep/lifecycle checks; the repair runs 17 cases and skips
only the two added API-cleanup cases. All-store coverage passes 19. A final focused
review and GitHub checks remain before merge. Source evidence is supplemented by
`/tmp/astra-pr89-ci-proposal-final.log`; only this fixture correction and execution
documentation follow that complete snapshot.

### Remaining native cost work

The recovered D1–D4 choices have a concrete implementation path within the
operator's existing constraints. Use LiteLLM's native spend logs in a dedicated
logical database/role on existing Postgres, keep `store_model_in_db=false`, and
disable prompt storage. Langfuse remains the trace sink; existing run records hold
derived totals, not a second per-call ledger. The live LiteLLM 1.94 process has no
`DATABASE_URL`, so durable native spend accounting is not enabled yet.

After the GraphRAG PR is clear, implement shared run/session/lane attribution and
the index-run slice before the NASA rebuild. Allocate proposal/run identities
before paid work; propagate context through embeddings, figures and graph calls;
persist immutable estimates separately from measured totals; reconcile complete,
failed, cancelled and restarted runs. Creating the logical database needs no
Postgres restart, but gateway wiring and application changes need controlled
restarts with indexing idle. Verify one complete small index against native rows
before NASA.

Replace the remaining direct Cohere and paid cloud-embedding routes with native
gateway endpoints while preserving provider/model, dimensions and embedding
identity. Local computation remains local. Then extend the same accounting
contract to benchmark, evaluation, Promptfoo and synthetic runs; benchmark paid
retrieval currently precedes allocation of its run ID and is missing from totals.

Native reconciliation must page results, enforce exact session identity despite
the spend API's substring filter, deduplicate request IDs, and distinguish a
missing/unpriced charge from measured zero. Existing run aggregates should expose
pending, complete and incomplete accounting with a valid chunk denominator.
Historical schema-preview spend cannot be reconstructed without supporting
records. New provider credentials, services, retention choices or an unavoidable provider
replacement would require a concrete operator decision; none is currently shown
necessary for this path. This work remains unimplemented.

An isolated native-ledger fixture now verifies the actual LiteLLM 1.94 behavior
before implementation: 140 native migrations, seven requests/rows, provider
reported positive and zero cost, usage-priced calculation, cache hits, failures,
session substring collisions, delayed writes and restart durability. It confirms
that an unpriced model can produce success plus zero spend, zero breakdown and
zero default pricing metadata. Cached responses can retain positive headers and
breakdowns while their native spend row correctly records zero; classify cache
first. A successful acknowledged request killed before native queue flush leaves
no row after restart. Native rows alone therefore cannot prove completeness.

Add aggregate request-dispatch/completion/uncertain counts and a durable census
state to existing run summaries, not a second per-call ledger. Close the census
only after every instrumented worker is quiescent and final counts are durable.
Interrupted or uncensused runs remain incomplete even if ledger rows stop changing.
The source audit also identified two required lifecycle repairs: shielded Docling
workers can continue figure calls after cancellation, and reconciling an older
summary must not make it the latest run merely by changing its modification time.
Persisted run time and the active generation govern ordering; preserve observed
chunk denominators on failure/cancellation. Local NASA embeddings and disabled
figures imply no invented cloud charges for those legs.

Fixture resources were cleaned; production was not changed. Reproduction and
evidence on Mac: `/private/tmp/astra-ledger-contract-report.md`,
`/private/tmp/astra-ledger-acceptance.py`, and
`/private/tmp/astra-ledger-contract-evidence/`.

### Benchmark scope review correction

The fresh Codex review on PR #89 identified that the displayed benchmark run cost
covered answer generation but excluded potentially billed shared retrieval. The
wire contract now states `cost_scope: generation`, persisted cost detail names
that scope, and the browser labels the amount Answer-generation cost with an
explicit retrieval exclusion. Corpus-scoped full-request traces remain unavailable
and non-authoritative until retrieval has complete accounting; unscoped generation
traces retain their measured totals. This is separate from the native whole-run
accounting work above.

The real HTTP/SDK accounting matrix now covers reported, estimated, failed and
reasoning-only outcomes with and without corpus scope. All 33 accounting/costing
tests pass. Contracts regenerated; server lint, mypy and config/contract validation
pass. The real API/browser saved-cost matrix passed all three fixture kinds,
preserving amounts and source labels while showing the explicit scope. Frontend
lint/build and type/banned checks pass. Focused Sol review and the amended GitHub
checks gate merge.

The benchmark-scope correction received an independent Sol xhigh APPROVE.
GitHub run 33942453191 on commit 28d0bf84 completed with 2,481 passed, 39 skipped
and one test failure: an exact Compose JSON snapshot expected explicit
`bind.create_host_path: false`, while the runner's serializer omitted the false
key. The source remains explicitly false. The deployment test now checks the
source requirement separately, retains the rendered mount/owner/health contract,
and rejects rendered true without depending on false-key serialization.
No deployment configuration changed for this correction.

The corrected deployment-contract suite passes all 61 tests on LXC100 and
received a focused independent Sol xhigh APPROVE. Publication still awaits
fresh GitHub checks; production remains at its previous marker with corpora idle.

### Merged deployment and native accounting continuation

PR #89 merged as bf7b9766 after final GitHub verification (2,486 passed, 39 skipped)
and independent Sol approvals of the final corrections. The merge's CI, including
the Docker build, also passed. All four production corpora were idle before the
controlled deployment. Production HEAD and deployment marker now match bf7b9766,
the checkout is clean, and /api/ready reports every required dependency ready.
The authenticated Graph UI loaded a six-node/five-edge fuel-tank neighborhood,
listed five source mentions, and opened/rendered A11_MissionReport.pdf page154.
NASA's old graph remains active; its rebuild has not started.

Native accounting is a separate, uncommitted slice. The existing index summary now
has optional aggregate accounting, immutable configuration/model/estimate identity,
processed denominators, and durable per-lane census checkpoints. Index and proposal
attempts have distinct IDs. Latest-index selection uses start time instead of file
mtime; the dashboard selects the exact manifest run. Atomic summary replacement
and stable file locks preserve newer checkpoints across queued status writes.
An OS lifetime lock distinguishes retained workers from an abandoned process.
The integrated census, native reader, and root owner tests passed139 cases on the
private LXC overlay. Generated contracts were refreshed there and synced to source.
API lifecycle, dashboard history semantics, and UI integration are still being
validated; these changes are not deployed.

Sol found an inbound/outbound role-membership gap in native ledger setup. The
provisioner now refuses either membership direction before creating resources.
The real disposable-Postgres setup/catalog suite passed69 tests. Docling census
integration uses the supported picture-model factory, preserves official crops
and annotations, and scopes its converter cache to the run; its11 direct cases
and existing35-case family passed (one explicitly unconfigured paid test skipped).
A further native retry investigation found inner SDK retries that router-level
counters alone do not prove absent. Policy verification remains conservative
until a native gateway/provider-attempt matrix validates the supported settings.
No native production database or paid NASA rebuild has been started.

### Native accounting integration and independent review follow-ups

The isolated native retry matrix reproduced three provider attempts for a failed
embedding request despite router/request retries being zero. Both the process
`DEFAULT_MAX_RETRIES=0` and native `litellm_settings.DEFAULT_MAX_RETRIES: 0` are
needed. The canonical generator now emits explicit zero retries for all391 aliases
and disables retry policies, fallback families and shadow/failover routing. Exact
native startup with networking disabled confirmed the generated configuration;
61 catalog and38 disposable-Postgres setup tests passed. Native management APIs
still cannot prove the effective cached SDK settings. Runtime accounting therefore
retains an unverified-policy qualification instead of declaring a complete total.

Index, figure and proposal calls carry explicit durable census scopes, with
worker leases surviving cancellation. Frozen original gateway roots allow later
reconciliation after configuration changes or corpus deletion. Real HTTP/API
history cases passed3/3 across reconfiguration, deindex and corpus deletion.
Failed proposal responses expose their attempt IDs, and latest proposal-attempt
history is a separate query from latest indexing history. The combined schema,
Dashboard, replay and cost API suite passed75 tests. Ancillary estimate failures
now save an unavailable quote without replacing the actual indexing source and
chunk-count checks; both real-file regression cases passed.

Deindex no longer erases run summaries or late worker checkpoints. Fourteen real
Dashboard/API cases passed, including complete/failed/cancelled/held-worker
history and exact live-manifest cost selection. The first native cost browser
suite passed five cases: delayed ingestion, bounded retry/manual refresh, legacy
and incomplete states, Dashboard refresh, and shared main/dock requests. Sol's UI
review then identified failed-proposal discoverability and additional corpus
switch races; those corrections and their browser regressions are in progress.

Independent Sol owner review found recovery and concurrent reconciliation races,
non-atomic bootstrap, duplicate-owner mutation, lock path aliasing and a stale
returned snapshot. These are being corrected with real filesystem/HTTP concurrency
coverage before publication. A separate Sol API integration review is running.
The native accounting slice remains uncommitted and undeployed. No native
production ledger database, NASA rebuild, or code-corpus refresh has started.

### Further review, test isolation, and native trace integration

Sol's API review identified four additional defects: the proposal deadline excluded
initial inventory and final persistence; current status returned deleted-corpus
history; figure ceilings omitted failed attempts; missing gateway credentials or
invalid client construction bypassed durable reconciliation errors. The correction
uses one reschedulable deadline from the original monotonic start, retains a typed
failed attempt even when no dispatch/census began, preserves explicit historical
run access while returning404 for deleted current status, counts failed picture
attempts, and saves reconciliation errors under a captured-record equality guard.
Real PostgreSQL table/row locks reproduced both timeout families against the old
code, then passed against the fix. Final combined verification is pending.

The initial full native snapshot ran2,803 passing tests,40 skipped and36 failing.
The launcher incorrectly disabled the OTel SDK, overrode the refusal suite's
Postgres configuration through POSTGRES_DSN, and omitted CI's example.env copy.
Two catalog assertions also predated explicit SDK retries, and the new glossary
term lacked its public mirror. Correcting these yielded35/36 passing; the remaining
failure was a third retry snapshot assertion. These are preliminary results, not
the final combined gate.

Sol's second owner review confirmed the original six fixes and found a duplicate
constructor's transient lifetime lock could hide an abandoned owner, plus zero-lane
completion retained stale reconciliation and changed its end time on repeated calls.
Duplicate rejection now occurs under the summary lock before lifetime ownership;
completion invalidates prior reconciliation and repeats without changing a closed
record. Census progress also clears obsolete reconciliation errors. Real process,
filesystem and HTTP regressions passed65 cases before adding the run trace lifecycle.

The Sol UI review's initial private API launcher inherited production endpoints.
Four synthetic schema requests reached the live gateway with Sol and returned200;
their saved attempt IDs are d6cc7bdcb9b248f5ad3265520c3df1f0,
ba27c6efacbd4260abf8176417779103,9db4fa9c32a246f09cddb8e809b9d7a0,
and75598e9593ba4eec8b06aacc5d738b5d. All censuses are closed and quiescent.
The payloads were fictional acceptance documents and standard schema instructions.
Native usage/cost was unavailable; no zero-charge claim is made. Eighteen temporary
corpus lifecycles also used production PostgreSQL, and their owned records were
confirmed removed. The private API was stopped; production services were untouched.
These runs are excluded from acceptance. A subsequent private startup briefly
attached the profiler to the existing collector; profiling is now explicitly
disabled and its URL blank. The replacement launcher uses env-i, explicit disposable
endpoints, synthetic credentials and resolved-configuration assertions.

Native billing and trace visibility are separate contracts. The running gateway
had only the Prometheus callback and no Langfuse project configuration. Pinned1.94
fixture verification established supported Langfuse session metadata, W3C parent
joining, and message redaction through turn_off_message_logging. Implementation is
adding one run observation retained through actual worker closure, explicit context
in census transports, low-cardinality lane metrics, and native Langfuse generations
while removing duplicate app generation emission. Native fixture, privacy, stream,
failure, and exact-count verification gate activation; production is unchanged.

### Final native backend gate and containment correction

The combined backend snapshot passed 2,914 tests with 38 skips in 672.68 seconds
on LXC100. Native gateway policy and telemetry integration were enabled. Ruff,
strict mypy (178 source files), banned-pattern checks, generated types, both
glossary copies, configuration reality and the contract bundle also passed.
Focused results included 224 native telemetry/setup cases, 73 owner lifecycle
cases and 53 history/Docling/dependency cases. Independent Sol xhigh review
approved the canonical run trace routes and exact corpus/run history guards.
The original owner and API findings are resolved; final native telemetry review
and the integrated browser gate remain in progress.

The history guard preserves existing filesystem paths while rejecting lossy
corpus/run directory aliases. Latest summaries, exact records, event listings
and stage replay now verify the stored identity. The regression matrix covers
both run kinds, three corpus-collision families and mixed run-ID event rows.

A later UI rerun passed EXHAUSTIVE_API_BASE instead of the required
EXHAUSTIVE_API_BASE_URL. The old guard ran after setup, so two temporary corpora
were created, patched and deleted in production at 06:29:23–24 UTC. No index,
proposal, completion or embedding route ran; gateway logs confirmed no provider
requests in the surrounding interval. Production registry, PostgreSQL and Qdrant
checks found no matching records. Root moved the 16 owned lineage assets and two
lock files to an audited private quarantine; none of those paths remain in
production. The failed rerun is excluded from acceptance.

The native-cost suite now fails during collection unless both explicit endpoints
name its private loopback fixtures and its working directory is a private LXC
overlay. Before any corpus mutation it checks resolved global configuration
through both the API and browser proxy, including stores, gateway and disabled
external integrations. Missing, misspelled and production endpoint settings were
actually rejected before hooks. The dependency and telemetry mutation matrix
also passes. Root owns further browser execution.

Live Graph acceptance also reproduced a delayed Reset response overwriting a
newer search. The correction uses shared request generations across the main
view and dock; its real response-ordering regression is in progress. Epstein's
approved two-type Person/Email schema is intentional and matches the completed
D19 source record; absence of Organization is not a reason to rebuild it.

The final native browser run reproduced a Dashboard status race missed by the
earlier UI review: a delayed corpus A response replaced the index details after
switching to corpus B, until the next 30-second refresh. The index-details card
now rejects stale callback starts, results, errors and loading completion using
a request generation plus the current corpus, and invalidates on cleanup. Both
switch directions pass. The complete native UI gate is now nine passing cases
in 1.4 minutes. Integrated frontend lint, 23 unit tests and build also pass.

The Graph fix passed seven strict real API/browser cases in 20.6 seconds. Each
held response retained its original status and body SHA after release. Coverage
includes Reset, search, entity and community selection, corpus change, parallel
loading completion and a stale real 404. The only earlier setup failure returned
empty real graph data during overlap with the full backend fixture cleanup;
repeating after that suite ended passed without another product-code change.

Sol's native telemetry review then identified missing default-fallback validation,
duplicate environment binding conflicts, native-readiness wording, failure-only
metric lane loss in pinned LiteLLM, and absent exported usage/cost assertions.
Corrections are in progress. These review findings do not invalidate the recorded
passing snapshot, but that snapshot is not the final publication gate.

### Remaining wider E scope, verified against current source

The native index/schema slice does not close every paid workflow. A separate
read-only call-chain audit confirmed these remaining items:

- Cloud embeddings from indexing, retrieval, semantic cache and Recall still
  share Embedder._embed_openai with environment-derived direct OpenAI routing
  and combined application/SDK retries. Canonical EMB gateway aliases and
  explicit call-site identity/census remain needed. A transport-only repair
  must preserve dense contracts, dimensions, preprocessing and cache identity.
- Cohere reranking still calls cohere.Client.rerank in a worker thread. The
  existing LiteLLM option is LLM listwise reranking, not native /rerank. Move
  the supported Cohere capability onto the native gateway substrate; the
  reranker cost endpoint must stop reporting hard-coded zero.
- Benchmark allocates its ID after shared retrieval; Eval POST/SSE and Promptfoo
  allocate IDs after work. Synthetic correctly saves an ID before scheduling,
  but generation, judging and its Eval quality gate do not propagate accounting.
  These existing run records need explicit pre-work identity and honest native
  reconciliation coverage. Promptfoo also needs subprocess lifecycle accounting.
- Shared generation currently derives attribution from tracing and uses a generic
  generation lane; billing identity must remain present when tracing is disabled.
  The middleware also lacks inbound W3C parent extraction for nested workflows.

The implementation order is cloud embedding transport, native Cohere replacement,
Benchmark/Eval/Synthetic run scopes, then Promptfoo subprocess attribution. This
is a continuation of the recovered D2–D4 requirements, not a new approval cycle.
NASA rebuild and deployed operator acceptance remain ahead of these later slices.

The final containment inventory found no production lineage files for the first
18 temporary corpora. Their 18 locks and 148 assets are confined to the originating
private API overlay and retained with the audit. The known provider history remains
exactly the four previously recorded synthetic schema calls.

Sol approved the Dashboard and native fixture guard corrections. Its Graph review
found one further state transition: deleting the last corpus left the old shared
graph visible when the selected corpus became empty. That empty-corpus transition
is being corrected with a real browser regression before the Graph slice freezes.

### Publication candidate verification

Sol xhigh approved the five telemetry corrections and then the narrow final
Graph, fixture-selection and observed-policy fallback corrections. The Graph
empty-corpus regression now passes through actual last-corpus deletion and
registry refresh, with held original responses, real 404 recovery and disabled
exports. Nine Graph cases pass. A separately observed stale config error in the
shared Apply bar after deleting the last corpus remains an operator follow-up;
it is not Graph data or selection state.

The final combined local backend run completed with 2,938 passed, 38 skipped and
three test failures in 687.52 seconds. Two expected retired Langfuse key/readiness
wording. The cancellation fixture waited for one server arrival but asserted two;
its new explicit second-arrival barrier establishes the two-running/one-queued
scenario before cancellation. The entire affected API and census suites then
passed 26 cases. Production code did not change for these test corrections.
A fresh full CI run is required before merge.

The final source snapshot passed Ruff, strict mypy (178 files), types, glossary,
configuration, contracts, frontend lint, 23 frontend unit tests and build. Native
browser execution passed all nine cases in 1.4 minutes against the final source
with the explicit NATIVE_COST_FIXTURE=1 selector. Without that selector ordinary exhaustive
collection skips this private-only suite; strict mode refuses missing setup.
The wrong-name, missing and production endpoint cases still fail before hooks.

GitNexus indexed 23,615 nodes and 966 flows, with documented static-analysis
limits. Its staged analysis reported critical scope across 69 files, 965 symbols
and 95 traced flows, matching indexing, configuration, observability and operator
UI ownership. The two unrelated instruction-file edits remain excluded.

### PR90 review corrections

The first PR90 CI run completed successfully: 2,911 passed and 68 environment-gated
skips in 858.61 seconds, plus frontend build and all contract gates. GitHub review
found two P2 accounting defects. Duplicate native call IDs now suppress the
ambiguous native logged subtotal; twelve provider-priced, gateway-priced and
cached-row variants failed before the fix and all 77 reader tests now pass.

Successful forced schema regeneration now immediately selects the returned
accounting ID even if the latest-history lookup fails. Historical requests begun
before a newer operator action cannot overwrite its result. Proposal success and
failure contracts carry the actual durable attempt start time, including cached
successes, context conflicts, provider timeouts and no-indexable-text refusals.
Ordering never compares proposal completion time or browser time. Legacy records
remain explicitly undated; a same-run legacy cache response cannot erase a known
timestamp and hide a later successful attempt.

The old-ID, overlapping-start and legacy-cache browser regressions each failed
against the preceding implementation at their intended accounting-ID assertions.
The corrected API and reader suites pass 126 cases; all response timestamps agree
with their durable summaries. Final frontend lint, 23 unit tests and build pass,
as do Ruff, strict mypy, configuration, type and contract checks. All nine final
native browser cases pass in 1.4 minutes. Sol xhigh approved the final correction
after its earlier findings were addressed. GitNexus reports the expected critical
shared-code scope: 70 files, 1,006 symbols and 95 affected flows. The CLI still
caps its displayed names with a larger limit, while reporting that its counts and
risk cover all changes; exact staged paths were checked separately. A fresh PR
review and full CI run follow.

The amended PR90 head `9c3bb56b` passed full CI with 2,922 tests and 68
environment-gated skips in 860.85 seconds. GitHub Codex review reported no major
issues on that exact head. PR90 merged as `2a3555a7` on September 5 at 08:42 UTC;
post-merge CI passed, including the Docker build and container test. Production
activation completed at 09:05 UTC on that exact commit. All nine preexisting
GitNexus tooling paths were preserved byte-for-byte. The native ledger migration
verified 140 completed migrations; native gateway readiness and the deployed marker
were verified after startup.

### Separate operator follow-ups

The Cost & Capacity dashboard follow-up uses UTC midnight for Today and retains
explicit selected-range and seven-day meanings. Native model/lane counters use
reset-aware queries and normalize absent lane labels to unattributed. The pinned
collector experiment confirmed that an asynchronous OTLP export failure does not
necessarily emit a callback-failure counter sample. Scoped terminal-error logs
therefore remain separate evidence. Their zero is guarded by the presence of logs
from the same gateway service; absent or foreign-only logs remain unavailable.
Five real Loki cases, the real Prometheus reset/midnight matrix and nine dashboard
tests pass. Sol approved the final presence correction. No production dashboard
change has been made yet.

Shared config loads now pin corpus/global scope and reject older selection epochs,
including A to B to A. The private Graph browser suite passed 14 cases after a
test-observer correction: Vite's actual timestamped module URL must be reused to
inspect the rendered app's store. Frontend lint, 21 unit tests and build passed in
that Graph overlay. Sol then found a further upstream recurrence: an older corpus
registry response can resurrect a deleted corpus after a newer forced refresh.
The new held-response regression reproduced that recurrence against the prior
store. Registry publication now fences success, failure, loading, URL/storage
canonicalization and events by request generation. All 16 Graph browser cases
pass, including old and new concurrent registry loads. All nine accounting UI
cases also pass with these shared-store changes. Final frontend lint, 23 unit
tests, build, nine dashboard tests with the real Prometheus query engine, Ruff,
banned-pattern and generated-type checks pass. Sol approved the final registry
correction; E5 and this config correction are frozen for their own publication.

The cloud-embedding transport continuation has begun as a separate source slice.
It will route existing OpenAI embedding calls through the native gateway with
explicit identities while preserving local embedding paths and dense contracts.
It is excluded from the pending PR90 deployment and NASA rebuild.


### September 5: live accounting and corpus recovery follow-through

The approved NASA schema attempt `e3e16387536941029e634ea4bddbc9da` completed
at 09:09:14 UTC after 33 seconds. The browser recovered the cached schema after a
usage interruption without generating another paid proposal. Its 26 node types,
34 relationship types and 89 directed patterns cover alarms, programs, trajectories,
anomalies, failure causes and corrective actions; schema hash is
`faa5b42a4876bd8e2c8ba43751fe856d2e69c288e45301efd1d600378e16375c`.
Native reconciliation matched one request and $0.0649835 provider-reported spend,
with 10,602 input and 3,848 output tokens. The delivered Langfuse generation and
historical Mimir schema-proposal counters agree with that usage and cost. Native
ledger content is absent; Langfuse input/output contain redaction placeholders.
The browser correctly retains the unverified gateway-attempt-policy qualifier.

The ordinary NASA rebuild attempt `f899295ba26d4b179d64ef714378bf69` refused
at 15:10:47 UTC before any extraction dispatch: the embedding guard reported stored
deterministic versus configured provider. The active generation remains unchanged.
The authoritative Postgres column is provider; the guard incorrectly read the absent
nested metadata key as deterministic. NASA, Epstein and code share that promotion
metadata shape. The guard correction reads only the canonical column and refuses
unknown identities. Its 10-case matrix reproduced nine failures on the old guard;
all 13 relevant promoted-lane cases pass with the correction, and Sol approved it.
No production metadata was manually repaired.

GitHub PR91 identified two further corpus recovery cases: an initial registry
failure followed by a pending retry could switch config to global, and stale forced
refresh callers could return before the winning registry published. Both behavioral
regressions failed on the prior stores. Successful registry resolution now has
explicit state, and forced/shared callers follow successive winning request promises.
All 18 real private Graph browser cases pass, including both new recovery cases.
The first chain harness attempt held three identical requests and reached its
fixture deadline; the corrected test holds at most two while exercising A-to-B-to-C
supersession. This intermediate 18-case result was superseded by the final 26-case matrix
and nine accounting cases described below.

The first focused D3 embedding suite passed 133 tests with one environment-gated
skip. Its core Sol review found three valid issues: application processes could
retain the upstream key, catalog upserts filled an invalid embedding base URL, and
HTTP 408/409 did not receive configured application retries. Corrections and broader
family tests are in progress. D3 remains excluded from deployment.

### September 5: failed full NASA replacement and remaining blockers

The explicitly forced staged replacement `0152e29560bf4d1fa9216375891b9d4f`
started at 15:21:38 UTC. Docling completed at 15:42:36; semantic KG requests began
at 15:42:39. Extraction failed with a request timeout at 15:46:17, before resolution
or community summaries. The active generation `3054ecc26d3649a086758e04ece30488`
and its 1,002 chunks/dense points remain intact. Failed staging rows, graph and
Qdrant collection were reclaimed, and the run fence was released.

The native census contains 131 actual HTTP attempts with nine uncertain outcomes.
The ledger subsequently recorded 130 successful provider rows totaling $3.0555729;
the browser's manual refresh at 15:57:55 matched that amount and retained incomplete
coverage with one missing request. Six native requests exceeded the configured
30-second timeout (maximum 41.093 seconds), and five provider completions arrived
after application failure. Four application OpenAI SDK retry delays were logged
even though native gateway retry fields were zero. The official wrapper also has
an independent rate-limit retry handler. Both hidden retry layers are now explicitly disabled in the pending PR91
source. The real HTTP matrix failed 33 cases on the old source; all 92 relevant
KG/census tests pass after the correction, and independent Sol review approved it.

The graph telemetry's 1,002 attempted/failed count is a whole-file exception count,
not actual dispatch evidence. All chunks ran inside one official pipeline execution;
successful per-chunk results were in memory and cannot be recovered from the
content-free ledger or redacted traces. The estimate of $3.2875 also omitted most
serialized schema/prompt overhead and understated output: observed requests averaged
7,646 input and 493 output tokens. A retry must follow corrected estimation and
timeout/retry handling; durable extraction reuse and truthful progress are being
assessed. No additional paid full run has been started.

D3's reviewed 38-source suite passed 249 tests with one provider-capability skip.
Sol's further catalog-family finding reproduced 13 failures in the broader upsert
matrix; all 32 endpoint cases now pass. Existing model families are preserved, and
new families derive from model identifiers rather than request capability labels.
Final Sol review approved this correction. Ruff, mypy (179 source files), banned
patterns, generated types, contract bundle and the 454-key config reality check pass.
D3 is still undeployed.

PR91's final failure correction returns an explicit non-rejecting registry-load
outcome and preserves the newest settled result for older mutation callers. An
actual failed winning refresh reproduced the old mutation falsely reporting success.
Sol approved the source correction. All 26 real Graph browser cases and all nine
native-accounting browser cases pass on the final stores. The browser test driver
now keeps async operations rooted in the actual rendered page: raw CDP evidence
identified a collected evaluation promise, rather than application navigation. A
separate update assertion now uses the supported corpus name field. Independent
Sol review approved the driver changes. One earlier private rerun collided with
pytest corpus cleanup sharing Neo4j; the final suites ran exclusively. Production
was unaffected. Frontend lint, 23 unit tests, build, Ruff, mypy (178 source files),
banned patterns and generated-type checks pass. GitNexus reports 14 changed files,
66 symbols and 36 expected shared-store flows at critical risk.

The extraction recovery plan is recorded separately in
`graphrag-extraction-recovery-2026-09-05.md`. Checkpoint persistence and a forecast
that includes approved schema/prompt overhead are under implementation; neither
is deployed or claimed accepted. No additional paid NASA rebuild has started.

### September 5: compact indexing results and release verification

The operator identified excessive permanently expanded accounting and schema text.
Run and proposal costs now start with a short recorded amount and qualified status;
exact amounts, estimates, census, provenance and refresh notes are in closed Details.
Schema review shows entity/relationship names and properties; raw JSON, versions,
identifiers and source hashes are under technical details. Run and graph diagnostics
also start closed. Errors and cost uncertainty remain visible. Both estimate consent
callers use a short summary with expandable assumptions; unknown totals never become
an embedding-only price. Semantic quick-start leads to the existing schema review.

Private browser verification covered 24 scenarios: the combined rerun passed 23,
and the remaining quick-start case passed after correcting its expected /web route.
Earlier fixture corrections made the missing-path case explicitly graph-off and
matched the current Keywords label without case sensitivity. The last status-helper
review correction has a terminal/live/idle/missing-state matrix; all 36 frontend
unit tests, lint and build pass. Independent Sol approved the final UI corrections.
The rendered main/dock/narrow cost and schema screenshots were inspected; production
activation is still pending the release gates.

PR91 head 53bb7b90 passed GitHub review but CI had four failures with 2,965 passes
and 69 skips. Three real PDF tests hit Hugging Face classifier download rate limits;
the fourth assumed every catalog vision model had a documented formula. The pending
CI correction provisions and verifies pinned Docling model files before testing,
without changing other Hugging Face clients. The vision family regression also
found undocumented model prefixes inheriting known image bounds: the old source
failed 72 of 112 new cases. Unknown image formulas now fail explicitly. A fresh
private artifact directory and verify-only preflight both pass. Full release tests
and independent review of this CI correction are running.
