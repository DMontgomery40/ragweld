#!/usr/bin/env python3
"""
Validate that generated.ts matches current Pydantic models.

This script should be run in CI and as a pre-commit hook.
It fails if the TypeScript types are out of sync with the Pydantic models.

Exit codes:
    0 - Types are in sync
    1 - Types are out of sync (run generate_types.py to fix)
    2 - generated.ts doesn't exist
    3 - Generation failed
"""
import subprocess
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

GENERATED_TS_PATH = PROJECT_ROOT / "web/src/types/generated.ts"
GENERATE_SCRIPT = PROJECT_ROOT / "scripts/generate_types.py"


def main() -> int:
    # Check generated.ts exists
    if not GENERATED_TS_PATH.exists():
        print(f"ERROR: {GENERATED_TS_PATH} does not exist!")
        print("Run: uv run scripts/generate_types.py")
        return 2

    try:
        # Read existing content
        existing_content = GENERATED_TS_PATH.read_text()

        # Generate fresh content to a temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ts', delete=False) as tmp:
            tmp_path = Path(tmp.name)

        # Temporarily redirect the output
        original_generated_ts = GENERATED_TS_PATH

        # Import and run generation directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("generate_types", GENERATE_SCRIPT)
        if spec is None or spec.loader is None:
            print("ERROR: Could not load generate_types.py")
            return 3

        generate_module = importlib.util.module_from_spec(spec)

        # Monkey-patch the output path
        old_stdout = sys.stdout
        sys.stdout = open('/dev/null', 'w')

        try:
            spec.loader.exec_module(generate_module)
            # Get the newly generated content
            fresh_content = GENERATED_TS_PATH.read_text()
        finally:
            sys.stdout.close()
            sys.stdout = old_stdout

        # Compare content (strip to handle trailing newlines)
        if existing_content.strip() != fresh_content.strip():
            print("ERROR: generated.ts is OUT OF SYNC with Pydantic models!")
            print("")
            print("The TypeScript types do not match the current Pydantic model definitions.")
            print("This can cause runtime type mismatches between frontend and backend.")
            print("")
            print("To fix, run:")
            print("  uv run scripts/generate_types.py")
            print("")
            return 1

        print("✓ Types are in sync - generated.ts matches Pydantic models")
        return 0

    except Exception as e:
        print(f"ERROR: Type validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 3


if __name__ == '__main__':
    sys.exit(main())
