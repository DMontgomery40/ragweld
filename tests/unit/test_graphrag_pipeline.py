from __future__ import annotations

import pytest
from neo4j_graphrag.components.types import (
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
)

from server.indexing.graphrag_pipeline import (
    RESERVED_SCOPE_KEYS,
    GraphScopeCollisionError,
    build_semantic_pipeline,
    require_run_id,
    require_staging_graph_id,
    resolution_property_for_policy,
    run_component_coroutine_in_worker,
    stamp_graph_scope,
    validate_no_reserved_scope_keys,
)

RUN_ID = "a" * 32
STAGING_ID = f"__staging__apollo__{RUN_ID}"


def _graph() -> Neo4jGraph:
    return Neo4jGraph(
        nodes=[
            Neo4jNode(
                id="doc-1",
                label="Document",
                properties={"file_path": "mission.md"},
            ),
            Neo4jNode(
                id="chunk-1",
                label="Chunk",
                properties={
                    "chunk_id": "mission.md:1-4:0",
                    "file_path": "mission.md",
                    "embedding": [0.1, 0.2],
                },
            ),
            Neo4jNode(id="alice", label="Person", properties={"name": "Alice"}),
        ],
        relationships=[
            Neo4jRelationship(
                start_node_id="chunk-1",
                end_node_id="doc-1",
                type="FROM_DOCUMENT",
                properties={},
            ),
            Neo4jRelationship(
                start_node_id="alice",
                end_node_id="chunk-1",
                type="FROM_CHUNK",
                properties={},
            ),
        ],
    )


def test_scope_validators_accept_only_server_staging_ids_and_hex_run_ids() -> None:
    assert require_run_id(RUN_ID) == RUN_ID
    assert require_staging_graph_id(STAGING_ID) == STAGING_ID
    for bad in ("run-1", "A" * 32, "a" * 31, "a" * 33):
        with pytest.raises(ValueError):
            require_run_id(bad)
    for bad in ("apollo", f"__staging__apollo__{'g' * 32}", f"__staging____{RUN_ID}"):
        with pytest.raises(ValueError):
            require_staging_graph_id(bad)


def test_scope_stamp_is_complete_and_removes_chunk_embeddings() -> None:
    graph = _graph()
    lexical = LexicalGraphConfig()
    validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)
    stamp_graph_scope(graph, repo_id=STAGING_ID, run_id=RUN_ID, lexical=lexical)

    assert all(node.properties["repo_id"] == STAGING_ID for node in graph.nodes)
    assert all(node.properties["run_id"] == RUN_ID for node in graph.nodes)
    assert all(rel.properties["repo_id"] == STAGING_ID for rel in graph.relationships)
    assert all(rel.properties["run_id"] == RUN_ID for rel in graph.relationships)

    chunk = next(node for node in graph.nodes if node.label == lexical.chunk_node_label)
    entity = next(node for node in graph.nodes if node.label == "Person")
    document = next(node for node in graph.nodes if node.label == lexical.document_node_label)
    assert chunk.properties["graphJoinId"] == f"{STAGING_ID}:mission.md:1-4:0"
    assert chunk.properties["chunk_id"] == "mission.md:1-4:0"
    assert "embedding" not in chunk.properties
    assert entity.properties["entity_id"] == "alice"
    assert entity.properties["entity_type"] == "Person"
    assert document.properties["file_path"] == "mission.md"


@pytest.mark.parametrize("item_kind", ["node", "relationship"])
def test_reserved_scope_collision_is_rejected_before_stamping(item_kind: str) -> None:
    graph = _graph()
    if item_kind == "node":
        graph.nodes[0].properties["repo_id"] = "attacker"
    else:
        graph.relationships[0].properties["graphJoinId"] = "attacker"
    with pytest.raises(GraphScopeCollisionError, match=item_kind):
        validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)


@pytest.mark.asyncio
async def test_worker_component_guard_refuses_the_api_event_loop() -> None:
    async def _component() -> str:
        return "ok"

    with pytest.raises(RuntimeError, match="worker thread"):
        run_component_coroutine_in_worker(_component)


@pytest.mark.parametrize(
    ("model", "base_url", "api_key"),
    [("", "http://gateway/v1", "key"), ("model", "", "key"), ("model", "http://gateway/v1", "")],
)
def test_semantic_pipeline_refuses_an_incomplete_route_before_driver_use(
    model: str, base_url: str, api_key: str
) -> None:
    with pytest.raises(RuntimeError, match="requires"):
        build_semantic_pipeline(
            driver=object(),  # type: ignore[arg-type]
            neo4j_database="neo4j",
            repo_id=STAGING_ID,
            run_id=RUN_ID,
            route_model=model,
            route_base_url=base_url,
            route_api_key=api_key,
            max_concurrency=1,
        )


@pytest.mark.parametrize(("policy", "expected"), [("semantic", "name"), ("code", "entity_id")])
def test_resolution_property_follows_the_graph_policy(policy: str, expected: str) -> None:
    """Task 8 drive defect D7: exact-match resolution keyed on ``name`` collapsed every
    ``__init__``/``main`` of the code corpus into one node (81 classes "containing" one
    ``__init__``). A code symbol's identity is its qualified id; a semantic entity's is its
    extracted name.
    """
    assert resolution_property_for_policy(policy) == expected


@pytest.mark.parametrize("policy", ["off", "excluded", ""])
def test_resolution_property_rejects_policies_without_a_graph(policy: str) -> None:
    with pytest.raises(ValueError, match="resolvable graph"):
        resolution_property_for_policy(policy)
