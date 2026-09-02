from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from server.gateway_catalog import LOCAL_GATEWAY_ALIAS
from server.models.chat_config import ChatConfig, LiteLLMConfig
from server.models.runtime_gateway import VLLMConfig
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.mlx_qwen3 import mlx_is_available
from server.runtime_capabilities import (
    GENERATION_SERVING_BACKEND_OPTIONS,
    SUPPORTED_CHUNKING_STRATEGIES,
    SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS,
    SUPPORTED_RERANKER_CLOUD_PROVIDERS,
    build_runtime_capabilities_response,
    build_runtime_capabilities_response_for_config,
    learning_agent_runtime_capability,
    validate_catalog_selection_metadata,
)


def test_runtime_capabilities_response_matches_backend_constants() -> None:
    response = build_runtime_capabilities_response()

    assert {item.id for item in response.generation.routing_backends} == {"litellm"}
    assert {item.id for item in response.generation.serving_backends} == {"vllm"}
    assert response.generation.default_route is not None
    assert response.generation.default_route.kind == "litellm"
    assert response.generation.default_route.provider_name == "LiteLLM"
    assert response.generation.default_route.model == "ragweld-local"

    assert {item.provider for item in response.embedding.providers} == SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS
    assert {item.id for item in response.reranker.cloud_providers} == SUPPORTED_RERANKER_CLOUD_PROVIDERS
    assert {item.id for item in response.chunking.strategies} == SUPPORTED_CHUNKING_STRATEGIES
    assert {item.id for item in response.indexing.storage_backends} == {
        "postgres_chunk_rows",
        "qdrant_dense",
        "qdrant_sparse_idf",
        "neo4j_lexical_graph",
        "neo4j_semantic_kg",
    }
    assert {item.id for item in response.search.vector_backends} == {"qdrant_dense"}
    assert {item.id for item in response.search.graph_backends} == {
        "qdrant_neo4j_traversal"
    }


def test_runtime_capabilities_can_resolve_litellm_as_default_generation_route() -> None:
    old_litellm = os.environ.get("LITELLM_API_KEY")
    os.environ.pop("LITELLM_API_KEY", None)
    try:
        cfg = TriBridConfig(
            chat=ChatConfig(
                litellm=LiteLLMConfig(
                    enabled=True,
                    base_url="http://127.0.0.1:4000/v1",
                    default_model="ragweld-local",
                ),
            ),
        )
        response = build_runtime_capabilities_response_for_config(cfg)
        assert response.generation.default_route is not None
        assert response.generation.default_route.kind == "litellm"
        assert response.generation.default_route.provider_name == "LiteLLM"
        assert response.generation.default_route.model == "ragweld-local"
        assert response.generation.default_route.base_url == "http://127.0.0.1:4000/v1"
    finally:
        if old_litellm is None:
            os.environ.pop("LITELLM_API_KEY", None)
        else:
            os.environ["LITELLM_API_KEY"] = old_litellm


def test_repo_catalog_selection_metadata_matches_runtime_rules() -> None:
    catalog_path = Path(__file__).resolve().parents[2] / "data" / "models.json"
    raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    rows = raw.get("models")
    assert isinstance(rows, list)
    models = [row for row in rows if isinstance(row, dict)]

    errors = validate_catalog_selection_metadata(models)
    assert not errors


def test_reranker_cloud_provider_schema_pattern_matches_runtime_options() -> None:
    """The config schema pattern and the runtime capability set must enumerate the same providers."""
    from server.models.tribrid_config_model import RerankingConfig

    pattern = str(RerankingConfig.model_fields["reranker_cloud_provider"].metadata[0].pattern)
    alternatives = set(pattern.strip("^$()").split("|"))
    assert alternatives == SUPPORTED_RERANKER_CLOUD_PROVIDERS


# ---------------------------------------------------------------------------
# Host-truth lanes: the local serving lane and the Learning Agent training lane
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
def test_generation_local_serving_capability_follows_the_effective_vllm_switch(enabled: bool) -> None:
    """Operator surfaces read whether the local lane is on from here, never from the catalog row."""
    cfg = TriBridConfig()
    cfg.chat.vllm = VLLMConfig(enabled=enabled, default_model="Qwen/Qwen3.8-27B-Instruct")

    lane = build_runtime_capabilities_response_for_config(cfg, mlx_available=False).generation.local_serving

    assert lane.alias == LOCAL_GATEWAY_ALIAS
    assert lane.enabled is enabled
    assert lane.backend in {item.id for item in GENERATION_SERVING_BACKEND_OPTIONS}
    assert lane.backend_label == "vLLM"
    assert lane.model == "Qwen/Qwen3.8-27B-Instruct"


@pytest.mark.parametrize("mlx_available", [True, False])
def test_learning_agent_capability_states_whether_the_host_backend_exists(mlx_available: bool) -> None:
    cfg = TriBridConfig()
    cfg.training.ragweld_agent_backend = "mlx_qwen3"
    cfg.training.ragweld_agent_base_model = "example-org/base-model-v9"
    cfg.training.ragweld_agent_model_path = "models/agent-store"

    lane = build_runtime_capabilities_response_for_config(cfg, mlx_available=mlx_available).training.learning_agent

    assert lane.execution_backend == "mlx_qwen3"
    assert lane.execution_locus == "host"
    assert lane.host_available is mlx_available
    assert lane.base_model == "example-org/base-model-v9"
    assert lane.artifact_path == "models/agent-store"
    if mlx_available:
        assert "runs on this host" in lane.availability_detail
        assert "fail closed" not in lane.availability_detail
    else:
        assert lane.availability_detail == (
            "Training backend mlx_qwen3 is not available on this host; runs will fail closed."
        )


def test_learning_agent_capability_places_unsloth_in_the_flyte_task_not_on_the_host() -> None:
    cfg = TriBridConfig()
    cfg.training.ragweld_agent_backend = "unsloth"

    lane = learning_agent_runtime_capability(cfg, mlx_available=True)

    assert lane.execution_locus == "flyte_task"
    assert lane.host_available is False
    assert "Flyte task image" in lane.availability_detail


def test_learning_agent_capability_fails_closed_on_an_unknown_backend() -> None:
    cfg = TriBridConfig()
    cfg.training.ragweld_agent_backend = "cuda_magic"

    lane = learning_agent_runtime_capability(cfg, mlx_available=True)

    assert lane.host_available is False
    assert "not a supported execution backend" in lane.availability_detail
    assert "fail closed" in lane.availability_detail


def test_runtime_capabilities_default_probe_matches_the_real_mlx_runtime_on_this_host() -> None:
    """Without an explicit probe result the surface reports what this host really has."""
    response = build_runtime_capabilities_response()

    assert response.training.learning_agent.host_available is mlx_is_available()
    assert response.generation.local_serving.alias == LOCAL_GATEWAY_ALIAS
