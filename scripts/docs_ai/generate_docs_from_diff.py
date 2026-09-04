#!/usr/bin/env python3
"""
Docs Autopilot for ragweld — diff-driven documentation updates.

This script is modeled after the diff-based "Docs Autopilot" workflows used in other repos:
- Look at git diff between a base ref and HEAD
- Ask an LLM to produce a unified diff patch for MkDocs sources
- Optionally apply the patch with `git apply`

Modes:
  - Plan (default): write a markdown plan/checklist (no network).
  - LLM (optional): call OpenAI to produce a unified diff patch.

Important:
  - Only modify MkDocs sources: `mkdocs/docs/**` and `mkdocs.yml`.
  - The output must be safe for `mkdocs build --strict`.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Direct script invocation must resolve the same policy as application callers.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROMPT_BASE_PATH = ROOT / "scripts" / "docs_ai" / "docs_prompt_base.md"

PATCH_FILE = ROOT / "mkdocs-docs-llm.patch"
# Raw model replies and the repair-round patch are kept as artifacts: the
# 2026-08-29 truncation bug had to be inferred because only the extracted
# patch survived the run.
RAW_REPLY_FILE = ROOT / "mkdocs-docs-llm-raw.txt"
REPAIR_PATCH_FILE = ROOT / "mkdocs-docs-llm-repair.patch"
REPAIR_RAW_REPLY_FILE = ROOT / "mkdocs-docs-llm-repair-raw.txt"
PAGE_REPAIR_RAW_REPLY_FILE = ROOT / "mkdocs-docs-llm-page-repair-raw.txt"
PLAN_FILE = ROOT / "mkdocs-docs-plan.md"

# Git's well-known empty tree object. Use as a "base ref" to treat the entire
# repository as added (bootstrap / catch-up run).
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# z-ai/glm-5.3-flash: 1,048,576-token window via OpenRouter, 131,072 max
# completion, $0.075/M in and $0.25/M out - cheap enough to quote the entire
# docs corpus on every run, which is what makes generated hunks apply.
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_MAX_OUTPUT_TOKENS = 131072
# Input budget, in tokens, estimated at ~4 characters per token. Leaves the
# completion budget plus headroom inside the provider's 1,048,576 window.
DEFAULT_CONTEXT_BUDGET_TOKENS = 700000
CHARS_PER_TOKEN = 4

CHANGED_FILES_LIST_LIMIT = 4000
DIFF_CONTEXT_FILE_LIMIT = 400
PER_FILE_DIFF_CHAR_LIMIT = 60000
# Share of the large-pool budget reserved for verbatim docs pages; the rest
# goes to code diffs. Docs content is what makes a hunk apply, so it wins.
DOCS_CONTEXT_BUDGET_SHARE = 0.45

ALLOWED_PATH_PREFIXES = (
    "mkdocs/docs/",
    "mkdocs.yml",
)

# Guardrails for incremental autopilot runs. We allow broad rewrites in bootstrap
# mode, but reject suspiciously destructive patches in normal push-mode runs.
PROTECTED_DOC_DELETE_LIMITS = {
    "mkdocs/docs/index.md": 120,
    "mkdocs/docs/manual/ui.md": 100,
    "mkdocs/docs/manual/indexing.md": 100,
}
GENERAL_DELETE_LIMIT = 260

# Heuristic: exclude obvious non-code / high-churn / generated artifacts from the change context.
EXCLUDE_SUBSTRINGS = (
    ".git/",
    ".venv/",
    "venv/",
    "node_modules/",
    "site/",
    "dist/",
    "build/",
    "output/",
    "tmp/",
    "data/eval_runs/",
    "data/reranker_train_runs/",
    "data/eval_dataset/",
    "data/benchmarks/",
    "CLEANUP_PLANS/",
)

# Tracked model artifacts live in the top-level `models/` tree. Matched as a
# path prefix only: `server/models/**` is the Pydantic source of truth and must
# stay in the change context.
EXCLUDE_PREFIXES = (
    "mkdocs/",
    "site/",
    "models/",
)

EXCLUDE_SUFFIXES = (
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".pdf",
    ".dmg",
    ".bin",
    ".safetensors",
)


def normalize_base_ref(base_ref: str) -> str:
    """Normalize special base refs.

    Supported sentinels:
      - EMPTY / empty / bootstrap / empty-tree -> git empty tree (full-repo diff)
    """

    b = (base_ref or "").strip()
    if b.lower() in {"empty", "bootstrap", "empty-tree", "empty_tree"}:
        return EMPTY_TREE
    return b


def is_bootstrap_base(base_ref: str) -> bool:
    return normalize_base_ref(base_ref) == EMPTY_TREE


def run(cmd: str, *, check: bool = True) -> str:
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        shell=True,
        capture_output=True,
        text=True,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{p.stderr}")
    return p.stdout


def _gh_error(msg: str) -> None:
    """Emit GitHub Actions error annotation (visible in Actions UI)."""
    # GitHub truncates long annotations; keep first line concise
    first = msg.split("\n")[0][:200]
    print(f"::error::docs-autopilot: {first}", flush=True)
    if len(msg) > len(first):
        print(msg, flush=True)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _maybe_load_dotenv() -> None:
    """Best-effort load of repo-local `.env` for local runs.

    GitHub Actions should provide secrets via env vars; locally it's common to keep keys in `.env`.
    This loader is intentionally minimal (no export of empty values, ignores comments).
    """

    for env_path in (ROOT / ".env", ROOT / "infra" / "litellm.env"):
        _load_env_file(env_path)


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = (raw or "").strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = (k or "").strip()
            if not k or k in os.environ:
                continue
            v = (v or "").strip().strip('"').strip("'")
            if v:
                os.environ[k] = v
    except Exception:
        return


def should_include_file(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    p_lower = p.lower()
    if any(p_lower.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return False
    if any(seg in p_lower for seg in EXCLUDE_SUBSTRINGS):
        return False
    if any(p_lower.endswith(suf) for suf in EXCLUDE_SUFFIXES):
        return False
    return True


def git_diff_names(base: str) -> list[str]:
    base = normalize_base_ref(base)
    out = run(f"git diff --name-only {shlex.quote(base)}..HEAD")
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return [p for p in files if should_include_file(p)]


def git_diff_text(base: str, path: str, *, max_chars: int = 6000) -> str:
    base = normalize_base_ref(base)
    diff = run(f"git diff --unified=3 {shlex.quote(base)}..HEAD -- {shlex.quote(path)}", check=False)
    diff = (diff or "").strip()
    if not diff:
        return ""
    if max_chars > 0 and len(diff) > max_chars:
        return diff[:max_chars] + "\n... [diff truncated]\n"
    return diff + "\n"


def _first_heading(md: str) -> str:
    for line in (md or "").splitlines():
        if line.startswith("# "):
            return line.removeprefix("# ").strip()
    return ""


def scan_docs_tree() -> list[str]:
    docs_dir = ROOT / "mkdocs" / "docs"
    if not docs_dir.exists():
        return []
    entries: list[str] = []
    for md_file in sorted(docs_dir.rglob("*.md")):
        rel = md_file.relative_to(docs_dir).as_posix()
        title = _first_heading(_read_text(md_file))
        entries.append(f"- {rel}" + (f" — {title}" if title else ""))
    return entries


def scan_screenshot_assets(*, limit: int = 80) -> list[str]:
    """List current screenshot assets that docs pages may reference."""

    roots = [
        ROOT / "mkdocs" / "docs" / "assets" / "images",
        ROOT / "web" / "public" / "screenshots",
    ]
    out: list[str] = []
    seen: set[str] = set()
    exts = {".png", ".jpg", ".jpeg", ".webp"}

    for root in roots:
        if not root.exists():
            continue
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in exts:
                continue
            rel = f.relative_to(ROOT).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            out.append(f"- {rel}")
            if len(out) >= limit:
                return out
    return out


def _select_context_files(changed: list[str], *, limit: int) -> list[str]:
    """Pick a high-signal subset of files to include diffs for."""

    preferred = [
        # Validated schema boundaries + core entrypoints
        "server/models/tribrid_config_model.py",
        "server/main.py",
        "server/config.py",
        # Common operator entrypoints
        "docker-compose.yml",
        "start.sh",
        "pyproject.toml",
        "data/models.json",
        "data/glossary.json",
        # API surface
        "server/api/config.py",
        "server/api/index.py",
        "server/api/search.py",
        "server/api/chat.py",
        "server/api/models.py",
        "server/api/graph.py",
        "server/api/keywords.py",
        "server/api/eval.py",
        "server/api/docker.py",
        "server/api/health.py",
        "server/api/reranker.py",
        "server/api/agent.py",
        "server/api/dataset.py",
        # Backend services/pipeline
        "server/services/rag.py",
        "server/services/answer_service.py",
        "server/retrieval/fusion.py",
        "server/retrieval/rerank.py",
        "server/indexing/chunker.py",
        "server/indexing/loader.py",
        "server/indexing/embedder.py",
        "server/db/postgres.py",
        "server/db/neo4j.py",
        # Frontend API client layer
        "web/src/api/client.ts",
        "web/src/api/config.ts",
        "web/src/api/indexing.ts",
        "web/src/api/models.ts",
        "web/src/api/health.ts",
        "web/src/api/docker.ts",
        # Chat UI + Recall
        "web/src/components/Chat/ChatInterface.tsx",
        "web/src/components/Chat/ChatSettings.tsx",
        "web/src/components/Chat/SourceDropdown.tsx",
        # Onboarding
        "web/src/components/tabs/StartTab.tsx",
        "web/src/stores/useOnboardingStore.ts",
        # Training studios (reranker + agent)
        "web/src/components/RerankerTraining/TrainingStudio.tsx",
        "web/src/components/AgentTraining/TrainingStudio.tsx",
        "web/src/components/RAG/LearningRankerSubtab.tsx",
        "web/src/components/RAG/LearningAgentSubtab.tsx",
        # Eval
        "web/src/components/Evaluation/EvalDrillDown.tsx",
        "web/src/components/tabs/EvalAnalysisTab.tsx",
        "web/src/components/Evaluation/TraceViewer.tsx",
        # Grafana + alerting/operations
        "web/src/components/Grafana/GrafanaDashboard.tsx",
        "web/src/components/Grafana/GrafanaConfig.tsx",
        "web/src/pages/GrafanaEmbed.tsx",
        "web/src/components/RAG/RetrievalSubtab.tsx",
        "web/src/components/Dashboard/MonitoringSubtab.tsx",
        # Active Admin control-plane surfaces
        "web/src/components/Admin/ConfigBasicsSubtab.tsx",
        "web/src/components/Admin/ConfigExplorerSubtab.tsx",
        "web/src/components/Admin/ConfigRawSubtab.tsx",
        "web/src/components/Admin/DependenciesSubtab.tsx",
        # Docker UI (mini-Portainer)
        "web/src/components/Infrastructure/DockerSubtab.tsx",
    ]

    changed_set = set(changed)
    selected: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p in seen:
            return
        if p not in changed_set:
            return
        selected.append(p)
        seen.add(p)

    for p in preferred:
        add(p)
        if len(selected) >= limit:
            return selected[:limit]

    # Prefer server/ and web/ files next (in the original diff ordering).
    for prefix in ("server/", "web/"):
        for p in changed:
            if p.startswith(prefix):
                add(p)
                if len(selected) >= limit:
                    return selected[:limit]

    for p in changed:
        add(p)
        if len(selected) >= limit:
            break

    return selected[:limit]


def _all_docs_context(*, budget_chars: int) -> tuple[list[str], int]:
    """Quote the current text of every docs page, newest-shallowest first.

    The single highest-leverage input: a model can only emit context lines that
    apply if it can see the exact bytes. The whole corpus is ~580 KB (~145k
    tokens) against a 1M-token window, so it fits with room to spare. Returns
    the blocks plus the number of pages the budget could not fit.
    """

    docs_dir = ROOT / "mkdocs" / "docs"
    if not docs_dir.exists():
        return [], 0

    pages = sorted(docs_dir.rglob("*.md"), key=lambda q: (len(q.relative_to(docs_dir).parts), q.as_posix()))
    blocks: list[str] = []
    spent = 0
    omitted = 0
    for page in pages:
        content = _read_text(page)
        if not content.strip():
            continue
        rel = page.relative_to(docs_dir).as_posix()
        block = f"### mkdocs/docs/{rel}\n```markdown\n{content}\n```"
        if spent + len(block) > budget_chars:
            omitted += 1
            continue
        blocks.append(block)
        spent += len(block)
    return blocks, omitted


def _selected_docs_context(*, rel_paths: list[str] | None = None, max_chars_per_file: int = 7000) -> list[str]:
    """Return a named set of existing docs content (used for targeted excerpts)."""

    docs_dir = ROOT / "mkdocs" / "docs"
    if not docs_dir.exists():
        return []

    if rel_paths is None:
        rel_paths = [
            "index.md",
            "manual/index.md",
            "manual/quickstart.md",
            "manual/indexing.md",
            "manual/search.md",
            "manual/ui.md",
            "manual/troubleshooting.md",
            "architecture.md",
            "retrieval/overview.md",
            "indexing.md",
            "configuration.md",
            "api.md",
            "operations.md",
            "deployment.md",
            "security.md",
            "troubleshooting.md",
            "eval_guide.md",
            "howto/reranker.md",
            "observability.md",
        ]

    blocks: list[str] = []
    for rel in rel_paths:
        p = docs_dir / rel
        if not p.exists():
            continue
        content = _read_text(p)
        if not content.strip():
            continue
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + "\n\n... [truncated]\n"
        blocks.append(f"### mkdocs/docs/{rel}\n{content}")
    return blocks


def build_plan(base_ref: str) -> str:
    base_norm = normalize_base_ref(base_ref)
    changed = git_diff_names(base_norm)
    mkdocs_yml = _read_text(ROOT / "mkdocs.yml")
    prompt_base = _read_text(PROMPT_BASE_PATH)

    is_bootstrap = base_norm == EMPTY_TREE

    budget_tokens = int(os.getenv("DOCS_AUTOPILOT_CONTEXT_BUDGET_TOKENS", str(DEFAULT_CONTEXT_BUDGET_TOKENS)))
    budget_chars = max(0, budget_tokens) * CHARS_PER_TOKEN
    # Reserve for the fixed sections (mkdocs.yml, tree listing, prompt base,
    # screenshot list, changed-file list) before the two large pools.
    fixed_reserve = 250_000
    docs_budget = max(0, int((budget_chars - fixed_reserve) * DOCS_CONTEXT_BUDGET_SHARE))
    docs_context, docs_omitted = _all_docs_context(budget_chars=docs_budget)
    diff_budget = max(0, budget_chars - fixed_reserve - sum(len(b) for b in docs_context))

    # Fill the remaining window with code diffs in priority order, then say
    # exactly what did not fit. A silent cap reads as "everything is covered".
    diffs: list[str] = []
    diff_spent = 0
    diff_candidates = _select_context_files(changed, limit=DIFF_CONTEXT_FILE_LIMIT)
    diffs_omitted = 0
    for path in diff_candidates:
        d = git_diff_text(base_norm, path, max_chars=PER_FILE_DIFF_CHAR_LIMIT)
        if not d:
            continue
        block = f"### {path}\n{d}"
        if diff_spent + len(block) > diff_budget:
            diffs_omitted += 1
            continue
        diffs.append(block)
        diff_spent += len(block)

    changed_preview = changed[:CHANGED_FILES_LIST_LIMIT]
    changed_more = max(0, len(changed) - len(changed_preview))

    bootstrap_note: list[str] = []
    if is_bootstrap:
        bootstrap_note = [
            "## Bootstrap mode",
            "Base ref resolved to the **git empty tree**. This run should treat the whole repo as new and do a one-time docs catch-up.",
            "After this catch-up, normal pushes should go back to small incremental diffs.",
            "",
        ]

    # Short excerpts from high-traffic pages, called out separately from the
    # full corpus below so the model treats their structure as load-bearing.
    preserve_context = _selected_docs_context(
        rel_paths=[
            "index.md",
            "manual/ui.md",
            "manual/indexing.md",
        ],
        max_chars_per_file=3500,
    )
    screenshot_assets = scan_screenshot_assets(limit=400)

    sections: list[str] = [
        "# Docs Autopilot Plan (diff-driven)",
        f"Base: {base_ref}" + (f" (resolved: {base_norm})" if base_norm != base_ref else ""),
        "",
        *bootstrap_note,
        "## Changed files (filtered)",
        *([f"- {p}" for p in changed_preview] or ["- (none)"]),
        *(["- ... and " + str(changed_more) + " more (truncated)"] if changed_more else []),
        "",
        "## Current MkDocs config (mkdocs.yml)",
        mkdocs_yml or "(mkdocs.yml not found)",
        "",
        "## Current docs tree (mkdocs/docs)",
        *(scan_docs_tree() or ["- (mkdocs/docs not found)"]),
        "",
        "## Screenshot assets (docs + web)",
        *(screenshot_assets or ["- (no screenshot assets found)"]),
        "",
        "## Existing high-traffic docs excerpts (preserve structure; edit minimally)",
        *(preserve_context or ["- (no preserve context pages found)"]),
        "",
        "## Current docs content (verbatim - copy context lines from here)",
        f"{len(docs_context)} page(s) quoted in full"
        + (f"; {docs_omitted} omitted for context budget" if docs_omitted else "; none omitted"),
        "",
        *(docs_context or ["- (no docs pages found)"]),
        "",
        "## Prompt base (docs_prompt_base.md)",
        prompt_base or "(missing scripts/docs_ai/docs_prompt_base.md)",
        "",
        "## Code diffs",
        f"{len(diffs)} file diff(s) included"
        + (f"; {diffs_omitted} omitted for context budget" if diffs_omitted else "; none omitted"),
        "",
        *(diffs or ["(no diffs captured)"]),
    ]
    return "\n".join(sections).strip() + "\n"


def _parse_diff_paths(patch_text: str) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    for line in (patch_text or "").splitlines():
        if not line.startswith("diff --git "):
            continue
        # diff --git a/<old> b/<new>
        parts = line.split()
        if len(parts) < 4:
            continue
        a_path = parts[2].removeprefix("a/").strip()
        b_path = parts[3].removeprefix("b/").strip()
        paths.append((a_path, b_path))
    return paths


def _validate_patch_paths(patch_text: str) -> list[str]:
    text = (patch_text or "").lstrip()
    if text.startswith("*** Begin Patch"):
        return _validate_cursor_patch_paths(patch_text)

    errors: list[str] = []
    for a_path, b_path in _parse_diff_paths(patch_text):
        for p in (a_path, b_path):
            if p == "/dev/null":
                continue
            if p == "mkdocs.yml":
                continue
            if p.startswith("mkdocs/docs/"):
                continue
            errors.append(f"Patch modifies disallowed path: {p}")
    return errors


def _validate_cursor_patch_paths(patch_text: str) -> list[str]:
    errors: list[str] = []
    for raw in (patch_text or "").splitlines():
        line = raw.strip()
        for prefix in ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "):
            if not line.startswith(prefix):
                continue
            p = line.removeprefix(prefix).strip().replace("\\", "/")
            if not p:
                errors.append("Cursor patch contains an empty path.")
                continue
            if p.startswith("/"):
                errors.append(f"Cursor patch uses absolute path: {p}")
                continue
            if p == "mkdocs.yml" or p.startswith("mkdocs/docs/"):
                continue
            errors.append(f"Patch modifies disallowed path: {p}")
    return errors


def _cursor_patch_line_stats(patch_text: str) -> dict[str, dict[str, int]]:
    """Return per-file added/removed line counts from Cursor-style patch format."""

    stats: dict[str, dict[str, int]] = {}
    current_path: str | None = None
    current_mode: str | None = None  # add | update

    for raw in (patch_text or "").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("*** Add File: "):
            current_path = stripped.removeprefix("*** Add File: ").strip().replace("\\", "/")
            current_mode = "add"
            stats.setdefault(current_path, {"added": 0, "removed": 0})
            continue
        if stripped.startswith("*** Update File: "):
            current_path = stripped.removeprefix("*** Update File: ").strip().replace("\\", "/")
            current_mode = "update"
            stats.setdefault(current_path, {"added": 0, "removed": 0})
            continue
        if stripped.startswith("*** Delete File: "):
            current_path = stripped.removeprefix("*** Delete File: ").strip().replace("\\", "/")
            current_mode = None
            existing = _read_text(ROOT / current_path)
            removed_lines = len(existing.splitlines()) if existing else 1
            stats.setdefault(current_path, {"added": 0, "removed": removed_lines})
            continue
        if stripped.startswith("*** "):
            current_path = None
            current_mode = None
            continue
        if current_path is None:
            continue

        if current_mode == "add":
            if line.startswith("+"):
                stats[current_path]["added"] += 1
            continue
        if current_mode == "update":
            if line.startswith("+"):
                stats[current_path]["added"] += 1
            elif line.startswith("-"):
                stats[current_path]["removed"] += 1

    return stats


def _patch_line_stats(patch_text: str) -> dict[str, dict[str, int]]:
    """Return per-file added/removed line counts from a unified diff."""

    text = (patch_text or "").lstrip()
    if text.startswith("*** Begin Patch"):
        return _cursor_patch_line_stats(patch_text)

    stats: dict[str, dict[str, int]] = {}
    current_add_path: str | None = None
    current_del_path: str | None = None

    for raw in (patch_text or "").splitlines():
        line = raw.rstrip("\n")
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) < 4:
                current_add_path = None
                current_del_path = None
                continue
            a_path = parts[2].removeprefix("a/").strip()
            b_path = parts[3].removeprefix("b/").strip()
            # Track additions on destination path and deletions on source path.
            # This preserves safety checks for renames (a -> b) where deletions
            # should still count against the original protected page.
            current_add_path = b_path if b_path != "/dev/null" else a_path
            current_del_path = a_path if a_path != "/dev/null" else b_path
            if current_add_path:
                stats.setdefault(current_add_path, {"added": 0, "removed": 0})
            if current_del_path:
                stats.setdefault(current_del_path, {"added": 0, "removed": 0})
            continue

        if current_add_path is None and current_del_path is None:
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+") and current_add_path:
            stats[current_add_path]["added"] += 1
        elif line.startswith("-") and current_del_path:
            stats[current_del_path]["removed"] += 1

    return stats


def _validate_patch_safety(patch_text: str, *, allow_large_deletes: bool) -> list[str]:
    """Reject suspiciously destructive docs rewrites in normal incremental mode."""

    if allow_large_deletes:
        return []

    errors: list[str] = []
    stats = _patch_line_stats(patch_text)

    for path, counts in stats.items():
        removed = counts.get("removed", 0)
        added = counts.get("added", 0)
        if removed == 0:
            continue

        protected_limit = PROTECTED_DOC_DELETE_LIMITS.get(path)
        if protected_limit is not None and removed > protected_limit:
            errors.append(
                f"Patch removes {removed} lines from protected page {path} (limit {protected_limit}). "
                "Prefer additive, targeted edits."
            )

        # Global guard: very large removals with tiny additions usually signal an
        # accidental full-page rewrite in incremental mode.
        if removed > GENERAL_DELETE_LIMIT and added < max(30, int(removed * 0.4)):
            errors.append(
                f"Patch appears overly destructive for {path} (removed={removed}, added={added}). "
                "Refusing likely rewrite."
            )

    return errors


PATCH_START_RE = re.compile(r"^(?:diff --git |\*\*\* Begin Patch)", re.MULTILINE)
# The closing fence must start a line: inside a diff every content line is
# prefixed (+/-/space), so a fence the model quoted inside a docs page
# (`+```mermaid`) never sits at column 0 and cannot end the wrapper early.
FENCE_RE = re.compile(r"```[^\n]*\n(.*?)^```", re.DOTALL | re.MULTILINE)


def _extract_unified_diff(text: str) -> str:
    """Pull the patch out of a model reply.

    Models wrap patches in code fences and top-and-tail them with prose. Both
    have to be stripped: git reads the file literally, so one stray "Here you
    go:" line makes the whole patch corrupt.
    """
    if not text:
        return ""

    # Prefer a fenced block that actually contains a patch (```diff, ```patch,
    # or an unlabelled fence) over anything quoted elsewhere in the reply.
    for match in FENCE_RE.finditer(text):
        block = match.group(1)
        if PATCH_START_RE.search(block):
            start = PATCH_START_RE.search(block).start()
            return block[start:].strip() + "\n"

    # Otherwise take everything from the first patch marker, dropping a
    # trailing fence and any sign-off after it.
    marker = PATCH_START_RE.search(text)
    if marker:
        body = text[marker.start() :]
        fence_end = body.find("\n```")
        if fence_end != -1:
            body = body[:fence_end]
        return body.strip() + "\n"

    return text.strip() + "\n"


def response_output_text(data: object) -> str:
    """Read the assistant text out of a Responses API payload.

    Refuses anything the provider did not finish. A patch cut off mid-hunk is
    not a smaller patch: `git apply --recount` would renumber the truncated
    hunk and land a half-written page, so truncation has to die here.
    """
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response format: {type(data)}")

    error = data.get("error")
    if error:
        raise RuntimeError(f"Provider returned an error: {error}")

    status = data.get("status")
    if status is not None and status != "completed":
        detail = data.get("incomplete_details") or {}
        reason = detail.get("reason") if isinstance(detail, dict) else None
        raise RuntimeError(
            f"Model response did not complete (status={status}, reason={reason or 'unknown'}). "
            "Raise DOCS_AUTOPILOT_MAX_OUTPUT_TOKENS or narrow the base range; "
            "a truncated patch is never applied."
        )

    out_text = data.get("output_text")
    if isinstance(out_text, str) and out_text.strip():
        return out_text.strip()

    chunks: list[str] = []
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            # Reasoning blocks arrive as `reasoning_text`; only the message counts.
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text", "")
                if text:
                    chunks.append(str(text))
    if chunks:
        return "\n".join(chunks).strip()

    raise RuntimeError("Model returned no output text.")


PAGE_REPAIR_SYSTEM_PROMPT = (
    "You are repairing documentation pages for ragweld whose unified-diff hunks git could not apply.\n"
    "For EACH page listed in the request, return its COMPLETE new content - the whole page, not a diff.\n"
    "Start every page with a line `### FILE: <path>` and end it with a line `### END FILE`.\n"
    "Keep everything on the page that the request did not ask you to change; apply only the intended edits.\n"
    "Markdown code fences inside the page are fine. Output nothing outside the FILE blocks.\n"
)

PAGE_BLOCK_RE = re.compile(r"^### FILE: (?P<path>[^\n]+)\n(?P<body>.*?)^### END FILE[ \t]*$", re.MULTILINE | re.DOTALL)


def call_llm_unified_diff(prompt: str) -> str:
    base_prompt = _read_text(PROMPT_BASE_PATH).strip()
    system_prompt = (
        (base_prompt + "\n\n") if base_prompt else ""
    ) + (
        "You are generating documentation updates for ragweld based on code changes.\n"
        "Use 'ragweld' (not 'tribrid' or 'TriBridRAG') as the product name in all doc text.\n"
        "Position ragweld as an MLOps Engineering Platform for retrieval and agent systems, not as retrieval-only tooling.\n"
        "Frame integrations as API first and MCP second: API is the primary contract, MCP is an overlay for agent ecosystems.\n"
        "Prefer targeted, additive edits; do not rewrite entire pages unless bootstrap mode explicitly requires it.\n"
        "Preserve structure on high-traffic pages (index.md, manual/ui.md, manual/indexing.md) and edit only relevant sections.\n"
        "When screenshot assets are present under mkdocs/docs/assets/images/, keep screenshot references/captions aligned with docs.\n"
        "You may create, move, or delete pages and restructure folders, and you may update mkdocs.yml nav accordingly.\n"
        "Only modify MkDocs sources: mkdocs/docs/** and mkdocs.yml.\n"
        "The plan quotes the full current text of every page, so copy context lines verbatim from it.\n"
        "Output ONLY a standard git unified diff patch suitable for `git apply`.\n"
        "Your output MUST use git patch headers: `diff --git a/path b/path`.\n"
        "Hunk line counts are recomputed on apply, but every context line must match the quoted page exactly.\n"
        "No stray characters, no code fences, no commentary.\n"
        "Finish every hunk you start; never stop mid-patch.\n"
        "The result must pass `mkdocs build --strict`.\n"
    )
    return call_llm(prompt, system_prompt=system_prompt)


def call_llm_pages(prompt: str) -> str:
    base_prompt = _read_text(PROMPT_BASE_PATH).strip()
    return call_llm(prompt, system_prompt=((base_prompt + "\n\n") if base_prompt else "") + PAGE_REPAIR_SYSTEM_PROMPT)


def call_llm(prompt: str, *, system_prompt: str) -> str:
    import requests

    from server.model_policy import ensure_model_allowed

    _maybe_load_dotenv()

    model = os.getenv("DOCS_AUTOPILOT_MODEL", DEFAULT_MODEL)
    ensure_model_allowed(model)

    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. In CI add it with: "
            "gh secret set OPENROUTER_API_KEY --repo <owner>/<repo>"
        )

    url = (os.getenv("DOCS_AUTOPILOT_API_BASE", DEFAULT_API_BASE).rstrip("/") + "/responses")
    max_output_tokens = int(os.getenv("DOCS_AUTOPILOT_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)))

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "instructions": system_prompt,
        "input": prompt,
        "text": {"verbosity": os.getenv("DOCS_AUTOPILOT_VERBOSITY", "high")},
        "reasoning": {"effort": os.getenv("DOCS_AUTOPILOT_REASONING_EFFORT", "high")},
        "max_output_tokens": max_output_tokens,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=int(os.getenv("DOCS_AUTOPILOT_HTTP_TIMEOUT_SECONDS", "1800")))
    r.raise_for_status()
    return response_output_text(r.json())


def _is_allowed_patch_path(path: str) -> bool:
    return path == "mkdocs.yml" or path.startswith("mkdocs/docs/")


@dataclass(frozen=True)
class _CursorPatchOperation:
    kind: str
    path: str
    content: str | None = None
    move_to: str | None = None


def _parse_cursor_style_patch(patch_text: str) -> list[_CursorPatchOperation]:
    """Parse a Cursor-style patch into validated in-memory operations."""

    raw_lines = (patch_text or "").splitlines()
    if not raw_lines or raw_lines[0].strip() != "*** Begin Patch":
        raise RuntimeError("Not a Cursor-style patch (missing '*** Begin Patch').")

    i = 1
    operations: list[_CursorPatchOperation] = []

    def _validate_rel_path(p: str) -> str:
        p = (p or "").strip().replace("\\", "/")
        if not p:
            raise RuntimeError("Patch contains an empty path.")
        if p.startswith("/"):
            raise RuntimeError(f"Refusing absolute path in patch: {p}")
        parts = Path(p).parts
        if any(part == ".." for part in parts):
            raise RuntimeError(f"Refusing path traversal in patch: {p}")
        if not _is_allowed_patch_path(p):
            raise RuntimeError(f"Patch modifies disallowed path: {p}")
        return p

    while i < len(raw_lines):
        line = raw_lines[i].strip("\n")
        if line.strip() == "*** End Patch":
            break
        if line.strip() == "":
            i += 1
            continue

        def _find_subsequence(haystack: list[str], needle: list[str]) -> int | None:
            if not needle:
                return None
            for start in range(0, len(haystack) - len(needle) + 1):
                if haystack[start : start + len(needle)] == needle:
                    return start
            return None

        if line.startswith("*** Add File: "):
            rel_path = _validate_rel_path(line.removeprefix("*** Add File: ").strip())
            i += 1
            content_lines: list[str] = []
            while i < len(raw_lines):
                nxt = raw_lines[i]
                if nxt.startswith("*** "):
                    break
                if not nxt.startswith("+"):
                    raise RuntimeError(f"Invalid add-file line (missing '+') for {rel_path}: {nxt[:80]}")
                content_lines.append(nxt[1:])
                i += 1

            operations.append(
                _CursorPatchOperation(
                    kind="add",
                    path=rel_path,
                    content="\n".join(content_lines) + "\n",
                )
            )
            continue

        if line.startswith("*** Update File: "):
            rel_path = _validate_rel_path(line.removeprefix("*** Update File: ").strip())
            full_path = ROOT / rel_path
            if not full_path.exists():
                raise RuntimeError(f"Update File refers to missing path: {rel_path}")

            file_lines = _read_text(full_path).splitlines()
            i += 1
            move_to: str | None = None
            if i < len(raw_lines) and raw_lines[i].startswith("*** Move to: "):
                move_to = _validate_rel_path(raw_lines[i].removeprefix("*** Move to: ").strip())
                i += 1

            while i < len(raw_lines):
                if raw_lines[i].startswith("*** "):
                    break
                if raw_lines[i].strip() == "*** End Patch":
                    break

                # Each hunk begins with one or more @@ context lines.
                if not raw_lines[i].startswith("@@"):
                    # Allow blank/noise lines between hunks.
                    if raw_lines[i].strip() == "":
                        i += 1
                        continue
                    raise RuntimeError(f"Expected '@@' hunk header in Update File for {rel_path}, got: {raw_lines[i][:80]}")

                while i < len(raw_lines) and raw_lines[i].startswith("@@"):
                    i += 1

                hunk_lines: list[str] = []
                while i < len(raw_lines) and not raw_lines[i].startswith("@@") and not raw_lines[i].startswith("*** "):
                    hl = raw_lines[i]
                    if not hl:
                        raise RuntimeError(f"Invalid empty hunk line in Update File for {rel_path}")
                    if hl[0] not in {" ", "+", "-"}:
                        raise RuntimeError(f"Invalid hunk line prefix in Update File for {rel_path}: {hl[:80]}")
                    hunk_lines.append(hl)
                    i += 1

                old_seq = [line[1:] for line in hunk_lines if line[0] in {" ", "-"}]
                new_seq = [line[1:] for line in hunk_lines if line[0] in {" ", "+"}]
                if not old_seq and not new_seq:
                    continue

                pos = _find_subsequence(file_lines, old_seq)
                if pos is None:
                    preview_old = "\n".join(old_seq[:20])
                    raise RuntimeError(
                        "Failed to apply Cursor-style hunk: could not find expected context in file.\n"
                        f"Path: {rel_path}\n"
                        f"Expected (old) snippet (truncated):\n{preview_old}\n"
                    )

                file_lines = file_lines[:pos] + new_seq + file_lines[pos + len(old_seq) :]

            operations.append(
                _CursorPatchOperation(
                    kind="move" if move_to else "update",
                    path=rel_path,
                    content="\n".join(file_lines) + "\n",
                    move_to=move_to,
                )
            )
            continue

        if line.startswith("*** Delete File: "):
            rel_path = _validate_rel_path(line.removeprefix("*** Delete File: ").strip())
            full_path = ROOT / rel_path
            if not full_path.exists():
                raise RuntimeError(f"Delete File refers to missing path: {rel_path}")
            operations.append(_CursorPatchOperation(kind="delete", path=rel_path))
            i += 1
            continue

        raise RuntimeError(f"Unrecognized patch directive: {line[:120]}")

    return operations


def _apply_cursor_style_patch(patch_text: str) -> list[str]:
    """Apply Cursor-style patch format transactionally.

    This format is sometimes returned by LLMs even when asked for `git apply`
    patches. We validate the entire patch in memory first so failures cannot
    leave partially written docs behind.
    """

    operations = _parse_cursor_style_patch(patch_text)
    touched: list[str] = []

    for operation in operations:
        full_path = ROOT / operation.path

        if operation.kind == "add":
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(operation.content or "", encoding="utf-8")
            touched.append(operation.path)
            continue

        if operation.kind == "update":
            full_path.write_text(operation.content or "", encoding="utf-8")
            touched.append(operation.path)
            continue

        if operation.kind == "delete":
            full_path.unlink()
            touched.append(operation.path)
            continue

        if operation.kind == "move":
            move_to = operation.move_to
            if not move_to:
                raise RuntimeError(f"Move operation missing destination for {operation.path}")
            target_path = ROOT / move_to
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(operation.content or "", encoding="utf-8")
            full_path.unlink()
            touched.extend([operation.path, move_to])
            continue

        raise RuntimeError(f"Unsupported Cursor patch operation: {operation.kind}")

    # Stage touched files, including deletions/moves.
    for rel in dict.fromkeys(touched):
        run(f"git add -A -- {shlex.quote(rel)}")

    return touched


def apply_patch(patch_path: Path) -> tuple[bool, str]:
    """Apply patch. Returns (success, error_message)."""
    patch_text = _read_text(patch_path)
    if (patch_text or "").lstrip().startswith("*** Begin Patch"):
        try:
            _apply_cursor_style_patch(patch_text)
            return True, ""
        except Exception as e:
            return False, str(e)

    try:
        # --recount: models miscount `@@` headers routinely and git otherwise
        # rejects the whole patch as corrupt. Context lines still have to match,
        # so this fixes arithmetic without accepting invented content.
        run(f"git apply --recount --index {shlex.quote(str(patch_path))}")
        return True, ""
    except RuntimeError as e:
        err = str(e)
        # Try Cursor-style as fallback if patch looks like it might be that format
        if "*** Begin Patch" in (patch_text or ""):
            try:
                _apply_cursor_style_patch(patch_text)
                return True, ""
            except Exception as fallback_e:
                return False, f"git apply: {err}\nCursor fallback: {fallback_e}"
        return False, err


@dataclass(frozen=True)
class PerFileApplyResult:
    applied: list[str]
    rejected: dict[str, str]
    # The rejected files' hunks, verbatim, so a repair round can show the model
    # exactly what it sent.
    rejected_patch_text: str


def _split_patch_by_file(patch_text: str) -> list[tuple[str, str]]:
    """Split a git unified diff into (path, chunk) pairs, one per `diff --git`."""
    chunks: list[tuple[str, str]] = []
    cur_path: str | None = None
    cur_lines: list[str] = []
    for line in (patch_text or "").splitlines(keepends=True):
        if line.startswith("diff --git "):
            if cur_path is not None:
                chunks.append((cur_path, "".join(cur_lines)))
            parts = line.split()
            a_path = parts[2].removeprefix("a/").strip() if len(parts) > 2 else ""
            b_path = parts[3].removeprefix("b/").strip() if len(parts) > 3 else ""
            cur_path = b_path if b_path and b_path != "/dev/null" else a_path
            cur_lines = [line]
        elif cur_path is not None:
            cur_lines.append(line)
    if cur_path is not None:
        chunks.append((cur_path, "".join(cur_lines)))
    return chunks


def _git_apply_error(message: str) -> str:
    """Keep only git's `error:` lines; the command echo is noise in a warning."""
    lines = [ln.strip() for ln in (message or "").splitlines() if ln.strip().startswith("error:")]
    return "\n".join(lines) or (message or "").strip() or "git apply rejected the hunk"


