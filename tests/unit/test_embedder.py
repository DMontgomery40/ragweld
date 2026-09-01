"""Tests for the embedder module."""

from unittest.mock import AsyncMock, patch

import pytest

from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.models.index import Chunk
from server.models.tribrid_config_model import EmbeddingConfig


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


@pytest.mark.asyncio
async def test_embed_batch_persistent_cache_reuses_vectors() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="deterministic",
            embedding_type="openai",
            embedding_model="text-embedding-3-small",
            embedding_dim=128,
            embedding_cache_enabled=True,
        )
    )

    cache_store: dict[str, list[float]] = {}
    upsert_calls = 0

    async def _lookup(input_hashes: list[str]) -> dict[str, list[float]]:
        return {h: cache_store[h] for h in input_hashes if h in cache_store}

    async def _upsert(entries: dict[str, tuple[str, list[float]]]) -> int:
        nonlocal upsert_calls
        upsert_calls += 1
        for h, (_, vec) in entries.items():
            cache_store[h] = list(vec)
        return len(entries)

    embedder.configure_cache_backend(lookup_batch=_lookup, upsert_batch=_upsert)

    first = await embedder.embed_batch(["hello cache"])
    second = await embedder.embed_batch(["hello cache"])

    assert len(first) == 1 and len(first[0]) == 128
    assert first == second
    assert upsert_calls == 1


@pytest.mark.asyncio
async def test_embed_chunks_accepts_contextual_override_texts() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="deterministic",
            embedding_type="openai",
            embedding_model="text-embedding-3-small",
            embedding_dim=128,
        )
    )
    chunk = Chunk(
        chunk_id="c1",
        content="same content",
        file_path="a.py",
        start_line=1,
        end_line=3,
        language="python",
        token_count=4,
    )

    plain = await embedder.embed_chunks([chunk])
    with_context = await embedder.embed_chunks([chunk], embed_texts=["[file=a.py] [line_range=1-3]\nsame content"])

    assert plain[0].embedding != with_context[0].embedding


def test_embedder_provider_methods_live_on_class() -> None:
    assert callable(Embedder._embed_openai)
    assert callable(Embedder._embed_mlx_embeddings)
    assert callable(Embedder._embed_local_sentence_transformers)


def test_configure_postgres_embedding_cache_backend_clears_stale_backend_when_postgres_lacks_cache_api() -> None:
    embedder = Embedder(
        EmbeddingConfig(
            embedding_backend="provider",
            embedding_type="local",
            embedding_model_local="all-MiniLM-L6-v2",
            embedding_dim=384,
            embedding_cache_enabled=True,
        )
    )

    async def _lookup(_input_hashes: list[str]) -> dict[str, list[float]]:
        return {}

    async def _upsert(_entries: dict[str, tuple[str, list[float]]]) -> int:
        return 0

    embedder.configure_cache_backend(lookup_batch=_lookup, upsert_batch=_upsert)
    assert embedder._cache_lookup_batch is not None
    assert embedder._cache_upsert_batch is not None

    configure_postgres_embedding_cache_backend(embedder, object())  # type: ignore[arg-type]

    assert embedder._cache_lookup_batch is None
    assert embedder._cache_upsert_batch is None
