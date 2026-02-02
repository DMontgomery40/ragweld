# API Reference

<div class="grid chunk_summaries" markdown>

-   :material-api:{ .lg .middle } **FastAPI Endpoints**

    ---

    Endpoints for config, indexing, retrieval, graph, models, keywords, reranker, and health.

-   :material-file-code:{ .lg .middle } **Schema by Pydantic**

    ---

    Request/response models are defined in Pydantic. The frontend imports generated TypeScript types.

-   :material-shield-key:{ .lg .middle } **Secrets Check**

    ---

    Validate configured API keys and DB connections via `/secrets/check`.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Inspect Schemas"
    Prefer calling `/config` first to align UI interactions with actual server capabilities. All shapes are Pydantic-driven.

!!! note "HTTP Conventions"
    - JSON requests/responses
    - Errors via standard status codes with `detail`
    - Streaming responses for long operations are `text/event-stream` or chunked JSON

!!! warning "Model Usage Costs"
    Reranking and keyword generation may incur API costs depending on selected models. Control via `data/models.json` and `TriBridConfig`.

## Endpoint Inventory

| Area | Route | Method | Purpose |
|------|-------|--------|---------|
| Config | `/config` | GET | Get full config |
| Config | `/config/reset` | POST | Reset to defaults |
| Config | `/config/{section}` | PATCH | Sectional patch, e.g., `fusion` |
| Secrets | `/secrets/check` | GET | Check provider keys + DB connections |
| Index | `/index` | POST | Start indexing |
| Index | `/index/status` | GET | Status for a corpus |
| Index | `/index/stats` | GET | Storage stats summary |
| Search | `/search` | POST | Tri-brid retrieval + fusion (+reranker) |
| Answer | `/answer` | POST | Retrieval + LLM answer generation |
| Graph | `/graph/{corpus_id}/entities` | GET | List entities |
| Graph | `/graph/{corpus_id}/entity/{id}` | GET | Entity details |
| Graph | `/graph/{corpus_id}/entity/{id}/neighbors` | GET | Neighborhood |
| Models | `/models/by-type/{component}` | GET | Models by component `GEN/EMB/RERANK` |
| Keywords | `/keywords/generate` | POST | Generate discriminative keywords |
| Reranker | `/reranker/*` | mixed | Status / mine / train / evaluate |
| Health | `/health` | GET | Liveness |
| Health | `/ready` | GET | Readiness |
| Metrics | `/metrics` | GET | Prometheus exposition |

```mermaid
flowchart TB
    CLI["Client"] --> API["FastAPI"]
    API --> PC["Postgres Client"]
    API --> NC["Neo4j Client"]
    API --> CFG["Pydantic Models"]
    API --> ML["Model Catalog"]
    PC --> DB[("PostgreSQL")]
    NC --> GDB[("Neo4j")]
```

## Example: Search Roundtrip (Annotated)

=== "Python"
```python
import httpx
base = "http://localhost:8000"

payload = {
    "corpus_id": "tribrid",  # (1)
    "query": "authentication flow",
    "top_k": 10
}
resp = httpx.post(f"{base}/search", json=payload)
resp.raise_for_status()
res = resp.json()  # type: SearchResponse (2)
print(res["fusion_method"], len(res["matches"]))
```

=== "curl"
```bash
BASE=http://localhost:8000
curl -sS -X POST "$BASE/search" \
  -H 'Content-Type: application/json' \
  -d '{"corpus_id":"tribrid","query":"authentication flow","top_k":10}' | jq '.fusion_method, .matches | length'
```

=== "TypeScript"
```typescript
import type { SearchRequest, SearchResponse } from "../web/src/types/generated";

async function run(req: SearchRequest): Promise<SearchResponse> {
  const r = await fetch("/search", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(req) });
  return await r.json(); // (2)
}
```

1. Always scope by `corpus_id` (legacy `repo_id` is accepted)
2. Response includes `fusion_method`, `reranker_mode`, `latency_ms`, and `matches` with provenance

!!! success "Model Catalog Endpoint"
    The UI must populate model selectors from `/models/...`. Do not hardcode lists.

## Health and Metrics

=== "Python"
```python
import httpx
print(httpx.get("http://localhost:8000/ready").json())   # readiness
print(httpx.get("http://localhost:8000/metrics").text[:300])  # metrics sample
```

=== "curl"
```bash
curl -sS http://localhost:8000/health | jq .
curl -sS http://localhost:8000/ready | jq .
curl -sS http://localhost:8000/metrics | head -n 20
```

=== "TypeScript"
```typescript
await fetch('/ready').then(r => r.ok || Promise.reject('Not ready'))
const metrics = await (await fetch('/metrics')).text()
console.log(metrics.split('\n').slice(0,5))
```

??? note "Streaming"
    Endpoints that can stream long-running operations (e.g., evaluation logs, training metrics) use Server-Sent Events or chunked JSON. Use backpressure-aware clients.
