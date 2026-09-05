"""Entity mention sources are real, generation-scoped FROM_CHUNK references."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from httpx import AsyncClient

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import build_generation
from server.models.index import Chunk, ChunkProvenance
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_neo4j, pytest.mark.asyncio]


@asynccontextmanager
async def _hold_source_query_response(uri: str) -> AsyncIterator[tuple[str, asyncio.Event, asyncio.Event]]:
    """Forward real Bolt traffic, pausing source-query responses for a manifest race.

    No database or application response is fabricated: this transport barrier lets
    the test commit a real promotion after the API has read its initial manifest.
    """
    upstream = urlsplit(uri)
    assert upstream.scheme == "bolt", "The live race fixture requires a plain Bolt connection"
    queried = asyncio.Event()
    release = asyncio.Event()
    connections: set[asyncio.Task[None]] = set()

    async def relay_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        upstream_writer: asyncio.StreamWriter | None = None
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(upstream.hostname, upstream.port or 7687)

            async def forward(source: asyncio.StreamReader, target: asyncio.StreamWriter, *, requests: bool) -> None:
                tail = b""
                while data := await source.read(65536):
                    if requests:
                        tail = (tail + data)[-65536:]
                        if b"RETURN sources" in tail:
                            queried.set()
                    elif queried.is_set():
                        await release.wait()
                    target.write(data)
                    await target.drain()
                target.close()

            async with asyncio.TaskGroup() as relays:
                relays.create_task(forward(reader, upstream_writer, requests=True))
                relays.create_task(forward(upstream_reader, writer, requests=False))
        finally:
            for connection in (writer, upstream_writer):
                if connection is not None:
                    connection.close()
                    with contextlib.suppress(ConnectionError):
                        await connection.wait_closed()

    def accept_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(relay_connection(reader, writer))
        connections.add(task)
        task.add_done_callback(connections.discard)

    server = await asyncio.start_server(accept_connection, "127.0.0.1", 0)
    try:
        yield f"bolt://127.0.0.1:{server.sockets[0].getsockname()[1]}", queried, release
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        for task in connections:
            task.cancel()
        await asyncio.gather(*connections, return_exceptions=True)


@pytest.mark.parametrize(
    ("entity_id", "offset"),
    [("linked", 0), ("linked", 1), ("unlinked", 0), ("missing", 0)],
    ids=["nonempty", "offset-past-end", "unlinked", "missing-entity"],
)
async def test_entity_sources_reject_generation_change_during_lookup(
    client: AsyncClient, entity_id: str, offset: int,
) -> None:
    corpus = f"pytest_graph_sources_race_{uuid4().hex[:8]}"
    run_id = uuid4().hex
    graph_repo = f"__staging__{corpus}__{run_id}"
    path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post("/api/corpora", json={"corpus_id": corpus, "name": corpus, "path": str(path)})
    assert created.status_code in (200, 201), created.text
    uri = require_env("NEO4J_URI")
    neo = Neo4jClient(uri, require_env("NEO4J_USER"), require_env("NEO4J_PASSWORD"))
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await neo.connect()
    await pg.connect()
    try:
        await pg.set_generation(corpus, build_generation(run_id=run_id, qdrant_collection=None, graph_repo_id=graph_repo))
        async with neo._require_driver().session(database=neo.database) as session:
            await session.run(
                """
                CREATE (e:__Entity__ {repo_id: $repo, run_id: $run, entity_id: 'linked'}),
                    (:__Entity__ {repo_id: $repo, run_id: $run, entity_id: 'unlinked'}),
                    (c:Chunk {repo_id: $repo, run_id: $run, chunk_id: 'source',
                        file_path: 'source.md', start_line: 1, end_line: 1, text: 'A real source mention'})
                CREATE (e)-[:FROM_CHUNK {repo_id: $repo, run_id: $run}]->(c)
                """,
                repo=graph_repo, run=run_id,
            )
        async with _hold_source_query_response(uri) as (proxy_uri, queried, release):
            previous_uri = os.environ.get("NEO4J_URI")
            os.environ["NEO4J_URI"] = proxy_uri
            request = asyncio.create_task(client.get(
                f"/api/graph/{corpus}/entity/sources",
                params={"entity_id": entity_id, "offset": offset, "run_id": run_id},
            ))
            try:
                await asyncio.wait_for(queried.wait(), timeout=10)
                assert not request.done(), "The source lookup must still be in flight at promotion"
                # A manifest may reuse the same graph under a new run. Even empty
                # lookups must notice the changed pagination token after the query.
                await pg.set_generation(corpus, build_generation(
                    run_id=uuid4().hex, qdrant_collection=None, graph_repo_id=graph_repo,
                ))
                release.set()
                response = await asyncio.wait_for(request, timeout=10)
                assert response.status_code == 409, response.text
                assert response.json()["detail"]["code"] == "graph_generation_changed"
            finally:
                release.set()
                if not request.done():
                    request.cancel()
                await asyncio.gather(request, return_exceptions=True)
                if previous_uri is None:
                    os.environ.pop("NEO4J_URI", None)
                else:
                    os.environ["NEO4J_URI"] = previous_uri
    finally:
        await neo.delete_graph(graph_repo)
        await neo.disconnect()
        await pg.disconnect()
        await client.delete(f"/api/corpora/{corpus}")


async def test_entity_sources_paginate_deduplicate_and_reject_foreign_generation_links(client: AsyncClient) -> None:
    corpus = f"pytest_graph_sources_{uuid4().hex[:8]}"
    run_id = uuid4().hex
    graph_repo = f"__staging__{corpus}__{run_id}"
    foreign_repo = f"__staging__{corpus}__{uuid4().hex}"
    path = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
    created = await client.post("/api/corpora", json={"corpus_id": corpus, "name": corpus, "path": str(path)})
    assert created.status_code in (200, 201), created.text
    neo = Neo4jClient(require_env("NEO4J_URI"), require_env("NEO4J_USER"), require_env("NEO4J_PASSWORD"))
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await neo.connect()
    await pg.connect()
    try:
        await pg.set_generation(corpus, build_generation(run_id=run_id, qdrant_collection=None, graph_repo_id=graph_repo))
        await pg.upsert_chunks(corpus, [
            Chunk(chunk_id="mention-1", file_path="tank-1.md", start_line=10, end_line=12,
                  content="Fuel tank inspection record 1", provenance=ChunkProvenance(extraction="direct"),
                  metadata={"char_start": 20, "char_end": 49}),
            Chunk(chunk_id="mention-2", file_path="tank-2.md", start_line=20, end_line=22,
                  content="A newer tank inspection record", provenance=ChunkProvenance(extraction="direct"),
                  metadata={"char_start": 50, "char_end": 70}),
        ])
        async with neo._require_driver().session(database=neo.database) as session:
            await session.run(
                """
                CREATE (e:__Entity__ {repo_id: $repo, run_id: $run, entity_id: 'merged/tank::1',
                    name: 'Fuel tank', entity_type: 'Tank'}),
                    (:__Entity__ {repo_id: $repo, run_id: $run, entity_id: 'unlinked', name: 'No mentions', entity_type: 'Tank'}),
                    (:__Entity__ {repo_id: $foreign, run_id: $run, entity_id: 'foreign-only', name: 'Foreign', entity_type: 'Tank'}),
                    (:__Entity__ {repo_id: $repo, run_id: 'wrong-run', entity_id: 'wrong-generation', name: 'Old', entity_type: 'Tank'})
                WITH e
                UNWIND range(1, 3) AS i
                CREATE (c:Chunk {repo_id: $repo, run_id: $run, chunk_id: 'mention-' + toString(i),
                    file_path: 'tank-' + toString(i) + '.md', start_line: i * 10, end_line: i * 10 + 2,
                    text: 'Fuel tank inspection record ' + toString(i)})
                CREATE (e)-[:FROM_CHUNK {repo_id: $repo, run_id: $run}]->(c)
                CREATE (e)-[:FROM_CHUNK {repo_id: $repo, run_id: $run}]->(c)
                """,
                repo=graph_repo, run=run_id, foreign=foreign_repo,
            )
            # Every way a foreign source can enter: wrong chunk corpus/run, wrong link
            # corpus/run, and a semantic neighbor with a source must all stay excluded.
            await session.run(
                """
                MATCH (e:__Entity__ {repo_id: $repo, entity_id: 'merged/tank::1'})
                WITH e
                UNWIND [
                    {chunk_repo: $foreign, chunk_run: $run, link_repo: $repo, link_run: $run},
                    {chunk_repo: $repo, chunk_run: 'wrong-run', link_repo: $repo, link_run: $run},
                    {chunk_repo: $repo, chunk_run: $run, link_repo: $foreign, link_run: $run},
                    {chunk_repo: $repo, chunk_run: $run, link_repo: $repo, link_run: 'wrong-run'}
                ] AS spec
                CREATE (c:Chunk {repo_id: spec.chunk_repo, run_id: spec.chunk_run, chunk_id: randomUUID(),
                    file_path: 'foreign.md', start_line: 1, end_line: 2, text: 'Foreign tank evidence'})
                CREATE (e)-[:FROM_CHUNK {repo_id: spec.link_repo, run_id: spec.link_run}]->(c)
                """,
                repo=graph_repo, run=run_id, foreign=foreign_repo,
            )
            await session.run(
                """
                MATCH (e:__Entity__ {repo_id: $repo, entity_id: 'merged/tank::1'})
                CREATE (n:__Entity__ {repo_id: $repo, run_id: $run, entity_id: 'neighbor', name: 'Valve', entity_type: 'Valve'})
                CREATE (c:Chunk {repo_id: $repo, run_id: $run, chunk_id: 'neighbor-mention',
                    file_path: 'neighbor.md', start_line: 1, end_line: 2, text: 'Valve inspection'})
                CREATE (e)-[:CONTAINS {repo_id: $repo, run_id: $run}]->(n)
                CREATE (n)-[:FROM_CHUNK {repo_id: $repo, run_id: $run}]->(c)
                """,
                repo=graph_repo, run=run_id,
            )

        endpoint = f"/api/graph/{corpus}/entity/sources"
        params: dict[str, str | int] = {"entity_id": "merged/tank::1", "limit": 2}
        first = await client.get(endpoint, params=params)
        assert first.status_code == 200, first.text
        first_page = first.json()
        assert first_page["run_id"] == run_id
        assert first_page["entity_id"] == "merged/tank::1"
        assert [s["chunk_id"] for s in first_page["sources"]] == ["mention-1", "mention-2"]
        assert first_page["sources"][0]["content"] == "Fuel tank inspection record 1"
        assert first_page["sources"][0]["start_line"] == 10
        assert first_page["sources"][0]["end_line"] == 12
        assert first_page["sources"][0]["provenance"]["extraction"] == "direct"
        assert first_page["sources"][0]["metadata"]["char_start"] == 20
        assert first_page["sources"][1]["metadata"] == {}
        assert first_page["sources"][1]["provenance"] is None
        assert first_page["next_offset"] == 2
        second = await client.get(endpoint, params={**params, "offset": 2, "run_id": run_id})
        assert second.status_code == 200, second.text
        assert [s["chunk_id"] for s in second.json()["sources"]] == ["mention-3"]
        assert second.json()["next_offset"] is None
        empty = await client.get(endpoint, params={**params, "offset": 3})
        assert empty.status_code == 200 and empty.json()["sources"] == []
        unlinked = await client.get(endpoint, params={"entity_id": "unlinked"})
        assert unlinked.status_code == 200 and unlinked.json()["sources"] == []
        for missing in ("absent", "foreign-only", "wrong-generation"):
            response = await client.get(endpoint, params={"entity_id": missing})
            assert response.status_code == 404, response.text
        for invalid in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
            response = await client.get(endpoint, params={**params, **invalid})
            assert response.status_code == 422, response.text
        mismatch = await client.get(endpoint, params={**params, "run_id": "older-run"})
        assert mismatch.status_code == 409, mismatch.text
        assert mismatch.json()["detail"]["code"] == "graph_generation_changed"
        # Promotion can reuse an existing graph resource under a newer manifest:
        # pagination follows the manifest, while Neo4j records retain the old run.
        newer_run = uuid4().hex
        await pg.set_generation(corpus, build_generation(run_id=newer_run, qdrant_collection=None, graph_repo_id=graph_repo))
        reused = await client.get(endpoint, params=params)
        assert reused.status_code == 200, reused.text
        assert reused.json()["run_id"] == newer_run
        assert [s["chunk_id"] for s in reused.json()["sources"]] == ["mention-1", "mention-2"]
        continuation = await client.get(endpoint, params={**params, "offset": 2, "run_id": newer_run})
        assert continuation.status_code == 200
        assert [s["chunk_id"] for s in continuation.json()["sources"]] == ["mention-3"]
        stale = await client.get(endpoint, params={**params, "offset": 2, "run_id": run_id})
        assert stale.status_code == 409
        relations = await client.get(f"/api/graph/{corpus}/entity/relationships", params={"entity_id": "merged/tank::1"})
        assert relations.status_code == 200
        assert len(relations.json()) == 1
        assert "chunk_id" not in relations.json()[0]["properties"]
    finally:
        for scope in (graph_repo, foreign_repo):
            await neo.delete_graph(scope)
        await neo.disconnect()
        await pg.disconnect()
        await client.delete(f"/api/corpora/{corpus}")
