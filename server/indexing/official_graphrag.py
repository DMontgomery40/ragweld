from __future__ import annotations

from neo4j_graphrag.components.lexical_graph import LexicalGraphBuilder
from neo4j_graphrag.components.types import LexicalGraphConfig, Neo4jGraph

from server.indexing.graphrag_pipeline import chunks_to_text_chunks, document_info
from server.models.index import Chunk

GRAPH_RAG_CHUNK_LABEL = "Chunk"
GRAPH_RAG_DOCUMENT_LABEL = "Document"
GRAPH_RAG_CHUNK_TO_DOCUMENT = "FROM_DOCUMENT"
GRAPH_RAG_FROM_CHUNK = "FROM_CHUNK"


def _lexical_graph_config() -> LexicalGraphConfig:
    """The unmodified Neo4j GraphRAG 1.19 lexical contract."""
    return LexicalGraphConfig()


async def write_lexical_graph_with_graphrag(
    *,
    repo_id: str,
    run_id: str,
    file_path: str,
    chunks: list[Chunk],
) -> tuple[Neo4jGraph, LexicalGraphConfig]:
    """Build one complete unscoped lexical graph for a file.

    ``repo_id`` and ``run_id`` remain in the call shape until the index loop is
    replaced in this task, but are deliberately not placed in model output.
    Server-owned scope is applied only by ``ScopedNeo4jWriter`` after collision
    validation.
    """
    del repo_id, run_id
    lexical = _lexical_graph_config()
    graph_result = await LexicalGraphBuilder(config=lexical).run(
        text_chunks=chunks_to_text_chunks(chunks),
        # One owner for the Document writer id (namespaced, Task 8 drive defect D18).
        document_info=document_info(file_path),
    )
    return graph_result.graph, lexical


def _count_semantic_edges(
    graph: Neo4jGraph,
    *,
    lexical_graph_config: LexicalGraphConfig,
) -> tuple[int, int, int]:
    lexical_labels = set(lexical_graph_config.lexical_graph_node_labels)
    chunk_ids = {
        str(node.properties.get(lexical_graph_config.chunk_id_property) or node.id)
        for node in graph.nodes
        if node.label == lexical_graph_config.chunk_node_label
    }
    entity_ids = {
        str(node.properties.get("entity_id") or node.id)
        for node in graph.nodes
        if node.label not in lexical_labels
    }
    relationship_count = 0
    linked_chunk_ids: set[str] = set()
    for relationship in graph.relationships:
        if relationship.type == lexical_graph_config.node_to_chunk_relationship_type:
            if (
                str(relationship.start_node_id) in entity_ids
                and str(relationship.end_node_id) in chunk_ids
            ):
                linked_chunk_ids.add(str(relationship.end_node_id))
            continue
        if (
            str(relationship.start_node_id) in entity_ids
            and str(relationship.end_node_id) in entity_ids
        ):
            relationship_count += 1
    return (
        len(entity_ids),
        relationship_count,
        max(0, len(chunk_ids - linked_chunk_ids)),
    )


__all__ = [
    "GRAPH_RAG_CHUNK_LABEL",
    "GRAPH_RAG_CHUNK_TO_DOCUMENT",
    "GRAPH_RAG_DOCUMENT_LABEL",
    "GRAPH_RAG_FROM_CHUNK",
    "_count_semantic_edges",
    "_lexical_graph_config",
    "write_lexical_graph_with_graphrag",
]
