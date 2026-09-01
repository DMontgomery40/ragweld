from __future__ import annotations

import re
from pathlib import Path

from server.graph.communities import (
    GDS_LEIDEN_ALGORITHM,
    GDS_VERSION_PREFIX,
    leiden_write_query,
    projection_name,
    projection_queries,
)


def test_projection_names_are_unique_and_cypher_safe() -> None:
    first = projection_name("__staging__corpus__0123456789abcdef0123456789abcdef")
    second = projection_name("__staging__corpus__0123456789abcdef0123456789abcdef")

    assert first != second
    assert re.fullmatch(r"ragweld_[a-f0-9]{32}", first)
    assert re.fullmatch(r"ragweld_[a-f0-9]{32}", second)


def test_projection_and_leiden_contract_are_scoped_weighted_and_deterministic() -> None:
    node_query, relationship_query = projection_queries()
    write_query = leiden_write_query()

    assert GDS_VERSION_PREFIX == "2.13."
    assert GDS_LEIDEN_ALGORITHM == "gds-leiden-2.13"
    assert ":__Entity__" in node_query and "$repo_id" in node_query
    assert ":__Entity__" in relationship_query and "$repo_id" in relationship_query
    assert "r.repo_id" not in relationship_query
    assert "coalesce(r.weight, 1.0)" in relationship_query
    assert "UNION ALL" in relationship_query
    assert "gds.leiden.write" in write_query
    assert "relationshipTypes: ['UNDIRECTED']" in write_query
    assert "communityPath" in write_query
    assert "includeIntermediateCommunities: true" in write_query
    assert "randomSeed: 19" in write_query
    assert "concurrency: 1" in write_query

    source = Path("server/graph/communities.py").read_text(encoding="utf-8")
    assert "gds.graph.relationships.toUndirected" in source
    assert "aggregation: 'SINGLE'" in source
