"""Unit tests for Neo4j graph browsing without a live Neo4j instance."""

from __future__ import annotations

import json

import pytest

from server.db.neo4j import Neo4jClient


class _FakeResult:
    def __init__(self, records: list[dict[str, object]]):
        self._records = records

    async def data(self) -> list[dict[str, object]]:
        return self._records

    async def single(self) -> dict[str, object] | None:
        return self._records[0] if self._records else None


class _FakeSession:
    def __init__(self, records: list[dict[str, object]], neighbour_count: int = 0):
        self._records = records
        self._neighbour_count = neighbour_count
        self.last_query: str | None = None
        self.last_params: dict[str, object] | None = None
        self.count_query: str | None = None
        self.count_params: dict[str, object] | None = None

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, query: str, **params):
        # `get_entity_neighbors` issues TWO queries - the neighbours query and then the
        # pre-limit count - so the count must be captured in its own slot. Recording both
        # into `last_query` let the later count query overwrite it, which silently
        # repointed every `last_query` assertion at a different Cypher statement that
        # happened to satisfy them all (review N-01).
        if "AS neighbours" in query:
            self.count_query = query
            self.count_params = params
            return _FakeResult([{"neighbours": self._neighbour_count}])
        self.last_query = query
        self.last_params = params
        return _FakeResult(self._records)


class _FakeDriver:
    def __init__(self, records: list[dict[str, object]], neighbour_count: int = 0):
        self._records = records
        self.session_obj = _FakeSession(records, neighbour_count)

    def session(self, database: str | None = None) -> _FakeSession:
        _ = database
        return self.session_obj


@pytest.mark.asyncio
async def test_get_entity_neighbors_inlines_hops_and_parses_response() -> None:
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")

    records = [
        {
            "entities": [
                {
                    "entity_id": "e1",
                    "name": "Foo",
                    "entity_type": "function",
                    "file_path": "src/foo.py",
                    "description": None,
                    "properties_json": json.dumps({"start_line": 1, "end_line": 2}),
                },
                {
                    "entity_id": "e2",
                    "name": "bar",
                    "entity_type": "function",
                    "file_path": "src/bar.py",
                    "description": None,
                    "properties_json": json.dumps({}),
                },
            ],
            "relationships": [
                {
                    "source_id": "e1",
                    "target_id": "e2",
                    "relation_type": "calls",
                    "weight": 1.0,
                    "properties_json": json.dumps({"reason": "unit-test"}),
                }
            ],
        }
    ]

    # Five reachable neighbours, only two of which the capped query returned.
    client._driver = _FakeDriver(records, neighbour_count=5)  # type: ignore[assignment]

    out = await client.get_entity_neighbors(repo_id="test-corpus", entity_id="e1", max_hops=2, limit=200)
    assert out is not None
    assert len(out.entities) == 2
    assert {e.entity_id for e in out.entities} == {"e1", "e2"}
    assert len(out.relationships) == 1
    assert out.relationships[0].relation_type == "calls"
    assert out.relationships[0].source_id == "e1"
    assert out.relationships[0].target_id == "e2"
    # The centre sorts first, so a cap never drops the entity that was asked for.
    assert out.entities[0].entity_id == "e1"

    # Each query is pinned separately: `last_query` is the neighbours query the test is
    # named for, `count_query` the pre-limit count (review N-01).
    session = client._driver.session_obj  # type: ignore[union-attr]
    assert "AS neighbours" not in session.last_query
    assert "AS entities" in session.last_query or "entity_id: n.entity_id" in session.last_query
    assert session.count_query is not None and "AS neighbours" in session.count_query
    assert session.count_params is not None
    assert session.count_params.get("repo_id") == "test-corpus"
    assert session.count_params.get("entity_id") == "e1"
    # The count must exclude the centre; the `+ 1` for it is added in Python.
    assert "n <> center" in session.count_query
    # `total_matched` is the PRE-limit count (5 neighbours + the centre), not len(entities),
    # which would have equalled the cap for any truncated neighbourhood (review F-03).
    assert out.total_matched == 6
    assert out.limit == 200

    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.last_query is not None
    assert "*1..2" in session.last_query
    assert session.last_params is not None
    assert session.last_params.get("repo_id") == "test-corpus"
    assert session.last_params.get("entity_id") == "e1"
    assert "max_hops" not in session.last_params


