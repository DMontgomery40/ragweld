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
| `reranking.reranker_cloud_model` | `RERANKER_CLOUD_MODEL` | `str` | `"openai.gpt-4.1-nano"` | — | Cloud reranker model when mode=cloud: a LiteLLM gateway alias for provider 'litellm' (a cheap non-reasoning instruct model is ideal), or a Cohere rerank model id for provider 'cohere'. |
| `reranking.reranker_cloud_provider` | `RERANKER_CLOUD_PROVIDER` | `str` | `"litellm"` | pattern=^(litellm\|cohere)$ | Cloud reranker provider when mode=cloud: 'litellm' scores candidates listwise through a LiteLLM gateway alias (no local model, no extra credential); 'cohere' calls the Cohere rerank API (COHERE_API_KEY). |
| `reranking.reranker_cloud_top_n` | `RERANKER_CLOUD_TOP_N` | `int` | `50` | ≥ 1, ≤ 200 | Number of candidates to rerank (cloud mode) |
| `reranking.reranker_mode` | `RERANKER_MODE` | `str` | `"none"` | pattern=^(cloud\|learning\|none)$ | Reranker mode: 'cloud' (LiteLLM gateway alias or Cohere API), 'learning' (MLX Qwen3 LoRA learning reranker), 'none' (disabled). Stale values such as 'local'/'hf' fail validation and must be migrated. |
| `reranking.reranker_timeout` | `RERANKER_TIMEOUT` | `int` | `10` | ≥ 5, ≤ 60 | Reranker API timeout (seconds) |
| `reranking.tribrid_reranker_alpha` | `TRIBRID_RERANKER_ALPHA` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Blend weight for reranker scores |
| `reranking.tribrid_reranker_batch` | `TRIBRID_RERANKER_BATCH` | `int` | `16` | ≥ 1, ≤ 128 | Reranker batch size |
| `reranking.tribrid_reranker_maxlen` | `TRIBRID_RERANKER_MAXLEN` | `int` | `512` | ≥ 128, ≤ 2048 | Max token length for reranker |
| `reranking.tribrid_reranker_reload_on_change` | `TRIBRID_RERANKER_RELOAD_ON_CHANGE` | `bool` | `false` | — | Hot-reload on model change |
| `reranking.tribrid_reranker_reload_period_sec` | `TRIBRID_RERANKER_RELOAD_PERIOD_SEC` | `int` | `60` | ≥ 10, ≤ 600 | Reload check period (seconds) |
| `reranking.tribrid_reranker_topn` | `TRIBRID_RERANKER_TOPN` | `int` | `50` | ≥ 10, ≤ 200 | Number of candidates to rerank (learning mode) |

### Details (glossary)

