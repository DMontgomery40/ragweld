# Config reference: `fusion`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 6

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `fusion.graph_weight` | `FUSION_GRAPH_WEIGHT` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Weight for graph search results (Neo4j) |
| `fusion.method` | `FUSION_METHOD` | `Literal["rrf", "weighted"]` | `"rrf"` | allowed="rrf", "weighted" | Fusion method: 'rrf' (Reciprocal Rank Fusion) or 'weighted' (score-based) |
| `fusion.normalize_scores` | `FUSION_NORMALIZE_SCORES` | `bool` | `true` | — | Normalize scores to [0,1] before fusion |
| `fusion.rrf_k` | `FUSION_RRF_K` | `int` | `60` | ≥ 1, ≤ 200 | RRF smoothing constant (higher = more weight to top ranks) |
| `fusion.sparse_weight` | `FUSION_SPARSE_WEIGHT` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Weight for sparse (Qdrant/bm25) search results |
| `fusion.vector_weight` | `FUSION_VECTOR_WEIGHT` | `float` | `0.4` | ≥ 0.0, ≤ 1.0 | Weight for vector search results (Qdrant dense) |

### Details (glossary)

??? info "`fusion.graph_weight` (`FUSION_GRAPH_WEIGHT`) — Graph Weight"
    **Category**: `general`

    Sets the contribution of graph retrieval in weighted fusion relative to sparse and vector signals. Increase it when structural relationships such as calls, imports, and dependencies are essential to user tasks; decrease it when lexical or semantic similarity should dominate. Because weighted fusion blends heterogeneous score sources, calibration and normalization matter as much as the raw weight values. Track performance by query type to ensure graph-heavy tuning improves structural questions without hurting broad semantic retrieval.

    **Badges**:
    - Fusion weighting

    **Links**:
    - [RGL Graph-Centric RAG (arXiv)](https://arxiv.org/abs/2503.19314)
    - [Neo4j GraphRAG User Guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Azure Vector Weighting](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-query#vector-weighting)
    - [Neo4j PageRank](https://neo4j.com/docs/graph-data-science/current/algorithms/page-rank/)

??? info "`fusion.method` (`FUSION_METHOD`) — Fusion Method"
    **Category**: `general`

    Chooses how result lists from different retrievers are combined. Reciprocal Rank Fusion is usually robust when score scales are incomparable, while weighted score fusion is better when each modality is well normalized and intentionally calibrated. The method you choose affects both stability and interpretability of ranking behavior across query types. Keep evaluation and production on the same fusion method so offline gains translate reliably at runtime.

    **Badges**:
    - Core fusion strategy

    **Links**:
    - [Exp4Fuse Rank Fusion (arXiv)](https://arxiv.org/abs/2506.04760)
    - [Elasticsearch RRF](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Azure Hybrid Ranking](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
    - [OpenSearch Normalization Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/)

??? info "`fusion.normalize_scores` (`FUSION_NORMALIZE_SCORES`) — Normalize Scores"
    **Category**: `general`

    In weighted fusion, vector similarity, BM25 relevance, and graph traversal scores usually exist on different numeric scales. This setting rescales them before combination so each retriever contributes based on relevance rather than raw magnitude. Keep normalization enabled when using weighted fusion, because otherwise one modality can dominate final ranking even with balanced weights. For rank-only fusion like RRF, normalization is usually unnecessary because only positions matter. If tuning weights does not change top results much, inspect score distributions first; poor normalization is often the real issue.

    **Badges**:
    - Fusion tuning

    **Links**:
    - [DAT: Dynamic Alpha Tuning for Hybrid Retrieval in RAG (arXiv 2025)](https://arxiv.org/abs/2503.23013)
    - [OpenSearch Normalization Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/)
    - [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid)
    - [Elasticsearch Reciprocal Rank Fusion API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)

??? info "`fusion.rrf_k` (`FUSION_RRF_K`) — RRF k Parameter"
    **Category**: `general`

    RRF combines result lists with the formula 1 divided by k plus rank, so k controls how quickly importance decays with lower-ranked items. Smaller k values strongly favor top hits from each retriever, while larger values preserve more mid-ranked candidates and improve diversity. In tri-brid retrieval, k interacts with each retriever depth and chunk granularity, so tune it with offline metrics instead of intuition. Start near 60, then lower it if results feel noisy and raise it if relevant alternatives disappear too quickly. Changing k is often safer than hand-tuning many modality weights.

    **Badges**:
    - RRF control

    **Links**:
    - [Hybrid RAG for Multilingual QA with RRF (arXiv 2025)](https://arxiv.org/abs/2512.12694)
    - [Reciprocal Rank Fusion Original Paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
    - [Elasticsearch Reciprocal Rank Fusion API](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)
    - [Unified Learning-to-Rank for Multi-Channel Retrieval (arXiv 2026)](https://arxiv.org/abs/2602.23530)

??? info "`fusion.sparse_weight` (`FUSION_SPARSE_WEIGHT`) — Sparse Weight"
    **Category**: `general`

    This weight controls how much lexical evidence from sparse retrieval influences the final fused ranking. Raising it improves exact-term tasks such as API names, error messages, file paths, and identifiers, but can reduce semantic recall when user wording differs from source text. Sparse weight should be tuned together with tokenizer and BM25 settings, because score behavior changes when stemming or chunk length changes. Use an evaluation set that includes both literal and conceptual queries so one class does not overfit the setting. If results become too keyword-literal, reduce this value before changing retriever architecture.

    **Badges**:
    - Keyword bias

    **Links**:
    - [DAT: Dynamic Alpha Tuning for Hybrid Retrieval in RAG (arXiv 2025)](https://arxiv.org/abs/2503.23013)
    - [Pinecone Hybrid Search Guide](https://docs.pinecone.io/guides/search/hybrid-search)
    - [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid)
    - [Elasticsearch Similarity and BM25 Settings](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity)

??? info "`fusion.vector_weight` (`FUSION_VECTOR_WEIGHT`) — Vector Weight"
    **Category**: `general`

    This weight determines how strongly semantic nearest-neighbor matches influence fused ranking. Higher values help when users ask conceptual questions using synonyms not present in source text, while lower values protect exact-match intent such as identifiers and versioned commands. Re-tune this after embedding-model changes, chunking changes, or reranker changes because score calibration shifts quickly across those updates. Evaluate with mixed query types and inspect which retriever wins per query, not just aggregate averages. If answers feel topically related but miss required literals, vector weight is likely too high.

    **Badges**:
    - Semantic bias

    **Links**:
    - [DAT: Dynamic Alpha Tuning for Hybrid Retrieval in RAG (arXiv 2025)](https://arxiv.org/abs/2503.23013)
    - [pgvector Extension](https://github.com/pgvector/pgvector)
    - [Pinecone Hybrid Search Guide](https://docs.pinecone.io/guides/search/hybrid-search)
    - [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid)
