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

**Total parameters**: 10

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `generation.enrich_disabled` | `ENRICH_DISABLED` | `bool` | `false` | — | Disable code enrichment |
| `generation.enrich_model` | `ENRICH_MODEL` | `str` | `"ragweld-local"` | — | LiteLLM alias for code enrichment |
| `generation.gen_max_tokens` | `GEN_MAX_TOKENS` | `int` | `512` | ≥ 100, ≤ 16000 | Max tokens for generation |
| `generation.gen_model` | `GEN_MODEL` | `str` | `"ragweld-local"` | — | Primary LiteLLM model alias |
| `generation.gen_model_cli` | `GEN_MODEL_CLI` | `str` | `""` | — | Optional LiteLLM alias for CLI requests |
| `generation.gen_model_http` | `GEN_MODEL_HTTP` | `str` | `""` | — | HTTP transport generation model override |
| `generation.gen_model_mcp` | `GEN_MODEL_MCP` | `str` | `""` | — | MCP transport generation model override |
| `generation.gen_temperature` | `GEN_TEMPERATURE` | `float` | `0.0` | ≥ 0.0, ≤ 2.0 | Generation temperature |
| `generation.gen_timeout` | `GEN_TIMEOUT` | `int` | `600` | ≥ 10, ≤ 900 | Generation timeout in seconds for non-chat generation calls (eval analysis, synthetic data); sized for single-stream CPU serving of the local model |
| `generation.gen_top_p` | `GEN_TOP_P` | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Nucleus sampling threshold |

### Details (glossary)

??? info "`generation.enrich_disabled` (`ENRICH_DISABLED`) — Disable Enrichment"
    **Category**: `general`

    This switch disables enrichment generation entirely during indexing. It is useful for fast iteration, low-cost development cycles, and emergency backfills where raw embedding retrieval is acceptable. The cost of disabling is reduced semantic metadata for reranking, chunk summaries, and explanatory UX features, which can lower answer quality on abstract or architecture-level questions. Use it intentionally and record when it is active so benchmark comparisons remain meaningful. A common pattern is enrichment disabled for local loops and enabled for production-grade index builds.

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
