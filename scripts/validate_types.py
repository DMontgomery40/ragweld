#!/usr/bin/env python3
"""
Validate that generated.ts matches current Pydantic models.

This script should be run in CI and as a pre-commit hook.
It fails if the TypeScript types are out of sync with the Pydantic models.

Exit codes:
    0 - Types are in sync
    1 - Types are out of sync (run generate_types.py to fix)
    2 - generated.ts doesn't exist
    3 - pydantic2ts failed
"""
import subprocess
import tempfile
import sys
from pathlib import Path

GENERATED_TS_PATH = Path("web/src/types/generated.ts")


def main() -> int:
    # Check generated.ts exists
    if not GENERATED_TS_PATH.exists():
        print(f"ERROR: {GENERATED_TS_PATH} does not exist!")
        print("Run: python3.10 -c \"from pydantic2ts import generate_typescript_defs; generate_typescript_defs('server.models.tribrid_config_model', 'web/src/types/generated.ts')\"")
        return 2

    # Generate to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False) as f:
        temp_path = Path(f.name)

    try:
        # Use Python API instead of CLI since CLI has issues
        result = subprocess.run(
            ['python3.10', '-c',
             f"from pydantic2ts import generate_typescript_defs; generate_typescript_defs('server.models.tribrid_config_model', '{temp_path}')"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"ERROR: pydantic2ts failed:")
            print(result.stderr)
            return 3

        # Compare files
        existing_content = GENERATED_TS_PATH.read_text().strip()
        generated_content = temp_path.read_text().strip()

        if existing_content != generated_content:
            print("ERROR: generated.ts is OUT OF SYNC with Pydantic models!")
            print("")
            print("The TypeScript types do not match the current Pydantic model definitions.")
            print("This can cause runtime type mismatches between frontend and backend.")
            print("")
            print("To fix, run:")
            print("  python3.10 -c \"from pydantic2ts import generate_typescript_defs; generate_typescript_defs('server.models.tribrid_config_model', 'web/src/types/generated.ts')\"")
            print("")
            return 1

        print("✓ Types are in sync - generated.ts matches Pydantic models")
        return 0

    finally:
        temp_path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
