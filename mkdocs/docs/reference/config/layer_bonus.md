# Config reference: `layer_bonus`

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
| `layer_bonus.freshness_bonus` | `FRESHNESS_BONUS` | `float` | `0.05` | ≥ 0.0, ≤ 0.3 | Bonus for recently modified files |
| `layer_bonus.gui` | `LAYER_BONUS_GUI` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for GUI/front-end layers |
| `layer_bonus.indexer` | `LAYER_BONUS_INDEXER` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for indexing/ingestion layers |
| `layer_bonus.intent_matrix` | `LAYER_INTENT_MATRIX` | `dict[str, dict[str, float]]` | `{"gui": {"gui": 1.2, "web": 1.2, "server": 0.9, "retrieval": 0.8, "indexer": 0.8}, "retrieval": {"retrieval": 1.3, "server": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}, "indexer": {"indexer": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}, "eval": {"eval": 1.3, "retrieval": 1.15, "server": 1.1, "web": 0.8, "gui": 0.7}, "infra": {"infra": 1.3, "scripts": 1.15, "server": 1.1, "web": 0.9}, "server": {"server": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6}}` | — | Intent-to-layer bonus matrix. Keys are query intents, values are layer->multiplier maps. |
| `layer_bonus.retrieval` | `LAYER_BONUS_RETRIEVAL` | `float` | `0.15` | ≥ 0.0, ≤ 0.5 | Bonus for retrieval/API layers |
| `layer_bonus.vendor_penalty` | `VENDOR_PENALTY` | `float` | `-0.1` | ≥ -0.5, ≤ 0.0 | Penalty for vendor/third-party code (negative values apply a penalty) |

### Details (glossary)

??? info "`layer_bonus.freshness_bonus` (`FRESHNESS_BONUS`) — Freshness Bonus"
    **Category**: `general`

    Adds a recency-based score bonus so newer files are favored during reranking. This is valuable in fast-moving repositories where recent commits are more likely to reflect current behavior, APIs, and incident fixes. The bonus should decay with file age to avoid suppressing stable but authoritative modules. Tune both the bonus magnitude and decay window against real query logs so freshness improves relevance without turning into naive newest-first ranking.

    **Badges**:
    - Temporal reranking

    **Links**:
    - [TempRetriever Temporal DPR (arXiv)](https://arxiv.org/abs/2502.21024)
    - [Elasticsearch Function Score](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Azure Scoring Profiles](https://learn.microsoft.com/en-us/azure/search/index-add-scoring-profiles)
    - [OpenSearch Function Score](https://docs.opensearch.org/latest/query-dsl/compound/function-score/)

??? info "`layer_bonus.gui` (`LAYER_BONUS_GUI`) — Layer Bonus (GUI)"
    **Category**: `ui`

    Score bias applied to chunks from frontend-oriented layers when query intent indicates UI behavior, navigation, or interaction logic. This helps a codebase RAG system rank components, views, and client-side state flows above backend internals when users ask interface-centric questions. Keep the bonus strong enough to overcome weak lexical overlap but not so strong that it suppresses semantically better backend evidence for mixed queries. The right setting is usually measured by evaluating intent-segmented query sets and checking whether UI questions improve without degrading cross-layer tasks.

    **Badges**:
    - Intent-layer routing

    **Links**:
    - [Meta-RAG for Large Codebases (arXiv)](https://arxiv.org/abs/2508.02611)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Azure Vector Weighting](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-query#vector-weighting)
    - [OpenSearch Normalization Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/)

??? info "`layer_bonus.indexer` (`LAYER_BONUS_INDEXER`) — Layer Bonus (Indexer)"
    **Category**: `retrieval`

    `LAYER_BONUS_INDEXER` is a structural ranking bias that boosts retrieval scores for artifacts mapped to indexing/ingestion layers before finer intent-matrix adjustments are applied. With the default `0.15` (range `0.0`-`0.5`), it helps prevent indexer-relevant files from being outscored by semantically similar but architecturally unrelated modules. Raising it increases recall for index pipeline troubleshooting and ingestion-change questions, but excessive values can over-prioritize indexer paths and reduce precision on mixed-intent queries. Tune this value together with other layer bonuses and evaluate with labeled queries that intentionally cross subsystem boundaries.

    **Links**:
    - [Single-Turn LLM Reformulation Powered Multi-Stage Hybrid Re-Ranking for Tip-of-the-Tongue Known-Item Retrieval (arXiv)](https://arxiv.org/abs/2602.10321)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Weaviate Hybrid Search](https://docs.weaviate.io/weaviate/search/hybrid)

??? info "`layer_bonus.intent_matrix` (`LAYER_INTENT_MATRIX`) — Intent Matrix (Advanced)"
    **Category**: `general`

    Advanced mapping that applies different layer weights per detected intent, effectively creating a policy table for architectural routing in retrieval. Instead of one global bonus, you can express rules like boosting frontend for UI intents, boosting services for API intents, and damping unrelated layers to reduce noise. This matrix is powerful but easy to overfit, so values should be tuned with offline eval sets that represent your real question mix and reviewed whenever repository structure changes. Treat it as a ranking policy artifact: version it, test it, and roll it out with the same discipline as model or index updates.

    **Badges**:
    - Intent policy

    **Links**:
    - [R3A: Query-Intent-Aware Relevance (arXiv)](https://arxiv.org/abs/2508.02506)
    - [Azure Scoring Profiles](https://learn.microsoft.com/en-us/azure/search/index-add-scoring-profiles)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [OpenSearch Normalization Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/)

??? info "`layer_bonus.retrieval` (`LAYER_BONUS_RETRIEVAL`) — Layer Bonus (Retrieval)"
    **Category**: `evaluation`

    Score bias applied to backend and data-access layers when intent classification indicates retrieval, API, indexing, or storage questions. It improves ranking for service, route, and data pipeline code when users ask how the system fetches or transforms information. Because this weight can overpower semantic relevance, tune it with side-by-side evaluations on UI and backend query slices to avoid over-routing everything to server code. In well-structured repos, this parameter is a high-leverage control for making architectural answers faster and more precise.

    **Badges**:
    - Intent-layer routing

    **Links**:
    - [Repository-level Code Search with LLMs (arXiv)](https://arxiv.org/abs/2502.07067)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Azure Scoring Profiles](https://learn.microsoft.com/en-us/azure/search/index-add-scoring-profiles)
    - [OpenSearch Normalization Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/)

??? info "`layer_bonus.vendor_penalty` (`VENDOR_PENALTY`) — Vendor Penalty"
    **Category**: `general`

    Negative score adjustment applied during reranking to chunks detected as third-party or vendored code (for example dependencies under vendor/, node_modules, generated SDKs, or mirrored upstream trees). The parameter is most useful when VENDOR_MODE prefers first-party sources and you want your application logic to outrank framework internals for ambiguous queries.

    Treat this as a ranking-bias control, not a hard filter: if the penalty is too large, relevant dependency docs can disappear from top results; if too small, repeated library boilerplate can crowd out business logic. Tune with side-by-side eval sets that include both product-code questions and dependency troubleshooting questions so recall and precision stay balanced.

    **Badges**:
    - Advanced RAG tuning
    - Code priority control

    **Links**:
    - [MICE: In-Context Retrieval and Reranking (arXiv 2026)](https://arxiv.org/abs/2602.16299)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [GitHub Linguist: How vendor/generated files are classified](https://github.com/github/linguist/blob/main/docs/how-linguist-works.md)
