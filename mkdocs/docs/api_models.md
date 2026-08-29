# Domain Models (Core Shapes)

<div class="grid chunk_summaries" markdown>

-   :material-shape-outline:{ .lg .middle } **Chunks**

    ---

    `Chunk`, `ChunkMatch`, `ChunkSummary` are the bread-and-butter types for RAG.

-   :material-timeline-text:{ .lg .middle } **Search/Answer**

    ---

    `SearchRequest/Response`, `AnswerRequest/Response`.

-   :material-forum:{ .lg .middle } **Chat**

    ---

    `ChatRequest/Response` with debug metadata.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Use generated types"
    Import types from `web/src/types/generated.ts`. Do not hand-write interfaces.

!!! note "Provenance"
    `ChunkMatch.source` preserves which leg (vector/sparse/graph) produced the match.

!!! warning "Line Ranges"
    When hydrating content, respect `hydration_max_chars` to avoid oversized payloads.

| Model | Key Fields |
|-------|------------|
| `Chunk` | `chunk_id`, `content`, `file_path`, `start_line`, `end_line`, `language`, `token_count` |
| `ChunkMatch` | `chunk_id`, `score`, `source`, `metadata`, `provenance` |
| `SearchRequest` | `corpus_id`, `query`, `top_k`, `include_vector/sparse/graph` |
| `SearchResponse` | `matches`, `fusion_method`, `reranker_mode`, `latency_ms` |
| `AnswerRequest` | `corpus_id`, `query`, `top_k`, `stream` |
| `AnswerResponse` | `answer`, `sources`, `model`, `tokens_used` |

```mermaid
flowchart LR
    Req["SearchRequest"] --> API
    API --> Res["SearchResponse"]
    Res --> UI["UI Components"]
```

=== "Python"
```python
from pprint import pprint
import httpx
pprint(httpx.post("http://localhost:8000/search", json={"corpus_id":"tribrid","query":"auth","top_k":5}).json())
```

=== "curl"
```bash
curl -sS -X POST http://localhost:8000/search -H 'Content-Type: application/json' -d '{"corpus_id":"tribrid","query":"auth","top_k":5}' | jq .
```

=== "TypeScript"
```typescript
import type { SearchResponse } from "./web/src/types/generated";
const data: SearchResponse = await (await fetch('/search', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id:'tribrid', query:'auth', top_k:5 }) })).json();
```

??? info "Hydration"
    Hydration strategy is controlled by `hydration.hydration_mode` and `hydration.hydration_max_chars` (also surfaced under `retrieval.*` for convenience).
