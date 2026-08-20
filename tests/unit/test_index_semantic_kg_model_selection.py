from __future__ import annotations

import pytest

from server.api.index import (
    _semantic_kg_catalog_row,
    _semantic_kg_catalog_rows,
    _semantic_kg_model_override,
)
from server.models.tribrid_config_model import TriBridConfig


def test_semantic_kg_catalog_rows_require_runtime_selectable_generation_metadata() -> None:
    rows = _semantic_kg_catalog_rows()
    assert rows
    for row in rows:
        provider = str(row.get("provider") or "").strip().lower()
        model = str(row.get("model") or "").strip()
        assert "GEN" in row.get("components", [])
        assert row.get("selection_status") == "runtime_selectable"
        assert "generation" in row.get("selection_roles", [])
        assert (provider, model) != ("openai", "gpt-5")


def test_semantic_kg_model_override_requires_explicit_catalog_selection() -> None:
    cfg = TriBridConfig()

    with pytest.raises(ValueError, match="Select a runtime-selectable GEN catalog model"):
        _semantic_kg_model_override(cfg)


def test_semantic_kg_model_override_accepts_runtime_selectable_catalog_entries() -> None:
    selectable = _semantic_kg_catalog_rows()
    assert selectable
    expected = selectable[0]
    provider = str(expected.get("provider") or "").strip()
    model = str(expected.get("model") or "").strip()

    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = f"{provider}/{model}"

    assert _semantic_kg_model_override(cfg) == f"{provider}/{model}"
    row = _semantic_kg_catalog_row(cfg)
    assert str(row.get("provider") or "").strip() == provider
    assert str(row.get("model") or "").strip() == model


def test_semantic_kg_model_override_rejects_plain_openai_gpt5() -> None:
    cfg = TriBridConfig()
    cfg.graph_indexing.semantic_kg_llm_model = "openai/gpt-5"

    with pytest.raises(ValueError, match="plain openai/gpt-5"):
        _semantic_kg_model_override(cfg)
