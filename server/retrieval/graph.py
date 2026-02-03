from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import GraphSearchConfig


class GraphRetriever:
    def __init__(self, postgres: PostgresClient, neo4j: Neo4jClient, embedder: Embedder):
        self.postgres = postgres
        self.neo4j = neo4j
        self.embedder = embedder

    async def search(self, repo_id: str, query: str, config: GraphSearchConfig) -> list[ChunkMatch]:
        return await self.neo4j.graph_search(repo_id, query, config.max_hops, config.top_k)

    async def expand_context(
        self,
        repo_id: str,
        chunk_ids: list[str],
        *,
        max_hops: int,
        top_k: int,
    ) -> list[ChunkMatch]:
        """Expand from seed chunks through the entity graph.

        This is a small wrapper around Neo4jClient.expand_chunks_via_entities() that
        hydrates returned chunk IDs via Postgres into ChunkMatch results.
        """
        if not chunk_ids or int(top_k or 0) <= 0:
            return []
        hops = int(max_hops or 0)
        if hops <= 0:
            return []

        # Seed scores are treated as equal; Neo4j applies hop-based decay.
        seeds = [(cid, 1.0) for cid in chunk_ids if str(cid).strip()]
        if not seeds:
            return []

        hits = await self.neo4j.expand_chunks_via_entities(
            repo_id,
            seeds,
            max_hops=hops,
            top_k=int(top_k),
        )
        if not hits:
            return []

        score_by_id = {cid: float(score) for cid, score in hits}
        expanded_ids = [cid for cid, _score in hits]
        hydrated = await self.postgres.get_chunks(repo_id, expanded_ids)

        out: list[ChunkMatch] = []
        for ch in hydrated:
            score = score_by_id.get(ch.chunk_id)
            if score is None:
                continue
            out.append(
                ChunkMatch(
                    chunk_id=ch.chunk_id,
                    content=ch.content,
                    file_path=ch.file_path,
                    start_line=ch.start_line,
                    end_line=ch.end_line,
                    language=ch.language,
                    score=float(score),
                    source="graph",
                    metadata={
                        **(ch.metadata or {}),
                        "corpus_id": repo_id,
                        "graph_mode": "chunk",
                        "graph_expansion": True,
                        "graph_hops": int(hops),
                    },
                )
            )
        return out
