# OSS-Composition Fork Kickoff

Date: 2026-03-24
Branch: `feat/oss-composition-kickoff`
Status: active execution program

## Goal

Formalize and start the ragweld OSS-composition fork as a real execution program.

The fork should preserve ragweld's overall MLOps/workbench feel while replacing as
much bespoke platform machinery as possible with established OSS components,
frameworks, protocols, and products. Custom code should survive only where it is
genuinely product-defining: provenance stitching, corpus identity, config
translation, workbench composition, eval analysis, and drilldown synthesis.

## Scope

- Lock the target architecture for the fork so we stop re-litigating major
  subsystem choices.
- Preserve the product-defining surfaces that make ragweld feel like ragweld.
- Start the fork with bounded migration seams instead of a monolithic rewrite.
- Establish workstreams, phase gates, and verification expectations.
- Establish explicit memory discipline so decisions and reversals stay durable
  across agents and turns.

## Non-goals

- Shipping the full fork in one branch.
- Preserving every current implementation detail.
- Preserving the current chat implementation or chat contract out of inertia.
- Mass-renaming `tribrid` identifiers to `ragweld`.
- Hand-editing `mkdocs/**` or `mkdocs.yml`.
- Building a second bespoke control plane on top of Flyte, LiteLLM, MLflow, or
  Langfuse.

## Protected Product Surfaces

These surfaces are protected at the product level even if their implementation
changes completely:

- Workbench shell and dock/splits experience.
- Embedded Grafana and the operator-console feel.
- Training Center as a first-class in-product surface.
- Eval analysis and drilldown as a first-class in-product surface.

Chat is explicitly not protected as an implementation. It should be rebuilt on
stronger OSS foundations inside the ragweld shell.

## Locked Stack

- Inference: `vLLM` for self-hosted serving.
- Gateway/routing: `LiteLLM` as the unified proxy/router over `vLLM`, hosted
  providers, and any remaining legacy external backends.
- Orchestration: `Flyte-first`.
- Retrieval/indexing: `Haystack + Docling + Qdrant`.
- Graph parity: `Neo4j` stays in v1 so graph surfaces do not disappear during
  the fork.
- Training execution: `Unsloth`.
- Runs/evals/regressions: `MLflow + Ragas + Promptfoo`.
- Eval drilldown substrate: `Langfuse-first` for traces, prompts, spans, and
  per-example inspection.
- Frontend shell/workbench: `Dockview + react-resizable-panels + TanStack Query
  + assistant-ui + shadcn/ui + Radix + xterm + Monaco`.

## Locked Observability Layer

- Canonical signal standard: `OpenTelemetry` for trace context, spans, logs, and
  cross-service correlation.
- Collector/agent: `Grafana Alloy` everywhere.
- Metrics backbone: `Prometheus` for scrape compatibility plus `Grafana Mimir`
  for long-retention multi-tenant metrics.
- Traces backbone: `Grafana Tempo`.
- Logs backbone: `Grafana Loki`.
- Continuous profiling: `Grafana Pyroscope`.
- Frontend/browser telemetry: `Grafana Faro`.
- LLM-native tracing and prompt observability: `Langfuse-first`.
- Cost layer:
  - `LiteLLM` for gateway budgets, spend, and model/provider accounting.
  - `Langfuse` for per-trace and per-generation cost attribution.
  - `OpenCost` for infra and cluster/GPU cost allocation.
- Workflow/run truth stays:
  - `Flyte` for workflow state and execution lineage.
  - `MLflow` for run, artifact, model, and eval truth.

## LiteLLM Security Pinning Rule

- Use an exact LiteLLM version, never a loose range.
- As of 2026-03-24, the newest patched GitHub stable release already captured in
  this branch is `v1.82.3-stable.patch.2` published at `2026-03-24T06:10:51Z`.
- PyPI currently shows `1.82.6`, but that package was uploaded earlier on
  `2026-03-22T06:36:00Z`, so do not assume it contains the same post-incident
  patch set.
- Until re-verified, prefer pinning the patched GitHub release tag instead of a
  floating PyPI version.

## Compatibility With The Locked Stack

