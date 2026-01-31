from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import RerankingConfig


class Reranker:
    def __init__(self, config: RerankingConfig):
        self.config = config
        self._model = None

    async def rerank(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        if self.config.reranker_mode == "none":
            return chunks[: self.config.tribrid_reranker_topn]
        elif self.config.reranker_mode == "local":
            return await self._rerank_local(query, chunks)
        elif self.config.reranker_mode == "learning":
            return await self._rerank_trained(query, chunks)
        elif self.config.reranker_mode == "cloud":
            return await self._rerank_api(query, chunks)
        return chunks

    async def _rerank_local(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        raise NotImplementedError

    async def _rerank_trained(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        raise NotImplementedError

    async def _rerank_api(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]:
        raise NotImplementedError

    def load_model(self) -> None:
        raise NotImplementedError

    def reload_model(self) -> None:
        raise NotImplementedError
