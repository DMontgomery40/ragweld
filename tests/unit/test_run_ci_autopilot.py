from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "docs_ai" / "run_ci_autopilot.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_ci_autopilot_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
    )


def _write_file(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _init_fake_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    _git(tmp_path, "init", "--bare", "remote.git")
    _git(tmp_path, "init", "repo")
    _git(repo, "config", "user.name", "Docs Test")
    _git(repo, "config", "user.email", "docs-test@example.com")
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(remote))

    _write_file(repo / ".gitignore", "mkdocs-docs-plan.md\nmkdocs-docs-llm.patch\noutput/\n")
    _write_file(repo / "mkdocs.yml", "site_name: Test\n")
    _write_file(repo / "mkdocs" / "docs" / "index.md", "# Home\n")
    _write_file(
        repo / "scripts" / "docs_ai" / "generate_docs_from_diff.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "",
                "import os",
                "from pathlib import Path",
                "import subprocess",
                "import sys",
                "",
                "ROOT = Path(__file__).resolve().parents[2]",
                "args = sys.argv[1:]",
                "if '--output' in args:",
                "    out_name = args[args.index('--output') + 1]",
                "    (ROOT / out_name).write_text('# plan\\n', encoding='utf-8')",
                "    raise SystemExit(0)",
                "mode = os.getenv('FAKE_DOCS_AI_MODE', 'success')",
                "patch_path = ROOT / 'mkdocs-docs-llm.patch'",
                "if mode == 'fail':",
                "    patch_path.write_text('diff --git a/mkdocs/docs/generated.md b/mkdocs/docs/generated.md\\n', encoding='utf-8')",
                "    print('simulated ai apply failure', file=sys.stderr)",
                "    raise SystemExit(1)",
                "if mode == 'empty':",
                "    patch_path.write_text('', encoding='utf-8')",
                "    raise SystemExit(0)",
                "(ROOT / 'mkdocs' / 'docs' / 'generated.md').write_text('# Generated\\n', encoding='utf-8')",
                "subprocess.run(['git', 'add', '--', 'mkdocs/docs/generated.md'], cwd=ROOT, check=True)",
                "patch_path.write_text('diff --git a/mkdocs/docs/generated.md b/mkdocs/docs/generated.md\\n', encoding='utf-8')",
                "raise SystemExit(0)",
                "",
            ]
        ),
        executable=True,
    )
    _write_file(
        repo / "scripts" / "generate_config_reference_docs.py",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "",
                "import os",
                "from pathlib import Path",
                "import sys",
                "",
                "ROOT = Path(__file__).resolve().parent.parent",
                "mode = os.getenv('FAKE_CONFIG_MODE', 'success')",
                "if mode == 'fail':",
                "    print('config generation failed', file=sys.stderr)",
                "    raise SystemExit(1)",
                "(ROOT / 'mkdocs' / 'docs' / 'reference' / 'config').mkdir(parents=True, exist_ok=True)",
                "(ROOT / 'mkdocs' / 'docs' / 'reference' / 'config' / 'index.md').write_text('# Config\\n', encoding='utf-8')",
                "raise SystemExit(0)",
                "",
            ]
        ),
        executable=True,
    )
    _write_file(
        fake_bin / "mkdocs",
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "",
                "import os",
                "import sys",
                "",
                "if os.getenv('FAKE_MKDOCS_MODE', 'success') == 'fail':",
                "    print('mkdocs build failed', file=sys.stderr)",
                "    raise SystemExit(1)",
                "print('mkdocs build passed')",
                "raise SystemExit(0)",
                "",
            ]
        ),
        executable=True,
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial fixture")
    _git(repo, "push", "-u", "origin", "main")
    return repo, remote, fake_bin


def _configure_module(module, repo: Path) -> None:
    module.ROOT = repo
    module.PLAN_FILE = repo / "mkdocs-docs-plan.md"
    module.PATCH_FILE = repo / "mkdocs-docs-llm.patch"
    module.ARTIFACT_DIR = repo / "output" / "docs-autopilot"
    module.LOG_FILE = module.ARTIFACT_DIR / "run.log"
    module.STATUS_FILE = module.ARTIFACT_DIR / "status.txt"
    module.STAGED_DIFF_FILE = module.ARTIFACT_DIR / "staged.diff"
    module.STAGED_STAT_FILE = module.ARTIFACT_DIR / "staged.stat"