- `vLLM` remains compatible with the observability plan because it exposes
  Prometheus-style metrics on its OpenAI-compatible server.
- `LiteLLM` remains compatible because it gives us a single routing and budget
  layer plus Langfuse and metrics integration points.
- `Langfuse` remains the LLM-native trace substrate rather than a replacement
  for MLflow or Flyte truth.
- `Flyte` remains the orchestration backbone, but its logs, metrics, and traces
  must flow into the same Grafana and OTEL fabric instead of becoming an island.
- `MLflow` remains the run and artifact system of record and should be linked
  from traces and dashboards rather than duplicated.

## Ragweld-Owned Logic That Survives The Fork

Upstream tools provide raw materials. Ragweld still owns:

- run-vs-run comparison
- changed config, prompt, model, dataset, and retriever analysis
- regressed vs improved example surfacing
- source-aware and provenance-aware explanation
- AI-written comparison synthesis grounded in real artifacts and traces
- the operator-facing observability UX inside the workbench
- the combined view that ties together cost, quality, provenance, and trace
  evidence in one surface instead of splitting them across multiple products

## Implementation Changes

- Replace router-owned jobs, JSON run registries, file-backed state, and ad hoc
  orchestration with Flyte, Postgres metadata, and MLflow artifacts.
- Replace OpenRouter-first runtime assumptions with `LiteLLM -> vLLM` as the
  default serving path.
- Replace bespoke extraction, chunking, embedding, and fusion orchestration with
  `Docling + Haystack + Qdrant`, while keeping ragweld-specific provenance and
  codebase identity stitching.
- Keep `Neo4j` and rebuild only the graph ingestion and retrieval glue needed
  for source-grounded graph parity.
- Rebuild chat on `assistant-ui` and standardize the broader shell on the locked
  frontend stack.
- Replace custom docs and spec systems with deterministic docs from Pydantic,
  OpenAPI, and JSON Schema into MkDocs.
- Replace custom tracing and log buffers with Langfuse plus the locked
  OpenTelemetry and Grafana stack.
- Keep Pydantic and FastAPI as the contract boundary, but split the current
  monolith into smaller schema and config packages and generate frontend clients
  and types from the resulting standard artifacts.

## Replacement Means Removal

- Yes: when an OSS subsystem wins, the goal is to remove the bespoke subsystem
  it replaces rather than keeping both forever.
- Compatibility adapters are allowed only as migration seams while parity is
  being proven.
- Every replacement slice must define:
  - the old code path being retired
  - the temporary adapter or bridge, if any
  - the parity gate required before deletion
  - the explicit cleanup step that removes the obsolete code path
- Do not accept "wrapped legacy forever" as success. A thin adapter around an
  old subsystem is only acceptable if it has a scheduled deletion target.
- The architecture gate is subtractive by default: any surviving custom
  subsystem must justify why no maintained OSS alternative is suitable and why
  the remaining custom code is smaller than the replaced bespoke surface.
- Protected product surfaces stay; weak implementations do not.

## UI Is Part Of The Slice

- Every fork slice must include its operator-facing workbench surface, not just
  backend plumbing.
- Do not treat UI parity as optional follow-up when the slice changes runtime,
  retrieval, indexing, training, eval, graph, or observability behavior.
- Minimum acceptance for any material slice:
  - the affected workbench surface still exists and remains understandable
  - operators can see the new backend state and next-step guidance in-product
  - protected surfaces are not silently degraded while backend work lands

## Public Interfaces

- Preserve route-level and UI-level continuity where useful, but do not freeze
  the current chat contract or the current backend architecture.
- Keep `FastAPI + Pydantic` as the public contract layer.
- Keep MCP on the official Python SDK and limit custom MCP logic to
  ragweld-specific tools and policies.
- Use compatibility adapters during migration so the current workbench can
  survive backend swaps incrementally.

## Workstreams

### 1. Runtime, gateway, observability, and cost

- Owns the `LiteLLM -> vLLM` path, provider compatibility, online request
  telemetry, cost instrumentation, and cross-service tracing.
- First bounded slice: define the runtime gateway contract, config surface,
  OTEL propagation, Langfuse hooks, and low-cardinality metrics labels without
  ripping out the current providers yet.
