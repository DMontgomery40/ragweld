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

    Additive score bonus applied to results that come from chunk_summary-based retrieval. Chunk summaries are short, structured descriptions of code chunks (purpose, key symbols, keywords) and can match conceptual queries better than raw code.

    This bonus helps chunk_summary hits compete with dense and sparse matches in fusion/reranking. Increase it if summary-based hits are good but rank too low; decrease it if they crowd out precise code hits.

    • Range: 0.0–1.0 (typical: 0.03–0.15)
    • Default: 0.08
    • Higher: stronger intent routing via summaries (risk: generic matches)
    • Lower: rely more on raw chunk text (risk: miss conceptual queries)
    • Interacts with: CHUNK_SUMMARY_SEARCH_ENABLED

    **Badges**:
    - Advanced RAG tuning

    **Links**:
    - [Document Summarization](https://en.wikipedia.org/wiki/Automatic_summarization)

??? info "`scoring.filename_boost_exact` (`FILENAME_BOOST_EXACT`) — Filename Exact Match Multiplier"
    **Category**: `general`

    Score multiplier applied when query terms exactly match a filename or key path segment. This is a deterministic lexical boost layered on top of retrieval/fusion scoring, useful for identifier-heavy code search where exact file names are strong intent signals.

    Increase this when users frequently search by known file names (for example: auth_service.py, package-lock.json). Reduce it if path matches overpower semantically better chunks.

    - High values: prioritize exact path hits
    - Lower values: keep semantic and content relevance dominant

??? info "`scoring.filename_boost_partial` (`FILENAME_BOOST_PARTIAL`) — Path Component Partial Match Multiplier"
    **Category**: `general`

    Score multiplier when any path component partially matches query terms (directory or filename fragment). Helps queries like "auth" prioritize auth-related files. Default: 1.2. Range: 1.0-3.0. Keep this lower than FILENAME_BOOST_EXACT.

??? info "`scoring.path_boosts` (`PATH_BOOSTS`) — Path Boosts"
    **Category**: `retrieval`

    Comma-separated path prefixes that receive additional scoring preference during ranking (for example: /gui,/server,/indexer,/retrieval). This is a deterministic bias layer for emphasizing known important code areas.

    Use this when organizational structure is meaningful to query intent. Keep boosts narrow and intentional; overly broad prefixes can distort relevance and hide better matches outside favored paths.

    - Good for: domain-priority routing, mono-repo subarea focus
    - Revisit after major repo restructuring

??? info "`scoring.vendor_mode` (`VENDOR_MODE`) — Vendor Mode"
    **Category**: `general`

    Controls scoring preference for your code vs third-party library code during reranking. "prefer_first_party" (recommended) boosts your app code (+0.06) and penalizes node_modules/vendor libs (-0.08) - best for understanding YOUR codebase. "prefer_vendor" does the opposite - useful when debugging library internals or learning from open-source code. Most users want prefer_first_party.

    **Badges**:
    - Code priority

    **Links**:
    - [First-Party vs Third-Party](https://en.wikipedia.org/wiki/First-party_and_third-party_sources)
