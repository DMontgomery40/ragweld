"""Tests for the reranker module - using LAW's RerankingConfig."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from server.models.tribrid_config_model import RerankingConfig
from server.models.retrieval import ChunkMatch
from server.retrieval.rerank import Reranker


def make_chunk(chunk_id: str, score: float) -> ChunkMatch:
    """Create a test chunk match."""
    return ChunkMatch(
        chunk_id=chunk_id,
        content=f"Content for {chunk_id}",
        file_path="test.py",
        start_line=1,
        end_line=10,
        language="python",
        score=score,
        source="vector",
    )


@pytest.fixture
def reranker_none() -> Reranker:
    """Create reranker with reranker_mode=none."""
    # LAW uses 'reranker_mode' not 'mode'
    config = RerankingConfig(reranker_mode="none")
    return Reranker(config)


def test_reranker_none_passthrough(reranker_none: Reranker) -> None:
    """Test that reranker_mode=none passes through unchanged."""
    chunks = [make_chunk("c1", 0.9), make_chunk("c2", 0.8), make_chunk("c3", 0.7)]

    # Synchronous test for passthrough
    assert reranker_none.config.reranker_mode == "none"


@pytest.mark.asyncio
async def test_reranker_none_async(reranker_none: Reranker) -> None:
    """Test async rerank with reranker_mode=none."""
    chunks = [make_chunk("c1", 0.9), make_chunk("c2", 0.8)]
    result = await reranker_none.rerank("test query", chunks)
    assert len(result) == 2
    # Order should be preserved
    assert result[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_reranker_local() -> None:
    """Test local cross-encoder reranking."""
    # LAW uses 'reranker_local_model' not 'local_model'
    # LAW uses 'tribrid_reranker_topn' (min=10) not 'top_n'
    config = RerankingConfig(
        reranker_mode="local",
        reranker_local_model="cross-encoder/ms-marco-MiniLM-L-12-v2",
        tribrid_reranker_topn=10,  # LAW minimum is 10
    )
    reranker = Reranker(config)

    chunks = [make_chunk("c1", 0.5), make_chunk("c2", 0.9), make_chunk("c3", 0.3)]

    with patch.object(reranker, "_rerank_local", new_callable=AsyncMock) as mock_rerank:
        # Mock returns reordered results
        mock_rerank.return_value = [chunks[1], chunks[0]]
        result = await reranker.rerank("test query", chunks)
        mock_rerank.assert_called_once()


@pytest.mark.asyncio
async def test_reranker_respects_top_n() -> None:
    """Test that reranker respects tribrid_reranker_topn limit."""
    # LAW uses 'tribrid_reranker_topn' (min=10, max=200) not 'top_n'
    config = RerankingConfig(reranker_mode="none", tribrid_reranker_topn=10)  # LAW minimum is 10
    reranker = Reranker(config)

    chunks = [make_chunk(f"c{i}", 0.9 - i * 0.1) for i in range(15)]  # More chunks than top_n
    result = await reranker.rerank("test query", chunks)
    assert len(result) <= 10


@pytest.mark.asyncio
async def test_reranker_empty_input() -> None:
    """Test reranker with empty input."""
    config = RerankingConfig(reranker_mode="none")
    reranker = Reranker(config)
    result = await reranker.rerank("test query", [])
    assert len(result) == 0
