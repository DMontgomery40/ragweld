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
  - corpus-scoped `Haystack + Docling + Qdrant` retrieval lane health (functional Qdrant probe + the active corpus generation)
- Human-facing visual surfaces:
  - Grafana is now a four-surface operator workspace: `Overview`, `Dashboards`, `Incidents`, and `Config`
  - Infrastructure -> Monitoring now carries the same operator deck instead of a narrower readiness card
  - Benchmark is visible in top-level navigation so runtime regressions are not hidden behind a dark route
  - the Grafana overview deck combines observability status, dashboard catalog links, recent incidents, latest trace evidence, Loki status, training control-plane truth, retrieval vector-lane health, and eval/benchmark/prompt regression summaries for the active corpus
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
- Mimir config: `/Users/davidmontgomery/ragweld/infra/mimir.yaml`
- Alert rules: `/Users/davidmontgomery/ragweld/infra/prometheus-rules.yml`
- Alertmanager config: `/Users/davidmontgomery/ragweld/infra/alertmanager.yml`
- Langfuse env: `/Users/davidmontgomery/ragweld/infra/langfuse.env.example`
  (committed dev defaults) + gitignored `infra/langfuse.env` overrides
- Grafana datasources: `/Users/davidmontgomery/ragweld/infra/grafana/provisioning/datasources/`
  (`prometheus`, `loki`, `tempo`, `mimir`, `pyroscope`)

Use `./start.sh --with-observability`, which starts the full fabric:
postgres-exporter, prometheus, grafana, loki, promtail, tempo, alloy, mimir,
pyroscope, alertmanager, and the Langfuse v4 stack (langfuse, langfuse-worker,
langfuse-postgres, langfuse-clickhouse, langfuse-redis, langfuse-minio).

Active local config values (2026-08-24, A3):

- `tracing.tracing_mode = "otel_langfuse"`
- `tracing.otlp_endpoint = "http://127.0.0.1:54320/v1/traces"`
- `tracing.alloy_base_url = "http://127.0.0.1:52345"`
- `tracing.tempo_base_url = "http://127.0.0.1:53200"`
- `tracing.mimir_base_url = "http://127.0.0.1:59009"`
- `tracing.pyroscope_base_url = "http://127.0.0.1:54040"`
- `tracing.faro_base_url = "http://127.0.0.1:52347/collect"`
- `tracing.alertmanager_base_url = "http://127.0.0.1:59093"`
- `tracing.langfuse_enabled = true`, `tracing.langfuse_base_url = "http://127.0.0.1:53000"`
- `tracing.opencost_base_url = ""` (OpenCost needs a Kubernetes API server;
  the Colima profile runs the plain Docker runtime, so it stays disabled)
- `ui.grafana_base_url = "http://127.0.0.1:3301"`

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

## A3 fabric completion (2026-08-24)

The five remaining fabric services are deployed Compose services with
functional readiness, wired data paths, and live-proven flows
(`docs/exec-plans/active/a3-observability-fabric-2026-08-24.md` is the
execution record):

- **Mimir** (`127.0.0.1:59009`, monolithic, filesystem storage): Prometheus
  `remote_write`s every WAL sample to it, so Tempo's span metrics arrive too.
  Grafana has a `Mimir` datasource at `/prometheus`.
- **Pyroscope** (`127.0.0.1:54040`): the host API attaches the `pyroscope-io`
  agent in the lifespan when `tracing.pyroscope_base_url` is set and pushes
  `ragweld-api` CPU profiles. The component status reports the truthful host
  agent state (`server/observability/profiling.py`); test lanes set
  `RAGWELD_DISABLE_PROFILING=1`.
- **Faro**: Alloy `faro.receiver` on `127.0.0.1:52347` (`/collect`, POST-only,
  CORS for the Vite/API origins), labels events
  `service_name=ragweld-web` / `ragweld_service=web` /
  `deployment_runtime=browser`, logs -> Loki, traces -> Tempo. The workbench
  initializes `@grafana/faro-web-sdk` from the loaded config
  (`web/src/observability/faro.ts`, called in `useAppInit`). E2E:
  `web/tests/e2e/observability/faro_rum.spec.ts`
  (`playwright.observability.config.ts`), no interception. The Frontend/RUM
  dashboard reads the real Loki stream. Browser trace instrumentation
  (`@grafana/faro-web-tracing`) is not installed yet — RUM is events/logs.
- **Alertmanager** (`127.0.0.1:59093`): Prometheus evaluates
  `infra/prometheus-rules.yml` (target-down rules + the always-firing
  `RagweldWatchdog` that proves delivery) and routes to it.
- **Langfuse v4** (`127.0.0.1:53000`; worker + dedicated Postgres, ClickHouse
  `25.12`, Redis, MinIO stay VM-internal): fresh v4 install (`events_only`
  mode — read via `GET /api/public/v2/observations`, the legacy
  `/api/public/traces` API is gone). `LANGFUSE_INIT_*` provisions the
  org/project/keys headlessly; the host API's `LANGFUSE_PUBLIC_KEY`/
  `LANGFUSE_SECRET_KEY` live in the root `.env`.
  `record_langfuse_generation` creates a real generation observation
  (`start_as_current_observation(as_type="generation")`) on the shared
  TracerProvider, so it lands on the SAME canonical trace id the API returns
  in `X-Trace-ID`, with input/output/usage and Langfuse-shaped cost details.
  Generation observation names: `chat.generation`, `chat.generation.stream`,
  `reranker.generation`, `benchmark.generation`, `eval.answer.generation`,
  `eval.analysis.generation`, `synthetic.grounded_qa.generation`,
  `synthetic.grounded_qa.judge`. Known upstream gap: Langfuse v4 does not yet
  surface the OTel model attribute as `providedModelName`, so the model also
  rides in observation metadata.
- **OpenCost**: not deployed — it requires a Kubernetes API server and the
  Colima profile runs the plain Docker runtime. It stays `disabled` in the
  status surface (empty base URL); do not report it healthy.
