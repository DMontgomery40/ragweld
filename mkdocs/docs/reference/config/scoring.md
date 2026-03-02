# Config reference: `scoring`

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
| `scoring.chunk_summary_bonus` | `CHUNK_SUMMARY_BONUS` | `float` | `0.08` | ≥ 0.0, ≤ 1.0 | Bonus score for chunks matched via chunk_summary-based retrieval |
| `scoring.filename_boost_exact` | `FILENAME_BOOST_EXACT` | `float` | `1.5` | ≥ 1.0, ≤ 5.0 | Score multiplier when filename exactly matches query terms |
| `scoring.filename_boost_partial` | `FILENAME_BOOST_PARTIAL` | `float` | `1.2` | ≥ 1.0, ≤ 3.0 | Score multiplier when path components match query terms |
| `scoring.path_boosts` | `PATH_BOOSTS` | `str` | `"/gui,/server,/indexer,/retrieval"` | — | Comma-separated path prefixes to boost |
| `scoring.vendor_mode` | `VENDOR_MODE` | `str` | `"prefer_first_party"` | pattern=^(prefer_first_party\|prefer_vendor\|neutral)$ | Vendor code preference |

### Details (glossary)

??? info "`scoring.chunk_summary_bonus` (`CHUNK_SUMMARY_BONUS`) — Chunk Summary Bonus"
    **Category**: `retrieval`

    Additive weight applied after score fusion when a hit came from chunk-summary retrieval instead of raw chunk text. In practice this controls whether conceptual matches such as intent, behavior, or API purpose can compete with exact-token matches from code. Raise it when summaries are high quality but consistently rank below noisy lexical matches; lower it when vague summaries outrank precise chunks and hurt answer grounding. Tune this together with your fusion method and evaluation set, because the same numeric bonus has very different effects depending on score normalization and corpus size.

    **Badges**:
    - Advanced tuning

    **Links**:
    - [cAST: Structural chunking for code RAG (arXiv 2025)](https://arxiv.org/abs/2506.15655)
    - [LangChain MultiVector Retriever](https://python.langchain.com/docs/how_to/multi_vector/)
    - [Elasticsearch Reciprocal Rank Fusion](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Weaviate hybrid retrieval](https://docs.weaviate.io/weaviate/search/hybrid)

??? info "`scoring.filename_boost_exact` (`FILENAME_BOOST_EXACT`) — Filename Exact Match Multiplier"
    **Category**: `general`

    Applies a multiplier when query tokens exactly match a filename or full path component, which is especially effective for identifier-driven code search. Exact filename intent often indicates the user already knows the artifact, so this feature can sharply improve rank quality for navigational queries. Set the multiplier high enough to surface true exact hits, but not so high that semantic relevance is overridden for exploratory questions. Validate with a mixed benchmark containing both known-file and concept-search tasks.

    **Badges**:
    - Lexical precision boost

    **Links**:
    - [Exp4Fuse Rank Fusion (arXiv)](https://arxiv.org/abs/2506.04760)
    - [Elasticsearch Term Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-term-query.html)
    - [Elasticsearch Multi Match Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-multi-match-query.html)
    - [Lucene BM25Similarity](https://lucene.apache.org/core/9_12_0/core/org/apache/lucene/search/similarities/BM25Similarity.html)

??? info "`scoring.filename_boost_partial` (`FILENAME_BOOST_PARTIAL`) — Path Component Partial Match Multiplier"
    **Category**: `general`

    Applies a weaker multiplier for partial path or filename matches, helping fragment queries like auth or billing surface relevant areas of the codebase. Because substring matches are noisier than exact matches, this value should stay below exact filename boost and be tested against false-positive-heavy queries. Token boundary handling and minimum match length are important to avoid boosting accidental overlaps. This parameter is most effective when combined with semantic and sparse retrieval rather than used alone.

    **Badges**:
    - Lexical recall boost

    **Links**:
    - [Exp4Fuse Rank Fusion (arXiv)](https://arxiv.org/abs/2506.04760)
    - [Elasticsearch Bool Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-bool-query.html)
    - [Elasticsearch Dis Max Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-dis-max-query.html)
    - [PostgreSQL Text Search Controls](https://www.postgresql.org/docs/current/textsearch-controls.html)

??? info "`scoring.path_boosts` (`PATH_BOOSTS`) — Path Boosts"
    **Category**: `retrieval`

    Adds deterministic ranking bonuses for files whose paths match configured prefixes (for example `/api`, `/retrieval`, or `/infra`). This is not a filter; candidates outside boosted paths can still win, but matching paths start with an intentional prior that reflects project structure and ownership patterns. In practice, path boosts are most useful when repositories contain large amounts of generated code, vendor trees, or historical directories that are semantically similar but operationally lower value. Tune this with offline evaluation and query logs: too much boost can hide genuinely relevant files, while too little leaves high-signal code regions under-ranked.

    **Links**:
    - [RANGER: Repository-Level Retrieval-Augmented Generation for Code Completion (arXiv 2025)](https://arxiv.org/abs/2509.25257)
    - [Elasticsearch Boosting Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-boosting-query.html)
    - [Elasticsearch Function Score Query](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-function-score-query.html)
    - [Vespa Ranking Framework](https://docs.vespa.ai/en/ranking.html)

??? info "`scoring.vendor_mode` (`VENDOR_MODE`) — Vendor Mode"
    **Category**: `general`

    Controls whether ranking heuristics prioritize first-party project code or third-party/vendor dependencies when scores are close. In large repos, vendor and framework code can dominate candidate lists simply because it is abundant; this setting counterbalances that effect for tasks where users primarily want answers about their own application logic. Prefer first-party mode for product debugging, architecture discovery, and onboarding into your codebase. Prefer vendor mode only when your query intent is explicitly about dependency internals. Evaluate with intent-labeled queries to confirm the mode aligns with expected navigation behavior.

    **Badges**:
    - Code priority

    **Links**:
    - [SaraCoder: Repository-Aware Code Retrieval at Scale (arXiv 2025)](https://arxiv.org/abs/2508.10068)
    - [Sourcegraph Code Search Documentation](https://sourcegraph.com/docs/code_search)
    - [GitHub Code Search Overview](https://docs.github.com/en/search-github/github-code-search/about-github-code-search)
    - [gitignore Patterns (vendor/exclusion hygiene)](https://git-scm.com/docs/gitignore)
