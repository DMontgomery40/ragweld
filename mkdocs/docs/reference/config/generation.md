# Config reference: `generation`

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

**Total parameters**: 20

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `generation.enrich_backend` | `ENRICH_BACKEND` | `str` | `"openai"` | pattern=^(openai\|ollama\|mlx)$ | Enrichment backend |
| `generation.enrich_disabled` | `ENRICH_DISABLED` | `int` | `0` | ≥ 0, ≤ 1 | Disable code enrichment |
| `generation.enrich_model` | `ENRICH_MODEL` | `str` | `"gpt-4o-mini"` | — | Model for code enrichment |
| `generation.enrich_model_ollama` | `ENRICH_MODEL_OLLAMA` | `str` | `""` | — | Ollama enrichment model |
| `generation.gen_backend` | `GEN_BACKEND` | `str` | `"openai"` | pattern=^(openai\|anthropic\|ollama\|mlx\|openrouter)$ | Provider backend for gen_model and channel overrides |
| `generation.gen_max_tokens` | `GEN_MAX_TOKENS` | `int` | `2048` | ≥ 100, ≤ 8192 | Max tokens for generation |
| `generation.gen_model` | `GEN_MODEL` | `str` | `"gpt-4o-mini"` | — | Primary generation model |
| `generation.gen_model_cli` | `GEN_MODEL_CLI` | `str` | `"qwen3-coder:14b"` | — | CLI generation model |
| `generation.gen_model_http` | `GEN_MODEL_HTTP` | `str` | `""` | — | HTTP transport generation model override |
| `generation.gen_model_mcp` | `GEN_MODEL_MCP` | `str` | `""` | — | MCP transport generation model override |
| `generation.gen_model_ollama` | `GEN_MODEL_OLLAMA` | `str` | `"qwen3-coder:30b"` | — | Ollama generation model |
| `generation.gen_retry_max` | `GEN_RETRY_MAX` | `int` | `2` | ≥ 1, ≤ 5 | Max retries for generation |
| `generation.gen_temperature` | `GEN_TEMPERATURE` | `float` | `0.0` | ≥ 0.0, ≤ 2.0 | Generation temperature |
| `generation.gen_timeout` | `GEN_TIMEOUT` | `int` | `60` | ≥ 10, ≤ 300 | Generation timeout (seconds) |
| `generation.gen_top_p` | `GEN_TOP_P` | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Nucleus sampling threshold |
| `generation.ollama_num_ctx` | `OLLAMA_NUM_CTX` | `int` | `8192` | ≥ 2048, ≤ 32768 | Context window for Ollama |
| `generation.ollama_request_timeout` | `OLLAMA_REQUEST_TIMEOUT` | `int` | `300` | ≥ 30, ≤ 1200 | Maximum total time to wait for a local (Ollama) generation request to complete (seconds) |
| `generation.ollama_stream_idle_timeout` | `OLLAMA_STREAM_IDLE_TIMEOUT` | `int` | `60` | ≥ 5, ≤ 300 | Maximum idle time allowed between streamed chunks from local (Ollama) during generation (seconds) |
| `generation.ollama_url` | `OLLAMA_URL` | `str` | `"http://127.0.0.1:11434/api"` | — | Ollama API URL |
| `generation.openai_base_url` | `OPENAI_BASE_URL` | `str` | `""` | — | OpenAI API base URL override (for proxies) |

### Details (glossary)

