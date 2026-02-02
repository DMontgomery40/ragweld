# Corpus vs repo_id

<div class="grid chunk_summaries" markdown>

-   :material-folder:{ .lg .middle } **Corpus-First**

    ---

    A corpus is any folder you index: repo, docs, or subtree.

-   :material-shield-sync:{ .lg .middle } **Isolation**

    ---

    Each corpus has separate Postgres tables, Neo4j DB, and config.

-   :material-rename:{ .lg .middle } **Naming Migration**

    ---

    API accepts `repo_id` but serializes as `corpus_id`.

</div>

[Get started](../index.md){ .md-button .md-button--primary }
[Configuration](../configuration.md){ .md-button }
[API](../api.md){ .md-button }

!!! tip "Best Practice"
    Use stable, lowercase slugs for corpus ids, e.g., `tribrid`, `myapp-docs`. Avoid spaces and special characters.

!!! note "AliasChoices"
    Pydantic models specify `validation_alias=AliasChoices("repo_id", "corpus_id")` and `serialization_alias="corpus_id"` to ensure forward compatibility.

!!! warning "Cross-Corpus Leakage"
    Never mix `corpus_id` across requests. Isolation is enforced in storage and graph layers.

## Models Using corpus_id

| Model | Fields |
|-------|--------|
| `IndexRequest` | `corpus_id`, `repo_path`, `force_reindex` |
| `IndexStatus` | `corpus_id`, `status`, `progress`, `current_file` |
| `SearchRequest` | `corpus_id`, `query`, `top_k` |

```mermaid
flowchart LR
    UI["UI"] --> API["API"]
    API --> Pyd["AliasChoices(repo_id, corpus_id)"]
    Pyd --> Store["Serialized as corpus_id"]
```

## Example Requests

=== "Python"
```python
import httpx
req = {"corpus_id": "tribrid", "repo_path": "/code/tribrid", "force_reindex": False}
httpx.post("http://localhost:8000/index", json=req)
httpx.get("http://localhost:8000/index/status", params={"corpus_id": "tribrid"})
```

=== "curl"
```bash
curl -sS -X POST http://localhost:8000/index -H 'Content-Type: application/json' -d '{
  "corpus_id": "tribrid", "repo_path": "/code/tribrid", "force_reindex": false
}'
```

=== "TypeScript"
```typescript
import type { IndexRequest } from "../../web/src/types/generated";
const req: IndexRequest = { corpus_id: 'tribrid', repo_path: '/code/tribrid', force_reindex: false };
```

!!! success "Multi-Corpus UIs"
    Add a repo switcher bound to `corpus_id`. All panels (RAG, Graph, Index) should update in lockstep.
