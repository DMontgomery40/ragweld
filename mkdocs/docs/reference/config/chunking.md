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
| `chunking.chunking_strategy` | `CHUNKING_STRATEGY` | `str` | `"ast"` | pattern=^(ast\|hybrid\|greedy\|fixed_chars\|fixed_tokens\|recursive\|markdown\|sentence\|qa_blocks\|semantic)$ | Chunking strategy (document + code) |
| `chunking.emit_chunk_ordinal` | — | `bool` | `true` | — | Emit chunk ordinal metadata for neighbor-window retrieval. |
| `chunking.emit_parent_doc_id` | — | `bool` | `true` | — | Emit parent document id metadata for neighbor-window retrieval. |
| `chunking.greedy_fallback_target` | `GREEDY_FALLBACK_TARGET` | `int` | `800` | ≥ 200, ≤ 2000 | Target size for greedy chunking |
| `chunking.markdown_include_code_fences` | — | `bool` | `true` | — | Whether to include fenced code blocks in markdown sections. |
| `chunking.markdown_max_heading_level` | — | `int` | `4` | ≥ 1, ≤ 6 | Max heading level to split on for markdown chunking. |
| `chunking.max_chunk_tokens` | `MAX_CHUNK_TOKENS` | `int` | `8000` | ≥ 100, ≤ 32000 | Maximum tokens per chunk - chunks exceeding this are split recursively |
| `chunking.max_indexable_file_size` | `MAX_INDEXABLE_FILE_SIZE` | `int` | `250000000` | ≥ 10000, ≤ 2000000000 | Max file size to index (bytes) - files larger than this are skipped |
| `chunking.min_chunk_chars` | `MIN_CHUNK_CHARS` | `int` | `50` | ≥ 10, ≤ 500 | Minimum chunk size |
| `chunking.overlap_tokens` | — | `int` | `64` | ≥ 0, ≤ 2048 | Token overlap between chunks (token-based strategies) |
| `chunking.preserve_imports` | `PRESERVE_IMPORTS` | `int` | `1` | ≥ 0, ≤ 1 | Include imports in chunks |
| `chunking.recursive_max_depth` | — | `int` | `10` | ≥ 1, ≤ 50 | Max recursion depth for recursive chunking. |
| `chunking.separator_keep` | — | `Literal["none", "prefix", "suffix"]` | `"suffix"` | allowed="none", "prefix", "suffix" | Whether to keep separators when splitting (recursive strategy). |
| `chunking.separators` | — | `list[str]` | `["\n\n", "\n", ". ", " ", ""]` | — | Separators for recursive chunking, in priority order. |
| `chunking.target_tokens` | — | `int` | `512` | ≥ 64, ≤ 8192 | Target tokens per chunk (token-based strategies) |

### Details (glossary)

