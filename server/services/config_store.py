"""Config persistence service.

TriBrid supports corpus separation (each corpus has its own settings).

- Global config: `tribrid_config.json` (defaults/template)
- Per-corpus config: stored in Postgres `corpus_configs` as JSONB

This module provides a small API to load/save either global or per-corpus configs.
"""

from __future__ import annotations

from server.config import load_config as load_global_config
from server.config import save_config as save_global_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig


class ConfigStore:
    """Load/save TriBridConfig for global and per-corpus scopes."""

    def __init__(self, postgres_dsn: str):
        self._postgres = PostgresClient(postgres_dsn)
        self._cache: dict[str | None, TriBridConfig] = {}

    async def get(self, repo_id: str | None = None) -> TriBridConfig:
        """Get config for a corpus (repo_id) or global when repo_id is None."""
        if repo_id in self._cache:
            return self._cache[repo_id]

        if repo_id is None:
            cfg = load_global_config()
            self._cache[None] = cfg
            return cfg

        # Per-corpus config lives in Postgres
        base = load_global_config()
        await self._postgres.connect()

        # Ensure corpus row exists (name defaults to repo_id)
        corpus = await self._postgres.get_corpus(repo_id)
        if corpus is None:
            await self._postgres.upsert_corpus(repo_id, name=repo_id, root_path=base.indexing.repo_path or ".")

        raw = await self._postgres.get_corpus_config_json(repo_id)
        if raw is None:
            # Seed new corpus config from the global template
            await self._postgres.upsert_corpus_config_json(repo_id, base.model_dump())
            cfg = base
        else:
            cfg = TriBridConfig.model_validate(raw)

        self._cache[repo_id] = cfg
        return cfg

    async def save(self, config: TriBridConfig, repo_id: str | None = None) -> TriBridConfig:
        """Persist config for a corpus (repo_id) or global when repo_id is None."""
        if repo_id is None:
            save_global_config(config)
            self._cache[None] = config
            return config

        await self._postgres.connect()
        await self._postgres.upsert_corpus_config_json(repo_id, config.model_dump())
        self._cache[repo_id] = config
        return config

    async def reset(self, repo_id: str | None = None) -> TriBridConfig:
        """Reset config to LAW defaults for the selected scope."""
        cfg = TriBridConfig()
        return await self.save(cfg, repo_id=repo_id)

    def clear_cache(self, repo_id: str | None = None) -> None:
        if repo_id is None:
            self._cache.clear()
            return
        self._cache.pop(repo_id, None)


_store: ConfigStore | None = None


def get_config_store(postgres_dsn: str | None = None) -> ConfigStore:
    """Get the process-wide ConfigStore singleton."""
    global _store
    if _store is not None:
        return _store
    if not postgres_dsn:
        # Bootstrap from global config (source of truth for DSN defaults)
        postgres_dsn = load_global_config().indexing.postgres_url
    _store = ConfigStore(postgres_dsn)
    return _store


async def get_config(repo_id: str | None = None) -> TriBridConfig:
    """Convenience wrapper to load config for a scope."""
    store = get_config_store()
    return await store.get(repo_id=repo_id)


async def save_config(config: TriBridConfig, repo_id: str | None = None) -> TriBridConfig:
    """Convenience wrapper to save config for a scope."""
    store = get_config_store()
    return await store.save(config, repo_id=repo_id)


async def reset_config(repo_id: str | None = None) -> TriBridConfig:
    store = get_config_store()
    return await store.reset(repo_id=repo_id)
