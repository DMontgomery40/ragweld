"""The execution prohibition covers identities, config fields, and direct transports."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.chat.generation import generate_chat_text, stream_chat_text
from server.chat.provider_router import ProviderRoute
from server.model_policy import ensure_model_allowed
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.parametrize("model", [
    "gpt-4", "gpt-4o", "gpt-4.1-nano", "openai.gpt-4o-mini.batch",
    "openrouter/openai/gpt-4-turbo", "litellm:openai.gpt-4.1",
    "  OPENAI/GPT-4O-2024-08-06  ", "openai/chatgpt-4o-latest",
])
def test_policy_blocks_model_family_in_all_identity_forms(model: str) -> None:
    with pytest.raises(ValueError, match="GPT-4-class models are blocked"):
        ensure_model_allowed(model)


@pytest.mark.parametrize("model", [
    "", "ragweld-local", "openai.gpt-5.6-luna", "openai/gpt-6",
    "anthropic/claude-sonnet-4.5", "meta-llama/llama-4-maverick",
    "mlx-community/Qwen3.8-27B-4bit", "text-embedding-3-small", "rerank-v3.5",
])
def test_policy_preserves_other_model_families(model: str) -> None:
    ensure_model_allowed(model)


@pytest.mark.parametrize("path", [
    ("generation", "gen_model"), ("generation", "enrich_model"),
    ("generation", "gen_model_cli"), ("generation", "gen_model_http"),
    ("generation", "gen_model_mcp"), ("chat", "litellm", "default_model"),
    ("chat", "multimodal", "vision_model_override"),
    ("graph_indexing", "semantic_kg_llm_model"),
    ("indexing", "figures", "vision_model"), ("reranking", "reranker_cloud_model"),
    ("evaluation", "ragas_judge_model"), ("evaluation", "promptfoo_grader_model"),
])
def test_config_rejects_blocked_models_at_each_paid_lane(path: tuple[str, ...]) -> None:
    payload: object = "openai.gpt-4o-mini"
    for key in reversed(path):
        payload = {key: payload}
    with pytest.raises(ValidationError, match="GPT-4-class models are blocked"):
        TriBridConfig.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_constructed_transport_routes_cannot_bypass_policy(stream: bool) -> None:
    route = ProviderRoute(kind="litellm", provider_name="LiteLLM", model="openai.gpt-4o-mini",
                          base_url="http://127.0.0.1:1/v1", api_key="")
    args = dict(route=route, system_prompt="Explain spacecraft systems.",
                user_message="How did Apollo 11 measure propellant tank pressure?",
                images=[], temperature=0.0, max_tokens=100, context_chunks=[])
    with pytest.raises(ValueError, match="GPT-4-class models are blocked"):
        if stream:
            async for _ in stream_chat_text(**args):
                pytest.fail("Blocked model emitted output")
        else:
            await generate_chat_text(**args)


def test_clean_config_requires_an_explicit_cloud_reranker_selection() -> None:
    cfg = TriBridConfig()
    assert cfg.reranking.reranker_mode == "none"
    assert cfg.reranking.reranker_cloud_model == ""


@pytest.mark.parametrize("blocked_field", ["route_model", "route_upstream"])
def test_graph_extraction_sdk_refuses_blocked_routes(blocked_field: str) -> None:
    from server.indexing.graphrag_pipeline import semantic_extraction_llm

    route = dict(route_model="openai.gpt-5.6-luna", route_upstream="openrouter/openai/gpt-5.6-luna")
    route[blocked_field] = "openai.gpt-4o-mini"
    with pytest.raises(ValueError, match="GPT-4-class models are blocked"):
        semantic_extraction_llm(**route, route_base_url="http://127.0.0.1:1/v1",
                                route_api_key="", llm_timeout_s=30, reasoning_effort="none")


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_field", ["model_alias", "route_model", "route_upstream"])
async def test_schema_sdk_refuses_blocked_identity_before_sampling(blocked_field: str) -> None:
    from server.indexing.graphrag_schema import derive_graph_schema_proposal

    route = dict(model_alias="openai.gpt-5.6-luna", route_model="openai.gpt-5.6-luna",
                 route_upstream="openrouter/openai/gpt-5.6-luna")
    route[blocked_field] = "openai.gpt-4.1-mini"
    with pytest.raises(ValueError, match="GPT-4-class models are blocked"):
        await derive_graph_schema_proposal(**route, corpus_id="nasa-apollo-11", chunks=[],
                                           route_base_url="http://127.0.0.1:1/v1", route_api_key="",
                                           reasoning_effort="none", input_fingerprint="unused")


def test_figure_sdk_refuses_blocked_route_before_docling_setup() -> None:
    from server.indexing.text_extractors import FigureGateway, build_figure_pipeline_options

    gateway = FigureGateway(base_url="http://127.0.0.1:1/v1", api_key="", model="openai.gpt-4o")
    with pytest.raises(ValueError, match="GPT-4-class models are blocked"):
        build_figure_pipeline_options(TriBridConfig().indexing.figures, gateway)