@pytest.mark.asyncio
async def test_neighbourhood_keeps_schema_labels_and_schema_edges() -> None:
    """Task 8 drive defect D1 (2026-09-01, NASA Apollo 11 corpus).

    The official GraphRAG pipeline labels entities with the approved schema
    (``LaunchSite``, ``Tank``) and relates them with the approved relationship
    types (``LOCATED_AT``). The client used to coerce any label outside the AST
    vocabulary to ``concept`` and to drop any edge outside a fixed allowlist, so
    the explorer showed "Apollo 11 Launch Site (concept)" with "1 nodes • 0 edges"
    while the store held 1,938 edges. The neighbourhood must (a) keep the stored
    kind verbatim, (b) keep the schema edge, and (c) confine the walk to entity
    nodes of the generation instead of enumerating edge types.
    """
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")
    records = [
        {
            "entities": [
                {
                    "entity_id": "A11_MissionReport.pdf:4472-4488:462000:2",
                    "name": "Apollo 11 Launch Site",
                    "entity_type": "LaunchSite",
                    "file_path": None,
                    "description": None,
                    "properties_json": json.dumps({"location": "Cape Canaveral"}),
                },
                {
                    "entity_id": "A11_MissionReport.pdf:4472-4488:462000:1",
                    "name": "LOX tank",
                    "entity_type": "Tank",
                    "file_path": None,
                    "description": None,
                    "properties_json": json.dumps({"pressure": 42.0}),
                },
            ],
            "relationships": [
                {
                    "source_id": "A11_MissionReport.pdf:4472-4488:462000:1",
                    "target_id": "A11_MissionReport.pdf:4472-4488:462000:2",
                    "relation_type": "LOCATED_AT",
                    "weight": 1.0,
                    "properties_json": json.dumps({}),
                }
            ],
        }
    ]
    client._driver = _FakeDriver(records, neighbour_count=1)  # type: ignore[assignment]

    out = await client.get_entity_neighbors(
        repo_id="__staging__nasa-apollo-11__run",
        entity_id="A11_MissionReport.pdf:4472-4488:462000:2",
        max_hops=2,
        limit=200,
    )
    assert out is not None
    assert {e.entity_type for e in out.entities} == {"LaunchSite", "Tank"}
    assert [r.relation_type for r in out.relationships] == ["LOCATED_AT"]

    session = client._driver.session_obj  # type: ignore[union-attr]
    for query, params in ((session.last_query, session.last_params), (session.count_query, session.count_params)):
        assert query is not None and params is not None
        assert "allowed_rels" not in params, "edge types are not enumerated; the schema owns them"
        assert "$allowed_rels" not in query
        # The walk stays on entity nodes of this generation: a 2-hop path must not
        # cross a Chunk node and report co-mentioned entities as neighbours.
        assert "ALL(x IN nodes(p) WHERE x:__Entity__ AND x.repo_id = $repo_id)" in query


@pytest.mark.asyncio
async def test_an_entity_without_a_stored_name_is_not_reported_as_the_string_none() -> None:
    """Task 8 drive defect D4: generations built from a schema without a ``name`` identity
    property hold anonymous entities; the wire contract must carry an empty name, never the
    text "None" that ``str(None)`` produced for the promoted NASA generation.
    """
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")
    records = [
        {
            "entities": [
                {
                    "entity_id": "A11_MissionReport.pdf:1-103:0:1",
                    "name": None,
                    "entity_type": "Tank",
                    "file_path": None,
                    "description": None,
                    "properties_json": json.dumps({"pressure": 50.0}),
                }
            ],
            "relationships": [],
        }
    ]
    client._driver = _FakeDriver(records, neighbour_count=0)  # type: ignore[assignment]
    out = await client.get_entity_neighbors(
        repo_id="__staging__nasa-apollo-11__run", entity_id="A11_MissionReport.pdf:1-103:0:1", max_hops=1, limit=10
    )
    assert out is not None
    assert out.entities[0].name == ""
