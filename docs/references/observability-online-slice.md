# Observability Online Slice

This reference describes the hard-cut observability slice for live online requests.

## Scope

- Request path: `browser -> FastAPI -> retrieval -> provider router -> LiteLLM/provider -> response`
- Canonical signal path: OpenTelemetry
- Workbench-facing LLM trace deep links: Langfuse
- Trace deep links: Tempo
- Collector/agent for local wiring: Grafana Alloy
- Local workbench trace cache stays as a short-term UI bridge, not the long-term source of truth

## Source of truth files

- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py`
- `/Users/davidmontgomery/ragweld/server/observability/runtime.py`
- `/Users/davidmontgomery/ragweld/server/observability/status.py`
- `/Users/davidmontgomery/ragweld/server/observability/costing.py`
- `/Users/davidmontgomery/ragweld/server/services/traces.py`
- `/Users/davidmontgomery/ragweld/server/api/observability.py`
- `/Users/davidmontgomery/ragweld/server/api/chat.py`
- `/Users/davidmontgomery/ragweld/server/api/search.py`

## Operator-facing APIs

- `GET /api/observability/status`
- `GET /api/traces/latest`
- `X-Correlation-ID`
- `X-Trace-ID`
- `X-Root-Span-ID`

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
- `tracing.otlp_endpoint = "http://localhost:4320/v1/traces"`
- `tracing.alloy_base_url = "http://localhost:12345"`
- `tracing.tempo_base_url = "http://localhost:3200"`
- `ui.grafana_base_url = "http://localhost:3001"`

## Deletion condition for the local trace bridge

The in-memory trace store can be removed once the workbench renders request drilldown exclusively from canonical trace APIs plus Tempo/Langfuse deep links without loss of operator fidelity.
