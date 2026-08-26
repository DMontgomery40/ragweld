"""The fence heartbeat survives a blocked API event loop (codex pass 8 #1).

The heartbeat runs in its own thread with a dedicated connection; blocking the
loop that started it must not stop the database-stamped heartbeat from
advancing, or another worker would take over a live run.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from server.api.index import _FenceHeartbeat
from server.db.postgres import PostgresClient
from server.services import config_store

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


async def test_heartbeat_advances_while_the_event_loop_is_blocked(client: AsyncClient) -> None:
    corpus_id = f"heartbeat-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    heartbeat: _FenceHeartbeat | None = None
    try:
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        cfg = await config_store.get_config(repo_id=corpus_id)
        cfg.indexing.index_run_lease_seconds = 30  # floor: one beat every 3 s
        claim = await pg.acquire_index_fence(
            corpus_id,
            "heartbeat-run",
            started_at=datetime.now(UTC),
            owner="this-test:1",
            lease_seconds=30,
        )
        assert claim.acquired
        before = (await pg.get_index_fence(corpus_id)).heartbeat_at

        heartbeat = _FenceHeartbeat(cfg, corpus_id, "heartbeat-run")
        heartbeat.start()
        # Block THIS event loop (the one the API and every asyncio task share)
        # for longer than the beat interval: only a loop-independent heartbeat
        # keeps the fence fresh.
        time.sleep(7.5)
        after = (await pg.get_index_fence(corpus_id)).heartbeat_at
        assert after > before, (before, after)
        assert not heartbeat.fence_lost.is_set()
        assert await pg.release_index_fence(corpus_id, "heartbeat-run") is True
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        config_store._store = None
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()
