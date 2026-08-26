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

**Total parameters**: 18

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `indexing.bm25_stemmer_lang` | `BM25_STEMMER_LANG` | `str` | `"english"` | — | Snowball stemmer language for the sparse (Qdrant/bm25) index. Part of the sparse index contract. |
| `indexing.bm25_tokenizer` | `BM25_TOKENIZER` | `str` | `"stemmer"` | pattern=^(stemmer\|lowercase\|whitespace)$ | Sparse (Qdrant/bm25) tokenization: 'stemmer' applies the Snowball stemmer for bm25_stemmer_lang; 'lowercase' and 'whitespace' disable stemming. Part of the sparse index contract (re-index on change). |
| `indexing.estimated_tokens_per_second_local` | `ESTIMATED_TOKENS_PER_SECOND_LOCAL` | `int \| None` | `null` | ≥ 100, ≤ 500000 | Optional local embedding throughput override for index-time estimates (tokens/sec). |
| `indexing.generation_retention_seconds` | `GENERATION_RETENTION_SECONDS` | `int` | `600` | ≥ 0, ≤ 86400 | How long a replaced index generation (its Qdrant collection and Neo4j graph) stays readable after a promotion before it is retired. Must cover the longest request that can still hold the old manifest; 0 retires it at the next commit. |
| `indexing.index_excluded_exts` | `INDEX_EXCLUDED_EXTS` | `str` | `".png,.jpg,.gif,.ico,.svg,.woff,.ttf"` | — | Excluded file extensions (comma-separated) |
| `indexing.index_max_file_size_mb` | `INDEX_MAX_FILE_SIZE_MB` | `int` | `250` | ≥ 1, ≤ 1024 | Max file size to index (MB) |
| `indexing.index_run_lease_seconds` | `INDEX_RUN_LEASE_SECONDS` | `int` | `600` | ≥ 30, ≤ 86400 | Lease on the per-corpus index-run fence. A running index heartbeats the fence; a fence whose last heartbeat is older than this is treated as a crashed worker and may be taken over by a new run. |
| `indexing.indexing_batch_size` | `INDEXING_BATCH_SIZE` | `int` | `100` | ≥ 10, ≤ 1000 | Batch size for indexing |
| `indexing.indexing_workers` | `INDEXING_WORKERS` | `int` | `4` | ≥ 1, ≤ 16 | Parallel workers for indexing |
| `indexing.large_file_mode` | — | `Literal["read_all", "stream"]` | `"stream"` | allowed="read_all", "stream" | How to ingest very large text files. 'stream' avoids loading entire files into memory. |
| `indexing.large_file_stream_chunk_chars` | — | `int` | `2000000` | ≥ 100000, ≤ 50000000 | When large_file_mode='stream', read text files in bounded char blocks (best-effort). |
| `indexing.parquet_extract_include_column_names` | `PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES` | `bool` | `true` | — | Include column headers when extracting Parquet text |
| `indexing.parquet_extract_max_cell_chars` | `PARQUET_EXTRACT_MAX_CELL_CHARS` | `int` | `20000` | ≥ 100, ≤ 200000 | Max characters per extracted Parquet cell (best-effort) |
| `indexing.parquet_extract_max_chars` | `PARQUET_EXTRACT_MAX_CHARS` | `int` | `2000000` | ≥ 10000, ≤ 50000000 | Max characters to extract from a single Parquet file during indexing (best-effort) |
| `indexing.parquet_extract_max_rows` | `PARQUET_EXTRACT_MAX_ROWS` | `int` | `5000` | ≥ 1, ≤ 200000 | Max rows to extract from a single Parquet file during indexing (best-effort) |
| `indexing.parquet_extract_text_columns_only` | `PARQUET_EXTRACT_TEXT_COLUMNS_ONLY` | `bool` | `true` | — | Extract only text/string-like columns from Parquet files when possible |
| `indexing.postgres_url` | `POSTGRES_URL` | `str` | `"postgresql://postgres:postgres@localhost:5432/tribrid_rag"` | — | PostgreSQL connection string (DSN) for corpus control/state storage (chunk rows, summaries, caches) |
| `indexing.skip_dense` | `SKIP_DENSE` | `bool` | `false` | — | Skip dense vector indexing |

