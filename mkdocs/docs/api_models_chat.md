# Chat Models

<div class="grid chunk_summaries" markdown>

-   :material-chat-processing:{ .lg .middle } **Request/Response**

    ---

    `ChatRequest` and `ChatResponse` with streaming option.

-   :material-bug-outline:{ .lg .middle } **Debug Info**

    ---

    `ChatDebugInfo` includes per-leg enablement and fusion params.

-   :material-timeline-text:{ .lg .middle } **Tracing**

    ---

    `Trace`, `TraceEvent`, and `/traces/latest` for last run.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Data Sources"
    Chat composes sources: one or more corpora and (optionally) Recall. There are no modes — everything composes.

!!! note "Vision"
    `images` supports up to 5 attachments when the model/provider supports multimodal.

!!! warning "Recall Scope"
    Recall gating only affects Recall; RAG corpora are always queried when checked.

| Model | Key Fields |
|-------|------------|
| `ChatRequest` | `message`, `corpus_id`, `sources`, `top_k`, `include_vector/sparse/graph`, `stream`, `web_enabled` |
| `ChatResponse` | `message`, `sources`, `tokens_used`, `debug`, `conversation_id`, `web_grounding` |
| `ChatDebugInfo` | `fusion_method`, `rrf_k`, per-leg weights, confidence thresholds, graph leg counts (`graph_qdrant_seed_chunks`, `graph_resolved_entities`, `graph_relationship_expansion_hits`, `graph_community_expansion_hits`, `graph_hydrated_chunks`) |

```mermaid
flowchart LR
    Req["ChatRequest"] --> API
    API --> Res["ChatResponse"]
    Res --> UI["Render + Sources"]
```

=== "Python"
```python
import httpx
print(httpx.post("http://127.0.0.1:8012/api/chat", json={"corpus_id":"tribrid","message":"where is auth?"}).json())
```

=== "curl"
```bash
curl -sS -X POST http://127.0.0.1:8012/api/chat -H 'Content-Type: application/json' -d '{"corpus_id":"tribrid","message":"where is auth?"}' | jq .
```

=== "TypeScript"
```typescript
const r = await (await fetch('/api/chat', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id:'tribrid', message:'where is auth?' }) })).json();
```

??? info "Recall Gate"
    `ChatResponse.debug.recall_plan` exposes the decision: intensity, overrides, and the signals behind them.
