from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.check_config_reality import (
    MAP_PATH,
    iter_leaf_keys,
    load_reality_map,
    validate_reality_map,
)
from server.config import _strip_removed_keys
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


RETIRED_KG_EXTRACTION_PROMPT = """You are a semantic knowledge graph extractor.

Given one corpus chunk, extract only entities and relations explicitly grounded in that text.

Rules:
- Return ONLY valid JSON (no markdown, no prose).
- Never fabricate entities, aliases, or links.
- Prefer exact surface forms for names (for example full person/organization names when present).
- Do not emit file paths or line numbers as entities.
- Keep output high-signal and deduplicated.

JSON format:
{
  "entities": [
    {"name": "Alex Rivera", "entity_type": "person"},
    {"name": "Northwind Labs", "entity_type": "org"},
    {"name": "Denver", "entity_type": "location"}
  ],
  "relations": [
    {"source": "Alex Rivera", "target": "Northwind Labs", "relation_type": "works_for", "evidence_text": "Alex Rivera works for Northwind Labs.", "confidence": 0.92},
    {"source": "Northwind Labs", "target": "Denver", "relation_type": "located_in", "evidence_text": "Northwind Labs is located in Denver.", "confidence": 0.95}
  ]
}

Allowed entity_type values: person, org, location, event, concept
Allowed relation_type values:
- associated_with
- met_with
- communicated_with
- works_for
- member_of
- founded
- owns
- funded
- participated_in
- located_in
- references
- related_to

Constraints:
- Extract only relations explicitly supported by the chunk text.
- Use canonical, grounded names for source/target (no invented aliases).
- If present, include optional "evidence_text" and "confidence" per relation."""


def test_upgrade_raw_config_replaces_the_retired_kg_extraction_prompt_default() -> None:
    """Every persisted config written before D24 carries the pre-official extraction prompt
    verbatim (the System Prompts page stores the default when nothing was edited). That text
    has no ``{schema}``/``{text}`` placeholders, so the official extractor cannot format it.
    A stored value equal to the retired default is the default, not an operator edit: the
    upgrade drops it so the LAW default applies, and reports the key as migrated.
    """
    raw = {"system_prompts": {"semantic_kg_extraction": RETIRED_KG_EXTRACTION_PROMPT}}
    cfg, changed, migrated = _upgrade_raw_config(raw)
    assert changed is True
    assert "system_prompts.semantic_kg_extraction" in migrated
    assert cfg.system_prompts.semantic_kg_extraction == TriBridConfig().system_prompts.semantic_kg_extraction
    assert "{schema}" in cfg.system_prompts.semantic_kg_extraction


def test_upgrade_raw_config_keeps_an_operator_edited_kg_extraction_prompt() -> None:
    edited = "My rules. {schema} {examples} {text}"
    cfg, _changed, migrated = _upgrade_raw_config(
        {"system_prompts": {"semantic_kg_extraction": edited}}
    )
    assert "system_prompts.semantic_kg_extraction" not in migrated
    assert cfg.system_prompts.semantic_kg_extraction == edited


@pytest.mark.parametrize("version", ["pre_redaction", "pre_grounding"])
@pytest.mark.parametrize("edited", [False, True])
def test_grounding_prompt_upgrade_replaces_only_exact_shipped_defaults(
    version: str, edited: bool,
) -> None:
    historical = (Path(__file__).parents[1] / "fixtures" /
                  f"semantic_kg_extraction_{version}.txt").read_text()
    stored = historical + "\nPreserve the operator's domain terminology." if edited else historical
    raw = {"system_prompts": {"semantic_kg_extraction": stored}}
    cfg, _changed, migrated = _upgrade_raw_config(raw)
    if edited:
        assert "system_prompts.semantic_kg_extraction" not in migrated
        assert cfg.system_prompts.semantic_kg_extraction == stored
    else:
        assert "system_prompts.semantic_kg_extraction" in migrated
        assert cfg.system_prompts.semantic_kg_extraction != stored
        assert cfg.system_prompts.semantic_kg_extraction == TriBridConfig().system_prompts.semantic_kg_extraction
    # The global JSON loader has the same behavior as the corpus config path.
    global_cfg = TriBridConfig.model_validate(_strip_removed_keys(raw))
    assert global_cfg.system_prompts.semantic_kg_extraction == cfg.system_prompts.semantic_kg_extraction
    # Loading the upgraded representation again preserves it without another migration.
    reloaded, _changed, migrated_again = _upgrade_raw_config(cfg.model_dump(mode="json"))
    assert "system_prompts.semantic_kg_extraction" not in migrated_again
    assert reloaded.system_prompts.semantic_kg_extraction == cfg.system_prompts.semantic_kg_extraction


def test_flat_config_loader_drops_the_retired_kg_extraction_prompt_too() -> None:
    """The flat tribrid_config.json loader and the deploy renderer share this normaliser."""
    raw = _strip_removed_keys({"system_prompts": {"semantic_kg_extraction": RETIRED_KG_EXTRACTION_PROMPT}})
    assert "semantic_kg_extraction" not in raw["system_prompts"]
    kept = _strip_removed_keys({"system_prompts": {"semantic_kg_extraction": "edited {schema} {text}"}})
    assert kept["system_prompts"]["semantic_kg_extraction"] == "edited {schema} {text}"


def test_reranker_timeout_default_covers_a_full_cloud_candidate_window() -> None:
    """Task 8 drive observation D15: chat's cloud rerank failed with a gateway ReadTimeout.
    Measured on LXC100 (openai.gpt-4.1-nano, the default 50 candidates x 700 chars): 5.7 to
    10.4 s at idle, 6.3 to 7.1 s beside four concurrent Luna extraction calls, 6.3 to 6.9 s
    under full CPU saturation. Concurrent load added a tenth; the retired 10 s default was
    simply inside the idle spread of the prompt it had to score. The default now leaves
    headroom over the slowest idle call, and a persisted 10 (the retired default, which the
    config page stores verbatim) is migrated the way the retired generation budget was.
    """
    assert TriBridConfig().reranking.reranker_timeout == 30
    cfg, changed, migrated = _upgrade_raw_config({"reranking": {"reranker_timeout": 10}})
    assert changed is True
    assert "reranking.reranker_timeout" in migrated
    assert cfg.reranking.reranker_timeout == 30
    kept, _changed, kept_migrated = _upgrade_raw_config({"reranking": {"reranker_timeout": 12}})
    assert "reranking.reranker_timeout" not in kept_migrated
    assert kept.reranking.reranker_timeout == 12
