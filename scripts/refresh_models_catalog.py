#!/usr/bin/env python3
"""Refresh data/models.json from the OpenRouter machine-readable models feed."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_SOURCE_PREFIX = "https://openrouter.ai/api/v1/models"
AUTO_DEPRECATED_PREFIX = "[auto-refresh] deprecated_on="
AUTO_PRICING_UNKNOWN = "[auto-refresh] pricing_unknown=true"

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = REPO_ROOT / "data" / "models.json"
MIRROR_PATH = REPO_ROOT / "web" / "public" / "models.json"

PROVIDER_ALIASES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "cohere": "cohere",
    "mistral": "mistral",
    "mistralai": "mistral",
    "deepseek": "deepseek",
    "x-ai": "xai",
    "xai": "xai",
}
MANAGED_PROVIDERS = set(PROVIDER_ALIASES.values())
PROVIDER_DEFAULT_BASE_URL = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
    "cohere": "https://api.cohere.ai/v2",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "xai": "https://api.x.ai/v1",
}
NEW_FAMILY_MAX_AGE_DAYS = 180

_DECIMAL_1K = Decimal("1000")
_DECIMAL_ROUND_12 = Decimal("0.000000000001")


@dataclass(frozen=True)
class FeedModel:
    provider: str
    family: str
    model: str
    context: int | None
    input_per_1k: float | None
    output_per_1k: float | None
    created_at: int | None

    @property
    def has_full_pricing(self) -> bool:
        return self.input_per_1k is not None and self.output_per_1k is not None


@dataclass
class RefreshStats:
    total_feed_rows: int = 0
    normalized_feed_rows: int = 0
    managed_existing_rows: int = 0
    updated_existing_rows: int = 0
    newly_deprecated_rows: int = 0
    new_rows: int = 0
    new_rows_missing_price: int = 0


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


def _canonical_provider(provider: Any) -> str | None:
    key = str(provider or "").strip().lower()
    if not key:
        return None
    return PROVIDER_ALIASES.get(key)


def _normalized_components(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for value in raw:
        comp = str(value or "").strip().upper()
        if comp:
            out.append(comp)
    return out


def _is_text_output_model(row: dict[str, Any]) -> bool:
    architecture = row.get("architecture")
    if not isinstance(architecture, dict):
        return False

    output_modalities = architecture.get("output_modalities")
    if isinstance(output_modalities, list):
        for modality in output_modalities:
            if str(modality or "").strip().lower() == "text":
                return True
        return False

    modality = str(architecture.get("modality") or "").strip().lower()
    if not modality:
        return False
    return modality.endswith("->text") or modality == "text"


def _parse_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


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
    per_1k = (per_token * _DECIMAL_1K).quantize(_DECIMAL_ROUND_12)
    return float(per_1k)


def _feed_model_score(model: FeedModel) -> tuple[int, int]:
    return (
        int(model.created_at or 0),
        1 if model.has_full_pricing else 0,
        1 if model.context is not None else 0,
    )


_SNAPSHOT_SUFFIX_RE = re.compile(
    r"(?:-\d{4}-\d{2}-\d{2}|-\d{8}|-\d{2}-\d{4}|-\d{2}-\d{2}|-\d{4})$"
)
_SIZE_TOKEN_RE = re.compile(r"\d+b$|\d+x\d+b$")
_VERSION_TOKEN_RE = re.compile(r"\d+(?:\.\d+)*")


def _model_family(model: str) -> str:
    """Normalize model id to a rolling family key for latest-version selection."""
    cur = str(model or "").strip()
    if not cur:
        return cur
    prev = None
    while cur != prev:
        prev = cur
        cur = _SNAPSHOT_SUFFIX_RE.sub("", cur)
    tokens = [tok for tok in cur.split("-") if tok]
    normalized_tokens: list[str] = []
    for token in tokens:
        lowered = token.strip().lower()
        if not lowered:
            continue
        # Keep size variants distinct (20b, 120b, 8x22b, etc.).
        if _SIZE_TOKEN_RE.fullmatch(lowered):
            normalized_tokens.append(lowered)
            continue
        stripped = _VERSION_TOKEN_RE.sub("", lowered)
        if stripped:
            normalized_tokens.append(stripped)
    if not normalized_tokens:
        return cur.lower()
    return "-".join(normalized_tokens)


def _parse_created_at(value: Any) -> int | None:
    if value is None:
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None


def _is_recent_family_candidate(*, feed: FeedModel, as_of_date: str) -> bool:
    if feed.created_at is None:
        return False
    try:
        as_of = datetime.fromisoformat(str(as_of_date)).date()
    except Exception:
        as_of = datetime.now(UTC).date()
    created_date = datetime.fromtimestamp(feed.created_at, tz=UTC).date()
    age_days = (as_of - created_date).days
    return age_days <= NEW_FAMILY_MAX_AGE_DAYS


def normalize_openrouter_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], FeedModel]:
    """Normalize OpenRouter feed rows into managed provider/family keys."""
    normalized: dict[tuple[str, str], FeedModel] = {}

    for row in rows:
        model_id = str(row.get("id") or "").strip()
        if "/" not in model_id:
            continue

        raw_provider, model_slug = model_id.split("/", 1)
        provider = _canonical_provider(raw_provider)
        if provider is None:
            continue

        model = model_slug.strip()
        if not model:
            continue
        if ":" in model:
            # Skip alias/snapshot suffixes to reduce daily churn.
            continue
        if not _is_text_output_model(row):
            continue

        pricing = row.get("pricing")
        prompt_per_1k = None
        completion_per_1k = None
        if isinstance(pricing, dict):
            prompt_per_1k = _parse_per_1k_pricing(pricing.get("prompt"))
            completion_per_1k = _parse_per_1k_pricing(pricing.get("completion"))
        if prompt_per_1k is None or completion_per_1k is None:
            prompt_per_1k = None
            completion_per_1k = None

        candidate = FeedModel(
            provider=provider,
            family=_model_family(model),
            model=model,
            context=_parse_non_negative_int(row.get("context_length")),
            input_per_1k=prompt_per_1k,
            output_per_1k=completion_per_1k,
            created_at=_parse_created_at(row.get("created")),
        )
        key = (provider, candidate.family)
        existing = normalized.get(key)
        if existing is None or _feed_model_score(candidate) > _feed_model_score(existing):
            normalized[key] = candidate

    return normalized


def _parse_notes(notes: str | None) -> tuple[list[str], str | None, bool]:
    if not notes:
        return [], None, False

    manual_parts: list[str] = []
    deprecated_on: str | None = None
    pricing_unknown = False

    for raw_part in str(notes).split("|"):
        part = raw_part.strip()
        if not part:
            continue
        if part.startswith(AUTO_DEPRECATED_PREFIX):
            maybe_date = part[len(AUTO_DEPRECATED_PREFIX):].strip()
            if maybe_date:
                deprecated_on = maybe_date
            continue
        if part == AUTO_PRICING_UNKNOWN:
            pricing_unknown = True
            continue
        manual_parts.append(part)

    return manual_parts, deprecated_on, pricing_unknown


def _compose_notes(
    manual_parts: list[str], *, deprecated_on: str | None, pricing_unknown: bool
) -> str | None:
    parts = [part.strip() for part in manual_parts if part.strip()]
    if deprecated_on:
        parts.append(f"{AUTO_DEPRECATED_PREFIX}{deprecated_on}")
    if pricing_unknown:
        parts.append(AUTO_PRICING_UNKNOWN)
    if not parts:
        return None
    return " | ".join(parts)


def _set_or_pop(row: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        row.pop(key, None)
        return
    row[key] = value


def _catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if not isinstance(models, list):
        return []
    return [dict(row) for row in models if isinstance(row, dict)]


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


def _build_catalog_core(
    catalog: dict[str, Any],
    feed_models_by_family: dict[tuple[str, str], FeedModel],
    *,
    as_of_date: str,
) -> tuple[dict[str, Any], RefreshStats]:
    stats = RefreshStats(normalized_feed_rows=len(feed_models_by_family))
    existing_rows = _catalog_models(catalog)

    result_rows: list[dict[str, Any]] = []
    seen_feed_families: set[tuple[str, str]] = set()
    emitted_model_keys: set[tuple[str, str]] = set()

    for row in existing_rows:
        provider = _canonical_provider(row.get("provider"))
        model = str(row.get("model") or "").strip()
        components = _normalized_components(row.get("components"))

        if provider is None or provider not in MANAGED_PROVIDERS or "GEN" not in components or not model:
            result_rows.append(row)
            continue

        stats.managed_existing_rows += 1
        family_key = (provider, _model_family(model))
        feed = feed_models_by_family.get(family_key)

        manual_notes, deprecated_on, pricing_unknown = _parse_notes(
            str(row.get("notes")) if row.get("notes") is not None else None
        )

        updated = dict(row)
        updated["provider"] = provider
        updated["model"] = model

        if feed is None:
            final_deprecated_on = deprecated_on or as_of_date
            new_notes = _compose_notes(
                manual_notes,
                deprecated_on=final_deprecated_on,
                pricing_unknown=pricing_unknown,
            )
            _set_or_pop(updated, "notes", new_notes)
            if deprecated_on is None and updated != row:
                stats.newly_deprecated_rows += 1
            result_rows.append(updated)
            continue

        seen_feed_families.add(family_key)

        updated["components"] = ["GEN"]
        updated["model"] = feed.model
        updated["unit"] = "1k_tokens"
        _set_or_pop(updated, "context", feed.context)
        _set_or_pop(updated, "input_per_1k", feed.input_per_1k)
        _set_or_pop(updated, "output_per_1k", feed.output_per_1k)
        _set_or_pop(updated, "base_url", PROVIDER_DEFAULT_BASE_URL.get(provider))

        updated.pop("embed_per_1k", None)
        updated.pop("rerank_per_1k", None)
        updated.pop("per_request", None)

        current_family_value = str(updated.get("family") or "").strip()
        if not current_family_value or current_family_value == model:
            updated["family"] = feed.model

        new_notes = _compose_notes(
            manual_notes,
            deprecated_on=None,
            pricing_unknown=not feed.has_full_pricing,
        )
        _set_or_pop(updated, "notes", new_notes)

        if updated != row:
            stats.updated_existing_rows += 1
        output_key = (provider, str(updated.get("model") or "").strip())
        if output_key in emitted_model_keys:
            continue
        emitted_model_keys.add(output_key)
        result_rows.append(updated)

    for key in sorted(feed_models_by_family.keys()):
        if key in seen_feed_families:
            continue
        provider, _family = key
        feed = feed_models_by_family[key]
        if not _is_recent_family_candidate(feed=feed, as_of_date=as_of_date):
            continue
        model = feed.model
        row = {
            "provider": provider,
            "family": model,
            "model": model,
            "components": ["GEN"],
            "unit": "1k_tokens",
        }
        _set_or_pop(row, "context", feed.context)
        _set_or_pop(row, "input_per_1k", feed.input_per_1k)
        _set_or_pop(row, "output_per_1k", feed.output_per_1k)
        _set_or_pop(row, "base_url", PROVIDER_DEFAULT_BASE_URL.get(provider))

        note_parts = ["Added automatically from OpenRouter feed."]
        row["notes"] = _compose_notes(
            note_parts,
            deprecated_on=None,
            pricing_unknown=not feed.has_full_pricing,
        )

        stats.new_rows += 1
        if not feed.has_full_pricing:
            stats.new_rows_missing_price += 1
        result_rows.append(row)

    result_rows.sort(key=lambda item: (str(item.get("provider") or ""), str(item.get("model") or "")))

    merged = copy.deepcopy(catalog)
    merged["currency"] = str(merged.get("currency") or "USD")
    merged["models"] = result_rows
    return merged, stats


def _catalog_without_last_updated(catalog: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(catalog)
    out.pop("last_updated", None)
    return out


def build_refreshed_catalog(
    catalog: dict[str, Any],
    feed_rows: list[dict[str, Any]],
    *,
    as_of_date: str,
) -> tuple[dict[str, Any], RefreshStats, bool]:
    normalized_by_family = normalize_openrouter_rows(feed_rows)
    merged, stats = _build_catalog_core(catalog, normalized_by_family, as_of_date=as_of_date)
    stats.total_feed_rows = len(feed_rows)

    candidate = copy.deepcopy(merged)
    candidate["sources"] = copy.deepcopy(catalog.get("sources", []))
    changed_by_models = _catalog_without_last_updated(candidate) != _catalog_without_last_updated(catalog)

    merged["sources"] = _merge_sources(
        catalog.get("sources"),
        as_of_date,
        refresh_stamp=changed_by_models,
    )
    changed = _catalog_without_last_updated(merged) != _catalog_without_last_updated(catalog)
    if changed:
        merged["last_updated"] = as_of_date
    else:
        if "last_updated" in catalog:
            merged["last_updated"] = catalog["last_updated"]
        else:
            merged.pop("last_updated", None)

    return merged, stats, changed


def load_catalog(path: Path) -> dict[str, Any]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        data = dict(raw)
        if not isinstance(data.get("models"), list):
            data["models"] = []
        return data
    if isinstance(raw, list):
        return {"currency": "USD", "models": raw}
    raise RuntimeError(f"Expected object/list JSON in {path}, got {type(raw).__name__}")


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


def serialize_catalog(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_catalog_files(canonical_path: Path, mirror_path: Path, catalog: dict[str, Any]) -> None:
    text = serialize_catalog(catalog)
    _atomic_write_text(canonical_path, text)
    _atomic_write_text(mirror_path, text)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write refreshed catalog to data/models.json and web/public/models.json.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    as_of_date = _today_iso()

    try:
        current_catalog = load_catalog(CANONICAL_PATH)
        feed_rows = fetch_openrouter_rows()
        refreshed_catalog, stats, content_changed = build_refreshed_catalog(
            current_catalog,
            feed_rows,
            as_of_date=as_of_date,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    target_text = serialize_catalog(refreshed_catalog)
    canonical_text = CANONICAL_PATH.read_text(encoding="utf-8")
    mirror_text = MIRROR_PATH.read_text(encoding="utf-8") if MIRROR_PATH.exists() else ""
    file_changed = canonical_text != target_text or mirror_text != target_text

    print(f"feed_rows={stats.total_feed_rows}")
    print(f"normalized_rows={stats.normalized_feed_rows}")
    print(f"managed_existing_rows={stats.managed_existing_rows}")
    print(f"updated_existing_rows={stats.updated_existing_rows}")
    print(f"newly_deprecated_rows={stats.newly_deprecated_rows}")
    print(f"new_rows={stats.new_rows}")
    print(f"new_rows_missing_price={stats.new_rows_missing_price}")
    print(f"catalog_content_changed={str(content_changed).lower()}")
    print(f"catalog_files_need_write={str(file_changed).lower()}")

    if not args.apply:
        print("dry_run=true")
        return 0

    if not file_changed:
        print("apply=true")
        print("result=no_changes")
        return 0

    write_catalog_files(CANONICAL_PATH, MIRROR_PATH, refreshed_catalog)
    print("apply=true")
    print("result=updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
