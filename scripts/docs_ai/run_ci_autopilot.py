#!/usr/bin/env python3
"""Transactional CI orchestration for docs-autopilot."""

from __future__ import annotations

import argparse
import json
import os
import re
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


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return (
        _run(("git", "merge-base", "--is-ancestor", ancestor, descendant), cwd=ROOT, check=False).returncode == 0
    )


def _gh_bin() -> str:
    return (os.getenv("DOCS_AUTOPILOT_GH_BIN") or "").strip() or "gh"


def _last_successful_run_head(workflow_file: str, branch: str) -> str:
    """Head SHA of the newest successful GitHub Actions run of `workflow_file` on `branch`.

    Empty only when GitHub reports no such run (first run ever). A lookup that
    cannot be performed raises: silently degrading to the per-push base would
    re-open the lost-push hole, so the run fails and the next one re-covers the
    range. Requires `actions: read`, which the job's `actions: write` grants.
    """
    args = [
        _gh_bin(),
        "run",
        "list",
        "--workflow",
        workflow_file,
        "--branch",
        branch,
        "--status",
        "success",
        "--limit",
        "1",
        "--json",
        "headSha",
    ]
    repository = (os.getenv("GITHUB_REPOSITORY") or "").strip()
    if repository:
        # Pin to this repository; an ambient GH_REPO must not redirect the lookup.
        args += ["--repo", repository]
    try:
        result = _run(args, cwd=ROOT, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"{_gh_bin()} is required to read {workflow_file} run history: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise RuntimeError(f"Unable to read {workflow_file} run history for {branch}: {detail}")
    try:
        runs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Malformed {workflow_file} run history for {branch}: {exc}") from exc
    if not isinstance(runs, list):
        raise RuntimeError(f"Malformed {workflow_file} run history for {branch}: expected a list")
    if not runs:
        return ""
    head = runs[0].get("headSha") if isinstance(runs[0], dict) else None
    if not isinstance(head, str) or not head.strip():
        raise RuntimeError(f"Malformed {workflow_file} run history for {branch}: missing headSha")
    return head.strip()


def _branch_for_runs() -> str:
    return (os.getenv("GITHUB_REF_NAME") or "").strip()


def resolve_base_ref(explicit_base: str) -> str:
    """Pick the commit the docs diff starts from.

    Order: an explicit operator base; else the head of the last *successful*
    autopilot run on this branch (the documented frontier — a run is only
    "success" when its LLM lane processed its range, see main()); else the
    branch counts as undocumented: `main` bootstraps from the empty tree and
    any other branch diffs from its fork point with `origin/main`.

    The push payload's `before` SHA is deliberately not used: it diffs only the
    last push, so a run cancelled by `cancel-in-progress` or failed for any
    reason would lose its changes for good.
    """
    base = explicit_base.strip()
    if base:
        return base

    branch = _branch_for_runs()
    if not branch:
        raise RuntimeError("GITHUB_REF_NAME is required to resolve the docs-autopilot base from run history.")

    last_head = _last_successful_run_head("docs-automation.yml", branch)
    if last_head:
        if _ref_exists(f"{last_head}^{{commit}}") and _is_ancestor(last_head, "HEAD"):
            return last_head
        _append_log(f"last successful run head {last_head} is not in {branch} history; treating the branch as undocumented")

    if branch == "main":
        return "EMPTY"
    if not _ref_exists("origin/main"):
        raise RuntimeError(f"origin/main is required to resolve the docs-autopilot base for {branch}.")
    return _run(("git", "merge-base", "origin/main", "HEAD"), cwd=ROOT).stdout.strip()


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


def _error_detail(result: CommandResult) -> str:
    """Best available failure text for an operator annotation.

    The first stdout line is usually progress noise: a real "corrupt patch at
    line 42" once got reported as "LLM patch saved: ...", which cost a log
    download to diagnose. Prefer stderr, then a stdout line that looks like an
    error, then the last line of output.
    """
    for stream in (result.stderr, result.stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if not lines:
            continue
        for line in lines:
            lowered = line.lower()
            if lowered.startswith(("error", "details:", "fatal", "traceback")) or "error:" in lowered:
                return line
        if stream is result.stderr:
            return lines[-1]
    tail = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return tail[-1] if tail else "(no details captured)"


def _annotation(level: str, message: str) -> None:
    print(f"::{level}::docs-autopilot: {message}", flush=True)


def _write_summary(lines: list[str]) -> None:
    text = "\n".join(lines).strip() + "\n"
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text)
    print(text, flush=True)


def _write_github_output(*, pushed: bool, commit_sha: str | None = None) -> None:
    """Expose whether this run pushed a docs commit.

    A push made with the workflow's GITHUB_TOKEN never fires another workflow's
    `push` trigger, so `Publish MkDocs (mike)` would not run for the autopilot
    commit on its own. The workflow reads these outputs and dispatches the
    publish explicitly when `pushed=true`.
    """
    output_path = (os.getenv("GITHUB_OUTPUT") or "").strip()
    if not output_path:
        return
    lines = [f"pushed={'true' if pushed else 'false'}"]
    if pushed and commit_sha:
        lines.append(f"commit_sha={commit_sha}")
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


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
            "openrouter",
            "--apply",
        ),
        cwd=worktree,
        check=False,
    )
    _copy_if_exists(worktree / PATCH_FILE.name, PATCH_FILE)
    # Raw model replies and the repair-round patch ride along as run artifacts
    # (`output/docs-autopilot/**` is uploaded), so a bad patch can be diagnosed
    # from what the model actually said rather than inferred from its remains.
    for name in (
        "mkdocs-docs-llm-raw.txt",
        "mkdocs-docs-llm-repair.patch",
        "mkdocs-docs-llm-repair-raw.txt",
        "mkdocs-docs-llm-page-repair-raw.txt",
    ):
        _copy_if_exists(worktree / name, ARTIFACT_DIR / name)
    if result.returncode != 0:
        return False, _error_detail(result)

    patch_text = (worktree / PATCH_FILE.name).read_text(encoding="utf-8") if (worktree / PATCH_FILE.name).exists() else ""
    if not patch_text.strip():
        return True, "LLM returned an empty patch."
    return True, _apply_summary(result.stdout) or "LLM patch applied successfully."


