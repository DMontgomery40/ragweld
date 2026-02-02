# API Cheatsheet (Quick Calls)

<div class="grid chunk_summaries" markdown>

-   :material-run:{ .lg .middle } **Fast Paths**

    ---

    Minimal calls to get from zero to search.

-   :material-file-cog:{ .lg .middle } **Config**

    ---

    Read, patch, reset.

-   :material-magnify:{ .lg .middle } **Search**

    ---

    Tri-brid retrieval with optional reranking.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

=== "Python"
```python
import httpx
B = "http://localhost:8000"
httpx.get(f"{B}/ready").raise_for_status()
httpx.post(f"{B}/index", json={"corpus_id":"tribrid","repo_path":"/repo","force_reindex":False})
print(httpx.post(f"{B}/search", json={"corpus_id":"tribrid","query":"auth flow","top_k":10}).json())
```

=== "curl"
```bash
BASE=http://localhost:8000
curl -sS "$BASE/ready" | jq .
curl -sS -X POST "$BASE/index" -H 'Content-Type: application/json' -d '{"corpus_id":"tribrid","repo_path":"/repo","force_reindex":false}'
curl -sS -X POST "$BASE/search" -H 'Content-Type: application/json' -d '{"corpus_id":"tribrid","query":"auth flow","top_k":10}' | jq .
```

=== "TypeScript"
```typescript
await fetch('/ready')
await fetch('/index', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id:'tribrid', repo_path:'/repo', force_reindex:false }) })
const data = await (await fetch('/search', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id:'tribrid', query:'auth flow', top_k:10 }) })).json()
console.log(data)
```

!!! info "Use generated types"
    In TS code, import `SearchRequest`, `SearchResponse`, `IndexRequest` from `web/src/types/generated.ts`.
