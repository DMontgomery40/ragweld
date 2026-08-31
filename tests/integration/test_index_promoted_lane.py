"""End-to-end: index a corpus through the API onto the promoted Postgres + Qdrant + Neo4j lane.

Runs only against live services (strict lane provisions disposable ones). No mocks.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import AsyncClient

import server.api.index as index_api
from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import (
    DeletionTombstone,
    RetiredGeneration,
    build_generation,
    reclaim_stale_run,
    staging_repo_id,
)
from server.retrieval.contracts import sparse_contract_from_config
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.mcp_probe_subprocess import call_mcp_probe
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]

_CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "acceptance_corpus"


def _metric_value(metrics_text: str, name: str) -> float:
    """Return the value of an unlabeled Prometheus series (0.0 when absent)."""
    for line in metrics_text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split(" ", 1)[1].strip())
    return 0.0


async def _wait_for_index(client: AsyncClient, corpus_id: str, *, timeout_s: float = 240.0) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        res = await client.get(f"/api/index/{corpus_id}/status")
        assert res.status_code == 200, res.text
        last = res.json()
        if last.get("status") in {"complete", "error", "cancelled"}:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"index did not finish in time: {last}")


async def _wait_fence_released(
    pg: PostgresClient, corpus_id: str, *, timeout_s: float = 10.0
) -> None:
    """The job releases its fence in `finally`, after it published `complete`: poll briefly."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await pg.get_index_fence(corpus_id) is None:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"fence on {corpus_id} was not released: {await pg.get_index_fence(corpus_id)}"
    )


