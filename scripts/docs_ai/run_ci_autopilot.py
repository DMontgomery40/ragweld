#!/usr/bin/env python3
"""Transactional CI orchestration for docs-autopilot."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLAN_FILE = ROOT / "mkdocs-docs-plan.md"
PATCH_FILE = ROOT / "mkdocs-docs-llm.patch"
ARTIFACT_DIR = ROOT / "output" / "docs-autopilot"
LOG_FILE = ARTIFACT_DIR / "run.log"
STATUS_FILE = ARTIFACT_DIR / "status.txt"
STAGED_DIFF_FILE = ARTIFACT_DIR / "staged.diff"
STAGED_STAT_FILE = ARTIFACT_DIR / "staged.stat"
ZERO_SHA = "0" * 40


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    cwd: Path
    returncode: int
    stdout: str
    stderr: str


def _reset_artifacts() -> None:
    for path in (PLAN_FILE, PATCH_FILE):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    shutil.rmtree(ARTIFACT_DIR, ignore_errors=True)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _append_log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip() + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_if_exists(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _format_proc(proc: CommandResult) -> str:
    return (
        f"$ {shlex.join(proc.args)}\n"
        f"[cwd] {proc.cwd}\n"
        f"[exit] {proc.returncode}\n"
        f"[stdout]\n{proc.stdout.rstrip()}\n"
        f"[stderr]\n{proc.stderr.rstrip()}\n"
    )


def _run(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> CommandResult:
    proc = subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    result = CommandResult(
        args=tuple(str(arg) for arg in args),
        cwd=cwd,
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
    _append_log(_format_proc(result))
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"{shlex.join(result.args)} failed: {detail}")
    return result


def _ref_exists(ref: str) -> bool:
    return _run(("git", "rev-parse", "--verify", ref), cwd=ROOT, check=False).returncode == 0


def resolve_base_ref(explicit_base: str) -> str:
    base = explicit_base.strip()
    if base:
        return base

    before = (os.getenv("GITHUB_EVENT_BEFORE") or "").strip()
    if before and before != ZERO_SHA:
        return before

    ref_name = (os.getenv("GITHUB_REF_NAME") or "").strip()
    if ref_name:
        candidate = f"origin/{ref_name}"
        if _ref_exists(candidate):
            return candidate

    for candidate in ("origin/main", "main", "HEAD~1"):
        if _ref_exists(candidate):
            return candidate

    raise RuntimeError("Unable to resolve base ref for docs-autopilot.")


def resolve_branch_name() -> str:
    head_ref = (os.getenv("GITHUB_HEAD_REF") or "").strip()
    if head_ref:
        return head_ref

    github_ref = (os.getenv("GITHUB_REF") or "").strip()
    if github_ref.startswith("refs/heads/"):
        return github_ref.removeprefix("refs/heads/")

    ref_name = (os.getenv("GITHUB_REF_NAME") or "").strip()
    if ref_name and not ref_name.endswith("/merge") and not ref_name.endswith("/head"):
        return ref_name

    branch = _run(("git", "branch", "--show-current"), cwd=ROOT).stdout.strip()
    if branch:
        return branch
    raise RuntimeError("Unable to resolve branch name for docs-autopilot push.")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "(no details captured)"


def _annotation(level: str, message: str) -> None:
    print(f"::{level}::docs-autopilot: {message}", flush=True)


def _write_summary(lines: list[str]) -> None:
    text = "\n".join(lines).strip() + "\n"
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(text, flush=True)


def _cli_python() -> str:
    override = (os.getenv("DOCS_AUTOPILOT_CLI_PYTHON") or "").strip()
    if override:
        return override
    return sys.executable


def _project_python() -> str:
    override = (os.getenv("DOCS_AUTOPILOT_PROJECT_PYTHON") or "").strip()
    if override:
        return override
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _mkdocs_bin() -> str:
    return (os.getenv("DOCS_AUTOPILOT_MKDOCS_BIN") or "").strip() or "mkdocs"


@contextmanager
def temporary_worktree() -> Path:
    temp_root = Path(tempfile.mkdtemp(prefix="docs-autopilot-"))
    try:
        _run(("git", "worktree", "add", "--detach", str(temp_root), "HEAD"), cwd=ROOT)
        yield temp_root
    finally:
        _run(("git", "worktree", "remove", "--force", str(temp_root)), cwd=ROOT, check=False)
        shutil.rmtree(temp_root, ignore_errors=True)


def _worktree_script(worktree: Path, rel_path: str) -> Path:
    return worktree / rel_path


def _capture_worktree_state(worktree: Path) -> None:
    status = _run(("git", "status", "--short"), cwd=worktree, check=False).stdout
    staged_diff = _run(("git", "diff", "--cached", "--no-color"), cwd=worktree, check=False).stdout
    staged_stat = _run(("git", "diff", "--cached", "--stat"), cwd=worktree, check=False).stdout
    _write_text(STATUS_FILE, status)
    _write_text(STAGED_DIFF_FILE, staged_diff)
    _write_text(STAGED_STAT_FILE, staged_stat)


def _reset_worktree(worktree: Path) -> None:
    _run(("git", "reset", "--hard", "HEAD"), cwd=worktree, check=False)
    _run(("git", "clean", "-fd"), cwd=worktree, check=False)


def _has_staged_changes(worktree: Path) -> bool:
    return _run(("git", "diff", "--cached", "--quiet"), cwd=worktree, check=False).returncode != 0


def _commit_and_push(worktree: Path, branch: str) -> str:
    _run(("git", "config", "user.name", "github-actions[bot]"), cwd=worktree)
    _run(("git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"), cwd=worktree)
    _run(("git", "commit", "-m", "docs(ai): autopilot update"), cwd=worktree)
    _run(("git", "push", "origin", f"HEAD:refs/heads/{branch}"), cwd=worktree)
    return _run(("git", "rev-parse", "HEAD"), cwd=worktree).stdout.strip()


def _run_generate_plan(worktree: Path, base_ref: str) -> None:
    result = _run(
        (
            _cli_python(),
            str(_worktree_script(worktree, "scripts/docs_ai/generate_docs_from_diff.py")),
            "--base",
            base_ref,
            "--output",
            PLAN_FILE.name,
        ),
        cwd=worktree,
    )
    _copy_if_exists(worktree / PLAN_FILE.name, PLAN_FILE)
    if result.returncode != 0:
        raise RuntimeError("Failed to generate docs plan.")


def _run_ai_patch(worktree: Path, base_ref: str) -> tuple[bool, str]:
    result = _run(
        (
            _cli_python(),
            str(_worktree_script(worktree, "scripts/docs_ai/generate_docs_from_diff.py")),
            "--base",
            base_ref,
            "--llm",
            "openai",
            "--apply",
        ),
        cwd=worktree,
        check=False,
    )
    _copy_if_exists(worktree / PATCH_FILE.name, PATCH_FILE)
    if result.returncode != 0:
        return False, _first_line(result.stderr or result.stdout)

    patch_text = (worktree / PATCH_FILE.name).read_text(encoding="utf-8") if (worktree / PATCH_FILE.name).exists() else ""
    if not patch_text.strip():
        return True, "LLM returned an empty patch."
    return True, "LLM patch applied successfully."


def _run_config_reference_generation(worktree: Path) -> tuple[bool, str]:
    result = _run(
        (
            _project_python(),
            str(_worktree_script(worktree, "scripts/generate_config_reference_docs.py")),
            "--clean",
        ),
        cwd=worktree,
        check=False,
    )
    if result.returncode != 0:
        return False, _first_line(result.stderr or result.stdout)
    _run(("git", "add", "--", "mkdocs/docs/reference/config"), cwd=worktree)
    return True, "Configuration reference regenerated."


def _run_build(worktree: Path) -> tuple[bool, str]:
    result = _run((_mkdocs_bin(), "build", "--strict"), cwd=worktree, check=False)
    if result.returncode != 0:
        return False, _first_line(result.stderr or result.stdout)
    return True, "mkdocs build --strict passed."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="", help="Optional base ref override")
    args = parser.parse_args(argv)

    _reset_artifacts()
    base_ref = resolve_base_ref(args.base)
    branch_name = resolve_branch_name()
    summary_lines = [
        "## Docs Autopilot",
        "",
        f"- Branch: `{branch_name}`",
        f"- Base ref: `{base_ref}`",
    ]

    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        raise RuntimeError("OPENAI_API_KEY is required for docs-autopilot CI.")

    with temporary_worktree() as worktree:
        _run_generate_plan(worktree, base_ref)
        summary_lines.append(f"- Plan artifact: `{PLAN_FILE.name}`")

        ai_ok, ai_message = _run_ai_patch(worktree, base_ref)
        summary_lines.append(f"- AI patch: {ai_message}")
        if not ai_ok:
            _annotation("warning", f"AI patch skipped: {ai_message}")
            _reset_worktree(worktree)

        config_ok, config_message = _run_config_reference_generation(worktree)
        summary_lines.append(f"- Config reference: {config_message}")
        if not config_ok:
            _annotation("warning", f"Config reference generation failed: {config_message}")
            _capture_worktree_state(worktree)
            summary_lines.extend(
                [
                    "- Result: branch unchanged.",
                    f"- Debug artifacts: `{ARTIFACT_DIR.relative_to(ROOT)}`",
                ]
            )
            _write_summary(summary_lines)
            return 0

        build_ok, build_message = _run_build(worktree)
        summary_lines.append(f"- Strict build: {build_message}")
        if not build_ok:
            _annotation("warning", f"Strict build failed: {build_message}")
            _capture_worktree_state(worktree)
            summary_lines.extend(
                [
                    "- Result: branch unchanged.",
                    f"- Debug artifacts: `{ARTIFACT_DIR.relative_to(ROOT)}`",
                ]
            )
            _write_summary(summary_lines)
            return 0

        if not _has_staged_changes(worktree):
            summary_lines.append("- Commit: no generated docs changes to push.")
            _write_summary(summary_lines)
            return 0

        commit_sha = _commit_and_push(worktree, branch_name)
        summary_lines.append(f"- Commit: pushed `docs(ai): autopilot update` at `{commit_sha}`.")
        _write_summary(summary_lines)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
