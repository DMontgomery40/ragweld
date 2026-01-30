from server.models.tribrid_config_model import EmbeddingConfig
from server.models.index import Chunk


class Embedder:
    def __init__(self, config: EmbeddingConfig):
        self.config = config

    async def embed(self, text: str) -> list[float]:
        raise NotImplementedError

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    async def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        raise NotImplementedError
