"""Runtime and gateway-related models extracted from the monolith.

This module is the first real slice out of `tribrid_config_model.py`. The
classes here define provider/gateway/runtime contracts that are shared across
chat routing, chat model discovery, and generation settings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatProviderInfo(BaseModel):
    """Selected provider route for a chat answer."""

    kind: Literal["cloud_direct", "openrouter", "local", "ragweld", "litellm"] = Field(
        description="Provider kind (router selection)"
    )
    provider_name: str = Field(description="Provider display name (e.g., OpenAI, OpenRouter, LiteLLM)")
    model: str = Field(description="Model identifier sent to provider")
    base_url: str | None = Field(default=None, description="Provider base URL (when applicable)")


def _default_chat_model_components() -> list[Literal["GEN", "EMB", "RERANK"]]:
    return ["GEN"]


class ChatModelInfo(BaseModel):
    """Single chat model option resolved from providers."""

    id: str = Field(description="Model identifier")
    override: str = Field(description="Canonical model_override value to send in chat requests")
    provider: str = Field(description="Provider display name (e.g., OpenRouter, LiteLLM, Ollama)")
    provider_key: str | None = Field(default=None, description="Provider key used in the model catalog")
    catalog_model: str | None = Field(default=None, description="Catalog model identifier when sourced from /api/models")
    components: list[Literal["GEN", "EMB", "RERANK"]] = Field(
        default_factory=_default_chat_model_components,
        description="Capabilities for this model option",
    )
    source: Literal["cloud_direct", "openrouter", "local", "ragweld", "litellm"] = Field(
        description="Model source group for UI grouping."
    )
    provider_type: str | None = Field(default=None, description="Provider type (ollama, llamacpp, openrouter, litellm, etc)")
    base_url: str | None = Field(default=None, description="Provider base URL (local/openrouter/litellm)")
    supports_vision: bool = Field(default=False, description="Whether this model is expected to support vision inputs")


class ChatModelsResponse(BaseModel):
    """Response payload for GET /api/chat/models."""

    models: list[ChatModelInfo] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health status for a configured provider endpoint."""

    provider: str = Field(description="Provider display name")
    kind: Literal["openrouter", "local", "ragweld", "litellm"] = Field(description="Provider kind")
    base_url: str = Field(description="Provider base URL")
    reachable: bool = Field(description="Whether the provider endpoint is reachable")
    detail: str | None = Field(default=None, description="Optional detail/error message")


class ProvidersHealthResponse(BaseModel):
    """Response payload for GET /api/chat/health."""

    providers: list[ProviderHealth] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    """LLM generation configuration."""

    gen_model: str = Field(
        default="gpt-4o-mini",
        description="Primary generation model",
    )

    gen_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Generation temperature",
    )

    gen_max_tokens: int = Field(
        default=2048,
        ge=100,
        le=8192,
        description="Max tokens for generation",
    )

    gen_top_p: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling threshold",
    )

    gen_timeout: int = Field(
        default=60,
        ge=10,
        le=300,
        description="Generation timeout (seconds)",
    )

    gen_retry_max: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Max retries for generation",
    )

    # --- Backend resolution rules ---
    # 1. gen_model uses gen_backend as provider
    # 2. gen_model_ollama / enrich_model_ollama — provider is always "ollama"
    # 3. enrich_model uses enrich_backend (below)
    # 4. semantic_kg_llm_model — inherits gen_backend when non-empty;
    #    falls back to enrich_model with enrich_backend
    # 5. Channel overrides (gen_model_cli/http/mcp) inherit gen_backend
    gen_backend: str = Field(
        default="openai",
        pattern="^(openai|anthropic|ollama|mlx|openrouter|litellm)$",
        description="Provider backend for gen_model and channel overrides",
    )

    enrich_model: str = Field(
        default="gpt-4o-mini",
        description="Model for code enrichment",
    )

    enrich_backend: str = Field(
        default="openai",
        pattern="^(openai|ollama|mlx)$",
        description="Enrichment backend",
    )

    enrich_disabled: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Disable code enrichment",
    )

    ollama_num_ctx: int = Field(
        default=8192,
        ge=2048,
        le=32768,
        description="Context window for Ollama",
    )

    gen_model_cli: str = Field(
        default="qwen3-coder:14b",
        description="CLI generation model",
    )

    gen_model_ollama: str = Field(
        default="qwen3-coder:30b",
        description="Ollama generation model",
    )

    gen_model_http: str = Field(
        default="",
        description="HTTP transport generation model override",
    )

    gen_model_mcp: str = Field(
        default="",
        description="MCP transport generation model override",
    )

    enrich_model_ollama: str = Field(
        default="",
        description="Ollama enrichment model",
    )

    ollama_url: str = Field(
        default="http://127.0.0.1:11434/api",
        description="Ollama API URL",
    )

    openai_base_url: str = Field(
        default="",
        description="OpenAI API base URL override (for proxies)",
    )

    ollama_request_timeout: int = Field(
        default=300,
        ge=30,
        le=1200,
        description="Maximum total time to wait for a local (Ollama) generation request to complete (seconds)",
    )
    ollama_stream_idle_timeout: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Maximum idle time allowed between streamed chunks from local (Ollama) during generation (seconds)",
    )