async def test_index_search_and_delete_on_promoted_lane(client: AsyncClient) -> None:
    corpus_id = f"promoted-lane-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    qdrant = QdrantChunkStore(load_config())
    try:
        await pg.connect()
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
        )
        assert created.status_code in (200, 201), created.text

        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        # Retire the replaced generation at the very next commit (the retention
        # grace is proven separately below with a long grace).
        cfg.indexing.generation_retention_seconds = 0
        cfg.vector_search.enabled = True
        cfg.sparse_search.enabled = True
        cfg.graph_search.enabled = True
        cfg.graph_search.mode = "chunk"
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_lexical_graph = True
        cfg.graph_indexing.store_chunk_embeddings = True
        cfg.graph_indexing.semantic_kg_enabled = False
        cfg.chat.litellm.enabled = False
        cfg.semantic_cache.enabled = False
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None

        metrics_before = await client.get("/metrics")
        assert metrics_before.status_code == 200
        runs_before = _metric_value(metrics_before.text, "tribrid_index_runs_total")
        duration_count_before = _metric_value(
            metrics_before.text, "tribrid_index_duration_seconds_count"
        )

        started = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True},
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final
        await _wait_fence_released(pg, corpus_id)

        # The fence is durable, not process-local: a fence written by ANOTHER worker
        # (nothing in this process's task map) refuses both a new run and a
        # de-index with the same typed 409 ...
        foreign_started = datetime.now(UTC)
        assert (
            await pg.acquire_index_fence(
                corpus_id,
                "foreign-run-1",
                started_at=foreign_started,
                owner="other-worker:1",
                lease_seconds=cfg.indexing.index_run_lease_seconds,
            )
        ).acquired
        refused = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": True},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"]["run_id"] == "foreign-run-1"
        assert refused.json()["detail"]["owner"] == "other-worker:1"
        refused_delete = await client.delete(f"/api/index/{corpus_id}")
        assert refused_delete.status_code == 409, refused_delete.text
        assert refused_delete.json()["detail"]["run_id"] == "foreign-run-1"
        # ... stopping it from here is refused too (it belongs to the other worker) ...
        refused_stop = await client.post(f"/api/index/{corpus_id}/stop")
        assert refused_stop.status_code == 409, refused_stop.text
        # ... and the fence stays exactly as written (nothing here touched it).
        assert await pg.release_index_fence(corpus_id, "foreign-run-1") is True
        assert await pg.get_index_fence(corpus_id) is None
        # A crashed worker's fence (heartbeat older than the lease) is taken over by
        # a new run instead of bricking the corpus, and the new run completes.
        stale_beat = datetime.now(UTC) - timedelta(seconds=cfg.indexing.index_run_lease_seconds + 5)
        assert (
            await pg.acquire_index_fence(
                corpus_id,
                "crashed-run",
                started_at=stale_beat,
                owner="dead-worker:2",
                lease_seconds=cfg.indexing.index_run_lease_seconds,
                heartbeat_at=stale_beat,
            )
        ).acquired
        takeover = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert takeover.status_code == 200, takeover.text
        taken = await pg.get_index_fence(corpus_id)
        assert taken is None or taken.run_id != "crashed-run", taken
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        await _wait_fence_released(pg, corpus_id)
        # Concurrent claims on one corpus: exactly one wins the durable CAS, the
        # others are told who holds it (the database row is the only authority).
        claims = await asyncio.gather(
            *(
                pg.acquire_index_fence(
                    corpus_id,
                    f"racer-{i}",
                    started_at=datetime.now(UTC),
                    owner=f"racer-worker:{i}",
                    lease_seconds=cfg.indexing.index_run_lease_seconds,
                )
                for i in range(6)
            )
        )
        winners = [c for c in claims if c.acquired]
        assert len(winners) == 1, claims
        assert all(
            c.held_by is not None and c.held_by.run_id.startswith("racer-")
            for c in claims
            if not c.acquired
        )
        holder = await pg.get_index_fence(corpus_id)
        assert holder is not None and holder.run_id.startswith("racer-")
        # Heartbeats move the database-stamped heartbeat forward for the holder only.
        before_beat = holder.heartbeat_at
        await asyncio.sleep(0.05)
        assert await pg.heartbeat_index_fence(corpus_id, holder.run_id) is True
        assert await pg.heartbeat_index_fence(corpus_id, "racer-nobody") is False
        assert (await pg.get_index_fence(corpus_id)).heartbeat_at > before_beat, (
            "a no-op heartbeat would not advance"
        )
        assert await pg.release_index_fence(corpus_id, holder.run_id) is True
        # A stale fence with no run behind it is released by the stop route.
        assert (
            await pg.acquire_index_fence(
                corpus_id,
                "crashed-run-2",
                started_at=stale_beat,
                owner="dead-worker:3",
                lease_seconds=cfg.indexing.index_run_lease_seconds,
                heartbeat_at=stale_beat,
            )
        ).acquired
        stopped = await client.post(f"/api/index/{corpus_id}/stop")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "cancelled" and "crashed-run-2" in str(
            stopped.json()["error"]
        )
        assert await pg.get_index_fence(corpus_id) is None

        # Postgres holds the chunk rows + contracts; Qdrant holds a promoted generation with one point per chunk.
        corpus = await pg.get_corpus(corpus_id)
        assert corpus is not None
        assert corpus["embedding_dimensions"] == int(cfg.embedding.embedding_dim)
        assert corpus["sparse_contract"] == sparse_contract_from_config(cfg)
        chunk_rows = await pg.count_chunks(corpus_id)
        assert chunk_rows > 0
        generation = await pg.get_generation(corpus_id)
        assert generation and generation.qdrant_collection and generation.graph_repo_id, generation
        status = await qdrant.status(corpus_id, physical=generation.qdrant_collection)
        assert status is not None, "promoted Qdrant generation missing"
        assert status.points == chunk_rows
        assert status.dense_points == chunk_rows
        assert status.dense_dimensions == int(cfg.embedding.embedding_dim)
        # Two real index runs so far (the first build and the takeover of the stale
        # fence) increment the index metrics; the chunk gauge is the promoted count.
        metrics_after = await client.get("/metrics")
        assert metrics_after.status_code == 200
        assert _metric_value(metrics_after.text, "tribrid_index_runs_total") == pytest.approx(
            runs_before + 2.0
        )
        assert _metric_value(
            metrics_after.text, "tribrid_index_duration_seconds_count"
        ) == pytest.approx(duration_count_before + 2.0)
        assert _metric_value(metrics_after.text, "tribrid_chunks_indexed_current") == pytest.approx(
            float(chunk_rows)
        )
        stored_chunks = await pg.list_chunks_for_repo(corpus_id, limit=5)
        assert stored_chunks and all(
            ch.provenance is not None and ch.provenance.extraction == "direct"
            for ch in stored_chunks
        )
        assert all(ch.embedding is None for ch in stored_chunks)

        # All three legs return results for a grounded query.
        body = {
            "query": "How often is the salinity sensor calibrated?",
            "corpus_id": corpus_id,
            "top_k": 8,
            "include_vector": True,
            "include_sparse": True,
            "include_graph": True,
            "cache_mode": "bypass",
        }
        search = await client.post("/api/search", json=body)
        assert search.status_code == 200, search.text
        payload = search.json()
        matches = payload["matches"]
        assert matches, payload
        debug = payload["debug"]
        assert int(debug["fusion_vector_results"]) > 0
        assert int(debug["fusion_sparse_results"]) > 0
        assert int(debug["fusion_graph_hydrated_chunks"]) > 0
        per_corpus = debug["fusion_per_corpus"][corpus_id]
        assert per_corpus["fusion_sparse_engine"] == "qdrant_sparse_idf"
        assert any("calibrat" in m["content"].lower() for m in matches)
        assert all(m["metadata"].get("corpus_id") == corpus_id for m in matches)

        # Sparse-only and vector-only requests both succeed on the same generation.
        for legs in (
            {"include_vector": False, "include_graph": False},
            {"include_sparse": False, "include_graph": False},
        ):
            res = await client.post("/api/search", json={**body, **legs})
            assert res.status_code == 200, res.text
            assert res.json()["matches"], legs

        # A NON-forced re-index of an already indexed corpus must rebuild through
        # staging and promote (2026-08-25 drive finding M5: it returned cached
        # stats without writing the staging corpus and the promotion failed with
        # "Staging corpus not found", leaving a permanent error run).
        reindex = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert reindex.status_code == 200, reindex.text
        final_reindex = await _wait_for_index(client, corpus_id)
        assert final_reindex["status"] == "complete", final_reindex
        assert final_reindex.get("error") in (None, ""), final_reindex
        assert await pg.count_chunks(corpus_id) == chunk_rows
        regeneration = await pg.get_generation(corpus_id)
        assert regeneration and regeneration.run_id != generation.run_id, regeneration
        restatus = await qdrant.status(corpus_id, physical=regeneration.qdrant_collection)
        assert restatus is not None and restatus.points == chunk_rows
        # generation_retention_seconds = 0: the replaced generation was retired at
        # this commit, by exact id, and pruned from the manifest.
        assert regeneration.retired == [], regeneration
        gone = await qdrant.status(corpus_id, physical=generation.qdrant_collection)
        assert gone is not None and gone.physical_collection is None, gone
        assert (await qdrant.count_points(regeneration.qdrant_collection)) == chunk_rows
        # With a long grace the replaced generation stays readable (an in-flight
        # reader that resolved the old manifest keeps working) and the manifest
        # records it as retired with the exact ids to drop later.
        scoped = await config_store.get_config(repo_id=corpus_id)
        scoped.indexing.generation_retention_seconds = 3600
        await pg.upsert_corpus_config_json(corpus_id, scoped.model_dump(mode="serialization"))
        config_store._store = None
        third = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert third.status_code == 200, third.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        third_generation = await pg.get_generation(corpus_id)
        assert third_generation and third_generation.run_id != regeneration.run_id
        assert [r.qdrant_collection for r in third_generation.retired] == [
            regeneration.qdrant_collection
        ], third_generation
        assert [r.graph_repo_id for r in third_generation.retired] == [regeneration.graph_repo_id]
        kept = await qdrant.status(corpus_id, physical=regeneration.qdrant_collection)
        assert kept is not None and kept.physical_collection == regeneration.qdrant_collection
        assert kept.points == chunk_rows
        assert (await qdrant.count_points(third_generation.qdrant_collection)) == chunk_rows
        # A second retained commit: the chain now holds TWO retired generations
        # (single-previous retention would have dropped the older one).
        fourth = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert fourth.status_code == 200, fourth.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        fourth_generation = await pg.get_generation(corpus_id)
        assert fourth_generation and [r.qdrant_collection for r in fourth_generation.retired] == [
            regeneration.qdrant_collection,
            third_generation.qdrant_collection,
        ], fourth_generation
        for collection in (regeneration.qdrant_collection, third_generation.qdrant_collection):
            still = await qdrant.status(corpus_id, physical=collection)
            assert still is not None and still.physical_collection == collection, collection
        # Grace back to 0: the next commit retires both by exact id and prunes them.
        scoped = await config_store.get_config(repo_id=corpus_id)
        scoped.indexing.generation_retention_seconds = 0
        await pg.upsert_corpus_config_json(corpus_id, scoped.model_dump(mode="serialization"))
        config_store._store = None
        fifth = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert fifth.status_code == 200, fifth.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        fifth_generation = await pg.get_generation(corpus_id)
        assert fifth_generation and fifth_generation.retired == [], fifth_generation
        for collection in (
            regeneration.qdrant_collection,
            third_generation.qdrant_collection,
            fourth_generation.qdrant_collection,
        ):
            gone = await qdrant.status(corpus_id, physical=collection)
            assert gone is not None and gone.physical_collection is None, collection
        assert (await qdrant.count_points(fifth_generation.qdrant_collection)) == chunk_rows
        # Widen the post-commit window: several due (grace 0) retired collections
        # give the sixth run real retirement work after its commit.
        window_collections = [
            await qdrant.create_generation(
                corpus_id, embedding_dim=int(cfg.embedding.embedding_dim)
            )
            for _ in range(8)
        ]
        await pg.set_generation(
            corpus_id,
            fifth_generation.model_copy(
                update={
                    "retired": [
                        RetiredGeneration(
                            run_id=f"window-{i}",
                            qdrant_collection=collection,
                            graph_repo_id=None,
                            retired_at=datetime.now(UTC) - timedelta(seconds=60),
                        )
                        for i, collection in enumerate(window_collections)
                    ]
                }
            ),
        )
        sixth = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert sixth.status_code == 200, sixth.text
        # Cancellation at/after the commit boundary: stop the run the moment its
        # manifest is live; the run must end complete (persisted summary too),
        # never cancelled, and the generation must stay live.
        deadline = asyncio.get_running_loop().time() + 120
        committed_generation = None
        while asyncio.get_running_loop().time() < deadline:
            current = await pg.get_generation(corpus_id)
            if current is not None and current.run_id != fifth_generation.run_id:
                committed_generation = current
                break
            await asyncio.sleep(0.02)
        assert committed_generation is not None, "the sixth run never committed"
        # The stop must hit a LIVE run in its post-commit phase: the durable fence
        # says "retiring" (written after the commit, before retirement starts) and
        # this process still owns the task. The eight due collections above give
        # that phase real work, so the stop lands inside it.
        phase_deadline = asyncio.get_running_loop().time() + 30
        fence_now = await pg.get_index_fence(corpus_id)
        while asyncio.get_running_loop().time() < phase_deadline and (
            fence_now is None or fence_now.phase != "retiring"
        ):
            await asyncio.sleep(0.01)
            fence_now = await pg.get_index_fence(corpus_id)
        assert fence_now is not None and fence_now.phase == "retiring", fence_now
        assert corpus_id in index_api._TASKS and not index_api._TASKS[corpus_id].done(), (
            "the sixth run finished its retirement before the stop could land"
        )
        stopped_after_commit = await client.post(f"/api/index/{corpus_id}/stop")
        assert stopped_after_commit.status_code == 200, stopped_after_commit.text
        assert stopped_after_commit.json()["status"] == "complete", stopped_after_commit.json()
        latest_after_stop = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert (
            latest_after_stop.status_code == 200
            and latest_after_stop.json()["status"] == "complete"
        )
        assert latest_after_stop.json()["run_id"] == committed_generation.run_id
        # The cancellation reached the committed-run handler of THAT run (not the
        # no-local-task path): the handler recorded it.
        assert index_api._CANCELLED_AFTER_COMMIT.get(corpus_id) == committed_generation.run_id
        assert (await pg.get_generation(corpus_id)).run_id == committed_generation.run_id
        assert (await qdrant.count_points(committed_generation.qdrant_collection)) == chunk_rows
        await _wait_fence_released(pg, corpus_id)
        # Mixed expiry, seeded on the manifest itself: one retired entry is long past
        # the grace (due), one is fresh (kept), and both are real collections. The
        # next commit drops exactly the due one, keeps the fresh one, and adds the
        # generation it replaced.
        scoped.indexing.generation_retention_seconds = 3600
        await pg.upsert_corpus_config_json(corpus_id, scoped.model_dump(mode="serialization"))
        config_store._store = None
        due_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=int(cfg.embedding.embedding_dim)
        )
        fresh_collection = await qdrant.create_generation(
            corpus_id, embedding_dim=int(cfg.embedding.embedding_dim)
        )
        # Real Neo4j graphs under the seeded ids: the due entry's own graph must be
        # physically deleted, the shared one must physically survive.
        due_graph = f"seed-due-graph-{uuid.uuid4().hex[:6]}"
        shared_graph = f"seed-shared-graph-{uuid.uuid4().hex[:6]}"
        seed_neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=cfg.graph_storage.resolve_database(corpus_id),
        )
        await seed_neo4j.connect()
        try:
            driver = seed_neo4j._require_driver()
            async with driver.session(database=seed_neo4j.database) as session:
                for gid in (due_graph, shared_graph):
                    await session.run(
                        "CREATE (:__Entity__ {repo_id: $repo_id, name: $name, id: $id})",
                        repo_id=gid,
                        name=f"Salinity sensor ({gid})",
                        id=f"{gid}:salinity-sensor",
                    )
            assert (await seed_neo4j.get_graph_stats(due_graph)).total_entities == 1
            assert (await seed_neo4j.get_graph_stats(shared_graph)).total_entities == 1
        finally:
            await seed_neo4j.disconnect()
        seeded = committed_generation.model_copy(
            update={
                "retired": [
                    # Both entries name the SAME graph: only the due entry's own
                    # collection may go; the shared graph must survive because the
                    # fresh entry still holds it.
                    RetiredGeneration(
                        run_id="seed-due",
                        qdrant_collection=due_collection,
                        graph_repo_id=shared_graph,
                        retired_at=datetime.now(UTC) - timedelta(seconds=7200),
                    ),
                    RetiredGeneration(
                        run_id="seed-due-own-graph",
                        qdrant_collection=None,
                        graph_repo_id=due_graph,
                        retired_at=datetime.now(UTC) - timedelta(seconds=7200),
                    ),
                    RetiredGeneration(
                        run_id="seed-fresh",
                        qdrant_collection=fresh_collection,
                        graph_repo_id=shared_graph,
                        retired_at=datetime.now(UTC),
                    ),
                ]
            }
        )
        await pg.set_generation(corpus_id, seeded)
        seventh = await client.post(
            "/api/index",
            json={"corpus_id": corpus_id, "repo_path": str(_CORPUS_PATH), "force_reindex": False},
        )
        assert seventh.status_code == 200, seventh.text
        assert (await _wait_for_index(client, corpus_id))["status"] == "complete"
        await _wait_fence_released(pg, corpus_id)
        after_mixed = await pg.get_generation(corpus_id)
        assert after_mixed is not None
        retired_now = {r.qdrant_collection for r in after_mixed.retired}
        assert due_collection not in retired_now, (
            after_mixed
        )  # its grace had elapsed: dropped and pruned
        assert (await qdrant.status(corpus_id, physical=due_collection)).physical_collection is None
        assert fresh_collection in retired_now, after_mixed  # still inside its grace: kept
        # The shared graph survived on the fresh entry (entry-wise retirement would have
        # dropped it with the due entry); the due entry is gone entirely.
        by_run = {r.run_id: r for r in after_mixed.retired}
        assert by_run["seed-fresh"].graph_repo_id == shared_graph, after_mixed
        # The due entry lost its own collection but still names the shared graph
        # (dropping it entry-wise would have deleted a graph the fresh entry holds);
        # it goes with the graph once nothing alive names it.
        assert "seed-due" in by_run and by_run["seed-due"].qdrant_collection is None, after_mixed
        assert by_run["seed-due"].graph_repo_id == shared_graph, after_mixed
        assert "seed-due-own-graph" not in by_run, after_mixed  # its only resource was dropped
        # Physically: the due entry's own graph is gone, the shared graph survived.
        check_neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=cfg.graph_storage.resolve_database(corpus_id),
        )
        await check_neo4j.connect()
        try:
            assert (await check_neo4j.get_graph_stats(due_graph)).total_entities == 0
            assert (await check_neo4j.get_graph_stats(shared_graph)).total_entities == 1
            await check_neo4j.delete_graph(shared_graph)
        finally:
            await check_neo4j.disconnect()
        assert (
            await qdrant.status(corpus_id, physical=fresh_collection)
        ).physical_collection == fresh_collection
        # The generation the seventh run replaced (the sixth) joins the retired list.
        assert committed_generation.qdrant_collection in retired_now, [
            (r.run_id, r.qdrant_collection, r.retired_at.isoformat()) for r in after_mixed.retired
        ]
        regeneration = after_mixed
        latest_run = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert latest_run.status_code == 200, latest_run.text
        assert latest_run.json()["status"] == "complete", latest_run.json()
        assert latest_run.json().get("error") in (None, ""), latest_run.json()
        after_reindex = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert after_reindex.status_code == 200 and after_reindex.json()["matches"], (
            after_reindex.text
        )

        # A run that fails before promotion must leave the active index and its
        # process-level stats exactly as they were (stats are published only
        # after the Postgres/Qdrant/Neo4j cutover completes).
        stats_before = (
            await client.get("/api/index/stats", params={"corpus_id": corpus_id})
        ).json()
        # A path the API cannot read is refused up front (it used to "complete" with 0 files).
        missing = await client.post(
            "/api/index",
            json={
                "corpus_id": corpus_id,
                "repo_path": str(_CORPUS_PATH / "does-not-exist"),
                "force_reindex": False,
            },
        )
        assert missing.status_code == 400, missing.text
        # A readable but empty directory starts a run that fails instead of promoting an empty index.
        empty_dir = tempfile.mkdtemp(prefix="ragweld-empty-corpus-")
        try:
            bogus = await client.post(
                "/api/index",
                json={"corpus_id": corpus_id, "repo_path": empty_dir, "force_reindex": False},
            )
            assert bogus.status_code == 200, bogus.text
            failed = await _wait_for_index(client, corpus_id)
        finally:
            os.rmdir(empty_dir)
        assert failed["status"] == "error", failed
        assert "No indexable files" in str(failed.get("error") or ""), failed
        stats_after = (await client.get("/api/index/stats", params={"corpus_id": corpus_id})).json()
        assert stats_after == stats_before, "a failed run must not touch the active index stats"
        assert await pg.count_chunks(corpus_id) == chunk_rows
        still = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert still.status_code == 200 and still.json()["matches"], still.text

        # The MCP probe goes through the mounted Streamable HTTP transport and the
        # registered `search` tool, not an HTTP shortcut. Each helper call owns one
        # child-process lifespan because the SDK session manager is one-shot.
        probe_status, probe_payload = await call_mcp_probe(
            corpus_id,
            None,
            question="How often is the salinity sensor calibrated?",
            top_k=5,
        )
        assert probe_status == 200, probe_payload
        assert probe_payload["tool"] == "search" and probe_payload["transport_url"].endswith(
            "/mcp/"
        )
        assert probe_payload["mode"] == cfg.mcp.default_mode and probe_payload["top_k"] == 5
        assert probe_payload["results"] and any(
            "calibrat" in row["content"].lower() for row in probe_payload["results"]
        )
        sparse_status, sparse_payload = await call_mcp_probe(
            corpus_id,
            "sparse_only",
            question="How often is the salinity sensor calibrated?",
            top_k=3,
        )
        assert sparse_status == 200, sparse_payload
        assert sparse_payload["mode"] == "sparse_only" and len(sparse_payload["results"]) <= 3
        assert all(row["source"] == "sparse" for row in sparse_payload["results"])

        # Retrieval request/latency metrics are measured on the shared fusion lane,
        # so chat retrieval counts exactly like /api/search (finding M9: chat never
        # incremented them and the on-call p95 rendered NaN).
        m0 = await client.get("/metrics")
        reqs0 = _metric_value(m0.text, "tribrid_search_requests_total")
        lat0 = _metric_value(m0.text, "tribrid_search_latency_seconds_count")
        counted_search = await client.post("/api/search", json={**body, "cache_mode": "bypass"})
        assert counted_search.status_code == 200, counted_search.text
        chat = await client.post(
            "/api/chat",
            json={
                "message": "How often is the salinity sensor calibrated?",
                "corpus_id": corpus_id,
                "sources": {"corpus_ids": [corpus_id]},
                "stream": False,
                "cache_mode": "bypass",
            },
        )
        # LiteLLM is disabled in this corpus config, so generation fails closed with
        # the typed 503 -- after retrieval ran on the fusion lane.
        assert chat.status_code == 503, chat.text
        assert chat.json()["detail"]["code"] == "generation_unavailable", chat.text
        m1 = await client.get("/metrics")
        assert _metric_value(m1.text, "tribrid_search_requests_total") == pytest.approx(reqs0 + 2.0)
        assert _metric_value(m1.text, "tribrid_search_latency_seconds_count") == pytest.approx(
            lat0 + 2.0
        )

        stats = await client.get("/api/index/stats", params={"corpus_id": corpus_id})
        assert stats.status_code == 200, stats.text
        storage = stats.json()["storage_breakdown"]
        assert int(storage["qdrant_points"]) == chunk_rows
        assert (
            int(storage["qdrant_dense_vector_bytes"])
            == chunk_rows * int(cfg.embedding.embedding_dim) * 4
        )
        # Dashboard storage truth on the real stores (replaces the former fake-Postgres test).
        assert int(storage["chunks_bytes"]) > 0
        assert int(storage["postgres_total_bytes"]) >= int(storage["chunks_bytes"])
        assert int(storage["total_storage_bytes"]) == (
            int(storage["postgres_total_bytes"])
            + int(storage["qdrant_dense_vector_bytes"])
            + int(storage["neo4j_store_bytes"])
        )
        dashboard_status = await client.get("/api/index/status", params={"corpus_id": corpus_id})
        assert dashboard_status.status_code == 200, dashboard_status.text
        dashboard = dashboard_status.json()
        assert dashboard["running"] is False
        assert dashboard["metadata"]["corpus_id"] == corpus_id
        assert dashboard["metadata"]["current_repo"] == corpus_id
        assert int(dashboard["metadata"]["total_storage"]) == int(storage["total_storage_bytes"])

        # Deleting the index drops the live AND the retained generation (the exact ids
        # the tombstone recorded), clears the tombstone, and the legs then fail
        # closed (chunk rows are gone too).
        retained_collections = [
            r.qdrant_collection for r in regeneration.retired if r.qdrant_collection
        ]
        assert retained_collections
        retained_collection = retained_collections[0]
        # A de-index tombstone on the row (an earlier deletion whose external cleanup
        # did not finish) closes every reader and writer with the typed 503 until the
        # deletion is retried; its targets are merged into that retry.
        stale_tombstone = DeletionTombstone(
            qdrant_collections=[f"{regeneration.qdrant_collection}__never_created"],
            graph_repo_ids=[],
            created_at=datetime.now(UTC) - timedelta(seconds=60),
            revision=uuid.uuid4().hex,
        )
        await pg.update_corpus_meta(
            corpus_id, {"index_tombstone": stale_tombstone.model_dump(mode="json")}
        )
        config_store._store = None
        for call in (
            client.post("/api/search", json={**body, "cache_mode": "bypass"}),
            client.post(
                "/api/index",
                json={
                    "corpus_id": corpus_id,
                    "repo_path": str(_CORPUS_PATH),
                    "force_reindex": True,
                },
            ),
            client.get(f"/api/index/{corpus_id}/status"),
            client.get(f"/api/index/{corpus_id}/stats"),
            client.get(f"/api/graph/{corpus_id}/stats"),
        ):
            closed = await call
            assert closed.status_code == 503, closed.text
            assert closed.json()["detail"]["code"] == "index_deletion_incomplete", closed.text
            assert closed.json()["detail"]["corpus_id"] == corpus_id
        deleted = await client.delete(f"/api/index/{corpus_id}")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deleted_chunks"] == chunk_rows
        assert deleted.json()["deleted_vector_collections"] >= 1
        assert await pg.get_generation(corpus_id) is None
        assert await pg.get_index_tombstone(corpus_id) is None, (
            "cleanup succeeded: no tombstone left"
        )
        for collection in (regeneration.qdrant_collection, retained_collection):
            wiped = await qdrant.status(corpus_id, physical=collection)
            assert wiped is not None and wiped.physical_collection is None, collection
        cleared = await pg.get_corpus(corpus_id)
        assert (
            cleared is not None
            and cleared["last_indexed"] is None
            and cleared["embedding_dimensions"] == 0
        )
        # A de-indexed corpus reports empty legs, not a missing-generation failure.
        empty = await client.post("/api/search", json=body)
        assert empty.status_code == 200, empty.text
        assert empty.json()["matches"] == []

        removed = await client.delete(f"/api/corpora/{corpus_id}")
        assert removed.status_code == 200, removed.text
    finally:
        config_store._store = None
        try:
            await qdrant.delete_corpus(corpus_id)
        except Exception:
            pass
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()


