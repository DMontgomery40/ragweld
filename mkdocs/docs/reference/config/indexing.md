# Config reference: `indexing`

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
| `indexing.bm25_stemmer_lang` | `BM25_STEMMER_LANG` | `str` | `"english"` | — | Stemmer language |
| `indexing.bm25_stopwords_lang` | `BM25_STOPWORDS_LANG` | `str` | `"en"` | — | Stopwords language code |
| `indexing.bm25_tokenizer` | `BM25_TOKENIZER` | `str` | `"stemmer"` | pattern=^(stemmer\|lowercase\|whitespace)$ | BM25 tokenizer type |
| `indexing.collection_suffix` | `COLLECTION_SUFFIX` | `str` | `"default"` | — | Collection suffix for multi-index scenarios |
| `indexing.index_excluded_exts` | `INDEX_EXCLUDED_EXTS` | `str` | `".png,.jpg,.gif,.ico,.svg,.woff,.ttf"` | — | Excluded file extensions (comma-separated) |
| `indexing.index_max_file_size_mb` | `INDEX_MAX_FILE_SIZE_MB` | `int` | `250` | ≥ 1, ≤ 1024 | Max file size to index (MB) |
| `indexing.indexing_batch_size` | `INDEXING_BATCH_SIZE` | `int` | `100` | ≥ 10, ≤ 1000 | Batch size for indexing |
| `indexing.indexing_workers` | `INDEXING_WORKERS` | `int` | `4` | ≥ 1, ≤ 16 | Parallel workers for indexing |
| `indexing.large_file_mode` | — | `Literal["read_all", "stream"]` | `"stream"` | allowed="read_all", "stream" | How to ingest very large text files. 'stream' avoids loading entire files into memory. |
| `indexing.large_file_stream_chunk_chars` | — | `int` | `2000000` | ≥ 100000, ≤ 50000000 | When large_file_mode='stream', read text files in bounded char blocks (best-effort). |
| `indexing.out_dir_base` | `OUT_DIR_BASE` | `str` | `"./out"` | — | Base output directory |
| `indexing.parquet_extract_include_column_names` | `PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES` | `int` | `1` | ≥ 0, ≤ 1 | Include column headers when extracting Parquet text |
| `indexing.parquet_extract_max_cell_chars` | `PARQUET_EXTRACT_MAX_CELL_CHARS` | `int` | `20000` | ≥ 100, ≤ 200000 | Max characters per extracted Parquet cell (best-effort) |
| `indexing.parquet_extract_max_chars` | `PARQUET_EXTRACT_MAX_CHARS` | `int` | `2000000` | ≥ 10000, ≤ 50000000 | Max characters to extract from a single Parquet file during indexing (best-effort) |
| `indexing.parquet_extract_max_rows` | `PARQUET_EXTRACT_MAX_ROWS` | `int` | `5000` | ≥ 1, ≤ 200000 | Max rows to extract from a single Parquet file during indexing (best-effort) |
| `indexing.parquet_extract_text_columns_only` | `PARQUET_EXTRACT_TEXT_COLUMNS_ONLY` | `int` | `1` | ≥ 0, ≤ 1 | Extract only text/string-like columns from Parquet files when possible |
| `indexing.postgres_url` | `POSTGRES_URL` | `str` | `"postgresql://postgres:postgres@localhost:5432/tribrid_rag"` | — | PostgreSQL connection string (DSN) for pgvector + FTS storage |
| `indexing.rag_out_base` | `RAG_OUT_BASE` | `str` | `""` | — | Override for OUT_DIR_BASE if specified |
| `indexing.repo_path` | `REPO_PATH` | `str` | `""` | — | Fallback repository path if not found in repos.json |
| `indexing.repos_file` | `REPOS_FILE` | `str` | `"./repos.json"` | — | Repository configuration file |
| `indexing.skip_dense` | `SKIP_DENSE` | `int` | `0` | ≥ 0, ≤ 1 | Skip dense vector indexing |
| `indexing.table_name` | `COLLECTION_NAME` | `str` | `"code_chunks_{repo}"` | — | pgvector table name template |

### Details (glossary)

