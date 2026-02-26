"""Integration tests for the search pipeline."""

import pytest

from server.models.retrieval import (
    ChunkMatch,
    SearchRequest,
    SearchResponse,
    AnswerRequest,
    AnswerResponse,
)


@pytest.mark.integration
def test_search_request_defaults() -> None:
    """Test search request with defaults."""
    request = SearchRequest(
        query="How does authentication work?",
        repo_id="my-repo",
    )

    assert request.top_k == 20
    assert request.include_vector is True
    assert request.include_sparse is True
    assert request.include_graph is True


@pytest.mark.integration
def test_search_request_custom() -> None:
    """Test search request with custom settings."""
    request = SearchRequest(
        query="Find user login function",
        repo_id="auth-repo",
        top_k=10,
        include_vector=True,
        include_sparse=True,
        include_graph=False,
    )

    assert request.top_k == 10
    assert request.include_graph is False


@pytest.mark.integration
def test_chunk_match() -> None:
    """Test chunk match model."""
    match = ChunkMatch(
        chunk_id="c-123",
        content="def authenticate(user, password):\n    ...",
        file_path="auth/login.py",
        start_line=15,
        end_line=25,
        language="python",
        score=0.92,
        source="vector",
        metadata={"function_name": "authenticate"},
    )

    assert match.score == 0.92
    assert match.source == "vector"
    assert "function_name" in match.metadata


@pytest.mark.integration
def test_search_response() -> None:
    """Test search response model."""
    matches = [
        ChunkMatch(
            chunk_id=f"c{i}",
            content=f"Content {i}",
            file_path="test.py",
            start_line=i * 10,
            end_line=i * 10 + 9,
            language="python",
            score=0.9 - i * 0.1,
            source="vector" if i % 2 == 0 else "sparse",
        )
        for i in range(5)
    ]

    response = SearchResponse(
        query="test query",
        matches=matches,
        fusion_method="rrf",
        reranker_mode="learning",
        latency_ms=125.5,
        debug={"vector_count": 3, "sparse_count": 2},
    )

    assert len(response.matches) == 5
    assert response.fusion_method == "rrf"


@pytest.mark.integration
def test_answer_request() -> None:
    """Test answer request model."""
    request = AnswerRequest(
        query="Explain the authentication flow",
        repo_id="auth-repo",
        top_k=5,
        stream=True,
        system_prompt="You are a code documentation assistant.",
    )

    assert request.stream is True
    assert request.system_prompt is not None


@pytest.mark.integration
def test_answer_response() -> None:
    """Test answer response model."""
    sources = [
        ChunkMatch(
            chunk_id="c1",
            content="Authentication module code",
            file_path="auth.py",
            start_line=1,
            end_line=50,
            language="python",
            score=0.95,
            source="vector",
        )
    ]

    response = AnswerResponse(
        query="How does auth work?",
        answer="The authentication system uses JWT tokens...",
        sources=sources,
        model="gpt-4o-mini",
        tokens_used=450,
        latency_ms=1250.0,
    )

    assert len(response.sources) == 1
    assert response.tokens_used == 450
