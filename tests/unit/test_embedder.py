"""Tests for the embedder module."""

import pytest
from unittest.mock import AsyncMock, patch

from server.indexing.embedder import Embedder
from server.models.tribrid_config_model import EmbeddingConfig
from server.models.index import Chunk


@pytest.fixture
def embedder() -> Embedder:
    """Create embedder with test config using LAW's field names."""
    config = EmbeddingConfig(
        embedding_type="openai",  # LAW uses 'embedding_type' not 'provider'
        embedding_model="text-embedding-3-small",  # LAW uses 'embedding_model' not 'model'
        embedding_dim=1536,  # LAW uses 'embedding_dim' not 'dimensions'
        embedding_batch_size=10,  # LAW uses 'embedding_batch_size' not 'batch_size'
    )
    return Embedder(config)


@pytest.mark.asyncio
async def test_embed_single(embedder: Embedder) -> None:
    """Test embedding a single text."""
    with patch.object(embedder, "embed", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [0.1] * 1536
        result = await embedder.embed("test text")
        assert len(result) == 1536


@pytest.mark.asyncio
async def test_embed_batch(embedder: Embedder) -> None:
    """Test batch embedding."""
    texts = ["text 1", "text 2", "text 3"]
    with patch.object(embedder, "embed_batch", new_callable=AsyncMock) as mock_batch:
        mock_batch.return_value = [[0.1] * 1536 for _ in texts]
        results = await embedder.embed_batch(texts)
        assert len(results) == 3
        assert all(len(r) == 1536 for r in results)


@pytest.mark.asyncio
async def test_embed_chunks(embedder: Embedder) -> None:
    """Test embedding chunks."""
    chunks = [
        Chunk(
            chunk_id="1",
            content="test content 1",
            file_path="test.py",
            start_line=1,
            end_line=5,
            language="python",
            token_count=10,
        ),
        Chunk(
            chunk_id="2",
            content="test content 2",
            file_path="test.py",
            start_line=6,
            end_line=10,
            language="python",
            token_count=10,
        ),
    ]

    with patch.object(embedder, "embed_batch", new_callable=AsyncMock) as mock_batch:
        mock_batch.return_value = [[0.1] * 1536, [0.2] * 1536]
        result = await embedder.embed_chunks(chunks)
        assert len(result) == 2
        assert result[0].embedding is not None
        assert result[1].embedding is not None
