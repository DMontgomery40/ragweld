#!/usr/bin/env python3
"""
Docs Autopilot for TriBridRAG — diff-driven documentation updates.

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
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[2]
PROMPT_BASE_PATH = ROOT / "scripts" / "docs_ai" / "docs_prompt_base.md"

PATCH_FILE = ROOT / "mkdocs-docs-llm.patch"
PLAN_FILE = ROOT / "mkdocs-docs-plan.md"

ALLOWED_PATH_PREFIXES = (
    "mkdocs/docs/",
    "mkdocs.yml",
)

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
    "models/",
    "CLEANUP_PLANS/",
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


def run(cmd: str, *, check: bool = True) -> str:
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}\n{p.stderr}")
    return p.stdout


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def should_include_file(path: str) -> bool:
    p = (path or "").replace("\\", "/")
    p_lower = p.lower()
    if p_lower.startswith("mkdocs/") or p_lower.startswith("site/"):
        return False
    if any(seg in p_lower for seg in EXCLUDE_SUBSTRINGS):
        return False
    if any(p_lower.endswith(suf) for suf in EXCLUDE_SUFFIXES):
        return False
    return True


def git_diff_names(base: str) -> List[str]:
    out = run(f"git diff --name-only {shlex.quote(base)}..HEAD")
    files = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return [p for p in files if should_include_file(p)]


def git_diff_text(base: str, path: str, *, max_chars: int = 6000) -> str:
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


def scan_docs_tree() -> List[str]:
    docs_dir = ROOT / "mkdocs" / "docs"
    if not docs_dir.exists():
        return []
    entries: list[str] = []
    for md_file in sorted(docs_dir.rglob("*.md")):
        rel = md_file.relative_to(docs_dir).as_posix()
        title = _first_heading(_read_text(md_file))
        entries.append(f"- {rel}" + (f" — {title}" if title else ""))
    return entries


def build_plan(base_ref: str) -> str:
    changed = git_diff_names(base_ref)
    mkdocs_yml = _read_text(ROOT / "mkdocs.yml")
    prompt_base = _read_text(PROMPT_BASE_PATH)

    diffs: list[str] = []
    for path in changed[:60]:
        d = git_diff_text(base_ref, path, max_chars=8000)
        if d:
            diffs.append(f"### {path}\n{d}")

    sections: list[str] = [
        "# Docs Autopilot Plan (diff-driven)",
        f"Base: {base_ref}",
        "",
        "## Changed files (filtered)",
        *([f"- {p}" for p in changed] or ["- (none)"]),
        "",
        "## Current MkDocs config (mkdocs.yml)",
        mkdocs_yml[:12000] if mkdocs_yml else "(mkdocs.yml not found)",
        "",
        "## Current docs tree (mkdocs/docs)",
        *(scan_docs_tree() or ["- (mkdocs/docs not found)"]),
        "",
        "## Prompt base (docs_prompt_base.md)",
        (prompt_base or "(missing scripts/docs_ai/docs_prompt_base.md)")[:4000],
        "",
        "## Code diffs (truncated)",
        *(diffs or ["(no diffs captured)"]),
    ]
    return "\n".join(sections).strip() + "\n"


def _extract_unified_diff(text: str) -> str:
    if not text:
        return ""

    # Prefer fenced diff blocks if present.
    m = re.search(r"```diff\\s*\\n([\\s\\S]*?)```", text, re.MULTILINE)
    if m:
        return (m.group(1) or "").strip() + "\n"

    # Otherwise, find the first diff header.
    m2 = re.search(r"^diff --git\\s+", text, re.MULTILINE)
    if m2:
        return text[m2.start() :].strip() + "\n"

    return text.strip() + "\n"


def _parse_diff_paths(patch_text: str) -> List[Tuple[str, str]]:
    paths: list[Tuple[str, str]] = []
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


def _validate_patch_paths(patch_text: str) -> List[str]:
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


def call_openai_unified_diff(prompt: str) -> str:
    import requests

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    # Default to the latest flagship model (override via OPENAI_MODEL).
    model = os.getenv("OPENAI_MODEL", "gpt-5.2")
    url = (os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").rstrip("/") + "/responses")
    max_output_tokens = int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "14000"))

    base_prompt = _read_text(PROMPT_BASE_PATH).strip()
    system_prompt = (
        (base_prompt + "\n\n") if base_prompt else ""
    ) + (
        "You are generating documentation updates for TriBridRAG based on code changes.\n"
        "You may create, move, or delete pages and restructure folders, and you may update mkdocs.yml nav accordingly.\n"
        "Only modify MkDocs sources: mkdocs/docs/** and mkdocs.yml.\n"
        "Output ONLY a unified diff patch suitable for `git apply` (no code fences, no extra commentary).\n"
        "The result must pass `mkdocs build --strict`.\n"
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        # Responses API: prefer top-level instructions + input. This avoids relying on
        # message-compat mode and matches the API reference examples.
        "instructions": system_prompt,
        "input": prompt,
        # GPT-5 family controls
        "text": {"verbosity": os.getenv("OPENAI_VERBOSITY", "high")},
        "reasoning": {"effort": os.getenv("OPENAI_REASONING_EFFORT", "high")},
        "max_output_tokens": max_output_tokens,
    }

    r = requests.post(url, headers=headers, json=payload, timeout=int(os.getenv("OPENAI_HTTP_TIMEOUT_SECONDS", "900")))
    r.raise_for_status()
    data = r.json()

    # Prefer Responses API output_text.
    if isinstance(data, dict):
        out_text = data.get("output_text")
        if isinstance(out_text, str) and out_text.strip():
            return out_text.strip()

        chunks: list[str] = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    t = content.get("text", "")
                    if t:
                        chunks.append(str(t))
        if chunks:
            return "\n".join(chunks).strip()

    raise RuntimeError(f"Unexpected OpenAI response format: {type(data)}")


def apply_patch(patch_path: Path) -> None:
    run(f"git apply --index {shlex.quote(str(patch_path))}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="docs-autopilot", description="Diff-driven MkDocs autopilot for TriBridRAG")
    ap.add_argument("--base", default="origin/main", help="Git ref to diff against (base..HEAD)")
    ap.add_argument("--llm", choices=["openai"], default=None, help="LLM provider (currently: openai)")
    ap.add_argument("--apply", action="store_true", help="Apply the returned patch with `git apply --index`")
    ap.add_argument("--output", default=str(PLAN_FILE.name), help="Plan output file (plan mode)")
    args = ap.parse_args()

    plan = build_plan(args.base)

    # Plan-only mode
    if not args.llm:
        out_path = ROOT / args.output
        out_path.write_text(plan, encoding="utf-8")
        print(f"Wrote plan: {out_path.relative_to(ROOT)}")
        return

    # LLM mode -> patch
    llm_text = call_openai_unified_diff(plan)
    patch_text = _extract_unified_diff(llm_text)
    if not patch_text.strip():
        raise RuntimeError("LLM returned empty patch")

    path_errors = _validate_patch_paths(patch_text)
    if path_errors:
        raise RuntimeError("Refusing patch that touches non-doc paths:\n" + "\n".join(f"- {e}" for e in path_errors))

    PATCH_FILE.write_text(patch_text, encoding="utf-8")
    print(f"LLM patch saved: {PATCH_FILE.relative_to(ROOT)}")

    if args.apply:
        apply_patch(PATCH_FILE)
        print("Patch applied to index.")


if __name__ == "__main__":
    main()

