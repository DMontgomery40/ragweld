#!/usr/bin/env python3
"""
Check for banned imports and terms in the codebase.

This script prevents accidental use of:
- Redis (removed)
- LangChain (use LangGraph directly)
- Wrong terminology (cards vs chunk_summaries, etc.)

Exit codes:
    0 - No violations found
    1 - Violations found (see output for details)
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

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
    "tests/api/test_index_dashboard_endpoints.py",
    "tests/api/test_rag_tab_endpoints.py",
    "tests/api/test_reranker_train_endpoints.py",
    "tests/api/test_search_endpoints.py",
    "tests/unit/test_embedder.py",
    "tests/unit/test_postgres_pooling.py",
    "tests/unit/test_reranker.py",
    "tests/unit/test_sparse.py",
}

# Banned import patterns (regex)
BANNED_IMPORTS: list[tuple[str, str]] = [
    (r'from\s+redis\s+import', 'Redis has been removed from this project'),
    (r'import\s+redis\b', 'Redis has been removed from this project'),
    (r'from\s+langchain\s+import', 'Use langgraph directly, not langchain wrappers'),
    (r'import\s+langchain\b(?!_)', 'Use langgraph directly, not langchain wrappers'),
]

# Banned terms in code (not imports)
BANNED_TERMS: list[tuple[str, str]] = [
    (r'\bcards\b', 'Use "chunk_summaries" instead of "cards"'),
    (r'golden.?question', 'Use "eval_dataset" instead of "golden questions"'),
]

# Pytest mocking patterns (zero-mocked tests policy). Mock usage is caught at the
# import so every access route is covered; only a *bare* `patch(` is matched at the
# call site — a lookbehind excludes object method calls like httpx `client.patch(`
# so a PATCH request is never mistaken for `unittest.mock.patch`.
PYTEST_MOCK_PATTERNS: list[tuple[str, str]] = [
    (r"\bmonkeypatch\b", "Zero-mocked tests: remove pytest monkeypatch usage."),
    (r"\bfrom\s+unittest\.mock\s+import\b", "Zero-mocked tests: remove unittest.mock usage."),
    (r"\bimport\s+unittest\.mock\b", "Zero-mocked tests: remove unittest.mock usage."),
    (r"\bfrom\s+unittest\s+import\b[^\n]*\bmock\b", "Zero-mocked tests: remove unittest.mock usage."),
    (r"^\s*import\s+mock\b", "Zero-mocked tests: remove the third-party mock backport."),
    (r"\bMagicMock\b", "Zero-mocked tests: remove unittest.mock MagicMock usage."),
    (r"\bAsyncMock\b", "Zero-mocked tests: remove unittest.mock AsyncMock usage."),
    (r"(?<![\w.])patch\(", "Zero-mocked tests: remove unittest.mock patch() usage."),
]

# =============================================================================
# Operator-facing terminology invariant (web/src + data/glossary.json)
# =============================================================================
#
# `.claude/rules/terminology.md` bans, in operator-facing copy: card/cards (for chunk
# summaries), golden questions, ranker (use reranker), profile(s). This scanner enforces the
# subset that can be checked without false positives:
#
# - `ranker`  : `\branker\b` matches the standalone word but NOT `reranker` (no word boundary
#               after the `e`) and NOT camelCase identifiers like `LearningRankerSubtab`.
# - `golden questions` : `golden.?questions?` — the legacy eval-set term.
#   Both are scanned in web/src (.ts/.tsx/.css) AND data/glossary.json.
#
# - `cards` (chunk-summary sense) : scanned in data/glossary.json ONLY. In web/src every
#   `card(s)` is a generic UI element (incident/provider/choice/citation cards), so a blanket
#   ban there would be all false positives. In the glossary the only legitimate `card(s)` are
#   the HuggingFace proper noun "Model Card(s)" and the chat UI "citation cards", which the
#   lookbehinds allow.
# - `profile(s)` is intentionally NOT enforced: it has many legitimate uses (Colima profile,
#   latency profile, corpus eval profile, prompt profile). The removed "Profiles" feature is
#   already gone; its residue is only "... removed" comments.
WEB_GLOSSARY_BANNED_TERMS: List[Tuple[str, str]] = [
    (r'\branker\b', 'Use "reranker" not "ranker" (terminology.md).'),
    (r'golden.?questions?', 'Use "eval_dataset"/"eval entries" not "golden questions" (terminology.md).'),
]
# `card(s)` meaning chunk summaries; allows "Model Card(s)" and "citation cards".
GLOSSARY_CARDS_BANNED = (
    re.compile(r'(?<!model[ -])(?<!citation )\bcards?\b', re.IGNORECASE),
    'Use "chunk_summaries" not "cards" (terminology.md).',
)
# The one web/src module allowed to contain a pre-rename banned slug: the subtab alias map,
# which exists precisely to keep old (now-renamed) bookmark slugs resolving.
WEB_BANNED_TERM_EXEMPT_PATHS = {
    "web/src/config/subtabAliases.ts",
}

# =============================================================================
# Environment usage policy
# =============================================================================
#
# Environment variables are allowed for:
# - Secrets (API keys)
# - Infrastructure/runtime wiring (ports, DSNs, container flags)
#
# They are NOT allowed for model selection or other operator-tunable behavior
# governed by the validated runtime configuration boundary.
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
# - moved under validated runtime config (preferred).
SERVER_ENV_GETENV_ALLOWLIST = {
    # Provider secrets
    "OPENAI_API_KEY",
    "LITELLM_API_KEY",
    "COHERE_API_KEY",
    "VOYAGE_API_KEY",
    "JINA_API_KEY",
    # Integrations (UI-only presence checks; values are never returned)
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
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
    "FRONTEND_PORT",
    "BACKEND_PORT",
    "RAGWELD_LOAD_DOTENV",
    "LOKI_BASE_URL",
}

# Keys that must never be read from env in server code (use validated config).
SERVER_ENV_GETENV_BANNED = {
    "LLM_MODEL",
    "LLM_PROVIDER",
    "LLM_TEMPERATURE",
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    # Provider routing URLs belong to the private LiteLLM deployment config.
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
    'output/playwright',
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


def check_python_files() -> list[str]:
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


def check_typescript_files(web_src: Path = Path('web/src')) -> list[str]:
    """Check TypeScript files for banned patterns."""
    errors: list[str] = []

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
        # Public wire contracts must come from the generated boundary types.
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
                    f"{rel_path}:{i}: Public wire types must be imported from types/generated.ts, not {spec}"
                )

        # ---------------------------------------------------------------------
        # Prevent reintroducing hand-written API payload interfaces in api/services
        # ---------------------------------------------------------------------
        if "/web/src/api/" in f"/{rel_norm}" or "/web/src/services/" in f"/{rel_norm}":
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(r"export\s+interface\s+\w+(Request|Response|Status)\b", line):
                    errors.append(
                        f"{rel_path}:{i}: Hand-written public wire interface found. "
                        "Define the registered backend boundary contract and import its generated type."
                    )

    return errors


def _normalize_relpath(p: Path) -> str:
    try:
        rel = p.relative_to(Path.cwd())
    except Exception:
        rel = p
    # Normalize path separators for stable output across platforms.
    return str(rel).replace("\\", "/")


def check_zero_mock_tests(
    web_tests_root: Path = Path(".tests"),
    pytests_root: Path = Path("tests"),
) -> list[str]:
    """Fail on mocked tests (Playwright route stubs, pytest mocks).

    Note: while migrating, files in ZERO_MOCK_ALLOWLIST are permitted to contain
    these patterns. The allowlist should shrink toward empty. The roots are
    parameters so tests can drive the scanner over a fixture tree.
    """
    errors: list[str] = []

    # Playwright route stubbing / request interception patterns
    playwright_patterns: list[tuple[str, str]] = [
        (r"\bpage\.route\(", "Zero-mocked tests: remove Playwright request stubbing (page.route)."),
        (r"\bcontext\.route\(", "Zero-mocked tests: remove Playwright request stubbing (context.route)."),
        (r"\broute\.fulfill\(", "Zero-mocked tests: remove mocked responses (route.fulfill)."),
        (r"\broute\.(abort|continue|fallback)\(", "Zero-mocked tests: remove request interception (route.abort/continue/fallback)."),
    ]

    if web_tests_root.exists():
        for f in web_tests_root.rglob("*"):
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

    if pytests_root.exists():
        for py_file in pytests_root.rglob("*.py"):
            if should_skip(py_file):
                continue
            rel = _normalize_relpath(py_file)
            # The checker's own test file carries these patterns as fixture strings to
            # prove the checker detects them; excluding it mirrors check_python_files,
            # which already skips `check_banned` paths for the banned-terms scan.
            if "check_banned" in str(py_file):
                continue
            try:
                content = py_file.read_text()
            except Exception:
                continue
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                for pattern, message in PYTEST_MOCK_PATTERNS:
                    if re.search(pattern, line):
                        if rel in ZERO_MOCK_ALLOWLIST:
                            continue
                        errors.append(f"{rel}:{i}: {message}")

    return errors


def check_no_legacy_web_modules() -> list[str]:
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


def check_legacy_project_name() -> list[str]:
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


def check_env_example_legacy_keys() -> list[str]:
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


def check_server_env_getenv_allowlist() -> list[str]:
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
                    "Move this under the validated runtime configuration boundary."
                )
                continue
            if key not in SERVER_ENV_GETENV_ALLOWLIST:
                errors.append(
                    f"{_normalize_relpath(py_file)}:{i}: Env key '{key}' is not allowlisted. "
                    "If this is a secret/infra key, add it to SERVER_ENV_GETENV_ALLOWLIST with justification; "
                    "otherwise move it under Pydantic config."
                )
    return errors


def check_studio_no_inline_styles() -> list[str]:
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


def check_no_frontend_runtime_models_json_fetches() -> list[str]:
    """Fail when frontend runtime code fetches static models.json directly."""
    errors: list[str] = []
    web_src = Path("web/src")
    if not web_src.exists():
        return errors

    banned_patterns = [
        (
            re.compile(r"fetch\(\s*['\"][^'\"]*models\.json", re.IGNORECASE),
            "Runtime catalog fetch from models.json is banned. Use /api/models via web/src/api/models.ts.",
        ),
        (
            re.compile(r"axios\.(get|post|request)\(\s*['\"][^'\"]*models\.json", re.IGNORECASE),
            "Runtime catalog fetch from models.json is banned. Use /api/models via web/src/api/models.ts.",
        ),
        (
            re.compile(r"api\(\s*['\"][^'\"]*models\.json", re.IGNORECASE),
            "Runtime catalog fetch from models.json is banned. Use /api/models via web/src/api/models.ts.",
        ),
    ]

    for f in web_src.rglob("*"):
        if should_skip(f) or not f.is_file():
            continue
        if f.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        # Generated file comments can mention models.json.
        if str(f).endswith("web/src/types/generated.ts"):
            continue
        try:
            content = f.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(content.split("\n"), 1):
            for pattern, message in banned_patterns:
                if pattern.search(line):
                    errors.append(f"{_normalize_relpath(f)}:{i}: {message}")
    return errors


def check_models_catalog_mirror_sync() -> list[str]:
    """Fail when data/models.json and web/public/models.json diverge."""
    errors: list[str] = []
    data_path = Path("data/models.json")
    web_path = Path("web/public/models.json")

    if not data_path.exists():
        errors.append("data/models.json missing (authoritative runtime catalog is required).")
        return errors
    if not web_path.exists():
        errors.append("web/public/models.json missing (legacy mirror is required for compatibility).")
        return errors

    try:
        data_obj = json.loads(data_path.read_text(errors="ignore"))
    except Exception as e:
        errors.append(f"data/models.json: failed to parse JSON ({e})")
        return errors
    try:
        web_obj = json.loads(web_path.read_text(errors="ignore"))
    except Exception as e:
        errors.append(f"web/public/models.json: failed to parse JSON ({e})")
        return errors

    if data_obj != web_obj:
        errors.append(
            "data/models.json and web/public/models.json are out of sync. "
            "Update both atomically (or use POST /api/models/upsert)."
        )
    return errors


def check_retrieval_config_surface() -> list[str]:
    """Run Retrieval UI/Pydantic surface coverage validation."""
    errors: list[str] = []
    validator_path = Path(__file__).resolve().parent / "validate_retrieval_config_surface.py"

    if not validator_path.exists():
        return [f"{_normalize_relpath(validator_path)}: Retrieval surface validator script is missing."]

    try:
        spec = importlib.util.spec_from_file_location("validate_retrieval_config_surface", validator_path)
        if spec is None or spec.loader is None:
            return [f"{_normalize_relpath(validator_path)}: Could not load validator module spec."]
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validate_fn = getattr(module, "validate_retrieval_config_surface", None)
        if not callable(validate_fn):
            return [f"{_normalize_relpath(validator_path)}: validate_retrieval_config_surface() not found."]
        result = validate_fn()
        if not isinstance(result, list):
            return [f"{_normalize_relpath(validator_path)}: Validator returned non-list result."]
        for item in result:
            errors.append(f"{_normalize_relpath(validator_path)}: {item}")
    except Exception as e:
        return [f"{_normalize_relpath(validator_path)}: Validator execution failed ({e})."]

    return errors


def check_web_and_glossary_terminology() -> List[str]:
    """Forbid banned operator-facing terminology in web/src and data/glossary.json.

    See WEB_GLOSSARY_BANNED_TERMS / GLOSSARY_CARDS_BANNED for the exact rules and rationale.
    """
    errors: list[str] = []
    compiled = [(re.compile(p, re.IGNORECASE), m) for p, m in WEB_GLOSSARY_BANNED_TERMS]

    # --- web/src (.ts/.tsx/.css), excluding generated + exempt alias module ---
    web_src = Path("web/src")
    if web_src.exists():
        for f in web_src.rglob("*"):
            if should_skip(f) or not f.is_file():
                continue
            if f.suffix not in {".ts", ".tsx", ".css"}:
                continue
            rel = _normalize_relpath(f)
            if rel.endswith("web/src/types/generated.ts") or "generated.ts" in rel:
                continue
            if rel in WEB_BANNED_TERM_EXEMPT_PATHS:
                continue
            try:
                content = f.read_text(errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(content.split("\n"), 1):
                for rx, message in compiled:
                    if rx.search(line):
                        errors.append(f"{rel}:{i}: {message}")

    # --- data/glossary.json (all string values) ---
    gpath = Path("data/glossary.json")
    if gpath.exists():
        try:
            glossary = json.loads(gpath.read_text(errors="ignore"))
        except Exception as e:
            errors.append(f"data/glossary.json: failed to parse JSON ({e})")
            glossary = None

        if glossary is not None:
            def _walk(obj, term: str):
                # Track the enclosing term name for a useful pointer.
                if isinstance(obj, dict):
                    here = str(obj.get("term") or term)
                    for v in obj.values():
                        yield from _walk(v, here)
                elif isinstance(obj, list):
                    for v in obj:
                        yield from _walk(v, term)
                elif isinstance(obj, str):
                    yield term, obj

            cards_rx, cards_msg = GLOSSARY_CARDS_BANNED
            for term, value in _walk(glossary, "?"):
                for rx, message in compiled:
                    if rx.search(value):
                        errors.append(f"data/glossary.json (term '{term}'): {message}")
                if cards_rx.search(value):
                    errors.append(f"data/glossary.json (term '{term}'): {cards_msg}")

    return errors


def main() -> int:
    print("Checking for banned patterns...")
    print("")

    errors = []
    errors.extend(check_python_files())
    errors.extend(check_typescript_files())
    errors.extend(check_web_and_glossary_terminology())
    errors.extend(check_zero_mock_tests())
    errors.extend(check_no_legacy_web_modules())
    errors.extend(check_legacy_project_name())
    errors.extend(check_env_example_legacy_keys())
    errors.extend(check_server_env_getenv_allowlist())
    errors.extend(check_studio_no_inline_styles())
    errors.extend(check_no_frontend_runtime_models_json_fetches())
    errors.extend(check_models_catalog_mirror_sync())
    errors.extend(check_retrieval_config_surface())

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
