# Searching & answering

<div class="grid chunk_summaries" markdown>

-   :material-magnify:{ .lg .middle } **Search**

    ---

    `/api/search` returns ranked chunk matches (no LLM generation).

-   :material-comment-text:{ .lg .middle } **Answer**

    ---

    `/api/answer` runs retrieval, then generates an answer with sources.

-   :material-tune:{ .lg .middle } **Control the legs**

    ---

    Toggle vector/sparse/graph per request and tune fusion/reranking via config.

</div>

[Quickstart](quickstart.md){ .md-button .md-button--primary }
[Indexing](indexing.md){ .md-button }
[Retrieval overview](../retrieval/overview.md){ .md-button }
[Configuration](../configuration.md){ .md-button }

!!! tip "Default API base"
    `http://127.0.0.1:8012/api`

!!! warning "Costs"
    Answer generation and some reranking modes can incur provider costs. If you’re experimenting, start with `/api/search` until you trust your retrieval.

## 1) Use `/api/search` to inspect retrieval quality

`/api/search` is the fastest way to debug relevance: it returns **matches**, their **scores**, and which leg produced them.

=== "curl"
    ```bash
    BASE="http://127.0.0.1:8012/api"
    curl -sS -X POST "$BASE/search" \
      -H "Content-Type: application/json" \
      -d '{
        "corpus_id": "demo",
        "query": "where is the FastAPI router mounted?",
        "top_k": 8,
        "include_vector": true,
        "include_sparse": true,
        "include_graph": true
      }' | jq '.matches[] | {file_path, start_line, end_line, score, source}'
    ```

=== "Python"
    ```python
    import httpx

    BASE = "http://127.0.0.1:8012/api"
    payload = {
        "corpus_id": "demo",
        "query": "where is the FastAPI router mounted?",
        "top_k": 8,
        "include_vector": True,
        "include_sparse": True,
        "include_graph": True,
    }
    res = httpx.post(f"{BASE}/search", json=payload, timeout=30).json()
    for m in res.get("matches", []):
        print(m["source"], m["file_path"], m["start_line"], m["end_line"], m["score"])
    ```

## 2) Use `/api/answer` when retrieval is “good enough”

`/api/answer` uses retrieval matches as context and asks the selected generation model to produce an answer.

!!! warning "Answers fail closed"
    If generation cannot run (no provider, spend limit, empty reply) or retrieval itself fails, `/api/answer` answers a typed `503` and `/api/answer/stream` emits a typed `error` event before `done` — neither returns a "retrieval-only" answer assembled from the sources. The error card names the failure class and the operator hint; see [Chat models](../api_models_chat.md).

```bash
BASE="http://127.0.0.1:8012/api"
curl -sS -X POST "$BASE/answer" \
  -H "Content-Type: application/json" \
  -d '{
    "corpus_id": "demo",
    "query": "How do I start the system locally and verify it is ready?",
    "top_k": 10
  }' | jq '{answer, sources_count: (.sources | length), model}'
```

## 3) Streaming answers

If you want tokens as they arrive, use `/api/answer/stream`.

!!! note "Clients differ"
    Some HTTP clients buffer output unless you disable buffering. Prefer `curl -N` or an SSE-aware client.

```bash
BASE="http://127.0.0.1:8012/api"
curl -N -sS -X POST "$BASE/answer/stream" \
  -H "Content-Type: application/json" \
  -d '{"corpus_id":"demo","query":"Summarize the indexing pipeline","top_k":10}'
```

## Quick tuning checklist (practical)

When answers are wrong, the cause is almost always one of:

1) the **corpus** wasn’t indexed as you think  
2) the **retrieval legs** didn’t pull the right chunks  
3) fusion/reranking reshuffled results in a surprising way  

- [ ] Confirm the correct corpus: `corpus_id` in every request
- [ ] Check index status: `/api/index/<corpus>/status`
- [ ] Run `/api/search` and inspect **source** (`vector|sparse|graph`) for top matches
- [ ] If recall is low, raise candidate sizes and/or reduce thresholds (via config)
- [ ] If precision is low, enable reranking and/or raise confidence gates (via config)

??? tip "When to disable a leg"
    - Disable **graph** if Neo4j is down or you want baseline performance.
    - Disable **sparse** if your corpus is mostly natural language without identifiers.
    - Disable **vector** if you’re debugging exact-identifier matching.

