from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

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
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "fail"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "success"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        assert rc == 0
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
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["FAKE_DOCS_AI_MODE"] = "success"
        os.environ["FAKE_CONFIG_MODE"] = "success"
        os.environ["FAKE_MKDOCS_MODE"] = "fail"
        os.environ["DOCS_AUTOPILOT_MKDOCS_BIN"] = str(fake_bin / "mkdocs")
        os.environ.pop("GITHUB_HEAD_REF", None)
        os.environ.pop("GITHUB_REF", None)
        os.environ.pop("GITHUB_REF_NAME", None)

        rc = module.main(["--base", "origin/main"])

        assert rc == 0
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