_APPLY_SUMMARY_RE = re.compile(r"^AUTOPILOT_APPLY_SUMMARY: applied=(\d+) rejected=(\d+)\s*$", re.MULTILINE)


def _apply_summary(stdout: str) -> str:
    """Turn the generator's per-file apply line into the run summary sentence."""
    m = _APPLY_SUMMARY_RE.search(stdout or "")
    if not m:
        return ""
    applied, rejected = int(m.group(1)), int(m.group(2))
    text = f"LLM patch applied: {applied} file(s)"
    if rejected:
        text += f"; {rejected} file(s) dropped after the repair round (see ::warning:: lines)"
    return text + "."


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
        return False, _error_detail(result)
    _run(("git", "add", "--", "mkdocs/docs/reference/config"), cwd=worktree)
    return True, "Configuration reference regenerated."


def _run_architecture_diagram_generation(worktree: Path) -> tuple[bool, str]:
    """Regenerate the architecture pages from the code; a missing module fails the run on purpose."""
    result = _run(
        (
            _project_python(),
            str(_worktree_script(worktree, "scripts/docs_ai/generate_architecture_diagrams.py")),
            "--clean",
        ),
        cwd=worktree,
        check=False,
    )
    if result.returncode != 0:
        return False, _error_detail(result)
    _run(("git", "add", "--", "mkdocs/docs/reference/architecture"), cwd=worktree)
    return True, "Architecture diagrams regenerated."


_STRICT_LINE_RE = re.compile(r"^(?:WARNING|ERROR)\s+-\s+.*|^Aborted with .*", re.MULTILINE)


def _strict_build_detail(result: CommandResult) -> str:
    """The mkdocs warnings that failed a strict build, not the plugin's INFO chatter.

    Run 33262983828 was reported as failing on
    `INFO - [git-revision-date-localized-plugin] ... has no git logs` while the
    actual cause, one dangling link, sat a few lines further down.
    """
    found: list[str] = []
    for stream in (result.stderr, result.stdout):
        for m in _STRICT_LINE_RE.finditer(stream or ""):
            line = m.group(0).strip()
            if line not in found:
                found.append(line)
    warnings = [ln for ln in found if not ln.startswith("Aborted")]
    aborted = [ln for ln in found if ln.startswith("Aborted")]
    if warnings:
        return " | ".join(warnings[:4] + aborted[:1])
    return _error_detail(result)


def _run_build(worktree: Path) -> tuple[bool, str]:
    result = _run((_mkdocs_bin(), "build", "--strict"), cwd=worktree, check=False)
    if result.returncode != 0:
        return False, _strict_build_detail(result)
    return True, "mkdocs build --strict passed."


def _latest_docs_commit(branch: str) -> str:
    # The checkout predates the autopilot's push from its temporary worktree,
    # so the branch tip must come from a live fetch; a stale tracking ref would
    # name an older docs commit and could report it as already published.
    fetch = _run(("git", "fetch", "--quiet", "origin", branch), cwd=ROOT, check=False)
    if fetch.returncode != 0:
        detail = fetch.stderr.strip() or fetch.stdout.strip() or "command failed"
        raise RuntimeError(f"git fetch origin {branch} failed; cannot determine publish state: {detail}")
    tip = f"origin/{branch}"
    if not _ref_exists(tip):
        raise RuntimeError(f"{tip} is missing after fetch; cannot determine publish state.")
    return _run(
        ("git", "log", "-1", "--format=%H", tip, "--", "mkdocs", "mkdocs.yml"),
        cwd=ROOT,
    ).stdout.strip()


