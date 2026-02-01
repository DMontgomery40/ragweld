"""Unit tests for Neo4j graph_search without a live Neo4j instance."""

from __future__ import annotations

import json

import pytest

from server.db.neo4j import Neo4jClient


class _FakeResult:
    def __init__(self, records: list[dict[str, object]]):
        self._records = records

    async def data(self) -> list[dict[str, object]]:
        return self._records


class _FakeSession:
    def __init__(self, records: list[dict[str, object]]):
        self._records = records
        self.last_query: str | None = None
        self.last_params: dict[str, object] | None = None

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, query: str, **params):
        self.last_query = query
        self.last_params = params
        return _FakeResult(self._records)


class _FakeDriver:
    def __init__(self, records: list[dict[str, object]]):
        self._records = records
        self.session_obj = _FakeSession(records)

    def session(self, database: str | None = None) -> _FakeSession:
        _ = database
        return self.session_obj


@pytest.mark.asyncio
async def test_graph_search_scoring_and_metadata() -> None:
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")

    records = [
        {
            "entity_id": "e1",
            "file_path": "src/foo.py",
            "properties_json": json.dumps({"start_line": 10, "end_line": 20}),
            "name": "Foo",
            "hops": 0,
            "direct_match": True,
        },
        {
            "entity_id": "e2",
            "file_path": "src/bar.py",
            "properties_json": json.dumps({"start_line": 1, "end_line": 1}),
            "name": "Bar",
            "hops": 2,
            "direct_match": False,
        },
    ]

    # Inject a fake driver so we never connect to Neo4j.
    client._driver = _FakeDriver(records)  # type: ignore[assignment]

    results = await client.graph_search(repo_id="test-corpus", query="Foo", max_hops=2, top_k=10)
    assert len(results) == 2

    top = results[0]
    tail = results[1]

    assert top.source == "graph"
    assert top.file_path == "src/foo.py"
    assert top.start_line == 10
    assert top.end_line == 20
    assert top.metadata.get("entity_id") == "e1"
    assert top.metadata.get("hops") == 0
    assert top.metadata.get("direct_match") is True

    assert tail.metadata.get("hops") == 2
    assert tail.metadata.get("direct_match") is False

    # Deterministic hop decay: closer hits should score higher.
    assert top.score > tail.score

    # Ensure Cypher params include tokens and the hop limit is inlined.
    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.last_query is not None
    assert session.last_params is not None
    assert session.last_params.get("repo_id") == "test-corpus"
    assert "*0..2" in session.last_query
    assert session.last_params.get("max_hops") is None
    assert "tokens" in session.last_params


@pytest.mark.asyncio
async def test_chunk_vector_search_builds_query_and_returns_chunk_ids() -> None:
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")

    records = [
        {"chunk_id": "c1", "score": 0.91},
        {"chunk_id": "c2", "score": 0.88},
    ]

    # Inject a fake driver so we never connect to Neo4j.
    client._driver = _FakeDriver(records)  # type: ignore[assignment]

    out = await client.chunk_vector_search(
        repo_id="test-corpus",
        embedding=[0.0, 0.1, 0.2],
        index_name="tribrid_chunk_embeddings",
        top_k=2,
        neighbor_window=1,
        overfetch_multiplier=10,
    )
    assert out == [("c1", 0.91), ("c2", 0.88)]

    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.last_query is not None
    assert "db.index.vector.queryNodes" in session.last_query
    assert "NEXT_CHUNK" in session.last_query
    assert session.last_params is not None
    assert session.last_params.get("repo_id") == "test-corpus"
    assert session.last_params.get("index_name") == "tribrid_chunk_embeddings"
    assert session.last_params.get("top_k") == 2
    assert session.last_params.get("seed_k") == 20


@pytest.mark.asyncio
async def test_entity_chunk_search_uses_in_chunk_links() -> None:
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")

    records = [
        {"chunk_id": "c1", "score": 0.5},
        {"chunk_id": "c2", "score": 0.4},
    ]
    client._driver = _FakeDriver(records)  # type: ignore[assignment]

    out = await client.entity_chunk_search(repo_id="test-corpus", query="Foo", max_hops=2, top_k=10)
    assert out == [("c1", 0.5), ("c2", 0.4)]

    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.last_query is not None
    assert "IN_CHUNK" in session.last_query
    assert session.last_params is not None
    assert session.last_params.get("repo_id") == "test-corpus"
    assert "*0..2" in session.last_query
    assert session.last_params.get("max_hops") is None
    assert session.last_params.get("limit") == 10
    assert "tokens" in session.last_params


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

    client._driver = _FakeDriver(records)  # type: ignore[assignment]

    out = await client.get_entity_neighbors(repo_id="test-corpus", entity_id="e1", max_hops=2, limit=200)
    assert out is not None
    assert len(out.entities) == 2
    assert {e.entity_id for e in out.entities} == {"e1", "e2"}
    assert len(out.relationships) == 1
    assert out.relationships[0].relation_type == "calls"
    assert out.relationships[0].source_id == "e1"
    assert out.relationships[0].target_id == "e2"

    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.last_query is not None
    assert "*1..2" in session.last_query
    assert session.last_params is not None
    assert session.last_params.get("repo_id") == "test-corpus"
    assert session.last_params.get("entity_id") == "e1"
    assert "max_hops" not in session.last_params

