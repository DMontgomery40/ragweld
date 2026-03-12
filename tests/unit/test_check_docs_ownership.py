from __future__ import annotations

import os
import subprocess
from pathlib import Path

from scripts import check_docs_ownership


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _init_repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", "remote.git")
    _git(tmp_path, "init", "repo")
    (repo / "mkdocs" / "docs").mkdir(parents=True)
    (repo / "scripts" / "docs_ai").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Home\n", encoding="utf-8")
    (repo / "mkdocs.yml").write_text("site_name: Test\n", encoding="utf-8")
    (repo / "scripts" / "docs_ai" / "README.md").write_text("# Docs AI\n", encoding="utf-8")
    (repo / "docs" / "index.md").write_text("# KB\n", encoding="utf-8")
    _git(repo, "config", "user.name", "Docs Test")
    _git(repo, "config", "user.email", "docs-test@example.com")
    _git(repo, "branch", "-M", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial fixture")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def test_non_bot_mkdocs_change_fails(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature/docs-change")
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Changed by hand\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "manual docs edit")

    previous_root = check_docs_ownership.ROOT
    try:
        check_docs_ownership.ROOT = repo
        assert check_docs_ownership.main(["--base", "origin/main"]) == 1
    finally:
        check_docs_ownership.ROOT = previous_root


def test_bot_generated_mkdocs_change_passes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature/bot-docs")
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Bot output\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "bot docs edit")

    previous_root = check_docs_ownership.ROOT
    previous_actor = os.environ.get("GITHUB_ACTOR")
    previous_actions = os.environ.get("GITHUB_ACTIONS")
    os.environ["GITHUB_ACTOR"] = "github-actions[bot]"
    os.environ["GITHUB_ACTIONS"] = "true"
    try:
        check_docs_ownership.ROOT = repo
        assert check_docs_ownership.main(["--base", "origin/main"]) == 0
    finally:
        check_docs_ownership.ROOT = previous_root
        if previous_actor is None:
            os.environ.pop("GITHUB_ACTOR", None)
        else:
            os.environ["GITHUB_ACTOR"] = previous_actor
        if previous_actions is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = previous_actions


def test_non_mkdocs_docs_autopilot_maintenance_change_passes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature/docs-ai-maintenance")
    (repo / "scripts" / "docs_ai" / "README.md").write_text("# Updated Docs AI\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "maintain docs autopilot readme")

    previous_root = check_docs_ownership.ROOT
    try:
        check_docs_ownership.ROOT = repo
        assert check_docs_ownership.main(["--base", "origin/main"]) == 0
    finally:
        check_docs_ownership.ROOT = previous_root


def test_non_bot_mkdocs_delete_fails(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature/docs-delete")
    _git(repo, "rm", "mkdocs/docs/index.md")
    _git(repo, "commit", "-m", "delete generated docs by hand")

    previous_root = check_docs_ownership.ROOT
    try:
        check_docs_ownership.ROOT = repo
        assert check_docs_ownership.main(["--base", "origin/main"]) == 1
    finally:
        check_docs_ownership.ROOT = previous_root


def test_spoofed_bot_author_does_not_bypass_without_actions_context(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "feature/spoofed-bot")
    _git(repo, "config", "user.name", "github-actions[bot]")
    _git(repo, "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    (repo / "mkdocs" / "docs" / "index.md").write_text("# Spoofed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "spoof bot author")

    previous_root = check_docs_ownership.ROOT
    previous_actor = os.environ.get("GITHUB_ACTOR")
    previous_actions = os.environ.get("GITHUB_ACTIONS")
    os.environ.pop("GITHUB_ACTOR", None)
    os.environ.pop("GITHUB_ACTIONS", None)
    try:
        check_docs_ownership.ROOT = repo
        assert check_docs_ownership.main(["--base", "origin/main"]) == 1
    finally:
        check_docs_ownership.ROOT = previous_root
        if previous_actor is None:
            os.environ.pop("GITHUB_ACTOR", None)
        else:
            os.environ["GITHUB_ACTOR"] = previous_actor
        if previous_actions is None:
            os.environ.pop("GITHUB_ACTIONS", None)
        else:
            os.environ["GITHUB_ACTIONS"] = previous_actions