- Exit criteria:
  - online request path is traceable end to end
  - budget and spend surfaces are visible
  - serving, routing, and gateway failures are diagnosable from the workbench

### 2. Training, evals, drilldown, and lineage

- Owns Training Center migration, workflow lineage, run truth, eval orchestration,
  and ragweld-specific comparison logic.
- First bounded slice: define one `Flyte + MLflow` job family plus the
  `Langfuse + MLflow + Ragas + Promptfoo` drilldown data model.
- Exit criteria:
  - one bounded workflow is launchable through the new stack
  - run artifacts and statuses land in MLflow truth
  - drilldown can explain regressions and improvements per example

### 3. Retrieval, indexing, and graph parity

- Owns ingestion, chunking, retrieval orchestration, provenance contracts, and
  v1 graph parity.
- First bounded slice: isolate a `Docling + Haystack + Qdrant` ingestion and
  search seam while preserving current provenance output semantics.
- Exit criteria:
  - indexed corpora preserve source file and line fidelity
  - graph views do not disappear during migration
  - retrieval quality and provenance remain measurable

### 4. Frontend shell, chat, and workbench migration

- Owns dock layout, shell composition, embedded observability, operator
  utilities, and the new in-shell chat experience.
- First bounded slice: create an `assistant-ui` migration seam and document the
  chat semantics that must survive: recall injection, source grounding,
  streaming, retry behavior, and session continuity.
- Exit criteria:
  - shell parity is visually and interactively credible
  - chat passes its new acceptance contract
  - protected surfaces still feel first-class inside the workbench

### 5. Contracts, docs, and migration sequencing

- Owns Pydantic contract decomposition, generated clients and types, deterministic
  docs, and compatibility adapters between old and new subsystems.
- First bounded slice: split the first contract surface out of the current
  monolith and prove the generated artifacts can drive the web client and docs.
- Exit criteria:
  - no hand-written frontend API payload types are reintroduced
  - contract generation stays mechanical
  - migration order is documented and reversible

## Delivery Phases

### Phase 0. Program setup

- Lock architecture, protected surfaces, observability layer, and memory rules.
- Start the branch with a single execution charter and indexed project memory.
- Done when:
  - this kickoff plan is the canonical execution artifact
  - project-local memory has a formal kickoff entry
  - first-slice boundaries are explicit

### Phase 1. Migration seams

- Build the first bounded slice in each workstream without forcing global cutover.
- Preserve current workbench continuity with compatibility adapters.
- Done when:
  - each workstream has one real seam implemented or explicitly staged
  - new artifacts can be exercised without deleting the old path yet

### Phase 2. Vertical pilots

- Prove the stack on end-to-end flows instead of subsystem demos.
- Required pilot shapes:
  - indexing -> search -> chat with trace and provenance evidence
  - workflow launch -> logs -> artifacts -> Training Center status
  - eval run -> drilldown -> run-vs-run analysis with regressed examples

### Phase 3. Shell parity and cutover hardening

- Replace remaining bespoke internals behind stable workbench surfaces.
- Use screenshot and interaction parity gates for protected surfaces.
- Keep architecture pressure on deleting bespoke code instead of wrapping it.

## First Implementation Slices

1. Runtime slice: define the `LiteLLM + vLLM` boundary, config surface, cost
   hooks, and observability propagation.
2. Chat slice: establish the `assistant-ui` migration seam and the semantic
   contract for recall, sources, streaming, retries, and sessions.
3. Workflow slice: define the first `Flyte + MLflow` run model for one bounded
   job family rather than trying to migrate every job at once.
4. Retrieval slice: isolate the first `Docling + Haystack + Qdrant`
   ingestion/search seam while preserving provenance output contracts and graph
   parity hooks.
5. Eval slice: define the `Langfuse + MLflow + Ragas + Promptfoo` drilldown
   model before rebuilding the screen.

## Test Plan

- Require screenshot and interaction parity for the workbench shell, dock
  behavior, Grafana embed, Training Center, graph view, and eval drilldown.
- Treat chat as a fresh acceptance target: streaming, recall injection, source
  citations, retry behavior, and session continuity must all pass.
