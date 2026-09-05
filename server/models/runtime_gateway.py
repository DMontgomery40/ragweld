"""Runtime and gateway-related models extracted from the monolith.

This module is the first real slice out of `tribrid_config_model.py`. The
classes here define provider/gateway/runtime contracts that are shared across
chat routing, chat model discovery, and generation settings.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.model_policy import ensure_model_allowed

_LITELLM_ALIAS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_litellm_alias(value: str, *, allow_empty: bool) -> str:
    """Normalize one application-visible LiteLLM alias and reject provider IDs."""

    alias = str(value or "").strip()
    ensure_model_allowed(alias)
    if not alias and allow_empty:
        return ""
    if not _LITELLM_ALIAS_PATTERN.fullmatch(alias):
        raise ValueError("must be a LiteLLM alias, not a provider or upstream model identifier")
    if alias != alias.lower():
        raise ValueError("must be a lowercase LiteLLM alias (gateway aliases are lowercase)")
    return alias


class ChatProviderInfo(BaseModel):
    """Selected provider route for a chat answer."""

    kind: Literal["litellm"] = Field(description="Application-visible generation boundary")
    provider_name: str = Field(description="Gateway display name")
    model: str = Field(description="LiteLLM model alias")
    base_url: str | None = Field(default=None, description="LiteLLM OpenAI-compatible base URL")


def _default_chat_model_components() -> list[Literal["GEN", "EMB", "RERANK"]]:
    return ["GEN"]


class ChatModelInfo(BaseModel):
    """Single chat model option resolved from providers."""

    id: str = Field(description="Model identifier")
    override: str = Field(description="Canonical model_override value to send in chat requests")
    provider: str = Field(description="Gateway display name")
    provider_key: str | None = Field(default=None, description="Gateway key")
    catalog_model: str | None = Field(default=None, description="Optional catalog identity")
    components: list[Literal["GEN", "EMB", "RERANK"]] = Field(
        default_factory=_default_chat_model_components,
        description="Capabilities for this model option",
    )
    source: Literal["litellm"] = Field(description="Model source group for UI grouping.")
    provider_type: str | None = Field(default=None, description="Gateway type")
    base_url: str | None = Field(default=None, description="LiteLLM base URL")
    supports_vision: bool = Field(default=False, description="Whether this model is expected to support vision inputs")
    catalog_provider: str | None = Field(
        default=None,
        description="Upstream provider slug from the model catalog row behind this alias (for UI grouping).",
    )
    display_name: str | None = Field(default=None, description="Human-readable name from the catalog row, when known")
    context: int | None = Field(default=None, ge=0, description="Maximum context tokens from the catalog row, when known")
    input_per_1k: float | None = Field(default=None, ge=0.0, description="Input cost per 1k tokens from the catalog row")
    output_per_1k: float | None = Field(default=None, ge=0.0, description="Output cost per 1k tokens from the catalog row")


class ChatModelsResponse(BaseModel):
    """Response payload for GET /api/chat/models."""

    models: list[ChatModelInfo] = Field(default_factory=list)


class ProviderHealth(BaseModel):
    """Health status for a configured provider endpoint."""

    provider: str = Field(description="Provider display name")
    kind: Literal["litellm"] = Field(description="Gateway kind")
    base_url: str = Field(description="Provider base URL")
    reachable: bool = Field(description="Whether the provider endpoint is reachable")
    detail: str | None = Field(default=None, description="Optional detail/error message")


class ProvidersHealthResponse(BaseModel):
    """Response payload for GET /api/chat/health."""

    providers: list[ProviderHealth] = Field(default_factory=list)


class GenerationConfig(BaseModel):
    """LLM generation configuration."""

    model_config = ConfigDict(extra="forbid")

    gen_model: str = Field(
        default="ragweld-local",
        description="Primary LiteLLM model alias",
    )

    gen_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Generation temperature",
    )

    gen_max_tokens: int = Field(
        default=512,
        ge=100,
        le=16000,
        description="Max tokens for generation",
    )

    gen_top_p: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling threshold",
    )

    gen_timeout: int = Field(
        default=600,
        ge=10,
        le=900,
        description="Generation timeout in seconds for non-chat generation calls (eval analysis, synthetic data); sized for single-stream CPU serving of the local model",
    )

    enrich_model: str = Field(
        default="ragweld-local",
        description="LiteLLM alias for code enrichment",
    )

    enrich_disabled: bool = Field(
        default=False,
        description="Disable code enrichment",
    )

    gen_model_cli: str = Field(
        default="",
        description="Optional LiteLLM alias for CLI requests",
    )

    gen_model_http: str = Field(
        default="",
        description="HTTP transport generation model override",
    )

    gen_model_mcp: str = Field(
        default="",
        description="MCP transport generation model override",
    )

    @field_validator("gen_model", "enrich_model", "gen_model_cli", "gen_model_http", "gen_model_mcp")
    @classmethod
    def validate_gateway_alias_fields(cls, value: str) -> str:
        return validate_litellm_alias(value, allow_empty=True)

class LiteLLMConfig(BaseModel):
    """Gateway configuration for an OpenAI-compatible LiteLLM proxy."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True)
    base_url: str = Field(default="http://127.0.0.1:54000/v1")
    default_model: str = Field(default="ragweld-local")

    @field_validator("default_model")
    @classmethod
    def validate_default_alias(cls, value: str) -> str:
        return validate_litellm_alias(value, allow_empty=False)


class VLLMConfig(BaseModel):
    """Reference configuration for the self-hosted vLLM serving layer."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True)
    base_url: str = Field(default="http://127.0.0.1:58080/v1")
    default_model: str = Field(default="mlx-community/Qwen3.8-27B-4bit")


class BenchmarkConfig(BaseModel):
    """Split-screen model comparison + pipeline profiling."""

    enabled: bool = Field(default=True)
    max_concurrent_models: int = Field(default=4, ge=2, le=8)
    save_results: bool = Field(default=True)
    results_path: str = Field(default="data/benchmarks/")
    include_cost_tracking: bool = Field(default=True)
    include_timing_breakdown: bool = Field(default=True)
