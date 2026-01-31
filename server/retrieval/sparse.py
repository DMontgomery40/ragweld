from server.db.postgres import PostgresClient
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import SparseSearchConfig
from server.services.config_store import get_config as load_scoped_config


class SparseRetriever:
    def __init__(self, postgres: PostgresClient):
        self.postgres = postgres

    async def search(self, repo_id: str, query: str, config: SparseSearchConfig) -> list[ChunkMatch]:
        # Keep sparse retrieval consistent with the corpus's tokenizer settings.
        cfg = await load_scoped_config(repo_id=repo_id)
        return await self.postgres.sparse_search(repo_id, query, config.top_k, ts_config=cfg.indexing.postgres_ts_config)
