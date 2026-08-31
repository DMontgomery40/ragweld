from __future__ import annotations

import pytest
from neo4j_graphrag.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.indexing.official_graphrag import (
    GRAPH_RAG_CHUNK_LABEL,
    GRAPH_RAG_DOCUMENT_LABEL,
    GRAPH_RAG_FROM_CHUNK,
    _count_semantic_edges,
    _lexical_graph_config,
    write_lexical_graph_with_graphrag,
)
from server.models.index import Chunk


@pytest.mark.asyncio
async def test_write_lexical_graph_with_graphrag_uses_unscoped_official_contract() -> None:
    chunks = [
        Chunk(
            chunk_id="chunk-1",
            content="hello world",
            file_path="docs/test.txt",
            start_line=1,
            end_line=3,
            token_count=4,
            embedding=[0.1, 0.2],
        )
    ]

    graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
        repo_id="repo-1",
        run_id="run-1",
        file_path="docs/test.txt",
        chunks=chunks,
    )

    assert lexical_graph_config.chunk_node_label == GRAPH_RAG_CHUNK_LABEL
    assert lexical_graph_config.document_node_label == GRAPH_RAG_DOCUMENT_LABEL
    assert lexical_graph_config.chunk_to_document_relationship_type == "FROM_DOCUMENT"
    assert lexical_graph_config.next_chunk_relationship_type == "NEXT_CHUNK"
    assert lexical_graph_config.node_to_chunk_relationship_type == "FROM_CHUNK"

    chunk_node = next(node for node in graph.nodes if node.label == GRAPH_RAG_CHUNK_LABEL)
    document_node = next(node for node in graph.nodes if node.label == GRAPH_RAG_DOCUMENT_LABEL)

    assert chunk_node.properties["chunk_id"] == "chunk-1"
    assert chunk_node.properties["file_path"] == "docs/test.txt"
    assert "embedding" not in chunk_node.properties

    assert document_node.properties["file_path"] == "docs/test.txt"
    assert not any(
        {"repo_id", "run_id", "graphJoinId"} & set(node.properties)
        for node in graph.nodes
    )
    assert not any(
        {"repo_id", "run_id", "graphJoinId"} & set(rel.properties)
        for rel in graph.relationships
    )
    assert all(rel.type != "IN_CHUNK" for rel in graph.relationships)


def test_count_semantic_edges_counts_entities_relations_and_empty_chunks() -> None:
    graph = Neo4jGraph(
        nodes=[
            Neo4jNode(id="chunk-1", label=GRAPH_RAG_CHUNK_LABEL, properties={"chunk_id": "chunk-1"}),
            Neo4jNode(id="chunk-2", label=GRAPH_RAG_CHUNK_LABEL, properties={"chunk_id": "chunk-2"}),
            Neo4jNode(id="alice", label="person", properties={"entity_id": "alice", "name": "Alice"}),
            Neo4jNode(id="openai", label="org", properties={"entity_id": "openai", "name": "OpenAI"}),
        ],
        relationships=[
            Neo4jRelationship(
                start_node_id="alice",
                end_node_id="openai",
                type="works_for",
                properties={},
            ),
            Neo4jRelationship(
                start_node_id="alice",
                end_node_id="chunk-1",
                type=GRAPH_RAG_FROM_CHUNK,
                properties={},
            ),
        ],
    )

    entity_count, relationship_count, empty_chunks = _count_semantic_edges(
        graph,
        lexical_graph_config=_lexical_graph_config(),
    )

    assert entity_count == 2
    assert relationship_count == 1
    assert empty_chunks == 1
