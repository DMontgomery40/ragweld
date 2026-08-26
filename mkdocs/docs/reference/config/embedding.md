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
| `embedding.embedding_cache_enabled` | `EMBEDDING_CACHE_ENABLED` | `bool` | `true` | — | Enable embedding cache |
| `embedding.embedding_dim` | `EMBEDDING_DIM` | `int` | `3072` | ≥ 128, ≤ 4096 | Embedding dimensions |
| `embedding.embedding_max_tokens` | `EMBEDDING_MAX_TOKENS` | `int` | `8000` | ≥ 512, ≤ 8192 | Max tokens per embedding chunk |
| `embedding.embedding_model` | `EMBEDDING_MODEL` | `str` | `"text-embedding-3-large"` | — | OpenAI embedding model |
| `embedding.embedding_model_local` | `EMBEDDING_MODEL_LOCAL` | `str` | `"BAAI/bge-small-en-v1.5"` | — | Local SentenceTransformer model |
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

    Controls how many chunks are embedded in each request or inference pass. Larger batches usually improve throughput by reducing per-request overhead and increasing accelerator utilization, but they raise peak memory pressure and can hit rate or timeout limits. Smaller batches are safer on constrained hosts and unstable networks but increase total indexing time. Tune this setting from observed throughput and error rates, not fixed defaults.

    **Badges**:
    - Throughput tuning

    **Links**:
    - [Hugging Face Text Embeddings Inference](https://huggingface.co/docs/text-embeddings-inference/index)
    - [Voyage embeddings docs](https://docs.voyageai.com/docs/embeddings)
    - [Qdrant points and upserts](https://qdrant.tech/documentation/concepts/points/)
    - [Dynamic batching for LLM throughput (2025)](https://arxiv.org/abs/2503.05248)

??? info "`embedding.embedding_cache_enabled` (`EMBEDDING_CACHE_ENABLED`) — Embedding Cache"
    **Category**: `embedding`

    Enables reuse of previously computed embeddings for identical normalized text, reducing repeated compute and API spend during reindex cycles. Cache hits are most beneficial when rerunning ingestion on mostly stable corpora or during iterative chunking tests. Cache keys should include model identifier, model revision, and preprocessing policy to prevent stale vectors from contaminating retrieval quality comparisons. Disable cache only when validating backend or model changes end-to-end.

    **Badges**:
    - Cost control

    **Links**:
    - [Redis client-side caching](https://redis.io/docs/latest/develop/use/client-side-caching/)
    - [Qdrant points and upserts](https://qdrant.tech/documentation/concepts/points/)
    - [Pinecone semantic search guide](https://docs.pinecone.io/guides/search/semantic-search)
    - [ContextPilot context reuse (2025)](https://arxiv.org/abs/2511.03475)

??? info "`embedding.embedding_dim` (`EMBEDDING_DIM`) — Embedding Dimension"
    **Category**: `embedding`

    Defines vector dimensionality in the index and must match model output exactly. Larger dimensions can preserve more semantic detail and improve hard-case recall, but they increase memory, storage, and approximate-nearest-neighbor compute cost. Smaller dimensions reduce cost and can speed search, especially when using embeddings designed for compression. Treat this as a quality-versus-efficiency control and rebenchmark whenever dimension changes.

    **Badges**:
    - Vector schema

    **Links**:
    - [Qdrant collections and vector size](https://qdrant.tech/documentation/concepts/collections/)
    - [Weaviate vector search concepts](https://weaviate.io/developers/weaviate/concepts/search/vector-search)
    - [SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html)
    - [Dimensionality reduction impact study (2025)](https://arxiv.org/abs/2508.17744)

??? info "`embedding.embedding_max_tokens` (`EMBEDDING_MAX_TOKENS`) — Embedding Max Tokens"
    **Category**: `embedding`

    This sets the maximum token count sent to the embedding model for each chunk. Content beyond the limit is truncated, so the value directly controls how much semantic evidence is preserved in each vector. Higher limits can improve recall for long code blocks and docs, but they increase indexing cost, latency, and the chance of mixing multiple topics into one embedding. Lower limits are cheaper and often cleaner semantically, but can drop critical tail context. Tune this against your chunk size distribution and monitor truncation rate so most chunks fit without clipping.

    **Badges**:
    - Affects cost

    **Links**:
    - [HiChunk (arXiv 2025)](https://arxiv.org/abs/2509.11552)
    - [OpenAI Cookbook: Embedding Long Inputs](https://github.com/openai/openai-cookbook/blob/main/examples/Embedding_long_inputs.ipynb)
    - [tiktoken README](https://github.com/openai/tiktoken/blob/main/README.md)
    - [Voyage Embeddings Docs](https://docs.voyageai.com/docs/embeddings)

??? info "`embedding.embedding_model` (`EMBEDDING_MODEL`) — Embedding Model (OpenAI)"
    **Category**: `embedding`

    This names the OpenAI embedding model used for indexing and query encoding when the OpenAI provider is selected. Model choice sets the quality, speed, vector shape options, and cost profile that downstream retrieval depends on. Because embedding spaces are model-specific, changing this value after indexing requires a full rebuild to keep similarity search valid. Treat model upgrades as versioned infrastructure changes: pin model ids, benchmark on your query set, and roll forward only with measured quality and latency impact. Avoid ad hoc switching between runs.

    **Badges**:
    - Requires reindex

    **Links**:
    - [jina-embeddings-v5-text (arXiv 2026)](https://arxiv.org/abs/2602.15547)
    - [OpenAI Cookbook: Get Embeddings](https://github.com/openai/openai-cookbook/blob/main/examples/Get_embeddings_from_dataset.ipynb)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)
    - [MTEB Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)

??? info "`embedding.embedding_model_local` (`EMBEDDING_MODEL_LOCAL`) — Local Embedding Model"
    **Category**: `embedding`

    This specifies the local embedding model (usually SentenceTransformers or Hugging Face) used when running without hosted embedding APIs. It is a core quality and performance lever: larger models often improve semantic recall but consume more memory and index slower. Different local models also use different dimensions and training objectives, so changing models requires reindexing. Pin exact model revisions to avoid drift across machines and CI jobs. Use your own benchmark queries to choose a model, since leaderboard rank alone may not match your codebase or domain vocabulary.

    **Badges**:
    - Local inference

    **Links**:
    - [jina-embeddings-v5-text (arXiv 2026)](https://arxiv.org/abs/2602.15547)
    - [mxbai-embed-large-v1 Model Card](https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1)
    - [BGE Small v1.5 Model Card](https://huggingface.co/BAAI/bge-small-en-v1.5)
    - [SentenceTransformers Pretrained Models](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html)

??? info "`embedding.embedding_model_mlx` (`EMBEDDING_MODEL_MLX`) — MLX Embedding Model"
    **Category**: `embedding`

    This sets the MLX-compatible embedding model used on Apple Silicon. MLX uses Metal-optimized kernels, so it can provide strong local throughput for private or offline indexing pipelines. As with every embedding backend, the model id and dimension define the vector space; changing either requires full reindexing to keep search comparable. Quantized variants can reduce memory and speed up inference, but you should validate recall on representative queries before adopting them broadly. Record model id and quantization in index metadata for reproducible builds.

    **Badges**:
    - Apple Silicon

    **Links**:
    - [jina-embeddings-v5-text (arXiv 2026)](https://arxiv.org/abs/2602.15547)
    - [MLX Repository](https://github.com/ml-explore/mlx)
    - [MLX Examples Repository](https://github.com/ml-explore/mlx-examples)
    - [mlx-community all-MiniLM-L6-v2-4bit](https://huggingface.co/mlx-community/all-MiniLM-L6-v2-4bit)

??? info "`embedding.embedding_retry_max` (`EMBEDDING_RETRY_MAX`) — Embedding Max Retries"
    **Category**: `embedding`

    This controls how many times the system retries a failed embedding call before marking the operation failed. It protects indexing from transient failures such as short network interruptions, temporary overload, and bursty rate-limit responses. Too few retries makes jobs brittle; too many retries can mask persistent faults and dramatically increase end-to-end indexing time. Pair this setting with exponential backoff and jitter so workers do not retry in synchronized waves. Track retry exhaustion in telemetry and fix root causes rather than continually raising the retry ceiling.

    **Badges**:
    - Reliability

    **Links**:
    - [MINES: Web API Invariant Anomaly Detection (arXiv 2025)](https://arxiv.org/abs/2512.06906)
    - [AWS Builders Library: Timeouts, Retries, Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
    - [Google Cloud Retry Strategy](https://cloud.google.com/storage/docs/retry-strategy)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)

??? info "`embedding.embedding_timeout` (`EMBEDDING_TIMEOUT`) — Embedding Timeout"
    **Category**: `embedding`

    This is the maximum wait time for an embedding request before the call is treated as failed. It defines how long indexing workers can block on slow upstream responses and strongly affects throughput under load. If timeout is too low, valid requests fail and trigger unnecessary retries; if too high, stuck calls reduce parallelism and delay incident detection. Tune this with retry count, concurrency, and observed p95 and p99 latency, not mean latency alone. Separate timeout profiles for interactive queries versus bulk indexing jobs when possible.

    **Badges**:
    - Latency control

    **Links**:
    - [LO2: Microservice API Anomaly Dataset (arXiv 2025)](https://arxiv.org/abs/2504.12067)
    - [AWS Builders Library: Timeouts, Retries, Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
    - [Google Cloud Retry Strategy](https://cloud.google.com/storage/docs/retry-strategy)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)

??? info "`embedding.embedding_type` (`EMBEDDING_TYPE`) — Embedding Provider"
    **Category**: `embedding`

    This selects the embedding backend family and therefore the core operating mode of retrieval: hosted API providers versus local inference runtimes. The choice drives quality, cost, privacy boundaries, tokenizer behavior, dimensionality, and operational dependencies such as network availability or local model files. Switching type usually changes vector space and requires reindexing to preserve ranking validity. Decide type at architecture level by balancing security and compliance constraints against latency and budget. Record provider and model together in index metadata so deployments remain reproducible.

    **Badges**:
    - Requires reindex

    **Links**:
    - [jina-embeddings-v5-text (arXiv 2026)](https://arxiv.org/abs/2602.15547)
    - [OpenAI Cookbook: Get Embeddings](https://github.com/openai/openai-cookbook/blob/main/examples/Get_embeddings_from_dataset.ipynb)
    - [Voyage Embeddings Docs](https://docs.voyageai.com/docs/embeddings)
    - [Gemini Embeddings Docs](https://ai.google.dev/gemini-api/docs/embeddings)

??? info "`embedding.voyage_model` (`VOYAGE_MODEL`) — Voyage Embedding Model"
    **Category**: `generation`

    Selects which Voyage embedding model generates vectors for indexing and retrieval. The model choice determines embedding behavior (for example code bias vs. general text behavior), output dimensionality, and operational cost/latency characteristics, so it directly affects both relevance quality and infra footprint.

    Change this deliberately and evaluate with a fixed benchmark query set. Because model changes alter vector semantics, switching models should be treated as a reindex event: regenerate vectors, rebuild the index, and compare recall@k, reranked precision, and p95 latency before promoting to production.

    **Badges**:
    - Requires reindex
    - Code-optimized

    **Links**:
    - [Llama-Embed-Nemotron-8B (arXiv 2025)](https://arxiv.org/abs/2511.07025)
    - [Voyage AI Embeddings API](https://docs.voyageai.com/docs/embeddings)
    - [Voyage Contextualized Chunk Embeddings](https://docs.voyageai.com/docs/contextualized-chunk-embeddings)
    - [Voyage AI FAQ](https://docs.voyageai.com/docs/faq)
