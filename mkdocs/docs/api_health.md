# Health, Readiness, and Metrics API

<div class="grid chunk_summaries" markdown>

-   :material-heart-pulse:{ .lg .middle } **Liveness**

    ---

    `/health` returns process liveness.

-   :material-check-decagram:{ .lg .middle } **Readiness**

    ---

    `/ready` verifies DB connectivity.

-   :material-chart-areaspline:{ .lg .middle } **Metrics**

    ---

    `/metrics` exposes Prometheus metrics.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Gate Traffic"
    Route production traffic only after readiness returns 200.

!!! note "503 still carries the breakdown"
    `/api/ready` answers `200` when every required dependency is ready and **`503`** when one is not — with the same `ReadinessStatus` payload either way, including the per-dependency map (databases, the LiteLLM gateway, index manifests) plus operator hints for anything down. The workbench's top-bar Health pill relies on this: it treats `503` as a status rather than an error and renders the breakdown in its popover, so a not-ready deployment still tells you *which* dependency is the problem. See the [UI tour](manual/ui.md).

!!! note "Exporter"
    A Postgres exporter is included in the compose stack; scrape it alongside `/metrics`.

!!! warning "High-cardinality"
    Avoid per-query labels in custom metrics. Aggregate by corpus or retriever.

=== "Python"
```python
import httpx
print(httpx.get("http://localhost:8000/health").json())
print(httpx.get("http://localhost:8000/ready").json())
print(httpx.get("http://localhost:8000/metrics").text[:200])
```

=== "curl"
```bash
curl -sS http://localhost:8000/health | jq .
curl -sS http://localhost:8000/ready | jq .
curl -sS http://localhost:8000/metrics | head -n 20
```

=== "TypeScript"
```typescript
await fetch('/health')
await fetch('/ready')
const m = await (await fetch('/metrics')).text();
console.log(m.split('\n').slice(0,5))
```

```mermaid
flowchart LR
    Scrape["Prometheus"] --> API_METRICS["/metrics"]
    API_METRICS --> APP["TriBridRAG"]
    APP --> PG["Postgres"]
    APP --> NEO["Neo4j"]
    Scrape --> PExp["postgres-exporter"]
```

??? info "Loki/Grafana"
    Logs and dashboards are available via Loki and Grafana services started by `docker compose`.
