from collections import defaultdict

from server.models.tribrid_config_model import FusionConfig
from server.models.retrieval import ChunkMatch
from server.retrieval.graph import GraphRetriever
from server.retrieval.sparse import SparseRetriever
from server.retrieval.vector import VectorRetriever


class TriBridFusion:
    def __init__(self, vector: VectorRetriever, sparse: SparseRetriever, graph: GraphRetriever):
        self.vector = vector
        self.sparse = sparse
        self.graph = graph

    async def search(self, repo_id: str, query: str, config: FusionConfig) -> list[ChunkMatch]:
        raise NotImplementedError

    def rrf_fusion(self, results: list[list[ChunkMatch]], k: int) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for result_list in results:
            for rank, chunk in enumerate(result_list):
                scores[chunk.chunk_id] += 1.0 / (k + rank + 1)
                chunk_map[chunk.chunk_id] = chunk
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [chunk_map[cid].model_copy(update={"score": scores[cid]}) for cid in sorted_ids]

    def weighted_fusion(self, results: list[list[ChunkMatch]], weights: list[float]) -> list[ChunkMatch]:
        scores: dict[str, float] = defaultdict(float)
        chunk_map: dict[str, ChunkMatch] = {}
        for weight, result_list in zip(weights, results):
            for chunk in result_list:
                scores[chunk.chunk_id] += chunk.score * weight
                chunk_map[chunk.chunk_id] = chunk
        sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [chunk_map[cid].model_copy(update={"score": scores[cid]}) for cid in sorted_ids]