- Run end-to-end flows for indexing, search, chat, graph exploration, training
  launch, training logs, eval runs, and run-to-run analysis.
- Add regression gates for:
  - retrieval quality
  - provenance correctness
  - workflow resumability
  - eval comparison accuracy
  - drilldown fidelity for per-example regressions and improvements
- Add an architecture gate: any surviving custom subsystem must justify why no
  maintained OSS alternative is suitable.

## Memory And Decision Discipline

- Keep long-lived fork memory only under
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/`.
- Every material fork decision must do both of the following in the same turn:
  - update the relevant repo-local execution or reference doc if it changes
    architecture, scope, contract, or acceptance criteria
  - add or update a project-local memory note and keep
    `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
    indexed
- New memory notes for this program should stay short and use the durable
  structure:
  - `Context`
  - `Decision`
  - `Evidence`
  - `Next`
- If a change alters the locked stack, protected surfaces, or observability
  layer, update this kickoff doc in the same turn instead of letting memory
  drift away from the repo artifact.
- Workstream-specific notes should capture:
  - what changed
  - what was rejected
  - what remains unverified
  - what should happen next

## Acceptance Criteria

- The branch contains a single source-of-truth kickoff plan for the fork that
  captures the locked stack, observability layer, protected surfaces,
  workstreams, phase gates, and first implementation slices.
- The plan explicitly preserves:
  - the general ragweld workbench feel
  - embedded Grafana
  - an in-product Training Center
  - an in-product eval analysis and drilldown surface
- The plan explicitly allows:
  - a substantial chat rebuild on OSS foundations
  - meaningful OSS customization when it deletes more bespoke code overall
- The first engineering slices are concrete enough to implement without
  reopening architectural intent.
- Project-local memory contains a formal kickoff note that future agents can
  extend without reopening this whole discussion.

## Risks / Failure Modes

- Treating the fork as a file-by-file transplant instead of a composition of
  stronger OSS subsystems.
- Regressing the protected product surfaces by over-optimizing for backend
  swaps.
- Letting one subsystem redesign force accidental API or UI churn across the
  whole repo.
- Duplicating observability, eval truth, run truth, or cost truth across
  multiple systems without clear ownership.
- Re-implementing a second bespoke control plane on top of Flyte, LiteLLM,
  MLflow, or Langfuse.
- Accepting fake parity because screenshots look close while interaction,
  provenance, drilldown, or resumability regress.

## Verification

- Repo verification for this kickoff-plan update:
  - `uv run python scripts/check_docs_ownership.py`
  - `uv run scripts/check_banned.py`
  - `uv run scripts/validate_types.py`
  - `uv run pytest -q`
- Human verification:
  - the locked stack is intact
  - the observability layer is explicit
  - the five workstreams are non-overlapping
  - protected surfaces and first slices are explicit
  - memory discipline is clear enough for future agents to follow

## Rollout / Rollback

- Rollout starts with bounded workstream slices, not a repo-wide rewrite.
- If a chosen subsystem later proves to be the wrong anchor, rollback means
  replacing that subsystem only; the protected product surfaces and workbench
  goals do not change.
- Compatibility adapters are allowed during migration, but they are temporary
  seams, not permanent excuses to keep bespoke subsystems alive.
- "Done" for a replacement slice means the obsolete bespoke path is deleted or
  there is a named blocker preventing deletion.

## Shared Rules For All Kickoff Agents

- Read `/Users/davidmontgomery/ragweld/AGENTS.md` first.
- Read the baseline memory note at
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/oss-first-fork-overhaul-baseline-2026-03-23.md`.
- Read the formal kickoff memory note at
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/oss-composition-fork-formal-kickoff-2026-03-24.md`.
- Keep `Pydantic is the law` and generated frontend types intact while changing
  the systems behind them.
- Prefer deleting hand-rolled platform responsibilities over polishing them.
- Do not hand-edit generated MkDocs output.
- Keep changes small, verifiable, and workstream-scoped.

## Status

- Branch created from `origin/main`
- Kickoff execution artifact formalized
- Memory discipline locked
- Detailed workstream implementation notes pending
