from __future__ import annotations

import os
from uuid import uuid4

import pytest

from server.db.neo4j import Neo4jClient
from server.indexing.official_graphrag import write_lexical_graph_with_graphrag
from server.models.index import Chunk


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


@pytest.mark.requires_neo4j
@pytest.mark.asyncio
async def test_official_graphrag_writer_round_trips_lexical_graph() -> None:
    repo_id = f"neo4j-live-{uuid4().hex}"
    client = Neo4jClient(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    chunks = [
        Chunk(
            chunk_id="chunk-1",
            content="first chunk",
            file_path="docs/live.txt",
            start_line=1,
            end_line=2,
            token_count=2,
            embedding=[0.1, 0.2],
        ),
        Chunk(
            chunk_id="chunk-2",
            content="second chunk",
            file_path="docs/live.txt",
            start_line=3,
            end_line=4,
            token_count=2,
            embedding=[0.3, 0.4],
        ),
    ]

    graph, lexical_graph_config = await write_lexical_graph_with_graphrag(
        repo_id=repo_id,
        run_id="live-round-trip",
        file_path="docs/live.txt",
        chunks=chunks,
    )

    await client.connect()
    try:
        await client.upsert_graphrag_graph(
            repo_id,
            graph,
            lexical_graph_config=lexical_graph_config,
        )
        driver = client._require_driver()
        async with driver.session(database=client.database) as session:
            result = await session.run(
                """
                MATCH (d:Document {repo_id: $repo_id, file_path: $file_path})
                MATCH (first:Chunk {repo_id: $repo_id, chunk_id: $first_chunk})-[:FROM_DOCUMENT]->(d)
                MATCH (first)-[:NEXT_CHUNK]->(second:Chunk {repo_id: $repo_id, chunk_id: $second_chunk})
                RETURN count(DISTINCT d) AS documents,
                       count(DISTINCT first) + count(DISTINCT second) AS chunks
                """,
                repo_id=repo_id,
                file_path="docs/live.txt",
                first_chunk="chunk-1",
                second_chunk="chunk-2",
            )
            record = await result.single()
        assert record is not None
        assert record["documents"] == 1
        assert record["chunks"] == 2
    finally:
        try:
            await client.delete_graph(repo_id)
        finally:
            await client.disconnect()
