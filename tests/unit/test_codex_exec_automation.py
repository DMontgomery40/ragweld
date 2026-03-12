from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.codex_exec_automation import _move_stale_worktree_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_valid_repo_root(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts").mkdir()
    (repo_root / "scripts" / "git_worktree_health.py").write_text(
        "from __future__ import annotations\n\nraise SystemExit(0)\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return repo_root


def test_move_stale_worktree_root_preserves_existing_contents(tmp_path: Path) -> None:
    stale_root = tmp_path / "ragweld-ui-proof-loop"
    stale_root.mkdir()
    marker = stale_root / "marker.txt"
    marker.write_text("stale", encoding="utf-8")

    backup_root = _move_stale_worktree_root(stale_root)

    assert not stale_root.exists()
    assert backup_root.exists()
    assert (backup_root / "marker.txt").read_text(encoding="utf-8") == "stale"


def test_dry_run_does_not_create_worktree_or_output(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root = _make_valid_repo_root(tmp_path)

    (automation_root / "automation.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'id = "test-lane"',
                'name = "Test Lane"',
                'prompt = "hello world"',
                'status = "PAUSED"',
                f'cwds = ["{repo_root}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_codex.chmod(0o755)

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CODEX_EXEC_BIN"] = str(fake_codex)

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "codex_exec_automation.py"),
            "--dry-run",
            "test-lane",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["dry_run"] is True
    assert payload["ready_to_execute"] is True
    assert payload["worktree_state"] == "missing"
    assert payload["worktree_root"] == str(fake_home / ".codex" / "exec-worktrees" / "test-lane")
    assert payload["command"] is not None
    assert not (fake_home / ".codex" / "exec-worktrees" / "test-lane").exists()
    assert not (repo_root / "output").exists()


def test_dry_run_reports_missing_codex_bin_without_failing(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root = _make_valid_repo_root(tmp_path)

    (automation_root / "automation.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'id = "test-lane"',
                'name = "Test Lane"',
                'prompt = "hello world"',
                'status = "PAUSED"',
                f'cwds = ["{repo_root}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env.pop("CODEX_EXEC_BIN", None)

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "codex_exec_automation.py"),
            "--dry-run",
            "test-lane",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["codex_bin"] is None
    assert payload["ready_to_execute"] is False
    assert payload["command"] is None
    assert not (repo_root / "output").exists()


def test_dry_run_fails_for_invalid_repo_root(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    invalid_repo_root = tmp_path / "not-a-repo"
    invalid_repo_root.mkdir()

    (automation_root / "automation.toml").write_text(
        "\n".join(
            [
                "version = 1",
                'id = "test-lane"',
                'name = "Test Lane"',
                'prompt = "hello world"',
                'status = "PAUSED"',
                f'cwds = ["{invalid_repo_root}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HOME"] = str(fake_home)

    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "codex_exec_automation.py"),
            "--dry-run",
            "test-lane",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    assert "not a git repository" in proc.stderr.lower()
