# OSS-Composition Fork Kickoff

Date: 2026-03-24
Branch: `feat/oss-composition-kickoff`
Status: active execution program, v3 formalized on 2026-03-25

## Goal

Formalize and start the ragweld OSS-composition fork as a real execution
program.

The fork preserves ragweld's overall MLOps and workbench character while
aggressively replacing bespoke platform code with established OSS components,
frameworks, protocols, and products. Custom code survives only where it is
genuinely product-defining: provenance stitching, corpus identity, config
translation, workbench composition, eval analysis, drilldown synthesis, and the
ragweld-owned operator workflow across those systems.

## Branch Canon

This branch is **replacement-only**.

- No fallbacks.
- No legacy compatibility shims.
- No transition-period dual paths.
- No backend-only migration slices without matching UI, docs, tests, and agent
  instructions.
- If a replacement slice is touched, the touched legacy path must be deleted in
  the same slice or blocked by a named blocker that prevents deletion.
- If the new path is not ready, fix the new path instead of routing back into
  the old subsystem.
- If older docs, memories, prompts, or rules conflict with this document or
  `AGENTS.md`, the branch canon wins.

## Protected Product Surfaces

These surfaces are protected at the product level even if their implementation
changes completely:

- Workbench shell and dock/splits experience.
- Embedded Grafana access plus ragweld-owned observability surfaces inside the
  workbench.
- Training Center as a first-class in-product surface.
- Eval analysis and drilldown as a first-class in-product surface.
- Graph parity surfaces during migration.

Grafana itself is not a ragweld implementation surface. What stays protected is
the embedded access, drilldown, and operator workflow around it inside the
ragweld workbench.

Chat is explicitly **not** protected as an implementation. It should be rebuilt
inside the ragweld shell on `assistant-ui`, not preserved for continuity.

## Locked Stack

- Inference: `vLLM` for self-hosted serving.
- Gateway/routing: `LiteLLM` as the unified proxy/router over `vLLM`, hosted
  providers, and any remaining external backends.
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

- Canonical signal standard: `OpenTelemetry` for trace context, spans, logs,
  and cross-service correlation.
- Collector and agent: `Grafana Alloy` everywhere.
- Metrics backbone: `Prometheus` for scrape compatibility plus `Grafana Mimir`
  for long-retention multi-tenant metrics.
- Traces backbone: `Grafana Tempo`.
- Logs backbone: `Grafana Loki`.
- Continuous profiling: `Grafana Pyroscope`.
- Frontend and browser telemetry: `Grafana Faro`.
- LLM-native tracing and prompt observability: `Langfuse-first`.
- Cost layer:
  - `LiteLLM` for gateway budgets, spend, and model/provider accounting.
  - `Langfuse` for per-trace and per-generation cost attribution.
  - `OpenCost` for infra and cluster/GPU cost allocation.
- Workflow and run truth stays:
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

- `vLLM` fits because it exposes Prometheus-style `/metrics` on its
  OpenAI-compatible server.
- `LiteLLM` fits because it gives ragweld a single routing, budget, spend, and
  Langfuse integration layer over self-hosted and hosted providers.
- `Langfuse` stays the LLM-native trace substrate rather than a replacement for
  MLflow or Flyte truth.
- `Flyte` remains the orchestration backbone, but its logs, metrics, traces, and
  execution identifiers must flow into the same Grafana and OTel fabric instead
  of becoming an island.
- `MLflow` remains the run and artifact system of record and should be linked
  from traces, dashboards, and drilldowns rather than duplicated.

## Current Baseline On This Branch

The branch already has four real baseline slices. They are not reopened by this
charter rewrite; they are the starting truth for the next slices.

### 1. Runtime / Gateway Formalization

- `LiteLLM` and `vLLM` are already real runtime vocabulary and config surfaces.
- Provider and model routing is more formalized than the old ad hoc runtime path.
- The workbench already exposes runtime/provider truth instead of hiding it.

### 2. Retrieval / Indexing OSS Pilot

- `Docling + Haystack + Qdrant` already exist as a real bounded retrieval and
  indexing path on this branch.
- Operators can already see and use that path from the workbench.
- Legacy retrieval still dominates outside the touched slice, which is why this
  remains a branch baseline rather than full retrieval replacement truth.

### 3. Observability Online + Cost

- Old LangSmith/LangTrace operator-facing config paths were removed from live
  surfaces and replaced with OTel, Langfuse, Tempo, Alloy, and cost fields.
- `/api/observability/status` exists and drives operator-facing readiness.
- `/api/traces/latest` already includes canonical observability metadata:
  `trace_id`, `root_span_id`, `correlation_id`, `route_summary`,
  `external_links`, and `cost_summary`.
