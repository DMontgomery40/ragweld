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

# =============================================================================
# Zero-mocked tests policy (TriBrid direction)
# =============================================================================
#
# We are moving to "zero-mocked tests": no Playwright request stubbing and no
# Python monkeypatch/unittest.mock. This checker is the enforcement mechanism.
#
# During migration, we allowlist known legacy tests that still contain mocks.
# Shrink this list toward empty as tests are converted to real integration/E2E.
ZERO_MOCK_ALLOWLIST = {
    # Playwright tests (temporary, migrating away from route stubs)
    ".tests/web/chat_streaming.spec.ts",
    ".tests/web/chat_dev_trace_logs.spec.ts",
    ".tests/web/dashboard-storage.spec.ts",
    ".tests/web/dev-stack.spec.ts",
    ".tests/web/eval_runner.spec.ts",
    ".tests/web/evaluation-runner.spec.ts",
    ".tests/web/grafana-tab.spec.ts",
    ".tests/web/graph-visualization.spec.ts",
    ".tests/web/graph.spec.ts",
    ".tests/web/graphrag-ui.spec.ts",
    ".tests/web/infrastructure-services-status.spec.ts",
    ".tests/web/rag-tab.spec.ts",
    ".tests/web/reranker-training.spec.ts",
    ".tests/web/stores-hooks.spec.ts",
    # Pytest files (temporary, migrating away from monkeypatch/mocks)
    "tests/api/test_chat_endpoints.py",
    "tests/api/test_config_endpoints.py",
    "tests/api/test_cost_endpoints.py",
    "tests/api/test_dev_stack_endpoints.py",
    "tests/api/test_docker_endpoints.py",
    "tests/api/test_index_dashboard_endpoints.py",
    "tests/api/test_metrics_endpoint.py",
    "tests/api/test_rag_tab_endpoints.py",
    "tests/api/test_reranker_train_endpoints.py",
    "tests/api/test_search_endpoints.py",
    "tests/unit/test_embedder.py",
    "tests/unit/test_fusion.py",
    "tests/unit/test_postgres_pooling.py",
    "tests/unit/test_reranker.py",
    "tests/unit/test_sparse.py",
}

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
    # Generated/runtime artifacts (may include arbitrary corpus content)
    'data/eval_runs',
]

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".txt",
    ".css",
    ".html",
    ".sh",
    ".toml",
    ".lock",
    ".example",
}


def should_skip(path: Path) -> bool:
    """Check if path should be skipped."""
    path_str = str(path)
    return any(skip in path_str for skip in SKIP_PATTERNS)


def check_python_files() -> List[str]:
    """Check Python files for banned patterns."""
    errors: list[str] = []

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
    errors: list[str] = []

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

        rel_path = _normalize_relpath(ts_file)
        rel_norm = rel_path.replace("\\", "/")

        # ---------------------------------------------------------------------
        # Pydantic-first enforcement: do not import API payload types from @web/types
        # ---------------------------------------------------------------------
        if "/web/src/api/" in f"/{rel_norm}" or "/web/src/stores/" in f"/{rel_norm}":
            # Allow UI-only modules (explicit allowlist).
            allow_prefixes = (
                "@web/types/storage",
            )
            for i, line in enumerate(content.split("\n"), 1):
                if "@web/types" not in line:
                    continue
                m = re.search(r"from\s+['\"](@web/types(?:/[^'\"]+)?)['\"]", line)
                if not m:
                    continue
                spec = m.group(1)
                if any(spec == p or spec.startswith(p + "/") for p in allow_prefixes):
                    continue
                errors.append(
                    f"{rel_path}:{i}: API types must be imported from types/generated.ts, not {spec}"
                )

        # ---------------------------------------------------------------------
        # Prevent reintroducing hand-written API payload interfaces in api/services
        # ---------------------------------------------------------------------
        if "/web/src/api/" in f"/{rel_norm}" or "/web/src/services/" in f"/{rel_norm}":
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(r"export\s+interface\s+\w+(Request|Response|Status)\b", line):
                    errors.append(
                        f"{rel_path}:{i}: Hand-written API interface found. "
                        "Define it in Pydantic and import from types/generated.ts."
                    )

        # Check for hand-written Config interfaces (should import from generated.ts)
        # Only flag in component files, not in hooks/stores/types directories
        if '/components/' in str(ts_file):
            if re.search(r'^interface\s+\w+Config\s*\{', content, re.MULTILINE):
                errors.append(
                    f"{ts_file}: Hand-written Config interface found. "
                    "Import from '../types/generated' instead."
                )

    return errors