### Details (glossary)

??? info "`indexing.bm25_stemmer_lang` (`BM25_STEMMER_LANG`) — BM25 Stemmer Language"
    **Category**: `retrieval`

    BM25_STEMMER_LANG is the Snowball stemmer language applied when BM25_TOKENIZER is `stemmer`, for example `english` or `german`; fastembed's `Qdrant/bm25` model uses it to normalize inflected forms before building sparse vectors. It is part of the corpus sparse contract: the language used at index time must match the language used at query time, so changing it requires a re-index. Unsupported language names fail the sparse leg with an explicit error rather than silently falling back.

    **Badges**:
    - Linguistics

    **Links**:
    - [Milco: Multilingual Sparse Retrieval via Connector (arXiv)](https://arxiv.org/abs/2510.00671)
    - [Elasticsearch Language Analyzers](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-lang-analyzer.html)
    - [Snowball Stemming Algorithms](https://snowballstem.org/)
    - [Lucene Analysis Common Module](https://lucene.apache.org/core/10_3_1/analysis/common/index.html)

??? info "`indexing.bm25_tokenizer` (`BM25_TOKENIZER`) — BM25 Tokenizer"
    **Category**: `retrieval`

    BM25_TOKENIZER chooses whether the sparse `Qdrant/bm25` vectors are built with Snowball stemming (`stemmer`, using BM25_STEMMER_LANG) or without stemming (`lowercase` and `whitespace` both disable the stemmer and keep exact tokens). Stemming helps narrative prose match inflected forms; exact tokens preserve identifiers, filenames, and error codes for code-heavy corpora. The choice is recorded in the corpus sparse contract, so changing it requires a re-index and is otherwise refused.

    **Badges**:
    - Tokenization

    **Links**:
    - [Multilingual Generative Retrieval via Semantic Compression (arXiv)](https://arxiv.org/abs/2510.07812)
    - [Elasticsearch Tokenizers](https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-tokenizers.html)
    - [Hugging Face Tokenizers](https://huggingface.co/docs/tokenizers/index)
    - [Lucene WhitespaceTokenizer](https://lucene.apache.org/core/10_3_1/analysis/common/org/apache/lucene/analysis/core/WhitespaceTokenizer.html)

??? info "`indexing.generation_retention_seconds` (`GENERATION_RETENTION_SECONDS`) — Generation Retention Seconds"
    GENERATION_RETENTION_SECONDS is how long a replaced index generation (its Qdrant collection and Neo4j graph) stays readable after a promotion before the next commit retires it. Promotion writes a new generation manifest in one Postgres transaction; a request that resolved the old manifest just before that commit still queries the old stores, so the grace must cover the longest request lifetime. A value of 0 retires the replaced generation at the very next commit. Retired generations are dropped by exact id, never by name prefix.

??? info "`indexing.index_excluded_exts` (`INDEX_EXCLUDED_EXTS`) — Excluded Extensions"
    **Category**: `infrastructure`

    Defines a denylist of file extensions that should be skipped before ingestion so the index is not polluted by binaries, build artifacts, media blobs, and other low-signal assets. In code and docs RAG, good exclusion rules improve both precision and indexing cost by avoiding irrelevant tokens and expensive parsing failures. Keep this list aligned with your repository layout and parser capabilities, because extension-only filtering can miss mislabeled files unless combined with MIME or content checks. Review exclusions after major stack changes, especially when adding documentation generators or notebook-heavy workflows. Overly broad exclusions can silently remove valuable domain knowledge from retrieval.

    **Badges**:
    - Corpus hygiene

    **Links**:
    - [Vision-Guided Chunking Improves RAG in Multimodal Long Context Scenarios](https://arxiv.org/abs/2506.16035)
    - [gitignore Pattern Format](https://git-scm.com/docs/gitignore)
    - [Unstructured Open Source Overview](https://docs.unstructured.io/open-source/introduction/overview)
    - [Azure AI Search: Chunk Large Documents](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents)

??? info "`indexing.index_max_file_size_mb` (`INDEX_MAX_FILE_SIZE_MB`) — Index max file size (MB)"
    **Category**: `chunking`

    Sets a hard upper bound on file size for indexing to prevent memory spikes and long-tail ingestion delays caused by extremely large documents. In RAG pipelines this value protects indexing stability, but if set too low it can remove high-value sources such as architecture guides, policy manuals, or API bundles. Use corpus stats to choose a threshold, typically around the P95 or P99 file size, then special-case known large files with streaming or sectioned ingestion. This setting interacts with chunking strategy, parser behavior, and total token budget, so tune it alongside chunk size and overlap rather than in isolation. Periodic audits of skipped-file lists help avoid accidental knowledge gaps.

    **Badges**:
    - Stability guardrail

    **Links**:
    - [HiFi-RAG: Enhancing Retrieval-Augmented Generation through High-Fidelity Contextual Chunking and Reasoning](https://arxiv.org/abs/2512.22442)
    - [Azure AI Search: Chunk Large Documents](https://learn.microsoft.com/en-us/azure/search/vector-search-how-to-chunk-documents)
    - [Unstructured Open Source Overview](https://docs.unstructured.io/open-source/introduction/overview)
    - [Weaviate Data Import](https://docs.weaviate.io/weaviate/manage-objects/import)

??? info "`indexing.index_run_lease_seconds` (`INDEX_RUN_LEASE_SECONDS`) — Index Run Lease Seconds"
    INDEX_RUN_LEASE_SECONDS is the lease on the durable per-corpus index-run fence stored on the corpus row. A running index heartbeats the fence at a tenth of the lease; a second run on the same corpus is refused with a typed 409 while the fence is fresh. A fence whose last heartbeat is older than the lease is treated as a crashed worker: a new run may take it over, and stopping the corpus releases it. Set it longer than the longest pause a run can have without heartbeating.

??? info "`indexing.indexing_batch_size` (`INDEXING_BATCH_SIZE`) — Indexing Batch Size"
    **Category**: `embedding`

    INDEXING_BATCH_SIZE sets how many chunks or records are processed together per indexing step, affecting throughput, memory pressure, and failure blast radius. Larger batches generally improve GPU and network utilization for embeddings and vector upserts, but they also increase peak memory and make retries more expensive. Smaller batches are slower but more resilient when providers rate-limit, vector stores throttle writes, or occasional malformed records appear. The best value depends on embedding latency, vector DB ingest speed, and available RAM, so it should be tuned with real pipeline telemetry. Start conservatively, then increase until throughput gains flatten or error rates begin rising.

    **Badges**:
    - Throughput

    **Links**:
    - [Qdrant Bulk Upload Tutorial](https://qdrant.tech/documentation/database-tutorials/bulk-upload/)
    - [pgvector Repository](https://github.com/pgvector/pgvector)
    - [PostgreSQL COPY Command](https://www.postgresql.org/docs/current/sql-copy.html)
    - [LightRetriever (2025): Faster Query Inference](https://arxiv.org/abs/2505.12260)

??? info "`indexing.indexing_workers` (`INDEXING_WORKERS`) — Indexing Workers"
    **Category**: `infrastructure`

    Controls how many parallel workers execute indexing stages such as parsing, chunking, sparse indexing, and embedding preparation. In RAG systems this is a throughput lever, but only up to the point where CPU cores, memory bandwidth, disk I/O, or embedding-provider rate limits become the bottleneck. A practical baseline is physical cores minus one or two so interactive tasks and background services still have headroom. If this value is set too high, context switching, queue contention, and retry pressure can increase total wall-clock time rather than reduce it. Tune with real run metrics, especially files-per-second, average chunk latency, and failed-task retries.

    **Badges**:
    - Throughput tuning

    **Links**:
    - [GraphAnchor: Graph-Enhanced and Attention-Driven Retrieval for RAG](https://arxiv.org/abs/2601.16462)
    - [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)
    - [Docker CPU Resource Constraints](https://docs.docker.com/engine/containers/resource_constraints/)
    - [FAISS Documentation](https://faiss.ai/)

??? info "`indexing.parquet_extract_include_column_names` (`PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES`) — Parquet Include Column Names"
    **Category**: `indexing`

    When enabled, column headers are injected into extracted Parquet text so retrieval can align values with field semantics (for example, distinguishing `price` from `discount_price`). This generally improves schema-aware search and downstream answer grounding, especially for wide analytical tables. The downside is extra tokens and potentially noisier chunks if column names are verbose or system-generated. Keep this on by default for mixed tabular + natural-language corpora, then validate index size impact on large datasets.

    **Links**:
    - [TGR: Table Graph Reasoner for Dense Tables (arXiv 2026)](https://arxiv.org/abs/2601.08444)
    - [Apache Parquet Documentation](https://parquet.apache.org/docs/)
    - [DuckDB Parquet Overview](https://duckdb.org/docs/stable/data/parquet/overview)
    - [Polars scan_parquet API](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_parquet.html)

??? info "`indexing.parquet_extract_max_cell_chars` (`PARQUET_EXTRACT_MAX_CELL_CHARS`) — Parquet Extract Max Cell Chars"
    **Category**: `indexing`

    Upper bound for characters extracted from any single Parquet cell before truncation. This prevents rare long values (JSON blobs, stack traces, raw HTML, encoded payloads) from dominating chunk budgets and crowding out other rows. A low cap improves throughput and keeps chunks balanced, but may clip high-value context in long descriptive fields. Choose a cap that protects indexing stability while preserving enough per-cell signal for your query patterns.

    **Links**:
    - [Efficient Table Retrieval from Massive Data Lakes (arXiv 2026)](https://arxiv.org/abs/2602.07642)
    - [Apache Parquet Format Repository](https://github.com/apache/parquet-format)
    - [DuckDB Parquet Performance Tips](https://duckdb.org/docs/stable/data/parquet/tips)
    - [pandas.read_parquet Reference](https://pandas.pydata.org/docs/reference/api/pandas.read_parquet.html)

??? info "`indexing.parquet_extract_max_chars` (`PARQUET_EXTRACT_MAX_CHARS`) — Parquet Extract Max Chars"
    **Category**: `indexing`

    Global character budget for text extracted from one Parquet file during indexing. Once this threshold is reached, extraction stops (best effort), giving predictable upper bounds on memory, ingestion time, and index growth. This setting is critical for very large tables where full-file extraction is unnecessary or too expensive. Pair it with row limits and cell caps so your truncation strategy is intentional rather than accidental.

    **Links**:
    - [Scalable Tabular In-Context Learning (arXiv 2025)](https://arxiv.org/abs/2502.03147)
    - [Parquet Implementation Status](https://parquet.apache.org/docs/file-format/implementationstatus/)
    - [DuckDB Querying Parquet Files](https://duckdb.org/docs/stable/guides/file_formats/query_parquet)
    - [pyarrow.parquet.read_table Reference](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.read_table.html)

??? info "`indexing.parquet_extract_max_rows` (`PARQUET_EXTRACT_MAX_ROWS`) — Parquet Extract Max Rows"
    **Category**: `indexing`

    Best-effort cap on the number of rows read from a Parquet file during extraction. It is a coarse but effective control for ingestion cost when a dataset is too large to fully materialize into text. Higher values improve coverage and long-tail recall, while lower values reduce indexing time and memory pressure. If row order is meaningful (for example, temporal logs), this cap also determines which slice of data becomes searchable first.

    **Links**:
    - [Scalable Tabular In-Context Learning (arXiv 2025)](https://arxiv.org/abs/2502.03147)
    - [Polars scan_parquet API (row limiting)](https://docs.pola.rs/api/python/stable/reference/api/polars.scan_parquet.html)
    - [DuckDB Parquet Overview](https://duckdb.org/docs/stable/data/parquet/overview)
    - [pyarrow.parquet.read_table Reference](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.read_table.html)

??? info "`indexing.parquet_extract_text_columns_only` (`PARQUET_EXTRACT_TEXT_COLUMNS_ONLY`) — Parquet Text Columns Only"
    **Category**: `indexing`

    Controls whether the Parquet ingestion path indexes only text-like columns (strings, long text blobs, comments, descriptions) instead of every column in the table. Keeping this enabled usually improves retrieval quality because numeric IDs, sparse codes, and high-cardinality counters often add noise without helping semantic recall. For mixed analytics datasets, this setting is a cost and relevance lever: you reduce token volume, embedding spend, and index size while preserving the fields that actually answer natural-language questions. Disable it only when numeric or categorical columns are first-class search targets and you have evaluation evidence that broader indexing improves recall more than it harms precision.

    **Links**:
    - [Text-to-SQL in the Wild: Benchmarking LLMs on Semi-structured Tables (arXiv 2025)](https://arxiv.org/abs/2511.16134)
    - [Apache Parquet Documentation](https://parquet.apache.org/docs/)
    - [DuckDB Parquet Integration Overview](https://duckdb.org/docs/stable/data/parquet/overview)
    - [pandas read_parquet Reference](https://pandas.pydata.org/docs/reference/api/pandas.read_parquet.html)

??? info "`indexing.postgres_url` (`POSTGRES_URL`) — PostgreSQL URL"
    **Category**: `infrastructure`

    Connection DSN for the PostgreSQL control/state store: the corpus registry and per-corpus config, chunk rows with provenance, chunk summaries, and the semantic/embedding caches. Chunk rows carry no vectors; dense and sparse vectors live in Qdrant and Postgres records the dense and sparse contracts they were built under. Retrieval hydrates graph hits and neighbor chunks from these rows, so Postgres must stay reachable for every leg even though it no longer executes vector or full-text search.

    **Links**:
    - [Text2VectorSQL: Bridging SQL and Vector Retrieval (arXiv 2025)](https://arxiv.org/abs/2506.23071)
    - [PostgreSQL libpq Connection Strings](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING)
    - [PostgreSQL Connection Settings](https://www.postgresql.org/docs/current/runtime-config-connection.html)
    - [pgvector Extension (GitHub)](https://github.com/pgvector/pgvector)

??? info "`indexing.skip_dense` (`SKIP_DENSE`) — Skip Dense Embeddings"
    **Category**: `retrieval`

    When enabled, indexing skips dense embedding generation and writes sparse-only points to the corpus Qdrant generation, leaving the vector leg empty for that corpus while sparse and graph retrieval still work. Use it for corpora where lexical matching is sufficient or when the embedding runtime is unavailable; the corpus records `embedding_dimensions = 0` so a later dense run must be a full re-index. Neo4j chunk vectors are also skipped, so chunk-mode graph search needs a dense run.

    **Badges**:
    - Much faster
    - Keyword-only
    - No semantic search

    **Links**:
    - [Mixture of Retrieval (MoR): Integrating Sparse and Dense Retrieval for RAG (arXiv 2025)](https://arxiv.org/abs/2506.15862)
    - [PostgreSQL Full Text Search](https://www.postgresql.org/docs/current/textsearch.html)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [Search in PostgreSQL: Full Text Search (ParadeDB)](https://www.paradedb.com/learn/search-in-postgresql/full-text-search)
