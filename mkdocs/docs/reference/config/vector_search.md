# Config reference: `vector_search`

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

**Total parameters**: 3

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `vector_search.enabled` | — | `bool` | `true` | — | Enable vector search in tri-brid retrieval |
| `vector_search.similarity_threshold` | — | `float` | `0.0` | ≥ 0.0, ≤ 1.0 | Minimum similarity score threshold (0 = no threshold) |
| `vector_search.top_k` | — | `int` | `50` | ≥ 10, ≤ 200 | Number of results to retrieve from vector search |
