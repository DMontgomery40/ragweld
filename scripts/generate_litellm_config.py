#!/usr/bin/env python3
"""Render infra/litellm-config.yaml from data/models.json (generated output, never hand-edited).

Usage:
  uv run python scripts/generate_litellm_config.py          # write the file in place
  uv run python scripts/generate_litellm_config.py --check  # exit 1 when the file is stale
"""

from __future__ import annotations

import argparse
import sys

from server.gateway_catalog import (
    CATALOG_PATH,
    LITELLM_CONFIG_PATH,
    GatewayCatalogError,
    gateway_rows,
    load_catalog,
    render_litellm_config,
    write_litellm_config,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the checked-in file matches the catalog.")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        catalog = load_catalog(CATALOG_PATH)
        rows = gateway_rows(catalog)
        expected = render_litellm_config(catalog)
    except GatewayCatalogError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    current = LITELLM_CONFIG_PATH.read_text(encoding="utf-8") if LITELLM_CONFIG_PATH.exists() else ""
    if args.check:
        if current != expected:
            print(
                f"ERROR: {LITELLM_CONFIG_PATH.relative_to(CATALOG_PATH.parents[1])} is stale; "
                "run `uv run python scripts/generate_litellm_config.py`",
                file=sys.stderr,
            )
            return 1
        print(f"LiteLLM config is in lockstep with the catalog ({len(rows)} aliases)")
        return 0

    if current == expected:
        print(f"LiteLLM config unchanged ({len(rows)} aliases)")
        return 0
    write_litellm_config(catalog, LITELLM_CONFIG_PATH)
    print(f"Wrote {LITELLM_CONFIG_PATH} ({len(rows)} aliases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
