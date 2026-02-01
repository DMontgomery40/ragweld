"""Unit tests for Postgres pool reuse.

These tests verify that PostgresClient reuses a single asyncpg pool per DSN,
avoiding expensive pool creation on every request.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_postgres_pool_is_cached_per_dsn(monkeypatch) -> None:
    import server.db.postgres as pgmod

    # Reset module-level caches for test isolation.
    pgmod._POOLS_BY_DSN.clear()
    pgmod._POOL_LOCKS_BY_DSN.clear()

    class _AcquireCM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    pool = MagicMock()
    pool.acquire.return_value = _AcquireCM()
    pool.close = AsyncMock()

    create_pool = AsyncMock(return_value=pool)
    monkeypatch.setattr(pgmod.asyncpg, "create_pool", create_pool, raising=True)
    monkeypatch.setattr(pgmod, "register_vector", AsyncMock(), raising=True)
    monkeypatch.setattr(pgmod.PostgresClient, "_ensure_schema", AsyncMock(), raising=True)

    # Two distinct clients, same DSN → one pool.
    c1 = pgmod.PostgresClient("postgresql://example")
    c2 = pgmod.PostgresClient("postgresql://example")

    await c1.connect()
    await c2.connect()

    assert create_pool.await_count == 1
    assert c1._pool is c2._pool

    # disconnect() should not close shared pools.
    await c1.disconnect()
    await c2.disconnect()
    assert pool.close.await_count == 0

    # Explicit shared pool shutdown closes the pool.
    await pgmod.PostgresClient.close_shared_pools()
    assert pool.close.await_count == 1

