from __future__ import annotations

from neo4j_graphrag.experimental.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.indexing.official_graphrag import (
    GRAPH_RAG_CHUNK_LABEL,
    GRAPH_RAG_FROM_CHUNK,
    _schema,
    _strip_openai_prefix,
    adapt_graphrag_graph,
)
from server.models.tribrid_config_model import TriBridConfig


def test_strip_openai_prefix_handles_prefixed_models() -> None:
    assert _strip_openai_prefix("openai/gpt-5.4-mini") == "gpt-5.4-mini"
    assert _strip_openai_prefix("litellm:openai/gpt-5.4-mini") == "gpt-5.4-mini"
    assert _strip_openai_prefix("gpt-5.4-mini") == "gpt-5.4-mini"


def test_adapt_graphrag_graph_keeps_typed_entities_relationships_and_chunk_links() -> None:
    graph = Neo4jGraph(
        nodes=[
            Neo4jNode(id="chunk-1", label=GRAPH_RAG_CHUNK_LABEL, properties={"chunk_id": "chunk-1"}),
            Neo4jNode(id="chunk-1:alice", label="person", properties={"name": "Alice"}),
            Neo4jNode(id="chunk-1:openai", label="org", properties={"name": "OpenAI"}),
        ],
        relationships=[
            Neo4jRelationship(
                start_node_id="chunk-1:alice",
                end_node_id="chunk-1:openai",
                type="works_for",
                properties={},
            ),
            Neo4jRelationship(
                start_node_id="chunk-1:alice",
                end_node_id="chunk-1",
                type=GRAPH_RAG_FROM_CHUNK,
                properties={},
            ),
        ],
    )

    adapted = adapt_graphrag_graph(graph, run_id="run-1")

    assert {entity.entity_type for entity in adapted.entities} == {"person", "org"}
    assert adapted.relationships[0].relation_type == "works_for"
    assert adapted.chunk_links == [{"entity_id": "chunk-1:alice", "chunk_id": "chunk-1"}]


def test_adapt_graphrag_graph_honors_configured_entity_and_relation_types() -> None:
    cfg = TriBridConfig.model_validate(
        {
            "graph_indexing": {
                "semantic_kg_allowed_entity_types": ["person"],
                "semantic_kg_allowed_relation_types": ["met_with"],
            }
        }
    )
    graph = Neo4jGraph(
        nodes=[
            Neo4jNode(id="chunk-1", label=GRAPH_RAG_CHUNK_LABEL, properties={"chunk_id": "chunk-1"}),
            Neo4jNode(id="chunk-1:alice", label="person", properties={"name": "Alice"}),
            Neo4jNode(id="chunk-1:openai", label="org", properties={"name": "OpenAI"}),
        ],
        relationships=[
            Neo4jRelationship(
                start_node_id="chunk-1:alice",
                end_node_id="chunk-1:openai",
                type="works_for",
                properties={},
            ),
            Neo4jRelationship(
                start_node_id="chunk-1:alice",
                end_node_id="chunk-1",
                type=GRAPH_RAG_FROM_CHUNK,
                properties={},
            ),
        ],
    )

    adapted = adapt_graphrag_graph(
        graph,
        run_id="run-1",
        allowed_entity_types=tuple(cfg.graph_indexing.semantic_kg_allowed_entity_types),
        allowed_relation_types=tuple(cfg.graph_indexing.semantic_kg_allowed_relation_types),
    )

    assert [entity.entity_type for entity in adapted.entities] == ["person"]
    assert adapted.relationships == []
    assert adapted.chunk_links == [{"entity_id": "chunk-1:alice", "chunk_id": "chunk-1"}]


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
