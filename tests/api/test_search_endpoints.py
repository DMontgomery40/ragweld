"""API tests for search endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_search(client: AsyncClient) -> None:
    """Test POST /api/search endpoint."""
    request = {
        "query": "How does authentication work?",
        "repo_id": "test-repo",
        "top_k": 10,
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [200, 404]  # 404 if repo doesn't exist

    if response.status_code == 200:
        data = response.json()
        assert "query" in data
        assert "matches" in data
        assert "fusion_method" in data
        assert "latency_ms" in data


@pytest.mark.asyncio
async def test_search_with_options(client: AsyncClient) -> None:
    """Test POST /api/search with search type options."""
    request = {
        "query": "Find login function",
        "repo_id": "test-repo",
        "top_k": 5,
        "include_vector": True,
        "include_sparse": True,
        "include_graph": False,
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [200, 404]


@pytest.mark.asyncio
async def test_search_empty_query(client: AsyncClient) -> None:
    """Test POST /api/search with empty query."""
    request = {
        "query": "",
        "repo_id": "test-repo",
    }
    response = await client.post("/api/search", json=request)
    assert response.status_code in [400, 422]


@pytest.mark.asyncio
async def test_answer(client: AsyncClient) -> None:
    """Test POST /api/answer endpoint."""
    request = {
        "query": "Explain the main function",
        "repo_id": "test-repo",
        "top_k": 5,
        "stream": False,
    }
    response = await client.post("/api/answer", json=request)
    assert response.status_code in [200, 404, 503]  # 503 if no LLM configured

    if response.status_code == 200:
        data = response.json()
        assert "query" in data
        assert "answer" in data
        assert "sources" in data


@pytest.mark.asyncio
async def test_answer_with_system_prompt(client: AsyncClient) -> None:
    """Test POST /api/answer with custom system prompt."""
    request = {
        "query": "What does this code do?",
        "repo_id": "test-repo",
        "system_prompt": "You are a senior code reviewer.",
        "stream": False,
    }
    response = await client.post("/api/answer", json=request)
    assert response.status_code in [200, 404, 503]


@pytest.mark.asyncio
async def test_answer_stream(client: AsyncClient) -> None:
    """Test POST /api/answer/stream endpoint."""
    request = {
        "query": "Explain the authentication flow",
        "repo_id": "test-repo",
        "stream": True,
    }
    response = await client.post("/api/answer/stream", json=request)
    assert response.status_code in [200, 404, 503]
