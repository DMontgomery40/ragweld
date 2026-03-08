from __future__ import annotations

import pytest

from server.db.postgres import PostgresClient, _POOL_LOCKS_BY_DSN, _POOLS_BY_DSN


@pytest.mark.asyncio
async def test_failed_connect_does_not_leak_pool_lock_entries() -> None:
    await PostgresClient.close_shared_pools()
    _POOLS_BY_DSN.clear()
    _POOL_LOCKS_BY_DSN.clear()

    dsns = [f"postgresql://postgres:postgres@127.0.0.1:1/lock_leak_{i}" for i in range(3)]
    for dsn in dsns:
        client = PostgresClient(dsn)
        with pytest.raises(Exception):
            await client.connect()

    assert _POOLS_BY_DSN == {}
    assert _POOL_LOCKS_BY_DSN == {}
