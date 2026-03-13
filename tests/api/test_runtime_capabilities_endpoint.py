from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_runtime_capabilities_endpoint_exposes_current_runtime_surface(client: AsyncClient) -> None:
    response = await client.get("/api/runtime-capabilities")
    assert response.status_code == 200
    body = response.json()

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
