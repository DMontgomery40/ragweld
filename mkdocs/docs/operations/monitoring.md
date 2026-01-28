# Monitoring

Monitor TriBridRAG performance and health.

## Metrics

TriBridRAG exposes Prometheus metrics:

```
GET /metrics
```

### Key Metrics

- `tribrid_search_latency_seconds` - Search latency histogram
- `tribrid_search_total` - Total search requests
- `tribrid_rerank_latency_seconds` - Reranking latency
- `tribrid_embedding_latency_seconds` - Embedding generation time

## Grafana Dashboard

A pre-built Grafana dashboard is available:

```json
{
  "ui": {
    "grafana_dashboard_uid": "tribrid-overview",
    "grafana_base_url": "http://127.0.0.1:3000"
  }
}
```

## Logging

Configure log level in config:

```json
{
  "tracing": {
    "log_level": "INFO",
    "tracing_enabled": true
  }
}
```

## Health Checks

```bash
# Quick health check
curl http://localhost:8000/api/health

# Detailed status
curl http://localhost:8000/api/health/detailed
```
