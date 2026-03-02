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

**Total parameters**: 14

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
| `graph_storage.neo4j_vector_query_mode` | `NEO4J_VECTOR_QUERY_MODE` | `Literal["auto", "procedure", "search"]` | `"auto"` | allowed="auto", "procedure", "search" | Neo4j chunk-vector query mode. 'auto' prefers runtime-safe defaults and only uses SEARCH where supported. |
| `graph_storage.relationship_types` | — | `list[str]` | `["calls", "imports", "inherits", "contains", "references"]` | — | Relationship types to extract |

### Details (glossary)

??? info "`graph_storage.graph_search_top_k` (`GRAPH_SEARCH_TOP_K`) — Graph Search Top-K"
    **Category**: `general`

    GRAPH_SEARCH_TOP_K controls how many graph candidates are kept before downstream fusion and reranking. Increasing top-k usually improves recall because more potentially useful graph evidence survives early pruning, but it also raises latency and can inflate reranker and generation token costs. If top-k is too small, graph retrieval appears weak even when the graph is high quality because relevant nodes are dropped prematurely. If it is too large, weaker graph neighbors can crowd the context budget and reduce final answer precision. Tune this setting with both retrieval metrics and end-to-end answer quality, and keep it aligned with final context assembly limits.

    **Badges**:
    - Top-K Control

    **Links**:
    - [Neo4j GraphRAG Python User Guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Neo4j Vector Indexes](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/)
    - [Elasticsearch Similarity and Ranking](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-modules-similarity.html)
    - [LightRetriever (2025): Faster Query Inference](https://arxiv.org/abs/2505.12260)

??? info "`graph_storage.include_communities` (`GRAPH_INCLUDE_COMMUNITIES`) — Include Communities"
    **Category**: `general`

    GRAPH_INCLUDE_COMMUNITIES enables expansion across precomputed graph communities instead of only direct neighbors. This can surface related components that belong to the same subsystem even when explicit edges between the exact seed nodes are weak or missing. It is most useful for architecture, ownership, and impact-analysis questions where thematic grouping matters. The tradeoff is broader recall with higher risk of topic drift, so community expansion should usually be combined with conservative hop limits and robust reranking. Community quality depends heavily on graph construction and algorithm settings, so treat this as a quality-dependent feature flag rather than always-on behavior.

    **Badges**:
    - Advanced Graph

    **Links**:
    - [Neo4j Louvain Algorithm](https://neo4j.com/docs/graph-data-science/current/algorithms/louvain/)
    - [Neo4j Leiden Algorithm](https://neo4j.com/docs/graph-data-science/current/algorithms/leiden/)
    - [Neo4j GraphRAG Python User Guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [TagRAG (2026): Tag-Guided Hierarchical GraphRAG](https://arxiv.org/abs/2601.05254)

??? info "`graph_storage.max_hops` (`GRAPH_MAX_HOPS`) — Graph Max Hops"
    **Category**: `general`

    GRAPH_MAX_HOPS caps traversal depth from each seed node in graph retrieval. One hop focuses on direct relationships, two hops often captures practical cross-file links, and larger values rapidly increase branching factor and latency. Higher hops can help for dependency-chain and architecture questions, but they also raise the chance of pulling weakly related evidence into the fusion stage. In most RAG/search deployments, this is one of the highest-impact latency controls because frontier size grows nonlinearly with graph degree. Tune with p95 latency and grounded answer metrics together, since deeper traversal can improve recall while reducing precision.

    **Badges**:
    - Latency-Recall

    **Links**:
    - [Cypher Variable-Length Patterns](https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-patterns/)
    - [Neo4j GraphRAG Python User Guide](https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html)
    - [Neo4j Cypher Query Tuning](https://neo4j.com/docs/cypher-manual/current/query-tuning/)
    - [TagRAG (2026): Tag-Guided Hierarchical GraphRAG](https://arxiv.org/abs/2601.05254)

??? info "`graph_storage.neo4j_uri` (`NEO4J_URI`) — Neo4j Connection URI"
    **Category**: `infrastructure`

    Neo4j URI config determines how clients connect, route, and secure graph queries in retrieval workflows. Use `neo4j://` for routed cluster-aware connections and `bolt://` for direct connections when routing is not needed. Misconfigured schemes can produce subtle behavior differences in failover, read routing, and TLS handling that only appear under load. Treat this value as infrastructure configuration: validate connectivity at startup, enforce encrypted transport in shared environments, and keep URI/auth settings externalized from source code.

    **Links**:
    - [SCOUT-RAG: Dynamic Graph Retrieval-Augmented Generation (arXiv 2026)](https://arxiv.org/abs/2602.08400)
    - [Neo4j Browser DBMS Connection](https://neo4j.com/docs/browser-manual/current/operations/dbms-connection/)
    - [Neo4j Python Driver Advanced Connection](https://neo4j.com/docs/python-manual/current/connect-advanced/)
    - [Neo4j GraphRAG](https://neo4j.com/labs/genai-ecosystem/graphrag/)
