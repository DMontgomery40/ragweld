from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.refresh_models_catalog import (
    AUTO_PRICING_TIERED,
    AUTO_PRICING_UNKNOWN,
    OPENROUTER_SOURCE_PREFIX,
    RefreshStats,
    build_gateway_row,
    build_refreshed_catalog,
    normalize_openrouter_rows,
    serialize_catalog,
    write_catalog_files,
)
from server.gateway_catalog import GatewayCatalogError


def test_refresh_removes_the_entire_blocked_family_and_keeps_unrelated_fours() -> None:
    blocked = ["openai/gpt-4", "openai/gpt-4-turbo", "openai/gpt-4o-mini",
               "openai/gpt-4o-2024-08-06", "openai/gpt-4.1-nano:batch"]
    allowed = ["openai/gpt-5.6-luna", "anthropic/claude-sonnet-4.5", "meta-llama/llama-4-maverick"]
    normalized = normalize_openrouter_rows([_feed_row(model) for model in blocked + allowed])
    assert set(normalized) == set(allowed)


def _feed_row(
    model_id: str,
    *,
    prompt: str | None = "0.000001",
    completion: str | None = "0.000002",
    context: int | None = 128_000,
    name: str | None = None,
    output_modalities: list[str] | None = None,
    input_modalities: list[str] | None = None,
) -> dict[str, Any]:
    pricing: dict[str, str] = {}
    if prompt is not None:
        pricing["prompt"] = prompt
    if completion is not None:
        pricing["completion"] = completion
    row: dict[str, Any] = {
        "id": model_id,
        "name": name or f"Name {model_id}",
        "pricing": pricing,
        "architecture": {
            "output_modalities": output_modalities if output_modalities is not None else ["text"],
            "input_modalities": input_modalities if input_modalities is not None else ["text"],
        },
    }
    if context is not None:
        row["context_length"] = context
    return row


def _local_row() -> dict[str, Any]:
    return {
        "provider": "ragweld",
        "family": "Qwen3.8-27B",
        "model": "mlx-community/Qwen3.8-27B-4bit",
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 32768,
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "base_url": "http://host.docker.internal:58080/v1",
        "gateway_alias": "ragweld-local",
        "gateway_upstream": "openai/ragweld-local",
    }


def _embedding_row() -> dict[str, Any]:
    return {
        "provider": "openai",
        "family": "text-embedding-3",
        "model": "text-embedding-3-small",
        "components": ["EMB"],
        "unit": "1k_tokens",
        "embed_per_1k": 0.00002,
        "dimensions": 1536,
        "base_url": "https://api.openai.com/v1",
    }


def _rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    rows = catalog.get("models")
    assert isinstance(rows, list)
    return [row for row in rows if isinstance(row, dict)]


def _find(catalog: dict[str, Any], model: str) -> dict[str, Any]:
    for row in _rows(catalog):
        if row.get("model") == model:
            return row
    raise AssertionError(f"missing model row: {model}")


def test_normalize_keeps_every_text_route_including_variants_and_counts_every_skip() -> None:
    stats = RefreshStats()
    normalized = normalize_openrouter_rows(
        [
            _feed_row("openai/gpt-5.4-mini", input_modalities=["text", "image"]),
            _feed_row("qwen/qwen3-coder:free", prompt="0", completion="0"),
            _feed_row("openai/gpt-5.4-mini", name="duplicate row"),
            _feed_row("~openai/gpt-latest"),
            _feed_row("openrouter/auto"),
            _feed_row("openrouter/free"),
            _feed_row("google/imagen-5", output_modalities=["image"]),
            _feed_row("broken/no-context", context=None),
            {"id": "not-a-route"},
            {"id": "openai/"},
        ],
        stats,
    )

    assert sorted(normalized) == ["openai/gpt-5.4-mini", "qwen/qwen3-coder:free"]
    assert normalized["openai/gpt-5.4-mini"].display_name == "Name openai/gpt-5.4-mini", "first row wins"
    assert normalized["openai/gpt-5.4-mini"].supports_vision is True
    assert normalized["openai/gpt-5.4-mini"].input_per_1k == 0.001
    assert normalized["openai/gpt-5.4-mini"].output_per_1k == 0.002
    assert normalized["qwen/qwen3-coder:free"].supports_vision is False
    assert normalized["qwen/qwen3-coder:free"].has_full_pricing is True
    assert stats.skipped_rolling_pointer == 1
    assert stats.skipped_router == 2
    assert stats.duplicate_feed_ids == 1
    assert stats.skipped_malformed_id == 2
    assert stats.skipped_non_text == 1
    assert stats.skipped_missing_context == 1
    assert stats.normalized_feed_rows == 2
    accounted = (
        stats.normalized_feed_rows
        + stats.skipped_rolling_pointer
        + stats.skipped_router
        + stats.duplicate_feed_ids
        + stats.skipped_malformed_id
        + stats.skipped_non_text
        + stats.skipped_missing_context
        + stats.skipped_invalid_alias
    )
    assert accounted == 10, "every feed row is either normalized or counted as a skip"


