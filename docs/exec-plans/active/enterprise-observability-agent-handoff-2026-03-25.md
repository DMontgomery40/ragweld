# Enterprise Observability Agent Handoff (2026-03-25)

## Purpose

This file is the dedicated handoff package for the agent finishing the
observability workstream on `feat/oss-composition-kickoff`.

The mission is **full MLOps-grade enterprise observability** across online
requests, workflows, training, evals, logs, metrics, traces, profiles, browser
telemetry, and cost while keeping the operator-facing ragweld workbench
first-class.

This handoff is meant to be **cold-start safe**. Assume the implementing agent
has no useful thread context beyond the files explicitly referenced here.

## Branch Canon

This branch is **replacement-only**.

- No fallbacks.
- No local-only observability bridges promoted as branch truth.
- No backend-only migration slice without the matching operator-facing UI, docs,
  tests, and instructions.
- No "instrument some spans now and wire the operator surfaces later."

If a touched observability slice is not ready on the new path, do not preserve
the old custom bridge as the real answer.

## Read First

- `/Users/davidmontgomery/ragweld/AGENTS.md`
- `/Users/davidmontgomery/ragweld/CLAUDE.md`
- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
- `/Users/davidmontgomery/ragweld/docs/references/training-control-plane-slice.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/observability-middleware-and-readiness-hardening-2026-03-25.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/training-control-plane-slice-2026-03-25.md`

## Locked Observability Layer

- Canonical signal standard: `OpenTelemetry`
- Collector/agent: `Grafana Alloy`
- Metrics backbone: `Prometheus + Mimir`
- Traces backbone: `Tempo`
- Logs backbone: `Loki`
- Continuous profiling: `Pyroscope`
- Frontend/browser telemetry: `Faro`
- LLM-native tracing and prompt observability: `Langfuse`
- Cost layer:
  - `LiteLLM` for gateway budgets and provider/model accounting
  - `Langfuse` for per-trace and per-generation cost attribution
  - `OpenCost` for infra and GPU cost allocation
- Workflow/run truth stays:
  - `Flyte` for workflow state and execution lineage
  - `MLflow` for run, artifact, model, and eval truth

## Cold-Start Branch Context

These slices are already real on this branch and should be treated as existing
foundation:

- runtime/gateway formalization over `LiteLLM + vLLM`
- retrieval/indexing pilot over `Docling + Haystack + Qdrant`
- online observability and cost slice over `OTel + Alloy + Tempo + Langfuse`
- Training Center control-plane truth exposing `Flyte + MLflow + Unsloth`
  readiness, links, and operator hints

What is still incomplete is **enterprise observability depth and end-to-end
workflow coverage**, not whether observability matters. The next agent should
finish the replacement layer, not restart the architecture debate.

## Current Reality

Primary backend surfaces:

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/main.py`
- `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
- `/Users/davidmontgomery/ragweld/server/observability/status.py`
- `/Users/davidmontgomery/ragweld/server/observability/costing.py`
- `/Users/davidmontgomery/ragweld/server/observability/metrics.py`
- `/Users/davidmontgomery/ragweld/server/api/observability.py`
- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/api/search.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
- `/Users/davidmontgomery/ragweld/server/services/traces.py`

Primary frontend/operator surfaces:

- `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Grafana/GrafanaConfig.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Evaluation/TraceViewer.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`

Already real on this branch:

- canonical correlation and trace headers across the wider `/api/*` surface
- OTel-first request instrumentation on core online paths
- `/api/observability/status` as operator-facing readiness truth
- Prometheus metrics exposure
- basic request cost visibility
- in-product readiness and trace-link surfaces

Still legacy or incomplete:

- browser telemetry is not yet real through `Faro`
- workflow/job observability is not yet unified end to end across
  `Flyte + MLflow + Langfuse + Grafana`
- `Loki`, `Mimir`, `Pyroscope`, and `OpenCost` are not yet canonical operator
  truth in-product
- the workbench still depends on the local trace bridge in
  `/Users/davidmontgomery/ragweld/server/services/traces.py`
- cost is not yet unified across `LiteLLM + Langfuse + OpenCost`

