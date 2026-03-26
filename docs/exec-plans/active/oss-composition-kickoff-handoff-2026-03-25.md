# OSS-Composition Kickoff Handoff (2026-03-25)

## Purpose

This file is the handoff package for the next agent working on
`feat/oss-composition-kickoff`. Treat it as the canonical continuation prompt
for this branch.

## Non-Negotiable Branch Rule

This branch is **replacement-only**.

- No fallbacks.
- No legacy compatibility shims.
- No transition-period dual paths.
- No "keep the old broken thing alive until later."
- No backend-only migration slices without the matching operator-facing
  UI/docs/tests/instructions.

If a subsystem is replaced in this branch, the touched surface must move
completely. If the new path is not ready, do not land a fake cutover that still
routes into the old subsystem.

## Locked Stack

- Inference: `vLLM`
- Gateway/routing: `LiteLLM`
- Orchestration: `Flyte`
- Retrieval/indexing: `Haystack + Docling + Qdrant`
- Graph parity: `Neo4j`
- Training execution: `Unsloth`
- Runs/evals/regressions: `MLflow + Ragas + Promptfoo`
- Eval drilldown substrate: `Langfuse`
- Observability fabric:
  - `OpenTelemetry`
  - `Grafana Alloy`
  - `Grafana Tempo`
  - `Grafana Loki`
  - `Grafana Mimir`
  - `Grafana Pyroscope`
  - `Grafana Faro`
- Frontend shell/workbench target:
  - `Dockview`
  - `react-resizable-panels`
  - `TanStack Query`
  - `assistant-ui`
  - `shadcn/ui`
  - `Radix`
  - `xterm`
  - `Monaco`

## Locked Observability Layer

- Canonical signal standard: `OpenTelemetry` for trace context, spans, logs, and
  cross-service correlation.
- Collector/agent: `Grafana Alloy` everywhere.
- Metrics backbone: `Prometheus + Grafana Mimir`.
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

## Protected Product Surfaces

- workspace shell and dock/splits experience
- embedded Grafana access plus ragweld-owned observability surfaces in the
  workbench
- Training Center as a first-class in-product surface
- eval analysis and drilldown as a first-class in-product surface
- graph parity surfaces during the migration

Chat is **not** protected as an implementation. It should be rebuilt on better
OSS foundations inside the ragweld shell.

## What Has Already Been Implemented On This Branch

