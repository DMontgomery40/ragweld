from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.check_config_reality import (
    MAP_PATH,
    iter_leaf_keys,
    load_reality_map,
    validate_reality_map,
)
from server.models.tribrid_config_model import ChatConfig, TriBridConfig
from server.services.config_store import _upgrade_raw_config

LEGACY_CHAT_PROMPT_FIELDS = (
    "system_prompt_base",
    "system_prompt_rag_suffix",
    "system_prompt_recall_suffix",
)


def test_config_reality_map_covers_all_tribrid_leaf_keys() -> None:
    leaves = iter_leaf_keys(TriBridConfig)
    mapping = load_reality_map(MAP_PATH)
    errors = validate_reality_map(mapping, leaves)
    assert not errors


def test_upgrade_raw_config_removes_legacy_indexing_keys() -> None:
    raw = {
        "indexing": {
            "postgres_url": "postgresql://postgres:postgres@localhost:5432/tribrid_rag",
            "table_name": "code_chunks_legacy",
            "collection_suffix": "legacy",
            "repo_path": "/tmp/legacy",
            "out_dir_base": "./out",
            "rag_out_base": "./rag",
            "repos_file": "./repos.json",
            "bm25_stopwords_lang": "en",
            "indexing_batch_size": 77,
        },
        "COLLECTION_NAME": "legacy_flat_collection",
        "REPOS_FILE": "./legacy.json",
        "BM25_STOPWORDS_LANG": "en",
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)
    assert changed is True
    assert cfg.indexing.indexing_batch_size == 77

    migrated_set = set(migrated)
    assert "indexing.table_name" in migrated_set
    assert "indexing.collection_suffix" in migrated_set
    assert "indexing.repo_path" in migrated_set
    assert "indexing.out_dir_base" in migrated_set
    assert "indexing.rag_out_base" in migrated_set
    assert "indexing.repos_file" in migrated_set
    assert "indexing.bm25_stopwords_lang" in migrated_set
    assert "COLLECTION_NAME" in migrated_set
    assert "REPOS_FILE" in migrated_set
    assert "BM25_STOPWORDS_LANG" in migrated_set


def test_upgrade_raw_config_normalizes_legacy_semantic_chunking() -> None:
    raw = {
        "chunking": {
            "chunking_strategy": "semantic",
        }
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is True
    assert cfg.chunking.chunking_strategy == "fixed_chars"
    assert "chunking.chunking_strategy" in set(migrated)


def test_upgrade_raw_config_replaces_legacy_generation_budget_but_preserves_production_chat_budget() -> None:
    raw = {
        "generation": {"gen_max_tokens": 2048},
        "chat": {"max_tokens": 4096},
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is True
    assert cfg.generation.gen_max_tokens == 512
    assert cfg.chat.max_tokens == 4096
    assert migrated == ["generation.gen_max_tokens"]


@pytest.mark.parametrize("chat_budget", [1024, 4096, 16384])
def test_upgrade_raw_config_preserves_explicit_nonlegacy_token_budgets(chat_budget: int) -> None:
    raw = {
        "generation": {"gen_max_tokens": 768},
        "chat": {"max_tokens": chat_budget},
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is False
    assert migrated == []
    assert cfg.generation.gen_max_tokens == 768
    assert cfg.chat.max_tokens == chat_budget


def test_upgrade_raw_config_replaces_pre_gateway_mlx_embedding_default() -> None:
    raw = {
        "embedding": {
            "embedding_backend": "provider",
            "embedding_type": "mlx",
            "embedding_model_mlx": "mlx-community/all-MiniLM-L6-v2-4bit",
            "embedding_dim": 384,
        }
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is True
    assert cfg.embedding.embedding_type == "huggingface"
    assert cfg.embedding.embedding_model_local == "BAAI/bge-small-en-v1.5"
    assert "embedding.embedding_type" in set(migrated)
    assert "embedding.embedding_model_local" in set(migrated)


def test_upgrade_raw_config_replaces_uncataloged_local_embedding_default() -> None:
    raw = {
        "embedding": {
            "embedding_backend": "provider",
            "embedding_type": "huggingface",
            "embedding_model_local": "all-MiniLM-L6-v2",
            "embedding_dim": 384,
        }
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is True
    assert cfg.embedding.embedding_model_local == "BAAI/bge-small-en-v1.5"
    assert "embedding.embedding_model_local" in set(migrated)


def test_legacy_base_suffix_chat_prompt_fields_are_removed() -> None:
    """The legacy base+suffix chat prompt composition was deleted (M-101/E-53).

    The live prompt builder selects one of the four state prompts; the base+suffix
    fields were a dead dual path and must not exist on ChatConfig anymore.
    """
    fields = set(ChatConfig.model_fields)
    for name in LEGACY_CHAT_PROMPT_FIELDS:
        assert name not in fields, f"{name} should be deleted from ChatConfig"
    # The four state prompts that replaced them remain.
    for name in (
        "system_prompt_direct",
        "system_prompt_rag",
        "system_prompt_recall",
        "system_prompt_rag_and_recall",
    ):
        assert name in fields


def test_chatconfig_forbids_persisted_legacy_prompt_keys_without_migration() -> None:
    """RED guard: with extra="forbid", a stored config carrying the legacy keys would
    fail to validate — proving the migration below is load-bearing, not cosmetic."""
    for name in LEGACY_CHAT_PROMPT_FIELDS:
        with pytest.raises(ValidationError):
            TriBridConfig.model_validate({"chat": {name: "stale value"}})


def test_upgrade_raw_config_strips_legacy_base_suffix_chat_prompt_keys() -> None:
    """A persisted config that still carries the removed base+suffix keys must load
    cleanly through the upgrade path, which strips them (no ValidationError)."""
    raw = {
        "chat": {
            "system_prompt_base": "You are a helpful assistant.",
            "system_prompt_rag_suffix": " Answer using the provided information.",
            "system_prompt_recall_suffix": " You have conversation history.",
            "system_prompt_direct": "Kept: a live state prompt.",
        }
    }

    cfg, changed, migrated = _upgrade_raw_config(raw)

    assert changed is True
    migrated_set = set(migrated)
    for name in LEGACY_CHAT_PROMPT_FIELDS:
        assert f"chat.{name}" in migrated_set
        assert not hasattr(cfg.chat, name)
    # The surviving state prompt is preserved through the migration.
    assert cfg.chat.system_prompt_direct == "Kept: a live state prompt."
