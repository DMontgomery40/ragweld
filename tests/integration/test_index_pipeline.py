"""Integration tests for the indexing pipeline."""

from datetime import datetime

import pytest

from server.models.index import Chunk, IndexRequest, IndexStats, IndexStatus


@pytest.mark.integration
def test_chunk_model() -> None:
    """Test chunk model creation and serialization."""
    chunk = Chunk(
        chunk_id="chunk-001",
        content="def hello():\n    print('Hello, World!')",
        file_path="greeting.py",
        start_line=1,
        end_line=2,
        language="python",
        token_count=15,
        embedding=[0.1] * 1536,
        summary="A simple greeting function",
    )

    assert chunk.chunk_id == "chunk-001"
    assert chunk.language == "python"
    assert len(chunk.embedding) == 1536

    # Test serialization
    json_str = chunk.model_dump_json()
    restored = Chunk.model_validate_json(json_str)
    assert restored.chunk_id == chunk.chunk_id


@pytest.mark.integration
def test_index_request() -> None:
    """Test index request model."""
    request = IndexRequest(
        repo_id="my-repo",
        repo_path="/path/to/repo",
        force_reindex=True,
    )

    assert request.repo_id == "my-repo"
    assert request.force_reindex is True


@pytest.mark.integration
def test_index_status_states() -> None:
    """Test index status transitions."""
    # Initial state
    status = IndexStatus(
        repo_id="repo-1",
        status="idle",
        progress=0.0,
        current_file=None,
        error=None,
        started_at=None,
        completed_at=None,
    )
    assert status.status == "idle"

    # Indexing state
    status = IndexStatus(
        repo_id="repo-1",
        status="indexing",
        progress=0.5,
        current_file="src/main.py",
        error=None,
        started_at=datetime.utcnow(),
        completed_at=None,
    )
    assert status.status == "indexing"
    assert status.progress == 0.5

    # Complete state
    status = IndexStatus(
        repo_id="repo-1",
        status="complete",
        progress=1.0,
        current_file=None,
        error=None,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    assert status.status == "complete"


@pytest.mark.integration
def test_index_stats() -> None:
    """Test index statistics model."""
    stats = IndexStats(
        repo_id="repo-1",
        total_files=100,
        total_chunks=500,
        total_tokens=50000,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        last_indexed=datetime.utcnow(),
        file_breakdown={".py": 60, ".ts": 30, ".md": 10},
    )

    assert stats.total_files == 100
    assert stats.total_chunks == 500
    assert sum(stats.file_breakdown.values()) == 100
