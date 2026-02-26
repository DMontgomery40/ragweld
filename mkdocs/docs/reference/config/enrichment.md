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
| `enrichment.chunk_summaries_enrich_default` | `CHUNK_SUMMARIES_ENRICH_DEFAULT` | `int` | `1` | ≥ 0, ≤ 1 | Enable chunk_summary enrichment by default |
| `enrichment.chunk_summaries_max` | `CHUNK_SUMMARIES_MAX` | `int` | `100` | ≥ 10, ≤ 1000 | Max chunk_summaries to generate |
| `enrichment.enrich_code_chunks` | `ENRICH_CODE_CHUNKS` | `int` | `1` | ≥ 0, ≤ 1 | Enable chunk enrichment |
| `enrichment.enrich_max_chars` | `ENRICH_MAX_CHARS` | `int` | `1000` | ≥ 100, ≤ 5000 | Max chars for enrichment prompt |
| `enrichment.enrich_min_chars` | `ENRICH_MIN_CHARS` | `int` | `50` | ≥ 10, ≤ 500 | Min chars for enrichment |
| `enrichment.enrich_timeout` | `ENRICH_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Enrichment timeout (seconds) |

### Details (glossary)

??? info "`enrichment.chunk_summaries_enrich_default` (`CHUNK_SUMMARIES_ENRICH_DEFAULT`) — Chunk Summaries Enrich Default"
    **Category**: `general`

    Enable chunk summary enrichment by default when building summaries. When enabled, summaries include enriched metadata (detailed purpose, technical details, domain concepts) using LLM analysis. When disabled, summaries use lightweight extraction only. Enrichment improves quality but increases indexing time and cost.

    Sweet spot: enabled for production systems. Enriched summaries provide better retrieval quality and more detailed metadata. Disable only if indexing speed or cost is a concern, or if lightweight summaries are sufficient.

    • Enabled: Full enrichment with LLM analysis (recommended)
    • Disabled: Lightweight extraction only (faster, lower cost)
    • Effect: Controls whether summaries are enriched with detailed metadata
    • Symptom if disabled: Less detailed summaries, potentially lower retrieval quality

    **Badges**:
    - Enrichment

    **Links**:
    - [Code Enrichment](https://cookbook.openai.com/examples/summarizing_long_documents)
    - [Chunk Summarization](https://vectify.ai/blog/LargeDocumentSummarization)

??? info "`enrichment.chunk_summaries_max` (`CHUNK_SUMMARIES_MAX`) — Max Chunk Summaries"
    **Category**: `general`

    Maximum number of chunk summaries to generate per corpus. Chunk summaries provide structured metadata (purpose, symbols, keywords) for each code chunk, improving retrieval quality. Higher values (200-500) provide more comprehensive coverage but increase indexing time and storage. Lower values (50-100) are faster but may miss important chunks.

    Sweet spot: 100 for balanced coverage. Use 50-75 for large codebases where indexing speed matters. Use 200-300 when comprehensive coverage is critical. Use 500+ only for small, critical codebases.

    • Range: 10-1000 (typical: 50-300)
    • Fast indexing: 50-75 (lower coverage)
    • Balanced: 100 (recommended)
    • Comprehensive: 200-300 (higher coverage)
    • Effect: Higher = more summaries, better coverage, longer indexing
    • Symptom too low: Important chunks missing summaries
    • Symptom too high: Slow indexing, storage overhead

    **Badges**:
    - Indexing

    **Links**:
    - [Chunk Summarization](https://vectify.ai/blog/LargeDocumentSummarization)
    - [Code Analysis](https://llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5)
    - [Document Summarization](https://cookbook.openai.com/examples/summarizing_long_documents)

??? info "`enrichment.enrich_code_chunks` (`ENRICH_CODE_CHUNKS`) — Enrich Code Chunks"
    **Category**: `chunking`

    Enable per-chunk code summarization during indexing. When on, each code chunk gets an AI-generated summary and keywords stored alongside the code. Powers the Cards feature (high-level code summaries) and improves reranking by providing semantic context. Increases indexing time and cost (API calls) but significantly improves retrieval quality for conceptual queries like "where is auth handled?"

    **Badges**:
    - Better retrieval
    - Slower indexing
    - Costs API calls

    **Links**:
    - [Code Summarization](https://en.wikipedia.org/wiki/Automatic_summarization)
