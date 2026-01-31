from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import VectorSearchConfig


class VectorRetriever:
    def __init__(self, postgres: PostgresClient, embedder: Embedder):
        self.postgres = postgres
        self.embedder = embedder

    async def search(self, repo_id: str, query: str, config: VectorSearchConfig) -> list[ChunkMatch]:
        embedding = await self.embedder.embed(query)
        results = await self.postgres.vector_search(repo_id, embedding, config.top_k)
        if config.similarity_threshold > 0:
            results = [r for r in results if r.score >= config.similarity_threshold]
        return results
