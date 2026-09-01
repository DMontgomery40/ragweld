"""Official GraphRAG adapter for Qdrant-seeded, generation-scoped Neo4j traversal."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever
from neo4j_graphrag.types import RetrieverResultItem
from qdrant_client import QdrantClient

from server.indexing.graphrag_pipeline import require_staging_graph_id
from server.retrieval.qdrant_store import DENSE_VECTOR_NAME


@dataclass(frozen=True, slots=True)
class GraphTraversalResult:
    chunk_scores: tuple[tuple[str, float], ...]
    qdrant_seed_chunks: int
    resolved_entities: int
    relationship_expansion_hits: int
    community_expansion_hits: int = 0
    resolved_entity_ids: tuple[str, ...] = ()


def _bounded_int(value: int, *, name: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def traversal_query(*, graph_repo_id: str, max_hops: int, neighbor_window: int) -> str:
    """Build the retrieval tail appended to GraphRAG's external-store match query.

    Neo4j GraphRAG currently parameterizes only ``match_params`` and
    ``id_property`` for this retriever. The staged graph id and traversal
    bounds therefore must be validated server-generated literals before they
    enter the Cypher tail.
    """
    repo_id = require_staging_graph_id(graph_repo_id)
    hops = _bounded_int(max_hops, name="max_hops", minimum=0, maximum=5)
    window = _bounded_int(neighbor_window, name="neighbor_window", minimum=0, maximum=10)
    scope = f"'{repo_id}'"
    neighbor_query = ""
    neighbor_candidates = "[]"
    if window:
        neighbor_query = f"""
        OPTIONAL MATCH neighbor_path=(related_chunk)-[neighbor_rel:NEXT_CHUNK*1..{window}]-(neighbor:Chunk)
        WHERE neighbor.repo_id = {scope}
          AND all(rel IN neighbor_rel WHERE rel.repo_id = {scope})
          AND NOT neighbor.graphJoinId IN seed_join_ids
        WITH related_chunk, expansion_score, resolved_entity_ids, seed_join_ids,
             collect(DISTINCT CASE WHEN neighbor IS NULL THEN NULL ELSE {{
                 chunk: neighbor,
                 score: expansion_score / (1.0 + length(neighbor_path)),
                 entity_ids: resolved_entity_ids
             }} END) AS neighbor_rows
        """
        neighbor_candidates = "[row IN neighbor_rows WHERE row IS NOT NULL]"
    return f"""
    AND node.repo_id = {scope}
    WITH node, score, [match_param IN $match_params | match_param[0]] AS seed_join_ids
    MATCH (seed_entity:__Entity__)-[seed_source:FROM_CHUNK]->(node)
    WHERE seed_entity.repo_id = {scope}
      AND seed_source.repo_id = {scope}
    MATCH entity_path=(seed_entity)-[entity_relationship*0..{hops}]-(related_entity:__Entity__)
    WHERE all(entity_node IN nodes(entity_path) WHERE entity_node.repo_id = {scope})
      AND all(entity_rel IN relationships(entity_path) WHERE entity_rel.repo_id = {scope})
    MATCH (related_entity)-[related_source:FROM_CHUNK]->(related_chunk:Chunk)
    WHERE related_entity.repo_id = {scope}
      AND related_source.repo_id = {scope}
      AND related_chunk.repo_id = {scope}
      AND NOT related_chunk.graphJoinId IN seed_join_ids
    WITH related_chunk,
         max(score / (1.0 + length(entity_path))) AS expansion_score,
         collect(DISTINCT seed_entity.entity_id) + collect(DISTINCT related_entity.entity_id)
             AS resolved_entity_ids,
         seed_join_ids
    {neighbor_query}
    WITH [{{chunk: related_chunk, score: expansion_score, entity_ids: resolved_entity_ids}}]
         + {neighbor_candidates} AS candidates,
         seed_join_ids
    UNWIND candidates AS candidate
    WITH candidate.chunk AS chunk,
         max(candidate.score) AS expansion_score,
         reduce(ids = [], entity_ids IN collect(candidate.entity_ids) |
             ids + [entity_id IN entity_ids WHERE entity_id IS NOT NULL AND NOT entity_id IN ids])
             AS resolved_entity_ids,
         seed_join_ids
    WHERE chunk IS NOT NULL
      AND NOT chunk.graphJoinId IN seed_join_ids
    RETURN chunk.chunk_id AS chunk_id,
           expansion_score AS score,
           resolved_entity_ids
    ORDER BY score DESC, chunk_id ASC
    """


def _format_record(record: Mapping[str, Any]) -> RetrieverResultItem:
    entity_ids = tuple(
        sorted({str(value) for value in (record.get("resolved_entity_ids") or []) if value})
    )
    return RetrieverResultItem(
        content={
            "chunk_id": str(record.get("chunk_id") or ""),
            "score": float(record.get("score") or 0.0),
        },
        metadata={"resolved_entity_ids": list(entity_ids)},
    )


def _retrieve_sync(
    *,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
    qdrant_url: str,
    collection_name: str,
    graph_repo_id: str,
    query_vector: list[float],
    top_k: int,
    max_hops: int,
    neighbor_window: int,
) -> GraphTraversalResult:
    seed_join_ids: set[str] = set()

    def _join_id(point: Any) -> str:
        value = str((point.payload or {}).get("graph_join_id") or "")
        if value:
            seed_join_ids.add(value)
        return value

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    qdrant = QdrantClient(url=qdrant_url, timeout=30)
    try:
        driver.verify_connectivity()
        retriever = QdrantNeo4jRetriever(
            driver=driver,
            client=qdrant,
            collection_name=collection_name,
            id_property_neo4j="graphJoinId",
            id_property_external="graph_join_id",
            using=DENSE_VECTOR_NAME,
            retrieval_query=traversal_query(
                graph_repo_id=graph_repo_id,
                max_hops=max_hops,
                neighbor_window=neighbor_window,
            ),
            result_formatter=_format_record,
            neo4j_database=neo4j_database,
            node_label_neo4j="Chunk",
            id_property_getter=_join_id,
        )
        result = retriever.search(query_vector=query_vector, top_k=max(1, int(top_k)))
        chunk_scores: list[tuple[str, float]] = []
        resolved: set[str] = set()
        for item in result.items:
            content = item.content if isinstance(item.content, Mapping) else {}
            metadata = item.metadata or {}
            chunk_id = str(content.get("chunk_id") or "")
            if not chunk_id:
                continue
            entity_ids = {
                str(value) for value in metadata.get("resolved_entity_ids", []) if value
            }
            resolved.update(entity_ids)
            chunk_scores.append((chunk_id, float(content.get("score") or 0.0)))
        chunk_scores.sort(key=lambda hit: (-hit[1], hit[0]))
        selected = tuple(chunk_scores[: max(1, int(top_k))])
        return GraphTraversalResult(
            chunk_scores=selected,
            qdrant_seed_chunks=len(seed_join_ids),
            resolved_entities=len(resolved),
            relationship_expansion_hits=len(selected),
            resolved_entity_ids=tuple(sorted(resolved)),
        )
    finally:
        qdrant.close()
        driver.close()


async def retrieve_graph_chunks(
    *,
    neo4j_uri: str,
    neo4j_user: str,
    neo4j_password: str,
    neo4j_database: str,
    qdrant_url: str,
    collection_name: str,
    graph_repo_id: str,
    query_vector: list[float],
    top_k: int,
    max_hops: int,
    neighbor_window: int,
) -> GraphTraversalResult:
    """Run all synchronous official-retriever I/O off the application event loop."""
    return await asyncio.to_thread(
        _retrieve_sync,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        neo4j_database=neo4j_database,
        qdrant_url=qdrant_url,
        collection_name=collection_name,
        graph_repo_id=graph_repo_id,
        query_vector=query_vector,
        top_k=top_k,
        max_hops=max_hops,
        neighbor_window=neighbor_window,
    )


__all__ = [
    "GraphTraversalResult",
    "retrieve_graph_chunks",
    "traversal_query",
]
