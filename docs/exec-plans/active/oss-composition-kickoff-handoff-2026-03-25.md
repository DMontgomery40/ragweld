# OSS-Composition Kickoff Handoff (2026-03-25)

## Purpose

This file is the handoff package for the next agent working on
`feat/oss-composition-kickoff`. Treat it as the canonical continuation prompt
for this branch.

## Non-Negotiable Branch Rule

This branch is **replacement-only**.

- No fallbacks
- No legacy compatibility shims
- No transition-period dual paths
- No "keep the old broken thing alive until later"
- No backend-only migration slices without the matching operator-facing UI/docs/tests/instructions

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

## Protected Product Surfaces

- workspace shell and dock/splits experience
- embedded Grafana and operator-console feel
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

- `Docling + Haystack + Qdrant` now exist as a real pilot seam, not just a plan.
- Operators can see and use the pilot from the workbench.
- Legacy retrieval is still dominant outside the pilot, but the new lane is real.

### 3. Observability Online + Cost Slice

Key files:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
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
- `/Users/davidmontgomery/ragweld/web/src/components/RAG/RetrievalSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Admin/IntegrationsSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Admin/SecretsSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Grafana/GrafanaConfig.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Evaluation/TraceViewer.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/tabs/ChatTab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/DevTools/Integrations.tsx`
- `/Users/davidmontgomery/ragweld/infra/docker-compose.observability.yml`
- `/Users/davidmontgomery/ragweld/infra/alloy/config.alloy`
- `/Users/davidmontgomery/ragweld/infra/tempo.yaml`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/datasources/tempo.yml`
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`

State:

- Old LangSmith/LangTrace observability config paths were removed from the live
  operator surfaces and replaced with OTel/Langfuse/Tempo/Alloy/cost fields.
- `/api/observability/status` exists and drives operator-facing readiness.
- `/api/traces/latest` now includes canonical observability metadata:
  `trace_id`, `root_span_id`, `correlation_id`, `route_summary`,
  `external_links`, `cost_summary`.
- Live request instrumentation is wired through chat/search/answer request paths.
- The workbench now shows readiness, trace deep links, and cost visibility.

## What Is Still Legacy And Must Be Replaced Next

### Training Center

Still legacy:

- custom run directories
- custom training orchestration
- MLX-heavy execution path
- no `Flyte + Unsloth + MLflow` truth layer

Required direction:

- keep Training Center as a first-class UI surface
- replace backend truth with `Flyte + Unsloth + MLflow`
- expose workflow/run/artifact status in-product, not only in backend state

### Eval Analysis / Drilldown

Still legacy:

- custom/file-backed eval truth in large parts of the stack
- missing full `Langfuse + MLflow + Ragas + Promptfoo` substrate

Required direction:

- keep ragweld-owned drilldown/comparison UX
- use Langfuse for traces/prompts/spans/per-example inspection
- use MLflow as run/artifact truth
- keep ragweld-specific analysis logic for diffs, regressions, provenance, and synthesis

### Chat Rebuild

Still legacy:

- hand-rolled chat implementation
- not rebuilt on `assistant-ui`

Required direction:

- rebuild chat inside the ragweld shell on `assistant-ui`
- keep ragweld recall/source-grounding/corpus semantics as custom adapters
- do not preserve the old chat implementation out of sentimentality

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

## Exact Prompt For The Next Agent

Use this literally or with minimal adaptation:

> Continue work on `feat/oss-composition-kickoff` as the OSS-composition fork branch for ragweld.
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
> - `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/branch-canon-and-observability-handoff-2026-03-25.md`
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
> 3. observability online + cost slice
>
> Main unfinished defining surfaces:
> 1. Training Center over `Flyte + Unsloth + MLflow`
> 2. Eval drilldown substrate over `Langfuse + MLflow + Ragas + Promptfoo`
> 3. Chat rebuild on `assistant-ui`
>
> Rules for the next move:
> - pick the next major logical slice, not scattered cleanup
> - if you touch backend truth, update the workbench surface in the same branch
> - delete/replace broken legacy behavior in the touched slice instead of preserving it
> - keep updating project-local memory as you go
> - keep README/AGENTS/CLAUDE/branch docs aligned with reality
>
> Verification expectation:
> - run changed-surface tests
> - run docs/types/contract validators
> - run frontend lint/build if frontend changes
> - attempt full `pytest -q` and report remaining failures honestly

## Suggested Next Major Slice

If you want the highest-leverage continuation, do this next:

1. Replace one bounded Training Center lane with `Flyte + MLflow + Unsloth`
2. Keep the existing Training Center UI surface first-class
3. Make workflow state, logs, artifacts, and operator hints visible in-product
4. Do not preserve the old trainer backend once the new lane is wired for that slice
