#!/usr/bin/env python3
"""Enforce config reality coverage for TriBridConfig."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from server.models.tribrid_config_model import TriBridConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = PROJECT_ROOT / "spec" / "config_reality_map.json"
VALID_DISPOSITIONS = {"runtime_effect", "ui_effect", "remove"}


def _unwrap_model_type(annotation: Any) -> type[BaseModel] | None:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    for arg in get_args(annotation):
        model = _unwrap_model_type(arg)
        if model is not None:
            return model
    return None


def iter_leaf_keys(model_type: type[BaseModel], prefix: str = "") -> list[str]:
    leaves: list[str] = []
    for name, field in model_type.model_fields.items():
        dotted = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
        nested = _unwrap_model_type(field.annotation)
        if nested is not None:
            leaves.extend(iter_leaf_keys(nested, dotted))
            continue
        leaves.append(dotted)
    return sorted(leaves)


def load_reality_map(path: Path = MAP_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("config_reality_map.json must be a JSON object")
    return raw


def _resolve_entry(key: str, mapping: dict[str, Any]) -> dict[str, Any] | None:
    overrides = mapping.get("overrides") or {}
    if isinstance(overrides, dict) and key in overrides and isinstance(overrides[key], dict):
        return dict(overrides[key])

    section = key.split(".", 1)[0]
    sections = mapping.get("sections") or {}
    if isinstance(sections, dict) and section in sections and isinstance(sections[section], dict):
        return dict(sections[section])
    return None


def validate_reality_map(mapping: dict[str, Any], leaves: list[str]) -> list[str]:
    errors: list[str] = []

    for key in leaves:
        entry = _resolve_entry(key, mapping)
        if entry is None:
            errors.append(f"Missing mapping for leaf key: {key}")
            continue
        disposition = str(entry.get("disposition") or "").strip()
        if disposition not in VALID_DISPOSITIONS:
            errors.append(f"Invalid disposition for {key}: {disposition!r}")
            continue
        if disposition == "runtime_effect":
            evidence = entry.get("evidence")
            if not isinstance(evidence, list) or not any(str(x).strip() for x in evidence):
                errors.append(f"runtime_effect key is missing evidence: {key}")

    legacy_removed = mapping.get("legacy_removed") or {}
    if isinstance(legacy_removed, dict):
        for key, entry in legacy_removed.items():
            if key in leaves:
                errors.append(f"legacy_removed key still exists in TriBridConfig: {key}")
            if not isinstance(entry, dict):
                errors.append(f"legacy_removed entry must be object: {key}")
                continue
            disposition = str(entry.get("disposition") or "").strip()
            if disposition != "remove":
                errors.append(f"legacy_removed entry must use disposition=remove: {key}")

    return errors


def main() -> int:
    if not MAP_PATH.exists():
        print(f"ERROR: missing map file: {MAP_PATH}")
        return 1
    leaves = iter_leaf_keys(TriBridConfig)
    mapping = load_reality_map(MAP_PATH)
    errors = validate_reality_map(mapping, leaves)
    if errors:
        print("Config reality check failed:")
        for err in errors:
            print(f"  - {err}")
        return 1
    print(f"Config reality check passed ({len(leaves)} leaf keys covered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