## Read In This Order

If you are starting cold, read these in sequence before editing:

1. `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
2. `/Users/davidmontgomery/ragweld/server/main.py`
3. `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
4. `/Users/davidmontgomery/ragweld/server/observability/status.py`
5. `/Users/davidmontgomery/ragweld/server/observability/costing.py`
6. `/Users/davidmontgomery/ragweld/server/api/observability.py`
7. `/Users/davidmontgomery/ragweld/server/api/agent.py`
8. `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
9. `/Users/davidmontgomery/ragweld/server/services/traces.py`
10. `/Users/davidmontgomery/ragweld/infra/docker-compose.observability.yml`
11. `/Users/davidmontgomery/ragweld/infra/alloy/config.alloy`
12. `/Users/davidmontgomery/ragweld/infra/tempo.yaml`
13. `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
14. `/Users/davidmontgomery/ragweld/web/src/components/Evaluation/TraceViewer.tsx`
15. `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
16. `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`
17. `/Users/davidmontgomery/ragweld/tests/api/test_observability_endpoints.py`
18. `/Users/davidmontgomery/ragweld/tests/unit/test_agent_training_control_plane.py`
19. `/Users/davidmontgomery/ragweld/tests/api/test_agent_training_control_plane_endpoints.py`

## Recommended Next Execution Slice

Make the next real cutover a **bounded Training Center workflow observability
replacement**:

`Learning Agent Studio -> Flyte execution -> task logs/metrics/profile ->
MLflow run/artifacts -> Langfuse spans -> Grafana/Loki/Mimir/Pyroscope/OpenCost`

Anchor that slice in:

- `/Users/davidmontgomery/ragweld/server/training/control_plane.py`
- `/Users/davidmontgomery/ragweld/server/api/agent.py`
- `/Users/davidmontgomery/ragweld/server/api/observability.py`
- `/Users/davidmontgomery/ragweld/server/observability/status.py`
- `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/TrainingStudio.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/AgentTraining/RunOverview.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Evaluation/TraceViewer.tsx`

Do not ship that slice against the legacy MLX/file-backed run truth. The
observability replacement has to move with the real Flyte/MLflow/Unsloth lane
for the touched Training Center slice.

## Do Not Regress

- Do not stop at request-only tracing and call that enterprise observability.
- Do not wire new operator UI to local-only bridges when canonical backends
  should own the truth.
- Do not treat Grafana embeds alone as sufficient; the workbench must expose
  logs, metrics, traces, profiles, cost, links, and operator hints together.
- Do not make Training Center observability depend on the legacy MLX/file-backed
  trainer lane.
- Do not duplicate Flyte or MLflow truth in bespoke ragweld registries once the
  touched slice moves.

## End-To-End Expectations

Every online request should be traceable end to end:

`browser -> API -> retrieval -> LiteLLM -> vLLM/provider -> response`

Every workflow path should be traceable end to end:

`UI or schedule -> Flyte workflow -> task logs/metrics -> MLflow artifacts ->
Langfuse spans`

Every touched operator surface should show first-class access to:

- traces
- logs
- metrics
- profiles
- cost
- external deep links
- operator hints when a dependency is misconfigured or unreachable

## Legacy Targets To Remove When The Replacement Covers Them

- `/Users/davidmontgomery/ragweld/server/services/traces.py`
- UI dependence on `/api/traces/latest` as the primary trace drilldown substrate
- local-only observability bridges presented as enterprise truth

Treat catalog-only request cost as a bridge, not the end state. Touched slices
should move toward the locked `LiteLLM + Langfuse + OpenCost` truth.

## First-Slice Definition Of Done

For the first real workflow observability cutover, "done" means all of the
following are true for one bounded Training Center lane:

- the run surface shows a real Flyte execution id/state
- the run surface shows a real MLflow run id and artifact linkage
- the run surface exposes Langfuse and Grafana deep links
- the operator can reach logs, metrics, traces, profiles, and cost from the
  workbench for that run family
- `/api/observability/status` reports readiness for the touched observability
  dependencies and fails closed when enabled services are unreachable
- the touched drilldown flow no longer depends on the local trace bridge as the
  canonical answer

## Acceptance Criteria

- `/api/observability/status` covers the locked components for the touched slice
  and fails closed when enabled targets are unreachable
- at least one online path is traceable end to end
- at least one workflow path is traceable end to end
- the workbench exposes logs, metrics, traces, profile, and cost links as
  first-class operator surfaces
- the touched slice does not route back through the local trace bridge as the
  canonical answer

## Verification Expectations

- run changed-surface backend tests
- run changed-surface frontend tests if UI is touched
- run docs/types/contract validators
- run frontend lint/build when frontend code changes
- attempt full `pytest -q` and report remaining failures honestly

## Tests To Extend

- `/Users/davidmontgomery/ragweld/tests/api/test_observability_endpoints.py`
- `/Users/davidmontgomery/ragweld/tests/unit/test_agent_training_control_plane.py`
- `/Users/davidmontgomery/ragweld/tests/api/test_agent_training_control_plane_endpoints.py`
- any changed-surface Training Center UI tests that validate in-product
  observability links and operator hints

## Docs And Memory Obligations

Update in the same turn when the slice moves:

- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
  or its direct successor
- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
- `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
- a same-day memory note under
  `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/`

