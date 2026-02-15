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

# =============================================================================
# Env usage policy ("THE LAW")
# =============================================================================
#
# Environment variables are allowed for:
# - Secrets (API keys)
# - Infrastructure/runtime wiring (ports, DSNs, container flags)
#
# They are NOT allowed for model selection or other tunable behavior that should
# be governed by Pydantic config (server/models/tribrid_config_model.py).
ENV_EXAMPLE_BANNED_KEYS = {
    # Legacy/no-op keys that have caused repeated confusion.
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
}

# Strict allowlist for literal os.getenv("...") keys in server/.
#
# If you add a new env dependency, it must be either:
# - a secret/infra key, added here with justification, OR
# - moved under Pydantic config (preferred).
SERVER_ENV_GETENV_ALLOWLIST = {
    # Provider secrets
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "COHERE_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "VOYAGE_API_KEY",
    "JINA_API_KEY",
    # Integrations (UI-only presence checks; values are never returned)
    "LANGTRACE_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_API_KEY",
    "NETLIFY_API_KEY",
    "GRAFANA_API_KEY",
    "SLACK_WEBHOOK_URL",
    "DISCORD_WEBHOOK_URL",
    # Postgres infra
    "POSTGRES_DSN",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    # Neo4j infra
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
    "TRIBRID_DB_DIR",
    # Dev stack / container wiring
    "TRIBRID_DEV_ORCHESTRATOR",
    "FRONTEND_PORT",
    "BACKEND_PORT",
    "LOKI_BASE_URL",
}

# Keys that must never be read from env in server code (config must be Pydantic-driven).
SERVER_ENV_GETENV_BANNED = {
    "LLM_MODEL",
    "LLM_PROVIDER",
    "LLM_TEMPERATURE",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    # Use TriBridConfig.generation.openai_base_url instead.
    "OPENAI_BASE_URL",
    # Use TriBridConfig.embedding.embedding_dim instead.
    "TRIBRID_EMBEDDING_DIM",
}

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
    # Model artifacts / training outputs (may include arbitrary tokens/strings)
    'data/reranker_train_runs',
    'models',
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

STUDIO_INLINE_STYLE_PATHS = [
    "web/src/components/RerankerTraining/TrainingStudio.tsx",
    "web/src/components/RerankerTraining/NeuralVisualizer.tsx",
    "web/src/components/RerankerTraining/NeuralVisualizerCore.tsx",
    "web/src/components/RerankerTraining/NeuralVisualizerWebGPU.tsx",
    "web/src/components/RerankerTraining/NeuralVisualizerWebGL2.tsx",
    "web/src/components/RerankerTraining/NeuralVisualizerCanvas2D.tsx",
    "web/src/components/RerankerTraining/StudioLogTerminal.tsx",
    "web/src/components/RAG/LearningRankerSubtab.tsx",
]


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


def check_no_legacy_web_modules() -> List[str]:
    """Fail if legacy JS modules exist under web/src.

    TriBridRAG is TypeScript-first on the frontend. Legacy JS modules are banned
    because they bypass typing and often rely on window globals.
    """
    errors: list[str] = []

    legacy_dir = Path("web/src/modules")
    if legacy_dir.exists():
        errors.append("web/src/modules exists (legacy JS modules are banned). Delete this directory.")

    web_src = Path("web/src")
    if web_src.exists():
        for p in web_src.rglob("*"):
            if should_skip(p):
                continue
            if p.is_file() and p.suffix in {".js", ".jsx"}:
                rel = _normalize_relpath(p)
                errors.append(f"{rel}: legacy JS/JSX file found under web/src (banned).")

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


def check_env_example_legacy_keys() -> List[str]:
    """Fail if .env.example contains legacy/no-op config keys.

    .env.example is tracked and serves as onboarding documentation. It must not
    advertise non-LAW configuration.
    """
    errors: list[str] = []
    p = Path(".env.example")
    if not p.exists():
        return errors
    try:
        content = p.read_text(errors="ignore")
    except Exception:
        return errors

    for key in sorted(ENV_EXAMPLE_BANNED_KEYS):
        if re.search(rf"^\s*{re.escape(key)}\s*=", content, re.MULTILINE):
            errors.append(
                f".env.example:1: Legacy key '{key}' found. "
                "Model/provider selection must be configured via Pydantic config, not .env."
            )
    return errors


def check_server_env_getenv_allowlist() -> List[str]:
    """Fail if server/ reads a non-allowlisted env key via os.getenv("...")."""
    errors: list[str] = []
    rx = re.compile(r"os\.getenv\(\s*['\"]([^'\"]+)['\"]")

    for py_file in Path("server").rglob("*.py"):
        if should_skip(py_file):
            continue
        try:
            content = py_file.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            m = rx.search(line)
            if not m:
                continue
            key = str(m.group(1) or "").strip()
            if not key:
                continue
            if key in SERVER_ENV_GETENV_BANNED:
                errors.append(
                    f"{_normalize_relpath(py_file)}:{i}: Env key '{key}' is banned in server code. "
                    "Move this under Pydantic config (THE LAW)."
                )
                continue
            if key not in SERVER_ENV_GETENV_ALLOWLIST:
                errors.append(
                    f"{_normalize_relpath(py_file)}:{i}: Env key '{key}' is not allowlisted. "
                    "If this is a secret/infra key, add it to SERVER_ENV_GETENV_ALLOWLIST with justification; "
                    "otherwise move it under Pydantic config."
                )
    return errors


def check_studio_no_inline_styles() -> List[str]:
    """Fail when inline style props appear in studio scope files."""
    errors: list[str] = []
    pattern = re.compile(r"\bstyle\s*=\s*\{")

    for rel in STUDIO_INLINE_STYLE_PATHS:
        p = Path(rel)
        if not p.exists():
            continue
        try:
            content = p.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            if pattern.search(line):
                errors.append(
                    f"{_normalize_relpath(p)}:{i}: Inline style is banned in studio scope. "
                    "Move styles to CSS classes."
                )
    return errors


def main() -> int:
    print("Checking for banned patterns...")
    print("")

    errors = []
    errors.extend(check_python_files())
    errors.extend(check_typescript_files())
    errors.extend(check_zero_mock_tests())
    errors.extend(check_no_legacy_web_modules())
    errors.extend(check_legacy_project_name())
    errors.extend(check_env_example_legacy_keys())
    errors.extend(check_server_env_getenv_allowlist())
    errors.extend(check_studio_no_inline_styles())

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
