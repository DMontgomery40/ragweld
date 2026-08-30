from __future__ import annotations

import pytest

from server.api.index import _gateway_model_spec, _semantic_kg_model_override
from server.models.tribrid_config_model import TriBridConfig


def test_semantic_kg_model_override_defaults_to_litellm_alias() -> None:
    cfg = TriBridConfig()

    assert _semantic_kg_model_override(cfg) == "ragweld-local"


def test_semantic_kg_model_override_accepts_gateway_alias() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = "semantic-graph"

    assert _semantic_kg_model_override(cfg) == "semantic-graph"


@pytest.mark.parametrize("model", ["openai/gpt-5", "openrouter:openai/gpt-5", "local:qwen3"])
def test_semantic_kg_model_override_rejects_direct_provider_ids(model: str) -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = model

    with pytest.raises(ValueError, match="LiteLLM alias"):
        _semantic_kg_model_override(cfg)


def test_the_default_semantic_alias_is_a_row_the_catalog_actually_serves() -> None:
    """The alias the default config resolves to has to be priceable, or the cost card cannot
    quote a semantic KG phase at all. This is the pairing that was broken: the override is an
    alias, and only an alias lookup can find its row.
    """
    spec = _gateway_model_spec(_semantic_kg_model_override(TriBridConfig()))

    assert spec is not None
    assert str(spec["gateway_alias"]) == "ragweld-local"
    assert "GEN" in [str(component).upper() for component in spec["components"]]
    assert str(spec["unit"]) == "1k_tokens"