def _remote_head(remote: Path) -> str:
    return subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _remote_file(remote: Path, path: str) -> str:
    return subprocess.run(
        ["git", "--git-dir", str(remote), "show", f"refs/heads/main:{path}"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def test_ai_patch_failure_still_allows_config_docs_and_keeps_root_clean(tmp_path: Path) -> None:
    module = _load_module()
    repo, remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)

    previous_env = os.environ.copy()
    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "fail"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "success"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        # The config reference still lands, but the run is marked failed: the
        # LLM lane did not process this range, so the next run must re-cover it.
        assert rc == 1
        assert _git(repo, "status", "--short").stdout.strip() == ""
        assert not (repo / "mkdocs" / "docs" / "reference" / "config" / "index.md").exists()
        assert _remote_file(remote, "mkdocs/docs/reference/config/index.md") == "# Config\n"
        assert "mkdocs/docs/generated.md" not in _git(repo, "ls-tree", "-r", "HEAD", "--name-only").stdout
        assert module.PATCH_FILE.exists()
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_strict_build_failure_discards_temp_state_and_does_not_push(tmp_path: Path) -> None:
    module = _load_module()
    repo, remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    before = _remote_head(remote)

    previous_env = os.environ.copy()
    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "success"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "fail"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        assert rc == 1
        assert _remote_head(remote) == before
        assert _git(repo, "status", "--short").stdout.strip() == ""
        assert module.STAGED_DIFF_FILE.exists()
        assert module.STATUS_FILE.exists()
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_resolve_branch_name_ignores_pull_request_merge_refs(tmp_path: Path) -> None:
    module = _load_module()
    repo, _remote, _fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)

    previous_env = os.environ.copy()
    try:
        os.environ["GITHUB_REF"] = "refs/pull/73/merge"
        os.environ["GITHUB_REF_NAME"] = "73/merge"
        os.environ.pop("GITHUB_HEAD_REF", None)

        assert module.resolve_branch_name() == "main"
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def _read_github_output(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_successful_run_pushes_docs_commit_and_reports_push_output(tmp_path: Path) -> None:
    module = _load_module()
    repo, remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    before = _remote_head(remote)
    github_output = tmp_path / "github_output.txt"

    previous_env = os.environ.copy()
    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "success"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "success"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ["GITHUB_OUTPUT"] = str(github_output)
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        after = _remote_head(remote)
        assert rc == 0
        assert after != before
        assert _remote_file(remote, "mkdocs/docs/generated.md") == "# Generated\n"
        assert _remote_file(remote, "mkdocs/docs/reference/config/index.md") == "# Config\n"
        subject = subprocess.run(
            ["git", "--git-dir", str(remote), "log", "-1", "--format=%s", "refs/heads/main"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        assert subject == "docs(ai): autopilot update"
        assert _git(repo, "status", "--short").stdout.strip() == ""
        # The workflow uses these outputs to dispatch the mike publish: a push made
        # with GITHUB_TOKEN never fires the deploy workflow's own `push` trigger.
        outputs = _read_github_output(github_output)
        assert outputs == {"pushed": "true", "commit_sha": after}
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_no_generated_changes_reports_pushed_false_and_leaves_remote_untouched(tmp_path: Path) -> None:
    module = _load_module()
    repo, remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    # Commit the deterministic config reference up front so a run with an empty
    # LLM patch produces no staged delta at all.
    _write_file(repo / "mkdocs" / "docs" / "reference" / "config" / "index.md", "# Config\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "config reference already current")
    _git(repo, "push", "origin", "main")
    before = _remote_head(remote)
    github_output = tmp_path / "github_output.txt"

    previous_env = os.environ.copy()
    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "empty"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "success"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ["GITHUB_OUTPUT"] = str(github_output)
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        assert rc == 0
        assert _remote_head(remote) == before
        assert _read_github_output(github_output) == {"pushed": "false"}
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_strict_build_failure_reports_pushed_false(tmp_path: Path) -> None:
    module = _load_module()
    repo, remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    before = _remote_head(remote)
    github_output = tmp_path / "github_output.txt"

    previous_env = os.environ.copy()
    try:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "success"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "fail"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ["GITHUB_OUTPUT"] = str(github_output)
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        assert rc == 1
        assert _remote_head(remote) == before
        assert _read_github_output(github_output) == {"pushed": "false"}
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_resolve_base_ref_without_a_successful_run_treats_the_branch_as_undocumented(tmp_path: Path) -> None:
    """No successful run on record means nothing on this branch has been documented.

    Falling back to the push payload's `before` SHA would diff only the last
    push (the 2026-03-12..08-21 silent regression shape, and the lost-push hole
    whenever the previous run failed or was cancelled), so that path does not
    exist: `main` bootstraps from the empty tree, any other branch diffs from
    its fork point with `origin/main`.
    """
    module = _load_module()
    repo, _remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    fork_point = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _commit_push(repo, "server/api/search.py", "# changed\n", "feature push")

    previous_env = os.environ.copy()
    try:
        os.environ["DOCS_AUTOPILOT_GH_BIN"] = str(_write_fake_gh(fake_bin))
        os.environ["FAKE_GH_AUTOPILOT_HEAD"] = ""
        os.environ["GITHUB_REF_NAME"] = "main"
        assert module.resolve_base_ref("") == "EMPTY"
        assert module.resolve_base_ref("EMPTY") == "EMPTY"

        # A non-main branch with no successful run: everything since it left main.
        _git(repo, "checkout", "-b", "development")
        _write_file(repo / "server" / "api" / "chat.py", "# dev\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "first development push")
        _git(repo, "push", "-u", "origin", "development")
        os.environ["GITHUB_REF_NAME"] = "development"
        base = module.resolve_base_ref("")
        assert base != fork_point  # main moved on after the fork point above
        assert base == _git(repo, "merge-base", "origin/main", "HEAD").stdout.strip()
        assert _git(repo, "diff", "--name-only", f"{base}..HEAD").stdout.strip() == "server/api/chat.py"
        _git(repo, "checkout", "main")

        # The branch name is the key for run history; without it there is no safe answer.
        os.environ.pop("GITHUB_REF_NAME", None)
        with pytest.raises(RuntimeError, match="GITHUB_REF_NAME"):
            module.resolve_base_ref("")
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_docs_workflows_wire_push_base_and_publish_dispatch() -> None:
    import yaml

    autopilot = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "docs-automation.yml").read_text(encoding="utf-8"))
    deploy = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "deploy-docs.yml").read_text(encoding="utf-8"))
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))

    job = autopilot["jobs"]["docs-autopilot"]
    assert "GITHUB_EVENT_BEFORE" not in job["env"]  # per-push base is not a supported path
    assert job["env"]["OPENROUTER_API_KEY"] == "${{ secrets.OPENROUTER_API_KEY }}"
    assert job["env"]["DOCS_AUTOPILOT_MODEL"] == "${{ vars.DOCS_AUTOPILOT_MODEL || 'z-ai/glm-5.3-flash' }}"
    # The docs lane no longer talks to api.openai.com; a stale OpenAI key in the
    # job env would silently look like configuration that still works.
    assert "OPENAI_API_KEY" not in job["env"]
    assert "OPENAI_MODEL" not in job["env"]
    assert autopilot["permissions"] == {"contents": "write", "actions": "write"}

    steps = {step.get("id") or step.get("name"): step for step in job["steps"]}
    autopilot_step = steps["autopilot"]
    assert "run_ci_autopilot.py --base" in autopilot_step["run"]
    assert autopilot_step["env"]["GH_TOKEN"] == "${{ github.token }}"  # last-successful-run base lookup
    state = steps["publish_state"]
    # Runs even when generation failed (missing key, LLM/build failure) so a docs
    # commit stranded by an earlier run still gets published; not on cancellation.
    assert state["if"] == "!cancelled() && github.ref_name == 'main'"
    assert "run_ci_autopilot.py --publish-state" in state["run"]
    assert state["env"]["GH_TOKEN"] == "${{ github.token }}"
    publish = steps["Publish with mike"]
    assert publish["if"] == (
        "!cancelled() && github.ref_name == 'main' && steps.publish_state.outputs.publish_needed == 'true'"
    )
    assert 'gh workflow run deploy-docs.yml --ref main --repo "$GITHUB_REPOSITORY"' in publish["run"]
    assert publish["env"]["GH_TOKEN"] == "${{ github.token }}"

    # The dispatch target must accept workflow_dispatch without required inputs.
    deploy_triggers = deploy[True] if True in deploy else deploy["on"]
    assert "workflow_dispatch" in deploy_triggers
    assert not (deploy_triggers.get("workflow_dispatch") or {}).get("inputs")

    # check_docs_ownership.py reads the same variable; CI must export it too.
    ownership_steps = ci["jobs"]["docs-ownership"]["steps"]
    enforce = next(step for step in ownership_steps if step.get("name") == "Enforce docs ownership")
    assert enforce["env"]["GITHUB_EVENT_BEFORE"] == "${{ github.event.before }}"