??? info "`indexing.bm25_stemmer_lang` (`BM25_STEMMER_LANG`) — BM25 Stemmer Language"
    **Category**: `retrieval`

    Language for stemming/normalization in BM25 sparse indexing. Common values: "en" (English - default), "multilingual" (multiple languages), "none" (disable stemming). Stemming reduces words to root forms (e.g., "running" -> "run") to improve keyword matching. English stemming works well for code comments, docs, and variable names. Use "none" for non-English repos or when exact keyword matching is critical (e.g., API names, error codes).

    Recommended: "en" for English codebases, "multilingual" for international teams, "none" for strict keyword matching.

    **Badges**:
    - Affects keyword search

    **Links**:
    - [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [Stemming Explained](https://en.wikipedia.org/wiki/Stemming)
    - [BM25S Library](https://github.com/xhluca/bm25s#supported-stemmers)

??? info "`indexing.bm25_stopwords_lang` (`BM25_STOPWORDS_LANG`) — BM25 Stopwords Language"
    **Category**: `retrieval`

    Language code used to select the stopword list for sparse (BM25/FTS) tokenization. Stopwords are extremely common words that are ignored to reduce noise (e.g., “the”, “and”, “of”).

    For code-heavy corpora, stopword filtering is a trade-off: it can clean up comments/README text, but it can also remove short tokens that sometimes matter. If your corpus contains multiple human languages, pick the dominant language, or use a minimal/no-stopword configuration if you care more about exact identifier matching.

    Changing stopwords changes the sparse vocabulary, so it only takes effect after rebuilding the sparse/FTS index.

    • Examples: en, es, fr (language codes)
    • Effect: controls which common words are ignored during sparse search
    • Symptom too aggressive: useful terms disappear from vocab preview
    • Symptom too permissive: huge vocab + noisy matches
    • Requires reindex: yes

    **Badges**:
    - Advanced indexing
    - Requires reindex

    **Links**:
    - [Stop Words](https://en.wikipedia.org/wiki/Stop_word)
    - [PostgreSQL Full Text Search Configurations](https://www.postgresql.org/docs/current/textsearch-configurations.html)

??? info "`indexing.bm25_tokenizer` (`BM25_TOKENIZER`) — BM25 Tokenizer"
    **Category**: `retrieval`

    Tokenization strategy for BM25 sparse index. Controls how code text is split into searchable terms. Options: "stemmer" (Porter stemming, normalizes word forms like "running" → "run"), "whitespace" (split on spaces only, preserves exact forms), "standard" (lowercase + split on punctuation). For code search, preserving exact forms is usually better than stemming.

    Sweet spot: "whitespace" or "standard" for code search. Stemming helps with natural language (README files, comments) but can hurt code search by conflating different identifiers. For example, stemming might merge "user" and "users" (good for prose) but also "handler" and "handle" (bad for code). Most code-focused RAG systems avoid stemming.

    "whitespace": Splits on whitespace only, preserves case and punctuation. Good for camelCase and snake_case. Example: "getUserData" → ["getUserData"].

    "standard": Lowercase + split on punctuation. Better for cross-case matching. Example: "getUserData" → ["getuserdata"] (matches "getuserdata", "getUserData", "GETUSERDATA").

    "stemmer": Applies Porter stemmer. Best for natural language, risky for code. Example: "getUserData" → stems individual tokens.

    • whitespace: Preserve exact forms, case-sensitive, best for strict code search
    • standard: Lowercase + punctuation split, case-insensitive, balanced (recommended)
    • stemmer: Normalize word forms, best for natural language, risky for code
    • Effect: Changes how BM25 matches query terms to code
    • Requires reindex: Changes take effect after rebuilding BM25 index

    **Badges**:
    - Advanced indexing
    - Requires reindex

    **Links**:
    - [BM25 Algorithm](https://en.wikipedia.org/wiki/Okapi_BM25)
    - [Porter Stemmer](https://en.wikipedia.org/wiki/Stemming#Porter_stemmer)
    - [Tokenization](https://en.wikipedia.org/wiki/Lexical_analysis#Tokenization)
    - [BM25S Tokenizers](https://github.com/xhluca/bm25s#tokenization)

??? info "`indexing.collection_suffix` (`COLLECTION_SUFFIX`) — Collection Suffix"
    **Category**: `general`

    Optional string appended to the default collection name (code_chunks_{REPO}) for A/B testing different indexing strategies. For example, suffix "_v2" creates "code_chunks_myrepo_v2". Useful when comparing embedding models, chunking strategies, or reranking approaches without overwriting your production index. Leave empty for default collection.

    **Badges**:
    - Experimental

    **Links**:
    - [Qdrant Collections](https://qdrant.tech/documentation/concepts/collections/)
    - [Collection Management](https://qdrant.tech/documentation/concepts/collections/#create-collection)
    - [Collection Naming](https://qdrant.tech/documentation/concepts/collections/#collection-name)

??? info "`indexing.index_excluded_exts` (`INDEX_EXCLUDED_EXTS`) — Excluded Extensions"
    **Category**: `infrastructure`

    Comma-separated file extensions to skip during indexing (e.g., ".png,.jpg,.pdf,.zip"). Prevents indexing binary files, images, or non-code assets. Reduces index size and improves relevance.

    **Links**:
    - [Gitignore Patterns](https://git-scm.com/docs/gitignore)
    - [File Extensions](https://en.wikipedia.org/wiki/Filename_extension)

??? info "`indexing.index_max_file_size_mb` (`INDEX_MAX_FILE_SIZE_MB`) — Index max file size (MB)"
    **Category**: `chunking`

    Hard cap for indexing: files larger than this (in MB) are skipped before reading. For very large text dumps, raise this above the file size and enable streaming ingestion.

??? info "`indexing.indexing_batch_size` (`INDEXING_BATCH_SIZE`) — Indexing Batch Size"
    **Category**: `embedding`

    Number of chunks to process in parallel during the indexing pipeline (chunking, enrichment, embedding, Qdrant upload). Higher values (100-500) maximize throughput on fast networks and powerful machines but increase memory usage and risk batch failures. Lower values (20-50) are more stable and provide better progress visibility. If indexing crashes with OOM or connection errors, reduce this. For large repos (100k+ files), use higher values for efficiency.

    Recommended: 100-200 for normal repos, 50-100 for large repos or slow connections, 500+ for small repos on powerful hardware.

    **Badges**:
    - Performance tuning
    - Memory sensitive

    **Links**:
    - [Batch Processing](https://en.wikipedia.org/wiki/Batch_processing)
    - [Qdrant Upload Performance](https://qdrant.tech/documentation/guides/bulk-upload/)

??? info "`indexing.indexing_workers` (`INDEXING_WORKERS`) — Indexing Workers"
    **Category**: `infrastructure`

    Number of parallel worker threads for CPU-intensive indexing tasks (file parsing, chunking, BM25 indexing). Higher values (4-16) utilize multi-core CPUs better and speed up indexing significantly. Lower values (1-2) reduce CPU load but increase indexing time. Set based on available CPU cores - typically use cores-1 or cores-2 to leave headroom for OS/other processes. For Docker/containers, ensure resource limits allow multiple workers.

    Recommended: 4-8 for most systems, 1-2 for low-power machines or containers with CPU limits, 12-16 for powerful servers.

    **Badges**:
    - CPU utilization
    - Faster indexing

    **Links**:
    - [Parallel Processing](https://en.wikipedia.org/wiki/Parallel_computing)
    - [Python ThreadPoolExecutor](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)
    - [Docker CPU Limits](https://docs.docker.com/engine/containers/resource_constraints/#cpu)

??? info "`indexing.out_dir_base` (`OUT_DIR_BASE`) — Out Dir Base"
    **Category**: `general`

    Where retrieval looks for indices (chunks.jsonl, bm25_index/). Use ./out.noindex-shared for one index across branches so MCP and local tools stay in sync. Stores dense vectors (Qdrant), sparse BM25 index, and indexed chunks. Symptom of mismatch: rag_search returns 0 results.

    **Badges**:
    - Requires restart (MCP)

    **Links**:
    - [Directory Concepts](https://en.wikipedia.org/wiki/Directory_(computing))
    - [MCP Protocol Spec](https://github.com/modelcontextprotocol/specification)
    - [Storage Management](https://qdrant.tech/documentation/concepts/storage/)

??? info "`indexing.parquet_extract_include_column_names` (`PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES`) — Parquet Include Column Names"
    **Category**: `indexing`

    Include Parquet column headers in extracted text (0/1). Keeping headers improves context for field-specific queries and schema-aware retrieval. Default: 1. Range: 0-1.

??? info "`indexing.parquet_extract_max_cell_chars` (`PARQUET_EXTRACT_MAX_CELL_CHARS`) — Parquet Extract Max Cell Chars"
    **Category**: `indexing`

    Maximum characters per Parquet cell when converting to text (best-effort). Long cells are truncated to keep output bounded.

??? info "`indexing.parquet_extract_max_chars` (`PARQUET_EXTRACT_MAX_CHARS`) — Parquet Extract Max Chars"
    **Category**: `indexing`

    Maximum total characters to extract from a single Parquet file during indexing (best-effort). Extraction stops once this limit is reached.

??? info "`indexing.parquet_extract_max_rows` (`PARQUET_EXTRACT_MAX_ROWS`) — Parquet Extract Max Rows"
    **Category**: `indexing`

    Best-effort cap on rows read from a single Parquet file during indexing. Prevents huge datasets from consuming excessive memory and time. Default: 5000. Range: 1-200000. Increase for deeper coverage; lower for faster and cheaper indexing.

??? info "`indexing.parquet_extract_text_columns_only` (`PARQUET_EXTRACT_TEXT_COLUMNS_ONLY`) — Parquet Text Columns Only"
    **Category**: `indexing`

    Extract only text-like Parquet columns when possible (0/1). Default: 1 to avoid noisy numeric or structured fields. Set to 0 if numeric columns are important to search.

??? info "`indexing.postgres_url` (`POSTGRES_URL`) — PostgreSQL pgvector URL"
    **Category**: `infrastructure`

    PostgreSQL DSN used for pgvector and FTS storage. Format: postgresql://user:pass@host:port/db. Default: postgresql://postgres:postgres@localhost:5432/tribrid_rag. Ensure pgvector is installed in the target database.

??? info "`indexing.rag_out_base` (`RAG_OUT_BASE`) — RAG Out Base"
    **Category**: `general`

    Optional override for retrieval output directory. If empty, OUT_DIR_BASE is used. Use this only when you need retrieval artifacts separated from other output paths.

    **Badges**:
    - Advanced

    **Links**:
    - [Configuration Management](https://12factor.net/config)
    - [Storage Concepts](https://qdrant.tech/documentation/concepts/storage/)
    - [BM25 Index Storage](https://github.com/BM25S/bm25s)

??? info "`indexing.repo_path` (`REPO_PATH`) — Repo Path (fallback)"
    **Category**: `general`

    Absolute filesystem path to the active repository when repos.json is not configured. This is the directory that will be indexed for code retrieval. Use repos.json instead for multi-repo setups with routing, keywords, and path boosts. Example: /Users/you/projects/myapp or /home/user/code/myrepo

    **Links**:
    - [Path Patterns](https://github.com/github/gitignore)
    - [Python pathlib Module](https://docs.python.org/3/library/pathlib.html)
    - [File System Paths](https://en.wikipedia.org/wiki/Path_(computing))

??? info "`indexing.repos_file` (`REPOS_FILE`) — Repos File"
    **Category**: `general`

    Path to repos.json that defines repo names, paths, keywords, path boosts, and layer bonuses used for multi-repo routing. Each repo entry includes name, path, optional keywords for boosting, path_boosts for directory-specific relevance, and layer_bonuses for hierarchical retrieval.

    **Links**:
    - [JSON Format Reference](https://www.json.org/json-en.html)
    - [Configuration Management](https://github.com/topics/configuration-management)
    - [Config File Concepts](https://en.wikipedia.org/wiki/Configuration_file)

??? info "`indexing.skip_dense` (`SKIP_DENSE`) — Skip Dense Embeddings"
    **Category**: `retrieval`

    Skip vector embeddings and Qdrant during indexing to create a fast BM25-only (keyword-only) index. Useful for quick testing, CI/CD pipelines, or when Qdrant is unavailable. BM25-only mode is faster and uses less resources but loses semantic search capability - only exact keyword matches work. Not recommended for production use unless you have a purely keyword-based use case.

    **Badges**:
    - Much faster
    - Keyword-only
    - No semantic search

    **Links**:
    - [Hybrid Search Benefits](https://www.pinecone.io/learn/hybrid-search-intro/)

??? info "`indexing.table_name` (`COLLECTION_NAME`) — Collection Name"
    **Category**: `general`

    Optional override for the Qdrant collection name where vectors are stored. Defaults to code_chunks_{REPO}. Set this if you maintain multiple profiles, A/B test embedding models, or run parallel indexing. Must be lowercase alphanumeric + underscore. Examples: code_chunks_v2, vectors_staging, embeddings_prod

    **Links**:
    - [Qdrant Collections Intro](https://qdrant.tech/documentation/concepts/collections/)
    - [Create Collections](https://qdrant.tech/documentation/concepts/collections/#create-collection)
    - [Database Collections](https://en.wikipedia.org/wiki/Database_collection)
