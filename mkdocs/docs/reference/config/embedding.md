# Config reference: `embedding`

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
| `embedding.auto_set_dimensions` | — | `bool` | `true` | — | When true, the UI auto-syncs embedding_dim from data/models.json when model changes. |
| `embedding.contextual_chunk_embeddings` | — | `Literal["off", "prepend_context", "late_chunking_local_only"]` | `"off"` | allowed="off", "prepend_context", "late_chunking_local_only" | Contextual chunk embedding mode. 'late_chunking_local_only' requires local/HF provider backend. |
| `embedding.embed_text_prefix` | — | `str` | `""` | — | Prefix added before chunk text prior to embedding (stable document context). |
| `embedding.embed_text_suffix` | — | `str` | `""` | — | Suffix added after chunk text prior to embedding. |
| `embedding.embedding_backend` | — | `Literal["deterministic", "provider"]` | `"deterministic"` | allowed="deterministic", "provider" | Embedding execution backend. 'deterministic' is offline/test-friendly; 'provider' calls real providers. |
| `embedding.embedding_batch_size` | `EMBEDDING_BATCH_SIZE` | `int` | `64` | ≥ 1, ≤ 256 | Batch size for embedding generation |
| `embedding.embedding_cache_enabled` | `EMBEDDING_CACHE_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable embedding cache |
| `embedding.embedding_dim` | `EMBEDDING_DIM` | `int` | `3072` | ≥ 128, ≤ 4096 | Embedding dimensions |
| `embedding.embedding_max_tokens` | `EMBEDDING_MAX_TOKENS` | `int` | `8000` | ≥ 512, ≤ 8192 | Max tokens per embedding chunk |
| `embedding.embedding_model` | `EMBEDDING_MODEL` | `str` | `"text-embedding-3-large"` | — | OpenAI embedding model |
| `embedding.embedding_model_local` | `EMBEDDING_MODEL_LOCAL` | `str` | `"all-MiniLM-L6-v2"` | — | Local SentenceTransformer model |
| `embedding.embedding_model_mlx` | `EMBEDDING_MODEL_MLX` | `str` | `"mlx-community/all-MiniLM-L6-v2-4bit"` | — | MLX-optimized embedding model (used when embedding_type=mlx) |
| `embedding.embedding_retry_max` | `EMBEDDING_RETRY_MAX` | `int` | `3` | ≥ 1, ≤ 5 | Max retries for embedding API |
| `embedding.embedding_timeout` | `EMBEDDING_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Embedding API timeout (seconds) |
| `embedding.embedding_type` | `EMBEDDING_TYPE` | `str` | `"openai"` | — | Embedding provider (dynamic - validated against models.json at runtime) |
| `embedding.input_truncation` | — | `Literal["error", "truncate_end", "truncate_middle"]` | `"truncate_end"` | allowed="error", "truncate_end", "truncate_middle" | What to do when text exceeds embedding/token limits. |
| `embedding.late_chunking_max_doc_tokens` | — | `int` | `8192` | ≥ 256, ≤ 65536 | Max tokens per document segment for local late chunking. |
| `embedding.voyage_model` | `VOYAGE_MODEL` | `str` | `"voyage-code-3"` | — | Voyage embedding model |

### Details (glossary)

