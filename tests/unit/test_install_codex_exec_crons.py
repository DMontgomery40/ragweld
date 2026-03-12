from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.install_codex_exec_crons import (
    DEFAULT_CRON_PATH,
    _load_current_crontab,
    _parse_rrule,
    install_managed_crontab,
    merge_crontab,
    render_cron_lines,
)


def _write_automation(
    automation_root: Path,
    *,
    automation_id: str,
    rrule: str,
    cwd: Path,
) -> None:
    path = automation_root / automation_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "automation.toml").write_text(
        "\n".join(
            [
                "version = 1",
                f'id = "{automation_id}"',
                'name = "Test lane"',
                'prompt = "test prompt"',
                'status = "PAUSED"',
                f'rrule = "{rrule}"',
                f'cwds = ["{cwd}"]',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_lane_automations(automation_root: Path, *, cwd: Path) -> None:
    _write_automation(
        automation_root,
        automation_id="ragweld-stability-loop",
        rrule="FREQ=HOURLY;INTERVAL=4;BYMINUTE=0",
        cwd=cwd,
    )
    _write_automation(
        automation_root,
        automation_id="ragweld-ui-proof-loop",
        rrule="FREQ=HOURLY;INTERVAL=4;BYMINUTE=20",
        cwd=cwd,
    )
    _write_automation(
        automation_root,
        automation_id="ragweld-eval-data-loop",
        rrule="FREQ=HOURLY;INTERVAL=4;BYMINUTE=40",
        cwd=cwd,
    )


def _write_fake_crontab(tmp_path: Path, *, initial_contents: str | None = None) -> tuple[Path, Path]:
    state_path = tmp_path / "crontab-state.txt"
    if initial_contents is not None:
        state_path.write_text(initial_contents, encoding="utf-8")

    script_path = tmp_path / "crontab"
    script_path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'STATE_FILE="${FAKE_CRONTAB_STATE}"',
                'case "$1" in',
                '  -l)',
                '    if [ -f "$STATE_FILE" ]; then',
                '      cat "$STATE_FILE"',
                "      exit 0",
                "    fi",
                '    echo "no crontab for test-user" >&2',
                "    exit 1",
                "    ;;",
                '  -)',
                '    cat > "$STATE_FILE"',
                "    exit 0",
                "    ;;",
                '  *)',
                '    echo "unsupported args" >&2',
                "    exit 2",
                "    ;;",
                "esac",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path, state_path


def test_render_cron_lines_match_automation_tomls(tmp_path: Path) -> None:
    repo_root = Path("/Users/davidmontgomery/ragweld")
    home = Path("/Users/davidmontgomery")
    automation_root = tmp_path / "automations"
    _write_lane_automations(automation_root, cwd=repo_root)

    lines = render_cron_lines(
        repo_root=repo_root,
        home=home,
        automation_root=automation_root,
        python_bin="/usr/local/bin/python3.12",
    )

    assert lines == [
        (
            "0 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_STABILITY "
            "/usr/local/bin/python3.12 "
            "/Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-stability-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-stability-loop.log 2>&1"
        ),
        (
            "20 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_UI_PROOF "
            "/usr/local/bin/python3.12 "
            "/Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-ui-proof-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-ui-proof-loop.log 2>&1"
        ),
        (
            "40 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_EVAL_DATA "
            "/usr/local/bin/python3.12 "
            "/Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-eval-data-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-eval-data-loop.log 2>&1"
        ),
    ]


def test_render_cron_lines_tracks_schedule_changes_from_automation_tomls(tmp_path: Path) -> None:
    automation_root = tmp_path / "automations"
    repo_root = Path("/Users/davidmontgomery/ragweld")
    home = Path("/Users/davidmontgomery")
    _write_automation(
        automation_root,
        automation_id="ragweld-stability-loop",
        rrule="FREQ=HOURLY;INTERVAL=6;BYMINUTE=5",
        cwd=repo_root,
    )
    _write_automation(
        automation_root,
        automation_id="ragweld-ui-proof-loop",
        rrule="FREQ=HOURLY;INTERVAL=4;BYMINUTE=33",
        cwd=repo_root,
    )
    _write_automation(
        automation_root,
        automation_id="ragweld-eval-data-loop",
        rrule="FREQ=HOURLY;INTERVAL=8;BYMINUTE=40",
        cwd=repo_root,
    )

    lines = render_cron_lines(
        repo_root=repo_root,
        home=home,
        automation_root=automation_root,
        python_bin="/usr/bin/python3",
    )

    assert lines[0].startswith("5 */6 * * * ")
    assert lines[1].startswith("33 */4 * * * ")
    assert lines[2].startswith("40 */8 * * * ")


def test_parse_rrule_supports_weekly_schedule() -> None:
    schedule = _parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE,FR;BYHOUR=9;BYMINUTE=30")

    assert schedule.expression == "30 9 * * 1,3,5"


def test_parse_rrule_rejects_hourly_intervals_cron_cannot_represent() -> None:
    with pytest.raises(ValueError, match="supported values are 1, 2, 3, 4, 6, 8, 12, got 5"):
        _parse_rrule("FREQ=HOURLY;INTERVAL=5;BYMINUTE=0")

    with pytest.raises(ValueError, match="supported values are 1, 2, 3, 4, 6, 8, 12, got 72"):
        _parse_rrule("FREQ=HOURLY;INTERVAL=72;BYMINUTE=0")


def test_parse_rrule_rejects_unsupported_fields() -> None:
    with pytest.raises(ValueError, match="unsupported fields"):
        _parse_rrule("FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30;INTERVAL=2")

    with pytest.raises(ValueError, match="unsupported fields"):
        _parse_rrule("FREQ=HOURLY;INTERVAL=4;BYMINUTE=20;COUNT=3")


def test_parse_rrule_rejects_missing_required_fields() -> None:
    with pytest.raises(ValueError, match="HOURLY RRULE must provide INTERVAL"):
        _parse_rrule("FREQ=HOURLY;BYMINUTE=5")

    with pytest.raises(ValueError, match="WEEKLY RRULE must provide BYHOUR"):
        _parse_rrule("FREQ=WEEKLY;BYDAY=MO")


def test_load_current_crontab_handles_missing_crontab(tmp_path: Path) -> None:
    fake_crontab, state_path = _write_fake_crontab(tmp_path)
    previous = os.environ.get("FAKE_CRONTAB_STATE")
    os.environ["FAKE_CRONTAB_STATE"] = str(state_path)
    try:
        assert _load_current_crontab(crontab_bin=str(fake_crontab)) == ""
    finally:
        if previous is None:
            os.environ.pop("FAKE_CRONTAB_STATE", None)
        else:
            os.environ["FAKE_CRONTAB_STATE"] = previous


def test_install_managed_crontab_rewrites_only_managed_entries(tmp_path: Path) -> None:
    fake_crontab, state_path = _write_fake_crontab(
        tmp_path,
        initial_contents="\n".join(
            [
                "22 13 * * * /Users/davidmontgomery/Desktop/download_backup.sh",
                (
                    "0 */4 * * * PATH=/old HOME=/Users/davidmontgomery "
                    "CRON_TAG=RAGWELD_CODEX_EXEC_STABILITY "
                    "/Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
                    "ragweld-stability-loop >> /tmp/old.log 2>&1"
                ),
                "43 3 12 * * /Users/davidmontgomery/ragweld/scripts/run_codex_gist_followup_once.sh",
                "",
            ]
        ),
    )
    automation_root = tmp_path / "automations"
    repo_root = Path("/Users/davidmontgomery/ragweld")
    home = tmp_path / "home"
    _write_lane_automations(automation_root, cwd=repo_root)

    previous = os.environ.get("FAKE_CRONTAB_STATE")
    os.environ["FAKE_CRONTAB_STATE"] = str(state_path)
    try:
        managed_lines = install_managed_crontab(
            repo_root=repo_root,
            home=home,
            automation_root=automation_root,
            python_bin="/usr/bin/python3",
            crontab_bin=str(fake_crontab),
        )
    finally:
        if previous is None:
            os.environ.pop("FAKE_CRONTAB_STATE", None)
        else:
            os.environ["FAKE_CRONTAB_STATE"] = previous

    merged = state_path.read_text(encoding="utf-8")
    assert "22 13 * * * /Users/davidmontgomery/Desktop/download_backup.sh" in merged
    assert "43 3 12 * * /Users/davidmontgomery/ragweld/scripts/run_codex_gist_followup_once.sh" in merged
    assert "/tmp/old.log" not in merged
    assert merged.count("CRON_TAG=RAGWELD_CODEX_EXEC_") == 3
    assert managed_lines[1] in merged
    assert (home / ".codex" / "log").is_dir()


def test_merge_crontab_replaces_managed_entries_and_preserves_unrelated_lines() -> None:
    existing = "\n".join(
        [
            "22 13 * * * /Users/davidmontgomery/Desktop/download_backup.sh",
            (
                "0 */4 * * * PATH=/old HOME=/Users/davidmontgomery "
                "CRON_TAG=RAGWELD_CODEX_EXEC_STABILITY "
                "/Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
                "ragweld-stability-loop >> /tmp/old.log 2>&1"
            ),
            "43 3 12 * * /Users/davidmontgomery/ragweld/scripts/run_codex_gist_followup_once.sh",
            "",
        ]
    )

    merged = merge_crontab(
        existing,
        [
            "0 */4 * * * PATH=/new HOME=/Users/davidmontgomery CRON_TAG=RAGWELD_CODEX_EXEC_STABILITY /usr/bin/python3 /repo/scripts/codex_exec_automation.py ragweld-stability-loop >> /tmp/stability.log 2>&1",
            "20 */4 * * * PATH=/new HOME=/Users/davidmontgomery CRON_TAG=RAGWELD_CODEX_EXEC_UI_PROOF /usr/bin/python3 /repo/scripts/codex_exec_automation.py ragweld-ui-proof-loop >> /tmp/ui-proof.log 2>&1",
            "40 */4 * * * PATH=/new HOME=/Users/davidmontgomery CRON_TAG=RAGWELD_CODEX_EXEC_EVAL_DATA /usr/bin/python3 /repo/scripts/codex_exec_automation.py ragweld-eval-data-loop >> /tmp/eval-data.log 2>&1",
        ],
    )

    assert "22 13 * * * /Users/davidmontgomery/Desktop/download_backup.sh" in merged
    assert "43 3 12 * * /Users/davidmontgomery/ragweld/scripts/run_codex_gist_followup_once.sh" in merged
    assert "/tmp/old.log" not in merged
    assert merged.count("CRON_TAG=RAGWELD_CODEX_EXEC_") == 3
    assert "/repo/scripts/codex_exec_automation.py ragweld-ui-proof-loop" in merged
