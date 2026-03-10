#!/usr/bin/env python3
"""Fail automation runs when a stop flag is present."""

from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    # A lightweight repo-local stop lever for automation lanes.
    stop_markers = [
        root / "output" / "automation" / "STOP",
        root / "output" / "automation" / "STOP_UI_PROOF",
    ]
    for marker in stop_markers:
        if marker.exists():
            print(f"[automation_stop_gate] blocked by {marker}")
            return 1
    print("[automation_stop_gate] pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
