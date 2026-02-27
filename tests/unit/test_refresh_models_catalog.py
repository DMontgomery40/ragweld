from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.refresh_models_catalog import (
    AUTO_DEPRECATED_PREFIX,
    AUTO_PRICING_UNKNOWN,
    OPENROUTER_SOURCE_PREFIX,
    build_refreshed_catalog,
    serialize_catalog,
    write_catalog_files,
)


def _text_feed_row(
    model_id: str,
    *,
    prompt: str | None,
    completion: str | None,
    context: int,
) -> dict[str, Any]:
    pricing: dict[str, str] = {}
    if prompt is not None:
        pricing["prompt"] = prompt
    if completion is not None:
        pricing["completion"] = completion
    return {
        "id": model_id,
        "context_length": context,
        "pricing": pricing,
        "architecture": {
            "output_modalities": ["text"],
            "modality": "text->text",
        },
    }


def _find_model(catalog: dict[str, Any], *, provider: str, model: str) -> dict[str, Any]:
    rows = catalog.get("models")
    assert isinstance(rows, list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("provider") or "").strip().lower() != provider:
            continue
        if str(row.get("model") or "").strip() != model:
            continue
        return row
    raise AssertionError(f"missing model row: {provider}/{model}")


def test_existing_model_updates_prices_context_and_clears_deprecated_marker() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [
            {
                "provider": "openai",
                "family": "gpt-4.1",
                "model": "gpt-4.1",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.002,
                "output_per_1k": 0.008,
                "context": 1_000_000,
                "base_url": "https://legacy.example/v1",
                "notes": (
                    "Manual note"
                    f" | {AUTO_DEPRECATED_PREFIX}2026-01-31"
                    f" | {AUTO_PRICING_UNKNOWN}"
                ),
            }
        ],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-4.1",
            prompt="0.000003",
            completion="0.000009",
            context=900_000,
        )
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True

    row = _find_model(refreshed, provider="openai", model="gpt-4.1")
    assert row["input_per_1k"] == 0.003
    assert row["output_per_1k"] == 0.009
    assert row["context"] == 900_000
    assert row["base_url"] == "https://api.openai.com/v1"
    assert row["notes"] == "Manual note"

    assert refreshed["last_updated"] == "2026-02-26"
    assert f"{OPENROUTER_SOURCE_PREFIX} (2026-02-26)" in refreshed["sources"]


def test_new_model_with_pricing_is_added_as_gen() -> None:
    catalog = {"currency": "USD", "last_updated": "2026-02-01", "sources": [], "models": []}
    feed_rows = [
        _text_feed_row(
            "openai/gpt-new-hotness",
            prompt="0.000001",
            completion="0.000004",
            context=256_000,
        )
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    row = _find_model(refreshed, provider="openai", model="gpt-new-hotness")
    assert row["components"] == ["GEN"]
    assert row["unit"] == "1k_tokens"
    assert row["input_per_1k"] == 0.001
    assert row["output_per_1k"] == 0.004
    assert row["context"] == 256_000


def test_new_model_missing_pricing_is_added_with_unknown_marker() -> None:
    catalog = {"currency": "USD", "last_updated": "2026-02-01", "sources": [], "models": []}
    feed_rows = [
        _text_feed_row(
            "openai/gpt-without-pricing",
            prompt=None,
            completion=None,
            context=128_000,
        )
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    row = _find_model(refreshed, provider="openai", model="gpt-without-pricing")
    assert "input_per_1k" not in row
    assert "output_per_1k" not in row
    assert AUTO_PRICING_UNKNOWN in str(row.get("notes"))


def test_removed_model_is_marked_deprecated_once_then_stabilizes() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [
            {
                "provider": "anthropic",
                "family": "claude-sonnet-4.5",
                "model": "claude-sonnet-4.5",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.003,
                "output_per_1k": 0.006,
                "context": 400_000,
                "notes": "Manual note",
            }
        ],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-4.1",
            prompt="0.000002",
            completion="0.000008",
            context=1_000_000,
        )
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    removed_row = _find_model(refreshed, provider="anthropic", model="claude-sonnet-4.5")
    assert f"{AUTO_DEPRECATED_PREFIX}2026-02-26" in str(removed_row.get("notes"))

    rerun, _stats2, changed2 = build_refreshed_catalog(refreshed, feed_rows, as_of_date="2026-02-27")
    assert changed2 is False
    removed_row_rerun = _find_model(rerun, provider="anthropic", model="claude-sonnet-4.5")
    assert f"{AUTO_DEPRECATED_PREFIX}2026-02-26" in str(removed_row_rerun.get("notes"))
    assert rerun["last_updated"] == "2026-02-26"
    assert rerun["sources"] == refreshed["sources"]


def test_unmanaged_provider_rows_remain_untouched() -> None:
    voyage_row = {
        "provider": "voyage",
        "family": "voyage-3-large",
        "model": "voyage-3-large",
        "components": ["EMB"],
        "unit": "1k_tokens",
        "embed_per_1k": 0.00018,
        "dimensions": 1024,
        "notes": "manual",
    }
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [voyage_row],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-4.1",
            prompt="0.000002",
            completion="0.000008",
            context=1_000_000,
        )
    ]

    refreshed, _stats, _changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert _find_model(refreshed, provider="voyage", model="voyage-3-large") == voyage_row


def test_colon_suffix_and_non_text_models_are_ignored() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-foo:free",
            prompt="0.000001",
            completion="0.000004",
            context=100_000,
        ),
        {
            "id": "openai/gpt-image-only",
            "context_length": 100_000,
            "pricing": {"prompt": "0.000001", "completion": "0.000004"},
            "architecture": {"output_modalities": ["image"], "modality": "text->image"},
        },
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is False
    assert refreshed["models"] == []


def test_sources_added_once_without_daily_churn_when_catalog_is_unchanged() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [],
        "models": [
            {
                "provider": "openai",
                "family": "gpt-4.1",
                "model": "gpt-4.1",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.002,
                "output_per_1k": 0.008,
                "context": 1_000_000,
                "base_url": "https://api.openai.com/v1",
            }
        ],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-4.1",
            prompt="0.000002",
            completion="0.000008",
            context=1_000_000,
        )
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    assert refreshed["sources"] == [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-26)"]

    rerun, _stats2, changed2 = build_refreshed_catalog(refreshed, feed_rows, as_of_date="2026-02-27")
    assert changed2 is False
    assert rerun["sources"] == [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-26)"]
    assert rerun["last_updated"] == "2026-02-26"


def test_write_catalog_files_makes_canonical_and_mirror_byte_identical(tmp_path: Path) -> None:
    canonical = tmp_path / "models.json"
    mirror = tmp_path / "models-mirror.json"
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-26",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-26)"],
        "models": [],
    }

    write_catalog_files(canonical, mirror, catalog)

    expected = serialize_catalog(catalog)
    assert canonical.read_text(encoding="utf-8") == expected
    assert mirror.read_text(encoding="utf-8") == expected
