"""Unit tests for Neo4j graph stats / community detection without a live Neo4j instance."""

from __future__ import annotations

import pytest

from server.db.neo4j import Neo4jClient


class _FakeResult:
    def __init__(
        self,
        *,
        single: dict[str, object] | None = None,
        data: list[dict[str, object]] | None = None,
    ) -> None:
        self._single = single
        self._data = data if data is not None else []

    async def single(self) -> dict[str, object] | None:
        return self._single

    async def data(self) -> list[dict[str, object]]:
        return self._data


class _QueueSession:
    def __init__(self, results: list[_FakeResult]):
        self._results = list(results)
        self.queries: list[str] = []
        self.params: list[dict[str, object]] = []

    async def __aenter__(self) -> "_QueueSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def run(self, query: str, **params):
        self.queries.append(query)
        self.params.append(params)
        if self._results:
            return self._results.pop(0)
        return _FakeResult()


class _FakeDriver:
    def __init__(self, results: list[_FakeResult]):
        self.session_obj = _QueueSession(results)

    def session(self, database: str | None = None) -> _QueueSession:
        _ = database
        return self.session_obj


@pytest.mark.asyncio
async def test_get_graph_stats_uses_optional_match_and_parses_counts() -> None:
    client = Neo4jClient(uri="bolt://fake", user="neo4j", password="test")

    client._driver = _FakeDriver(  # type: ignore[assignment]
        [
            _FakeResult(
                single={
                    "total_entities": 0,
                    "total_relationships": 0,
                    "total_communities": 0,
                    "total_documents": 3,
                    "total_chunks": 7,
                }
            ),
            _FakeResult(data=[]),
            _FakeResult(data=[]),
        ]
    )

    out = await client.get_graph_stats(repo_id="test-corpus")
    assert out.total_entities == 0
    assert out.total_relationships == 0
    assert out.total_communities == 0
    assert out.total_documents == 3
    assert out.total_chunks == 7

    session = client._driver.session_obj  # type: ignore[attr-defined]
    assert session.queries
    q0 = session.queries[0]
    assert "OPTIONAL MATCH (e:__Entity__" in q0
    assert "OPTIONAL MATCH (:__Entity__" in q0
    assert "OPTIONAL MATCH (c:Community" in q0


def _clique_pair_with_bridge() -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}

    def link(a: str, b: str) -> None:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)

    for i in range(6):
        for j in range(i + 1, 6):
            link(f"a{i}", f"a{j}")
            link(f"b{i}", f"b{j}")
    link("a0", "b0")
    adjacency["isolated"] = set()
    return adjacency


def test_modularity_groups_keep_bridged_cliques_apart_and_are_deterministic() -> None:
    """Label propagation collapsed two cliques joined by one bridge into one group
    (adversarial review of the 2026-08-25 drive fixes); Louvain must not."""
    from server.db.neo4j import _modularity_groups

    groups = _modularity_groups(_clique_pair_with_bridge())
    assert groups == [[f"a{i}" for i in range(6)], [f"b{i}" for i in range(6)]]
    assert groups == _modularity_groups(_clique_pair_with_bridge())  # stable partition
    assert _modularity_groups({"solo": set(), "pair": set()}) == []