def _write_fake_gh(fake_bin: Path) -> Path:
    """A stand-in `gh` that answers `gh run list ... --json headSha` from env.

    FAKE_GH_AUTOPILOT_HEAD / FAKE_GH_DEPLOY_HEAD hold the head SHA of the last
    successful run of each workflow (empty = no such run).
    """
    path = fake_bin / "gh"
    _write_file(
        path,
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "",
                "import json",
                "import os",
                "import sys",
                "",
                "args = sys.argv[1:]",
                "log = os.environ.get('FAKE_GH_LOG')",
                "if log:",
                "    with open(log, 'a', encoding='utf-8') as handle:",
                "        handle.write(' '.join(args) + '\\n')",
                "if os.environ.get('FAKE_GH_FAIL'):",
                "    print('gh: HTTP 403: Resource not accessible by integration', file=sys.stderr)",
                "    raise SystemExit(1)",
                "repo = os.environ.get('GITHUB_REPOSITORY')",
                "if repo:",
                "    if args[-2:] != ['--repo', repo]:",
                "        print('expected --repo ' + repo + ' but got: ' + ' '.join(args), file=sys.stderr)",
                "        raise SystemExit(2)",
                "    args = args[:-2]",
                "if args[:2] == ['run', 'list']:",
                "    flags = args[2:]",
                "    expected = ['--workflow', None, '--branch', None, '--status', 'success', '--limit', '1', '--json', 'headSha']",
                "    if len(flags) != len(expected) or any(e is not None and f != e for f, e in zip(flags, expected)):",
                "        print('unexpected run list flags: ' + ' '.join(flags), file=sys.stderr)",
                "        raise SystemExit(2)",
                "    workflow = flags[1]",
                "    branch = flags[3]",
                "    if workflow not in ('docs-automation.yml', 'deploy-docs.yml'):",
                "        print('unknown workflow ' + workflow, file=sys.stderr)",
                "        raise SystemExit(2)",
                "    if branch != os.environ.get('FAKE_GH_BRANCH', 'main'):",
                "        print(json.dumps([]))",
                "        raise SystemExit(0)",
                "    key = 'FAKE_GH_AUTOPILOT_HEAD' if workflow == 'docs-automation.yml' else 'FAKE_GH_DEPLOY_HEAD'",
                "    sha = os.environ.get(key, '')",
                "    print(json.dumps([{'headSha': sha}] if sha else []))",
                "    raise SystemExit(0)",
                "if args[:2] == ['workflow', 'run']:",
                "    raise SystemExit(0)",
                "print('unexpected gh call: ' + ' '.join(args), file=sys.stderr)",
                "raise SystemExit(2)",
                "",
            ]
        ),
        executable=True,
    )
    return path


