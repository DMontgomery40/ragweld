#!/usr/bin/env python3
"""Refresh the generation rows of data/models.json from the OpenRouter models feed.

Every text-output model OpenRouter serves becomes one GEN catalog row routed
through the LiteLLM gateway (``gateway_alias`` + ``gateway_upstream``). Rows
that leave the feed are removed. Embedding/reranker rows and the ``ragweld``
vLLM serving row are never touched. ``--apply`` writes the catalog, its web
mirror, and the generated infra/litellm-config.yaml together so the gateway and
the catalog cannot drift.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from server.gateway_catalog import (
    CATALOG_PATH,
    LITELLM_CONFIG_PATH,
    LOCAL_GATEWAY_PROVIDER,
    OPENROUTER_BASE_URL,
    OPENROUTER_UPSTREAM_PREFIX,
    WEB_CATALOG_PATH,
    GatewayCatalogError,
    gateway_alias_for_openrouter_id,
    gateway_rows,
    load_catalog,
    serialize_catalog,
    write_catalog_trio,
)
from server.model_policy import ensure_model_allowed
from server.runtime_capabilities import apply_selection_metadata_to_catalog

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_SOURCE_PREFIX = "https://openrouter.ai/api/v1/models"
AUTO_PRICING_UNKNOWN = "[auto-refresh] pricing_unknown=true"
AUTO_PRICING_TIERED = "[auto-refresh] pricing_tiered=true"
ROLLING_POINTER_PREFIX = "~"
ROUTER_PROVIDER = "openrouter"  # openrouter/auto etc. pick another model at request time

_OPENAI_NUMBERED_GPT_RE = re.compile(
    r"^openai/gpt-(?P<version>\d+(?:\.\d+)*)(?P<suffix>(?:[-:].*)?)$",
    re.IGNORECASE,
)
_ANTHROPIC_CURRENT_RE = re.compile(
    r"^anthropic/claude-(?P<family>opus|fable|sonnet|haiku)-(?P<version>\d+(?:\.\d+)*)(?:[-:].*)?$",
    re.IGNORECASE,
)
_ANTHROPIC_LEGACY_RE = re.compile(
    r"^anthropic/claude-(?P<version>\d+(?:\.\d+)*)-(?P<family>opus|fable|sonnet|haiku)(?:[-:].*)?$",
    re.IGNORECASE,
)

_DECIMAL_1K = Decimal("1000")
_DECIMAL_ROUND_12 = Decimal("0.000000000001")


@dataclass(frozen=True)
class FeedModel:
    provider: str
    model_id: str
    display_name: str | None
    context: int
    input_per_1k: float | None
    output_per_1k: float | None
    supports_vision: bool
    pricing_tiered: bool

    @property
    def has_full_pricing(self) -> bool:
        return self.input_per_1k is not None and self.output_per_1k is not None


@dataclass
class RefreshStats:
    total_feed_rows: int = 0
    normalized_feed_rows: int = 0
    skipped_malformed_id: int = 0
    skipped_non_text: int = 0
    skipped_rolling_pointer: int = 0
    skipped_router: int = 0
    skipped_missing_context: int = 0
    skipped_invalid_alias: int = 0
    skipped_blocked_model: int = 0
    skipped_superseded: int = 0
    duplicate_feed_ids: int = 0
    rows_pricing_tiered: int = 0
    previous_gateway_rows: int = 0
    gateway_rows: int = 0
    rows_missing_price: int = 0
    removed_rows: int = 0
    added_rows: int = 0
    preserved_rows: int = 0


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _is_text_output_model(row: dict[str, Any]) -> bool:
    architecture = row.get("architecture")
    if not isinstance(architecture, dict):
        return False
    output_modalities = architecture.get("output_modalities")
    if isinstance(output_modalities, list):
        return any(str(modality or "").strip().lower() == "text" for modality in output_modalities)
    modality = str(architecture.get("modality") or "").strip().lower()
    return bool(modality) and (modality.endswith("->text") or modality == "text")


def _accepts_images(row: dict[str, Any]) -> bool:
    architecture = row.get("architecture")
    if not isinstance(architecture, dict):
        return False
    input_modalities = architecture.get("input_modalities")
    if isinstance(input_modalities, list):
        return any(str(modality or "").strip().lower() == "image" for modality in input_modalities)
    modality = str(architecture.get("modality") or "").strip().lower()
    return "image" in modality.split("->", 1)[0]


def _parse_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_per_1k_pricing(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        per_token = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if per_token < 0:
        return None
    return float((per_token * _DECIMAL_1K).quantize(_DECIMAL_ROUND_12))


def _version_tuple(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in raw.split("."))


def _openai_frontier_version(model_id: str) -> tuple[int, ...] | None:
    """Return the generation for ordinary numbered GPT routes.

    Image and open-weight GPT routes are distinct product families, so a newer
    frontier generation must not remove them from the catalog.
    """

    match = _OPENAI_NUMBERED_GPT_RE.fullmatch(model_id)
    if match is None or match.group("suffix").lower().startswith("-image"):
        return None
    return _version_tuple(match.group("version"))


def _anthropic_family_version(model_id: str) -> tuple[str, tuple[int, ...]] | None:
    for pattern in (_ANTHROPIC_CURRENT_RE, _ANTHROPIC_LEGACY_RE):
        match = pattern.fullmatch(model_id)
        if match is not None:
            return match.group("family").lower(), _version_tuple(match.group("version"))
    return None


def _remove_superseded_versions(normalized: dict[str, FeedModel], stats: RefreshStats) -> None:
    """Drop older OpenAI GPT generations and Claude family versions in place."""

    openai_versions = {
        version
        for model_id in normalized
        if (version := _openai_frontier_version(model_id)) is not None
    }
    latest_openai = max(openai_versions, default=None)

    latest_anthropic: dict[str, tuple[int, ...]] = {}
    for model_id in normalized:
        parsed = _anthropic_family_version(model_id)
        if parsed is None:
            continue
        family, version = parsed
        latest_anthropic[family] = max(version, latest_anthropic.get(family, version))

    superseded: list[str] = []
    for model_id in normalized:
        openai_version = _openai_frontier_version(model_id)
        if openai_version is not None and latest_openai is not None and openai_version < latest_openai:
            superseded.append(model_id)
            continue
        anthropic = _anthropic_family_version(model_id)
        if anthropic is not None:
            family, version = anthropic
            if version < latest_anthropic[family]:
                superseded.append(model_id)

    for model_id in superseded:
        del normalized[model_id]
    stats.skipped_superseded += len(superseded)


def normalize_openrouter_rows(rows: list[dict[str, Any]], stats: RefreshStats | None = None) -> dict[str, FeedModel]:
    """Normalize feed rows into gateway candidates keyed by OpenRouter model id."""

    stats = stats or RefreshStats()
    normalized: dict[str, FeedModel] = {}
    for row in rows:
        model_id = str(row.get("id") or "").strip()
        if model_id.startswith(ROLLING_POINTER_PREFIX):
            stats.skipped_rolling_pointer += 1
            continue
        provider_prefix, separator, slug = model_id.partition("/")
        if not separator or not provider_prefix.strip() or not slug.strip():
            stats.skipped_malformed_id += 1
            continue
        if provider_prefix.strip().lower() == ROUTER_PROVIDER:
            # Meta-routers resolve to a different model per request; the
            # answer's lineage would not name the model that produced it.
            stats.skipped_router += 1
            continue
        try:
            ensure_model_allowed(model_id)
        except ValueError:
            stats.skipped_blocked_model += 1
            continue
        if model_id in normalized:
            stats.duplicate_feed_ids += 1
            continue
        if not _is_text_output_model(row):
            stats.skipped_non_text += 1
            continue
        context = _parse_positive_int(row.get("context_length"))
        if context is None:
            top_provider = row.get("top_provider")
            if isinstance(top_provider, dict):
                context = _parse_positive_int(top_provider.get("context_length"))
        if context is None:
            stats.skipped_missing_context += 1
            continue
        try:
            gateway_alias_for_openrouter_id(model_id)
        except GatewayCatalogError:
            stats.skipped_invalid_alias += 1
            continue

        pricing = row.get("pricing")
        prompt_per_1k = completion_per_1k = None
        pricing_tiered = False
        if isinstance(pricing, dict):
            prompt_per_1k = _parse_per_1k_pricing(pricing.get("prompt"))
            completion_per_1k = _parse_per_1k_pricing(pricing.get("completion"))
            overrides = pricing.get("overrides")
            pricing_tiered = isinstance(overrides, list) and len(overrides) > 0
        if prompt_per_1k is None or completion_per_1k is None:
            prompt_per_1k = completion_per_1k = None
        if pricing_tiered:
            stats.rows_pricing_tiered += 1

        provider, _slug = model_id.split("/", 1)
        display_name = str(row.get("name") or "").strip() or None
        normalized[model_id] = FeedModel(
            provider=provider.strip().lower(),
            model_id=model_id,
            display_name=display_name,
            context=context,
            input_per_1k=prompt_per_1k,
            output_per_1k=completion_per_1k,
            supports_vision=_accepts_images(row),
            pricing_tiered=pricing_tiered,
        )
    _remove_superseded_versions(normalized, stats)
    stats.normalized_feed_rows = len(normalized)
    return normalized


def _catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if not isinstance(models, list):
        return []
    return [dict(row) for row in models if isinstance(row, dict)]


def _components(row: dict[str, Any]) -> set[str]:
    raw = row.get("components")
    if not isinstance(raw, list):
        return set()
    return {str(value or "").strip().upper() for value in raw if str(value or "").strip()}


def _is_openrouter_gateway_row(row: dict[str, Any]) -> bool:
    return str(row.get("gateway_upstream") or "").startswith(OPENROUTER_UPSTREAM_PREFIX)


def _is_generation_only_row(row: dict[str, Any]) -> bool:
    return _components(row) == {"GEN"}


def _preserved_row(row: dict[str, Any]) -> bool:
    """Rows the feed never owns: embeddings, rerankers, and the local vLLM serving row."""

    if str(row.get("provider") or "").strip().lower() == LOCAL_GATEWAY_PROVIDER:
        return True
    return not _is_generation_only_row(row)


def build_gateway_row(feed: FeedModel) -> dict[str, Any]:
    row: dict[str, Any] = {
        "provider": feed.provider,
        "family": feed.model_id.split("/", 1)[1],
        "model": feed.model_id,
        "components": ["GEN"],
        "unit": "1k_tokens",
        "context": feed.context,
    }
    if feed.has_full_pricing:
        row["input_per_1k"] = feed.input_per_1k
        row["output_per_1k"] = feed.output_per_1k
    row["base_url"] = OPENROUTER_BASE_URL
    if feed.display_name:
        row["display_name"] = feed.display_name
    row["gateway_alias"] = gateway_alias_for_openrouter_id(feed.model_id)
    row["gateway_upstream"] = f"{OPENROUTER_UPSTREAM_PREFIX}{feed.model_id}"
    row["supports_vision"] = feed.supports_vision
    notes: list[str] = []
    if not feed.has_full_pricing:
        notes.append(AUTO_PRICING_UNKNOWN)
    if feed.pricing_tiered:
        notes.append(AUTO_PRICING_TIERED)
    if notes:
        row["notes"] = " | ".join(notes)
    return row


def _merge_sources(existing: Any, as_of_date: str, *, refresh_stamp: bool) -> list[str]:
    out: list[str] = []
    existing_openrouter: str | None = None
    if isinstance(existing, list):
        for item in existing:
            source = str(item or "").strip()
            if not source:
                continue
            if source.startswith(OPENROUTER_SOURCE_PREFIX):
                if existing_openrouter is None:
                    existing_openrouter = source
                continue
            out.append(source)
    if refresh_stamp or existing_openrouter is None:
        out.append(f"{OPENROUTER_SOURCE_PREFIX} ({as_of_date})")
    else:
        out.append(existing_openrouter)
    return out


def _catalog_without_last_updated(catalog: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(catalog)
    out.pop("last_updated", None)
    return out


def _refresh_litellm_reranker_rows(
    preserved: list[dict[str, Any]],
    feed_models: dict[str, FeedModel],
) -> list[dict[str, Any]]:
    """Keep the manual listwise reranker route on the retained Luna generation."""

    luna_candidates = [
        feed
        for model_id, feed in feed_models.items()
        if re.fullmatch(r"openai/gpt-[0-9]+(?:\.[0-9]+)*-luna", model_id)
    ]
    luna_reranker_rows = [
        row
        for row in preserved
        if str(row.get("provider") or "").lower() == "litellm"
        and _components(row) == {"RERANK"}
        and re.fullmatch(r"openai\.gpt-[0-9]+(?:\.[0-9]+)*-luna", str(row.get("model") or ""))
    ]
    if not luna_reranker_rows:
        return preserved
    if not luna_candidates:
        retained_aliases = {gateway_alias_for_openrouter_id(model_id) for model_id in feed_models}
        stale_aliases = sorted(
            str(row.get("model") or "")
            for row in luna_reranker_rows
            if str(row.get("model") or "") not in retained_aliases
        )
        if stale_aliases:
            raise RuntimeError(
                "cannot migrate preserved LiteLLM reranker row: no retained OpenAI Luna route; "
                f"stale aliases={stale_aliases}"
            )
        return preserved
    latest_luna = max(
        luna_candidates,
        key=lambda feed: _openai_frontier_version(feed.model_id) or (),
    )
    alias = gateway_alias_for_openrouter_id(latest_luna.model_id)
    family = latest_luna.model_id.split("/", 1)[1]

    refreshed: list[dict[str, Any]] = []
    for original in preserved:
        row = copy.deepcopy(original)
        if original in luna_reranker_rows:
            row.update(
                family=family,
                model=alias,
                context=latest_luna.context,
                display_name=f"LiteLLM gateway: {latest_luna.display_name} (listwise rerank)",
                notes=(
                    f"Listwise reranking through the LiteLLM gateway alias {alias}: one request per query "
                    "carrying the top-N candidate snippets; scores 0-10 in candidate order. "
                    "Billed at the alias' token prices."
                ),
            )
            if latest_luna.has_full_pricing:
                row["input_per_1k"] = latest_luna.input_per_1k
                row["output_per_1k"] = latest_luna.output_per_1k
            else:
                row.pop("input_per_1k", None)
                row.pop("output_per_1k", None)
        refreshed.append(row)
    return refreshed


def production_aliases() -> tuple[str, ...]:
    """The gateway aliases deploy/proxmox/render_config.py assigns to production."""
    from deploy.proxmox.render_config import (
        PRODUCTION_CHAT_MODEL_ALIAS,
        PRODUCTION_MODEL_ALIAS,
        PRODUCTION_VISION_MODEL_ALIAS,
    )

    return (PRODUCTION_MODEL_ALIAS, PRODUCTION_CHAT_MODEL_ALIAS, PRODUCTION_VISION_MODEL_ALIAS)


def build_refreshed_catalog(
    catalog: dict[str, Any],
    feed_rows: list[dict[str, Any]],
    *,
    as_of_date: str,
    required_aliases: tuple[str, ...] = (),
) -> tuple[dict[str, Any], RefreshStats, bool]:
    """Replace every feed-owned GEN row with the current OpenRouter routes.

    A refresh that would drop the route behind a ``required_aliases`` entry fails, as a
    missing Luna reranker route does: a partial new generation (a GPT-7 Luna before a
    GPT-7 Sol) must never publish a gateway config without the aliases production uses.
    """

    stats = RefreshStats(total_feed_rows=len(feed_rows))
    feed_models = normalize_openrouter_rows(feed_rows, stats)

    existing_rows = _catalog_models(catalog)
    preserved = _refresh_litellm_reranker_rows(
        [row for row in existing_rows if _preserved_row(row)],
        feed_models,
    )
    replaced = [row for row in existing_rows if not _preserved_row(row)]
    previous_ids = {str(row.get("model") or "") for row in replaced if _is_openrouter_gateway_row(row)}
    stats.previous_gateway_rows = len(previous_ids)
    stats.preserved_rows = len(preserved)

    gateway_rows_out = [build_gateway_row(feed_models[model_id]) for model_id in sorted(feed_models)]
    current_ids = set(feed_models)
    stats.gateway_rows = len(gateway_rows_out)
    stats.rows_missing_price = sum(1 for row in gateway_rows_out if "input_per_1k" not in row)
    stats.removed_rows = len(replaced) - len(previous_ids & current_ids)
    stats.added_rows = len(current_ids - previous_ids)

    result_rows = preserved + gateway_rows_out
    result_rows.sort(key=lambda item: (str(item.get("provider") or ""), str(item.get("model") or "")))

    merged = copy.deepcopy(catalog)
    merged["currency"] = str(merged.get("currency") or "USD")
    merged["models"] = result_rows
    merged = apply_selection_metadata_to_catalog(merged)
    gateway_rows(merged)  # fail closed on alias collisions or a missing local serving row
    routed = {str(row.get("gateway_alias") or "") for row in merged["models"] if isinstance(row, dict)}
    dropped = sorted(alias for alias in required_aliases if alias not in routed)
    if dropped:
        raise RuntimeError(
            f"refresh would remove routes production still uses: {dropped} "
            "(deploy/proxmox/render_config.py); move those defaults to a retained route in the same change"
        )

    candidate = copy.deepcopy(merged)
    candidate["sources"] = copy.deepcopy(catalog.get("sources", []))
    changed_by_models = _catalog_without_last_updated(candidate) != _catalog_without_last_updated(catalog)
    merged["sources"] = _merge_sources(catalog.get("sources"), as_of_date, refresh_stamp=changed_by_models)
    changed = _catalog_without_last_updated(merged) != _catalog_without_last_updated(catalog)
    if changed:
        merged["last_updated"] = as_of_date
    elif "last_updated" in catalog:
        merged["last_updated"] = catalog["last_updated"]
    else:
        merged.pop("last_updated", None)
    return merged, stats, changed


def fetch_openrouter_rows() -> list[dict[str, Any]]:
    try:
        response = httpx.get(OPENROUTER_MODELS_URL, timeout=30.0)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"failed to fetch {OPENROUTER_MODELS_URL}: {exc}") from exc
    try:
        payload: Any = response.json()
    except Exception as exc:
        raise RuntimeError("failed to parse OpenRouter response as JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("OpenRouter response root must be an object")
    data = payload.get("data")
    if not isinstance(data, list):
        raise RuntimeError("OpenRouter response missing data[]")
    rows = [row for row in data if isinstance(row, dict)]
    if len(rows) != len(data):
        raise RuntimeError("OpenRouter response contained non-object rows in data[]")
    return rows


def write_catalog_files(
    canonical_path: Path,
    mirror_path: Path,
    catalog: dict[str, Any],
    *,
    litellm_config_path: Path,
) -> None:
    """Write catalog, mirror and generated YAML together (validated + rendered first, flock-guarded)."""

    write_catalog_trio(
        catalog,
        canonical_path=canonical_path,
        mirror_path=mirror_path,
        litellm_config_path=litellm_config_path,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write data/models.json, web/public/models.json and infra/litellm-config.yaml.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    as_of_date = _today_iso()

    try:
        current_catalog = load_catalog(CATALOG_PATH)
        feed_rows = fetch_openrouter_rows()
        refreshed_catalog, stats, content_changed = build_refreshed_catalog(
            current_catalog,
            feed_rows,
            as_of_date=as_of_date,
            required_aliases=production_aliases(),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    target_text = serialize_catalog(refreshed_catalog)
    canonical_text = CATALOG_PATH.read_text(encoding="utf-8")
    mirror_text = WEB_CATALOG_PATH.read_text(encoding="utf-8") if WEB_CATALOG_PATH.exists() else ""
    file_changed = canonical_text != target_text or mirror_text != target_text

    for key, value in vars(stats).items():
        print(f"{key}={value}")
    print(f"catalog_content_changed={str(content_changed).lower()}")
    print(f"catalog_files_need_write={str(file_changed).lower()}")

    if not args.apply:
        print("dry_run=true")
        return 0

    write_catalog_files(CATALOG_PATH, WEB_CATALOG_PATH, refreshed_catalog, litellm_config_path=LITELLM_CONFIG_PATH)
    print("apply=true")
    print("result=updated" if file_changed else "result=litellm_config_regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