- Canonical observability headers now cover the broader `/api/*` surface, while
  richer request instrumentation already exists on the chat, search, and answer
  paths.
- The workbench already shows readiness, trace links, route context, and cost
  visibility in-product.

### 4. Training Control-Plane Truth

- Learning Agent Studio already exposes the `Flyte + MLflow + Unsloth` target
  lane in-product.
- `GET /api/agent/train/control-plane/status` reports readiness, links, and
  operator hints.
- Learning Agent run models already have typed fields for workflow backend,
  tracking backend, execution backend, external ids, links, and operator hints.
- Actual launch execution is still on the local MLX lane, which is why this is
  a truthful control-plane slice rather than a completed Training Center
  replacement.

## Ragweld-Owned Logic That Survives The Fork

Upstream tools provide raw materials. Ragweld still owns:

- run-vs-run comparison
- changed config, prompt, model, dataset, and retriever analysis
- regressed vs improved example surfacing
- source-aware and provenance-aware explanation
- AI-written comparison synthesis grounded in real artifacts and traces
- the ragweld-owned observability workflow inside the workbench
- the combined operator view that ties together cost, quality, provenance, and
  trace evidence instead of splitting them across multiple products

## Public Contract Policy

- `FastAPI + Pydantic` remain the public contract boundary.
- No promise is made to preserve current internal backend architecture.
- No promise is made to preserve the current chat contract if it conflicts with
  the rebuild.
- No branch doc should imply fallback routing, compatibility shims, dual-write
  behavior, or old/new coexistence on this branch.
- Observability policy is contract-level intent: every online request and every
  workflow path must be traceable end to end with canonical correlation, trace
  context, links, and cost surfaced in-product.
- Keep MCP on the official Python SDK and limit custom MCP logic to
  ragweld-specific tools and policies.

## Replacement Means Removal

- When an OSS subsystem wins, the goal is to delete the bespoke subsystem it
  replaces rather than keep both forever.
- Do not accept "wrapped legacy forever" as success.
- Do not introduce compatibility adapters, migration seams, bridge layers, or
  continuity-preserving coexistence logic on this branch.
- Every replacement slice must define:
  - the old code path being retired
  - the new code path becoming truth
  - the parity gate required before deletion
  - the cleanup step that deletes the obsolete path
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

## Workstreams

### 1. Runtime, gateway, observability, and cost

- Owns the `LiteLLM -> vLLM` path, provider compatibility, online request
  telemetry, workflow/job observability, cost instrumentation, and cross-service
  tracing.
- Exit criteria:
  - online request path is traceable end to end
  - workflow and job paths are traceable end to end
  - logs, metrics, traces, profiles, and cost are diagnosable from the
    workbench
  - remaining local-only observability bridges have named deletion conditions

### 2. Training, evals, drilldown, and lineage

- Owns Training Center replacement, workflow lineage, run truth, eval
  orchestration, and ragweld-specific comparison logic.
- Exit criteria:
  - one bounded Learning Agent lane launches through `Flyte + Unsloth + MLflow`
  - run statuses, logs, links, and artifacts land in real backend truth
  - drilldown can explain regressions and improvements per example

### 3. Retrieval, indexing, and graph parity

- Owns ingestion, chunking, retrieval orchestration, provenance contracts, and
  v1 graph parity.
- Exit criteria:
  - indexed corpora preserve source file and line fidelity
  - graph views do not disappear during migration
  - retrieval quality and provenance remain measurable
  - touched slices promote `Docling + Haystack + Qdrant` from pilot to branch
    truth

### 4. Frontend shell, chat, and workbench migration

- Owns dock layout, shell composition, embedded observability, operator
  utilities, and the in-shell chat rebuild.
- Exit criteria:
  - shell parity is visually and interactively credible
  - chat passes its fresh acceptance contract
  - protected surfaces still feel first-class inside the workbench

### 5. Contracts, docs, and program sequencing

- Owns Pydantic contract decomposition, generated clients and types,
  deterministic docs, and execution-program sequencing.
- Exit criteria:
  - no hand-written frontend API payload types are reintroduced
  - contract generation stays mechanical
  - canonical program docs and project-local memory remain aligned

## Locked Execution Queue

As of 2026-03-25, the user explicitly reordered the queue so the chat rebuild
goes first.

1. Rebuild chat inside the shell on `assistant-ui`.
   - Preserve ragweld semantics for recall, sources, streaming, retries,
     citations, and session continuity.
   - Do not preserve the current hand-rolled chat implementation out of
     continuity concerns.

