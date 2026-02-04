#!/usr/bin/env python3
"""
Print the configured Codex CLI model from ~/.codex/config.toml.

This is intentionally simple and machine-readable (prints just the model string).
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    config_path = Path("~/.codex/config.toml").expanduser()
    if not config_path.exists():
        print("")
        return

    try:
        import tomllib  # py>=3.11
    except Exception:
        print("")
        return

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        print("")
        return

    model = data.get("model", "")
    if model is None:
        model = ""
    print(model)


if __name__ == "__main__":
    main()

