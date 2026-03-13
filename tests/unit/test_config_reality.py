from __future__ import annotations

from scripts.check_config_reality import (
    MAP_PATH,
    iter_leaf_keys,
    load_reality_map,
    validate_reality_map,
)
from server.models.tribrid_config_model import TriBridConfig
from server.services.config_store import _upgrade_raw_config


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
