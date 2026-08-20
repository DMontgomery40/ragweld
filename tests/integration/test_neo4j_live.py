from __future__ import annotations

import os

import pytest

from server.db.neo4j import Neo4jClient


@pytest.mark.requires_neo4j
@pytest.mark.asyncio
async def test_neo4j_client_bootstraps_schema_from_empty_store() -> None:
    client = Neo4jClient(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    await client.connect()
    try:
        status = await client.ping()
        await client.ensure_schema()
        assert status["ok"] is True
    finally:
        await client.disconnect()
