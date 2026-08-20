"""Replacement-only contract for the application-visible generation boundary."""

import pytest
from pydantic import ValidationError

from server.models.runtime_gateway import (
    ChatModelInfo,
    ChatProviderInfo,
    GenerationConfig,
    LiteLLMConfig,
    ProviderHealth,
)
from server.models.tribrid_config_model import ChatConfig, ModelCatalogEntry, TriBridConfig


def test_generation_config_contains_only_gateway_aliases_and_generic_controls() -> None:
    fields = set(GenerationConfig.model_fields)

    assert {
        "gen_model",
        "gen_temperature",
        "gen_max_tokens",
        "gen_top_p",
        "gen_timeout",
        "enrich_model",
        "enrich_disabled",
        "gen_model_cli",
        "gen_model_http",
        "gen_model_mcp",
    }.issubset(fields)
    assert {
        "gen_backend",
        "enrich_backend",
        "gen_retry_max",
        "gen_model_ollama",
        "enrich_model_ollama",
        "ollama_num_ctx",
        "ollama_url",
        "ollama_request_timeout",
        "ollama_stream_idle_timeout",
        "openai_base_url",
    }.isdisjoint(fields)
    assert GenerationConfig().gen_model == "ragweld-local"
    assert GenerationConfig().enrich_model == "ragweld-local"


def test_chat_config_contains_only_litellm_and_vllm_generation_deployments() -> None:
    fields = set(ChatConfig.model_fields)

    assert {"litellm", "vllm"}.issubset(fields)
    assert {"openrouter", "local_models", "openai_protocol"}.isdisjoint(fields)
    assert "fallback_models" not in LiteLLMConfig.model_fields


@pytest.mark.parametrize(
    ("model", "field_name"),
    [
        (ChatProviderInfo, "kind"),
        (ChatModelInfo, "source"),
        (ProviderHealth, "kind"),
    ],
)
def test_public_generation_route_literals_expose_only_litellm(model: type, field_name: str) -> None:
    schema = model.model_json_schema()
    assert schema["properties"][field_name]["const"] == "litellm"


def test_provider_catalog_has_no_generation_selection_contract() -> None:
    schema = ModelCatalogEntry.model_json_schema()
    role_items = schema["properties"]["selection_roles"]["items"]
    assert role_items["enum"] == ["embedding_provider", "reranker_cloud"]


@pytest.mark.parametrize(
    ("payload", "removed_field"),
    [
        ({"generation": {"gen_backend": "openai"}}, "gen_backend"),
        ({"generation": {"enrich_backend": "openai"}}, "enrich_backend"),
        ({"generation": {"gen_retry_max": 2}}, "gen_retry_max"),
        ({"generation": {"gen_model_ollama": "qwen"}}, "gen_model_ollama"),
        ({"generation": {"enrich_model_ollama": "qwen"}}, "enrich_model_ollama"),
        ({"generation": {"ollama_num_ctx": 8192}}, "ollama_num_ctx"),
        ({"generation": {"ollama_url": "http://127.0.0.1:11434"}}, "ollama_url"),
        ({"generation": {"ollama_request_timeout": 300}}, "ollama_request_timeout"),
        ({"generation": {"ollama_stream_idle_timeout": 60}}, "ollama_stream_idle_timeout"),
        ({"generation": {"openai_base_url": "http://127.0.0.1:8000"}}, "openai_base_url"),
        ({"chat": {"openrouter": {"enabled": True}}}, "openrouter"),
        ({"chat": {"local_models": {"providers": []}}}, "local_models"),
        ({"chat": {"openai_protocol": "responses"}}, "openai_protocol"),
        ({"chat": {"litellm": {"fallback_models": ["paid"]}}}, "fallback_models"),
    ],
)
def test_removed_generation_contracts_are_rejected(payload: dict[str, object], removed_field: str) -> None:
    from server.models.tribrid_config_model import TriBridConfig

    with pytest.raises(ValidationError, match=removed_field):
        TriBridConfig.model_validate(payload)


@pytest.mark.parametrize(
    "removed_key",
    [
        "GEN_BACKEND",
        "ENRICH_BACKEND",
        "GEN_RETRY_MAX",
        "GEN_MODEL_OLLAMA",
        "ENRICH_MODEL_OLLAMA",
        "OLLAMA_NUM_CTX",
        "OLLAMA_URL",
        "OLLAMA_REQUEST_TIMEOUT",
        "OLLAMA_STREAM_IDLE_TIMEOUT",
        "OPENAI_BASE_URL",
    ],
)
def test_removed_flat_generation_contracts_are_rejected(removed_key: str) -> None:
    with pytest.raises(ValueError, match=removed_key):
        TriBridConfig.from_flat_dict({removed_key: "removed"})


@pytest.mark.parametrize("removed_key", ["GEN_BACKEND", "OPENAI_BASE_URL", "OLLAMA_URL"])
def test_removed_flat_keys_are_rejected_by_nested_root_validation(removed_key: str) -> None:
    with pytest.raises(ValidationError, match=removed_key):
        TriBridConfig.model_validate({removed_key: "removed"})


@pytest.mark.parametrize(
    "payload",
    [
        {"generation": {"gen_model": "openai/gpt-5.4-mini"}},
        {"generation": {"enrich_model": "openrouter:openai/gpt-5.4-mini"}},
        {"generation": {"gen_model_cli": "local:qwen3:8b"}},
        {"chat": {"litellm": {"default_model": "openai/gpt-5.4-mini"}}},
        {"chat": {"multimodal": {"vision_model_override": "openrouter:vision"}}},
        {"graph_indexing": {"semantic_kg_llm_model": "openai/gpt-5.4-mini"}},
    ],
)
def test_direct_provider_identifiers_are_rejected_during_config_parse(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="LiteLLM alias"):
        TriBridConfig.model_validate(payload)


def test_embedding_and_reranker_provider_contracts_remain_available() -> None:
    from server.models.tribrid_config_model import TriBridConfig

    cfg = TriBridConfig.model_validate(
        {
            "embedding": {"embedding_type": "openai"},
            "reranking": {"reranker_cloud_provider": "cohere"},
        }
    )
    assert cfg.embedding.embedding_type == "openai"
    assert cfg.reranking.reranker_cloud_provider == "cohere"
