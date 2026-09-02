from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever
from pydantic import ValidationError

from server.indexing.graphrag_pipeline import lexical_graph_config
from server.models.tribrid_config_model import GraphSearchConfig, TriBridConfig
from server.retrieval.graphrag_retriever import (
    ENTITY_LABEL,
    MAX_RELATED_ENTITIES_PER_SEED_CEILING,
    lexical_graph_shape,
    traversal_query,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPH_REPO_ID = "__staging__corpus__0123456789abcdef0123456789abcdef"
GLOSSARY_KEY = "GRAPH_MAX_RELATED_ENTITIES_PER_SEED"


def _query(
    *,
    graph_repo_id: str = GRAPH_REPO_ID,
    max_hops: int = 2,
    neighbor_window: int = 1,
    max_related_entities_per_seed: int = 50,
) -> str:
    return traversal_query(
        graph_repo_id=graph_repo_id,
        max_hops=max_hops,
        neighbor_window=neighbor_window,
        max_related_entities_per_seed=max_related_entities_per_seed,
    )


def test_official_qdrant_neo4j_retriever_contract_has_required_join_controls() -> None:
    params = inspect.signature(QdrantNeo4jRetriever).parameters

    assert "collection_name" in params
    assert "id_property_neo4j" in params
    assert "id_property_external" in params
    assert "using" in params
    assert "node_label_neo4j" in params
    assert "retrieval_query" in params


def test_traversal_starts_from_scoped_chunks_and_excludes_every_qdrant_seed() -> None:
    query = _query()

    assert f"node.repo_id = '{GRAPH_REPO_ID}'" in query
    assert "$match_params" in query
    assert "FROM_CHUNK" in query
    assert "NEXT_CHUNK" in query
    assert "related_chunk.graphJoinId IN seed_join_ids" in query
    assert "NOT related_chunk.graphJoinId IN seed_join_ids" in query
    assert "IN_CHUNK" not in query


def test_lexical_shape_comes_from_the_writer_contract() -> None:
    lexical = lexical_graph_config()
    shape = lexical_graph_shape()

    assert shape.chunk_label == lexical.chunk_node_label == "Chunk"
    assert shape.from_chunk == lexical.node_to_chunk_relationship_type == "FROM_CHUNK"
    assert shape.next_chunk == lexical.next_chunk_relationship_type == "NEXT_CHUNK"
    assert shape.structural_relationship_types == ("FROM_CHUNK", "FROM_DOCUMENT", "NEXT_CHUNK")
    assert ENTITY_LABEL == "__Entity__"


def test_traversal_expands_only_through_semantic_entity_relationships() -> None:
    query = _query(max_hops=2)
    scope = f"'{GRAPH_REPO_ID}'"

    assert (
        "MATCH entity_path=(seed_entity)-[entity_relationship*0..2]-(related_entity:__Entity__)"
        in query
    )
    # Every node on the path is an entity: a Chunk can never be an intermediate hop.
    assert (
        "all(entity_node IN nodes(entity_path)\n"
        f"                  WHERE entity_node:__Entity__ AND entity_node.repo_id = {scope})"
        in query
    )
    # No lexical-structure relationship can be a hop, so co-mention is not adjacency.
    assert (
        "all(entity_rel IN relationships(entity_path)\n"
        "                  WHERE NOT type(entity_rel) IN ['FROM_CHUNK', 'FROM_DOCUMENT', 'NEXT_CHUNK']"
        f" AND entity_rel.repo_id = {scope})" in query
    )
    # Chunk expansion happens only after the entity expansion, from resolved entities.
    assert query.index("RETURN related_entity, distance") < query.index(
        "MATCH (related_entity)-[related_source:FROM_CHUNK]->(related_chunk:Chunk)"
    )


def test_traversal_caps_related_entities_per_seed_nearest_first() -> None:
    query = _query(max_related_entities_per_seed=7)

    assert "WITH seed_entity, max(score) AS seed_score, seed_join_ids" in query
    assert "CALL (seed_entity) {" in query
    assert "min(length(entity_path)) AS distance" in query
    assert "count(entity_path) AS path_count" in query
    assert "ORDER BY distance ASC, path_count DESC, related_entity.entity_id ASC" in query
    assert "LIMIT 7" in query
    assert query.index("LIMIT 7") < query.index(
        "MATCH (related_entity)-[related_source:FROM_CHUNK]"
    )
    # Score decay by path length is kept, on the deduplicated seed score.
    assert "max(seed_score / (1.0 + distance)) AS expansion_score" in query


@pytest.mark.parametrize(("window", "present"), [(0, False), (1, True), (3, True)])
def test_neighbor_window_hydration_is_preserved(window: int, present: bool) -> None:
    query = _query(neighbor_window=window)

    assert (f"NEXT_CHUNK*1..{window}" in query) is present
    assert ("neighbor_rows" in query) is present


@pytest.mark.parametrize(
    ("repo_id", "max_hops", "neighbor_window", "max_related"),
    [
        ("bad repo id", 1, 0, 50),
        (GRAPH_REPO_ID, -1, 0, 50),
        (GRAPH_REPO_ID, 9, 0, 50),
        (GRAPH_REPO_ID, 1, -1, 50),
        (GRAPH_REPO_ID, 1, 11, 50),
        (GRAPH_REPO_ID, 1, 0, 0),
        (GRAPH_REPO_ID, 1, 0, MAX_RELATED_ENTITIES_PER_SEED_CEILING + 1),
    ],
)
def test_traversal_rejects_unbounded_or_unsafe_query_literals(
    repo_id: str, max_hops: int, neighbor_window: int, max_related: int
) -> None:
    with pytest.raises(ValueError):
        traversal_query(
            graph_repo_id=repo_id,
            max_hops=max_hops,
            neighbor_window=neighbor_window,
            max_related_entities_per_seed=max_related,
        )


def test_max_related_entities_per_seed_is_a_typed_tunable_with_glossary_terms() -> None:
    assert GraphSearchConfig().max_related_entities_per_seed == 50
    assert TriBridConfig().graph_search.max_related_entities_per_seed == 50
    for bad in (0, MAX_RELATED_ENTITIES_PER_SEED_CEILING + 1):
        with pytest.raises(ValidationError):
            GraphSearchConfig(max_related_entities_per_seed=bad)
    # The Cypher ceiling and the Pydantic ceiling are the same contract.
    assert "LIMIT 1000" in _query(
        max_related_entities_per_seed=MAX_RELATED_ENTITIES_PER_SEED_CEILING
    )
    for rel in ("data/glossary.json", "web/public/glossary.json"):
        terms = {
            term.get("key")
            for term in json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))["terms"]
        }
        assert GLOSSARY_KEY in terms, f"{rel} lacks {GLOSSARY_KEY}"
