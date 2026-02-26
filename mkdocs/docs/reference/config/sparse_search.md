# Config reference: `sparse_search`

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

**Total parameters**: 11

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `sparse_search.bm25_b` | — | `float` | `0.4` | ≥ 0.0, ≤ 1.0 | BM25 length normalization (0 = no penalty, 1 = full penalty) |
| `sparse_search.bm25_k1` | — | `float` | `1.2` | ≥ 0.5, ≤ 3.0 | BM25 term frequency saturation (higher = more weight to term frequency) |
| `sparse_search.enabled` | — | `bool` | `true` | — | Enable sparse BM25 search in tri-brid retrieval |
| `sparse_search.engine` | — | `Literal["postgres_fts", "pg_search_bm25"]` | `"postgres_fts"` | allowed="postgres_fts", "pg_search_bm25" | Sparse retrieval engine. 'postgres_fts' uses built-in FTS; 'pg_search_bm25' uses ParadeDB pg_search. |
| `sparse_search.file_path_fallback` | — | `bool` | `true` | — | If sparse retrieval returns empty, run a file_path-based fallback ranking (best-effort). |
| `sparse_search.file_path_max_terms` | — | `int` | `6` | ≥ 1, ≤ 32 | Max extracted query terms used for file_path fallback. |
| `sparse_search.highlight` | — | `bool` | `false` | — | Enable sparse highlight payloads when supported (UI later). |
| `sparse_search.query_mode` | — | `Literal["plain", "phrase", "boolean"]` | `"plain"` | allowed="plain", "phrase", "boolean" | How to interpret the sparse query string. |
| `sparse_search.relax_max_terms` | — | `int` | `8` | ≥ 1, ≤ 32 | Max extracted query terms used for relaxed sparse fallback. |
| `sparse_search.relax_on_empty` | — | `bool` | `true` | — | If sparse retrieval returns empty, retry with a relaxed OR-style query (best-effort). |
| `sparse_search.top_k` | — | `int` | `50` | ≥ 10, ≤ 200 | Number of results to retrieve from sparse search |
