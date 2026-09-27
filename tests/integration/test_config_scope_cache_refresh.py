"""Production config ownership across real cached reads and concurrent writes."""

import asyncio
import uuid

import pytest
import pytest_asyncio

from server.config import DEFAULT_CONFIG_PATH, load_config, save_config
from server.services.config_store import ConfigStore


pytestmark = [pytest.mark.asyncio, pytest.mark.requires_postgres]


@pytest_asyncio.fixture
async def scoped_store():
    original = load_config()
    global_config = original.model_copy(deep=True)
    global_config.ui.runtime_mode = "production"
    global_config.chat.litellm.default_model = "z-ai.glm-5.3-flash"
    store = ConfigStore(global_config.indexing.postgres_url)
    corpus_id = f"pytest_config_refresh_{uuid.uuid4().hex}"
    await store._postgres.connect()
    await store._postgres.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
    await store.save(global_config)
    corpus_config = global_config.model_copy(deep=True)
    corpus_config.chat.temperature = 1.3
    corpus_config.embedding.embedding_backend = "deterministic"
    await store._postgres.upsert_corpus_config_json(corpus_id, corpus_config.model_dump())
    try:
        yield store, corpus_id, global_config
    finally:
        await store._postgres.delete_corpus(corpus_id)
        save_config(original)


async def test_warm_scope_refreshes_global_model_without_losing_corpus_settings(scoped_store):
    store, corpus_id, global_config = scoped_store
    warm = await store.get(corpus_id)
    assert warm.chat.litellm.default_model == "z-ai.glm-5.3-flash"
    global_config.chat.litellm.default_model = "openai.gpt-6-sol"
    await store.save(global_config)

    refreshed = await store.get(corpus_id)
    assert refreshed.chat.litellm.default_model == "openai.gpt-6-sol"
    assert refreshed.chat.temperature == 1.3
    assert refreshed.embedding.embedding_backend == "deterministic"
    refreshed.chat.temperature = 0.1
    assert (await store.get(corpus_id)).chat.temperature == 1.3


async def test_nonpersisting_refresh_changes_neither_storage_nor_cached_snapshots(scoped_store):
    store, corpus_id, global_config = scoped_store
    await store.get(corpus_id)
    global_config.chat.litellm.default_model = "openai.gpt-6-sol"
    await store.save(global_config)
    cache_before = {key: value.model_dump() for key, value in store._cache.items()}
    row_before = await store._postgres.get_corpus_config_json(corpus_id)
    disk_before = DEFAULT_CONFIG_PATH.read_bytes()

    fresh = await store.get(corpus_id, persist=False)

    assert fresh.chat.litellm.default_model == "openai.gpt-6-sol"
    assert fresh.embedding.embedding_backend == "deterministic"
    assert {key: value.model_dump() for key, value in store._cache.items()} == cache_before
    assert await store._postgres.get_corpus_config_json(corpus_id) == row_before
    assert DEFAULT_CONFIG_PATH.read_bytes() == disk_before


async def test_global_save_during_blocked_cold_load_does_not_repopulate_stale_cache(scoped_store):
    store, corpus_id, global_config = scoped_store
    pool = store._postgres._pool
    assert pool is not None
    # Exhaust this test process's actual connection pool, not the shared service.
    connections = [await pool.acquire() for _ in range(pool.get_max_size())]
    pending = asyncio.create_task(store.get(corpus_id))
    try:
        async with asyncio.timeout(5):
            while not pool._queue._getters:
                if pending.done():
                    await pending
                    pytest.fail("Scoped load did not wait for a database connection")
                await asyncio.sleep(0.001)
        global_config.chat.litellm.default_model = "openai.gpt-6-sol"
        await store.save(global_config)
    finally:
        for connection in connections:
            await pool.release(connection)
    try:
        loaded = await pending
        assert loaded.chat.litellm.default_model == "openai.gpt-6-sol"
        assert (await store.get(corpus_id)).chat.litellm.default_model == "openai.gpt-6-sol"
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("write_kind", ["save", "migration"])
async def test_global_save_during_corpus_write_refreshes_returned_and_cached_settings(scoped_store, write_kind):
    store, corpus_id, global_config = scoped_store
    corpus_config = await store.get(corpus_id)
    corpus_config.chat.temperature = 1.5
    if write_kind == "migration":
        corpus_config.chat.litellm.default_model = "openai.gpt-6-luna"
        await store._postgres.upsert_corpus_config_json(corpus_id, corpus_config.model_dump())
        store.clear_cache(corpus_id)
    pool = store._postgres._pool
    assert pool is not None
    async with pool.acquire() as blocker:
        transaction = blocker.transaction()
        await transaction.start()
        await blocker.fetchrow("SELECT repo_id FROM corpus_configs WHERE repo_id = $1 FOR UPDATE", corpus_id)
        pending = asyncio.create_task(
            store.save(corpus_config, corpus_id) if write_kind == "save" else store.get(corpus_id)
        )
        try:
            async with asyncio.timeout(5):
                while not await blocker.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid)))",
                    blocker.get_server_pid(),
                ):
                    if pending.done():
                        await pending
                        pytest.fail("Scoped write did not reach the locked corpus row")
                    await asyncio.sleep(0.001)
            global_config.chat.litellm.default_model = "openai.gpt-6-sol"
            await store.save(global_config)
        finally:
            await transaction.rollback()
    try:
        saved = await pending
        assert saved.chat.litellm.default_model == "openai.gpt-6-sol"
        assert saved.chat.temperature == 1.5
        assert saved.embedding.embedding_backend == "deterministic"
        assert (await store.get(corpus_id)).chat.litellm.default_model == "openai.gpt-6-sol"
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_development_scope_retains_its_model_override(scoped_store):
    store, corpus_id, global_config = scoped_store
    await store.get(corpus_id)
    global_config.ui.runtime_mode = "development"
    global_config.chat.litellm.default_model = "openai.gpt-6-sol"
    await store.save(global_config)
    scoped = await store.get(corpus_id)
    assert scoped.chat.litellm.default_model == "z-ai.glm-5.3-flash"
