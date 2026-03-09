import asyncio

import pytest

from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import ConfigStore


@pytest.mark.asyncio
async def test_get_global_config_returns_detached_copy() -> None:
    store = ConfigStore("postgresql://unused")

    cfg1 = await store.get(repo_id=None)
    cfg2 = await store.get(repo_id=None)

    assert cfg1 is not cfg2

    original = str(cfg2.generation.gen_model or "")
    mutated = f"{original}-race-test" if original else "race-test-model"
    cfg1.generation.gen_model = mutated

    cfg3 = await store.get(repo_id=None)
    assert cfg3.generation.gen_model == original


class _ControlledPostgres:
    def __init__(self, *, raw: dict[str, object], started: asyncio.Event, release: asyncio.Event) -> None:
        self._raw = raw
        self._started = started
        self._release = release

    async def connect(self) -> None:
        return None

    async def get_corpus(self, repo_id: str) -> dict[str, object]:
        _ = repo_id
        return {"id": repo_id}

    async def get_corpus_config_json(self, repo_id: str) -> dict[str, object]:
        _ = repo_id
        self._started.set()
        await self._release.wait()
        return self._raw

    async def upsert_corpus_config_json(self, repo_id: str, payload: dict[str, object]) -> None:
        _ = repo_id
        _ = payload
        return None


@pytest.mark.asyncio
async def test_get_does_not_overwrite_newer_concurrent_repo_save() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    old_cfg = TriBridConfig()
    new_cfg = TriBridConfig()
    new_cfg.generation.gen_model = "concurrency-new-model"

    store = ConfigStore("postgresql://unused")
    store._cache[None] = TriBridConfig()
    store._postgres = _ControlledPostgres(raw=old_cfg.model_dump(), started=started, release=release)  # type: ignore[assignment]

    pending_get = asyncio.create_task(store.get(repo_id="repo-1"))
    await started.wait()

    pending_save = asyncio.create_task(store.save(new_cfg, repo_id="repo-1"))
    release.set()
    await pending_get
    await pending_save

    final_cfg = await store.get(repo_id="repo-1")
    assert final_cfg.generation.gen_model == "concurrency-new-model"


@pytest.mark.asyncio
async def test_clear_cache_releases_repo_lock() -> None:
    store = ConfigStore("postgresql://unused")

    lock = await store._get_lock("repo-ephemeral")
    assert lock is store._locks["repo-ephemeral"]

    store.clear_cache(repo_id="repo-ephemeral")
    assert "repo-ephemeral" not in store._locks


@pytest.mark.asyncio
async def test_clear_cache_does_not_replace_lock_while_held() -> None:
    store = ConfigStore("postgresql://unused")

    first_lock = await store._get_lock("repo-race")
    await first_lock.acquire()
    try:
        store.clear_cache(repo_id="repo-race")
        second_lock = await store._get_lock("repo-race")
    finally:
        first_lock.release()

    assert second_lock is first_lock
