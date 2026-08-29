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

**Total parameters**: 28

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `graph_indexing.ast_calls_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST call relationships (function->callee). |
| `graph_indexing.ast_contains_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST containment relationships (module->class/function, class->method). |
| `graph_indexing.ast_imports_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST import relationships (module->imported_module). |
| `graph_indexing.ast_inherits_weight` | — | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Edge weight for AST inheritance relationships (class->base). |
| `graph_indexing.build_code_graph` | — | `bool` | `false` | — | Build an AST code graph during indexing: module, class and function entities with contains/inherits/imports/calls relationships (tree-sitter; Python, TypeScript, JavaScript), each linked to the chunk that defines it |
| `graph_indexing.build_lexical_graph` | — | `bool` | `true` | — | Build lexical graph (Document/Chunk nodes + NEXT_CHUNK relationships) |
| `graph_indexing.chunk_embedding_property` | — | `str` | `"embedding"` | — | Chunk node property that stores the embedding vector |
| `graph_indexing.chunk_vector_index_name` | — | `str` | `"tribrid_chunk_embeddings"` | — | Neo4j vector index name for Chunk embeddings (mode='chunk') |
| `graph_indexing.enabled` | — | `bool` | `true` | — | Enable graph building during indexing (Neo4j) |
| `graph_indexing.semantic_kg_allowed_entity_types` | — | `list[Literal["person", "org", "location", "event", "concept"]]` | `["person", "org", "location", "event", "concept"]` | — | Allowed semantic KG entity types produced by extraction. |
| `graph_indexing.semantic_kg_allowed_relation_types` | — | `list[Literal["associated_with", "met_with", "communicated_with", "works_for", "member_of", "founded", "owns", "funded", "participated_in", "located_in", "references", "related_to"]]` | `["associated_with", "met_with", "communicated_with", "works_for", "member_of", "founded", "owns", "funded", "participated_in", "located_in", "references", "related_to"]` | — | Allowed semantic KG relationship types produced by extraction. |
| `graph_indexing.semantic_kg_enabled` | — | `bool` | `false` | — | Build an official Neo4j GraphRAG semantic graph with typed entities and relationships linked to chunks during indexing |
| `graph_indexing.semantic_kg_llm_model` | — | `str` | `""` | — | Optional LiteLLM alias for GraphRAG semantic extraction; empty uses the gateway default |
| `graph_indexing.semantic_kg_llm_timeout_s` | — | `int` | `30` | ≥ 5, ≤ 120 | Timeout (seconds) for semantic KG LLM extraction per chunk |
| `graph_indexing.semantic_kg_max_chunks` | — | `int` | `40000` | ≥ 0, ≤ 100000 | Maximum chunks to process for semantic KG extraction per indexing run (0 = disabled) |
| `graph_indexing.semantic_kg_max_concepts_per_chunk` | — | `int` | `8` | ≥ 0, ≤ 50 | Maximum semantic concepts to extract per chunk |
| `graph_indexing.semantic_kg_max_relations_per_chunk` | — | `int` | `12` | ≥ 0, ≤ 200 | Maximum semantic relations to retain per chunk during GraphRAG extraction |
| `graph_indexing.semantic_kg_min_concept_len` | — | `int` | `4` | ≥ 3, ≤ 20 | Minimum length for semantic concept tokens |
| `graph_indexing.semantic_kg_mode` | — | `Literal["heuristic", "llm"]` | `"llm"` | allowed="heuristic", "llm" | Semantic KG extraction mode. This branch targets the official Neo4j GraphRAG LLM path; 'heuristic' is a stale legacy setting. |
| `graph_indexing.semantic_kg_reasoning_effort` | — | `Literal["minimal", "low", "medium", "high", "xhigh"]` | `"medium"` | allowed="minimal", "low", "medium", "high", "xhigh" | Reasoning effort for semantic KG extraction when using OpenAI Responses-compatible models. |
| `graph_indexing.semantic_kg_relation_weight_heuristic` | — | `float` | `0.5` | ≥ 0.0, ≤ 1.0 | Edge weight for semantic concept relations in heuristic fallback mode. |
| `graph_indexing.semantic_kg_relation_weight_llm` | — | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Edge weight for semantic concept relations in LLM mode. |
| `graph_indexing.semantic_kg_require_llm_success` | — | `bool` | `false` | — | When true, fail the indexing run if GraphRAG semantic extraction fails for a chunk. |
| `graph_indexing.semantic_kg_typed_entities_enabled` | — | `bool` | `true` | — | When true, semantic KG extraction preserves typed entities (person, org, location, event, concept). |
| `graph_indexing.store_chunk_embeddings` | — | `bool` | `true` | — | Store chunk embeddings on Chunk nodes for Neo4j vector search (requires dense embeddings) |
| `graph_indexing.vector_index_online_timeout_s` | — | `float` | `60.0` | ≥ 1.0, ≤ 600.0 | Timeout waiting for Neo4j vector index ONLINE (seconds) |
| `graph_indexing.vector_similarity_function` | — | `Literal["cosine", "euclidean"]` | `"cosine"` | allowed="cosine", "euclidean" | Neo4j vector similarity function |
| `graph_indexing.wait_vector_index_online` | — | `bool` | `true` | — | Wait for the Neo4j vector index to come ONLINE after (re)creating it |
