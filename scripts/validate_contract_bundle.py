#!/usr/bin/env python3
"""Validate that the checked-in contract bundle matches code truth."""

from __future__ import annotations

import filecmp
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPORT_SCRIPT = PROJECT_ROOT / "scripts" / "export_contract_bundle.py"
BUNDLE_DIR = PROJECT_ROOT / "docs" / "references" / "contract-bundle"
EXPECTED_FILES = (
    "openapi.json",
    "json_schema_bundle.json",
    "surface_target_manifest.json",
)


def main() -> int:
    missing = [name for name in EXPECTED_FILES if not (BUNDLE_DIR / name).exists()]
    if missing:
        print("ERROR: contract bundle is incomplete!")
        for name in missing:
            print(f"  - missing: {BUNDLE_DIR / name}")
        print("")
        print("Run:")
        print("  uv run scripts/export_contract_bundle.py")
        return 2

    with tempfile.TemporaryDirectory(prefix="contract-bundle-") as tmp:
        tmp_dir = Path(tmp)
        result = subprocess.run(
            [sys.executable, str(EXPORT_SCRIPT), "--out-dir", str(tmp_dir)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("ERROR: export_contract_bundle.py failed during validation")
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip())
            return 3

        mismatches = [
            name
            for name in EXPECTED_FILES
            if not filecmp.cmp(BUNDLE_DIR / name, tmp_dir / name, shallow=False)
        ]
        if mismatches:
            print("ERROR: contract bundle is out of sync with code truth!")
            for name in mismatches:
                print(f"  - stale: {BUNDLE_DIR / name}")
            print("")
            print("Run:")
            print("  uv run scripts/export_contract_bundle.py")
            return 1

    print("✓ Contract bundle is in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
