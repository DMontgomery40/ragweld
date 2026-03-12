from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "docs_ai" / "generate_docs_from_diff.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_docs_from_diff_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "mkdocs" / "docs").mkdir(parents=True)
    (repo / "mkdocs.yml").write_text("site_name: Test\n", encoding="utf-8")
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Old Title\n", encoding="utf-8")
    (repo / "mkdocs" / "docs" / "api.md").write_text("# API Reference\n", encoding="utf-8")
    _git(tmp_path, "init", "repo")
    _git(repo, "config", "user.name", "Docs Test")
    _git(repo, "config", "user.email", "docs-test@example.com")
    _git(repo, "branch", "-M", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial fixture")
    return repo


def test_apply_patch_accepts_unified_diff(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
                "--- a/mkdocs/docs/index.md",
                "+++ b/mkdocs/docs/index.md",
                "@@ -1 +1 @@",
                "-# Old Title",
                "+# Updated Title",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True
    assert err == ""
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"
    assert "mkdocs/docs/index.md" in _git(repo, "diff", "--cached", "--name-only").stdout


def test_apply_patch_accepts_cursor_patch(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.cursor"
    patch_path.write_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: mkdocs/docs/index.md",
                "@@",
                "-# Old Title",
                "+# Updated Title",
                "*** End Patch",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is True
    assert err == ""
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Updated Title\n"
    assert "mkdocs/docs/index.md" in _git(repo, "diff", "--cached", "--name-only").stdout


def test_failed_cursor_patch_leaves_worktree_clean(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.cursor"
    patch_path.write_text(
        "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: mkdocs/docs/index.md",
                "@@",
                "-# Old Title",
                "+# Updated Title",
                "*** Update File: mkdocs/docs/api.md",
                "@@",
                "-missing line",
                "+replacement",
                "*** End Patch",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is False
    assert "Failed to apply Cursor-style hunk" in err
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Old Title\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""


def test_failed_unified_diff_leaves_worktree_clean(tmp_path: Path) -> None:
    module = _load_module()
    repo = _init_repo(tmp_path)
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text(
        "\n".join(
            [
                "diff --git a/mkdocs/docs/index.md b/mkdocs/docs/index.md",
                "--- a/mkdocs/docs/index.md",
                "+++ b/mkdocs/docs/index.md",
                "@@ -1 +1 @@",
                "-# Missing Title",
                "+# Updated Title",
                "",
            ]
        ),
        encoding="utf-8",
    )

    module.ROOT = repo
    ok, err = module.apply_patch(patch_path)

    assert ok is False
    assert "patch does not apply" in err.lower()
    assert (repo / "mkdocs" / "docs" / "index.md").read_text(encoding="utf-8") == "# Old Title\n"
    assert _git(repo, "status", "--short").stdout.strip() == ""
