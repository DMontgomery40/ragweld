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

**Total parameters**: 11

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
| `graph_indexing.enabled` | — | `bool` | `true` | — | Enable graph building during indexing (Neo4j) |
| `graph_indexing.semantic_kg_llm_model` | — | `str` | `""` | — | Optional LiteLLM alias for GraphRAG semantic extraction; empty uses the gateway default |
| `graph_indexing.semantic_kg_llm_timeout_s` | — | `int` | `90` | ≥ 5, ≤ 600 | Timeout (seconds) for semantic KG LLM extraction per chunk |
| `graph_indexing.semantic_kg_max_chunks` | — | `int` | `40000` | ≥ 1, ≤ 100000 | Maximum eligible chunks for a semantic GraphRAG run. Runs above this ceiling fail before promotion; the corpus is never sliced into a partial graph. |
| `graph_indexing.semantic_kg_reasoning_effort` | — | `Literal["minimal", "low", "medium", "high", "xhigh"]` | `"medium"` | allowed="minimal", "low", "medium", "high", "xhigh" | Reasoning effort for semantic KG extraction when using OpenAI Responses-compatible models. |
