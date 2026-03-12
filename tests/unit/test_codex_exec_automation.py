from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.codex_exec_automation import _move_stale_worktree_root

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "codex_exec_automation.py"


def _make_valid_repo_root(
    tmp_path: Path,
    *,
    health_exit_code: int = 0,
    with_origin_main: bool = True,
) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts").mkdir()
    health_args_path = repo_root / "health_args.json"
    (repo_root / "scripts" / "git_worktree_health.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "import json",
                "import sys",
                "from pathlib import Path",
                "",
                f"Path({str(health_args_path)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')",
                f"raise SystemExit({health_exit_code})",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Codex Test"], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "codex-test@example.com"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "initial fixture"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if with_origin_main:
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    return repo_root, health_args_path


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
    repo_root, health_args_path = _make_valid_repo_root(tmp_path)

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
            str(SCRIPT_PATH),
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
    assert json.loads(health_args_path.read_text(encoding="utf-8")) == ["--strict"]
    assert not (fake_home / ".codex" / "exec-worktrees" / "test-lane").exists()
    assert not (repo_root / "output").exists()


def test_dry_run_reports_missing_codex_bin_without_failing(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root, health_args_path = _make_valid_repo_root(tmp_path)

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
            str(SCRIPT_PATH),
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
    assert json.loads(health_args_path.read_text(encoding="utf-8")) == ["--strict"]
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
            str(SCRIPT_PATH),
            "--dry-run",
            "test-lane",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0


def test_dry_run_fails_when_health_script_fails(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root, health_args_path = _make_valid_repo_root(tmp_path, health_exit_code=1)

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

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--dry-run", "test-lane"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    assert json.loads(health_args_path.read_text(encoding="utf-8")) == ["--strict"]


def test_dry_run_fails_without_origin_main_ref(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root, _ = _make_valid_repo_root(tmp_path, with_origin_main=False)

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
        [sys.executable, str(SCRIPT_PATH), "--dry-run", "test-lane"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    assert "origin/main" in proc.stderr


def test_dry_run_marks_unmanaged_git_checkout_as_stale(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root, _ = _make_valid_repo_root(tmp_path)
    unmanaged_exec_root = fake_home / ".codex" / "exec-worktrees" / "test-lane"
    unmanaged_exec_root.mkdir(parents=True)
    subprocess.run(
        ["git", "init"],
        cwd=unmanaged_exec_root,
        text=True,
        capture_output=True,
        check=True,
    )

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
        [sys.executable, str(SCRIPT_PATH), "--dry-run", "test-lane"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["worktree_state"] == "stale-non-worktree"


def test_run_replaces_unmanaged_exec_checkout(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    automation_root = fake_home / ".codex" / "automations" / "test-lane"
    automation_root.mkdir(parents=True)
    repo_root, _ = _make_valid_repo_root(tmp_path)
    unmanaged_exec_root = fake_home / ".codex" / "exec-worktrees" / "test-lane"
    unmanaged_exec_root.mkdir(parents=True)
    (unmanaged_exec_root / "marker.txt").write_text("foreign checkout", encoding="utf-8")
    subprocess.run(
        ["git", "init"],
        cwd=unmanaged_exec_root,
        text=True,
        capture_output=True,
        check=True,
    )

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
        [sys.executable, str(SCRIPT_PATH), "test-lane"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["returncode"] == 0
    stale_roots = sorted((fake_home / ".codex" / "exec-worktrees").glob("test-lane.stale-*"))
    assert stale_roots
    assert (stale_roots[0] / "marker.txt").read_text(encoding="utf-8") == "foreign checkout"
    assert unmanaged_exec_root.exists()
    assert not (unmanaged_exec_root / "marker.txt").exists()
