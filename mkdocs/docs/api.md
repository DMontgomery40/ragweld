<div class="grid chunk_summaries" markdown>

-   :material-information:{ .lg .middle } **API Endpoints**

    ---

    FastAPI endpoints in server/api/

-   :material-magnify:{ .lg .middle } **Search & Retrieval**

    ---

    /search, /graph, /chunk_summaries

-   :material-cog:{ .lg .middle } **Config & Models**

    ---

    /config, /models, /reranker

</div>

!!! note "Implementation Note"
    The API routes map directly to the server modules under server/api. Each endpoint uses Pydantic models for request/response validation.

!!! tip "Pro Tip"
    Use the models endpoint (GET /models) as the authoritative list for UI dropdowns. Do not hardcode model lists elsewhere.

!!! warning "Compatibility Warning"
    API still uses `repo_id` naming. When scoping operations, prefer `corpus_id` but accept `repo_id` for compatibility.

??? note "Collapsible: Endpoint index"

    The API modules expose endpoints and helper functions. Key modules include:

    - chunk_summaries.py
    - config.py
    - reranker.py
    - models.py
    - index.py
    - graph.py


## Selected endpoints and usage

| Endpoint | Method | Purpose | Request model |
|----------|--------|---------|---------------|
| /search | POST | Run tri-brid search | SearchRequest (generated) |
| /config | GET/PUT/PATCH | Read/update server config | TriBridConfig (generated) |
| /models | GET | Serve data/models.json | n/a |
| /chunk_summaries | GET/POST | Read/build chunk summaries | IndexScope / BuildRequest |
| /graph/{corpus_id}/entities | GET | List graph entities | CorpusScope |


```mermaid
flowchart LR
    Client --> API[FastAPI]
    API --> Search[/search]
    API --> Models[/models]
    API --> Config[/config]
    Search --> Fusion[TriBridFusion]
    Fusion --> DB[(Postgres)]
    Fusion --> Graph[(Neo4j)]
```


### Example: search call

=== "Python"
    ```python
    import requests

    resp = requests.post('http://localhost:8000/search', json={
      'query': 'how to run migrations',
      'repo_id': 'my_corpus'
    }) # (1)
    print(resp.json())
    ```

=== "curl"
    ```bash
    curl -X POST "http://localhost:8000/search" \
      -H 'Content-Type: application/json' \
      -d '{"query":"how to run migrations","repo_id":"my_corpus"}'
    ```

=== "TypeScript"
    ```typescript
    import { SearchRequest, SearchResponse } from '../types/generated' // (1)

    async function run(query: string, repoId: string): Promise<SearchResponse> {
      const res = await fetch('/api/search', {
        method: 'POST',
        body: JSON.stringify({ query, repo_id: repoId }),
      })
      return res.json()
    }
    ```


1. Use generated types for request/response shapes


### Reranker endpoints (selected)

| Route | Method | Purpose |
|-------|--------|---------|
| /reranker/status | GET | Check if reranker is loaded |
| /reranker/mine | POST | Mine triplets for training |
| /reranker/train | POST | Train a reranker model |
| /reranker/evaluate | POST | Evaluate reranker performance |


### Chunk summaries endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| /chunk_summaries | GET | List summaries for a corpus |
| /chunk_summaries/build | POST | Trigger background build of chunk summaries |


- [x] Use ++ctrl+c++ to copy curl snippets
- [x] Use generated TypeScript types from Pydantic for API contracts


??? note "Collapsible: Error handling"

    FastAPI returns structured errors when validation fails. Check status codes and error messages that include the failing field path.
