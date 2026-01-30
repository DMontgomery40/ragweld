"""Tests for the chunker module."""

import pytest

from server.indexing.chunker import Chunker
from server.models.tribrid_config_model import ChunkingConfig


@pytest.fixture
def chunker() -> Chunker:
    """Create chunker with test config."""
    # Use LAW's ChunkingConfig with its field names
    # LAW has min chunk_size=200, max overlap must be < chunk_size
    config = ChunkingConfig(
        chunking_strategy="ast",  # LAW uses 'chunking_strategy' not 'strategy'
        chunk_size=500,  # LAW minimum is 200
        chunk_overlap=100,  # Must be < chunk_size
        min_chunk_chars=50,  # LAW min is 10, max is 500
    )
    return Chunker(config)


def test_chunker_init(chunker: Chunker) -> None:
    """Test chunker initialization."""
    assert chunker.config.chunk_size == 500
    assert chunker.config.chunk_overlap == 100


def test_chunk_file_not_implemented(chunker: Chunker) -> None:
    """Test chunk_file raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        chunker.chunk_file("test.py", "def foo(): pass")


def test_chunk_ast_not_implemented(chunker: Chunker) -> None:
    """Test chunk_ast raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        chunker.chunk_ast("test.py", "def foo(): pass", "python")
