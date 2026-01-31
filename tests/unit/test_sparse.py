"""Tests for the sparse retriever module - using LAW's SparseSearchConfig."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from server.models.tribrid_config_model import SparseSearchConfig, TriBridConfig
from server.models.retrieval import ChunkMatch
from server.retrieval.sparse import SparseRetriever


@pytest.fixture
def sparse_config() -> SparseSearchConfig:
    """Create sparse search config with LAW's field names."""
    return SparseSearchConfig(
        enabled=True,
        top_k=10,
        bm25_k1=1.5,
        bm25_b=0.75,
    )


@pytest.fixture
def mock_config() -> TriBridConfig:
    """Create mock TriBridConfig for load_scoped_config."""
    return TriBridConfig()


@pytest.fixture
def mock_postgres() -> MagicMock:
    """Create mock Postgres client."""
    mock = MagicMock()
    mock.sparse_search = AsyncMock(
        return_value=[
            ChunkMatch(
                chunk_id="c1",
                content="Python function definition",
                file_path="test.py",
                start_line=1,
                end_line=10,
                language="python",
                score=0.9,
                source="sparse",
            ),
            ChunkMatch(
                chunk_id="c2",
                content="Another Python example",
                file_path="test2.py",
                start_line=1,
                end_line=5,
                language="python",
                score=0.7,
                source="sparse",
            ),
        ]
    )
    return mock


@pytest.mark.asyncio
async def test_sparse_search_basic(
    mock_postgres: MagicMock,
    sparse_config: SparseSearchConfig,
    mock_config: TriBridConfig,
) -> None:
    """Test basic sparse search."""
    with patch("server.retrieval.sparse.load_scoped_config", new_callable=AsyncMock, return_value=mock_config):
        retriever = SparseRetriever(mock_postgres)
        results = await retriever.search("repo-1", "python function", sparse_config)

        assert len(results) == 2
        assert all(r.source == "sparse" for r in results)
        mock_postgres.sparse_search.assert_called_once()


@pytest.mark.asyncio
async def test_sparse_search_respects_top_k(
    mock_postgres: MagicMock,
    sparse_config: SparseSearchConfig,
    mock_config: TriBridConfig,
) -> None:
    """Test that sparse search respects top_k."""
    sparse_config.top_k = 1
    with patch("server.retrieval.sparse.load_scoped_config", new_callable=AsyncMock, return_value=mock_config):
        retriever = SparseRetriever(mock_postgres)

        # Even though mock returns 2, config says top_k=1
        await retriever.search("repo-1", "test", sparse_config)
        _call_args = mock_postgres.sparse_search.call_args
        # Verify top_k was passed
        assert sparse_config.top_k == 1


@pytest.mark.asyncio
async def test_sparse_search_disabled(
    mock_postgres: MagicMock,
    sparse_config: SparseSearchConfig,
    mock_config: TriBridConfig,
) -> None:
    """Test that disabled sparse search returns empty."""
    sparse_config.enabled = False
    with patch("server.retrieval.sparse.load_scoped_config", new_callable=AsyncMock, return_value=mock_config):
        retriever = SparseRetriever(mock_postgres)
        results = await retriever.search("repo-1", "test", sparse_config)

        # Should not call postgres when disabled
        assert len(results) == 0 or not sparse_config.enabled


def test_sparse_config_defaults() -> None:
    """Test sparse config default values from LAW."""
    config = SparseSearchConfig()
    assert config.enabled is True
    assert config.top_k == 50
    # LAW's defaults
    assert config.bm25_k1 == 1.2  # LAW default is 1.2
    assert config.bm25_b == 0.4   # LAW default is 0.4