2. Finish the observability workstream as a full-stack replacement layer, not
   just online request tracing.
   - Lock end-to-end online request tracing:
     `browser -> API -> retrieval -> LiteLLM -> vLLM/provider -> response`.
   - Lock end-to-end workflow path tracing:
     `UI or schedule -> Flyte workflow -> task logs/metrics -> MLflow artifacts -> Langfuse spans`.
   - Treat remaining local-only trace buffers or ad hoc observability stores as
     temporary surfaces with explicit deletion conditions.

3. Make Training Center the next primary backend replacement target after
   observability.
   - Replace one bounded Learning Agent lane with real
     `Flyte + Unsloth + MLflow` launch, status, logs, links, and artifacts.
   - Keep the in-product Training Center surface first-class in the same slice.
   - Delete the touched local MLX-backed lane instead of keeping it as a
     fallback.

4. Make eval analysis and drilldown the next substrate replacement after that
   lane is real.
   - Use `Langfuse` for traces, prompts, spans, and per-example inspection.
   - Use `MLflow` as run and artifact truth.
   - Keep ragweld-owned comparison, provenance analysis, regressions, and
     synthesis in the workbench.

5. Move retrieval and indexing from pilot to replacement path.
   - Promote `Docling + Haystack + Qdrant` from pilot seam to real backend truth
     when a retrieval or indexing slice is touched.
     - Keep provenance and Neo4j graph parity explicit in the same slice.

## Delivery Phases

### Phase 0. Program setup

- Lock architecture, protected surfaces, observability layer, branch canon, and
  memory rules.
- Done when:
  - this kickoff plan is the canonical execution artifact
  - the branch handoff mirrors this kickoff plan
  - project-local memory is indexed and current

### Phase 1. Bounded replacement slices

- Deliver one real replacement slice at a time, not broad repo churn.
- Done when:
  - each touched slice moves backend, UI, docs, tests, and instructions together
  - each touched slice deletes the obsolete path or records a named blocker
  - no touched slice routes back into legacy behavior

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

## Test And Acceptance

### Program-formalization acceptance

- The kickoff doc is the single canonical repo artifact for the fork.
- The handoff doc matches the kickoff doc.
- Project-local memory contains an indexed v3 formalization note.
- No canonical branch doc instructs fallbacks, compatibility adapters, migration
  seams, or old/new coexistence on this branch.

### Replacement-slice acceptance

- Backend, UI, docs, tests, and instructions move together.
- No touched slice routes back into legacy behavior.
- Protected surfaces remain present and understandable in-product.
- The obsolete bespoke path is deleted or blocked by a named blocker.

### Test plan

- Require screenshot and interaction parity for the workbench shell, dock
  behavior, embedded Grafana access, Training Center, graph view, and eval
  drilldown.
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
  - add or update a project-local memory note and keep `MEMORY.md` indexed
- New memory notes for this program should stay short and use the durable
  structure:
  - `Context`
  - `Decision`
  - `Evidence`
  - `Next`
- If a change alters the locked stack, protected surfaces, observability layer,
  or execution queue, update this kickoff doc in the same turn instead of
  letting memory drift away from the repo artifact.

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

- Repo verification for this charter update:
  - `uv run python scripts/check_docs_ownership.py`
  - `uv run scripts/check_banned.py`
  - `uv run scripts/validate_types.py`
  - `uv run pytest -q`
- Frontend verification only if frontend code changes:
  - `npm --prefix web run lint`
  - `npm --prefix web run build`
- Human verification:
  - the locked stack is intact
  - the observability layer is explicit
  - the execution queue is explicit
  - protected surfaces are explicit
  - memory discipline is clear enough for future agents to follow

## Rollout / Rollback

- Rollout starts with bounded replacement slices, not a repo-wide rewrite.
- If a chosen subsystem later proves to be the wrong anchor, rollback means
  replacing that subsystem only; the protected product surfaces and workbench
  goals do not change.
- Rollback does not mean reviving fallbacks or dual paths on this branch.
- "Done" for a replacement slice means the obsolete bespoke path is deleted or
  there is a named blocker preventing deletion.

## Shared Rules For All Kickoff Agents

- Read `/Users/davidmontgomery/ragweld/AGENTS.md` first.
- Read the baseline memory note at
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/oss-first-fork-overhaul-baseline-2026-03-23.md`.
- Read the formal kickoff memory note at
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/oss-composition-fork-formal-kickoff-2026-03-24.md`.
- Read the v3 charter formalization memory note once it exists.
- Keep `Pydantic is the law` and generated frontend types intact while changing
  the systems behind them.
- Prefer deleting hand-rolled platform responsibilities over polishing them.
- Do not hand-edit generated MkDocs output.
- Keep changes small, verifiable, and workstream-scoped.

## Status

- Branch created from `origin/main`
- Kickoff execution artifact formalized
- V3 charter rewrite aligned to replacement-only canon
- Detailed workstream implementation notes active in project-local memory
