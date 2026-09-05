# Architecture

<div class="grid chunk_summaries" markdown>

-   :material-source-branch:{ .lg .middle } **Tri-Path Retrieval**

    ---

    Vector, Sparse, and Graph retrievers run concurrently for maximum recall.

-   :material-shuffle-variant:{ .lg .middle } **Fusion Layer**

    ---

    Weighted fusion or RRF unifies heterogeneous scores into one ranking.

-   :material-swap-vertical:{ .lg .middle } **Optional Reranker**

    ---

    Cloud rerankers and the Qwen3 LoRA learning reranker can refine the fused list.

-   :material-cog:{ .lg .middle } **Pydantic-Orchestrated**

    ---

    All engine parameters are Pydantic fields with constraints and defaults.

-   :material-rocket:{ .lg .middle } **FastAPI Surface**

    ---

    Clean endpoints for indexing, retrieval, graph queries, and system health.

-   :material-chart-areaspline:{ .lg .middle } **Observability**

    ---

    Readiness + Prometheus metrics + PostgreSQL exporter.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Concurrency"
    ragweld parallelizes retrievers with async I/O. Size DB connection pools to match concurrency and avoid I/O starvation.

!!! note "Failure Isolation"
    Each retriever is wrapped so failures degrade that leg only. Fusion runs on the subset that succeeded; fused results keep provenance in `ChunkMatch.source`.

!!! warning "Graph Availability"
    When the graph leg is requested and Neo4j (or the Qdrant seed store) is unavailable, the request fails with a typed dependency error rather than silently returning partial results. Disable the leg per request (`include_graph=false`) if you need vector+sparse-only behavior during an outage.

## System Diagram

```mermaid
flowchart LR
    subgraph API["FastAPI"]
      FAPI["Search / Chat / Answer routes"]
      CACHE["Semantic cache\n(server/retrieval/cache.py)"]
    end

    subgraph Legs["Three retrieval legs"]
      V["Vector leg\n(Qdrant dense generation)"]
      S["Sparse leg\n(Qdrant BM25 sparse generation)"]
      G["Graph leg\n(Qdrant seeds joined to Neo4j)"]
    end

    FAPI --> CACHE
    CACHE --> EMB["Query embedder"]
    EMB --> V
    EMB --> G
    CACHE --> S

    V --> FU["Fusion"]
    S --> FU
    G --> FU

    FU --> BOOST["Scoring boosts +\ndedup / MMR"]
    BOOST --> RR["Reranker\n(optional)"]
    RR --> CONF["Confidence gate\n(conf_top1 / conf_avg5)"]
    FU --> CONF
    CONF --> HYD["Hydration\n(lazy / eager)"]
    HYD --> RES["Results"]

    V <--> QD["Qdrant\n(dense + sparse)"]
    S <--> QD
    G <--> QD
    G <--> NEO["Neo4j\n(entities + FROM_CHUNK)"]
    HYD <--> PG["Postgres\n(chunk rows)"]
```

The authoritative, code-generated version of this pipeline — every leg, weight, gate and default — lives on the generated [retrieval pipeline reference](reference/architecture/retrieval-pipeline.md).

## Layer Responsibilities

| Layer | Module | Responsibilities | Representative Config |
|------|--------|------------------|-----------------------|
| Vector | `server/retrieval/qdrant_store.py` | Dense search over the corpus Qdrant generation | `vector_search.enabled`, `vector_search.top_k`, `embedding.*` |
| Sparse | `server/retrieval/qdrant_store.py` | IDF-modified BM25 sparse vectors (fastembed `Qdrant/bm25`) | `sparse_search.enabled`, `sparse_search.top_k`, `indexing.bm25_*` |
| Graph | `server/retrieval/graphrag_retriever.py` | Qdrant-seeded, generation-scoped Neo4j traversal over `FROM_CHUNK` entities and `NEXT_CHUNK` neighbors | `graph_search.enabled`, `graph_search.max_hops`, `graph_search.top_k`, `graph_storage.*` |
| Fusion | `server/retrieval/fusion.py` | Merge lists and scores | `fusion.method`, `fusion.rrf_k`, `fusion.*_weight` |
| Reranker | `server/retrieval/rerank.py` | Cloud/learning reranker scoring | `reranking.reranker_mode`, `reranking.*` |

## Hot Path (Annotated)

=== "Python"
```python
from server.retrieval.fusion import TriBridFusion
from server.retrieval.rerank import Reranker

async def search(query: str, corpus_id: str, cfg):  # (1)!
    fusion = TriBridFusion(cfg)
    fused = await fusion.search(corpus_id, query)   # (2)!
    if cfg.reranking.reranker_mode != "none":
        rr = Reranker(cfg)
        fused = await rr.rerank(query, fused)       # (3)!
    return fused                                    # (4)!
```

1. Query and corpus identifier; use `corpus_id` (alias of legacy `repo_id`)
2. Fusion runs vector/sparse/graph concurrently and merges results
3. Optional rerank, then return typed response
4. Returns unified `SearchResponse` with provenance and latency

=== "curl"
```bash
BASE=http://127.0.0.1:8012/api
# (2)! Fusion (vector+sparse+graph)
curl -sS -X POST "$BASE/search" \
  -H 'Content-Type: application/json' \
  -d '{
    "corpus_id": "tribrid",
    "query": "connection pool size",
    "top_k": 10
  }' | jq '.matches[0]'
```

=== "TypeScript"
```typescript
import type { SearchRequest, SearchResponse } from "./web/src/types/generated";

export async function triSearch(req: SearchRequest): Promise<SearchResponse> {
  const resp = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return await resp.json(); // (4)!
}
```

## Fusion Choices

| Method | Formula | Strengths | Notes |
|--------|---------|-----------|-------|
| weighted | `w_v*sv + w_s*ss + w_g*sg` | Interpretable weight tuning | Normalize scores if distributions differ |
| rrf | `sum 1/(k+rank_i)` | Robust across heterogeneous scales | Tune `rrf_k` in `fusion.rrf_k` |

```mermaid
flowchart TB
    Q["Query"] --> V["Vector Top-K"]
    Q --> S["Sparse Top-K"]
    Q --> G["Graph Top-K"]
    V --> FU["Fusion"]
    S --> FU
    G --> FU
    FU --> OUT["Top-N Results"]
```

??? note "Implementation Notes"
    - All configurable fields (weights, top_k, thresholds) live in `TriBridConfig`. Frontend sliders and toggles must map 1:1 to these fields via `generated.ts`.
    - DB clients: `server/db/postgres.py` (pgvector + FTS) and `server/db/neo4j.py` (graph). Keep pools separate to avoid head-of-line blocking.