def test_tiered_feed_pricing_is_flagged_not_flattened_silently() -> None:
    stats = RefreshStats()
    row = _feed_row("x-ai/grok-4.6", prompt="0.000002", completion="0.000006")
    row["pricing"]["overrides"] = [{"min_prompt_tokens": 200000, "prompt": "0.000004", "completion": "0.000012"}]
    feed = normalize_openrouter_rows([row], stats)["x-ai/grok-4.6"]

    assert feed.pricing_tiered is True
    assert stats.rows_pricing_tiered == 1
    built = build_gateway_row(feed)
    assert built["input_per_1k"] == 0.002 and built["output_per_1k"] == 0.006
    assert built["notes"] == AUTO_PRICING_TIERED


def test_feed_ids_with_uppercase_get_lowercase_aliases() -> None:
    feed = normalize_openrouter_rows([_feed_row("Qwen/Qwen3-4B")])["Qwen/Qwen3-4B"]
    built = build_gateway_row(feed)
    assert built["gateway_alias"] == "qwen.qwen3-4b"
    assert built["provider"] == "qwen"
    assert built["gateway_upstream"] == "openrouter/Qwen/Qwen3-4B"


def test_gateway_row_carries_alias_upstream_pricing_and_vision() -> None:
    feed = normalize_openrouter_rows([_feed_row("anthropic/claude-sonnet-4.5", name="Anthropic: Claude Sonnet 4.5")])
    row = build_gateway_row(feed["anthropic/claude-sonnet-4.5"])

    assert row == {
        "provider": "anthropic",
        "family": "claude-sonnet-4.5",
        "model": "anthropic/claude-sonnet-4.5",
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": 128_000,
        "input_per_1k": 0.001,
        "output_per_1k": 0.002,
        "base_url": "https://openrouter.ai/api/v1",
        "display_name": "Anthropic: Claude Sonnet 4.5",
        "gateway_alias": "anthropic.claude-sonnet-4.5",
        "gateway_upstream": "openrouter/anthropic/claude-sonnet-4.5",
        "supports_vision": False,
    }


def test_gateway_row_marks_missing_pricing_instead_of_inventing_it() -> None:
    feed = normalize_openrouter_rows([_feed_row("perplexity/sonar-deep-research", prompt="-1", completion="-1")])
    row = build_gateway_row(feed["perplexity/sonar-deep-research"])

    assert "input_per_1k" not in row and "output_per_1k" not in row
    assert row["notes"] == AUTO_PRICING_UNKNOWN