def apply_patch_per_file(patch_path: Path) -> PerFileApplyResult:
    """Apply a model patch one file at a time.

    `git apply` is all-or-nothing: on 2026-08-29 five hunks whose context the
    model had "pre-edited" threw away eleven clean pages and left the documented
    frontier pinned at March. Each file is its own `git apply --index` here, so
    clean pages land and the rejected ones are reported (and offered a repair
    round) instead of sinking the run.
    """
    patch_text = _read_text(patch_path)
    if (patch_text or "").lstrip().startswith("*** Begin Patch"):
        ops = _parse_cursor_style_patch(patch_text)
        paths = sorted({op.path for op in ops})
        ok, err = apply_patch(patch_path)
        if ok:
            return PerFileApplyResult(applied=paths, rejected={}, rejected_patch_text="")
        return PerFileApplyResult(applied=[], rejected={p: err for p in paths}, rejected_patch_text=patch_text)

    applied: list[str] = []
    rejected: dict[str, str] = {}
    rejected_chunks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="docs-autopilot-apply-") as td:
        for i, (path, chunk) in enumerate(_split_patch_by_file(patch_text)):
            tmp = Path(td) / f"chunk-{i:03d}.diff"
            tmp.write_text(chunk if chunk.endswith("\n") else chunk + "\n", encoding="utf-8")
            try:
                run(f"git apply --recount --index {shlex.quote(str(tmp))}")
                applied.append(path)
            except RuntimeError as e:
                rejected[path] = _git_apply_error(str(e))
                rejected_chunks.append(chunk)
    return PerFileApplyResult(applied=applied, rejected=rejected, rejected_patch_text="".join(rejected_chunks))


