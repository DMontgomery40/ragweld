from __future__ import annotations

import pytest

from server.api.index import (
    _semantic_kg_catalog_row,
    _semantic_kg_catalog_rows,
    _semantic_kg_model_override,
)
from server.models.tribrid_config_model import TriBridConfig


def test_semantic_kg_catalog_rows_exclude_plain_openai_gpt5_but_keep_newer_models() -> None:
    rows = _semantic_kg_catalog_rows()
    catalog_pairs = {
        (str(row.get("provider") or "").strip().lower(), str(row.get("model") or "").strip())
        for row in rows
    }

    assert ("openai", "gpt-5") not in catalog_pairs
    assert ("openai", "gpt-5.4") in catalog_pairs


def test_semantic_kg_model_override_defaults_to_catalog_preferred_model() -> None:
    cfg = TriBridConfig()

    assert _semantic_kg_model_override(cfg) == "openai/gpt-5.4"


def test_semantic_kg_model_override_accepts_runtime_selectable_catalog_entries() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = "anthropic/claude-sonnet-4.6"

    assert _semantic_kg_model_override(cfg) == "anthropic/claude-sonnet-4.6"
    row = _semantic_kg_catalog_row(cfg)
    assert str(row.get("provider") or "").strip().lower() == "anthropic"
    assert str(row.get("model") or "").strip() == "claude-sonnet-4.6"


def test_semantic_kg_model_override_rejects_plain_openai_gpt5() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = "openai/gpt-5"

    with pytest.raises(ValueError, match="plain openai/gpt-5"):
        _semantic_kg_model_override(cfg)
