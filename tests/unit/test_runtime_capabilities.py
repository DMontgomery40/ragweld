from __future__ import annotations

import json
import os
from pathlib import Path

from server.models.chat_config import ChatConfig, LiteLLMConfig
from server.models.tribrid_config_model import TriBridConfig
from server.runtime_capabilities import (
    SUPPORTED_CHUNKING_STRATEGIES,
    SUPPORTED_PROVIDER_BACKEND_EMBEDDING_PROVIDERS,
    SUPPORTED_RERANKER_CLOUD_PROVIDERS,
    build_runtime_capabilities_response,
    build_runtime_capabilities_response_for_config,
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
