from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import pytest
from neo4j import GraphDatabase

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.indexing.graphrag_pipeline import resolve_staged_entities

pytestmark = [pytest.mark.requires_neo4j, pytest.mark.asyncio]


async def _snapshot(neo: Neo4jClient, repo_id: str) -> str:
    rows = await neo.execute_cypher(
        """
        MATCH (n {repo_id: $repo_id})
        RETURN elementId(n) AS element_id, labels(n) AS labels, properties(n) AS properties
        ORDER BY element_id
        """,
        {"repo_id": repo_id},
    )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


async def _write(driver, database: str, query: str, parameters: dict) -> None:
    await asyncio.to_thread(
        driver.execute_query,
        query,
        parameters_=parameters,
        database_=database,
    )


async def test_official_exact_match_resolution_is_scoped_to_one_staged_generation() -> None:
    target_run = uuid4().hex
    other_run = uuid4().hex
    target = f"__staging__resolver-target__{target_run}"
    other = f"__staging__resolver-other__{other_run}"
    cfg = load_config()
    database = cfg.graph_storage.resolve_database("resolver-isolation")
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        auth=(
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        ),
    )
    await neo.connect()
    try:
        for repo_id, run_id in ((target, target_run), (other, other_run)):
            await _write(
                driver,
                database,
                """
                CREATE (:__Entity__:Person {
                    entity_id: randomUUID(), name: 'Ada', marker: 'first',
                    repo_id: $repo_id, run_id: $run_id
                })
                CREATE (:__Entity__:Person {
                    entity_id: randomUUID(), name: 'Ada', marker: 'second',
                    repo_id: $repo_id, run_id: $run_id
                })
                CREATE (:__Entity__:Organization {
                    entity_id: randomUUID(), name: 'Analytical Engines', marker: 'org',
                    repo_id: $repo_id, run_id: $run_id
                })
                """,
                {"repo_id": repo_id, "run_id": run_id},
            )
        other_before = await _snapshot(neo, other)

        telemetry = await resolve_staged_entities(
            driver=driver,
            neo4j_database=database,
            repo_id=target,
        )

        target_count = await neo.execute_cypher(
            "MATCH (n:__Entity__ {repo_id: $repo_id}) RETURN count(n) AS n",
            {"repo_id": target},
        )
        assert telemetry.candidate_nodes == 3
        assert telemetry.resolved_nodes == 2
        assert telemetry.merged_nodes == 1
        assert telemetry.unresolved_duplicate_groups == 0
        assert int(target_count[0]["n"]) == 2
        assert await _snapshot(neo, other) == other_before
    finally:
        await _write(
            driver,
            database,
            "MATCH (n) WHERE n.repo_id IN $repo_ids DETACH DELETE n",
            {"repo_ids": [target, other]},
        )
        await neo.disconnect()
        await asyncio.to_thread(driver.close)
