from __future__ import annotations

import pytest

from server.indexing.embedder import Embedder
from server.models.tribrid_config_model import EmbeddingConfig, TokenizationConfig


class _ProbeEmbedder(Embedder):
    def __init__(self, config: EmbeddingConfig):
        super().__init__(config, TokenizationConfig())
        self.calls: list[tuple[str, list[str]]] = []

    async def _embed_mlx_embeddings(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("mlx", list(texts)))
        raise RuntimeError("mlx unavailable")

    async def _embed_local_backend(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(("local", list(texts)))
        return [[0.25] * self.dim for _ in texts]


@pytest.mark.asyncio
async def test_mlx_provider_falls_back_to_local_backend() -> None:
    embedder = _ProbeEmbedder(
        EmbeddingConfig(
            embedding_backend="provider",
            embedding_type="mlx",
            embedding_model_mlx="mlx-community/all-MiniLM-L6-v2-4bit",
            embedding_model_local="all-MiniLM-L6-v2",
            embedding_dim=384,
        )
    )

    vectors = await embedder.embed_batch(["Jeffrey Epstein walked out of the Stockade on July 21, 2009."])

    assert len(vectors) == 1
    assert len(vectors[0]) == 384
    assert embedder.calls == [
        ("mlx", ["Jeffrey Epstein walked out of the Stockade on July 21, 2009."]),
        ("local", ["Jeffrey Epstein walked out of the Stockade on July 21, 2009."]),
    ]


@pytest.mark.asyncio
async def test_mlx_provider_without_local_model_keeps_original_error() -> None:
    embedder = _ProbeEmbedder(
        EmbeddingConfig(
            embedding_backend="provider",
            embedding_type="mlx",
            embedding_model_mlx="mlx-community/all-MiniLM-L6-v2-4bit",
            embedding_model_local="",
            embedding_dim=384,
        )
    )

    with pytest.raises(RuntimeError, match="mlx unavailable"):
        await embedder.embed_batch(["Jeffrey Epstein walked out of the Stockade on July 21, 2009."])

    assert embedder.calls == [("mlx", ["Jeffrey Epstein walked out of the Stockade on July 21, 2009."])]
