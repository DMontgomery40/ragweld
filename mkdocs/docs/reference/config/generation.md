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

**Total parameters**: 19

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `generation.enrich_backend` | `ENRICH_BACKEND` | `str` | `"openai"` | pattern=^(openai\|ollama\|mlx)$ | Enrichment backend |
| `generation.enrich_disabled` | `ENRICH_DISABLED` | `int` | `0` | ≥ 0, ≤ 1 | Disable code enrichment |
| `generation.enrich_model` | `ENRICH_MODEL` | `str` | `"gpt-4o-mini"` | — | Model for code enrichment |
| `generation.enrich_model_ollama` | `ENRICH_MODEL_OLLAMA` | `str` | `""` | — | Ollama enrichment model |
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

    Backend service for generating code summaries and enrichment metadata during indexing. Options: "openai" (GPT models, highest quality), "ollama" (local models, free), "mlx" (Apple Silicon optimized). Enrichment adds per-chunk summaries and keywords used by features like cards and improved reranking. Disable to speed up indexing or reduce costs.

    **Badges**:
    - Optional feature
    - Increases index time

    **Links**:
    - [MLX on Apple Silicon](https://github.com/ml-explore/mlx)
    - [Ollama Local Models](https://ollama.com/library)

??? info "`generation.enrich_disabled` (`ENRICH_DISABLED`) — Disable Enrichment"
    **Category**: `general`

    Completely disable code enrichment (summaries, keywords, cards) during indexing (1=disable, 0=enable). When disabled, indexing is much faster and cheaper (no LLM API calls) but you lose card search, enriched metadata, and semantic boosting. Use this for quick re-indexing during development, CI/CD pipelines, or when working with non-code content. Re-enable for production to get full retrieval quality benefits.

    Recommended: 0 (enrichment ON) for production, 1 (enrichment OFF) for fast iteration and testing.

    **Badges**:
    - Much faster indexing
    - Loses card search

??? info "`generation.enrich_model` (`ENRICH_MODEL`) — Enrichment Model"
    **Category**: `generation`

    Specific model name for code enrichment when ENRICH_BACKEND is set. For OpenAI: "gpt-4o-mini" (recommended, cheap), "gpt-4o" (higher quality, costly). For Ollama: specify via ENRICH_MODEL_OLLAMA instead. Smaller models (gpt-4o-mini, qwen2.5-coder:7b) balance cost and quality for summaries. Enrichment happens during indexing, not at query time.

    **Badges**:
    - Affects index cost

    **Links**:
    - [OpenAI Models](https://platform.openai.com/docs/models)
    - [Cost Comparison](https://openai.com/api/pricing/)

??? info "`generation.enrich_model_ollama` (`ENRICH_MODEL_OLLAMA`) — Enrichment Model (Ollama)"
    **Category**: `generation`

    Ollama model name for code enrichment when ENRICH_BACKEND=ollama. Recommended: "qwen2.5-coder:7b" (fast, code-focused), "deepseek-coder:6.7b" (excellent code understanding), "codellama:13b" (high quality, slower). Model must be pulled via "ollama pull <model>" before use. Local enrichment is free but slower than cloud APIs.

    **Badges**:
    - Free (local)
    - Requires model download

    **Links**:
    - [Ollama Models](https://ollama.com/library)
    - [Pull Models](https://github.com/ollama/ollama#quickstart)
    - [Code-Focused Models](https://ollama.com/search?c=tools)

??? info "`generation.gen_max_tokens` (`GEN_MAX_TOKENS`) — Max Tokens"
    **Category**: `generation`

    Maximum number of tokens the LLM can generate in a single response. Higher values allow longer answers but increase cost and latency. Typical: 512-1024 for concise answers, 2048-4096 for detailed explanations.

    **Links**:
    - [OpenAI Token Limits](https://platform.openai.com/docs/guides/text-generation)
    - [Token Counting](https://platform.openai.com/tokenizer)

??? info "`generation.gen_model` (`GEN_MODEL`) — Generation Model"
    **Category**: `generation`

    Answer model. Local: qwen3-coder:14b via Ollama. Cloud: gpt-4o-mini, etc. Larger models cost more and can be slower; smaller ones are faster/cheaper.

    **Badges**:
    - Affects latency

    **Links**:
    - [OpenAI Models](https://platform.openai.com/docs/models)
    - [Ollama API (GitHub)](https://github.com/ollama/ollama/blob/main/docs/api.md)

??? info "`generation.gen_model_cli` (`GEN_MODEL_CLI`) — CLI Channel Model"
    **Category**: `generation`

    Override GEN_MODEL for CLI chat sessions only. Allows using different models for terminal vs web interface - e.g., faster models for CLI iteration, higher quality for production GUI. Useful for developer workflows where CLI is for quick testing and HTTP is for end users. If not set, uses GEN_MODEL.

    **Badges**:
    - Channel-specific

??? info "`generation.gen_model_http` (`GEN_MODEL_HTTP`) — HTTP Channel Model"
    **Category**: `generation`

    Override GEN_MODEL specifically for HTTP API requests (GUI, external API calls). Useful for serving different models to different channels - e.g., use gpt-4o for production HTTP but qwen-coder locally. If not set, falls back to GEN_MODEL. Example use case: cheaper models for public API, expensive models for internal tools.

    **Badges**:
    - Channel-specific

    **Links**:
    - [Model Selection](https://platform.openai.com/docs/models)

??? info "`generation.gen_model_mcp` (`GEN_MODEL_MCP`) — MCP Channel Model"
    **Category**: `generation`

    Override GEN_MODEL for MCP tool invocations only. Use a lighter/cheaper model for MCP tools since tool calls are typically simpler than complex reasoning. Example: gpt-4o-mini for MCP, gpt-4o for main chat. Reduces costs when tools are called frequently (search, file operations, etc.). If not set, uses GEN_MODEL.

    **Badges**:
    - Cost savings
    - Channel-specific

    **Links**:
    - [Model Pricing](https://openai.com/api/pricing/)

??? info "`generation.gen_retry_max` (`GEN_RETRY_MAX`) — Generation Max Retries"
    **Category**: `generation`

    Number of retry attempts for failed LLM API calls due to rate limits, network errors, or transient failures. Higher values improve reliability but increase latency on failures. Typical: 2-3 retries.

    **Links**:
    - [Retry Strategies](https://platform.openai.com/docs/guides/error-codes)
    - [Exponential Backoff](https://en.wikipedia.org/wiki/Exponential_backoff)

??? info "`generation.gen_temperature` (`GEN_TEMPERATURE`) — Default Response Creativity"
    **Category**: `generation`

    Global default temperature for generation. 0.0 = deterministic; small values (0.04-0.2) add slight variation in prose. Use per-model tuning for creative tasks vs. code answers.

    **Links**:
    - [Sampling Controls](https://platform.openai.com/docs/guides/text-generation)
    - [Nucleus/Top‑p](https://en.wikipedia.org/wiki/Nucleus_sampling)

??? info "`generation.gen_timeout` (`GEN_TIMEOUT`) — Generation Timeout"
    **Category**: `generation`

    Maximum seconds to wait for LLM response before timing out. Prevents hanging on slow models or network issues. Increase for large models or slow connections. Typical: 30-120 seconds.

    **Links**:
    - [Timeout Best Practices](https://platform.openai.com/docs/guides/rate-limits)
    - [HTTP Timeouts](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Timeout)

??? info "`generation.gen_top_p` (`GEN_TOP_P`) — Top-P (Nucleus Sampling)"
    **Category**: `generation`

    Controls randomness via nucleus sampling (0.0-1.0). Lower values (0.1-0.5) make output more focused and deterministic. Higher values (0.9-1.0) increase creativity and diversity. Recommended: 0.9 for general use.

    **Links**:
    - [Nucleus Sampling](https://platform.openai.com/docs/guides/text-generation/parameter-details)
    - [Top-P Explanation](https://en.wikipedia.org/wiki/Top-p_sampling)

??? info "`generation.ollama_request_timeout` (`OLLAMA_REQUEST_TIMEOUT`) — Local Request Timeout (seconds)"
    **Category**: `generation`

    Maximum total time to wait for a single local (Ollama) generation request to complete. Increase for long answers; decrease to fail fast on slow models or poor connectivity.

    **Links**:
    - [Ollama API: Generate](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-completion)
    - [HTTP Timeouts](https://developer.mozilla.org/en-US/docs/Web/HTTP/Timeouts)

??? info "`generation.ollama_stream_idle_timeout` (`OLLAMA_STREAM_IDLE_TIMEOUT`) — Local Stream Idle Timeout (seconds)"
    **Category**: `generation`

    Maximum idle time allowed between streamed chunks from local (Ollama). If no tokens arrive within this window, the request aborts to prevent hanging streams.

    **Links**:
    - [Streaming Basics](https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream)
    - [Ollama Streaming](https://github.com/ollama/ollama/blob/main/docs/api.md#streaming)

??? info "`generation.ollama_url` (`OLLAMA_URL`) — Ollama URL"
    **Category**: `generation`

    Local inference endpoint for Ollama running on your machine (e.g., http://127.0.0.1:11434/api). Used when GEN_MODEL targets a local model like llama2, mistral, qwen, or neural-chat. Requires Ollama installed and running: ollama serve

    **Links**:
    - [Ollama REST API](https://github.com/ollama/ollama/blob/main/docs/api.md)
    - [Ollama Docker Setup](https://ollama.com/blog/ollama-is-now-available-as-an-official-docker-image)
    - [Ollama Model Library](https://ollama.com/library)

??? info "`generation.openai_base_url` (`OPENAI_BASE_URL`) — OpenAI Base URL"
    **Category**: `generation`

    ADVANCED: Override the OpenAI API base URL for OpenAI-compatible endpoints. Use cases: local inference servers (LM Studio, vLLM, text-generation-webui), Azure OpenAI (https://YOUR_RESOURCE.openai.azure.com/), proxy services. Default: https://api.openai.com/v1. Useful for development, air-gapped environments, or cost optimization via self-hosted models.

    **Badges**:
    - Advanced
    - For compatible endpoints only

    **Links**:
    - [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
    - [Azure OpenAI](https://learn.microsoft.com/en-us/azure/ai-services/openai/)
    - [LM Studio Setup](https://lmstudio.ai/docs/local-server)
    - [vLLM Compatibility](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