??? info "`generation.enrich_backend` (`ENRICH_BACKEND`) — Enrichment Backend"
    **Category**: `general`

    This chooses the runtime that generates enrichment metadata during indexing, such as chunk summaries, tags, and semantic hints. Backend choice changes quality, latency, cost, privacy posture, and operational complexity, so it can materially alter downstream retrieval and reranking behavior. Hosted backends generally reduce ops burden and may provide stronger quality, while local backends can improve data control and predictable marginal cost. Treat backend changes like model migrations: version prompts and settings, then rerun evaluation before production rollout. Do not assume enrichment outputs are interchangeable across backends.

    **Badges**:
    - Index pipeline

    **Links**:
    - [Meta-RAG on Large Codebases Using Code Summarization (arXiv 2025)](https://arxiv.org/abs/2508.02611)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)
    - [Ollama API Docs](https://github.com/ollama/ollama/blob/main/docs/api.md)
    - [MLX Repository](https://github.com/ml-explore/mlx)

??? info "`generation.enrich_disabled` (`ENRICH_DISABLED`) — Disable Enrichment"
    **Category**: `general`

    This switch disables enrichment generation entirely during indexing. It is useful for fast iteration, low-cost development cycles, and emergency backfills where raw embedding retrieval is acceptable. The cost of disabling is reduced semantic metadata for reranking, cards, and explanatory UX features, which can lower answer quality on abstract or architecture-level questions. Use it intentionally and record when it is active so benchmark comparisons remain meaningful. A common pattern is enrichment disabled for local loops and enabled for production-grade index builds.

    **Badges**:
    - Faster indexing

    **Links**:
    - [Not All Tokens Matter: Efficient Code Summarization (arXiv 2026)](https://arxiv.org/abs/2601.20147)
    - [Ollama README](https://github.com/ollama/ollama/blob/main/README.md)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)
    - [MLX Repository](https://github.com/ml-explore/mlx)

??? info "`generation.enrich_model` (`ENRICH_MODEL`) — Enrichment Model"
    **Category**: `generation`

    This selects the exact model used by the configured enrichment backend. It is the main lever on the quality versus cost versus throughput tradeoff for generated summaries and keywords. Higher-capability models can improve semantic signals for reranking and explanation quality, while lighter models reduce expense and indexing time. Even without changing embeddings, enrichment model swaps can shift retrieval outcomes, so they should be benchmarked and version-controlled. Pin model ids and evaluate outputs on representative repositories before adopting changes in production pipelines.

    **Badges**:
    - Affects quality/cost

    **Links**:
    - [Code vs Serialized AST Inputs for Code Summarization (arXiv 2026)](https://arxiv.org/abs/2602.06671)
    - [EyeLayer: Human Attention for Code Summarization (arXiv 2026)](https://arxiv.org/abs/2602.22368)
    - [openai-python API Reference](https://github.com/openai/openai-python/blob/main/api.md)
    - [Ollama API Docs](https://github.com/ollama/ollama/blob/main/docs/api.md)

??? info "`generation.enrich_model_ollama` (`ENRICH_MODEL_OLLAMA`) — Enrichment Model (Ollama)"
    **Category**: `generation`

    Selects the local Ollama model used for enrichment steps such as code-card expansion, metadata extraction, and structure-aware summaries before retrieval. This choice is a quality versus latency tradeoff: larger coder models usually produce richer symbols and relationships, while smaller models reduce indexing time and hardware pressure. Keep the selected model pinned to an explicit tag so enrichment output stays reproducible across rebuilds. In production, validate the model on a fixed enrichment sample set and monitor drift in extracted fields after model upgrades.

    **Badges**:
    - Local model tuning

    **Links**:
    - [rStar-Coder (arXiv)](https://arxiv.org/abs/2505.21297)
    - [Ollama Documentation](https://docs.ollama.com/)
    - [Ollama Model Library](https://ollama.com/library)
    - [Ollama Quickstart](https://github.com/ollama/ollama#quickstart)

??? info "`generation.gen_backend` (`GEN_BACKEND`) — Generation Backend"
    **Category**: `generation`

    Generation backend selects the provider stack that executes model calls, which affects auth, parameter semantics, rate limits, timeouts, and tool-calling behavior. Treat backend choice as an operational contract, not a cosmetic model switch. In RAG systems, keep backend-specific defaults normalized so output length, safety behavior, and citation style stay predictable across providers. If you support multiple backends, define a deterministic fallback order and record backend metadata in logs for incident triage. Backend heterogeneity without observability is a common source of inconsistent answer quality.

    **Badges**:
    - Provider routing

    **Links**:
    - [Universal Model Routing for Efficient LLM Inference (arXiv 2025)](https://arxiv.org/abs/2502.08773)
    - [OpenAI Python SDK](https://github.com/openai/openai-python)
    - [Anthropic Claude Models](https://docs.anthropic.com/en/docs/about-claude/models)
    - [Ollama API Reference](https://github.com/ollama/ollama/blob/main/docs/api.md)

??? info "`generation.gen_max_tokens` (`GEN_MAX_TOKENS`) — Max Tokens"
    **Category**: `generation`

    This is the upper bound on generated output length per request. In RAG, it directly controls cost and latency, but also determines whether answers can include full reasoning, citations, and edge-case handling without truncation. Set defaults by task class instead of one global value, then enforce stricter caps on interactive channels to protect tail latency. Pair this with context packing and answer format constraints so tokens are spent on grounded content rather than repetition. Monitor both truncation frequency and response quality, because either metric alone can hide a bad token budget.

    **Badges**:
    - Cost and latency

    **Links**:
    - [TimeBill: Time-Budgeted Inference for LLMs (arXiv 2025)](https://arxiv.org/abs/2512.21859)
    - [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
    - [Gemini Token Counting](https://ai.google.dev/gemini-api/docs/tokens)
    - [OpenAI Cookbook: Count Tokens with tiktoken](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_count_tokens_with_tiktoken.ipynb)

??? info "`generation.gen_model` (`GEN_MODEL`) — Generation Model"
    **Category**: `generation`

    This is the primary model used to synthesize answers from retrieved context, and it dominates quality, latency, and cost behavior. Choose it with workload-specific evaluation sets, not leaderboard intuition, because retrieval quality and prompt structure can change model rankings. Version model IDs explicitly so experiments are reproducible and regressions can be traced. Re-evaluate whenever provider releases shift default behavior, even if API names stay stable. Good retrieval can still underperform if the generation model is misaligned with your task style and response requirements.

    **Badges**:
    - Primary quality lever

    **Links**:
    - [Lookahead Routing for Large Language Models (arXiv 2025)](https://arxiv.org/abs/2510.19506)
    - [OpenAI Python SDK](https://github.com/openai/openai-python)
    - [Anthropic Claude Models](https://docs.anthropic.com/en/docs/about-claude/models)
    - [OpenRouter Provider Selection](https://openrouter.ai/docs/guides/routing/provider-selection)

??? info "`generation.gen_model_cli` (`GEN_MODEL_CLI`) — CLI Channel Model"
    **Category**: `generation`

    This override selects a model specifically for CLI sessions, which are usually iterative and speed-sensitive. Using a smaller or local model here can improve developer feedback loops while keeping production channels on a higher-capability model. Keep retrieval stack and system prompts aligned across channels so CLI debugging reflects real behavior. Log the active CLI model in run metadata to make test results reproducible. Use this for workflow optimization, not as an untracked fork of application behavior.

    **Badges**:
    - Developer workflow

    **Links**:
    - [Universal Model Routing for Efficient LLM Inference (arXiv 2025)](https://arxiv.org/abs/2502.08773)
    - [Ollama Quickstart](https://github.com/ollama/ollama#quickstart)
    - [LiteLLM Router](https://docs.litellm.ai/docs/routing)
    - [OpenAI Python SDK](https://github.com/openai/openai-python)

??? info "`generation.gen_model_http` (`GEN_MODEL_HTTP`) — HTTP Channel Model"
    **Category**: `generation`

    This override controls model selection for HTTP/API traffic, where SLOs, concurrency, and cost controls are usually stricter than interactive internal use. It enables channel-specific governance, such as serving public endpoints with stable low-variance models while reserving premium models for internal workflows. Treat changes here as API behavior changes and validate with canary rollouts. Align timeout and retry policies to the chosen model because latency profile varies significantly by provider and model class. Clear fallback order prevents unpredictable responses during upstream incidents.

    **Badges**:
    - API channel

    **Links**:
    - [Lookahead Routing for Large Language Models (arXiv 2025)](https://arxiv.org/abs/2510.19506)
    - [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
    - [LiteLLM Router](https://docs.litellm.ai/docs/routing)
    - [OpenRouter Provider Selection](https://openrouter.ai/docs/guides/routing/provider-selection)

??? info "`generation.gen_model_mcp` (`GEN_MODEL_MCP`) — MCP Channel Model"
    **Category**: `generation`

    This override applies to MCP tool-invocation paths, where requests are structured and often latency-sensitive. A lighter model can be sufficient for tool selection and argument construction, reducing spend without degrading end-to-end quality. Prioritize schema adherence and tool-call reliability over open-ended generation fluency in this channel. Validate with tool-call success rate, argument validity, and recovery behavior after tool errors. If tool use regresses while chat quality remains stable, this override is the first place to inspect.

    **Badges**:
    - Tool channel

    **Links**:
    - [INFERENCEDYNAMICS: Efficient Routing Across LLMs (arXiv 2025)](https://arxiv.org/abs/2505.16303)
    - [Model Context Protocol Introduction](https://modelcontextprotocol.io/introduction)
    - [Model Context Protocol Specification (2025-06-18)](https://modelcontextprotocol.io/specification/2025-06-18)
    - [MCP Transport Specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)

??? info "`generation.gen_model_ollama` (`GEN_MODEL_OLLAMA`) — Generation Model (Ollama)"
    **Category**: `generation`

    `GEN_MODEL_OLLAMA` selects the concrete local model tag used when generation is routed through Ollama instead of a hosted provider. In this configuration family, the default is `qwen3-coder:30b`, and changing it directly affects response quality, latency, memory pressure, and token-context behavior for all generation calls that use the Ollama path. Use explicit model tags and keep them consistent across environments so evaluation runs remain reproducible and regressions can be traced to model changes rather than retrieval or prompt drift. When updating this value, validate compatibility with your configured context and timeout settings before promoting to shared environments.

    **Links**:
    - [Production-Grade Local LLM Inference on Apple Silicon: A Comparative Study of MLX, MLC-LLM, Ollama, llama.cpp, and PyTorch (arXiv)](https://arxiv.org/abs/2511.05502)
    - [Ollama API Reference (repo docs)](https://github.com/ollama/ollama/blob/main/docs/api.md)
    - [Ollama Modelfile Reference](https://github.com/ollama/ollama/blob/main/docs/modelfile.mdx)
    - [Ollama Context Length Guide](https://github.com/ollama/ollama/blob/main/docs/context-length.mdx)

??? info "`generation.gen_retry_max` (`GEN_RETRY_MAX`) — Generation Max Retries"
    **Category**: `generation`

    This sets how many times generation requests are retried after transient failures such as rate limits or temporary backend faults. Higher values can improve success rate but also increase latency and amplify traffic during outages if backoff is weak. Use bounded retries with exponential backoff and jitter, and track request IDs to avoid accidental duplicate side effects. Interactive channels usually need fewer retries than background jobs. If retries are frequent but final success stays low, reduce retries and fix timeout, routing, or provider health first.

    **Badges**:
    - Resilience

    **Links**:
    - [KevlarFlow: Resiliency in LLM Serving (arXiv 2026)](https://arxiv.org/abs/2601.22438)
    - [OpenAI Cookbook: Handle Rate Limits](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_handle_rate_limits.ipynb)
    - [Anthropic API Errors](https://docs.anthropic.com/en/api/errors)
    - [LiteLLM Reliability and Fallbacks](https://docs.litellm.ai/docs/proxy/reliability)

??? info "`generation.gen_temperature` (`GEN_TEMPERATURE`) — Default Response Creativity"
    **Category**: `generation`

    Temperature controls sampling randomness. In retrieval-grounded QA, lower values usually improve consistency and factual stability, while higher values increase stylistic variation and drift risk. Keep defaults low for technical explanations, debugging steps, and config guidance where repeatability matters. Raise it only for explicitly creative tasks and monitor variance across repeated runs of the same query. If answer facts change across retries with identical context, temperature is likely set too high for your use case.

    **Badges**:
    - Sampling control

    **Links**:
    - [Learning Temperature Policy from LLM Internal States (arXiv 2026)](https://arxiv.org/abs/2602.13035)
    - [Anthropic Prompt Engineering: Use Temperature](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/use-temperature)
    - [Hugging Face Text Generation Parameters](https://huggingface.co/docs/transformers/main_classes/text_generation)
    - [OpenAI Cookbook: Formatting Chat Inputs](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_format_inputs_to_ChatGPT_models.ipynb)

??? info "`generation.gen_timeout` (`GEN_TIMEOUT`) — Generation Timeout"
    **Category**: `generation`

    Timeout sets the maximum wait for generation before the request is aborted. This is a reliability boundary that protects workers and users during provider slowdowns; too low causes false failures, too high causes queue buildup and cascading retries. Tune it by model class and expected output length, then enforce stricter limits for interactive paths. Combine timeout with retry policy so slow requests do not create retry storms. Rising timeout rates usually indicate context bloat, backend saturation, or routing misconfiguration rather than a need for unlimited timeout.

    **Badges**:
    - SLO guardrail

    **Links**:
    - [KevlarFlow: Resiliency in LLM Serving (arXiv 2026)](https://arxiv.org/abs/2601.22438)
    - [LiteLLM Timeout Controls](https://docs.litellm.ai/docs/proxy/timeout)
    - [LiteLLM Reliability and Fallbacks](https://docs.litellm.ai/docs/proxy/reliability)
    - [Anthropic API Errors](https://docs.anthropic.com/en/api/errors)

??? info "`generation.gen_top_p` (`GEN_TOP_P`) — Top-P (Nucleus Sampling)"
    **Category**: `generation`

    Top-p applies nucleus sampling by limiting choices to the smallest token set whose cumulative probability reaches p. Lower values narrow the candidate set and improve determinism, while higher values increase lexical diversity. In RAG answers, top-p is usually tuned with temperature; high values for both can increase hallucination risk even with good retrieval context. Keep top-p conservative for technical and policy-sensitive responses. When troubleshooting unstable outputs, reduce top-p before redesigning prompts so you isolate sampling entropy effects first.

    **Badges**:
    - Sampling control

    **Links**:
    - [Top-H Decoding: Bounded Entropy Text Generation (arXiv 2025)](https://arxiv.org/abs/2509.02510)
    - [Hugging Face Text Generation Parameters](https://huggingface.co/docs/transformers/main_classes/text_generation)
    - [Anthropic Messages API](https://docs.anthropic.com/en/api/messages)
    - [OpenAI Cookbook: Formatting Chat Inputs](https://github.com/openai/openai-cookbook/blob/main/examples/How_to_format_inputs_to_ChatGPT_models.ipynb)

??? info "`generation.ollama_num_ctx` (`OLLAMA_NUM_CTX`) — Ollama Context Window"
    **Category**: `generation`

    Ollama `num_ctx` sets the maximum context tokens used per generation request, directly affecting both quality headroom and memory footprint. Higher values let you include more retrieved evidence and longer instructions, but they increase KV-cache pressure and can reduce throughput on constrained hardware. Tune this parameter from measured prompt composition (system + query + retrieved chunks + expected answer) rather than guessing. If requests regularly approach the ceiling, improve chunk selection and compression before simply raising `num_ctx`, because blindly increasing window size can destabilize latency.

    **Links**:
    - [ParisKV: KV-Cache Compression for Long-Context LLMs (arXiv 2026)](https://arxiv.org/abs/2602.07721)
    - [Ollama Context Length](https://docs.ollama.com/context-length)
    - [Ollama Modelfile Reference](https://docs.ollama.com/modelfile)
    - [Ollama FAQ](https://docs.ollama.com/faq)

??? info "`generation.ollama_request_timeout` (`OLLAMA_REQUEST_TIMEOUT`) — Local Request Timeout (seconds)"
    **Category**: `generation`

    Ollama request timeout is the hard client-side budget for a full generation call, including model warmup, first-token delay, and decode time. Set it too low and valid long-context responses fail prematurely; set it too high and stalled calls tie up worker capacity and degrade system responsiveness. Calibrate timeout from observed p95/p99 latency per model and hardware profile, and revisit after model swaps or context-window changes. Use streaming plus clear retry/abort policy so timeout behavior remains predictable during spikes.

    **Links**:
    - [Efficient Multi-Adapter LLM Serving via Cross-Model KV-Cache Reuse (arXiv 2025)](https://arxiv.org/abs/2512.17910)
    - [Ollama Generate API](https://docs.ollama.com/api/generate)
    - [Ollama Streaming API](https://docs.ollama.com/api/streaming)
    - [vLLM Multi-LoRA Serving and Latency Metrics (2026)](https://blog.vllm.ai/2026/02/26/multi-lora.html)

??? info "`generation.ollama_stream_idle_timeout` (`OLLAMA_STREAM_IDLE_TIMEOUT`) — Local Stream Idle Timeout (seconds)"
    **Category**: `generation`

    Maximum allowed silent gap (in seconds) between streamed tokens/chunks from the local Ollama endpoint before Crucible treats the response as stalled and aborts the request. This protects the UI from hanging indefinitely when a socket is half-open or a backend worker dies mid-generation. Set it too low and you will cut off valid long-prefill responses on larger context windows; set it too high and users wait too long on dead streams. Tune this together with network proxy timeouts and model size so cancellation behavior is fast but not trigger-happy.

    **Links**:
    - [Rethinking Latency DoS in KV Cache Systems (arXiv 2026)](https://arxiv.org/abs/2602.07878)
    - [Ollama Streaming API](https://docs.ollama.com/api/streaming)
    - [Nginx proxy_read_timeout](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout)
    - [Node.js AbortSignal.timeout()](https://nodejs.org/api/globals.html#abortsignaltimeoutdelay)

??? info "`generation.ollama_url` (`OLLAMA_URL`) — Ollama URL"
    **Category**: `generation`

    Base URL Crucible uses to reach Ollama over HTTP for local-model inference (for example, endpoints such as `/api/chat`, `/api/generate`, and `/api/tags`). This value controls where requests are sent from the app backend, so incorrect hostnames, ports, or path prefixes cause immediate model-routing failures. For remote or containerized setups, use a reachable address from the process that runs Crucible, not just from your browser. When multiple OpenAI-compatible backends are in play, keep this endpoint explicit so provider routing and debugging stay deterministic.

    **Links**:
    - [FlyingServing: Scalable and Fault-Tolerant LLM Serving (arXiv 2026)](https://arxiv.org/abs/2602.22593)
    - [Ollama API Reference](https://docs.ollama.com/api)
    - [Ollama Model Tags Endpoint](https://docs.ollama.com/api/tags)
    - [vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)

??? info "`generation.openai_base_url` (`OPENAI_BASE_URL`) — OpenAI Base URL"
    **Category**: `generation`

    Advanced endpoint override for OpenAI-compatible APIs. Use this when routing Crucible through alternative backends such as Azure-hosted deployments, vLLM, or internal gateway proxies that implement OpenAI-style request/response contracts. Base URL mismatches are a common root cause of 404/401 errors because SDK path composition, versioning, and auth headers differ across providers. Keep this setting paired with explicit model/provider assignments so you can trace which endpoint handled each request during failures.

    **Badges**:
    - Advanced
    - For compatible endpoints only

    **Links**:
    - [LMCache: Optimizing LLM Caching and Routing (arXiv 2025)](https://arxiv.org/abs/2510.09665)
    - [OpenAI Node SDK](https://github.com/openai/openai-node)
    - [vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/)
    - [Azure OpenAI API Version and Endpoint Guidance](https://learn.microsoft.com/en-us/azure/ai-services/openai/api-version-deprecation)