## Exact Prompt For The Observability Agent

> Continue work on `feat/oss-composition-kickoff` by finishing the
> observability workstream as a real enterprise-grade replacement layer across
> online requests and workflow/training paths.
>
> Branch canon:
> - replacement-only
> - no fallbacks
> - no local-only observability bridge kept as branch truth
> - no backend-only migration slice without matching UI/docs/tests/instructions
>
> Read first:
> - `/Users/davidmontgomery/ragweld/AGENTS.md`
> - `/Users/davidmontgomery/ragweld/CLAUDE.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
> - `/Users/davidmontgomery/ragweld/docs/exec-plans/active/enterprise-observability-agent-handoff-2026-03-25.md`
> - `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
> - `/Users/davidmontgomery/ragweld/docs/references/training-control-plane-slice.md`
> - `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
>
> Locked layer:
> - `OpenTelemetry`
> - `Grafana Alloy`
> - `Tempo`
> - `Loki`
> - `Mimir`
> - `Pyroscope`
> - `Faro`
> - `Langfuse`
> - `LiteLLM`
> - `OpenCost`
> - `Flyte`
> - `MLflow`
>
> Read the implementation in this order before editing:
> - `server/models/tribrid_config_model.py`
> - `server/main.py`
> - `server/observability/runtime.py`
> - `server/observability/status.py`
> - `server/observability/costing.py`
> - `server/api/observability.py`
> - `server/api/agent.py`
> - `server/training/control_plane.py`
> - `server/services/traces.py`
> - `infra/docker-compose.observability.yml`
> - `infra/alloy/config.alloy`
> - `infra/tempo.yaml`
> - `web/src/components/Infrastructure/MonitoringSubtab.tsx`
> - `web/src/components/Evaluation/TraceViewer.tsx`
> - `web/src/components/AgentTraining/TrainingStudio.tsx`
> - `web/src/components/AgentTraining/RunOverview.tsx`
> - `tests/api/test_observability_endpoints.py`
> - `tests/unit/test_agent_training_control_plane.py`
> - `tests/api/test_agent_training_control_plane_endpoints.py`
>
> Forbidden regressions:
> - no request-only slice masquerading as enterprise observability
> - no operator dependence on local-only trace bridges where canonical services
>   should be the truth
> - no Training Center observability built on the legacy MLX/file-backed lane
> - no bespoke duplicate run registries for data already owned by Flyte/MLflow
>
> Preferred next slice:
> - replace one bounded Training Center workflow observability lane end to end
> - expose logs, metrics, traces, profiles, cost, and deep links in-product
> - delete or bypass the local trace bridge once the new surface covers the same
>   operator workflow
>
> Verification expectation:
> - run changed-surface tests
> - run docs/types validators
> - run frontend lint/build if frontend changes
> - attempt full `pytest -q` and report remaining failures honestly
