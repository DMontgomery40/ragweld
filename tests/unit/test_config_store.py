import pytest

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