??? info "`embedding.embedding_batch_size` (`EMBEDDING_BATCH_SIZE`) — Embedding Batch Size"
    **Category**: `embedding`

    Number of text chunks to embed in a single API call or local batch during indexing. Higher values (50-200) speed up indexing by reducing API round trips but may hit rate limits or memory constraints. Lower values (10-30) are safer but slower. For OpenAI/Voyage APIs, batching significantly reduces total indexing time. For local models, larger batches improve GPU utilization but require more VRAM. If indexing fails with rate limit or OOM errors, reduce this value.

    Recommended: 100-150 for API providers, 16-32 for local models (GPU), 4-8 for CPU-only.

    **Badges**:
    - Performance tuning
    - Watch rate limits

    **Links**:
    - [OpenAI Batch Embedding](https://platform.openai.com/docs/guides/embeddings/use-cases)
    - [Rate Limits](https://platform.openai.com/docs/guides/rate-limits)
    - [GPU Memory Management](https://huggingface.co/docs/transformers/en/perf_train_gpu_one)

??? info "`embedding.embedding_cache_enabled` (`EMBEDDING_CACHE_ENABLED`) — Embedding Cache"
    **Category**: `embedding`

    Cache embedding API results to disk to avoid re-computing vectors for identical text. Reduces API costs and speeds up reindexing. Disable only for debugging or when embeddings change frequently.

    **Links**:
    - [Caching Strategies](https://en.wikipedia.org/wiki/Cache_(computing))
    - [Embedding Best Practices](https://platform.openai.com/docs/guides/embeddings/use-cases)

??? info "`embedding.embedding_dim` (`EMBEDDING_DIM`) — Embedding Dimension"
    **Category**: `embedding`

    Vector dimensionality for MXBAI/local embedding models. Common sizes: 384 (fast, lower quality), 768 (balanced, recommended), 1024 (best quality, slower). Larger dimensions capture more semantic nuance but increase Qdrant storage requirements and query latency. Must match your embedding model's output size. Changing this requires full reindexing - vectors of different dimensions are incompatible.

    **Badges**:
    - Requires reindex
    - Affects storage

    **Links**:
    - [Vector Embeddings](https://en.wikipedia.org/wiki/Word_embedding)
    - [Dimensionality Tradeoffs](https://www.sbert.net/docs/pretrained_models.html#model-overview)
    - [Qdrant Vector Config](https://qdrant.tech/documentation/concepts/collections/#create-a-collection)

??? info "`embedding.embedding_max_tokens` (`EMBEDDING_MAX_TOKENS`) — Embedding Max Tokens"
    **Category**: `embedding`

    Maximum token length for text chunks sent to embedding models during indexing. Text exceeding this length is truncated by the tokenizer. Most embedding models support 512-8192 tokens. Longer limits preserve more context per chunk but increase embedding cost and processing time. Shorter limits are faster and cheaper but may lose semantic context for large functions/classes. Balance based on your average code chunk size and model capabilities.

    Recommended: 512 for most code (functions/methods), 1024 for documentation-heavy repos, 256 for ultra-fast indexing.

    **Badges**:
    - Affects cost
    - Context preservation

    **Links**:
    - [Tokenization Basics](https://huggingface.co/docs/transformers/main/en/tokenizer_summary)
    - [OpenAI Token Limits](https://platform.openai.com/docs/guides/embeddings/embedding-models)
    - [Voyage Limits](https://docs.voyageai.com/docs/embeddings#input-text)

??? info "`embedding.embedding_model` (`EMBEDDING_MODEL`) — Embedding Model (OpenAI)"
    **Category**: `embedding`

    OpenAI embedding model name when EMBEDDING_TYPE=openai. Current options: "text-embedding-3-small" (512-3072 dims, $0.02/1M tokens, fast), "text-embedding-3-large" (256-3072 dims, $0.13/1M tokens, highest quality), "text-embedding-ada-002" (legacy, 1536 dims, $0.10/1M tokens). Larger models improve semantic search quality but cost more and require more storage. Changing this requires full reindexing as embeddings are incompatible across models.

    Recommended: text-embedding-3-small for most use cases, text-embedding-3-large for production systems demanding highest quality.

    **Badges**:
    - Requires reindex
    - Costs API calls

    **Links**:
    - [OpenAI Embeddings Guide](https://platform.openai.com/docs/guides/embeddings)
    - [Embedding Models](https://platform.openai.com/docs/models/embeddings)
    - [Pricing Calculator](https://openai.com/api/pricing/)

??? info "`embedding.embedding_model_local` (`EMBEDDING_MODEL_LOCAL`) — Local Embedding Model"
    **Category**: `embedding`

    HuggingFace model name or local path when EMBEDDING_TYPE=local or mxbai. Popular options: "mixedbread-ai/mxbai-embed-large-v1" (1024 dims, excellent quality), "BAAI/bge-small-en-v1.5" (384 dims, fast), "sentence-transformers/all-MiniLM-L6-v2" (384 dims, lightweight). Local embeddings are free but slower than API-based options. Model is downloaded on first use and cached locally. Choose larger models (768-1024 dims) for quality or smaller (384 dims) for speed.

    Recommended: mxbai-embed-large-v1 for best free quality, all-MiniLM-L6-v2 for resource-constrained environments.

    **Badges**:
    - Free (no API)
    - Requires download

    **Links**:
    - [Sentence Transformers Models](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html)
    - [HuggingFace Model Hub](https://huggingface.co/models?pipeline_tag=feature-extraction&sort=downloads)
    - [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)

??? info "`embedding.embedding_model_mlx` (`EMBEDDING_MODEL_MLX`) — MLX Embedding Model"
    **Category**: `embedding`

    MLX model identifier when EMBEDDING_TYPE=mlx. Runs locally on Apple Silicon via MLX/Metal for very fast embedding inference. Default: "mlx-community/all-MiniLM-L6-v2-4bit". The model is downloaded on first use and cached locally. Changing this requires a full reindex (embeddings are not comparable across models).

    **Badges**:
    - Metal GPU
    - Free (no API)
    - Requires reindex

??? info "`embedding.embedding_retry_max` (`EMBEDDING_RETRY_MAX`) — Embedding Max Retries"
    **Category**: `embedding`

    Retry attempts for failed embedding API calls during indexing. Higher values ensure indexing completes despite transient errors but slow down failure recovery. Typical: 2-3 retries.

    **Links**:
    - [Error Handling](https://platform.openai.com/docs/guides/error-codes)
    - [Retry Patterns](https://en.wikipedia.org/wiki/Retry_pattern)

??? info "`embedding.embedding_timeout` (`EMBEDDING_TIMEOUT`) — Embedding Timeout"
    **Category**: `embedding`

    Maximum seconds to wait for embedding API response. Similar to GEN_TIMEOUT but for embedding calls during indexing. Increase for large batches or slow networks. Typical: 30-60 seconds.

    **Links**:
    - [API Timeouts](https://platform.openai.com/docs/guides/rate-limits)
    - [Embedding API](https://platform.openai.com/docs/api-reference/embeddings)

??? info "`embedding.embedding_type` (`EMBEDDING_TYPE`) — Embedding Provider"
    **Category**: `embedding`

    Selects the embedding provider for dense vector search. Also determines the token counter used during code chunking, which affects chunk boundaries and splitting behavior.

    • openai — strong quality, paid (cl100k tokenizer)
    • voyage — strong retrieval, paid (voyage tokenizer)
    • mlx — Apple Silicon local embeddings via MLX/Metal (fast)
    • mxbai — OSS via SentenceTransformers
    • local — any HuggingFace SentenceTransformer model
    • gemini — Google Gemini embeddings

    Note: Changing this setting affects both retrieval quality AND how code is split into chunks during indexing. A reindex is required after changing.

    **Badges**:
    - Requires reindex
    - Affects chunking

    **Links**:
    - [OpenAI Embeddings](https://platform.openai.com/docs/guides/embeddings)
    - [Voyage AI Embeddings](https://docs.voyageai.com/docs/embeddings)
    - [Google Gemini Embeddings](https://ai.google.dev/gemini-api/docs/embeddings)
    - [SentenceTransformers Docs](https://www.sbert.net/)

??? info "`embedding.voyage_model` (`VOYAGE_MODEL`) — Voyage Embedding Model"
    **Category**: `generation`

    Voyage AI embedding model when EMBEDDING_TYPE=voyage. Options: "voyage-code-2" (1536 dims, optimized for code, recommended), "voyage-3" (1024 dims, general-purpose, fast), "voyage-3-lite" (512 dims, budget option). Voyage models are specialized for code retrieval and often outperform OpenAI on technical queries. Code-specific models understand programming constructs, API patterns, and documentation better than general embeddings.

    Recommended: voyage-code-2 for code-heavy repos, voyage-3 for mixed content (code + docs).

    **Badges**:
    - Requires reindex
    - Code-optimized

    **Links**:
    - [Voyage Embeddings API](https://docs.voyageai.com/docs/embeddings)
    - [voyage-code-2 Details](https://docs.voyageai.com/docs/voyage-code-2)
    - [Model Comparison](https://docs.voyageai.com/docs/model-comparison)