def test_refresh_replaces_provider_direct_generation_rows_and_preserves_embedding_and_local_rows() -> None:
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
                "base_url": "https://api.openai.com/v1",
            },
            {
                "provider": "ollama",
                "family": "llama3.2",
                "model": "llama3.2:3b",
                "components": ["GEN"],
                "unit": "1k_tokens",
                "input_per_1k": 0.0,
                "output_per_1k": 0.0,
                "context": 8192,
            },
            _embedding_row(),
            _local_row(),
        ],
    }

    merged, stats, changed = build_refreshed_catalog(
        catalog,
        [_feed_row("openai/gpt-5.4-mini"), _feed_row("openai/gpt-4.1")],
        as_of_date="2026-08-22",
    )

    assert changed is True
    models = [(row["provider"], row["model"]) for row in _rows(merged)]
    assert models == [
        ("openai", "openai/gpt-5.4-mini"),
        ("openai", "text-embedding-3-small"),
        ("ragweld", "mlx-community/Qwen3.8-27B-4bit"),
    ]
    assert all("gpt-4" not in row["model"] for row in _rows(merged))
    assert _find(merged, "text-embedding-3-small") == {
        **_embedding_row(),
        "selection_roles": ["embedding_provider"],
        "selection_status": "runtime_selectable",
        "selection_reason": None,
    }
    assert _find(merged, "mlx-community/Qwen3.8-27B-4bit")["gateway_alias"] == "ragweld-local"
    assert stats.removed_rows == 2
    assert stats.added_rows == 1
    assert stats.preserved_rows == 2
    assert stats.gateway_rows == 1
    assert merged["last_updated"] == "2026-08-22"
    assert merged["sources"] == [f"{OPENROUTER_SOURCE_PREFIX} (2026-08-22)"]


def test_refresh_removes_routes_that_left_the_feed_and_is_idempotent() -> None:
    base = {"currency": "USD", "sources": [], "models": [_local_row(), _embedding_row()]}
    first, _stats, changed_first = build_refreshed_catalog(
        base,
        [_feed_row("openai/gpt-5.4-mini"), _feed_row("deepseek/deepseek-v4")],
        as_of_date="2026-08-22",
    )
    assert changed_first is True
    assert {row["model"] for row in _rows(first) if row.get("gateway_upstream", "").startswith("openrouter/")} == {
        "openai/gpt-5.4-mini",
        "deepseek/deepseek-v4",
    }

    second, stats, changed_second = build_refreshed_catalog(
        first,
        [_feed_row("openai/gpt-5.4-mini")],
        as_of_date="2026-08-23",
    )
    assert changed_second is True
    assert stats.removed_rows == 1
    assert stats.added_rows == 0
    assert [row["model"] for row in _rows(second) if row.get("components") == ["GEN"]] == [
        "openai/gpt-5.4-mini",
        "mlx-community/Qwen3.8-27B-4bit",
    ]

    third, _stats, changed_third = build_refreshed_catalog(
        second,
        [_feed_row("openai/gpt-5.4-mini")],
        as_of_date="2026-08-24",
    )
    assert changed_third is False
    assert third["last_updated"] == second["last_updated"]
    assert third["sources"] == second["sources"]


def test_refresh_fails_closed_without_the_local_serving_row() -> None:
    with pytest.raises(GatewayCatalogError, match="ragweld-local"):
        build_refreshed_catalog(
            {"currency": "USD", "sources": [], "models": [_embedding_row()]},
            [_feed_row("openai/gpt-5.4-mini")],
            as_of_date="2026-08-22",
        )


def test_write_catalog_files_writes_catalog_mirror_and_gateway_config_together(tmp_path: Path) -> None:
    merged, _stats, _changed = build_refreshed_catalog(
        {"currency": "USD", "sources": [], "models": [_local_row()]},
        [_feed_row("openai/gpt-5.4-mini")],
        as_of_date="2026-08-22",
    )
    canonical = tmp_path / "data" / "models.json"
    mirror = tmp_path / "web" / "public" / "models.json"
    gateway = tmp_path / "infra" / "litellm-config.yaml"

    write_catalog_files(canonical, mirror, merged, litellm_config_path=gateway)

    assert canonical.read_text(encoding="utf-8") == serialize_catalog(merged)
    assert mirror.read_text(encoding="utf-8") == serialize_catalog(merged)
    model_list = yaml.safe_load(gateway.read_text(encoding="utf-8"))["model_list"]
    assert [row["model_name"] for row in model_list] == ["ragweld-local", "openai.gpt-5.4-mini"]
    assert model_list[1]["litellm_params"] == {
        "model": "openrouter/openai/gpt-5.4-mini",
        "api_key": "os.environ/OPENROUTER_API_KEY",
        "num_retries": 0,
        "max_retries": 0,
    }
    assert all(
        row["litellm_params"]["num_retries"] == row["litellm_params"]["max_retries"] == 0
        for row in model_list
    )
