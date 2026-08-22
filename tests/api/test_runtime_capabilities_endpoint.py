from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_runtime_capabilities_endpoint_exposes_current_runtime_surface(client: AsyncClient) -> None:
    response = await client.get("/api/runtime-capabilities")
    assert response.status_code == 200
    body = response.json()

    generation_routing = {str(item.get("id") or "") for item in body["generation"]["routing_backends"]}
    assert generation_routing == {"litellm"}

    generation_serving = {str(item.get("id") or "") for item in body["generation"]["serving_backends"]}
    assert generation_serving == {"vllm"}

    default_route = body["generation"]["default_route"]
    assert default_route is not None
    assert default_route["kind"] == "litellm"
    assert default_route["provider_name"] == "LiteLLM"
    assert default_route["model"] == "ragweld-local"

    embedding_providers = {str(item.get("provider") or "") for item in body["embedding"]["providers"]}
    assert embedding_providers == {"openai", "mlx", "local", "huggingface"}

    reranker_cloud_providers = {str(item.get("id") or "") for item in body["reranker"]["cloud_providers"]}
    assert reranker_cloud_providers == {"cohere"}

    reranker_learning_backends = {str(item.get("id") or "") for item in body["reranker"]["learning_backends"]}
    assert reranker_learning_backends == {"mlx_qwen3"}

    chunking_ids = {str(item.get("id") or "") for item in body["chunking"]["strategies"]}
    assert "semantic" not in chunking_ids
    assert {
        "ast",
        "hybrid",
        "greedy",
        "fixed_chars",
        "fixed_tokens",
        "recursive",
        "markdown",
        "sentence",
        "qa_blocks",
    }.issubset(chunking_ids)

    indexing_storage = {str(item.get("id") or "") for item in body["indexing"]["storage_backends"]}
    assert {
        "postgres_chunk_rows",
        "qdrant_dense",
        "qdrant_sparse_idf",
        "neo4j_lexical_graph",
        "neo4j_chunk_vector",
        "neo4j_semantic_kg",
    } == indexing_storage

    search_vector = {str(item.get("id") or "") for item in body["search"]["vector_backends"]}
    assert search_vector == {
        "qdrant_dense",
        "neo4j_chunk_vector",
    }
