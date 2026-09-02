import asyncio
import os

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


@pytest.mark.asyncio
async def test_warm_corpus_cache_does_not_hide_postgres_outage() -> None:
    postgres_keys = (
        "POSTGRES_DSN",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    previous = {key: os.environ.pop(key) for key in postgres_keys if key in os.environ}
    try:
        store = ConfigStore("postgresql://postgres:postgres@127.0.0.1:1/ragweld_outage")
        store._cache["warm-corpus"] = TriBridConfig()

        with pytest.raises((ConnectionError, OSError, TimeoutError)):
            await store.get(repo_id="warm-corpus")
    finally:
        os.environ.update(previous)


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


class _SnapshotPostgres:
    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw
        self.upserts: list[tuple[str, dict[str, object]]] = []

    async def connect(self) -> None:
        return None

    async def get_corpus(self, repo_id: str) -> dict[str, object]:
        return {"id": repo_id}

    async def get_corpus_config_json(self, repo_id: str) -> dict[str, object]:
        _ = repo_id
        return self.raw

    async def upsert_corpus_config_json(self, repo_id: str, payload: dict[str, object]) -> None:
        self.upserts.append((repo_id, payload))


def _production_global_config() -> TriBridConfig:
    cfg = TriBridConfig()
    cfg.ui.runtime_mode = "production"
    cfg.generation.gen_model = "openai.gpt-5.6-terra"
    cfg.generation.enrich_model = "openai.gpt-5.6-terra"
    cfg.chat.max_tokens = 16000
    cfg.chat.litellm.default_model = "z-ai.glm-5.3-flash"
    cfg.ui.chat_default_model = "z-ai.glm-5.3-flash"
    cfg.chat.web.max_results = 8
    cfg.chat.web.max_total_results = 10
    cfg.chat.web.max_characters = 24000
    cfg.synthetic.generator.max_tokens = 16000
    cfg.ui.grafana_base_url = "https://ragweld-grafana.dtmont.com"
    cfg.tracing.langfuse_public_base_url = "https://ragweld-langfuse.dtmont.com"
    cfg.tracing.faro_base_url = "https://ragweld.dtmont.com/faro/collect"
    cfg.tracing.trace_store_path = "data/traces/workbench.json"
    cfg.training.ragweld_agent_flyte_console_base_url = "https://ragweld-flyte.dtmont.com"
    cfg.training.ragweld_agent_mlflow_console_base_url = "https://ragweld-mlflow.dtmont.com"
    cfg.evaluation.ragas_judge_model = "openai.gpt-5.6-terra"
    cfg.evaluation.promptfoo_grader_model = "openai.gpt-5.6-terra"
    return cfg


def _legacy_scoped_config() -> TriBridConfig:
    cfg = TriBridConfig()
    cfg.generation.gen_model = "z-ai.glm-5.3-flash"
    cfg.generation.enrich_model = "z-ai.glm-5.3-flash"
    cfg.chat.max_tokens = 4096
    cfg.chat.litellm.default_model = "openai.gpt-5.6-terra"
    cfg.ui.chat_default_model = "openai.gpt-5.6-terra"
    cfg.chat.web.enabled = False
    cfg.chat.web.max_results = 1
    cfg.synthetic.generator.max_tokens = 4096
    cfg.ui.grafana_base_url = "https://grafana.ragweld.com"
    cfg.tracing.langfuse_public_base_url = "https://langfuse.ragweld.com"
    cfg.tracing.faro_base_url = "https://me.ragweld.com/faro/collect"
    cfg.tracing.trace_store_path = ""
    cfg.training.ragweld_agent_flyte_console_base_url = "https://flyte.ragweld.com"
    cfg.training.ragweld_agent_mlflow_console_base_url = "https://mlflow.ragweld.com"
    cfg.evaluation.ragas_judge_model = "z-ai.glm-5.3-flash"
    cfg.evaluation.promptfoo_grader_model = "z-ai.glm-5.3-flash"
    cfg.chat.temperature = 1.7
    return cfg


@pytest.mark.asyncio
async def test_production_scope_reconciles_deployment_contract_and_persists_migration() -> None:
    global_cfg = _production_global_config()
    legacy = _legacy_scoped_config()
    postgres = _SnapshotPostgres(legacy.model_dump())
    store = ConfigStore("postgresql://unused")
    store._cache[None] = global_cfg
    store._postgres = postgres  # type: ignore[assignment]

    scoped = await store.get(repo_id="nasa-apollo-11")

    assert scoped.generation.gen_model == "openai.gpt-5.6-terra"
    assert scoped.generation.enrich_model == "openai.gpt-5.6-terra"
    assert scoped.chat.max_tokens == 16000
    assert scoped.chat.litellm.default_model == "z-ai.glm-5.3-flash"
    assert scoped.ui.chat_default_model == "z-ai.glm-5.3-flash"
    assert scoped.chat.web == global_cfg.chat.web
    assert scoped.synthetic.generator.max_tokens == 16000
    assert scoped.ui.grafana_base_url == "https://ragweld-grafana.dtmont.com"
    assert scoped.tracing.langfuse_public_base_url == "https://ragweld-langfuse.dtmont.com"
    assert scoped.tracing.faro_base_url == "https://ragweld.dtmont.com/faro/collect"
    assert scoped.tracing.trace_store_path == "data/traces/workbench.json"
    assert scoped.training.ragweld_agent_flyte_console_base_url == "https://ragweld-flyte.dtmont.com"
    assert scoped.training.ragweld_agent_mlflow_console_base_url == "https://ragweld-mlflow.dtmont.com"
    assert scoped.evaluation.ragas_judge_model == "openai.gpt-5.6-terra"
    assert scoped.evaluation.promptfoo_grader_model == "openai.gpt-5.6-terra"
    assert scoped.chat.temperature == 1.7

    assert len(postgres.upserts) == 1
    repo_id, persisted = postgres.upserts[0]
    assert repo_id == "nasa-apollo-11"
    assert persisted["ui"]["grafana_base_url"] == "https://ragweld-grafana.dtmont.com"  # type: ignore[index]
    assert persisted["chat"]["litellm"]["default_model"] == "z-ai.glm-5.3-flash"  # type: ignore[index]
    assert persisted["chat"]["web"]["max_characters"] == 24000  # type: ignore[index]


@pytest.mark.asyncio
async def test_production_scope_save_cannot_reintroduce_deployment_drift() -> None:
    global_cfg = _production_global_config()
    legacy = _legacy_scoped_config()
    postgres = _SnapshotPostgres(legacy.model_dump())
    store = ConfigStore("postgresql://unused")
    store._cache[None] = global_cfg
    store._postgres = postgres  # type: ignore[assignment]

    saved = await store.save(legacy, repo_id="nasa-apollo-11")

    assert saved.ui.grafana_base_url == "https://ragweld-grafana.dtmont.com"
    assert saved.tracing.faro_base_url == "https://ragweld.dtmont.com/faro/collect"
    assert saved.chat.litellm.default_model == "z-ai.glm-5.3-flash"
    assert saved.chat.web == global_cfg.chat.web
    assert saved.chat.max_tokens == 16000
    assert saved.chat.temperature == 1.7
    assert postgres.upserts[-1][1]["ui"]["grafana_base_url"] == "https://ragweld-grafana.dtmont.com"  # type: ignore[index]


@pytest.mark.asyncio
async def test_production_scope_reconciles_schema_defaulted_missing_keys() -> None:
    global_cfg = _production_global_config()
    postgres = _SnapshotPostgres({})
    store = ConfigStore("postgresql://unused")
    store._cache[None] = global_cfg
    store._postgres = postgres  # type: ignore[assignment]

    scoped = await store.get(repo_id="legacy-minimal")

    assert scoped.ui.grafana_base_url == "https://ragweld-grafana.dtmont.com"
    assert scoped.chat.litellm.default_model == "z-ai.glm-5.3-flash"
    assert scoped.tracing.trace_store_path == "data/traces/workbench.json"


@pytest.mark.asyncio
async def test_nonproduction_scope_preserves_corpus_overrides() -> None:
    global_cfg = _production_global_config()
    global_cfg.ui.runtime_mode = "development"
    legacy = _legacy_scoped_config()
    postgres = _SnapshotPostgres(legacy.model_dump())
    store = ConfigStore("postgresql://unused")
    store._cache[None] = global_cfg
    store._postgres = postgres  # type: ignore[assignment]

    scoped = await store.get(repo_id="development-corpus")

    assert scoped.ui.grafana_base_url == "https://grafana.ragweld.com"
    assert scoped.chat.litellm.default_model == "openai.gpt-5.6-terra"
    assert scoped.chat.web.enabled is False
    assert scoped.chat.max_tokens == 4096
    assert postgres.upserts == []


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


@pytest.mark.asyncio
async def test_production_scope_keeps_corpus_embedding_overrides() -> None:
    """S18 (2026-09-02 drive): a corpus's embedding settings are its own index contract.

    In production mode the store reconciled ``embedding.*`` to the deployment globals on
    every read and save, while the index job honoured the corpus's saved value. A PATCH
    of ``embedding_backend=deterministic`` answered 200, the first run embedded
    deterministically, the config API read back ``provider``, and the next non-forced run
    refused with "stored=deterministic, config=provider". What an operator saves on a
    corpus applies to that corpus; the deployment owns URLs and default models, not the
    corpus's embedding contract.
    """
    global_cfg = _production_global_config()
    global_cfg.embedding.embedding_backend = "provider"
    global_cfg.embedding.embedding_type = "huggingface"
    scoped_cfg = _legacy_scoped_config()
    scoped_cfg.ui.runtime_mode = "production"
    scoped_cfg.embedding.embedding_backend = "deterministic"
    postgres = _SnapshotPostgres(scoped_cfg.model_dump())
    store = ConfigStore("postgresql://unused")
    store._cache[None] = global_cfg
    store._postgres = postgres  # type: ignore[assignment]

    scoped = await store.get(repo_id="pytest_embedding_override")
    assert scoped.embedding.embedding_backend == "deterministic"
    # The deployment-owned values still reconcile; the corpus's embedding choice does not.
    assert scoped.ui.grafana_base_url == "https://ragweld-grafana.dtmont.com"
    for _repo_id, payload in postgres.upserts:
        assert payload["embedding"]["embedding_backend"] == "deterministic"  # type: ignore[index]

    scoped.embedding.embedding_backend = "deterministic"
    saved = await store.save(scoped, repo_id="pytest_embedding_override")
    assert saved.embedding.embedding_backend == "deterministic"
    assert postgres.upserts[-1][1]["embedding"]["embedding_backend"] == "deterministic"  # type: ignore[index]