### 1. Runtime / Gateway Formalization Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/runtime_capabilities.py`
- `/Users/davidmontgomery/ragweld/server/api/runtime_capabilities.py`
- `/Users/davidmontgomery/ragweld/server/chat/provider_router.py`
- `/Users/davidmontgomery/ragweld/server/chat/model_discovery.py`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ProviderSetup.tsx`

State:

- `LiteLLM` and `vLLM` are real runtime vocabulary and config surfaces.
- The workbench exposes runtime/provider truth instead of hiding it.
- Provider/model routing is more formalized than the old ad hoc assumptions.

### 2. Retrieval / Indexing OSS Pilot Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/indexing/oss_retrieval_pilot.py`
- `/Users/davidmontgomery/ragweld/server/api/index.py`
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/IndexingPilotPanel.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalPilotPanel.tsx`

State:

- `Docling + Haystack + Qdrant` now exist as a real bounded retrieval and
  indexing path, not just a plan.
- Operators can see and use that path from the workbench.
- Legacy retrieval is still dominant outside the touched slice, which is why
  retrieval replacement is still in the execution queue.

### 3. Observability Online + Cost Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/main.py`
- `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
- `/Users/davidmontgomery/ragweld/server/observability/status.py`
- `/Users/davidmontgomery/ragweld/server/observability/costing.py`
- `/Users/davidmontgomery/ragweld/server/api/observability.py`
- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/api/search.py`
- `/Users/davidmontgomery/ragweld/server/chat/generation.py`
- `/Users/davidmontgomery/ragweld/server/chat/handler.py`
- `/Users/davidmontgomery/ragweld/server/services/answer_service.py`
- `/Users/davidmontgomery/ragweld/server/services/traces.py`
- `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Grafana/GrafanaConfig.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Evaluation/TraceViewer.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/tabs/ChatTab.tsx`
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`

State:

- Old LangSmith/LangTrace observability config paths were removed from the live
  operator surfaces and replaced with OTel/Langfuse/Tempo/Alloy/cost fields.
- `/api/observability/status` exists and drives operator-facing readiness.
- `/api/traces/latest` includes canonical observability metadata:
  `trace_id`, `root_span_id`, `correlation_id`, `route_summary`,
  `external_links`, and `cost_summary`.
- Canonical observability headers now cover the wider `/api/*` surface, while
  richer request instrumentation already exists on the chat/search/answer paths.
- OTLP readiness is treated as a real reachability target, not just a configured
  field.
- The workbench shows readiness, trace links, route/root-span context, and cost
  visibility.

### 4. Training Control-Plane Truth Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/ControlPlaneStatus.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`
- `/Users/davidmontgomery/ragweld/docs/references/training-control-plane-slice.md`

State:

- Learning Agent Studio now exposes the `Flyte + MLflow + Unsloth` target lane
  in-product.
- `GET /api/agent/train/control-plane/status` reports per-component readiness,
  links, and operator hints.
- Learning Agent run models now have typed fields for workflow backend, tracking
  backend, execution backend, external ids, links, and operator hints.
- Actual launch execution is still on the local MLX lane; this slice makes the
  replacement target explicit without claiming the cutover is done.

### 5. Chat Rebuild UI Cutover Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/chat/handler.py`
- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/ChatInterface.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatTransport.ts`
- `/Users/davidmontgomery/ragweld/web/src/components/Chat/chatSessions.ts`
- `/Users/davidmontgomery/ragweld/docs/references/chat-assistant-ui-slice.md`

State:

- the visible Chat tab is now powered by `assistant-ui` over a ragweld-specific
  external-store runtime
- the existing FastAPI SSE contract stays live for the first slice, and raw SSE
  parsing is isolated in the chat transport adapter
- ragweld citations, recall plan, provider response id, run ids, and
  observability headers now ride as structured assistant message metadata
- chat no longer fabricates retrieval-only answers when no provider is
  available; non-stream chat fails closed and stream chat emits SSE `error`
  events instead
- backend conversation continuity still depends on the in-memory
  `ConversationStore`, and browser-local thread persistence is still a stopgap

## What Is Still Legacy And Must Be Replaced Next

### Observability / Tracing

Still legacy:

- browser and frontend telemetry are not yet first-class through the full
  `Faro + OTel + Grafana` path
- workflow/job traces, metrics, logs, profiles, and cost are not yet unified
  end-to-end across `Flyte + MLflow + Langfuse + Grafana`
- the local workbench trace store still exists as a temporary operator bridge

Required direction:

- every online request must be traceable end to end:
  `browser -> API -> retrieval -> LiteLLM -> vLLM/provider -> response`
- every workflow path must be traceable end to end:
  `UI or schedule -> Flyte workflow -> task logs/metrics -> MLflow artifacts -> Langfuse spans`
- logs, metrics, traces, profiles, and cost must become first-class visibility
  surfaces, not only backend plumbing
- local-only trace bridges should be deleted once canonical APIs and linked
  backends cover the same operator use case

### Training Center

Still legacy:

- custom run directories
- custom training orchestration
- MLX-heavy execution path
- no real `Flyte + Unsloth + MLflow` launch/status/artifact truth yet

Required direction:

- keep Training Center as a first-class UI surface
- replace backend truth with `Flyte + Unsloth + MLflow`
- expose workflow state, logs, links, artifacts, and operator hints in-product
- delete the touched local MLX-backed lane instead of preserving it as fallback

### Eval Analysis / Drilldown

Still legacy:

- custom/file-backed eval truth in large parts of the stack
- missing full `Langfuse + MLflow + Ragas + Promptfoo` substrate

Required direction:

- keep ragweld-owned drilldown/comparison UX
- use Langfuse for traces/prompts/spans/per-example inspection
- use MLflow as run/artifact truth
- keep ragweld-specific analysis logic for diffs, regressions, provenance, and
  synthesis
- do not ship backend substrate work without the matching drilldown UI surface

### Chat Storage / Persistence Follow-On

Still legacy:

- the in-memory `ConversationStore` is still the backend continuity truth
- browser-local thread persistence is still a stopgap
- there is still no canonical backend thread list/history truth for the
  rebuilt `assistant-ui` shell

Required direction:

- replace chat persistence/backend truth coherently without routing back into
  the old UI or fallback behavior
- keep ragweld recall/source-grounding/corpus semantics as first-class
  assistant-ui metadata and companion controls
- preserve streaming, citations, provider response id continuity, and
  observability headers while deleting the temporary storage seams

### Retrieval / Indexing

Still legacy:

- the `Docling + Haystack + Qdrant` lane is still described as a pilot outside
  the touched slice
- legacy retrieval remains dominant outside that path

Required direction:

- promote `Docling + Haystack + Qdrant` to branch truth where a retrieval or
  indexing slice is touched
- keep provenance and Neo4j graph parity explicit in the same slice

## Locked Execution Queue

As of 2026-03-25, the user explicitly reordered the queue so the chat rebuild
goes first.

1. Rebuild chat inside the shell on `assistant-ui`.
2. Finish the observability workstream as a full-stack replacement layer.
3. Replace one bounded Training Center lane with
   `Flyte + Unsloth + MLflow`.
4. Replace the eval analysis and drilldown substrate with
   `Langfuse + MLflow + Ragas + Promptfoo`.
5. Promote retrieval/indexing from pilot to replacement truth where touched.

## Dedicated Agent Handoffs

These are intended to be cold-start handoff packages. They duplicate critical
branch context on purpose so delegated agents do not need prior thread history.

- Chat rebuild with memory and recall preservation:
  `/Users/davidmontgomery/ragweld/docs/exec-plans/active/chat-rebuild-memory-recall-agent-handoff-2026-03-25.md`
- Enterprise observability replacement:
  `/Users/davidmontgomery/ragweld/docs/exec-plans/active/enterprise-observability-agent-handoff-2026-03-25.md`

## Verification State

Green targeted verification already run on this branch:

- `uv run pytest -q tests/api/test_observability_endpoints.py tests/api/test_secrets_endpoints.py::test_secrets_check_reflects_process_env tests/api/test_config_endpoints.py::test_put_config_persists_hard_cut_observability_fields tests/unit/test_trace_store.py`
- targeted chat/stream regression tests after the observability slice
- `uv run python scripts/check_docs_ownership.py`
- `uv run scripts/check_banned.py`
- `uv run scripts/validate_types.py`
- `uv run scripts/export_contract_bundle.py`
- `uv run scripts/validate_contract_bundle.py`
- `npm --prefix web run lint`
- `npm --prefix web run build`

Full repo verification was also run:

- `uv run pytest -q`

Current remaining full-suite failures are outside the observability slice and
currently cluster in:

- Postgres-dependent corpus/config tests expecting a local DB on `localhost:5432`
- eval comparison routing/error tests
- feedback/health corpus-scope tests
- lineage/promotion flows
- prompts reset
- feedback-mining linkage flows

Do **not** treat those remaining failures as permission to reintroduce
fallbacks in the fork slices that are already moving.

Additional GraphRAG guardrail:

- The checked-in `tribrid_config.json` graph defaults must stay aligned with
  `server/models/tribrid_config_model.py` for this branch.
- Official Neo4j GraphRAG schema guidance must be config-driven, not
  hardcoded to concept-only or to a baked-in relation/entity subset.
- If `semantic_kg_allowed_entity_types` or relation-type controls drift from
  the Pydantic truth, fix the config/template/tests together before trusting
  the corpus run.

## Exact Prompt For The Next Agent

Use this literally or with minimal adaptation:

> Continue work on `feat/oss-composition-kickoff` as the OSS-composition fork
> branch for ragweld.
>
> Branch canon:
> - replacement-only
> - no fallbacks
> - no legacy compatibility shims
> - no transition-period dual paths
> - no backend-only migration slices without matching UI/docs/tests/instructions
>
> Read first:
> - `/Users/davidmontgomery/ragweld/AGENTS.md`
> - `/Users/davidmontgomery/ragweld/CLAUDE.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-fork-kickoff.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
> - `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/fork-v3-charter-formalization-2026-03-25.md`
>
> Locked stack:
> - `vLLM`
> - `LiteLLM`
> - `Flyte`
> - `Haystack + Docling + Qdrant`
> - `Neo4j`
> - `Unsloth`
> - `MLflow + Ragas + Promptfoo`
> - `Langfuse`
> - `OpenTelemetry + Grafana Alloy + Tempo + Loki + Mimir + Pyroscope + Faro`
> - `Dockview + react-resizable-panels + TanStack Query + assistant-ui + shadcn/ui + Radix + xterm + Monaco`
>
> Current completed slices:
> 1. runtime/gateway formalization
> 2. retrieval/indexing OSS pilot
> 3. observability online + cost
> 4. training control-plane truth
> 5. chat rebuild UI cutover on `assistant-ui`
>
> Locked execution queue:
> 1. rebuild chat on `assistant-ui`
> 2. finish observability as a full-stack replacement layer
> 3. replace one bounded Training Center lane with `Flyte + Unsloth + MLflow`
> 4. replace eval drilldown substrate with `Langfuse + MLflow + Ragas + Promptfoo`
> 5. promote retrieval/indexing from pilot to replacement truth where touched
>
> Rules for the next move:
> - pick the next major logical slice, not scattered cleanup
> - if you touch backend truth, update the workbench surface in the same branch
> - delete or replace broken legacy behavior in the touched slice instead of preserving it
> - keep project-local memory updated in the same turn
> - keep README/AGENTS/CLAUDE/branch docs aligned with reality
>
> Verification expectation:
> - run changed-surface tests
> - run docs/types/contract validators
> - run frontend lint/build if frontend changes
> - attempt full `pytest -q` and report remaining failures honestly
