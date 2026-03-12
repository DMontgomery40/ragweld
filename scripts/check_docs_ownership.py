#!/usr/bin/env python3
"""Prevent hand-edits to docs-autopilot-owned MkDocs output."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZERO_SHA = "0" * 40
BOT_ACTORS = {"github-actions[bot]"}


def _run(*args: str, check: bool = True) -> str:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(args)}")
    return proc.stdout


def _git_ref_exists(ref: str) -> bool:
    proc = subprocess.run(
        ("git", "rev-parse", "--verify", ref),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _default_base_ref() -> str | None:
    base_ref = (os.getenv("DOCS_OWNERSHIP_BASE") or "").strip()
    if base_ref:
        return base_ref

    github_base = (os.getenv("GITHUB_BASE_REF") or "").strip()
    if github_base:
        for candidate in (f"origin/{github_base}", github_base):
            if _git_ref_exists(candidate):
                return candidate

    before = (os.getenv("GITHUB_EVENT_BEFORE") or "").strip()
    if before and before != ZERO_SHA:
        return before

    for candidate in ("origin/main", "main", "HEAD~1"):
        if candidate == "HEAD~1":
            proc = subprocess.run(
                ("git", "rev-parse", "--verify", candidate),
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if proc.returncode == 0:
                return candidate
            continue
        if _git_ref_exists(candidate):
            return candidate
    return None


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def changed_files(base_ref: str | None) -> list[str]:
    if base_ref:
        return _split_lines(_run("git", "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base_ref}...HEAD"))

    changed = set(_split_lines(_run("git", "diff", "--name-only", "--diff-filter=ACDMRTUXB", "HEAD", check=False)))
    changed.update(_split_lines(_run("git", "diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB", check=False)))
    changed.update(_split_lines(_run("git", "ls-files", "--others", "--exclude-standard", check=False)))
    return sorted(changed)


def has_local_changes() -> bool:
    tracked = _run("git", "status", "--short", check=False)
    return bool(tracked.strip())


def is_bot_context() -> bool:
    if (os.getenv("GITHUB_ACTIONS") or "").strip().lower() != "true":
        return False
    actor = (os.getenv("GITHUB_ACTOR") or "").strip()
    return actor in BOT_ACTORS


def violating_paths(paths: Iterable[str]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        normalized = path.strip().replace("\\", "/")
        if not normalized:
            continue
        if normalized == "mkdocs.yml" or normalized.startswith("mkdocs/"):
            violations.append(normalized)
    return sorted(dict.fromkeys(violations))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="", help="Optional base ref for branch diff mode")
    args = parser.parse_args(argv)

    explicit_base = args.base.strip()
    if explicit_base:
        files = changed_files(explicit_base)
    elif has_local_changes():
        files = changed_files(None)
    else:
        files = changed_files(_default_base_ref())
    violations = violating_paths(files)
    if not violations:
        print("[check_docs_ownership] pass")
        return 0

    if is_bot_context():
        print("[check_docs_ownership] pass (bot-generated docs output)")
        return 0

    print(
        "Docs ownership check failed: `mkdocs/**` and `mkdocs.yml` are docs-autopilot output.",
        file=sys.stderr,
    )
    print(
        "Do not hand-edit generated docs in feature work. Update code, Pydantic, glossary, "
        "`scripts/docs_ai/docs_prompt_base.md`, or `scripts/docs_ai/README.md` instead.",
        file=sys.stderr,
    )
    print("Violating paths:", file=sys.stderr)
    for path in violations:
        print(f"  - {path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