def _commit_push(repo: Path, rel_path: str, text: str, message: str) -> str:
    _write_file(repo / rel_path, text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    _git(repo, "push", "origin", "main")
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def test_resolve_base_ref_covers_pushes_whose_run_was_cancelled(tmp_path: Path) -> None:
    """cancel-in-progress drops run A when push B lands; B must diff from the last
    run that actually completed, not from A, or A's changes are never documented."""
    module = _load_module()
    repo, _remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    last_success = _git(repo, "rev-parse", "HEAD").stdout.strip()
    push_a = _commit_push(repo, "server/api/search.py", "# a\n", "push A (run cancelled)")
    _commit_push(repo, "server/api/chat.py", "# b\n", "push B")

    previous_env = os.environ.copy()
    try:
        os.environ["DOCS_AUTOPILOT_GH_BIN"] = str(_write_fake_gh(fake_bin))
        os.environ["GITHUB_REF_NAME"] = "main"

        os.environ["FAKE_GH_AUTOPILOT_HEAD"] = last_success
        assert module.resolve_base_ref("") == last_success
        assert push_a != last_success

        # On GitHub the lookup is pinned to this repository (an ambient GH_REPO must not redirect it).
        os.environ["GITHUB_REPOSITORY"] = "DMontgomery40/ragweld"
        assert module.resolve_base_ref("") == last_success
        os.environ.pop("GITHUB_REPOSITORY")

        # A recorded head that is not in this branch's history (rewritten history) is
        # no frontier at all: the branch counts as undocumented.
        os.environ["FAKE_GH_AUTOPILOT_HEAD"] = "f" * 40
        assert module.resolve_base_ref("") == "EMPTY"

        # Only this branch's runs count.
        os.environ["FAKE_GH_AUTOPILOT_HEAD"] = last_success
        os.environ["FAKE_GH_BRANCH"] = "development"
        assert module.resolve_base_ref("") == "EMPTY"
        os.environ.pop("FAKE_GH_BRANCH")

        # The run-history lookup failing is not a license to use the lossy per-push
        # base: fail closed so the next run (from the last success) re-covers the range.
        os.environ["FAKE_GH_FAIL"] = "1"
        with pytest.raises(RuntimeError, match="run history"):
            module.resolve_base_ref("")
        os.environ.pop("FAKE_GH_FAIL")
        os.environ["DOCS_AUTOPILOT_GH_BIN"] = str(fake_bin / "no-such-gh")
        with pytest.raises(RuntimeError, match="run history"):
            module.resolve_base_ref("")
        os.environ["DOCS_AUTOPILOT_GH_BIN"] = str(fake_bin / "gh")

        # An explicit operator base always wins (manual catch-up dispatch), no lookup needed.
        os.environ["FAKE_GH_FAIL"] = "1"
        assert module.resolve_base_ref("6a07f43") == "6a07f43"
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


def test_publish_state_reports_whether_latest_docs_commit_is_deployed(tmp_path: Path) -> None:
    module = _load_module()
    repo, _remote, fake_bin = _init_fake_repo(tmp_path)
    _configure_module(module, repo)
    initial = _git(repo, "rev-parse", "HEAD").stdout.strip()
    code_only = _commit_push(repo, "server/api/search.py", "# a\n", "code change")
    docs_commit = _commit_push(repo, "mkdocs/docs/generated.md", "# Generated\n", "docs(ai): autopilot update")
    later_code = _commit_push(repo, "server/api/chat.py", "# b\n", "another code change")
    github_output = tmp_path / "github_output.txt"

    previous_env = os.environ.copy()
    try:
        os.environ["DOCS_AUTOPILOT_GH_BIN"] = str(_write_fake_gh(fake_bin))
        os.environ["GITHUB_REF_NAME"] = "main"
        os.environ["GITHUB_OUTPUT"] = str(github_output)

        # Never deployed (or deploy runs expired): the docs commit is unpublished.
        os.environ["FAKE_GH_DEPLOY_HEAD"] = ""
        assert module.main(["--publish-state"]) == 0
        assert _read_github_output(github_output) == {"publish_needed": "true", "docs_commit": docs_commit}

        # Last deploy built a tip that predates the docs commit: still unpublished.
        github_output.write_text("", encoding="utf-8")
        os.environ["FAKE_GH_DEPLOY_HEAD"] = code_only
        assert module.main(["--publish-state"]) == 0
        assert _read_github_output(github_output) == {"publish_needed": "true", "docs_commit": docs_commit}

        # Last deploy built the docs commit itself, or any descendant: published.
        for deployed in (docs_commit, later_code):
            github_output.write_text("", encoding="utf-8")
            os.environ["FAKE_GH_DEPLOY_HEAD"] = deployed
            assert module.main(["--publish-state"]) == 0
            assert _read_github_output(github_output) == {"publish_needed": "false", "docs_commit": docs_commit}

        # CI checks out a detached pre-push SHA and its origin/main ref predates the
        # autopilot's push from the temp worktree: the tip must come from a real fetch.
        _git(repo, "checkout", "--detach", initial)
        _git(repo, "update-ref", "refs/remotes/origin/main", code_only)
        github_output.write_text("", encoding="utf-8")
        os.environ["FAKE_GH_DEPLOY_HEAD"] = code_only
        assert module.main(["--publish-state"]) == 0
        assert _read_github_output(github_output) == {"publish_needed": "true", "docs_commit": docs_commit}
        assert _git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip() == later_code

        # Deploy history unavailable: fail closed rather than report a publish state.
        github_output.write_text("", encoding="utf-8")
        os.environ["FAKE_GH_FAIL"] = "1"
        with pytest.raises(RuntimeError, match="run history"):
            module.main(["--publish-state"])
        assert github_output.read_text(encoding="utf-8") == ""
        os.environ.pop("FAKE_GH_FAIL")

        # The branch tip must come from a live fetch: a stale tracking ref would
        # name an older, already-published docs commit and report "published".
        _git(repo, "update-ref", "refs/remotes/origin/main", code_only)
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
        os.environ["FAKE_GH_DEPLOY_HEAD"] = code_only
        with pytest.raises(RuntimeError, match="fetch"):
            module.main(["--publish-state"])
        assert github_output.read_text(encoding="utf-8") == ""
    finally:
        os.environ.clear()
        os.environ.update(previous_env)
