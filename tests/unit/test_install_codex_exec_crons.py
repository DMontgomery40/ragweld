from __future__ import annotations

from pathlib import Path

from scripts.install_codex_exec_crons import DEFAULT_CRON_PATH, merge_crontab, render_cron_lines


def test_render_cron_lines_match_expected_lanes() -> None:
    repo_root = Path("/Users/davidmontgomery/ragweld")
    home = Path("/Users/davidmontgomery")

    lines = render_cron_lines(repo_root=repo_root, home=home)

    assert lines == [
        (
            "0 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_STABILITY "
            "python3 /Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-stability-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-stability-loop.log 2>&1"
        ),
        (
            "20 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_UI_PROOF "
            "python3 /Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-ui-proof-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-ui-proof-loop.log 2>&1"
        ),
        (
            "40 */4 * * * "
            f"PATH={DEFAULT_CRON_PATH} "
            "HOME=/Users/davidmontgomery "
            "CRON_TAG=RAGWELD_CODEX_EXEC_EVAL_DATA "
            "python3 /Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py "
            "ragweld-eval-data-loop "
            ">> /Users/davidmontgomery/.codex/log/cron-ragweld-eval-data-loop.log 2>&1"
        ),
    ]


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
        render_cron_lines(
            repo_root=Path("/Users/davidmontgomery/ragweld"),
            home=Path("/Users/davidmontgomery"),
        ),
    )

    assert "22 13 * * * /Users/davidmontgomery/Desktop/download_backup.sh" in merged
    assert "43 3 12 * * /Users/davidmontgomery/ragweld/scripts/run_codex_gist_followup_once.sh" in merged
    assert "/tmp/old.log" not in merged
    assert merged.count("CRON_TAG=RAGWELD_CODEX_EXEC_") == 3
    assert "python3 /Users/davidmontgomery/ragweld/scripts/codex_exec_automation.py ragweld-ui-proof-loop" in merged