_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(\s+\"[^\"]*\")?\)")
_NAV_ITEM_RE = re.compile(r"^(\s*)- [^:]+: ([^\s].*?\.md)\s*$")
_NAV_SECTION_RE = re.compile(r"^(\s*)- [^:]+:\s*$")


@dataclass
class LinkRepairReport:
    fixed: list[tuple[str, str, str]]
    unwrapped: list[tuple[str, str]]
    nav_pruned: list[str]
    changed_files: list[str]


def _is_relative_doc_link(target: str) -> bool:
    t = (target or "").strip()
    if not t or t.startswith(("#", "/", "mailto:", "tel:", "data:")) or "://" in t:
        return False
    return True


def _prune_nav(mkdocs_yml: Path, docs_dir: Path) -> list[str]:
    """Drop nav entries whose page does not exist, and sections left empty by that.

    mkdocs.yml carries `!!python/name:` tags, so this is a line pass over the
    `nav:` block rather than a YAML round-trip.
    """
    lines = mkdocs_yml.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(r"^nav:\s*$", ln)), None)
    if start is None:
        return []
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^[A-Za-z_]", lines[i])), len(lines))
    nav = lines[start + 1 : end]
    pruned: list[str] = []
    kept: list[str] = []
    for ln in nav:
        m = _NAV_ITEM_RE.match(ln)
        if m and not (docs_dir / m.group(2).strip()).exists():
            pruned.append(m.group(2).strip())
            continue
        kept.append(ln)
    # A section header is empty when the next non-blank line is not indented deeper.
    result: list[str] = []
    for i, ln in enumerate(kept):
        m = _NAV_SECTION_RE.match(ln)
        if m:
            indent = len(m.group(1))
            nxt = next((k for k in kept[i + 1 :] if k.strip()), None)
            if nxt is None or (len(nxt) - len(nxt.lstrip(" "))) <= indent:
                pruned.append(ln.strip())
                continue
        result.append(ln)
    if pruned:
        mkdocs_yml.write_text("".join(lines[: start + 1] + result + lines[end:]), encoding="utf-8")
    return pruned


