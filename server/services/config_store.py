"""Config persistence service.

TriBrid supports corpus separation (each corpus has its own settings).

- Global config: `tribrid_config.json` (defaults/template)
- Per-corpus config: stored in Postgres `corpus_configs` as JSONB

This module provides a small API to load/save either global or per-corpus configs.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from typing import Any

from server.config import DEFAULT_CONFIG_PATH, drop_retired_prompt_defaults
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
    "indexing.auto_prepare_dense_retrieval",
    "sparse_search.engine",
    "sparse_search.query_mode",
    "sparse_search.highlight",
    "sparse_search.relax_on_empty",
    "sparse_search.relax_max_terms",
    "sparse_search.file_path_fallback",
    "sparse_search.file_path_max_terms",
    "retrieval.bm25_k1",
    "retrieval.bm25_b",
    "chat.recall.vector_backend",
    "graph_storage.neo4j_password",
    "chat.litellm.api_key",
    # Removed legacy base+suffix chat prompt composition (M-101/B-22/E-53): the 4-state
    # prompts replaced it. Strip the dead keys so persisted (extra="forbid") configs load.
    "chat.system_prompt_base",
    "chat.system_prompt_rag_suffix",
    "chat.system_prompt_recall_suffix",
    "graph_search.mode",
    "graph_search.chunk_seed_overfetch_multiplier",
    "graph_search.chunk_entity_expansion_enabled",
    "graph_search.chunk_entity_expansion_weight",
    "graph_indexing.store_chunk_embeddings",
    "graph_indexing.chunk_vector_index_name",
    "graph_indexing.chunk_embedding_property",
    "graph_indexing.vector_similarity_function",
    "graph_indexing.wait_vector_index_online",
    "graph_indexing.vector_index_online_timeout_s",
    "graph_storage.community_algorithm",
)

_REMOVED_FLAT_KEYS: tuple[str, ...] = (
    "COLLECTION_NAME",
    "COLLECTION_SUFFIX",
    "REPO_PATH",
    "OUT_DIR_BASE",
    "RAG_OUT_BASE",
    "REPOS_FILE",
    "BM25_STOPWORDS_LANG",
    "BM25_K1",
    "BM25_B",
    "AUTO_PREPARE_DENSE_RETRIEVAL",
    "NEO4J_PASSWORD",
    "GRAPH_COMMUNITY_ALGORITHM",
)


_PRODUCTION_SCOPED_GLOBAL_PATHS: tuple[str, ...] = (
    "generation.gen_model",
    "generation.enrich_model",
    "generation.gen_max_tokens",
    "chat.max_tokens",
    "chat.litellm.default_model",
    "chat.multimodal.vision_model_override",
    "chat.vllm.enabled",
    "chat.web",
    "synthetic.generator.max_tokens",
    "embedding.embedding_backend",
    "embedding.embedding_type",
    "embedding.embedding_model",
    "embedding.embedding_dim",
    "ui.chat_default_model",
    "ui.runtime_mode",
    "ui.open_browser",
    "ui.grafana_base_url",
    "tracing.langfuse_base_url",
    "tracing.langfuse_public_base_url",
    "tracing.faro_base_url",
    "tracing.trace_store_path",
    "training.ragweld_agent_flyte_admin_base_url",
    "training.ragweld_agent_flyte_console_base_url",
    "training.ragweld_agent_flyte_callback_base_url",
    "training.ragweld_agent_mlflow_tracking_url",
    "training.ragweld_agent_mlflow_console_base_url",
    "evaluation.ragas_judge_model",
    "evaluation.promptfoo_grader_model",
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


def _value_at_path(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        current = current[part]
    return current


def _set_value_at_path(payload: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    current: Any = payload
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = copy.deepcopy(value)


def _reconcile_production_scope(
    config: TriBridConfig,
    global_config: TriBridConfig,
) -> tuple[TriBridConfig, bool, list[str]]:
    """Apply deployment-owned production values to a corpus-scoped config."""
    if str(global_config.ui.runtime_mode or "").strip().lower() != "production":
        return config, False, []

    scoped_payload = config.model_dump(mode="json")
    global_payload = global_config.model_dump(mode="json")
    changed_paths: list[str] = []
    for dotted_path in _PRODUCTION_SCOPED_GLOBAL_PATHS:
        expected = _value_at_path(global_payload, dotted_path)
        if _value_at_path(scoped_payload, dotted_path) == expected:
            continue
        _set_value_at_path(scoped_payload, dotted_path, expected)
        changed_paths.append(dotted_path)

    if not changed_paths:
        return config, False, []
    return TriBridConfig.model_validate(scoped_payload), True, changed_paths


def _upgrade_raw_config(raw: dict[str, Any]) -> tuple[TriBridConfig, bool, list[str]]:
    """Upgrade stored JSON config and return (validated_cfg, changed, migrated_keys)."""
    original = copy.deepcopy(raw or {})
    working = copy.deepcopy(original)
    migrated_keys: list[str] = []

    for key in _REMOVED_FLAT_KEYS:
        if key in working:
            del working[key]
            migrated_keys.append(key)

    for dotted in _REMOVED_NESTED_KEYS:
        if _remove_nested_key(working, dotted):
            migrated_keys.append(dotted)

    migrated_keys.extend(drop_retired_prompt_defaults(working))

    chunking = working.get("chunking")
    if isinstance(chunking, dict):
        strategy = str(chunking.get("chunking_strategy") or "").strip().lower()
        if strategy == "semantic":
            chunking["chunking_strategy"] = "fixed_chars"
            migrated_keys.append("chunking.chunking_strategy")

    generation = working.get("generation")
    if isinstance(generation, dict) and generation.get("gen_max_tokens") == 2048:
        generation["gen_max_tokens"] = 512
        migrated_keys.append("generation.gen_max_tokens")

    # The retired 10 s reranker timeout sat inside the idle latency spread of the default
    # cloud candidate window (D15); the config page persisted that default verbatim.
    reranking = working.get("reranking")
    if isinstance(reranking, dict) and reranking.get("reranker_timeout") == 10:
        reranking["reranker_timeout"] = 30
        migrated_keys.append("reranking.reranker_timeout")

    embedding = working.get("embedding")
    if (
        isinstance(embedding, dict)
        and embedding.get("embedding_backend") == "provider"
        and embedding.get("embedding_type") == "mlx"
        and embedding.get("embedding_model_mlx") == "mlx-community/all-MiniLM-L6-v2-4bit"
    ):
        embedding["embedding_type"] = "huggingface"
        migrated_keys.append("embedding.embedding_type")

    if (
        isinstance(embedding, dict)
        and embedding.get("embedding_backend") == "provider"
        and embedding.get("embedding_type") in {"local", "huggingface"}
        and embedding.get("embedding_model_local", "all-MiniLM-L6-v2") == "all-MiniLM-L6-v2"
    ):
        embedding["embedding_model_local"] = "BAAI/bge-small-en-v1.5"
        migrated_keys.append("embedding.embedding_model_local")

    cfg = TriBridConfig.model_validate(working)
    changed = bool(migrated_keys)
    return (cfg, changed, sorted(set(migrated_keys)))


class ConfigStore:
    """Load/save TriBridConfig for global and per-corpus scopes."""

    def __init__(self, postgres_dsn: str):
        self._postgres = PostgresClient(postgres_dsn, schema_mode="control")
        self._cache: dict[str | None, TriBridConfig] = {}
        self._locks: dict[str | None, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _get_lock(self, repo_id: str | None) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(repo_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[repo_id] = lock
            return lock

    async def get(self, repo_id: str | None = None) -> TriBridConfig:
        """Get config for a corpus (repo_id) or global when repo_id is None."""
        lock = await self._get_lock(repo_id)
        async with lock:
            if repo_id is None and repo_id in self._cache:
                return self._cache[repo_id].model_copy(deep=True)

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
                self._cache[None] = cfg.model_copy(deep=True)
                return self._cache[None].model_copy(deep=True)

            # Per-corpus config lives in Postgres
            base = (await self.get(repo_id=None)).model_copy(deep=True)
            await self._postgres.connect()

            # Ensure corpus row exists (do NOT auto-create on read)
            corpus = await self._postgres.get_corpus(repo_id)
            if corpus is None:
                raise CorpusNotFoundError(f"Corpus not found: {repo_id}")

            if repo_id in self._cache:
                return self._cache[repo_id].model_copy(deep=True)

            raw = await self._postgres.get_corpus_config_json(repo_id)
            if raw is None:
                # Seed new corpus config from the global template
                await self._postgres.upsert_corpus_config_json(repo_id, base.model_dump())
                cfg = base
            else:
                cfg, changed, migrated = _upgrade_raw_config(raw)
                cfg, reconciled, reconciled_paths = _reconcile_production_scope(cfg, base)
                changed = changed or reconciled
                migrated.extend(reconciled_paths)
                if changed:
                    await self._postgres.upsert_corpus_config_json(repo_id, cfg.model_dump())
                    if migrated:
                        logger.info("Auto-migrated corpus config keys repo_id=%s: %s", repo_id, ", ".join(migrated))
            self._cache[repo_id] = cfg.model_copy(deep=True)
            return self._cache[repo_id].model_copy(deep=True)

    async def save(self, config: TriBridConfig, repo_id: str | None = None) -> TriBridConfig:
        """Persist config for a corpus (repo_id) or global when repo_id is None."""
        lock = await self._get_lock(repo_id)
        async with lock:
            if repo_id is None:
                save_global_config(config)
                self._cache[None] = config.model_copy(deep=True)
                return self._cache[None].model_copy(deep=True)

            await self._postgres.connect()
            corpus = await self._postgres.get_corpus(repo_id)
            if corpus is None:
                raise CorpusNotFoundError(f"Corpus not found: {repo_id}")
            base = await self.get(repo_id=None)
            config, _, _ = _reconcile_production_scope(config, base)
            await self._postgres.upsert_corpus_config_json(repo_id, config.model_dump())
            self._cache[repo_id] = config.model_copy(deep=True)
            return self._cache[repo_id].model_copy(deep=True)

    async def reset(self, repo_id: str | None = None) -> TriBridConfig:
        """Reset config to LAW defaults for the selected scope."""
        cfg = TriBridConfig()
        return await self.save(cfg, repo_id=repo_id)

    def clear_cache(self, repo_id: str | None = None) -> None:
        def _drop_lock_if_idle(key: str | None) -> None:
            lock = self._locks.get(key)
            if lock is None:
                return
            # Preserve held locks so in-flight callers cannot split synchronization.
            if lock.locked():
                return
            self._locks.pop(key, None)

        if repo_id is None:
            self._cache.clear()
            for key in list(self._locks.keys()):
                _drop_lock_if_idle(key)
            return
        self._cache.pop(repo_id, None)
        _drop_lock_if_idle(repo_id)


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
