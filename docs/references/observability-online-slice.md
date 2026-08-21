# Observability Online Slice

This reference describes the hard-cut observability slice for live online requests.

## Scope

- Request path: `browser -> FastAPI -> retrieval -> LiteLLM -> vLLM or explicit gateway-owned upstream alias -> response`
- Global API coverage: every `/api/*` response now emits canonical `X-Correlation-ID`, `X-Trace-ID`, and `X-Root-Span-ID` headers through shared middleware
- Canonical signal path: OpenTelemetry
- Workbench-facing LLM trace deep links: Langfuse
- Trace deep links: Tempo
- Collector/agent for local wiring: Grafana Alloy
- Gateway and workflow surfaces now show up in the same operator-facing status deck:
  - `LiteLLM`
  - `vLLM`
  - `Flyte`
  - `MLflow`
  - `Unsloth`
- Expanded stack truth now also covers:
  - `Mimir`
  - `Pyroscope`
  - `Faro`
  - `OpenCost`
  - `Alertmanager`
  - corpus-scoped `Haystack + Docling + Qdrant` retrieval lane health
- Human-facing visual surfaces:
  - Grafana is now a four-surface operator workspace: `Overview`, `Dashboards`, `Incidents`, and `Config`
  - Infrastructure -> Monitoring now carries the same operator deck instead of a narrower readiness card
  - Benchmark is visible in top-level navigation so runtime regressions are not hidden behind a dark route
  - the Grafana overview deck combines observability status, dashboard catalog links, recent incidents, latest trace evidence, Loki status, training control-plane truth, retrieval pilot health, and eval/benchmark/prompt regression summaries for the active corpus
  - the dashboard workspace is now catalog-driven from the backend instead of a frontend-only hardcoded preset list
- Local workbench trace cache stays as a short-term UI bridge for primary live request surfaces, not the long-term source of truth

## Source of truth files

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
- `/Users/davidmontgomery/ragweld/server/observability/status.py`
- `/Users/davidmontgomery/ragweld/server/observability/catalog.py`
- `/Users/davidmontgomery/ragweld/server/observability/incidents.py`
- `/Users/davidmontgomery/ragweld/server/observability/ml_quality.py`
- `/Users/davidmontgomery/ragweld/server/observability/costing.py`
- `/Users/davidmontgomery/ragweld/server/services/traces.py`
- `/Users/davidmontgomery/ragweld/server/api/observability.py`
- `/Users/davidmontgomery/ragweld/server/api/eval.py`
- `/Users/davidmontgomery/ragweld/server/api/benchmark.py`
- `/Users/davidmontgomery/ragweld/server/api/prompts.py`
- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/api/search.py`
- `/Users/davidmontgomery/ragweld/web/src/components/Observability/OperatorDeck.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Observability/IncidentsBoard.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/tabs/GrafanaTab.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Grafana/GrafanaDashboard.tsx`
- `/Users/davidmontgomery/ragweld/web/src/components/Infrastructure/MonitoringSubtab.tsx`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/oncall-overview.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/gateway-serving.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/retrieval-indexing-graph.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/training-workflow.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/eval-benchmark-prompt-regressions.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/cost-capacity.json`
- `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/dashboards/frontend-rum.json`

## Operator-facing APIs

- `GET /api/observability/status`
- `GET /api/observability/catalog`
- `GET /api/observability/incidents`
- `GET /api/eval/observability/summary`
- `GET /api/benchmark/observability/summary`
- `GET /api/prompts/observability/summary`
- `GET /api/traces/latest`
- `GET /api/agent/train/control-plane/status`
- `GET /api/loki/status`
- `GET /api/index/{corpus_id}/pilot/status`
- `X-Correlation-ID`
- `X-Trace-ID`
- `X-Root-Span-ID`

## Readiness semantics

- `GET /api/observability/status` now treats OTLP export as a real target, not just a configured field.
- If OTLP, Alloy, Tempo, Langfuse, Grafana, Mimir, Pyroscope, Faro, OpenCost, Alertmanager, or the configured gateway/training lane is enabled and unreachable, the status response should fail closed with grouped component severity plus an operator hint.
- The same status surface now includes gateway, workflow, and retrieval truth for `LiteLLM`, `vLLM`, `Flyte`, `MLflow`, `Unsloth`, and the active `Haystack + Docling + Qdrant` lane, so the workbench can render a command-center view instead of a backend-only readiness blob.
- The incident feed is intentionally multi-source:
  - infrastructure/component failures
  - retrieval degradation
  - eval regression summaries
  - benchmark regression summaries
  - prompt-regression / pending-verification correlation

## Local dev wiring

- Overlay compose file: `/Users/davidmontgomery/ragweld/infra/docker-compose.observability.yml`
- Alloy config: `/Users/davidmontgomery/ragweld/infra/alloy/config.alloy`
- Tempo config: `/Users/davidmontgomery/ragweld/infra/tempo.yaml`
- Grafana Tempo datasource: `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/datasources/tempo.yml`

Use:

```bash
docker compose -f docker-compose.yml -f infra/docker-compose.observability.yml up -d grafana tempo alloy
```

Suggested local config values:

- `tracing.tracing_mode = "otel_langfuse"` when Langfuse is configured, otherwise `otel` or `local`
- `tracing.otlp_endpoint = "http://localhost:54320/v1/traces"`
- `tracing.alloy_base_url = "http://localhost:52345"`
- `tracing.tempo_base_url = "http://localhost:53200"`
- `ui.grafana_base_url = "http://localhost:3301"`

## Deletion condition for the local trace bridge

The in-memory trace store can be removed once the workbench renders request drilldown exclusively from canonical trace APIs plus Tempo/Langfuse deep links without loss of operator fidelity.

## Host API logs and functional readiness probes (2026-08-21)

- The host FastAPI process now exports its Python/uvicorn logs over OTLP
  (`<otlp_endpoint>` with `/v1/traces` swapped for `/v1/logs`) to Alloy, which
  forwards them to Loki (`otelcol.exporter.loki` -> `loki.write`). Resource
  attributes `service.name`, `ragweld.service=api`, and
  `deployment.runtime=host` become Loki labels via the `loki.resource.labels`
  hint.
- promtail adds `ragweld_service=<compose service>` and
  `deployment_runtime=container` to container logs, so one LogQL selector
  (`{ragweld_service=~"api|postgres|neo4j"}`) covers the host API and the
  containers while `deployment_runtime` keeps them distinguishable. The Chat
  log panel uses that selector.
- Observability status probes now hit functional readiness paths (Tempo
  `/ready`, Alloy `/-/ready`, Grafana `/api/health`, Mimir/Pyroscope `/ready`,
  OpenCost `/healthz`, Alertmanager `/-/ready`, Langfuse
  `/api/public/health`); a 4xx on a base URL no longer counts as healthy. For
  POST-only intake endpoints (OTLP, Faro) a 405/415 to GET is reported as
  "listener present", not as generic health.