def repair_docs_links(root: Path) -> LinkRepairReport:
    """Make relative links resolve before `mkdocs build --strict` sees them.

    Run 33262983828 landed 15 pages and lost all of them to one link:
    `manual/onboarding.md` pointed at `eval.md` when the page is
    `guides/eval.md`. A dangling `.md` link whose basename exists exactly once
    is rewritten to that page; anything else is unwrapped to plain text with a
    warning; nav entries with no page are pruned. Assets and external URLs are
    left for mkdocs to judge.
    """
    docs_dir = root / "mkdocs" / "docs"
    report = LinkRepairReport(fixed=[], unwrapped=[], nav_pruned=[], changed_files=[])
    if not docs_dir.exists():
        return report
    pages = sorted(docs_dir.rglob("*.md"))
    by_name: dict[str, list[Path]] = {}
    for page in pages:
        by_name.setdefault(page.name, []).append(page)

    for page in pages:
        text = page.read_text(encoding="utf-8")
        rel_page = page.relative_to(root).as_posix()

        def _sub(m: re.Match[str], page: Path = page, rel_page: str = rel_page) -> str:
            label, target, title = m.group(1), m.group(2), m.group(3) or ""
            if not _is_relative_doc_link(target):
                return m.group(0)
            path_part, _, anchor = target.partition("#")
            if not path_part.lower().endswith(".md"):
                return m.group(0)
            if (page.parent / path_part).resolve().exists():
                return m.group(0)
            matches = by_name.get(Path(path_part).name, [])
            if len(matches) == 1:
                new_target = os.path.relpath(matches[0], page.parent).replace(os.sep, "/")
                if anchor:
                    new_target += f"#{anchor}"
                report.fixed.append((rel_page, target, new_target))
                return f"[{label}]({new_target}{title})"
            report.unwrapped.append((rel_page, target))
            return label

        new_text = _MD_LINK_RE.sub(_sub, text)
        if new_text != text:
            page.write_text(new_text, encoding="utf-8")
            report.changed_files.append(rel_page)

    mkdocs_yml = root / "mkdocs.yml"
    if mkdocs_yml.exists():
        pruned = _prune_nav(mkdocs_yml, docs_dir)
        if pruned:
            report.nav_pruned.extend(pruned)
            report.changed_files.append("mkdocs.yml")
    return report


