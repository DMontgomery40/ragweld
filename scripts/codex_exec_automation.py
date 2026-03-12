#!/usr/bin/env python3
"""Run a Codex automation prompt via local `codex exec` instead of the desktop app."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
CODEX_SOURCE_ROOT = HOME / "codex" / "codex-rs"
DEFAULT_CODEX_BIN_CANDIDATES = (
    CODEX_SOURCE_ROOT / "target" / "release" / "codex",
    CODEX_SOURCE_ROOT / "target" / "debug" / "codex",
)
STOP_HOOK_PATH = HOME / ".codex" / "hooks" / "blocking-stop-hook.sh"
GIT_HEALTH_SCRIPT = "scripts/git_worktree_health.py"


def _run(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(args)}")
    return proc.stdout.strip()


def _resolve_codex_bin() -> Path:
    env_override = os.environ.get("CODEX_EXEC_BIN")
    if env_override:
        path = Path(env_override)
        if path.exists():
            return path
    for candidate in DEFAULT_CODEX_BIN_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("could not find a local codex binary; build codex-cli first")


def _load_automation(automation_id: str) -> dict[str, object]:
    path = HOME / ".codex" / "automations" / automation_id / "automation.toml"
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _repo_root(automation: dict[str, object]) -> Path:
    cwds = automation.get("cwds")
    if not isinstance(cwds, list) or not cwds:
        raise ValueError("automation is missing cwds")
    repo_root = Path(cwds[0])
    if not repo_root.exists():
        raise FileNotFoundError(f"repo root does not exist: {repo_root}")
    return repo_root


def _git_health_script(repo_root: Path) -> Path:
    path = repo_root / GIT_HEALTH_SCRIPT
    if not path.exists():
        raise FileNotFoundError(f"missing git health script: {path}")
    return path


def _assert_origin_main_exists(repo_root: Path) -> None:
    try:
        _run("git", "-C", str(repo_root), "rev-parse", "--verify", "origin/main^{commit}")
    except RuntimeError as exc:
        raise RuntimeError(f"repo is missing origin/main and cannot prepare an exec worktree: {repo_root}") from exc


def _assert_repo_git_health(repo_root: Path) -> None:
    _run("git", "-C", str(repo_root), "fetch", "--all", "--prune")
    _run("git", "-C", str(repo_root), "worktree", "prune")
    script_path = _git_health_script(repo_root)
    _run(sys.executable, str(script_path), "--strict", cwd=repo_root)
    _assert_origin_main_exists(repo_root)


def _planned_worktree_root(automation_id: str) -> Path:
    return HOME / ".codex" / "exec-worktrees" / automation_id


def _planned_run_dir(repo_root: Path, automation_id: str, *, timestamp_utc: str) -> Path:
    return repo_root / "output" / "automation" / "codex-exec" / automation_id / timestamp_utc


def _move_stale_worktree_root(worktree_root: Path) -> Path:
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = worktree_root.with_name(f"{worktree_root.name}.stale-{timestamp_utc}")
    suffix = 0
    candidate = backup_root
    while candidate.exists():
        suffix += 1
        candidate = worktree_root.with_name(f"{backup_root.name}-{suffix}")
    worktree_root.rename(candidate)
    return candidate


def _is_repo_managed_worktree(repo_root: Path, worktree_root: Path) -> bool:
    output = _run("git", "-C", str(repo_root), "worktree", "list", "--porcelain")
    resolved_worktree_root = worktree_root.resolve()
    for raw_line in output.splitlines():
        if raw_line.startswith("worktree "):
            listed_path = Path(raw_line[len("worktree ") :]).resolve()
            if listed_path == resolved_worktree_root:
                return True
    return False


def _worktree_state_for_dry_run(repo_root: Path, worktree_root: Path) -> str:
    if not worktree_root.exists():
        return "missing"
    if not _is_repo_managed_worktree(repo_root, worktree_root):
        return "stale-non-worktree"
    status = _run("git", "-C", str(worktree_root), "status", "--porcelain")
    if status.strip():
        raise RuntimeError(
            f"automation exec worktree is dirty and cannot be safely reused: {worktree_root}"
        )
    return "ready"


def _ensure_worktree(repo_root: Path, automation_id: str) -> Path:
    worktree_root = _planned_worktree_root(automation_id)
    repo_root.mkdir(parents=True, exist_ok=True)
    _run("git", "-C", str(repo_root), "fetch", "--all", "--prune")
    _run("git", "-C", str(repo_root), "worktree", "prune")
    if worktree_root.exists() and not _is_repo_managed_worktree(repo_root, worktree_root):
        backup_path = _move_stale_worktree_root(worktree_root)
        _run("git", "-C", str(repo_root), "worktree", "prune")
        print(
            (
                "[codex_exec_automation] moved stale unmanaged exec directory "
                f"{worktree_root} -> {backup_path}"
            ),
            file=sys.stderr,
        )
    if worktree_root.exists():
        status = _run("git", "-C", str(worktree_root), "status", "--porcelain")
        if status.strip():
            raise RuntimeError(
                f"automation exec worktree is dirty and cannot be safely reused: {worktree_root}"
            )
        _run("git", "-C", str(worktree_root), "fetch", "--all", "--prune")
        _run("git", "-C", str(worktree_root), "checkout", "--detach", "origin/main")
        return worktree_root
    worktree_root.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "-C", str(repo_root), "worktree", "add", "--detach", str(worktree_root), "origin/main")
    return worktree_root


def _prepare_run_dir(repo_root: Path, automation_id: str) -> tuple[Path, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = _planned_run_dir(repo_root, automation_id, timestamp_utc=ts)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, ts


def _build_command(
    *,
    codex_bin: Path | None,
    worktree_root: Path,
    last_message_path: Path,
) -> list[str] | None:
    if codex_bin is None:
        return None
    return [
        str(codex_bin),
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--color",
        "never",
        "--json",
        "-C",
        str(worktree_root),
        "-o",
        str(last_message_path),
        "-c",
        f'stop_hook=["bash","{STOP_HOOK_PATH}"]',
        "-",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("automation_id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    automation = _load_automation(args.automation_id)
    prompt = automation.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("automation is missing prompt text")

    repo_root = _repo_root(automation)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    worktree_root = _planned_worktree_root(args.automation_id)
    planned_run_dir = _planned_run_dir(repo_root, args.automation_id, timestamp_utc=ts)
    events_path = planned_run_dir / "events.jsonl"
    stderr_path = planned_run_dir / "stderr.log"
    last_message_path = planned_run_dir / "last_message.txt"
    meta_path = planned_run_dir / "meta.json"

    if args.dry_run:
        _assert_repo_git_health(repo_root)
        worktree_state = _worktree_state_for_dry_run(repo_root, worktree_root)
        codex_bin: Path | None
        try:
            codex_bin = _resolve_codex_bin()
        except FileNotFoundError:
            codex_bin = None

        meta = {
            "timestamp_utc": ts,
            "dry_run": True,
            "automation_id": args.automation_id,
            "repo_root": str(repo_root),
            "worktree_root": str(worktree_root),
            "worktree_state": worktree_state,
            "codex_bin": str(codex_bin) if codex_bin is not None else None,
            "ready_to_execute": codex_bin is not None,
            "events_path": str(events_path),
            "stderr_path": str(stderr_path),
            "last_message_path": str(last_message_path),
            "command": _build_command(
                codex_bin=codex_bin,
                worktree_root=worktree_root,
                last_message_path=last_message_path,
            ),
        }
        print(json.dumps(meta))
        return 0

    codex_bin = _resolve_codex_bin()
    _assert_repo_git_health(repo_root)
    worktree_root = _ensure_worktree(repo_root, args.automation_id)
    run_dir = planned_run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    command = _build_command(
        codex_bin=codex_bin,
        worktree_root=worktree_root,
        last_message_path=last_message_path,
    )
    assert command is not None

    prompt_path = run_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    with events_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_handle:
        env = os.environ.copy()
        env["CODEX_INTERNAL_ORIGINATOR_OVERRIDE"] = "Codex Desktop"
        proc = subprocess.run(
            command,
            input=prompt,
            text=True,
            cwd=str(repo_root),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
        )

    meta = {
        "timestamp_utc": ts,
        "automation_id": args.automation_id,
        "repo_root": str(repo_root),
        "worktree_root": str(worktree_root),
        "codex_bin": str(codex_bin),
        "events_path": str(events_path),
        "stderr_path": str(stderr_path),
        "last_message_path": str(last_message_path),
        "returncode": proc.returncode,
    }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta))
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
