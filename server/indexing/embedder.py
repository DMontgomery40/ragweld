from __future__ import annotations

import asyncio
import hashlib
import math
import re

from server.models.index import Chunk
from server.models.tribrid_config_model import EmbeddingConfig

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{1,63}")


class Embedder:
    """Deterministic local embedder (placeholder).

    This repo is moving toward provider-backed embeddings (OpenAI/Voyage/local),
    but the backend currently needs a deterministic embedding implementation for
    tests and local dev without external dependencies.
    """

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        # Deterministic embeddings must match the configured dimensionality so that
        # Postgres pgvector storage and stats are consistent across the system.
        self.dim = max(32, int(getattr(config, "embedding_dim", 256) or 256))

    def _embed_sync(self, text: str) -> list[float]:
        tokens = _TOKEN_RE.findall((text or "").lower())
        vec = [0.0] * self.dim
        for tok in tokens:
            h = hashlib.md5(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def embed(self, text: str) -> list[float]:
        # Deterministic CPU work: offload to a thread so long indexing runs
        # don't block the FastAPI event loop (status endpoints, UI polling, etc.).
        return await asyncio.to_thread(self._embed_sync, text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(lambda: [self._embed_sync(t) for t in texts])

    async def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        if not chunks:
            return []
        embeddings = await self.embed_batch([c.content for c in chunks])
        return [c.model_copy(update={"embedding": emb}) for c, emb in zip(chunks, embeddings, strict=True)]