def publish_state() -> int:
    """Report whether the branch tip's newest docs commit has been deployed.

    A commit pushed with GITHUB_TOKEN never fires deploy-docs.yml's `push`
    trigger, so the workflow dispatches the publish explicitly. Deciding from
    deploy history (not from "did this run push") also publishes docs commits
    stranded by an earlier cancelled or failed run.
    """
    branch = _branch_for_runs() or "main"
    docs_commit = _latest_docs_commit(branch)
    needed = False
    if docs_commit:
        deployed_head = _last_successful_run_head("deploy-docs.yml", branch)
        published = bool(deployed_head) and _ref_exists(f"{deployed_head}^{{commit}}") and _is_ancestor(
            docs_commit, deployed_head
        )
        needed = not published
    output_path = (os.getenv("GITHUB_OUTPUT") or "").strip()
    lines = [f"publish_needed={'true' if needed else 'false'}", f"docs_commit={docs_commit}"]
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="", help="Optional base ref override")
    parser.add_argument(
        "--publish-state",
        action="store_true",
        help="Only report publish_needed/docs_commit for the branch tip (no generation).",
    )
    args = parser.parse_args(argv)

    if args.publish_state:
        return publish_state()

    _reset_artifacts()
    base_ref = resolve_base_ref(args.base)
    branch_name = resolve_branch_name()
    summary_lines = [
        "## Docs Autopilot",
        "",
        f"- Branch: `{branch_name}`",
        f"- Base ref: `{base_ref}`",
    ]

    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        raise RuntimeError(
            "OPENROUTER_API_KEY is required for docs-autopilot CI. "
            "Add it with: gh secret set OPENROUTER_API_KEY"
        )

    with temporary_worktree() as worktree:
        _run_generate_plan(worktree, base_ref)
        summary_lines.append(f"- Plan artifact: `{PLAN_FILE.name}`")

        # The run's conclusion is the processed-range marker for the next run's
        # base (see resolve_base_ref), so it must be "success" only when the LLM
        # lane actually processed this range. Failures below still push what
        # they can (the deterministic config reference) but exit non-zero.
        ai_ok, ai_message = _run_ai_patch(worktree, base_ref)
        summary_lines.append(f"- AI patch: {ai_message}")
        if not ai_ok:
            _annotation("error", f"AI patch failed: {ai_message}")
            _reset_worktree(worktree)

        config_ok, config_message = _run_config_reference_generation(worktree)
        summary_lines.append(f"- Config reference: {config_message}")
        if not config_ok:
            _annotation("error", f"Config reference generation failed: {config_message}")
            _capture_worktree_state(worktree)
            summary_lines.extend(
                [
                    "- Result: branch unchanged; run marked failed so the next run re-covers this range.",
                    f"- Debug artifacts: `{ARTIFACT_DIR.relative_to(ROOT)}`",
                ]
            )
            _write_summary(summary_lines)
            _write_github_output(pushed=False)
            return 1

        diagrams_ok, diagrams_message = _run_architecture_diagram_generation(worktree)
        summary_lines.append(f"- Architecture diagrams: {diagrams_message}")
        if not diagrams_ok:
            _annotation("error", f"Architecture diagram generation failed: {diagrams_message}")
            _capture_worktree_state(worktree)
            summary_lines.extend(
                [
                    "- Result: branch unchanged; run marked failed so the next run re-covers this range.",
                    f"- Debug artifacts: `{ARTIFACT_DIR.relative_to(ROOT)}`",
                ]
            )
            _write_summary(summary_lines)
            _write_github_output(pushed=False)
            return 1

        build_ok, build_message = _run_build(worktree)
        summary_lines.append(f"- Strict build: {build_message}")
        if not build_ok:
            _annotation("error", f"Strict build failed: {build_message}")
            _capture_worktree_state(worktree)
            summary_lines.extend(
                [
                    "- Result: branch unchanged; run marked failed so the next run re-covers this range.",
                    f"- Debug artifacts: `{ARTIFACT_DIR.relative_to(ROOT)}`",
                ]
            )
            _write_summary(summary_lines)
            _write_github_output(pushed=False)
            return 1

        pushed_sha: str | None = None
        if _has_staged_changes(worktree):
            pushed_sha = _commit_and_push(worktree, branch_name)
            summary_lines.append(f"- Commit: pushed `docs(ai): autopilot update` at `{pushed_sha}`.")
        else:
            summary_lines.append("- Commit: no generated docs changes to push.")

        if not ai_ok:
            summary_lines.append(
                "- Result: LLM lane did not process this range; run marked failed so the next run re-covers it."
            )
        _write_summary(summary_lines)
        _write_github_output(pushed=pushed_sha is not None, commit_sha=pushed_sha)
        return 0 if ai_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
