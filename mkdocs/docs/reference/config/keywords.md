# Config reference: `keywords`

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

**Total parameters**: 5

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `keywords.keywords_auto_generate` | `KEYWORDS_AUTO_GENERATE` | `bool` | `true` | — | Auto-generate keywords |
| `keywords.keywords_boost` | `KEYWORDS_BOOST` | `float` | `1.3` | ≥ 1.0, ≤ 3.0 | Score boost for keyword matches |
| `keywords.keywords_max_per_repo` | `KEYWORDS_MAX_PER_REPO` | `int` | `50` | ≥ 10, ≤ 500 | Max discriminative keywords per repo |
| `keywords.keywords_min_freq` | `KEYWORDS_MIN_FREQ` | `int` | `3` | ≥ 1, ≤ 10 | Min frequency for keyword |
| `keywords.keywords_refresh_hours` | `KEYWORDS_REFRESH_HOURS` | `int` | `24` | ≥ 1, ≤ 168 | Hours between keyword refresh |

### Details (glossary)

??? info "`keywords.keywords_auto_generate` (`KEYWORDS_AUTO_GENERATE`) — Auto-Generate Keywords"
    **Category**: `general`

    Automatically derives routing and retrieval keywords from repository content so the system can bootstrap sparse relevance signals without full manual curation. In RAG this is especially useful for new repos or rapidly changing codebases where static keyword lists become stale. A strong auto-generation pipeline should normalize identifiers, remove boilerplate terms, and preserve domain-specific phrases that improve query-to-repo routing. Treat generated keywords as a candidate set that can be audited and refined, not as immutable truth. Quality usually improves when automatic extraction is combined with a small manually maintained allowlist and blocklist.

    **Badges**:
    - Auto routing

    **Links**:
    - [KeyRAG: Dynamic Keyphrase-Based Retrieval for Adaptive Generation](https://arxiv.org/abs/2510.09557)
    - [scikit-learn Text Feature Extraction](https://scikit-learn.org/stable/modules/feature_extraction.html#text-feature-extraction)
    - [scikit-learn TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)
    - [Elasticsearch Text Analysis](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis.html)

??? info "`keywords.keywords_boost` (`KEYWORDS_BOOST`) — Keywords Boost"
    **Category**: `general`

    Applies a multiplicative weight when documents match configured corpus keywords, allowing lexical intent signals to influence ranking beyond base retrieval scores. This is useful when user phrasing closely matches repo terminology, but aggressive boosting can overwhelm semantic relevance and reduce answer diversity. Calibrate with offline relevance evaluation so boosted ranking improves precision without collapsing recall. In hybrid retrieval, keyword boost should be tuned alongside BM25 parameters and dense fusion weights, not independently. Start conservative and increase only when you have evidence that keyword hits are consistently high-value.

    **Badges**:
    - Ranking weight

    **Links**:
    - [Practical BM25 Part 2: Optimizing an Effective and Robust Retriever](https://arxiv.org/abs/2502.17057)
    - [Elasticsearch Similarity Settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html)
    - [PostgreSQL Full Text Search Introduction](https://www.postgresql.org/docs/current/textsearch-intro.html)
    - [scikit-learn Text Feature Extraction](https://scikit-learn.org/stable/modules/feature_extraction.html#text-feature-extraction)

??? info "`keywords.keywords_max_per_repo` (`KEYWORDS_MAX_PER_REPO`) — Keywords Max Per Repo"
    **Category**: `general`

    Caps how many repository-specific keywords are retained for routing and scoring. The cap controls a core tradeoff: higher values increase topical coverage for broad repositories, while lower values reduce memory, indexing overhead, and ranking noise from generic terms. In multi-repo RAG, this directly affects router entropy and can change which repos are considered candidates for a query. Tune by repository size and lexical diversity, then verify with routing confusion metrics. If you observe cross-repo false positives, reducing this cap is often more effective than simply raising keyword boost.

    **Badges**:
    - Routing breadth

    **Links**:
    - [Improving Dense and Sparse Retrieval via Rank Fusion for LLM-Based Search](https://arxiv.org/abs/2506.04760)
    - [Elasticsearch Similarity Settings](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html)
    - [Weaviate Hybrid Search Concepts](https://docs.weaviate.io/weaviate/concepts/search/hybrid-search)
    - [PostgreSQL Full Text Search Introduction](https://www.postgresql.org/docs/current/textsearch-intro.html)

??? info "`keywords.keywords_min_freq` (`KEYWORDS_MIN_FREQ`) — Keywords Min Frequency"
    **Category**: `general`

    Sets the minimum corpus frequency a term must reach before it is eligible as a stored keyword. This acts as a denoising threshold that removes one-off tokens, typos, and low-signal identifiers from routing logic. A low threshold improves recall of niche concepts but can increase noise; a high threshold improves precision but can suppress critical rare terms like subsystem names or protocol identifiers. Optimal values depend on corpus scale and update velocity, so tune against validation queries rather than intuition. Many teams pair this threshold with exception rules for known high-value rare terms.

    **Badges**:
    - Noise filter

    **Links**:
    - [MAPEX: A Multi-Agent Framework for Explainable Keyphrase Extraction](https://arxiv.org/abs/2509.18813)
    - [scikit-learn TfidfVectorizer](https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html)
    - [Elasticsearch Text Analysis](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis.html)
    - [scikit-learn Text Feature Extraction](https://scikit-learn.org/stable/modules/feature_extraction.html#text-feature-extraction)

??? info "`keywords.keywords_refresh_hours` (`KEYWORDS_REFRESH_HOURS`) — Keywords Refresh (Hours)"
    **Category**: `general`

    Controls how often automatic keyword extraction is recomputed from current repository content. Short refresh intervals keep routing aligned with active development, while long intervals reduce compute load and ranking churn. In practice, this should track code-change velocity: fast-moving repos benefit from daily or sub-daily refreshes, while stable repos can refresh weekly. Too-frequent refresh can destabilize relevance if term statistics swing sharply between runs, so pair cadence tuning with quality monitoring. Incremental or diff-aware refresh pipelines usually deliver better freshness-cost balance than full rebuilds.

    **Badges**:
    - Freshness cadence

    **Links**:
    - [DynamicRAG: Dynamic Retrieval-Augmented Generation for Long-Context LLMs](https://arxiv.org/abs/2505.07233)
    - [Qdrant Collections Concepts](https://qdrant.tech/documentation/concepts/collections/)
    - [Weaviate Data Import](https://docs.weaviate.io/weaviate/manage-objects/import)
    - [LlamaIndex Basic Optimization Strategies](https://developers.llamaindex.ai/python/framework/optimizing/basic_strategies/basic_strategies/)
