#!/usr/bin/env python3
"""Audit ragweld automation branch and worktree health."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()

AUTOMATION_BRANCH_PREFIXES = (
    "codex/stability-",
    "codex/ui-proof-",
    "codex/eval-data-",
)

TOOL_WORKTREE_ROOTS = (
    HOME / ".codex" / "worktrees",
    HOME / ".codex" / "exec-worktrees",
)


@dataclass(frozen=True)
class BranchRecord:
    name: str
    commit: str
    upstream: str
    track: str
    worktreepath: str


@dataclass(frozen=True)
class WorktreeRecord:
    path: str
    head: str
    branch: str
    detached: bool
    prunable: str


@dataclass(frozen=True)
class Issue:
    severity: str
    kind: str
    message: str
    branch: str = ""
    upstream: str = ""
    worktree: str = ""


def _run(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    proc = subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"command failed: {' '.join(args)}")
    return proc.stdout


def _is_automation_branch(branch: str) -> bool:
    return branch.startswith(AUTOMATION_BRANCH_PREFIXES)


def _is_tool_worktree(path: str) -> bool:
    resolved = Path(path).expanduser()
    return any(
        root == resolved or root in resolved.parents
        for root in TOOL_WORKTREE_ROOTS
    )


def _parse_branch_records() -> list[BranchRecord]:
    fmt = "%(refname:short)%00%(objectname:short)%00%(upstream:short)%00%(upstream:track)%00%(worktreepath)"
    output = _run("git", "for-each-ref", f"--format={fmt}", "refs/heads")
    records: list[BranchRecord] = []
    for line in output.splitlines():
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) != 5:
            raise RuntimeError(f"unexpected git for-each-ref output: {line!r}")
        records.append(BranchRecord(*parts))
    return records


def _parse_worktree_records() -> list[WorktreeRecord]:
    output = _run("git", "worktree", "list", "--porcelain")
    records: list[WorktreeRecord] = []
    current: dict[str, str | bool] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current is not None:
                records.append(
                    WorktreeRecord(
                        path=str(current.get("path", "")),
                        head=str(current.get("head", "")),
                        branch=str(current.get("branch", "")),
                        detached=bool(current.get("detached", False)),
                        prunable=str(current.get("prunable", "")),
                    )
                )
                current = None
            continue

        if raw_line.startswith("worktree "):
            if current is not None:
                records.append(
                    WorktreeRecord(
                        path=str(current.get("path", "")),
                        head=str(current.get("head", "")),
                        branch=str(current.get("branch", "")),
                        detached=bool(current.get("detached", False)),
                        prunable=str(current.get("prunable", "")),
                    )
                )
            current = {"path": raw_line[len("worktree ") :], "head": "", "branch": "", "detached": False, "prunable": ""}
            continue

        if current is None:
            continue

        if raw_line.startswith("HEAD "):
            current["head"] = raw_line[len("HEAD ") :]
        elif raw_line.startswith("branch "):
            current["branch"] = raw_line[len("branch refs/heads/") :]
        elif raw_line == "detached":
            current["detached"] = True
        elif raw_line.startswith("prunable "):
            current["prunable"] = raw_line[len("prunable ") :]

    if current is not None:
        records.append(
            WorktreeRecord(
                path=str(current.get("path", "")),
                head=str(current.get("head", "")),
                branch=str(current.get("branch", "")),
                detached=bool(current.get("detached", False)),
                prunable=str(current.get("prunable", "")),
            )
        )
    return records


def _current_branch() -> str:
    return _run("git", "branch", "--show-current").strip()


def _merged_to_origin_main(branch: str) -> bool:
    proc = subprocess.run(
        ("git", "merge-base", "--is-ancestor", branch, "origin/main"),
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _branch_issues(
    branches: list[BranchRecord],
    *,
    current_branch_only: bool,
    allow_missing_upstream: bool,
) -> list[Issue]:
    current_branch = _current_branch() if current_branch_only else ""
    issues: list[Issue] = []

    for branch in branches:
        if not _is_automation_branch(branch.name):
            continue
        if current_branch_only and branch.name != current_branch:
            continue

        active = bool(branch.worktreepath)
        severity = "error" if active or current_branch_only else "warning"
        track = branch.track or ""
        merged_note = ""
        if not branch.upstream and _merged_to_origin_main(branch.name):
            merged_note = " It already appears merged into origin/main."

        if not branch.upstream and not allow_missing_upstream:
            issues.append(
                Issue(
                    severity=severity,
                    kind="missing-upstream",
                    branch=branch.name,
                    worktree=branch.worktreepath,
                    message=f"Automation branch `{branch.name}` has no upstream.{merged_note}",
                )
            )
            continue

        if branch.upstream and "[gone]" in track:
            issues.append(
                Issue(
                    severity=severity,
                    kind="gone-upstream",
                    branch=branch.name,
                    upstream=branch.upstream,
                    worktree=branch.worktreepath,
                    message=f"Automation branch `{branch.name}` tracks deleted upstream `{branch.upstream}`.",
                )
            )
            continue

        if branch.upstream and "behind" in track:
            issues.append(
                Issue(
                    severity=severity,
                    kind="behind-upstream",
                    branch=branch.name,
                    upstream=branch.upstream,
                    worktree=branch.worktreepath,
                    message=f"Automation branch `{branch.name}` is behind upstream `{branch.upstream}` ({track.strip()}).",
                )
            )

    return issues


def _worktree_issues(records: list[WorktreeRecord]) -> list[Issue]:
    issues: list[Issue] = []
    for record in records:
        if record.prunable and _is_tool_worktree(record.path):
            issues.append(
                Issue(
                    severity="error",
                    kind="prunable-worktree",
                    worktree=record.path,
                    message=f"Tool worktree `{record.path}` has stale metadata: {record.prunable}.",
                )
            )
    return issues


def _print_text(issues: list[Issue]) -> None:
    if not issues:
        print("git/worktree health: ok")
        return

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity != "error"]

    if errors:
        print("git/worktree health errors:", file=sys.stderr)
        for issue in errors:
            print(f"- {issue.message}", file=sys.stderr)

    if warnings:
        stream = sys.stderr if errors else sys.stdout
        print("git/worktree health warnings:", file=stream)
        for issue in warnings:
            print(f"- {issue.message}", file=stream)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit ragweld automation git/worktree health.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any error is present.")
    parser.add_argument(
        "--current-branch-only",
        action="store_true",
        help="Audit only the currently checked-out branch and skip repo-wide branch warnings.",
    )
    parser.add_argument(
        "--allow-missing-upstream",
        action="store_true",
        help="Do not fail local-only automation branches that have not been pushed yet.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args()

    issues = _branch_issues(
        _parse_branch_records(),
        current_branch_only=args.current_branch_only,
        allow_missing_upstream=args.allow_missing_upstream,
    )
    if not args.current_branch_only:
        issues.extend(_worktree_issues(_parse_worktree_records()))

    payload = {
        "ok": not any(issue.severity == "error" for issue in issues),
        "issues": [asdict(issue) for issue in issues],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        _print_text(issues)

    if args.strict and not payload["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
