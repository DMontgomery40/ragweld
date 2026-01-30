from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import SparseSearchConfig
from server.models.retrieval import ChunkMatch


class SparseRetriever:
    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    async def search(self, repo_id: str, query: str, config: SparseSearchConfig) -> list[ChunkMatch]:
        return await self.postgres.sparse_search(repo_id, query, config.top_k)