??? info "`reranking.rerank_input_snippet_chars` (`RERANK_INPUT_SNIPPET_CHARS`) — Rerank Snippet Length"
    **Category**: `reranking`

    `RERANK_INPUT_SNIPPET_CHARS` caps how many characters from each retrieved chunk are forwarded into reranker scoring. In implementation terms, this is a throughput and quality guardrail: smaller snippets reduce request size and latency, but risk truncating decisive evidence; larger snippets preserve context at the cost of higher tokenization load, longer inference, and potentially provider-side input-limit errors. The right value should be based on corpus structure and query style, then validated with offline ranking metrics plus p95 latency and cost tracking so you can find the smallest snippet size that preserves relevance quality.

    **Badges**:
    - Affects latency/cost
    - Context guardrail

    **Links**:
    - [BAR-RAG: Boundary-Aware Adaptive Retrieval for Better Reranking (arXiv)](https://arxiv.org/abs/2602.03689)
    - [Cohere Rerank Overview](https://docs.cohere.com/docs/rerank-overview)
    - [Voyage AI Reranker Docs](https://docs.voyageai.com/docs/reranker)
    - [Hugging Face Padding and Truncation](https://huggingface.co/docs/transformers/main/pad_truncation)

??? info "`reranking.reranker_cloud_model` (`RERANKER_CLOUD_MODEL`) — Cloud Model"
    **Category**: `reranking`

    The model the cloud reranker calls: a LiteLLM gateway alias for provider `litellm` (a cheap non-reasoning instruct model such as openai.gpt-4.1-nano keeps the listwise scoring fast and deterministic), or a Cohere rerank model id for provider `cohere`. This parameter directly controls the quality/latency/cost tradeoff of the rerank stage; the scores it returns are min-max normalized and blended with the fusion score by the reranker alpha.

    **Badges**:
    - Provider-scoped

    **Links**:
    - [InsertRank: Bias Mitigation in Rerankers (arXiv 2025)](https://arxiv.org/abs/2506.14086)
    - [Cohere Models Documentation](https://docs.cohere.com/docs/models)
    - [Voyage AI Reranker Docs](https://docs.voyageai.com/docs/reranker)
    - [Jina Reranker v2 Model Card](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual)

??? info "`reranking.reranker_cloud_provider` (`RERANKER_CLOUD_PROVIDER`) — Cloud Rerank Provider"
    **Category**: `reranking`

    Determines which remote service scores candidates when reranker mode is cloud. `litellm` (default) sends the query and the top-N candidate snippets in one request to a LiteLLM gateway alias and reads back a JSON array of 0-10 relevance scores in candidate order; it reuses the gateway credential, loads no local model, and is billed at the alias' token prices. `cohere` calls the Cohere rerank API with COHERE_API_KEY. Provider choice affects auth, rate limits, billing units and latency; a provider that cannot run (no gateway, unknown alias, missing key) is reported as a skipped rerank, never faked.

    **Badges**:
    - Requires API key

    **Links**:
    - [HyperRAG: Hybrid Retrieval-Augmented Generation (arXiv 2025)](https://arxiv.org/abs/2504.02921)
    - [Cohere Reranking Guide](https://docs.cohere.com/docs/reranking-with-cohere)
    - [Voyage AI Reranker Docs](https://docs.voyageai.com/docs/reranker)
    - [Jina Rerank Models via Elastic Open Inference API](https://www.elastic.co/search-labs/blog/jina-ai-embeddings-rerank-model-open-inference-api)

??? info "`reranking.reranker_cloud_top_n` (`RERANKER_CLOUD_TOP_N`) — Cloud Reranker Top-N"
    **Category**: `reranking`

    Limits how many first-pass candidates are sent into the cloud reranker. This is the main quality-cost control for API reranking: higher Top-N usually improves final precision/recall at the expense of latency and request cost. Tune it jointly with first-stage retrieval depth; a small Top-N can hide relevant documents before reranking ever sees them, while an oversized Top-N can waste budget on obvious non-matches. Start from an empirically measured knee point (quality gain flattening vs latency growth) rather than a fixed default.

    **Badges**:
    - Cloud API costs
    - Rate limits apply

    **Links**:
    - [RankFlow: Reranking Pipeline Optimization (arXiv 2025)](https://arxiv.org/abs/2502.00709)
    - [Cohere Rerank API (top_n parameter)](https://docs.cohere.com/reference/rerank)
    - [OpenSearch Rerank Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/rerank-processor/)
    - [LangChain Contextual Compression Retriever](https://api.python.langchain.com/en/latest/retrievers/langchain.retrievers.contextual_compression.ContextualCompressionRetriever.html)

??? info "`reranking.reranker_mode` (`RERANKER_MODE`) — Reranker Mode"
    **Category**: `reranking`

    Global switch for reranking behavior: `none` passes retrieval order through, `cloud` rescores the top-N candidates through a remote service (the LiteLLM gateway alias or Cohere), and `learning` uses the locally trained MLX Qwen3 LoRA reranker. Use `none` for lowest-latency baselines and `cloud` when you want a stronger ordering without loading a model on the host; every search logs whether the rerank was applied, skipped (with the reason) or failed.

    **Badges**:
    - Controls reranking behavior

    **Links**:
    - [MICE: Retrieval + Reranking Improvements (arXiv 2026)](https://arxiv.org/abs/2602.16299)
    - [Cohere Reranking Guide](https://docs.cohere.com/docs/reranking-with-cohere)
    - [Jina MLX Retrieval (Local Reranker Training/Serving)](https://github.com/jina-ai/mlx-retrieval)
    - [OpenSearch Rerank Processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/rerank-processor/)

??? info "`reranking.reranker_timeout` (`RERANKER_TIMEOUT`) — Reranker Timeout"
    **Category**: `reranking`

    Maximum wait time for cloud reranker requests before failing fast. This parameter protects end-to-end request latency and prevents queue pileups during provider slowdowns, but setting it too low can create false negatives under transient network variance. Tune timeout with retry policy and user-facing SLA in mind; timeout alone is not enough without fallback strategy (for example, use first-stage ranking when reranker times out). Track timeout rate by provider/model so you can distinguish systemic misconfiguration from temporary upstream degradation.

    **Badges**:
    - Reliability

    **Links**:
    - [MICE: Retrieval Pipeline Robustness (arXiv 2026)](https://arxiv.org/abs/2602.16299)
    - [HTTPX Timeouts Guide](https://www.python-httpx.org/advanced/timeouts/)
    - [Cohere Rerank API Reference](https://docs.cohere.com/reference/rerank)
    - [Voyage AI Reranker Docs](https://docs.voyageai.com/docs/reranker)

??? info "`reranking.tribrid_reranker_alpha` (`TRIBRID_RERANKER_ALPHA`) — Reranker Blend Alpha"
    **Category**: `general`

    Interpolation weight used when combining the reranker score with upstream hybrid retrieval score. In practical terms, this is the control for how much the final ranking trusts pairwise relevance modeling versus the broader BM25+dense candidate order. Raising alpha usually improves precision for well-formed queries, but if it is set too high the system can overfit to reranker biases and underweight lexical exact-match evidence. Tune it with fixed query sets and report both quality metrics (nDCG, MRR, grounded answer rate) and latency to avoid hidden regressions.

    **Badges**:
    - Affects ranking

    **Links**:
    - [Rethinking the Reranker: Boundary-Aware Evidence Selection (arXiv 2026)](https://arxiv.org/abs/2602.03689)
    - [AcuRank: Uncertainty-Aware Adaptive Computation for Listwise Reranking (arXiv 2025)](https://arxiv.org/abs/2505.18512)
    - [Elasticsearch Reciprocal Rank Fusion (RRF)](https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html)
    - [SentenceTransformers Cross-Encoder Reranker Training](https://www.sbert.net/examples/cross_encoder/training/rerankers/README.html)

??? info "`reranking.tribrid_reranker_batch` (`TRIBRID_RERANKER_BATCH`) — Reranker Batch Size (Inference)"
    **Category**: `general`

    Inference micro-batch size for reranker scoring over candidate documents. Larger batches can increase throughput and reduce per-item overhead on GPU, but memory pressure grows quickly with longer inputs and higher top-N. If this value is too aggressive you will see OOMs, allocator fragmentation, or latency spikes from retries and paging. Production tuning should sweep batch size jointly with max sequence length and candidate count, because these three parameters multiply into total token compute.

    **Badges**:
    - Tune for memory

    **Links**:
    - [AcuRank: Uncertainty-Aware Adaptive Computation for Listwise Reranking (arXiv 2025)](https://arxiv.org/abs/2505.18512)
    - [PyTorch DataLoader Reference](https://pytorch.org/docs/stable/data.html#torch.utils.data.DataLoader)
    - [SentenceTransformers Cross-Encoder Applications](https://www.sbert.net/examples/cross_encoder/applications/README.html)
    - [Hugging Face Transformers Padding and Truncation](https://huggingface.co/docs/transformers/main/pad_truncation)

??? info "`reranking.tribrid_reranker_maxlen` (`TRIBRID_RERANKER_MAXLEN`) — Reranker Max Sequence Length (Inference)"
    **Category**: `general`

    Maximum token budget for each query-document pair at rerank time. This parameter directly controls truncation behavior: small values improve speed and memory, while large values preserve long-context evidence at higher cost. For code and technical retrieval, quality gains usually plateau after a certain length unless queries depend on long-range context. Evaluate max length using long-tail queries, because overly short truncation tends to hide failures that only appear on long files and verbose documentation.

    **Badges**:
    - Performance sensitive

    **Links**:
    - [Query-focused and Memory-aware Reranker for Long Context Processing (arXiv 2026)](https://arxiv.org/abs/2602.12192)
    - [DeAR: Dual-Stage Document Reranking with Reasoning Agents (arXiv 2025)](https://arxiv.org/abs/2508.16998)
    - [Hugging Face Transformers Padding and Truncation](https://huggingface.co/docs/transformers/main/pad_truncation)
    - [SentenceTransformers Cross-Encoder Applications](https://www.sbert.net/examples/cross_encoder/applications/README.html)

??? info "`reranking.tribrid_reranker_reload_on_change` (`TRIBRID_RERANKER_RELOAD_ON_CHANGE`) — Reranker Auto-Reload"
    **Category**: `general`

    Toggles hot-reload behavior when the reranker model path changes at runtime. In development this shortens iteration loops because newly trained adapters can be activated without restarting the service. In production, uncontrolled auto-reload can introduce jitter, temporary cache invalidation, and model consistency issues across replicas. If enabled, pair it with health checks and staged rollout logic so reload events do not degrade retrieval latency or answer stability.

    **Badges**:
    - Development feature
    - Disable in production

    **Links**:
    - [AcuRank: Uncertainty-Aware Adaptive Computation for Listwise Reranking (arXiv 2025)](https://arxiv.org/abs/2505.18512)
    - [watchfiles Documentation (file change monitoring)](https://watchfiles.helpmanual.io/)
    - [PEFT Checkpoint Format and Loading](https://huggingface.co/docs/peft/developer_guides/checkpoint)
    - [Transformers from_pretrained() Model Loading](https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.from_pretrained)

??? info "`reranking.tribrid_reranker_topn` (`TRIBRID_RERANKER_TOPN`) — Reranker Top-N"
    **Category**: `general`

    Upper bound on how many retrieved candidates are passed into the reranker stage. Higher Top-N usually improves recall headroom because more borderline candidates are reconsidered, but reranker cost grows roughly linearly with this value. If set too low, relevant documents never reach reranking; if set too high, latency and GPU utilization can explode for little quality gain. Choose Top-N by plotting quality-latency curves and selecting the smallest value that keeps recall stable on hard queries.

    **Badges**:
    - Advanced RAG tuning
    - Affects latency

    **Links**:
    - [Rethinking the Reranker: Boundary-Aware Evidence Selection (arXiv 2026)](https://arxiv.org/abs/2602.03689)
    - [DeAR: Dual-Stage Document Reranking with Reasoning Agents (arXiv 2025)](https://arxiv.org/abs/2508.16998)
    - [Qdrant Reranking and Hybrid Search](https://qdrant.tech/documentation/search-precision/reranking-hybrid-search/)
    - [SentenceTransformers Cross-Encoder Reranker Training](https://www.sbert.net/examples/cross_encoder/training/rerankers/README.html)
