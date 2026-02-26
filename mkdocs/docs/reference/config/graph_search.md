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

**Total parameters**: 9

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `graph_search.chunk_entity_expansion_enabled` | — | `bool` | `true` | — | When mode='chunk', expand from seed chunks via Entity graph (IN_CHUNK links) to find related chunks |
| `graph_search.chunk_entity_expansion_weight` | — | `float` | `0.8` | ≥ 0.0, ≤ 1.0 | Blend weight for entity-expansion scores relative to seed chunk scores (mode='chunk') |
| `graph_search.chunk_neighbor_window` | — | `int` | `1` | ≥ 0, ≤ 10 | When mode='chunk', include up to N adjacent chunks (NEXT_CHUNK) around each seed hit |
| `graph_search.chunk_seed_overfetch_multiplier` | — | `int` | `10` | ≥ 1, ≤ 50 | When mode='chunk' and Neo4j uses a shared database, overfetch seed hits before filtering by corpus_id |
| `graph_search.enabled` | — | `bool` | `true` | — | Enable graph search in tri-brid retrieval |
| `graph_search.include_communities` | — | `bool` | `true` | — | Include community-based expansion in graph search |
| `graph_search.max_hops` | — | `int` | `2` | ≥ 1, ≤ 5 | Maximum graph traversal hops |
| `graph_search.mode` | — | `Literal["chunk", "entity"]` | `"chunk"` | allowed="chunk", "entity" | Graph retrieval mode. 'chunk' uses lexical chunk nodes + Neo4j vector index; 'entity' uses the legacy code-entity graph. |
| `graph_search.top_k` | — | `int` | `30` | ≥ 5, ≤ 100 | Number of results to retrieve from graph search |
