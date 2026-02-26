# Config reference: `graph_indexing`

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

**Total parameters**: 22

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `graph_indexing.ast_calls_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST call relationships (function->callee). |
| `graph_indexing.ast_contains_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST containment relationships (module->class/function, class->method). |
| `graph_indexing.ast_imports_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST import relationships (module->imported_module). |
| `graph_indexing.ast_inherits_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST inheritance relationships (class->base). |
| `graph_indexing.build_lexical_graph` | — | `bool` | `true` | — | Build lexical graph (Document/Chunk nodes + NEXT_CHUNK relationships) |
| `graph_indexing.chunk_embedding_property` | — | `str` | `"embedding"` | — | Chunk node property that stores the embedding vector |
| `graph_indexing.chunk_vector_index_name` | — | `str` | `"tribrid_chunk_embeddings"` | — | Neo4j vector index name for Chunk embeddings (mode='chunk') |
| `graph_indexing.enabled` | — | `bool` | `true` | — | Enable graph building during indexing (Neo4j) |
| `graph_indexing.semantic_kg_enabled` | — | `bool` | `false` | — | Build semantic knowledge graph (concept entities + relations) linked to chunks during indexing |
| `graph_indexing.semantic_kg_llm_model` | — | `str` | `""` | — | LLM model name for semantic KG extraction when semantic_kg_mode='llm' (empty = use generation.enrich_model) |
| `graph_indexing.semantic_kg_llm_timeout_s` | — | `int` | `30` | ≥ 5, ≤ 120 | Timeout (seconds) for semantic KG LLM extraction per chunk |
| `graph_indexing.semantic_kg_max_chunks` | — | `int` | `200` | ≥ 0, ≤ 100000 | Maximum chunks to process for semantic KG extraction per indexing run (0 = disabled) |
| `graph_indexing.semantic_kg_max_concepts_per_chunk` | — | `int` | `8` | ≥ 0, ≤ 50 | Maximum semantic concepts to extract per chunk |
| `graph_indexing.semantic_kg_max_relations_per_chunk` | — | `int` | `12` | ≥ 0, ≤ 200 | Maximum semantic relations to create per chunk (heuristic mode) |
| `graph_indexing.semantic_kg_min_concept_len` | — | `int` | `4` | ≥ 3, ≤ 20 | Minimum length for semantic concept tokens |
| `graph_indexing.semantic_kg_mode` | — | `Literal["heuristic", "llm"]` | `"heuristic"` | allowed="heuristic", "llm" | Semantic KG extraction mode. 'heuristic' is deterministic and test-friendly; 'llm' uses an LLM to extract entities + relations. |
| `graph_indexing.semantic_kg_relation_weight_heuristic` | — | `float` | `0.5` | ≥ 0.0, ≤ 1.0 | Edge weight for semantic concept relations in heuristic fallback mode. |
| `graph_indexing.semantic_kg_relation_weight_llm` | — | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Edge weight for semantic concept relations in LLM mode. |
| `graph_indexing.store_chunk_embeddings` | — | `bool` | `true` | — | Store chunk embeddings on Chunk nodes for Neo4j vector search (requires dense embeddings) |
| `graph_indexing.vector_index_online_timeout_s` | — | `float` | `60.0` | ≥ 1.0, ≤ 600.0 | Timeout waiting for Neo4j vector index ONLINE (seconds) |
| `graph_indexing.vector_similarity_function` | — | `Literal["cosine", "euclidean"]` | `"cosine"` | allowed="cosine", "euclidean" | Neo4j vector similarity function |
| `graph_indexing.wait_vector_index_online` | — | `bool` | `true` | — | Wait for the Neo4j vector index to come ONLINE after (re)creating it |
