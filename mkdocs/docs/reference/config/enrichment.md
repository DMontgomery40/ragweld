# Config reference: `enrichment`

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
| `enrichment.chunk_summaries_enrich_default` | `CHUNK_SUMMARIES_ENRICH_DEFAULT` | `bool` | `true` | — | Enable chunk_summary enrichment by default |
| `enrichment.chunk_summaries_max` | `CHUNK_SUMMARIES_MAX` | `int` | `100` | ≥ 10, ≤ 1000 | Max chunk_summaries to generate |
| `enrichment.enrich_code_chunks` | `ENRICH_CODE_CHUNKS` | `bool` | `true` | — | Enable chunk enrichment |
| `enrichment.enrich_max_chars` | `ENRICH_MAX_CHARS` | `int` | `1000` | ≥ 100, ≤ 5000 | Max chars for enrichment prompt |
| `enrichment.enrich_min_chars` | `ENRICH_MIN_CHARS` | `int` | `50` | ≥ 10, ≤ 500 | Min chars for enrichment |
| `enrichment.enrich_timeout` | `ENRICH_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Enrichment timeout (seconds) |

### Details (glossary)

??? info "`enrichment.chunk_summaries_enrich_default` (`CHUNK_SUMMARIES_ENRICH_DEFAULT`) — Chunk Summaries Enrich Default"
    **Category**: `general`

    Controls whether chunk summaries are generated with richer, model-assisted metadata by default. Enriched summaries can add intent, entities, API surface hints, and semantic cues that improve retrieval and reranking beyond raw embeddings alone. The trade-off is higher indexing cost and longer build times, especially on large repositories. Enable enrichment when search quality and explainability matter more than ingestion speed, and disable it for rapid iteration pipelines where you need frequent low-cost reindexing.

    **Badges**:
    - Metadata quality

    **Links**:
    - [Code-Craft Summarization (2025)](https://arxiv.org/abs/2504.08975)
    - [OpenAI Summarization Cookbook](https://cookbook.openai.com/examples/summarizing_long_documents)
    - [LlamaIndex Vector Store Index](https://docs.llamaindex.ai/en/stable/module_guides/indexing/vector_store_index/)
    - [LangChain Retrieval Concepts](https://python.langchain.com/docs/concepts/retrieval/)

??? info "`enrichment.chunk_summaries_max` (`CHUNK_SUMMARIES_MAX`) — Max Chunk Summaries"
    **Category**: `general`

    Caps how many chunk summaries are produced for a corpus. This is a budget control over indexing cost, storage footprint, and retrieval metadata coverage. A low cap is fast but can miss important modules, while a high cap improves coverage and long-tail recall at the cost of longer ingestion and larger indexes. Choose this value based on corpus size and criticality, then validate with retrieval benchmarks so the limit reflects actual answer quality rather than arbitrary round numbers.

    **Badges**:
    - Coverage budget

    **Links**:
    - [MIRAGE Benchmark (2025)](https://arxiv.org/abs/2504.17137)
    - [T2-RAGBench (2025)](https://arxiv.org/abs/2506.12071)
    - [OpenAI Summarization Cookbook](https://cookbook.openai.com/examples/summarizing_long_documents)
    - [LlamaIndex Vector Store Index](https://docs.llamaindex.ai/en/stable/module_guides/indexing/vector_store_index/)

??? info "`enrichment.enrich_code_chunks` (`ENRICH_CODE_CHUNKS`) — Enrich Code Chunks"
    **Category**: `chunking`

    When enabled, each code chunk is augmented with model-generated summaries or semantic descriptors during indexing. This often improves conceptual retrieval because rerankers can match intent signals beyond literal token overlap. The tradeoff is extra indexing time, compute cost, and the risk of noisy metadata if prompts or models are weak. Chunk size and model selection both matter: oversized chunks produce vague summaries, while tiny chunks lose architectural context. Evaluate this feature with task-based retrieval metrics to confirm the added metadata improves real query outcomes.

    **Badges**:
    - Slower indexing

    **Links**:
    - [EyeLayer: Human Attention for Code Summarization (arXiv 2026)](https://arxiv.org/abs/2602.22368)
    - [Meta-RAG on Large Codebases Using Code Summarization (arXiv 2025)](https://arxiv.org/abs/2508.02611)
    - [LlamaIndex Repository](https://github.com/run-llama/llama_index)
    - [LangChain Repository](https://github.com/langchain-ai/langchain)
