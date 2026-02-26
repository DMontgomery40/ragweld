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
| `fusion.sparse_weight` | `FUSION_SPARSE_WEIGHT` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Weight for sparse BM25/FTS search results |
| `fusion.vector_weight` | `FUSION_VECTOR_WEIGHT` | `float` | `0.4` | ≥ 0.0, ≤ 1.0 | Weight for vector search results (pgvector) |

### Details (glossary)

??? info "`fusion.graph_weight` (`FUSION_GRAPH_WEIGHT`) — Graph Weight"
    **Category**: `general`

    Weight assigned to graph (Neo4j) search results in weighted fusion mode. Higher values (0.4-0.6) favor structural relationships, lower values (0.2-0.3) reduce graph influence. Weights must sum to ~1.0 with vector and sparse weights. Recommended: 0.3 for balanced tri-brid retrieval.

    Sweet spot: 0.3 for balanced systems. Use 0.4-0.5 when graph relationships are critical (e.g., finding code that calls or imports specific functions). Use 0.2 when vector and sparse search are more important.

    • Range: 0.0-1.0 (must sum with vector + sparse ≈ 1.0)
    • Vector/sparse-focused: 0.2 (lower graph weight)
    • Balanced: 0.3 (recommended)
    • Graph-focused: 0.4-0.5 (higher graph weight)
    • Effect: Higher = more weight to graph search results
    • Symptom too high: Graph matches dominate, other modalities buried
    • Symptom too low: Graph relationships undervalued

    **Badges**:
    - Weighted Mode

    **Links**:
    - [Neo4j GraphRAG](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Graph Traversal](https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package)
    - [Weighted Fusion](https://en.wikipedia.org/wiki/Data_fusion)

??? info "`fusion.method` (`FUSION_METHOD`) — Fusion Method"
    **Category**: `general`

    Method for combining results from vector, sparse, and graph search: "rrf" (Reciprocal Rank Fusion) or "weighted" (score-based weighted sum). RRF combines ranking positions without score normalization, making it robust to different score scales. Weighted fusion requires normalized scores and allows fine-grained control over modality weights.

    Sweet spot: "rrf" for most use cases. RRF is simpler, more robust, and doesn't require score normalization. Use "weighted" when you need precise control over modality weights or when score distributions are well-calibrated.

    • RRF: Position-based fusion, robust to score scales, simpler
    • Weighted: Score-based fusion, requires normalization, more control
    • Effect: Determines how tri-brid results are combined
    • Symptom wrong method: Suboptimal result ranking

    **Badges**:
    - Core Setting

    **Links**:
    - [Reciprocal Rank Fusion](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
    - [RRF Paper](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)
    - [Data Fusion](https://en.wikipedia.org/wiki/Data_fusion)

??? info "`fusion.normalize_scores` (`FUSION_NORMALIZE_SCORES`) — Normalize Scores"
    **Category**: `general`

    Normalize scores from vector, sparse, and graph search to [0,1] range before fusion. This ensures scores from different modalities are comparable when using weighted fusion. When disabled, raw scores are used directly (may cause one modality to dominate). Recommended: enabled for weighted fusion, not needed for RRF.

    Sweet spot: enabled for weighted fusion mode. Normalization prevents one modality from dominating due to different score scales. For RRF mode, normalization is unnecessary since RRF uses ranking positions, not scores.

    • Enabled: Scores normalized to [0,1], comparable across modalities
    • Disabled: Raw scores used, may cause modality imbalance
    • Effect: Controls score normalization before weighted fusion
    • Symptom if disabled: One modality may dominate due to score scale differences

    **Badges**:
    - Weighted Mode

    **Links**:
    - [Score Normalization](https://link.springer.com/chapter/10.1007/11880592_57)
    - [Normalization Methods](https://codecademy.com/article/min-max-zscore-normalization)
    - [Data Fusion](https://en.wikipedia.org/wiki/Data_fusion)

??? info "`fusion.rrf_k` (`FUSION_RRF_K`) — RRF k Parameter"
    **Category**: `general`

    RRF constant for tri-brid fusion when method is rrf. Formula: sum(1/(k+rank)). Lower k emphasizes top ranks more; higher k distributes weight more evenly. Default: 60. Range: 1-200.

    **Badges**:
    - RRF Mode

    **Links**:
    - [RRF Original Paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)
    - [RRF Research](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/)
    - [Reciprocal Rank Fusion](https://en.wikipedia.org/wiki/Reciprocal_rank_fusion)

??? info "`fusion.sparse_weight` (`FUSION_SPARSE_WEIGHT`) — Sparse Weight"
    **Category**: `general`

    Weight assigned to sparse (BM25) search results in weighted fusion mode. Higher values (0.4-0.6) favor keyword matches, lower values (0.2-0.3) reduce keyword influence. Weights must sum to ~1.0 with vector and graph weights. Recommended: 0.3 for balanced tri-brid retrieval.

    Sweet spot: 0.3 for balanced systems. Use 0.4-0.5 when exact keyword matching is critical (e.g., finding specific function names or error codes). Use 0.2 when semantic and graph search are more important.

    • Range: 0.0-1.0 (must sum with vector + graph ≈ 1.0)
    • Semantic-focused: 0.2 (lower keyword weight)
    • Balanced: 0.3 (recommended)
    • Keyword-focused: 0.4-0.5 (higher keyword weight)
    • Effect: Higher = more weight to sparse search results
    • Symptom too high: Keyword matches dominate, semantic matches buried
    • Symptom too low: Keyword matches undervalued

    **Badges**:
    - Weighted Mode

    **Links**:
    - [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [Hybrid Search](https://www.elastic.co/search-labs/blog/improving-information-retrieval-elastic-stack-hybrid)
    - [Weighted Fusion](https://en.wikipedia.org/wiki/Data_fusion)

??? info "`fusion.vector_weight` (`FUSION_VECTOR_WEIGHT`) — Vector Weight"
    **Category**: `general`

    Weight assigned to vector (pgvector) search results in weighted fusion mode. Higher values (0.5-0.7) favor semantic matches, lower values (0.2-0.4) reduce semantic influence. Weights must sum to ~1.0 with sparse and graph weights. Recommended: 0.4 for balanced tri-brid retrieval.

    Sweet spot: 0.4 for balanced systems. Use 0.5-0.6 when semantic matching is critical (e.g., finding conceptually similar code). Use 0.2-0.3 when keyword matching is more important than semantics.

    • Range: 0.0-1.0 (must sum with sparse + graph ≈ 1.0)
    • Keyword-focused: 0.2-0.3 (lower semantic weight)
    • Balanced: 0.4 (recommended)
    • Semantic-focused: 0.5-0.6 (higher semantic weight)
    • Effect: Higher = more weight to vector search results
    • Symptom too high: Semantic matches dominate, keyword matches buried
    • Symptom too low: Semantic matches undervalued

    **Badges**:
    - Weighted Mode

    **Links**:
    - [Hybrid Search](https://www.pinecone.io/learn/hybrid-search-intro/)
    - [Weighted Fusion](https://en.wikipedia.org/wiki/Data_fusion)
    - [Fusion Strategies](https://arxiv.org/abs/2402.14734)
