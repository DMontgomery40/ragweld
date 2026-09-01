#!/usr/bin/env python3
"""Validate glossary.json structure and frontend copy.

Checks:
- data/glossary.json parses and has expected shape
- keys are unique
- web/public/glossary.json exists and matches data/glossary.json (byte-for-byte)
- every literal <TooltipIcon name="..."> key in web/src exists in the glossary
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED_TERM_FIELDS = {"term", "key", "definition", "category", "related"}


def _fail(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        _fail(f"Failed to parse {path}: {e}")
    raise AssertionError("unreachable")


def _find_tooltipicon_literal_keys(web_src: Path) -> set[str]:
    pattern = re.compile(r'<TooltipIcon\s+[^>]*name="([^"]+)"')
    keys: set[str] = set()
    for tsx in web_src.rglob("*.tsx"):
        text = tsx.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            keys.add(m.group(1))
    return keys


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    data_path = repo_root / "data" / "glossary.json"
    public_path = repo_root / "web" / "public" / "glossary.json"
    web_src = repo_root / "web" / "src"

    if not data_path.exists():
        _fail("data/glossary.json missing")
    if not public_path.exists():
        _fail("web/public/glossary.json missing")

    # Byte-for-byte match so production builds are reproducible.
    if data_path.read_bytes() != public_path.read_bytes():
        _fail("web/public/glossary.json does not match data/glossary.json (run scripts/generate_glossary.py)")

    data = _load_json(data_path)
    if not isinstance(data, dict):
        _fail("data/glossary.json root must be an object")
    terms = data.get("terms")
    if not isinstance(terms, list):
        _fail('data/glossary.json must contain a "terms" array')

    keys: list[str] = []
    for i, term in enumerate(terms):
        if not isinstance(term, dict):
            _fail(f"terms[{i}] must be an object")
        missing = REQUIRED_TERM_FIELDS - set(term.keys())
        if missing:
            _fail(f"terms[{i}] missing required fields: {sorted(missing)}")
        if not isinstance(term.get("key"), str) or not term["key"].strip():
            _fail(f"terms[{i}].key must be a non-empty string")
        keys.append(term["key"])
        if not isinstance(term.get("related"), list):
            _fail(f"terms[{i}].related must be a list")

        # Optional fields should be lists if present.
        if "links" in term and not isinstance(term["links"], list):
            _fail(f"terms[{i}].links must be a list")
        if "badges" in term and not isinstance(term["badges"], list):
            _fail(f"terms[{i}].badges must be a list")

    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        _fail(f"Duplicate glossary keys found: {sorted(dupes)[:20]}")

    # Ensure TooltipIcon literal call sites resolve.
    ui_keys = _find_tooltipicon_literal_keys(web_src)
    missing_ui = sorted(set(ui_keys) - set(keys))
    if missing_ui:
        preview = ", ".join(missing_ui[:25])
        _fail(f"Missing TooltipIcon keys in glossary: {preview}")

    print(f"✓ glossary.json OK ({len(keys)} terms)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
