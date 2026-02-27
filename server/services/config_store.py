"""Config persistence service.

TriBrid supports corpus separation (each corpus has its own settings).

- Global config: `tribrid_config.json` (defaults/template)
- Per-corpus config: stored in Postgres `corpus_configs` as JSONB

This module provides a small API to load/save either global or per-corpus configs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from server.config import DEFAULT_CONFIG_PATH
from server.config import load_config as load_global_config
from server.config import save_config as save_global_config
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig

logger = logging.getLogger(__name__)


class CorpusNotFoundError(RuntimeError):
    """Raised when a corpus-scoped config is requested for a missing corpus."""


_REMOVED_NESTED_KEYS: tuple[str, ...] = (
    "indexing.table_name",
    "indexing.collection_suffix",
    "indexing.repo_path",
    "indexing.out_dir_base",
    "indexing.rag_out_base",
    "indexing.repos_file",
    "indexing.bm25_stopwords_lang",
)

_REMOVED_FLAT_KEYS: tuple[str, ...] = (
    "COLLECTION_NAME",
    "COLLECTION_SUFFIX",
    "REPO_PATH",
    "OUT_DIR_BASE",
    "RAG_OUT_BASE",
    "REPOS_FILE",
    "BM25_STOPWORDS_LANG",
)


def _remove_nested_key(payload: dict[str, Any], dotted_path: str) -> bool:
    parts = [p for p in str(dotted_path or "").split(".") if p]
    if not parts:
        return False
    cur: Any = payload
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    leaf = parts[-1]
    if isinstance(cur, dict) and leaf in cur:
        del cur[leaf]
        return True
    return False


def _migrate_config_in_place(cfg: TriBridConfig) -> list[str]:
    """Apply small backward-compatible config migrations.

    This is intentionally minimal and only handles known-bad historical values.
    """
    migrated: list[str] = []

    # OpenRouter model ids must be valid OpenRouter `provider/model` strings.
    # A prior default shipped with a non-existent suffix, which breaks provider calls.
    try:
        if cfg.chat.openrouter.default_model == "anthropic/claude-sonnet-4-20250514":
            cfg.chat.openrouter.default_model = "anthropic/claude-sonnet-4"
            migrated.append("chat.openrouter.default_model")
    except Exception:
        # Best-effort; never block config loads.
        pass
    return migrated


def _upgrade_raw_config(raw: dict[str, Any]) -> tuple[TriBridConfig, bool, list[str]]:
    """Upgrade stored JSON config and return (validated_cfg, changed, migrated_keys)."""
    working = dict(raw or {})
    migrated_keys: list[str] = []

    for key in _REMOVED_FLAT_KEYS:
        if key in working:
            del working[key]
            migrated_keys.append(key)

    for dotted in _REMOVED_NESTED_KEYS:
        if _remove_nested_key(working, dotted):
            migrated_keys.append(dotted)

    cfg = TriBridConfig.model_validate(working)
    migrated_keys.extend(_migrate_config_in_place(cfg))
    normalized = cfg.model_dump()
    changed = normalized != raw
    return (cfg, changed, sorted(set(migrated_keys)))


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
            cfg: TriBridConfig
            changed = False
            migrated: list[str] = []
            if DEFAULT_CONFIG_PATH.exists():
                try:
                    raw = json.loads(DEFAULT_CONFIG_PATH.read_text())
                except Exception:
                    raw = None
                if isinstance(raw, dict):
                    cfg, changed, migrated = _upgrade_raw_config(raw)
                else:
                    cfg = load_global_config()
            else:
                cfg = load_global_config()

            if changed:
                save_global_config(cfg)
                if migrated:
                    logger.info("Auto-migrated global config keys: %s", ", ".join(migrated))
            self._cache[None] = cfg
            return cfg

        # Per-corpus config lives in Postgres
        base = (await self.get(repo_id=None)).model_copy(deep=True)
        await self._postgres.connect()

        # Ensure corpus row exists (do NOT auto-create on read)
        corpus = await self._postgres.get_corpus(repo_id)
        if corpus is None:
            raise CorpusNotFoundError(f"Corpus not found: {repo_id}")

        raw = await self._postgres.get_corpus_config_json(repo_id)
        if raw is None:
            # Seed new corpus config from the global template
            await self._postgres.upsert_corpus_config_json(repo_id, base.model_dump())
            cfg = base
        else:
            cfg, changed, migrated = _upgrade_raw_config(raw)
            if changed:
                await self._postgres.upsert_corpus_config_json(repo_id, cfg.model_dump())
                if migrated:
                    logger.info("Auto-migrated corpus config keys repo_id=%s: %s", repo_id, ", ".join(migrated))
        self._cache[repo_id] = cfg
        return cfg

    async def save(self, config: TriBridConfig, repo_id: str | None = None) -> TriBridConfig:
        """Persist config for a corpus (repo_id) or global when repo_id is None."""
        _migrate_config_in_place(config)
        if repo_id is None:
            save_global_config(config)
            self._cache[None] = config
            return config

        await self._postgres.connect()
        corpus = await self._postgres.get_corpus(repo_id)
        if corpus is None:
            raise CorpusNotFoundError(f"Corpus not found: {repo_id}")
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
