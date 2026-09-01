from __future__ import annotations

import inspect

import pytest
from neo4j_graphrag.retrievers import QdrantNeo4jRetriever

from server.retrieval.graphrag_retriever import traversal_query


def test_official_qdrant_neo4j_retriever_contract_has_required_join_controls() -> None:
    params = inspect.signature(QdrantNeo4jRetriever).parameters

    assert "collection_name" in params
    assert "id_property_neo4j" in params
    assert "id_property_external" in params
    assert "using" in params
    assert "node_label_neo4j" in params
    assert "retrieval_query" in params


def test_traversal_starts_from_scoped_chunks_and_excludes_every_qdrant_seed() -> None:
    graph_repo_id = "__staging__corpus__0123456789abcdef0123456789abcdef"
    query = traversal_query(
        graph_repo_id=graph_repo_id,
        max_hops=2,
        neighbor_window=1,
    )

    assert f"node.repo_id = '{graph_repo_id}'" in query
    assert "$match_params" in query
    assert "FROM_CHUNK" in query
    assert "NEXT_CHUNK" in query
    assert "related_chunk.graphJoinId IN seed_join_ids" in query
    assert "NOT related_chunk.graphJoinId IN seed_join_ids" in query
    assert "IN_CHUNK" not in query


@pytest.mark.parametrize(
    ("repo_id", "max_hops", "neighbor_window"),
    [
        ("bad repo id", 1, 0),
        ("__staging__corpus__0123456789abcdef0123456789abcdef", -1, 0),
        ("__staging__corpus__0123456789abcdef0123456789abcdef", 9, 0),
        ("__staging__corpus__0123456789abcdef0123456789abcdef", 1, -1),
        ("__staging__corpus__0123456789abcdef0123456789abcdef", 1, 11),
    ],
)
def test_traversal_rejects_unbounded_or_unsafe_query_literals(
    repo_id: str, max_hops: int, neighbor_window: int
) -> None:
    with pytest.raises(ValueError):
        traversal_query(
            graph_repo_id=repo_id,
            max_hops=max_hops,
            neighbor_window=neighbor_window,
        )