??? info "`chunking.ast_overlap_lines` (`AST_OVERLAP_LINES`) — AST Overlap Lines"
    **Category**: `chunking`

    Number of overlapping lines between consecutive AST-based code chunks. Overlap ensures context continuity across chunk boundaries, preventing loss of meaning when functions or classes are split. Higher overlap (5-15 lines) improves retrieval quality by providing more context but increases index size and duplicate content. Lower overlap (0-5 lines) reduces redundancy but risks fragmenting logical units.

    Sweet spot: 3-5 lines for balanced context preservation. Use 5-10 lines for codebases with large functions or complex nested structures where context matters heavily. Use 0-2 lines for memory-constrained environments or when chunk boundaries align well with natural code structure (e.g., clean function boundaries). AST-aware chunking (cAST method) respects syntax boundaries, so overlap supplements structural chunking.

    Example: With 5-line overlap, if chunk 1 ends at line 100, chunk 2 starts at line 96, creating a 5-line bridge. This helps when a query matches content near chunk boundaries - the overlapping region appears in both chunks, improving recall. The cAST paper (EMNLP 2025) shows overlap significantly improves code retrieval accuracy.

    • Range: 0-15 lines (typical)
    • Minimal: 0-2 lines (tight memory, clean boundaries)
    • Balanced: 3-5 lines (recommended for most codebases)
    • High context: 5-10 lines (complex nested code)
    • Very high: 10-15 lines (maximum context, high redundancy)
    • Trade-off: More overlap = better recall, larger index

    **Badges**:
    - Advanced chunking
    - Requires reindex

    **Links**:
    - [cAST Chunking Paper (EMNLP 2025)](https://arxiv.org/abs/2506.15655)
    - [AST Chunking Toolkit](https://github.com/yilinjz/astchunk)
    - [Context Window in RAG](https://arxiv.org/abs/2312.10997)

??? info "`chunking.chunk_overlap` (`CHUNK_OVERLAP`) — Chunk Overlap"
    **Category**: `chunking`

    Number of characters overlapped between adjacent chunks. Overlap reduces boundary effects and improves recall at the cost of a larger index and slower indexing.

    **Links**:
    - [LangChain: Text Splitters](https://python.langchain.com/docs/modules/data_connection/document_transformers/text_splitters/)

??? info "`chunking.chunk_size` (`CHUNK_SIZE`) — Chunk Size"
    **Category**: `chunking`

    Target size (in characters) for each indexed chunk. For AST chunking this acts as a guardrail when nodes are large. Larger chunks preserve more context but reduce recall; smaller chunks improve recall but may fragment semantics.

    **Badges**:
    - Affects recall/precision

    **Links**:
    - [LangChain: Text Splitters](https://python.langchain.com/docs/modules/data_connection/document_transformers/text_splitters/)
    - [Okapi BM25 (context windows)](https://en.wikipedia.org/wiki/Okapi_BM25)

??? info "`chunking.chunking_strategy` (`CHUNKING_STRATEGY`) — Chunking Strategy"
    **Category**: `chunking`

    Primary strategy for splitting code into chunks during indexing. Options: "ast" (AST-aware, syntax-respecting, recommended for code), "greedy" (line-based splitting, simpler), "hybrid" (AST with greedy fallback). AST chunking uses the cAST method (EMNLP 2025) to respect function/class boundaries, preserving semantic units. Greedy chunking splits at line breaks to hit target size, ignoring syntax. Hybrid uses AST primarily with greedy fallback for unparseable files.

    "ast" (recommended for code): Parses syntax tree and chunks at natural boundaries (functions, classes, methods). Produces semantically coherent chunks. Best for code retrieval. Requires parseable syntax - fails gracefully on malformed code.

    "greedy": Simple line-based splitting at target character count. Fast, always works, but may split mid-function or mid-class, fragmenting semantic units. Use for non-code (markdown, text) or when AST parsing is too slow.

    "hybrid": Tries AST first, falls back to greedy on parse errors. Balanced approach - gets AST benefits for well-formed code, handles edge cases gracefully. Recommended for mixed codebases (code + docs + config).

    • ast: Syntax-aware, best retrieval quality, code-only, requires parseable syntax (recommended for code)
    • greedy: Fast, always works, ignores syntax, lower quality chunks, good for non-code
    • hybrid: AST + greedy fallback, balanced, handles all files (recommended for mixed repos)
    • Effect: Fundamental impact on chunk quality, retrieval precision, index structure
    • Requires reindex: Changes take effect after full rebuild

    **Badges**:
    - Core indexing choice
    - Requires reindex

    **Links**:
    - [cAST Chunking Paper (EMNLP 2025)](https://arxiv.org/abs/2506.15655)
    - [AST Chunking Toolkit](https://github.com/yilinjz/astchunk)
    - [RAG Chunking Best Practices](https://weaviate.io/blog/chunking-strategies-for-rag)

??? info "`chunking.greedy_fallback_target` (`GREEDY_FALLBACK_TARGET`) — Greedy Fallback Target (Chars)"
    **Category**: `general`

    Target chunk size (in characters) for greedy fallback chunking when AST-based chunking fails or encounters oversized logical units. Greedy chunking splits text at line boundaries to hit this approximate size. Used as a safety mechanism when: (1) file syntax is unparseable, (2) a single function/class exceeds MAX_CHUNK_SIZE, (3) non-code files (markdown, text) are indexed.

    Sweet spot: 500-800 characters for fallback chunks. This roughly corresponds to 100-150 tokens, providing reasonable context when AST chunking isn't possible. Use 800-1200 for larger fallback chunks (more context but less precise boundaries). Use 300-500 for smaller fallback chunks (tighter boundaries, less context). Greedy chunking is less semantic than AST chunking - it splits at line breaks regardless of code structure.

    Example: If a 3000-char function exceeds MAX_CHUNK_SIZE and can't be split structurally, greedy fallback divides it into ~4 chunks of ~750 chars each (based on GREEDY_FALLBACK_TARGET=800). This preserves some of the function in each chunk. Greedy fallback is rare in well-formed code but essential for robustness.

    • Range: 300-1500 characters (typical)
    • Small: 300-500 chars (tight boundaries, less context)
    • Balanced: 500-800 chars (recommended, ~100-150 tokens)
    • Large: 800-1200 chars (more context per fallback chunk)
    • Very large: 1200-1500 chars (maximum context, rare use)
    • When used: Syntax errors, oversized units, non-code files

    **Badges**:
    - Fallback mechanism
    - Requires reindex

    **Links**:
    - [Chunking Robustness](https://github.com/yilinjz/astchunk#fallback-modes)
    - [Greedy Chunking](https://en.wikipedia.org/wiki/Chunking_(psychology))

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

    Maximum file size in bytes that will be indexed. Files larger than this limit are skipped during indexing to prevent memory issues and avoid indexing large binary or generated files. Default is 2MB (2,000,000 bytes). Increase for codebases with legitimately large source files; decrease to speed up indexing and reduce memory usage.

    Sweet spot: 1-2 MB for most codebases. Use 500KB-1MB for memory-constrained environments or when you want to exclude large auto-generated files. Use 2-5MB for codebases with large source files (e.g., bundled assets, data files that should be searchable). Files exceeding this limit are logged as skipped.

    Example: A 5MB SQL dump file would be skipped with MAX_INDEXABLE_FILE_SIZE=2000000. To include it, increase to 6000000 (6MB). Large files that are indexed will be chunked normally, but may take longer to process and consume more embedding API tokens.

    • Range: 100KB - 10MB (typical)
    • Tight: 100KB - 500KB (skip most large files, fast indexing)
    • Balanced: 1MB - 2MB (recommended, handles normal source files)
    • Large: 2MB - 5MB (include larger source files)
    • Very large: 5MB - 10MB (include data files, maximum coverage)
    • Trade-off: Higher limit = more coverage, slower indexing, more memory

    **Badges**:
    - File filtering
    - Requires reindex

??? info "`chunking.min_chunk_chars` (`MIN_CHUNK_CHARS`) — Min Chunk Chars"
    **Category**: `chunking`

    Minimum characters required for a chunk to be kept. Very small fragments below this are dropped or merged to reduce indexing noise. Default: 50. Range: 10-500. Raise it for a cleaner index; lower it if you need tiny helpers and stubs searchable. Changing this requires reindexing.

    **Badges**:
    - Index quality control
    - Requires reindex

    **Links**:
    - [Code Chunking Best Practices](https://weaviate.io/blog/chunking-strategies-for-rag)
    - [cAST Filtering](https://github.com/yilinjz/astchunk#filtering)

??? info "`chunking.preserve_imports` (`PRESERVE_IMPORTS`) — Preserve Imports"
    **Category**: `infrastructure`

    Include import and require blocks even when they are below MIN_CHUNK_CHARS (0/1). Improves dependency discovery queries like "where is X imported". Default: 1. Range: 0-1. Changing this requires reindexing.

    **Badges**:
    - Dependency tracking
    - Requires reindex

    **Links**:
    - [Code Structure Analysis](https://en.wikipedia.org/wiki/Dependency_analysis)
    - [Module Systems](https://en.wikipedia.org/wiki/Modular_programming)
