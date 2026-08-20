from __future__ import annotations

import pytest
from neo4j_graphrag.experimental.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.indexing.official_graphrag import (
    GRAPH_RAG_CHUNK_LABEL,
    GRAPH_RAG_DOCUMENT_LABEL,
    GRAPH_RAG_FROM_CHUNK,
    _count_semantic_edges,
    _lexical_graph_config,
    _schema,
    write_lexical_graph_with_graphrag,
)
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.asyncio
async def test_write_lexical_graph_with_graphrag_tags_document_and_chunk_nodes() -> None:
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

    chunk_node = next(node for node in graph.nodes if node.label == GRAPH_RAG_CHUNK_LABEL)
    document_node = next(node for node in graph.nodes if node.label == GRAPH_RAG_DOCUMENT_LABEL)

    assert chunk_node.properties["repo_id"] == "repo-1"
    assert chunk_node.properties["run_id"] == "run-1"
    assert chunk_node.properties["chunk_id"] == "chunk-1"
    assert chunk_node.properties["file_path"] == "docs/test.txt"

    assert document_node.properties["repo_id"] == "repo-1"
    assert document_node.properties["run_id"] == "run-1"
    assert document_node.properties["file_path"] == "docs/test.txt"
    assert document_node.properties["document_id"] == "repo-1:docs/test.txt"


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


def test_schema_uses_configured_entity_and_relation_types() -> None:
    cfg = TriBridConfig.model_validate(
        {
            "graph_indexing": {
                "semantic_kg_allowed_entity_types": ["person", "event"],
                "semantic_kg_allowed_relation_types": ["met_with", "participated_in"],
            }
        }
    )

    schema = _schema(
        allowed_entity_types=tuple(cfg.graph_indexing.semantic_kg_allowed_entity_types),
        allowed_relation_types=tuple(cfg.graph_indexing.semantic_kg_allowed_relation_types),
    )

    assert [node.label for node in schema.node_types] == ["person", "event"]
    assert [rel.label for rel in schema.relationship_types] == ["met_with", "participated_in"]
    assert all(pattern.relationship in {"met_with", "participated_in"} for pattern in schema.patterns)
