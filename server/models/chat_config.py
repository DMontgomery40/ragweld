"""Chat 2.0 configuration models (thin re-export).

TriBridRAG is **Pydantic-first**: the source of truth ("THE LAW") lives in
`server/models/tribrid_config_model.py`. This module exists only as a stable,
focused import path for the Chat 2.0 config models and must not define any new
Pydantic models.
"""

from .tribrid_config_model import (  # noqa: F401
    ActiveSources,
    BenchmarkConfig,
    ChatConfig,
    ChatMultimodalConfig,
    ImageAttachment,
    ImageGenConfig,
    LiteLLMConfig,
    LocalModelConfig,
    LocalProviderEntry,
    OpenRouterConfig,
    RecallConfig,
    RecallFusionOverrides,
    RecallGateConfig,
    RecallIntensity,
    RecallPlan,
    RecallSignals,
    VLLMConfig,
)

__all__ = [
    "ActiveSources",
    "ImageAttachment",
    "RecallConfig",
    "RecallIntensity",
    "RecallSignals",
    "RecallFusionOverrides",
    "RecallPlan",
    "RecallGateConfig",
    "ChatMultimodalConfig",
    "ImageGenConfig",
    "LiteLLMConfig",
    "OpenRouterConfig",
    "LocalProviderEntry",
    "LocalModelConfig",
    "VLLMConfig",
    "BenchmarkConfig",
    "ChatConfig",
]
