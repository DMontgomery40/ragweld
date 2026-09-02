# Config reference: `graph_search`

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
| `graph_search.chunk_neighbor_window` | — | `int` | `1` | ≥ 0, ≤ 10 | Include up to N adjacent chunks (NEXT_CHUNK) around relationship hits |
| `graph_search.enabled` | — | `bool` | `true` | — | Enable graph search in tri-brid retrieval |
| `graph_search.include_communities` | — | `bool` | `true` | — | Include community-based expansion in graph search |
| `graph_search.max_hops` | — | `int` | `2` | ≥ 1, ≤ 5 | Maximum graph traversal hops |
| `graph_search.max_related_entities_per_seed` | — | `int` | `50` | ≥ 1, ≤ 1000 | Maximum related entities kept per seed entity during graph traversal, nearest first then most connected. Bounds how far a hub entity can expand. |
| `graph_search.top_k` | — | `int` | `30` | ≥ 5, ≤ 100 | Number of results to retrieve from graph search |
