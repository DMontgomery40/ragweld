"""Index status honours the corpus-scoped lease, from the durable fence, with no process state.

Replaces the monkeypatched `test_get_index_status_uses_corpus_scoped_config`:
the scoped config decides whether a fence is live (indexing) or stale (idle),
so the status route must resolve the CORPUS config, not the global one.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from server.config import load_config
from server.db.postgres import PostgresClient
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


async def test_deindex_repairs_a_corrupt_reclaim_backlog(client: AsyncClient) -> None:
    """A malformed reclaim backlog answers the typed 409 on start; DELETE repairs it; start succeeds."""
    corpus_id = f"backlog-repair-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        await pg.update_corpus_meta(corpus_id, {"reclaim_backlog": {"not": "a list"}})
        config_store._store = None
        refused = await client.post(
            "/api/index", json={"corpus_id": corpus_id, "repo_path": ".", "force_reindex": True}
        )
        assert refused.status_code == 409, refused.text
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
        await pg.disconnect()
