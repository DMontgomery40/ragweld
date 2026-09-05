"""Official GraphRAG adapter for Qdrant-seeded, generation-scoped Neo4j traversal."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever
from neo4j_graphrag.types import RetrieverResultItem
from qdrant_client import QdrantClient
from qdrant_client import models as qmodels

from server.indexing.graphrag_pipeline import lexical_graph_config, require_staging_graph_id
from server.retrieval.qdrant_store import DENSE_VECTOR_NAME, point_id_for_chunk

ENTITY_LABEL = "__Entity__"
MAX_RELATED_ENTITIES_PER_SEED_CEILING = 1000

_CYPHER_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class GraphTraversalResult:
    chunk_scores: tuple[tuple[str, float], ...]
    qdrant_seed_chunks: int
    resolved_entities: int
    relationship_expansion_hits: int
    community_expansion_hits: int = 0
    resolved_entity_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LexicalGraphShape:
    """Structural labels and relationship types of the official lexical graph.

    These come from the same ``LexicalGraphConfig`` the index writer uses, so the
    traversal never guesses which edges are document structure rather than
    extracted semantics.
    """

    chunk_label: str
    from_chunk: str
    next_chunk: str
    structural_relationship_types: tuple[str, ...]


def _bounded_int(value: int, *, name: str, minimum: int, maximum: int) -> int:
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _cypher_identifier(value: str, *, name: str) -> str:
    if not _CYPHER_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{name} is not a safe Cypher identifier: {value!r}")
    return value


def lexical_graph_shape() -> LexicalGraphShape:
    lexical = lexical_graph_config()
    from_chunk = _cypher_identifier(
        str(lexical.node_to_chunk_relationship_type), name="node_to_chunk_relationship_type"
    )
    next_chunk = _cypher_identifier(
        str(lexical.next_chunk_relationship_type), name="next_chunk_relationship_type"
    )
    from_document = _cypher_identifier(
        str(lexical.chunk_to_document_relationship_type),
        name="chunk_to_document_relationship_type",
    )
    return LexicalGraphShape(
        chunk_label=_cypher_identifier(str(lexical.chunk_node_label), name="chunk_node_label"),
        from_chunk=from_chunk,
        next_chunk=next_chunk,
        structural_relationship_types=tuple(sorted({from_chunk, next_chunk, from_document})),
    )


def traversal_query(
    *,
    graph_repo_id: str,
    max_hops: int,
    neighbor_window: int,
    max_related_entities_per_seed: int,
) -> str:
    """Build the retrieval tail appended to GraphRAG's external-store match query.

    Neo4j GraphRAG currently parameterizes only ``match_params`` and
    ``id_property`` for this retriever. The staged graph id and traversal
    bounds therefore must be validated server-generated literals before they
    enter the Cypher tail.

    Expansion walks the semantic graph only: every node on an entity path is an
    entity and no relationship on it is lexical structure (``FROM_CHUNK``,
    ``NEXT_CHUNK``, ``FROM_DOCUMENT``), so two entities co-mentioned in one
    chunk are not neighbours unless the extractor linked them. Each seed entity
    keeps at most ``max_related_entities_per_seed`` related entities, nearest
    first, so a hub entity cannot pull the whole corpus into one query.

    The cap counts OTHER entities only. The seed itself is excluded from the
    capped set and added back at distance 0, so its own chunks are always
    reachable and ``max_related_entities_per_seed=1`` means one related entity --
    not zero, which is what a cap that counted the seed's own distance-0 row
    against itself used to mean.
    """
    repo_id = require_staging_graph_id(graph_repo_id)
    hops = _bounded_int(max_hops, name="max_hops", minimum=0, maximum=5)
    window = _bounded_int(neighbor_window, name="neighbor_window", minimum=0, maximum=10)
    related_cap = _bounded_int(
        max_related_entities_per_seed,
        name="max_related_entities_per_seed",
        minimum=1,
        maximum=MAX_RELATED_ENTITIES_PER_SEED_CEILING,
    )
    shape = lexical_graph_shape()
    scope = f"'{repo_id}'"
    structural = "[" + ", ".join(f"'{rel}'" for rel in shape.structural_relationship_types) + "]"
    neighbor_query = ""
    neighbor_candidates = "[]"
    if window:
        neighbor_query = f"""
        OPTIONAL MATCH neighbor_path=(related_chunk)-[neighbor_rel:{shape.next_chunk}*1..{window}]-(neighbor:{shape.chunk_label})
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
    MATCH (seed_entity:{ENTITY_LABEL})-[seed_source:{shape.from_chunk}]->(node)
    WHERE seed_entity.repo_id = {scope}
      AND seed_source.repo_id = {scope}
    WITH seed_entity, max(score) AS seed_score, seed_join_ids
    CALL (seed_entity) {{
        MATCH entity_path=(seed_entity)-[entity_relationship*0..{hops}]-(related_entity:{ENTITY_LABEL})
        WHERE related_entity <> seed_entity
          AND all(entity_node IN nodes(entity_path)
                  WHERE entity_node:{ENTITY_LABEL} AND entity_node.repo_id = {scope})
          AND all(entity_rel IN relationships(entity_path)
                  WHERE NOT type(entity_rel) IN {structural} AND entity_rel.repo_id = {scope})
        WITH related_entity,
             min(length(entity_path)) AS distance,
             count(entity_path) AS path_count
        ORDER BY distance ASC, path_count DESC, related_entity.entity_id ASC
        LIMIT {related_cap}
        RETURN collect({{entity: related_entity, distance: distance}}) AS related_entities
    }}
    UNWIND [{{entity: seed_entity, distance: 0}}] + related_entities AS expansion
    WITH seed_entity, seed_score, seed_join_ids,
         expansion.entity AS related_entity,
         expansion.distance AS distance
    MATCH (related_entity)-[related_source:{shape.from_chunk}]->(related_chunk:{shape.chunk_label})
    WHERE related_source.repo_id = {scope}
      AND related_chunk.repo_id = {scope}
      AND NOT related_chunk.graphJoinId IN seed_join_ids
    WITH related_chunk,
         max(seed_score / (1.0 + distance)) AS expansion_score,
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
    max_related_entities_per_seed: int,
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
                max_related_entities_per_seed=max_related_entities_per_seed,
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
            entity_ids = {str(value) for value in metadata.get("resolved_entity_ids", []) if value}
            resolved.update(entity_ids)
            chunk_scores.append((chunk_id, float(content.get("score") or 0.0)))
        # A common entity can connect hundreds of chunks with identical graph
        # evidence. Choosing those by chunk id returns the same arbitrary text for
        # unrelated questions. Use the existing query vector only to break ties
        # within this traversal-derived candidate set; graph scores and the seed
        # exclusion remain unchanged, so dense seeds receive no second credit.
        relevance: dict[str, float] = {}
        if chunk_scores:
            candidates = qdrant.query_points(
                collection_name=collection_name,
                query=query_vector,
                using=DENSE_VECTOR_NAME,
                query_filter=qmodels.Filter(must=[qmodels.HasIdCondition(
                    has_id=[point_id_for_chunk(chunk_id) for chunk_id, _ in chunk_scores],
                )]),
                limit=len(chunk_scores),
                with_payload=["id"],
                with_vectors=False,
            )
            relevance = {
                str((point.payload or {}).get("id") or ""): float(point.score)
                for point in candidates.points
            }
            if any(chunk_id not in relevance for chunk_id, _ in chunk_scores):
                raise ValueError("Graph candidates are missing from their Qdrant generation")
        chunk_scores.sort(key=lambda hit: (-hit[1], -relevance[hit[0]], hit[0]))
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
    max_related_entities_per_seed: int,
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
        max_related_entities_per_seed=max_related_entities_per_seed,
    )


__all__ = [
    "ENTITY_LABEL",
    "MAX_RELATED_ENTITIES_PER_SEED_CEILING",
    "GraphTraversalResult",
    "LexicalGraphShape",
    "lexical_graph_shape",
    "retrieve_graph_chunks",
    "traversal_query",
]