def build_page_repair_prompt(*, rejected: dict[str, str], rejected_patch_text: str) -> str:
    """Ask for whole replacement pages for the files git still rejects after the diff repair round."""
    lines: list[str] = [
        "# Docs Autopilot Page Repair",
        "",
        "`git apply` rejected your diffs for the pages below even after a repair attempt, so return each page",
        "in full instead. For every page: the complete new content, applying the edits your rejected hunks",
        "intended, and keeping every other part of the page exactly as quoted. Use `### FILE: <path>` /",
        "`### END FILE` markers. Do not return any page that is not listed here.",
        "",
        "## Why each was rejected",
        *[f"- {path}: {err.splitlines()[0] if err else 'rejected'}" for path, err in rejected.items()],
        "",
        "## Your rejected hunks (the edits you intended)",
        "```diff",
        (rejected_patch_text or "").rstrip(),
        "```",
        "",
        "## Current page text (verbatim)",
    ]
    for path in rejected:
        current = _read_text(ROOT / path)
        if current:
            lines += [f"### {path}", "```markdown", current, "```", ""]
        else:
            lines += [f"### {path}", "(does not exist yet - return the complete new page)", ""]
    return "\n".join(lines).rstrip() + "\n"


def parse_page_blocks(text: str) -> dict[str, str]:
    """`### FILE: path` ... `### END FILE` blocks -> {path: content}. Fences inside a page are content."""
    pages: dict[str, str] = {}
    for m in PAGE_BLOCK_RE.finditer(text or ""):
        path = m.group("path").strip().strip("`").replace("\\", "/")
        body = m.group("body")
        if body and not body.endswith("\n"):
            body += "\n"
        pages[path] = body
    return pages