class OpenRouterConfig(BaseModel):
    """Unified gateway to many cloud models via OpenAI-compatible routing."""

    enabled: bool = Field(default=False)
    base_url: str = Field(default="https://openrouter.ai/api/v1")
    default_model: str = Field(default="anthropic/claude-sonnet-4")
    site_name: str = Field(default="TriBridRAG")
    fallback_models: list[str] = Field(default=["openai/gpt-4o", "google/gemini-2.0-flash"])


class LiteLLMConfig(BaseModel):
    """Gateway configuration for an OpenAI-compatible LiteLLM proxy."""

    enabled: bool = Field(default=True)
    base_url: str = Field(default="http://127.0.0.1:54000/v1")
    default_model: str = Field(default="ragweld-local")
    fallback_models: list[str] = Field(default_factory=list)


class VLLMConfig(BaseModel):
    """Reference configuration for the self-hosted vLLM serving layer."""

    enabled: bool = Field(default=True)
    base_url: str = Field(default="http://127.0.0.1:58080/v1")
    default_model: str = Field(default="Qwen/Qwen3-0.6B")


class LocalProviderEntry(BaseModel):
    """A single local inference provider endpoint."""

    name: str = Field(description="Display name")
    provider_type: str = Field(pattern="^(ollama|llamacpp|lmstudio|vllm|litellm|custom)$")
    base_url: str = Field(description="Provider API endpoint")
    enabled: bool = Field(default=True)
    priority: int = Field(
        default=0,
        ge=0,
        description="Lower = higher priority when multiple have same model.",
    )


class LocalModelConfig(BaseModel):
    """Supports multiple simultaneous local inference providers."""

    providers: list[LocalProviderEntry] = Field(
        default=[
            LocalProviderEntry(
                name="Ollama",
                provider_type="ollama",
                base_url="http://127.0.0.1:11434",
                priority=0,
            ),
            LocalProviderEntry(
                name="llama.cpp",
                provider_type="llamacpp",
                base_url="http://127.0.0.1:8080",
                priority=1,
            ),
        ]
    )
    auto_detect: bool = Field(default=True)
    health_check_interval: int = Field(default=30, ge=10, le=300)
    fallback_to_cloud: bool = Field(default=True)
    gpu_memory_limit_gb: float = Field(default=0, ge=0)
    default_chat_model: str = Field(default="qwen3:8b")
    default_vision_model: str = Field(default="qwen3-vl:8b")
    default_embedding_model: str = Field(default="nomic-embed-text")


class BenchmarkConfig(BaseModel):
    """Split-screen model comparison + pipeline profiling."""

    enabled: bool = Field(default=True)
    max_concurrent_models: int = Field(default=4, ge=2, le=8)
    save_results: bool = Field(default=True)
    results_path: str = Field(default="data/benchmarks/")
    include_cost_tracking: bool = Field(default=True)
    include_timing_breakdown: bool = Field(default=True)
