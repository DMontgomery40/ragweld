# Config reference: `chunking`

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

**Total parameters**: 18

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chunking.ast_overlap_lines` | `AST_OVERLAP_LINES` | `int` | `20` | ≥ 0, ≤ 100 | Overlap lines for AST chunking |
| `chunking.chunk_overlap` | `CHUNK_OVERLAP` | `int` | `200` | ≥ 0, ≤ 1000 | Overlap between chunks |
| `chunking.chunk_size` | `CHUNK_SIZE` | `int` | `1000` | ≥ 200, ≤ 5000 | Target chunk size (non-whitespace chars) |
| `chunking.chunking_strategy` | `CHUNKING_STRATEGY` | `str` | `"ast"` | pattern=^(ast\|hybrid\|greedy\|fixed_chars\|fixed_tokens\|recursive\|markdown\|sentence\|qa_blocks)$ | Chunking strategy (document + code) |
| `chunking.emit_chunk_ordinal` | — | `bool` | `true` | — | Emit chunk ordinal metadata for neighbor-window retrieval. |
| `chunking.emit_parent_doc_id` | — | `bool` | `true` | — | Emit parent document id metadata for neighbor-window retrieval. |
| `chunking.greedy_fallback_target` | `GREEDY_FALLBACK_TARGET` | `int` | `800` | ≥ 200, ≤ 2000 | Target size for greedy chunking |
| `chunking.markdown_include_code_fences` | — | `bool` | `true` | — | Whether to include fenced code blocks in markdown sections. |
| `chunking.markdown_max_heading_level` | — | `int` | `4` | ≥ 1, ≤ 6 | Max heading level to split on for markdown chunking. |
| `chunking.max_chunk_tokens` | `MAX_CHUNK_TOKENS` | `int` | `8000` | ≥ 100, ≤ 32000 | Maximum tokens per chunk - chunks exceeding this are split recursively |
| `chunking.max_indexable_file_size` | `MAX_INDEXABLE_FILE_SIZE` | `int` | `250000000` | ≥ 10000, ≤ 2000000000 | Max file size to index (bytes) - files larger than this are skipped |
| `chunking.min_chunk_chars` | `MIN_CHUNK_CHARS` | `int` | `50` | ≥ 10, ≤ 500 | Minimum chunk size |
| `chunking.overlap_tokens` | — | `int` | `64` | ≥ 0, ≤ 2048 | Token overlap between chunks (token-based strategies) |
| `chunking.preserve_imports` | `PRESERVE_IMPORTS` | `bool` | `true` | — | Include imports in chunks |
| `chunking.recursive_max_depth` | — | `int` | `10` | ≥ 1, ≤ 50 | Max recursion depth for recursive chunking. |
| `chunking.separator_keep` | — | `Literal["none", "prefix", "suffix"]` | `"suffix"` | allowed="none", "prefix", "suffix" | Whether to keep separators when splitting (recursive strategy). |
| `chunking.separators` | — | `list[str]` | `["\n\n", "\n", ". ", " ", ""]` | — | Separators for recursive chunking, in priority order. |
| `chunking.target_tokens` | — | `int` | `512` | ≥ 64, ≤ 8192 | Target tokens per chunk (token-based strategies) |

### Details (glossary)

??? info "`chunking.ast_overlap_lines` (`AST_OVERLAP_LINES`) — AST Overlap Lines"
    **Category**: `chunking`

    AST_OVERLAP_LINES sets how many source lines are repeated between adjacent syntax-aware chunks when code is segmented by AST boundaries. Overlap preserves boundary context such as imports, signatures, decorators, and class state that might otherwise be split and become harder to retrieve. Too little overlap reduces recall on cross-boundary queries; too much overlap bloats the index, increases near-duplicates, and can bias scoring toward repeated context. Start with a small overlap and tune using real code-search prompts that depend on boundary continuity, then track recall improvement versus index growth and latency.

    **Badges**:
    - Chunking

    **Links**:
    - [cAST: AST-Based Structural Chunking for Code RAG (arXiv)](https://arxiv.org/abs/2506.15655)
    - [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/)
    - [LangChain Text Splitters](https://python.langchain.com/docs/concepts/text_splitters/)
    - [Cohere Chunking Strategies](https://docs.cohere.com/page/chunking-strategies)

??? info "`chunking.chunk_overlap` (`CHUNK_OVERLAP`) — Chunk Overlap"
    **Category**: `chunking`

    Specifies how much content is repeated between adjacent chunks. Overlap reduces boundary loss by ensuring entities, arguments, or code flow that cross a split still appear in at least one retrievable unit. Too little overlap hurts recall near chunk edges; too much overlap bloats the index, increases embedding cost, and can bias retrieval toward duplicated text. The right value depends on document structure and query style, so measure retrieval hit quality and index growth together rather than tuning overlap in isolation.

    **Badges**:
    - Boundary recall

    **Links**:
    - [Breaking It Down (2025)](https://arxiv.org/abs/2512.00367)
    - [LangChain Text Splitters](https://python.langchain.com/docs/concepts/text_splitters/)
    - [LlamaIndex Node Parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)
    - [Weaviate Search Concepts](https://weaviate.io/developers/weaviate/concepts/search)

??? info "`chunking.chunk_size` (`CHUNK_SIZE`) — Chunk Size"
    **Category**: `chunking`

    Sets the target size of each chunk before embedding. Larger chunks preserve more local context and can help complex synthesis, but they reduce granularity and may retrieve irrelevant text; smaller chunks improve precision and reranking flexibility but risk fragmenting meaning. In code and technical corpora, chunk size should be tuned with overlap, tokenizer behavior, and model context limits as a single budget problem. The best value is empirical: run retrieval evaluations on your actual question set and choose the smallest size that preserves answer completeness.

    **Badges**:
    - Recall/precision

    **Links**:
    - [Breaking It Down (2025)](https://arxiv.org/abs/2512.00367)
    - [LangChain Text Splitters](https://python.langchain.com/docs/concepts/text_splitters/)
    - [LlamaIndex Node Parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)
    - [HF Tokenizer Docs](https://huggingface.co/docs/transformers/main_classes/tokenizer)

??? info "`chunking.chunking_strategy` (`CHUNKING_STRATEGY`) — Chunking Strategy"
    **Category**: `chunking`

    Defines how source content is segmented before embedding and indexing, which is one of the highest-impact choices in a RAG pipeline. Syntax-aware strategies preserve logical units like functions or classes and usually improve precision for code queries, while simpler fixed or greedy splits are faster and more robust for mixed or noisy inputs. Hybrid strategies often perform best operationally because they retain structure when parsing succeeds and fall back gracefully when it does not. Any strategy change should trigger reindexing and evaluation because embeddings, recall patterns, and reranker behavior all shift together.

    **Badges**:
    - Index quality

    **Links**:
    - [cAST (2025)](https://arxiv.org/abs/2506.15655)
    - [Tree-sitter](https://tree-sitter.github.io/tree-sitter/)
    - [ASTChunk Repository](https://github.com/yilinjz/astchunk)
    - [LangChain Text Splitters](https://python.langchain.com/docs/concepts/text_splitters/)

??? info "`chunking.greedy_fallback_target` (`GREEDY_FALLBACK_TARGET`) — Greedy Fallback Target (Chars)"
    **Category**: `general`

    GREEDY_FALLBACK_TARGET defines the approximate character size for fallback chunks when structured chunking fails, such as parse errors, malformed files, or oversized units that cannot be split semantically. It is a resilience control that keeps indexing and retrieval operational when ideal AST-aware segmentation is not possible. Smaller targets improve precision but can fragment meaning; larger targets preserve context but reduce retrieval granularity and increase prompt cost. Choose a value that aligns with your embedding model and downstream context budget, then validate on real failure cases instead of clean files only. Any change should be followed by reindexing so fallback boundaries are rebuilt consistently.

    **Badges**:
    - Chunking Fallback

    **Links**:
    - [LangChain Text Splitters Concepts](https://python.langchain.com/docs/concepts/text_splitters/)
    - [LlamaIndex Node Parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)
    - [Cohere Chunking Strategies](https://docs.cohere.com/page/chunking-strategies)
    - [FreeChunker (2025): Cross-Granularity Chunking](https://arxiv.org/abs/2510.20356)

??? info "`chunking.max_chunk_tokens` (`MAX_CHUNK_TOKENS`) — Max Chunk Tokens"
    **Category**: `chunking`

    Maximum token length for a single code chunk during AST-based chunking. Limits chunk size to fit within embedding model token limits (typically 512-8192 tokens). Larger chunks (1000-2000 tokens) capture more context per chunk, reducing fragmentation of large functions/classes. Smaller chunks (200-512 tokens) create more granular units, improving precision but potentially losing broader context.

    Sweet spot: 512-768 tokens for balanced chunking. This fits most embedding models (e.g., OpenAI text-embedding-3 supports up to 8191 tokens, but 512-768 is practical). Use 768-1024 for code with large docstrings or complex classes where context matters. Use 256-512 for tight memory budgets or when targeting very specific code snippets. AST chunking respects syntax, so chunks won't split mid-function even if size limit is hit (falls back to greedy chunking).

    Token count is approximate (based on whitespace heuristics, not exact tokenization). Actual embedding input may vary slightly. If a logical unit (function, class) exceeds MAX_CHUNK_TOKENS, the chunker splits it using GREEDY_FALLBACK_TARGET for sub-chunking while preserving structure where possible.

    • Range: 200-2000 tokens (typical)
    • Small: 256-512 tokens (precision, tight memory)
    • Balanced: 512-768 tokens (recommended, fits most models)
    • Large: 768-1024 tokens (more context, larger functions)
    • Very large: 1024-2000 tokens (maximum context, risky for some models)
    • Constraint: Must not exceed embedding model token limit

    **Badges**:
    - Advanced chunking
    - Requires reindex

    **Links**:
    - [Token Limits by Model](https://platform.openai.com/docs/guides/embeddings/embedding-models)
    - [cAST Paper](https://arxiv.org/abs/2506.15655)
    - [Chunking Size Tradeoffs](https://weaviate.io/blog/chunking-strategies-for-rag)
    - [Token Estimation](https://github.com/openai/tiktoken)

??? info "`chunking.max_indexable_file_size` (`MAX_INDEXABLE_FILE_SIZE`) — Max Indexable File Size"
    **Category**: `infrastructure`

    Defines the byte-size cutoff above which files are excluded from indexing. This protects index jobs from pathological memory and token consumption on massive generated assets, archives, or dumps, and keeps indexing latency predictable. If this value is too low, important large source artifacts (for example long SQL, generated API clients, or monolithic configs) may never become retrievable. If too high, indexing throughput can collapse and storage cost can spike. Set this using observed file-size distribution, then reindex so the new threshold is applied consistently.

    **Badges**:
    - File filtering
    - Requires reindex

    **Links**:
    - [A New Chunking Strategy for Long-Document Retrieval (arXiv 2025)](https://arxiv.org/abs/2505.21700)
    - [Sourcegraph Indexed Search Administration](https://sourcegraph.com/docs/admin/search#indexed-search)
    - [GitLab Instance Limits (Indexed File Size Settings)](https://docs.gitlab.com/ee/administration/instance_limits.html)
    - [Azure AI Search Limits, Quotas, and Capacity](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)

??? info "`chunking.min_chunk_chars` (`MIN_CHUNK_CHARS`) — Min Chunk Chars"
    **Category**: `chunking`

    Lower bound on chunk length kept during indexing. Chunks smaller than this threshold are typically merged or discarded to reduce retrieval noise from trivial fragments (isolated braces, tiny comments, short tokens). Setting it too low increases index clutter and false positives; setting it too high can remove short but meaningful facts (config flags, function signatures, one-line constraints). Tune this jointly with chunk size and overlap using real queries: track recall impact on terse lookups while watching precision and index growth.

    **Badges**:
    - Index quality control
    - Requires reindex

    **Links**:
    - [cAST: Structural Chunking for Code RAG (arXiv 2025)](https://arxiv.org/abs/2506.15655)
    - [LangChain Text Splitter Concepts](https://python.langchain.com/docs/concepts/text_splitters/)
    - [Weaviate Chunking Strategies for RAG](https://weaviate.io/blog/chunking-strategies-for-rag)
    - [LlamaIndex Node Parser Guide](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)

??? info "`chunking.preserve_imports` (`PRESERVE_IMPORTS`) — Preserve Imports"
    **Category**: `infrastructure`

    Forces the indexer to retain import/require/use statements even when chunks are otherwise below minimum size thresholds. This improves dependency-oriented retrieval, such as 'where is X imported' or 'which modules depend on Y', because import edges often encode architecture intent that function bodies alone miss. The tradeoff is slightly larger index size and potential noise if import blocks are highly repetitive across generated files. Keep it enabled when dependency tracing is a core use case, and pair it with deduplication or path-level weighting to avoid over-indexing boilerplate.

    **Badges**:
    - Dependency tracking
    - Requires reindex

    **Links**:
    - [GRACE: Graph-Retrieval Augmentation for Code Repositories (arXiv 2025)](https://arxiv.org/abs/2509.05980)
    - [Python Import System Reference](https://docs.python.org/3/reference/import.html)
    - [Node.js Modules Documentation](https://nodejs.org/api/modules.html)
    - [Java Language Specification: Packages and Modules](https://docs.oracle.com/javase/specs/jls/se22/html/jls-7.html)
