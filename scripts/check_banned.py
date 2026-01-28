#!/usr/bin/env python3
"""
Check for banned imports and terms in the codebase.

This script prevents accidental use of:
- Qdrant (we use pgvector)
- Redis (removed)
- LangChain (use LangGraph directly)
- Wrong terminology (cards vs chunk_summaries, etc.)

Exit codes:
    0 - No violations found
    1 - Violations found (see output for details)
"""
import re
import sys
from pathlib import Path
from typing import List, Tuple

# Banned import patterns (regex)
BANNED_IMPORTS: List[Tuple[str, str]] = [
    (r'from\s+qdrant_client\s+import', 'Use pgvector instead of Qdrant'),
    (r'import\s+qdrant_client', 'Use pgvector instead of Qdrant'),
    (r'from\s+redis\s+import', 'Redis has been removed from this project'),
    (r'import\s+redis\b', 'Redis has been removed from this project'),
    (r'from\s+langchain\s+import', 'Use langgraph directly, not langchain wrappers'),
    (r'import\s+langchain\b(?!_)', 'Use langgraph directly, not langchain wrappers'),
]

# Banned terms in code (not imports)
BANNED_TERMS: List[Tuple[str, str]] = [
    (r'\bcards\b', 'Use "chunk_summaries" instead of "cards"'),
    (r'golden.?question', 'Use "eval_dataset" instead of "golden questions"'),
]

# Files/directories to skip
SKIP_PATTERNS = [
    '__pycache__',
    '.git',
    'node_modules',
    '.venv',
    'venv',
    '.pytest_cache',
    'dist',
    'build',
    '.mypy_cache',
]


def should_skip(path: Path) -> bool:
    """Check if path should be skipped."""
    path_str = str(path)
    return any(skip in path_str for skip in SKIP_PATTERNS)


def check_python_files() -> List[str]:
    """Check Python files for banned patterns."""
    errors = []

    for py_file in Path('server').rglob('*.py'):
        if should_skip(py_file):
            continue

        try:
            content = py_file.read_text()
        except Exception as e:
            print(f"Warning: Could not read {py_file}: {e}")
            continue

        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # Check banned imports
            for pattern, message in BANNED_IMPORTS:
                if re.search(pattern, line):
                    errors.append(f"{py_file}:{i}: {message}")

            # Check banned terms (skip if in this file or CLAUDE.md context)
            if 'check_banned' not in str(py_file) and 'BANNED' not in line:
                for pattern, message in BANNED_TERMS:
                    if re.search(pattern, line, re.IGNORECASE):
                        errors.append(f"{py_file}:{i}: {message}")

    return errors


def check_typescript_files() -> List[str]:
    """Check TypeScript files for banned patterns."""
    errors = []

    web_src = Path('web/src')
    if not web_src.exists():
        return errors

    for ts_file in web_src.rglob('*.ts'):
        if should_skip(ts_file):
            continue

        # Skip generated files
        if 'generated.ts' in str(ts_file):
            continue

        try:
            content = ts_file.read_text()
        except Exception as e:
            print(f"Warning: Could not read {ts_file}: {e}")
            continue

        # Check for hand-written Config interfaces (should import from generated.ts)
        # Only flag in component files, not in hooks/stores/types directories
        if '/components/' in str(ts_file):
            if re.search(r'^interface\s+\w+Config\s*\{', content, re.MULTILINE):
                errors.append(
                    f"{ts_file}: Hand-written Config interface found. "
                    "Import from '../types/generated' instead."
                )

    return errors


def main() -> int:
    print("Checking for banned patterns...")
    print("")

    errors = []
    errors.extend(check_python_files())
    errors.extend(check_typescript_files())

    if errors:
        print("BANNED PATTERNS FOUND:")
        print("")
        for error in sorted(errors):
            print(f"  ✗ {error}")
        print("")
        print(f"Total: {len(errors)} violation(s)")
        print("")
        print("Fix these issues before committing.")
        return 1

    print("✓ No banned patterns found")
    return 0


if __name__ == '__main__':
    sys.exit(main())
