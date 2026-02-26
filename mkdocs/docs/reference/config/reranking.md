# Config reference: `reranking`

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

**Total parameters**: 12

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `reranking.rerank_input_snippet_chars` | `RERANK_INPUT_SNIPPET_CHARS` | `int` | `700` | ≥ 200, ≤ 2000 | Snippet chars for reranking input |
| `reranking.reranker_cloud_model` | `RERANKER_CLOUD_MODEL` | `str` | `"rerank-v3.5"` | — | Cloud reranker model name when mode=cloud (Cohere: rerank-v3.5) |
| `reranking.reranker_cloud_provider` | `RERANKER_CLOUD_PROVIDER` | `str` | `"cohere"` | — | Cloud reranker provider when mode=cloud (cohere, voyage, jina) |
| `reranking.reranker_cloud_top_n` | `RERANKER_CLOUD_TOP_N` | `int` | `50` | ≥ 1, ≤ 200 | Number of candidates to rerank (cloud mode) |
| `reranking.reranker_mode` | `RERANKER_MODE` | `str` | `"none"` | pattern=^(cloud\|local\|learning\|none)$ | Reranker mode: 'cloud' (Cohere/Voyage/Jina API), 'learning' (MLX Qwen3 LoRA learning reranker), 'none' (disabled). Legacy values 'local'/'hf' normalize to 'learning'. |
| `reranking.reranker_timeout` | `RERANKER_TIMEOUT` | `int` | `10` | ≥ 5, ≤ 60 | Reranker API timeout (seconds) |
| `reranking.tribrid_reranker_alpha` | `TRIBRID_RERANKER_ALPHA` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Blend weight for reranker scores |
| `reranking.tribrid_reranker_batch` | `TRIBRID_RERANKER_BATCH` | `int` | `16` | ≥ 1, ≤ 128 | Reranker batch size |
| `reranking.tribrid_reranker_maxlen` | `TRIBRID_RERANKER_MAXLEN` | `int` | `512` | ≥ 128, ≤ 2048 | Max token length for reranker |
| `reranking.tribrid_reranker_reload_on_change` | `TRIBRID_RERANKER_RELOAD_ON_CHANGE` | `int` | `0` | ≥ 0, ≤ 1 | Hot-reload on model change |
| `reranking.tribrid_reranker_reload_period_sec` | `TRIBRID_RERANKER_RELOAD_PERIOD_SEC` | `int` | `60` | ≥ 10, ≤ 600 | Reload check period (seconds) |
| `reranking.tribrid_reranker_topn` | `TRIBRID_RERANKER_TOPN` | `int` | `50` | ≥ 10, ≤ 200 | Number of candidates to rerank (learning mode) |

### Details (glossary)

