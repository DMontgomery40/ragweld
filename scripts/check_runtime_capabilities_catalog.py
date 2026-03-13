#!/usr/bin/env python3
"""Validate that models.json selection metadata matches the runtime capability rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from server.runtime_capabilities import validate_catalog_selection_metadata

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "data" / "models.json"


def main() -> int:
    if not CATALOG_PATH.exists():
        print(f"ERROR: missing catalog file: {CATALOG_PATH}")
        return 1

    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    rows = raw.get("models")
    if not isinstance(rows, list):
        print("ERROR: models.json must contain a top-level 'models' list")
        return 1

    models = [row for row in rows if isinstance(row, dict)]
    errors = validate_catalog_selection_metadata(models)
    if errors:
        print("Runtime capability catalog check failed:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Runtime capability catalog check passed ({len(models)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
