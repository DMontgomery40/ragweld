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
    created: int = 1_765_000_000,
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
        "created": created,
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
    assert row["selection_roles"] == ["generation"]
    assert row["selection_status"] == "runtime_selectable"
    assert row["selection_reason"] is None


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
    refreshed_voyage = _find_model(refreshed, provider="voyage", model="voyage-3-large")
    for key, value in voyage_row.items():
        assert refreshed_voyage[key] == value
    assert refreshed_voyage["selection_roles"] == []
    assert refreshed_voyage["selection_status"] == "catalog_only"
    assert "Provider-backed embeddings currently execute only via" in refreshed_voyage["selection_reason"]


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


def test_existing_snapshot_is_replaced_by_latest_family_variant() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [
            {
                "provider": "openai",
                "family": "gpt-4o-2024-08-06",
                "model": "gpt-4o-2024-08-06",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.003,
                "output_per_1k": 0.012,
                "context": 128_000,
            }
        ],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-4o-2024-08-06",
            prompt="0.0000025",
            completion="0.00001",
            context=128_000,
            created=1_722_975_600,
        ),
        _text_feed_row(
            "openai/gpt-4o-2024-11-20",
            prompt="0.0000025",
            completion="0.00001",
            context=128_000,
            created=1_732_127_594,
        ),
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    replacement = _find_model(refreshed, provider="openai", model="gpt-4o-2024-11-20")
    assert replacement["family"] == "gpt-4o-2024-11-20"
    assert replacement["input_per_1k"] == 0.0025
    assert replacement["output_per_1k"] == 0.01
    models = refreshed.get("models")
    assert isinstance(models, list)
    assert sum(1 for row in models if isinstance(row, dict) and row.get("provider") == "openai") == 1


def test_brand_new_old_family_is_not_auto_added() -> None:
    catalog = {"currency": "USD", "last_updated": "2026-02-01", "sources": [], "models": []}
    feed_rows = [
        _text_feed_row(
            "openai/gpt-legacy-2024-01-10",
            prompt="0.000001",
            completion="0.000004",
            context=128_000,
            created=1_704_844_800,  # 2024-01-10
        ),
        _text_feed_row(
            "openai/gpt-fresh-2026-02-20",
            prompt="0.0000015",
            completion="0.000006",
            context=256_000,
            created=1_771_545_600,  # 2026-02-20
        ),
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-26")
    assert changed is True
    _find_model(refreshed, provider="openai", model="gpt-fresh-2026-02-20")
    models = refreshed.get("models")
    assert isinstance(models, list)
    assert all(
        not (
            isinstance(row, dict)
            and str(row.get("provider") or "").strip().lower() == "openai"
            and str(row.get("model") or "").strip() == "gpt-legacy-2024-01-10"
        )
        for row in models
    )


def test_existing_version_line_moves_to_latest_model_in_same_family() -> None:
    catalog = {
        "currency": "USD",
        "last_updated": "2026-02-01",
        "sources": [f"{OPENROUTER_SOURCE_PREFIX} (2026-02-01)"],
        "models": [
            {
                "provider": "openai",
                "family": "gpt-5.1-codex",
                "model": "gpt-5.1-codex",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.00125,
                "output_per_1k": 0.01,
                "context": 400_000,
            }
        ],
    }
    feed_rows = [
        _text_feed_row(
            "openai/gpt-5.1-codex",
            prompt="0.00000125",
            completion="0.00001",
            context=400_000,
            created=1_763_060_298,
        ),
        _text_feed_row(
            "openai/gpt-5.2-codex",
            prompt="0.00000175",
            completion="0.000014",
            context=400_000,
            created=1_768_409_315,
        ),
        _text_feed_row(
            "openai/gpt-5.3-codex",
            prompt="0.00000175",
            completion="0.000014",
            context=400_000,
            created=1_771_959_164,
        ),
    ]

    refreshed, _stats, changed = build_refreshed_catalog(catalog, feed_rows, as_of_date="2026-02-27")
    assert changed is True
    latest = _find_model(refreshed, provider="openai", model="gpt-5.3-codex")
    assert latest["family"] == "gpt-5.3-codex"
    assert latest["input_per_1k"] == 0.00175
    assert latest["output_per_1k"] == 0.014
    models = refreshed.get("models")
    assert isinstance(models, list)
    assert sum(1 for row in models if isinstance(row, dict) and row.get("provider") == "openai") == 1
