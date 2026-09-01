from __future__ import annotations

import os

import pytest

from server.db.postgres import _POOL_LOCKS_BY_DSN, _POOLS_BY_DSN, PostgresClient


@pytest.mark.asyncio
async def test_failed_connect_does_not_leak_pool_lock_entries() -> None:
    env_keys = (
        "POSTGRES_DSN",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    saved_env = {k: os.environ.get(k) for k in env_keys}
    for key in env_keys:
        os.environ.pop(key, None)

    await PostgresClient.close_shared_pools()
    _POOLS_BY_DSN.clear()
    _POOL_LOCKS_BY_DSN.clear()

    try:
        dsns = [f"postgresql://postgres:postgres@127.0.0.1:1/lock_leak_{i}" for i in range(3)]
        for dsn in dsns:
            client = PostgresClient(dsn)
            with pytest.raises(OSError):
                await client.connect()

        assert _POOLS_BY_DSN == {}
        assert _POOL_LOCKS_BY_DSN == {}
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
