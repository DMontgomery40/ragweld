from __future__ import annotations

import pytest

from server.api.index import (
    _resolve_semantic_kg_model_and_provider,
    _semantic_kg_model_override,
)
from server.models.tribrid_config_model import TriBridConfig


def test_semantic_kg_model_override_defaults_to_litellm_alias() -> None:
    cfg = TriBridConfig()

    assert _semantic_kg_model_override(cfg) == "ragweld-local"
    assert _resolve_semantic_kg_model_and_provider(cfg) == ("ragweld-local", "litellm")


def test_semantic_kg_model_override_accepts_gateway_alias() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = "semantic-graph"

    assert _semantic_kg_model_override(cfg) == "semantic-graph"
    assert _resolve_semantic_kg_model_and_provider(cfg) == ("semantic-graph", "litellm")


@pytest.mark.parametrize("model", ["openai/gpt-5", "openrouter:openai/gpt-5", "local:qwen3"])
def test_semantic_kg_model_override_rejects_direct_provider_ids(model: str) -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = model

    with pytest.raises(ValueError, match="LiteLLM alias"):
        _semantic_kg_model_override(cfg)
