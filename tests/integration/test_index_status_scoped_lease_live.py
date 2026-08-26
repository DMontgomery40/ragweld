"""Index status honours the corpus-scoped lease, from the durable fence, with no process state.

Replaces the monkeypatched `test_get_index_status_uses_corpus_scoped_config`:
the scoped config decides whether a fence is live (indexing) or stale (idle),
so the status route must resolve the CORPUS config, not the global one.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import ReclaimEntry, staging_repo_id
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


async def test_index_status_reads_the_fence_with_the_corpus_scoped_lease(
    client: AsyncClient,
) -> None:
    corpus_id = f"scoped-lease-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        cfg = load_config()
        # Global lease is 600s; this corpus says 30s (the floor).
        cfg.indexing.index_run_lease_seconds = 30
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        # A fence heartbeated 120s ago: live under the global lease, stale under the corpus lease.
        beat = datetime.now(UTC) - timedelta(seconds=120)
        claim = await pg.acquire_index_fence(
            corpus_id,
            "other-worker-run",
            started_at=beat,
            owner="other-worker:9",
            lease_seconds=30,
            heartbeat_at=beat,
        )
        assert claim.acquired
        status = await client.get(f"/api/index/{corpus_id}/status")
        assert status.status_code == 200, status.text
        assert status.json()["status"] != "indexing", status.json()  # stale under the CORPUS lease

        # A fresh fence held by another worker reads as indexing, with that run named.
        assert await pg.release_index_fence(corpus_id, "other-worker-run") is True
        claim = await pg.acquire_index_fence(
            corpus_id,
            "other-worker-run-2",
            started_at=datetime.now(UTC),
            owner="other-worker:9",
            lease_seconds=30,
        )
        assert claim.acquired
        status = await client.get(f"/api/index/{corpus_id}/status")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "indexing", status.json()
        assert "other-worker-run-2" in str(status.json()["current_file"])
        assert await pg.release_index_fence(corpus_id, "other-worker-run-2") is True
    finally:
        config_store._store = None
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()


def _neo4j_for(cfg, corpus_id: str) -> Neo4jClient:
    return Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.resolve_password(),
        database=cfg.graph_storage.resolve_database(corpus_id),
    )


async def _seed_graph_node(neo4j: Neo4jClient, graph_id: str) -> None:
    driver = neo4j._require_driver()
    async with driver.session(database=neo4j.database) as session:
        await session.run(
            "CREATE (:__Entity__ {repo_id: $repo_id, name: 'Salinity sensor', id: $id})",
            repo_id=graph_id,
            id=f"{graph_id}:salinity-sensor",
        )
    assert (await neo4j.get_graph_stats(graph_id)).total_entities == 1


@pytest.mark.requires_qdrant
@pytest.mark.requires_neo4j
async def test_deindex_repairs_a_corrupt_reclaim_backlog(client: AsyncClient) -> None:
    """A backlog with one VALID entry (real staged resources) and one malformed item.

    Every reader answers the typed 409 at runtime; the de-index absorbs the valid
    entry (its real Qdrant collection, Neo4j graph and staging rows go), removes
    the key whatever its shape, leaves no tombstone, and the next start succeeds.
    """
    corpus_id = f"backlog-repair-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    cfg = load_config()
    qdrant = QdrantChunkStore(cfg)
    neo4j: Neo4jClient | None = None
    staged_collection: str | None = None
    dead_run = "dead-run-1"
    staged_graph = staging_repo_id(corpus_id, dead_run)
    try:
        await pg.connect()
        neo4j = _neo4j_for(cfg, corpus_id)
        await neo4j.connect()
        staged_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=int(cfg.embedding.embedding_dim)
        )
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        # Real staged resources of the dead run: a Qdrant collection, a Neo4j graph, staging rows.
        driver = neo4j._require_driver()
        async with driver.session(database=neo4j.database) as session:
            await session.run(
                "CREATE (:__Entity__ {repo_id: $repo_id, name: 'Salinity sensor', id: $id})",
                repo_id=staged_graph,
                id=f"{staged_graph}:salinity-sensor",
            )
        assert (await neo4j.get_graph_stats(staged_graph)).total_entities == 1
        await pg.upsert_corpus(staged_graph, name=staged_graph, root_path=".")
        assert (
            await qdrant.status(corpus_id, physical=staged_collection)
        ).physical_collection == staged_collection
        valid_entry = ReclaimEntry(
            run_id=dead_run,
            staged_qdrant_collection=staged_collection,
            staged_graph_repo_id=staged_graph,
            recorded_at=datetime.now(UTC),
        ).model_dump(mode="json")
        await pg.update_corpus_meta(
            corpus_id, {"reclaim_backlog": [valid_entry, {"not": "an entry"}]}
        )
        config_store._store = None
        # Runtime: every reader of this corpus answers the typed 409 (not just POST).
        # (No run summary exists yet: latest-run must answer the 409, never a 404.)
        for call in (
            client.post(
                "/api/index", json={"corpus_id": corpus_id, "repo_path": ".", "force_reindex": True}
            ),
            client.get(f"/api/index/{corpus_id}/status"),
            client.get(f"/api/index/{corpus_id}/stats"),
            client.get(f"/api/index/{corpus_id}/runs/latest"),
            client.get("/api/index/status", params={"corpus_id": corpus_id}),
            client.get("/api/index/stats", params={"corpus_id": corpus_id}),
        ):
            refused = await call
            assert refused.status_code == 409, (refused.request.url, refused.text)
            assert refused.json()["detail"]["code"] == "persisted_state_corrupt", refused.text
            assert refused.json()["detail"]["key"] == "reclaim_backlog"
        assert await pg.get_index_fence(corpus_id) is None, (
            "no fence is written for a corrupt corpus"
        )
        repaired = await client.delete(f"/api/index/{corpus_id}")
        assert repaired.status_code == 200, repaired.text
        row = await pg.get_corpus(corpus_id)
        assert "reclaim_backlog" not in row["meta"], row["meta"]
        assert await pg.get_index_tombstone(corpus_id) is None
        # The valid entry's real resources are gone: collection, graph, staging row.
        assert (
            await qdrant.status(corpus_id, physical=staged_collection)
        ).physical_collection is None
        assert (await neo4j.get_graph_stats(staged_graph)).total_entities == 0
        assert await pg.get_corpus(staged_graph) is None
        started = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": ".", "force_reindex": True}
        )
        assert started.status_code == 200, started.text
        stopped = await client.post(f"/api/index/{corpus_id}/stop")
        assert stopped.status_code == 200, stopped.text
    finally:
        config_store._store = None
        await client.post(f"/api/index/{corpus_id}/stop")
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        if staged_collection is not None:
            with contextlib.suppress(Exception):
                await qdrant.drop_generation(staged_collection)
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.delete_graph(staged_graph)
            await neo4j.disconnect()
        with contextlib.suppress(Exception):
            await pg.delete_corpus_with_data(staged_graph)
        await pg.disconnect()


@pytest.mark.requires_qdrant
@pytest.mark.requires_neo4j
async def test_deindex_absorbs_a_dead_runs_fence_inventory_and_orphan_staging_rows(
    client: AsyncClient,
) -> None:
    """A crashed run that was never taken over leaves only its FENCE as the record of what it staged.

    De-index must drop exactly that inventory (real collection, real graph,
    staging rows) plus any orphan staging rows of this corpus, and must leave a
    sibling corpus's staging rows alone: ``a`` never sweeps ``a__b``.
    """
    corpus_id = f"fence-inventory-{uuid.uuid4().hex[:8]}"
    sibling_id = f"{corpus_id}__b"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    cfg = load_config()
    qdrant = QdrantChunkStore(cfg)
    neo4j: Neo4jClient | None = None
    staged_collection: str | None = None
    dead_run = "crashed-run-7"
    staged_graph = staging_repo_id(corpus_id, dead_run)
    ghost_rows = staging_repo_id(corpus_id, "ghost-run")  # no fence, no backlog names it
    sibling_rows = staging_repo_id(sibling_id, "sibling-run")
    try:
        await pg.connect()
        neo4j = _neo4j_for(cfg, corpus_id)
        await neo4j.connect()
        staged_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=int(cfg.embedding.embedding_dim)
        )
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        await _seed_graph_node(neo4j, staged_graph)
        for staged in (staged_graph, ghost_rows, sibling_rows):
            await pg.upsert_corpus(staged, name=staged, root_path=".")
        lease = cfg.indexing.index_run_lease_seconds
        stale_beat = datetime.now(UTC) - timedelta(seconds=lease + 5)
        assert (
            await pg.acquire_index_fence(
                corpus_id,
                dead_run,
                started_at=stale_beat,
                owner="dead-worker:7",
                lease_seconds=lease,
                heartbeat_at=stale_beat,
            )
        ).acquired
        assert await pg.record_fence_staging(
            corpus_id, dead_run, qdrant_collection=staged_collection, graph_repo_id=staged_graph
        )
        config_store._store = None

        repaired = await client.delete(f"/api/index/{corpus_id}")
        assert repaired.status_code == 200, repaired.text
        row = await pg.get_corpus(corpus_id)
        assert row is not None
        assert not ({"index_run", "reclaim_backlog", "index_tombstone"} & set(row["meta"])), row[
            "meta"
        ]
        # The dead run's exact inventory is gone ...
        assert (
            await qdrant.status(corpus_id, physical=staged_collection)
        ).physical_collection is None
        assert (await neo4j.get_graph_stats(staged_graph)).total_entities == 0
        assert await pg.get_corpus(staged_graph) is None
        # ... so are orphan staging rows nothing recorded ...
        assert await pg.get_corpus(ghost_rows) is None
        # ... and the sibling corpus's staging rows are untouched.
        assert await pg.get_corpus(sibling_rows) is not None
        started = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": ".", "force_reindex": True}
        )
        assert started.status_code == 200, started.text
    finally:
        config_store._store = None
        await client.post(f"/api/index/{corpus_id}/stop")
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        if staged_collection is not None:
            with contextlib.suppress(Exception):
                await qdrant.drop_generation(staged_collection)
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.delete_graph(staged_graph)
            await neo4j.disconnect()
        for staged in (staged_graph, ghost_rows, sibling_rows):
            with contextlib.suppress(Exception):
                await pg.delete_corpus_with_data(staged)
        await pg.disconnect()