def _normalize_relpath(p: Path) -> str:
    try:
        rel = p.relative_to(Path.cwd())
    except Exception:
        rel = p
    # Normalize path separators for stable output across platforms.
    return str(rel).replace("\\", "/")


def check_zero_mock_tests() -> List[str]:
    """Fail on mocked tests (Playwright route stubs, pytest mocks).

    Note: while migrating, files in ZERO_MOCK_ALLOWLIST are permitted to contain
    these patterns. The allowlist should shrink toward empty.
    """
    errors: list[str] = []

    # Playwright route stubbing / request interception patterns
    playwright_patterns: list[tuple[str, str]] = [
        (r"\bpage\.route\(", "Zero-mocked tests: remove Playwright request stubbing (page.route)."),
        (r"\bcontext\.route\(", "Zero-mocked tests: remove Playwright request stubbing (context.route)."),
        (r"\broute\.fulfill\(", "Zero-mocked tests: remove mocked responses (route.fulfill)."),
        (r"\broute\.(abort|continue|fallback)\(", "Zero-mocked tests: remove request interception (route.abort/continue/fallback)."),
    ]

    tests_root = Path(".tests")
    if tests_root.exists():
        for f in tests_root.rglob("*"):
            if should_skip(f) or not f.is_file():
                continue
            if f.suffix not in {".ts", ".tsx", ".js"}:
                continue
            rel = _normalize_relpath(f)
            try:
                content = f.read_text()
            except Exception:
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                for pattern, message in playwright_patterns:
                    if re.search(pattern, line):
                        if rel in ZERO_MOCK_ALLOWLIST:
                            continue
                        errors.append(f"{rel}:{i}: {message}")

    # Pytest mocking patterns
    pytest_patterns: list[tuple[str, str]] = [
        (r"\bmonkeypatch\b", "Zero-mocked tests: remove pytest monkeypatch usage."),
        (r"\bfrom\s+unittest\.mock\s+import\b", "Zero-mocked tests: remove unittest.mock usage."),
        (r"\bimport\s+unittest\.mock\b", "Zero-mocked tests: remove unittest.mock usage."),
        (r"\bMagicMock\b", "Zero-mocked tests: remove unittest.mock MagicMock usage."),
        (r"\bAsyncMock\b", "Zero-mocked tests: remove unittest.mock AsyncMock usage."),
        (r"\bpatch\(", "Zero-mocked tests: remove unittest.mock patch() usage."),
    ]

    pytests_root = Path("tests")
    if pytests_root.exists():
        for py_file in pytests_root.rglob("*.py"):
            if should_skip(py_file):
                continue
            rel = _normalize_relpath(py_file)
            try:
                content = py_file.read_text()
            except Exception:
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                for pattern, message in pytest_patterns:
                    if re.search(pattern, line):
                        if rel in ZERO_MOCK_ALLOWLIST:
                            continue
                        errors.append(f"{rel}:{i}: {message}")

    return errors


def check_legacy_project_name() -> List[str]:
    """Fail if the legacy project name substring appears anywhere.

    Note: Implemented without embedding the forbidden substring in this source file.
    """
    errors: list[str] = []
    legacy = "".join(["a", "g", "r", "o"])
    rx = re.compile(re.escape(legacy), re.IGNORECASE)

    for f in Path(".").rglob("*"):
        if should_skip(f) or not f.is_file():
            continue
        if f.suffix and f.suffix not in TEXT_SUFFIXES:
            continue
        if not f.suffix and f.name not in {"Dockerfile", "Makefile"}:
            continue
        try:
            # Avoid decoding failures in mixed encodings; we only need substring detection.
            content = f.read_text(errors="ignore")
        except Exception:
            continue
        if not rx.search(content):
            continue

        rel = _normalize_relpath(f)
        # Find the first matching line number for a helpful pointer.
        for i, line in enumerate(content.split("\n"), 1):
            if rx.search(line):
                errors.append(f"{rel}:{i}: Legacy project name detected; use TriBrid naming.")
                break

    return errors


def main() -> int:
    print("Checking for banned patterns...")
    print("")

    errors = []
    errors.extend(check_python_files())
    errors.extend(check_typescript_files())
    errors.extend(check_zero_mock_tests())
    errors.extend(check_legacy_project_name())

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
