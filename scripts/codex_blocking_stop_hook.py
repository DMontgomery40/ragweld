#!/usr/bin/env python3
"""Blocking after-agent hook for Codex exec automation lanes."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AUTOMATION_BRANCH_PREFIXES = (
    "codex/stability-",
    "codex/ui-proof-",
    "codex/eval-data-",
)


def _run(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(args)}")
    return proc.stdout.strip()


def _canonical_repo_root(cwd: Path) -> Path:
    try:
        repo_root = _run("git", "-C", str(cwd), "rev-parse", "--show-toplevel")
    except Exception:
        return cwd
    return Path(repo_root)


def _current_branch(cwd: Path) -> str:
    try:
        return _run("git", "-C", str(cwd), "branch", "--show-current")
    except Exception:
        return ""


def _log(payload: dict[str, object], cwd: Path | None, repo_root: Path | None, branch: str) -> None:
    log_dir = Path.home() / ".codex" / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with (log_dir / "blocking-stop-hook.log").open("a", encoding="utf-8") as handle:
        handle.write(
            f"{ts}\tcwd={cwd or ''}\trepo_root={repo_root or ''}\tbranch={branch}\t"
            f"session_id={payload.get('session_id', '')}\n"
        )


def _gate_script(cwd: Path, repo_root: Path) -> Path | None:
    candidates = (
        cwd / "scripts" / "automation_stop_gate.py",
        repo_root / "scripts" / "automation_stop_gate.py",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _git_health_script(cwd: Path, repo_root: Path) -> Path | None:
    candidates = (
        cwd / "scripts" / "git_worktree_health.py",
        repo_root / "scripts" / "git_worktree_health.py",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    hook_event = payload.get("hook_event")
    if not isinstance(hook_event, dict) or hook_event.get("event_type") != "after_agent":
        return 0

    cwd_value = payload.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value.startswith("/"):
        return 0

    cwd = Path(cwd_value)
    repo_root = _canonical_repo_root(cwd)
    branch = _current_branch(cwd)
    _log(payload, cwd, repo_root, branch)

    if repo_root.name != "ragweld":
        return 0
    if not branch.startswith(AUTOMATION_BRANCH_PREFIXES):
        return 0

    gate_script = _gate_script(cwd, repo_root)
    if gate_script is None:
        print("blocking stop hook: missing automation_stop_gate.py", file=sys.stderr)
        return 1

    proc = subprocess.run(
        (sys.executable, str(gate_script)),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "automation stop gate failed"
        print(message, file=sys.stderr)
        return proc.returncode

    git_health_script = _git_health_script(cwd, repo_root)
    if git_health_script is None:
        print("blocking stop hook: missing git_worktree_health.py", file=sys.stderr)
        return 1

    git_proc = subprocess.run(
        (sys.executable, str(git_health_script), "--strict", "--current-branch-only"),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if git_proc.returncode == 0:
        return 0

    message = git_proc.stderr.strip() or git_proc.stdout.strip() or "git/worktree health gate failed"
    print(message, file=sys.stderr)
    return git_proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