async def test_only_the_manifest_run_id_proves_a_commit_and_reclaim_never_drops_manifest_resources(
    client: AsyncClient,
) -> None:
    """A dead run whose recorded staged collection is a RETAINED one is not "committed".

    Only ``manifest.run_id`` proves a commit. Stop and takeover both classify the
    dead run as uncommitted (cancelled, never complete) and hand its inventory
    to reclaim; reclaim drops the run's own staged graph but NEVER a collection
    the manifest names (live or retained), and clears the backlog entry.
    """
    corpus_id = f"retained-id-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    cfg = load_config()
    qdrant = QdrantChunkStore(cfg)
    neo4j: Neo4jClient | None = None
    retained: str | None = None
    live: str | None = None
    dead_run = "dead-run-3"
    staged_graph = staging_repo_id(corpus_id, dead_run)
    lease = cfg.indexing.index_run_lease_seconds
    try:
        await pg.connect()
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=cfg.graph_storage.resolve_database(corpus_id),
        )
        await neo4j.connect()
        created = await client.post(
            "/api/corpora",
            json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
        )
        assert created.status_code in (200, 201), created.text
        dim = int(cfg.embedding.embedding_dim)
        retained = await qdrant.create_generation(corpus_id, embedding_dim=dim)
        live = await qdrant.create_generation(corpus_id, embedding_dim=dim)
        manifest = build_generation(
            run_id="live-run",
            qdrant_collection=live,
            graph_repo_id=None,
            previous=build_generation(
                run_id="old-run",
                qdrant_collection=retained,
                graph_repo_id=None,
                now=datetime.now(UTC) - timedelta(seconds=30),
            ),
            now=datetime.now(UTC),
        )
        assert retained in manifest.all_qdrant_collections()
        await pg.set_generation(corpus_id, manifest)
        driver = neo4j._require_driver()
        async with driver.session(database=neo4j.database) as session:
            await session.run(
                "CREATE (:__Entity__ {repo_id: $repo_id, name: 'Tidal gauge', id: $id})",
                repo_id=staged_graph,
                id=f"{staged_graph}:tidal-gauge",
            )
        await pg.upsert_corpus(staged_graph, name=staged_graph, root_path=".")
        stale_beat = datetime.now(UTC) - timedelta(seconds=lease + 5)

        async def _seed_dead_fence() -> None:
            assert (
                await pg.acquire_index_fence(
                    corpus_id,
                    dead_run,
                    started_at=stale_beat,
                    owner="dead-worker:3",
                    lease_seconds=lease,
                    heartbeat_at=stale_beat,
                )
            ).acquired
            assert await pg.record_fence_staging(
                corpus_id, dead_run, qdrant_collection=retained, graph_repo_id=staged_graph
            )

        # 1) Stop: the dead run is reclaimed (cancelled), never finalized as complete.
        await _seed_dead_fence()
        config_store._store = None
        stopped = await client.post(f"/api/index/{corpus_id}/stop")
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "cancelled", stopped.json()
        assert dead_run in str(stopped.json()["error"])
        assert await pg.get_index_fence(corpus_id) is None
        assert await pg.reclaim_backlog(corpus_id) == [], "the reclaim confirmed and cleared itself"
        assert (await qdrant.status(corpus_id, physical=retained)).physical_collection == retained
        assert (await qdrant.status(corpus_id, physical=live)).physical_collection == live
        assert (await neo4j.get_graph_stats(staged_graph)).total_entities == 0
        assert await pg.get_corpus(staged_graph) is None
        after_stop = await pg.get_generation(corpus_id)
        assert after_stop is not None and after_stop.run_id == "live-run"
        assert retained in after_stop.all_qdrant_collections()

        # 2) Takeover: the claim classifies the same dead fence as uncommitted and
        #    moves its inventory to the backlog; the reclaim leaves the retained
        #    collection alone and confirms.
        await pg.upsert_corpus(staged_graph, name=staged_graph, root_path=".")
        await _seed_dead_fence()
        claim = await pg.acquire_index_fence(
            corpus_id,
            "new-run",
            started_at=datetime.now(UTC),
            owner="worker:new",
            lease_seconds=lease,
        )
        assert claim.acquired and claim.taken_over is not None
        assert claim.taken_over.run_id == dead_run
        assert claim.taken_over_committed is False, "a retained id is not ownership"
        backlog = await pg.reclaim_backlog(corpus_id)
        assert [e.run_id for e in backlog] == [dead_run]
        assert backlog[0].staged_qdrant_collection == retained
        assert await reclaim_stale_run(cfg, corpus_id, backlog[0]) is True
        assert await pg.reclaim_backlog(corpus_id) == []
        assert (await qdrant.status(corpus_id, physical=retained)).physical_collection == retained
        assert await pg.get_corpus(staged_graph) is None
        assert await pg.release_index_fence(corpus_id, "new-run") is True
    finally:
        config_store._store = None
        await client.post(f"/api/index/{corpus_id}/stop")
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        for collection in (retained, live):
            if collection is not None:
                with contextlib.suppress(Exception):
                    await qdrant.drop_generation(collection)
        if neo4j is not None:
            with contextlib.suppress(Exception):
                await neo4j.delete_graph(staged_graph)
            await neo4j.disconnect()
        with contextlib.suppress(Exception):
            await pg.delete_corpus_with_data(staged_graph)
        await pg.disconnect()
