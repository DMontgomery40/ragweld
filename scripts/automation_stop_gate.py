#!/usr/bin/env python3
"""Deterministic guardrail for automation branches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BOOTSTRAP_ARTIFACT = ROOT / "output" / "automation" / "bootstrap" / "latest.json"
ACCEPTANCE_ARTIFACT = ROOT / "output" / "automation" / "acceptance" / "latest.json"
GIT_HEALTH_SCRIPT = ROOT / "scripts" / "git_worktree_health.py"
FRESHNESS_SECONDS = 45 * 60

AUTOMATION_BRANCH_PREFIXES = (
    "codex/stability-",
    "codex/ui-proof-",
    "codex/eval-data-",
)

NON_SUBSTANTIVE_PATTERNS = (
    "docs/exec-plans/active/autopilot-status/",
    "docs/exec-plans/active/worktree-salvage-",
    "docs/exec-plans/active/",
    "mkdocs/",
)

MOCK_PATTERNS = (
    r"\bmonkeypatch\b",
    r"\bfrom\s+unittest\.mock\s+import\b",
    r"\bimport\s+unittest\.mock\b",
    r"\bMagicMock\b",
    r"\bAsyncMock\b",
    r"\bpatch\(",
    r"\bpage\.route\(",
    r"\bcontext\.route\(",
    r"\broute\.fulfill\(",
    r"\broute\.(abort|continue|fallback)\(",
)


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


def current_branch() -> str:
    return _run("git", "branch", "--show-current").strip()


def is_automation_branch(branch: str) -> bool:
    return branch.startswith(AUTOMATION_BRANCH_PREFIXES)


def lane_for_branch(branch: str) -> str | None:
    if branch.startswith("codex/stability-"):
        return "stability"
    if branch.startswith("codex/ui-proof-"):
        return "ui-proof"
    if branch.startswith("codex/eval-data-"):
        return "eval-data"
    return None


def base_ref() -> str:
    for ref in ("origin/main", "main"):
        proc = subprocess.run(
            ("git", "rev-parse", "--verify", ref),
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return ref
    return "HEAD~1"


def changed_files(staged: bool) -> list[str]:
    if staged:
        output = _run("git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB")
    else:
        output = _run("git", "diff", "--name-only", "--diff-filter=ACMRTUXB", f"{base_ref()}...HEAD")
    return [line.strip() for line in output.splitlines() if line.strip()]


def diff_text(staged: bool) -> str:
    if staged:
        return _run("git", "diff", "--cached", "--unified=0", "--no-color")
    return _run("git", "diff", "--unified=0", "--no-color", f"{base_ref()}...HEAD")


def is_non_substantive(path: str) -> bool:
    normalized = path.strip()
    if not normalized:
        return True
    if normalized.endswith(".md"):
        return True
    return any(normalized.startswith(prefix) for prefix in NON_SUBSTANTIVE_PATTERNS)


def added_lines_only(diff: str) -> list[str]:
    out: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        out.append(line[1:])
    return out


def read_artifact(path: Path, *, require_success: bool) -> str | None:
    if not path.exists():
        return f"missing artifact: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"invalid artifact {path}: {exc}"

    age = time.time() - path.stat().st_mtime
    if age > FRESHNESS_SECONDS:
        return f"artifact too old ({int(age)}s): {path}"

    if require_success and payload.get("status") != "passed" and payload.get("ok") is not True:
        return f"artifact is not successful: {path}"
    return None


def git_health_error(*, allow_missing_upstream: bool) -> str | None:
    if not GIT_HEALTH_SCRIPT.exists():
        return f"missing git health script: {GIT_HEALTH_SCRIPT}"

    command = [sys.executable, str(GIT_HEALTH_SCRIPT), "--strict", "--current-branch-only"]
    if allow_missing_upstream:
        command.append("--allow-missing-upstream")

    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return None
    return proc.stderr.strip() or proc.stdout.strip() or "git/worktree health gate failed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staged", action="store_true", help="Check staged changes instead of branch diff")
    args = parser.parse_args()

    # A lightweight repo-local stop lever for automation lanes.
    stop_markers = [
        ROOT / "output" / "automation" / "STOP",
        ROOT / "output" / "automation" / "STOP_UI_PROOF",
    ]
    for marker in stop_markers:
        if marker.exists():
            print(f"[automation_stop_gate] blocked by {marker}")
            return 1

    branch = current_branch()
    if not is_automation_branch(branch):
        print("[automation_stop_gate] pass")
        return 0

    lane = lane_for_branch(branch)
    if lane is None:
        print("[automation_stop_gate] pass")
        return 0

    files = changed_files(args.staged)
    if files and all(is_non_substantive(path) for path in files):
        print(
            "automation stop gate: worker automation branches may not commit or push docs-only/status-only changes.",
            file=sys.stderr,
        )
        for path in files:
            print(f"  - {path}", file=sys.stderr)
        return 1

    diff = diff_text(args.staged)
    for added in added_lines_only(diff):
        for pattern in MOCK_PATTERNS:
            if re.search(pattern, added):
                print(
                    "automation stop gate: newly added fake-green test code is forbidden on automation branches.",
                    file=sys.stderr,
                )
                print(f"  offending line: {added}", file=sys.stderr)
                return 1

    bootstrap_error = read_artifact(BOOTSTRAP_ARTIFACT, require_success=True)
    if bootstrap_error is not None:
        print(f"automation stop gate: {bootstrap_error}", file=sys.stderr)
        print("run ./scripts/automation_bootstrap.sh before committing or pushing this automation branch.", file=sys.stderr)
        return 1

    if lane == "ui-proof":
        acceptance_error = read_artifact(ACCEPTANCE_ARTIFACT, require_success=False)
        if acceptance_error is not None:
            print(f"automation stop gate: {acceptance_error}", file=sys.stderr)
            print("run ./scripts/acceptance_epstein.sh and capture a fresh real acceptance result first.", file=sys.stderr)
            return 1

    if not args.staged:
        git_error = git_health_error(allow_missing_upstream=True)
        if git_error is not None:
            print(f"automation stop gate: {git_error}", file=sys.stderr)
            return 1

    print("[automation_stop_gate] pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