@dataclass(frozen=True)
class PageRepairResult:
    written: list[str]
    refused: dict[str, str]


def apply_page_replacements(pages: dict[str, str], *, allowed: set[str], allow_large_deletes: bool) -> PageRepairResult:
    """Write whole-page replacements for rejected files, under the same safety rules as a patch.

    The replacement is diffed against the page on disk so the delete limits that
    guard incremental runs apply to it exactly as they would to a hunk.
    """
    written: list[str] = []
    refused: dict[str, str] = {}
    for path, content in pages.items():
        if path not in allowed:
            refused[path] = "not one of the rejected pages"
            continue
        if not _is_allowed_patch_path(path):
            refused[path] = "outside mkdocs/docs"
            continue
        target = ROOT / path
        current = _read_text(target)
        synthetic = "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if not synthetic.strip():
            refused[path] = "identical to the current page"
            continue
        synthetic = f"diff --git a/{path} b/{path}\n" + synthetic
        errors = _validate_patch_safety(synthetic, allow_large_deletes=allow_large_deletes)
        if errors:
            refused[path] = "; ".join(errors)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(path)
    if written:
        run("git add -- " + " ".join(shlex.quote(p) for p in written))
    return PageRepairResult(written=written, refused=refused)


def build_repair_prompt(*, rejected: dict[str, str], rejected_patch_text: str) -> str:
    """Ask the model to re-emit only the files git rejected, against the real page text."""
    lines: list[str] = [
        "# Docs Autopilot Repair (rejected hunks)",
        "",
        "`git apply` rejected the hunks below: at least one context line in each does not match the",
        "page on disk (typically a context line that already contains the edit you intended to make).",
        "Re-emit a corrected git unified diff for ONLY the files listed here. Copy every context line",
        "verbatim from the current page text quoted below; express each change as -/+ line pairs.",
        "Output only the patch.",
        "",
        "## git apply errors",
        *[f"- {path}: {err.splitlines()[0] if err else 'rejected'}" for path, err in rejected.items()],
        "",
        "## Rejected hunks (what you sent)",
        "```diff",
        (rejected_patch_text or "").rstrip(),
        "```",
        "",
        "## Current page text (verbatim - copy context lines from here)",
    ]
    for path in rejected:
        current = _read_text(ROOT / path)
        if current:
            lines += [f"### {path}", "```markdown", current, "```", ""]
        else:
            lines += [f"### {path}", "(does not exist yet - emit it as a new-file diff against /dev/null)", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(prog="docs-autopilot", description="Diff-driven MkDocs autopilot for ragweld")
    ap.add_argument("--base", default="origin/main", help="Git ref to diff against (base..HEAD)")
    ap.add_argument("--llm", choices=["openrouter"], default=None, help="LLM provider (currently: openrouter)")
    ap.add_argument("--apply", action="store_true", help="Apply the returned patch with `git apply --index`")
    ap.add_argument("--apply-patch", default="", help="Apply an existing patch file and exit (no LLM call)")
    ap.add_argument("--output", default=str(PLAN_FILE.name), help="Plan output file (plan mode)")
    args = ap.parse_args()

    if args.apply_patch:
        patch_path = Path(args.apply_patch)
        if not patch_path.is_absolute():
            patch_path = ROOT / patch_path
        ok, err = apply_patch(patch_path)
        if not ok:
            _gh_error(f"Patch apply failed: {err}")
            raise SystemExit(1)
        print("Patch applied to index.")
        return

    plan = build_plan(args.base)

    # Plan-only mode
    if not args.llm:
        out_path = ROOT / args.output
        out_path.write_text(plan, encoding="utf-8")
        print(f"Wrote plan: {out_path.relative_to(ROOT)}")
        return

    # LLM mode -> patch
    llm_text = call_llm_unified_diff(plan)
    RAW_REPLY_FILE.write_text(llm_text, encoding="utf-8")
    patch_text = _extract_unified_diff(llm_text)
    if not patch_text.strip():
        print("LLM returned an empty patch. Assuming no docs update is needed.")
        PATCH_FILE.write_text("", encoding="utf-8")
        return

    path_errors = _validate_patch_paths(patch_text)
    if path_errors:
        raise RuntimeError("Refusing patch that touches non-doc paths:\n" + "\n".join(f"- {e}" for e in path_errors))

    safety_errors = _validate_patch_safety(
        patch_text,
        allow_large_deletes=is_bootstrap_base(args.base),
    )
    if safety_errors:
        raise RuntimeError(
            "Refusing suspiciously destructive docs patch:\n" + "\n".join(f"- {e}" for e in safety_errors)
        )

    PATCH_FILE.write_text(patch_text, encoding="utf-8")
    print(f"LLM patch saved: {PATCH_FILE.relative_to(ROOT)}")

    if args.apply:
        result = apply_patch_per_file(PATCH_FILE)
        repair_rounds = int(os.getenv("DOCS_AUTOPILOT_REPAIR_ROUNDS", "1"))
        for attempt in range(1, repair_rounds + 1):
            if not result.rejected:
                break
            print(
                f"Repair round {attempt}: git apply rejected {len(result.rejected)} file(s); "
                "asking the model to re-emit them against the current page text."
            )
            repair_reply = call_llm_unified_diff(
                build_repair_prompt(rejected=result.rejected, rejected_patch_text=result.rejected_patch_text)
            )
            REPAIR_RAW_REPLY_FILE.write_text(repair_reply, encoding="utf-8")
            repair_patch = _extract_unified_diff(repair_reply)
            if not repair_patch.strip():
                print("Repair round returned an empty patch.")
                break
            repair_errors = _validate_patch_paths(repair_patch) + _validate_patch_safety(
                repair_patch, allow_large_deletes=is_bootstrap_base(args.base)
            )
            if repair_errors:
                print("Repair patch refused:\n" + "\n".join(f"- {e}" for e in repair_errors))
                break
            REPAIR_PATCH_FILE.write_text(repair_patch, encoding="utf-8")
            again = apply_patch_per_file(REPAIR_PATCH_FILE)
            # Files the model did not re-emit stay rejected with their original
            # error; files it re-emitted but git still refuses carry the new one.
            still_rejected = {p: e for p, e in result.rejected.items() if p not in again.applied}
            still_rejected.update(again.rejected)
            result = PerFileApplyResult(
                applied=result.applied + again.applied,
                rejected=still_rejected,
                rejected_patch_text=again.rejected_patch_text or result.rejected_patch_text,
            )

        if result.rejected and os.getenv("DOCS_AUTOPILOT_PAGE_REPAIR", "1") == "1":
            print(f"Page repair: asking the model for whole replacement pages for {len(result.rejected)} file(s).")
            page_reply = call_llm_pages(
                build_page_repair_prompt(rejected=result.rejected, rejected_patch_text=result.rejected_patch_text)
            )
            PAGE_REPAIR_RAW_REPLY_FILE.write_text(page_reply, encoding="utf-8")
            pages = parse_page_blocks(page_reply)
            outcome = apply_page_replacements(
                pages, allowed=set(result.rejected), allow_large_deletes=is_bootstrap_base(args.base)
            )
            for path, why in outcome.refused.items():
                print(f"Page repair refused {path}: {why}")
            still = {p: e for p, e in result.rejected.items() if p not in outcome.written}
            for path in outcome.written:
                print(f"Page repair wrote {path}")
            result = PerFileApplyResult(
                applied=result.applied + outcome.written, rejected=still, rejected_patch_text=result.rejected_patch_text
            )

        for path, err in result.rejected.items():
            first = err.splitlines()[0] if err else "git apply rejected it"
            print(f"::warning::docs-autopilot: dropped {path}: {first}")
        print(f"AUTOPILOT_APPLY_SUMMARY: applied={len(result.applied)} rejected={len(result.rejected)}")

        if result.applied:
            links = repair_docs_links(ROOT)
            for page, old, new in links.fixed:
                print(f"Link repaired in {page}: {old} -> {new}")
            for page, old in links.unwrapped:
                print(f"::warning::docs-autopilot: unresolvable link {old} in {page} unwrapped to plain text")
            for entry in links.nav_pruned:
                print(f"::warning::docs-autopilot: nav entry pruned (no such page): {entry}")
            if links.changed_files:
                run("git add -- " + " ".join(shlex.quote(p) for p in links.changed_files))
            print(
                f"AUTOPILOT_LINK_REPAIR: fixed={len(links.fixed)} unwrapped={len(links.unwrapped)} "
                f"nav_pruned={len(links.nav_pruned)}"
            )
        if not result.applied:
            _gh_error("Docs autopilot: no file of the LLM patch could be applied (corrupt or incompatible).")
            for path, err in result.rejected.items():
                _gh_error(f"{path}: {err}")
            raise SystemExit(1)
        dropped = f"; dropped {len(result.rejected)}" if result.rejected else ""
        print(f"Patch applied to index: {len(result.applied)} file(s){dropped}.")


if __name__ == "__main__":
    main()