??? info "`reranking.rerank_input_snippet_chars` (`RERANK_INPUT_SNIPPET_CHARS`) — Rerank Snippet Length"
    **Category**: `reranking`

    Maximum characters from each candidate chunk sent to the reranker. Keeps payloads within provider limits and focuses scoring on the most relevant prefix. Typical range: 400-1200 chars. Use 400-600 when providers reject long inputs or latency is critical; 800-1200 when answers depend on longer doc/context blocks. If set too low, quality drops from missing context; too high increases latency and rerank cost per request.

    **Badges**:
    - Affects latency/cost
    - Context guardrail

    **Links**:
    - [Voyage reranker token limits](https://docs.voyageai.com/docs/reranker)
    - [Cohere rerank context length](https://docs.cohere.com/docs/rerank)

??? info "`reranking.reranker_cloud_model` (`RERANKER_CLOUD_MODEL`) — Cloud Model"
    **Category**: `reranking`

    Provider-scoped rerank model id from models.json. Examples: rerank-3.5 (cohere), rerank-2 (voyage), or any custom id you add. Model list comes from models.json; add entries there to surface more options in this picker.

    **Badges**:
    - Provider-scoped

??? info "`reranking.reranker_cloud_provider` (`RERANKER_CLOUD_PROVIDER`) — Cloud Rerank Provider"
    **Category**: `reranking`

    When RERANKER_MODE=cloud, specifies which API provider to use for reranking. Options: cohere, voyage, jina. Each provider has different pricing and model options—see models.json for available models. Requires the corresponding API key (COHERE_API_KEY, VOYAGE_API_KEY, etc.).

    **Badges**:
    - Requires API key

    **Links**:
    - [Cohere Rerank](https://docs.cohere.com/reference/rerank)
    - [Voyage Rerank](https://docs.voyageai.com/docs/reranker)
    - [Jina Rerank](https://jina.ai/reranker/)

??? info "`reranking.reranker_cloud_top_n` (`RERANKER_CLOUD_TOP_N`) — Cloud Reranker Top-N"
    **Category**: `reranking`

    Maximum number of candidates to send to cloud reranking APIs (Cohere, Voyage, Jina). Cloud rerankers have rate limits and per-request pricing, so this setting is separate from the learning reranker top-N. Lower values reduce API costs and stay within rate limits. Higher values improve recall but increase costs per query.

    • Typical range: 20-100 candidates
    • Cost-conscious: 20-30 for budget limits
    • Balanced default: 50 for most workloads
    • High recall: 80-100 for exploratory queries
    • Note: Cloud reranking is billed per candidate, so monitor costs

    **Badges**:
    - Cloud API costs
    - Rate limits apply

    **Links**:
    - [Cohere Rerank API](https://docs.cohere.com/reference/rerank)
    - [Voyage Rerank](https://docs.voyageai.com/docs/reranker)

??? info "`reranking.reranker_mode` (`RERANKER_MODE`) — Reranker Mode"
    **Category**: `reranking`

    Controls which reranking approach is used.

    • none: Disabled—BM25 + vector fusion only (no reranker scoring).
    • learning: Trainable learning reranker (MLX Qwen3 LoRA).
    • cloud: External API reranking (Cohere, Voyage, Jina).

    Legacy values:
    • local / hf: normalized to "learning" for backward compatibility.

    Recommended: Start with "learning" if you want the system to adapt over time; use "cloud" for managed quality if you have an API budget.

    **Badges**:
    - Controls reranking behavior

??? info "`reranking.reranker_timeout` (`RERANKER_TIMEOUT`) — Reranker Timeout"
    **Category**: `reranking`

    Timeout (seconds) for cloud reranker HTTP calls. Larger timeouts reduce false failures on slow providers; smaller timeouts fail fast when endpoints are slow or unreachable. Applies only to cloud backends.

    **Badges**:
    - Reliability

??? info "`reranking.tribrid_reranker_alpha` (`TRIBRID_RERANKER_ALPHA`) — Reranker Blend Alpha"
    **Category**: `general`

    Weight of the learning reranker score during final fusion. Higher alpha prioritizes pairwise reranker scoring; lower alpha relies more on initial hybrid retrieval (BM25 + dense). Typical range 0.6–0.8. Increasing alpha can improve ordering for nuanced queries but may surface false positives if your reranker is undertrained.

    **Badges**:
    - Affects ranking

    **Links**:
    - [Reciprocal Rank Fusion (RRF)](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
    - [Hybrid Retrieval Concepts](https://qdrant.tech/articles/hybrid-search/)

??? info "`reranking.tribrid_reranker_batch` (`TRIBRID_RERANKER_BATCH`) — Reranker Batch Size (Inference)"
    **Category**: `general`

    Batch size used when scoring candidates during rerank. Higher values reduce latency but increase memory. If you see OOM or throttling, lower this value.

    **Badges**:
    - Tune for memory

    **Links**:
    - [Batching Techniques](https://huggingface.co/docs/transformers/v4.44.2/en/perf_train_gpu_one#use-mixed-precision)
    - [Latency vs Throughput](https://en.wikipedia.org/wiki/Batch_processing)

??? info "`reranking.tribrid_reranker_maxlen` (`TRIBRID_RERANKER_MAXLEN`) — Reranker Max Sequence Length (Inference)"
    **Category**: `general`

    Maximum token length for each (query, text) pair during live reranking. Larger values increase memory/cost and may not improve quality beyond ~256–384 tokens for code. Use higher values for long comments/docs; lower for tight compute budgets.

    **Badges**:
    - Performance sensitive

    **Links**:
    - [Transformers Tokenization](https://huggingface.co/docs/transformers/main/en/tokenizer_summary)
    - [Sequence Length vs Memory](https://huggingface.co/docs/transformers/perf_train_gpu_one)

??? info "`reranking.tribrid_reranker_reload_on_change` (`TRIBRID_RERANKER_RELOAD_ON_CHANGE`) — Reranker Auto-Reload"
    **Category**: `general`

    Automatically reload the learning reranker artifact when `training.tribrid_reranker_model_path` changes during runtime (1=yes, 0=no). When enabled, the system detects adapter directory changes and hot-reloads the new weights without a server restart. Useful during development and in Training Studio workflows when promoting or swapping artifacts.

    Recommended: 1 for development/testing, 0 for production deployments.

    **Badges**:
    - Development feature
    - Disable in production

    **Links**:
    - [Hot Reload Patterns](https://en.wikipedia.org/wiki/Hot_swapping)

??? info "`reranking.tribrid_reranker_topn` (`TRIBRID_RERANKER_TOPN`) — Reranker Top-N"
    **Category**: `general`

    Maximum number of candidates to pass through the reranker stage during retrieval. After hybrid fusion (BM25 + dense), the top-N candidates are reranked using pairwise scoring before final selection. Higher values (50-100) can improve quality by considering more candidates but increase reranking latency and compute cost. Lower values (20-30) are faster but may miss items that scored poorly in initial retrieval but would rank highly after reranking.

    Sweet spot: 40-60 for most use cases. Use 60-80 for complex queries where initial ranking may be noisy. Use 20-40 for tight latency budgets or when initial hybrid retrieval is already high-quality.

    Note: MLX Qwen3 reranking can be significantly slower per candidate than smaller rerankers. If you care about interactive latency, start with 20–30 and measure.

    • Typical range: 20-80 candidates
    • Balanced default: 40-50 for most workloads
    • High recall: 60-80 for exploratory queries
    • Low latency: 20-30 for speed-critical apps

    **Badges**:
    - Advanced RAG tuning
    - Affects latency

    **Links**:
    - [Reranking in RAG](https://arxiv.org/abs/2407.21059)
    - [Hybrid Search + Rerank](https://qdrant.tech/articles/hybrid-search/)
