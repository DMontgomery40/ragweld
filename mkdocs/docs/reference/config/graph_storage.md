# Config reference: `graph_storage`

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

**Total parameters**: 13

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `graph_storage.community_algorithm` | `GRAPH_COMMUNITY_ALGORITHM` | `Literal["louvain", "label_propagation"]` | `"louvain"` | allowed="louvain", "label_propagation" | Community detection algorithm |
| `graph_storage.entity_types` | — | `list[str]` | `["function", "class", "module", "variable", "import"]` | — | Entity types to extract and store in graph |
| `graph_storage.graph_search_top_k` | `GRAPH_SEARCH_TOP_K` | `int` | `30` | ≥ 5, ≤ 100 | Number of results from graph traversal |
| `graph_storage.include_communities` | `GRAPH_INCLUDE_COMMUNITIES` | `bool` | `true` | — | Include community detection in graph analysis |
| `graph_storage.max_hops` | `GRAPH_MAX_HOPS` | `int` | `2` | ≥ 1, ≤ 5 | Maximum traversal hops for graph search |
| `graph_storage.neo4j_auto_create_databases` | — | `bool` | `true` | — | Automatically create per-corpus Neo4j databases when missing (Enterprise). |
| `graph_storage.neo4j_database` | `NEO4J_DATABASE` | `str` | `"neo4j"` | — | Neo4j database name |
| `graph_storage.neo4j_database_mode` | — | `Literal["shared", "per_corpus"]` | `"shared"` | allowed="shared", "per_corpus" | Database isolation mode: 'shared' uses a single Neo4j database (Community-compatible), 'per_corpus' uses a separate Neo4j database per corpus (Enterprise multi-database). |
| `graph_storage.neo4j_database_prefix` | — | `str` | `"tribrid_"` | — | Prefix for per-corpus Neo4j database names when neo4j_database_mode='per_corpus'. |
| `graph_storage.neo4j_password` | `NEO4J_PASSWORD` | `str` | `""` | — | Neo4j password (defaults to NEO4J_PASSWORD env var when unset) |
| `graph_storage.neo4j_uri` | `NEO4J_URI` | `str` | `"bolt://localhost:7687"` | — | Neo4j connection URI (bolt:// or neo4j://) |
| `graph_storage.neo4j_user` | `NEO4J_USER` | `str` | `"neo4j"` | — | Neo4j username |
| `graph_storage.relationship_types` | — | `list[str]` | `["calls", "imports", "inherits", "contains", "references"]` | — | Relationship types to extract |

### Details (glossary)

??? info "`graph_storage.graph_search_top_k` (`GRAPH_SEARCH_TOP_K`) — Graph Search Top-K"
    **Category**: `general`

    Number of candidate results to retrieve from Neo4j graph search before fusion. Higher values (40-100) improve recall for graph-based relationships but increase query latency. Lower values (15-30) are faster but may miss relevant connections. Must be >= FINAL_K. Recommended: 30 for balanced performance.

    Sweet spot: 30 for production systems. Use 40-50 when graph relationships are critical (e.g., finding code that calls or imports specific functions). Use 15-20 for cost-sensitive scenarios or when graph indexing is sparse.

    • Range: 5-100 (typical: 20-50)
    • Balanced: 30 (recommended)
    • High recall: 40-50 (relationship-heavy queries)
    • Cost-sensitive: 15-20 (faster, lower cost)
    • Effect: Higher = more graph candidates, better recall, higher latency
    • Symptom too low: Relevant graph connections missed
    • Symptom too high: Slower queries, diminishing returns

    **Badges**:
    - Affects latency
    - Graph relationships

    **Links**:
    - [Neo4j GraphRAG](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Graph Traversal](https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package)
    - [Top-K Retrieval](https://en.wikipedia.org/wiki/Nearest_neighbor_search#k-nearest_neighbors)

??? info "`graph_storage.include_communities` (`GRAPH_INCLUDE_COMMUNITIES`) — Include Communities"
    **Category**: `general`

    Enable community-based expansion in graph search. When enabled, the system uses community detection algorithms (e.g., Louvain) to identify clusters of related nodes and expands search to include entire communities. This improves recall for related concepts but may introduce noise. Recommended: enabled for entity mode, optional for chunk mode.

    Sweet spot: enabled for entity mode, disabled for chunk mode. Community expansion works best with entity-based graphs where structural clusters are meaningful. For chunk mode, neighbor expansion is usually sufficient.

    • Enabled: Community-based expansion, better recall, may introduce noise
    • Disabled: Direct neighbor expansion only, more focused results
    • Effect: Controls whether community detection influences traversal
    • Symptom if disabled: Related concepts in same community may be missed

    **Badges**:
    - Advanced

    **Links**:
    - [Louvain Algorithm](https://neo4j.com/docs/graph-data-science/current/algorithms/louvain)
    - [Community Detection](https://neo4j.com/docs/graph-data-science/current/algorithms/community/)
    - [Community Detection Algorithms](https://en.wikipedia.org/wiki/Community_structure)

??? info "`graph_storage.max_hops` (`GRAPH_MAX_HOPS`) — Graph Max Hops"
    **Category**: `general`

    Maximum number of graph traversal hops from seed nodes. Each hop expands the search to connected nodes (chunks, entities, relationships). Higher values (3-5) find more distant relationships but increase query latency and may introduce noise. Lower values (1-2) are faster and more focused. Recommended: 2 for balanced performance.

    Sweet spot: 2 for production systems. Use 1 for fast, focused traversal (immediate neighbors only). Use 3-4 when you need to find distant relationships or explore deep code structures. Use 5 only for exploratory queries where completeness matters more than speed.

    • Range: 1-5 (typical: 1-3)
    • Focused: 1 (immediate neighbors only)
    • Balanced: 2 (recommended)
    • Deep exploration: 3-4 (distant relationships)
    • Effect: Higher = more relationships explored, better recall, higher latency
    • Symptom too low: Relevant connections missed
    • Symptom too high: Slower queries, noise introduced

    **Badges**:
    - Performance

    **Links**:
    - [Neo4j Graph Traversal](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Graph Traversal Depth](https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package)
    - [Graph Algorithms](https://en.wikipedia.org/wiki/Graph_traversal)

??? info "`graph_storage.neo4j_uri` (`NEO4J_URI`) — Neo4j Connection URI"
    **Category**: `infrastructure`

    Connection URI for Neo4j graph database. Used for entity relationships, graph traversal, and community detection in tri-brid search. Format: bolt://host:7687 or neo4j://host:7687. Enables graph-based retrieval for code navigation.
