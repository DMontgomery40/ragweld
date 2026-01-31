from server.db.neo4j import Neo4jClient
from server.indexing.embedder import Embedder
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import GraphSearchConfig


class GraphRetriever:
    def __init__(self, neo4j: Neo4jClient, embedder: Embedder):
        self.neo4j = neo4j
        self.embedder = embedder

    async def search(self, repo_id: str, query: str, config: GraphSearchConfig) -> list[ChunkMatch]:
        return await self.neo4j.graph_search(repo_id, query, config.max_hops, config.top_k)

    async def expand_context(self, chunk_ids: list[str], max_hops: int) -> list[ChunkMatch]:
        raise NotImplementedError
