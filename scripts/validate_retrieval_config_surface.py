#!/usr/bin/env python3
"""Validate Retrieval UI config-surface coverage against Pydantic."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, Iterable, get_args, get_origin

REQUIRED_SECTIONS: tuple[str, ...] = (
    "retrieval",
    "vector_search",
    "sparse_search",
    "graph_search",
    "fusion",
    "scoring",
    "layer_bonus",
    "generation",
    "tracing",
    "hydration",
    "semantic_cache",
)

USE_CONFIG_FIELD_RE = re.compile(r"useConfigField(?:<[^()]*>)?\(\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
MIRROR_SETTER_REQUIREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("setUnifiedBm25K1", ("setSparseBm25K1", "setRetrievalBm25K1")),
    ("setUnifiedBm25B", ("setSparseBm25B", "setRetrievalBm25B")),
    ("setUnifiedHydrationMode", ("setHydrationMode", "setRetrievalHydrationMode")),
    ("setUnifiedHydrationMaxChars", ("setHydrationMaxChars", "setRetrievalHydrationMaxChars")),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_model_candidates(annotation: Any) -> Iterable[Any]:
    yield annotation
    origin = get_origin(annotation)
    if origin is None:
        return
    for arg in get_args(annotation):
        yield from _iter_model_candidates(arg)


def _resolve_model_fields(annotation: Any) -> dict[str, Any] | None:
    seen: set[int] = set()
    for candidate in _iter_model_candidates(annotation):
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        fields = getattr(candidate, "model_fields", None)
        if isinstance(fields, dict):
            return fields
    return None


def _required_keys() -> tuple[set[str], list[str]]:
    from server.models.tribrid_config_model import TriBridConfig

    errors: list[str] = []
    required: set[str] = set()

    for section in REQUIRED_SECTIONS:
        top_field = TriBridConfig.model_fields.get(section)
        if top_field is None:
            errors.append(f"Missing section in TriBridConfig: {section}")
            continue

        nested_fields = _resolve_model_fields(top_field.annotation)
        if not nested_fields:
            errors.append(f"Could not resolve Pydantic fields for section: {section}")
            continue

        for field_name in nested_fields:
            required.add(f"{section}.{field_name}")

    return required, errors


def _collect_ui_bindings() -> tuple[set[str], list[str]]:
    root = _repo_root()
    files = (
        root / "web" / "src" / "components" / "RAG" / "RetrievalSubtab.tsx",
        root / "web" / "src" / "components" / "RAG" / "IntentMatrixEditor.tsx",
    )

    errors: list[str] = []
    bindings: set[str] = set()

    for file_path in files:
        if not file_path.exists():
            errors.append(f"Required UI file is missing: {file_path.relative_to(root)}")
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"Failed to read {file_path.relative_to(root)}: {exc}")
            continue
        bindings.update(USE_CONFIG_FIELD_RE.findall(content))

    return bindings, errors


def _collect_control_plane_bindings() -> tuple[set[str], list[str]]:
    try:
        from server.config_control_plane import build_config_field_descriptors
    except Exception as exc:
        return set(), [f"Failed to load config control plane descriptors: {exc}"]
    return {descriptor.path for descriptor in build_config_field_descriptors()}, []


def _validate_component_extensions() -> list[str]:
    root = _repo_root()
    rag_dir = root / "web" / "src" / "components" / "RAG"
    errors: list[str] = []

    required_tsx = (
        rag_dir / "RetrievalSubtab.tsx",
        rag_dir / "IntentMatrixEditor.tsx",
    )
    for file_path in required_tsx:
        if not file_path.exists():
            errors.append(f"Required TSX component is missing: {file_path.relative_to(root)}")

    for stem in ("RetrievalSubtab", "IntentMatrixEditor"):
        for ext in ("js", "jsx"):
            legacy = rag_dir / f"{stem}.{ext}"
            if legacy.exists():
                errors.append(f"Legacy non-TSX component is not allowed: {legacy.relative_to(root)}")

    return errors


def _validate_mirrored_pair_setters() -> list[str]:
    root = _repo_root()
    retrieval_path = root / "web" / "src" / "components" / "RAG" / "RetrievalSubtab.tsx"
    if not retrieval_path.exists():
        return [f"Required UI file is missing: {retrieval_path.relative_to(root)}"]

    try:
        content = retrieval_path.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"Failed to read {retrieval_path.relative_to(root)}: {exc}"]

    errors: list[str] = []
    for setter_name, required_calls in MIRROR_SETTER_REQUIREMENTS:
        pattern = re.compile(
            rf"const\s+{re.escape(setter_name)}\s*=\s*useCallback\(\s*\(\s*value:[^)]*\)\s*=>\s*\{{(?P<body>.*?)\}}\s*,",
            re.DOTALL,
        )
        match = pattern.search(content)
        if not match:
            errors.append(f"Missing unified mirror setter: {setter_name}")
            continue

        body = match.group("body")
        for required_call in required_calls:
            if f"{required_call}(value)" not in body:
                errors.append(
                    f"Unified mirror setter {setter_name} must call {required_call}(value) for compatibility."
                )

    return errors


def validate_retrieval_config_surface() -> list[str]:
    errors: list[str] = []

    required, required_errors = _required_keys()
    errors.extend(required_errors)

    bindings, binding_errors = _collect_ui_bindings()
    errors.extend(binding_errors)
    control_plane_bindings, control_plane_errors = _collect_control_plane_bindings()
    errors.extend(control_plane_errors)

    target_prefixes = {f"{section}." for section in REQUIRED_SECTIONS}
    scoped_bindings = {k for k in bindings if any(k.startswith(prefix) for prefix in target_prefixes)}
    scoped_bindings.update({k for k in control_plane_bindings if any(k.startswith(prefix) for prefix in target_prefixes)})

    missing = sorted(required - scoped_bindings)
    unknown = sorted(scoped_bindings - required)

    for key in missing:
        errors.append(f"Missing Retrieval UI binding: {key}")
    for key in unknown:
        errors.append(f"Unknown Retrieval UI binding (not in Pydantic): {key}")

    errors.extend(_validate_component_extensions())
    errors.extend(_validate_mirrored_pair_setters())

    return errors


def main() -> int:
    errors = validate_retrieval_config_surface()
    if errors:
        print("✗ Retrieval config surface validation failed")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("✓ Retrieval config surface is in sync with Pydantic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
