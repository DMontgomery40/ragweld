from __future__ import annotations

import pytest

from server.api.health import _probe_neo4j_readiness
from server.api.repos import _get_graph_stats_or_none
from server.models.tribrid_config_model import GraphStats, ReadinessDependencyStatus


class _PingFailureNeo4j:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def connect(self) -> None:
        self.events.append("connect")

    async def ping(self) -> dict[str, str]:
        self.events.append("ping")
        raise RuntimeError("neo4j ping failed")

    async def database_exists(self, _db_name: str) -> bool:
        raise AssertionError("database_exists should not run after ping failure")

    async def disconnect(self) -> None:
        self.events.append("disconnect")


class _DatabaseCheckFailureNeo4j:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def connect(self) -> None:
        self.events.append("connect")

    async def ping(self) -> dict[str, str]:
        self.events.append("ping")
        return {"status": "ok"}

    async def database_exists(self, _db_name: str) -> bool:
        self.events.append("database_exists")
        raise RuntimeError("database visibility denied")

    async def disconnect(self) -> None:
        self.events.append("disconnect")


class _GraphStatsFailureNeo4j:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def get_graph_stats(self, repo_id: str) -> GraphStats:
        self.events.append(f"get_graph_stats:{repo_id}")
        raise RuntimeError("graph stats failed")

    async def disconnect(self) -> None:
        self.events.append("disconnect")


@pytest.mark.asyncio
async def test_probe_neo4j_readiness_disconnects_on_ping_failure() -> None:
    neo4j = _PingFailureNeo4j()
    status = ReadinessDependencyStatus(database="corpus-db")

    with pytest.raises(RuntimeError, match="neo4j ping failed"):
        await _probe_neo4j_readiness(neo4j, db_name="corpus-db", status=status)

    assert neo4j.events == ["connect", "ping", "disconnect"]


@pytest.mark.asyncio
async def test_probe_neo4j_readiness_disconnects_when_database_check_fails() -> None:
    neo4j = _DatabaseCheckFailureNeo4j()
    status = ReadinessDependencyStatus(database="corpus-db")

    ready = await _probe_neo4j_readiness(neo4j, db_name="corpus-db", status=status)

    assert ready is False
    assert status.ok is False
    assert status.error == "Neo4j database readiness could not be verified."
    assert status.operator_hint == "Verify Neo4j database permissions and the resolved corpus database."
    assert neo4j.events == ["connect", "ping", "database_exists", "disconnect"]


@pytest.mark.asyncio
async def test_graph_stats_helper_disconnects_on_failure() -> None:
    neo4j = _GraphStatsFailureNeo4j()

    with pytest.raises(RuntimeError, match="graph stats failed"):
        await _get_graph_stats_or_none(neo4j, "cleanup-corpus")

    assert neo4j.events == ["get_graph_stats:cleanup-corpus", "disconnect"]
