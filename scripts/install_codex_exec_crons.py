#!/usr/bin/env python3
"""Install or print the three host cron lanes that drive Ragweld codex exec."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CRON_PATH = (
    "/Library/Frameworks/Python.framework/Versions/3.12/bin:"
    "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
CRON_SCRIPT = REPO_ROOT / "scripts" / "codex_exec_automation.py"


@dataclass(frozen=True)
class CodexExecLane:
    minute: int
    cron_tag: str
    automation_id: str
    log_name: str

    @property
    def schedule(self) -> str:
        return f"{self.minute} */4 * * *"


LANES: tuple[CodexExecLane, ...] = (
    CodexExecLane(
        minute=0,
        cron_tag="RAGWELD_CODEX_EXEC_STABILITY",
        automation_id="ragweld-stability-loop",
        log_name="cron-ragweld-stability-loop.log",
    ),
    CodexExecLane(
        minute=20,
        cron_tag="RAGWELD_CODEX_EXEC_UI_PROOF",
        automation_id="ragweld-ui-proof-loop",
        log_name="cron-ragweld-ui-proof-loop.log",
    ),
    CodexExecLane(
        minute=40,
        cron_tag="RAGWELD_CODEX_EXEC_EVAL_DATA",
        automation_id="ragweld-eval-data-loop",
        log_name="cron-ragweld-eval-data-loop.log",
    ),
)
MANAGED_CRON_TAGS = frozenset(lane.cron_tag for lane in LANES)


def render_cron_lines(
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
    python_bin: str = "python3",
) -> list[str]:
    resolved_home = Path.home() if home is None else home
    log_dir = resolved_home / ".codex" / "log"
    script_path = repo_root / "scripts" / "codex_exec_automation.py"
    return [
        (
            f"{lane.schedule} "
            f"PATH={DEFAULT_CRON_PATH} "
            f"HOME={resolved_home} "
            f"CRON_TAG={lane.cron_tag} "
            f"{python_bin} {script_path} {lane.automation_id} "
            f">> {log_dir / lane.log_name} 2>&1"
        )
        for lane in LANES
    ]


def merge_crontab(existing_text: str, managed_lines: list[str]) -> str:
    existing_lines = existing_text.splitlines()

    # Only replace the three worker-lane entries that this repo owns.
    kept_lines = [
        line for line in existing_lines if not any(tag in line for tag in MANAGED_CRON_TAGS)
    ]

    final_lines = kept_lines[:]
    if final_lines and final_lines[-1].strip():
        final_lines.append("")
    final_lines.extend(managed_lines)
    return "\n".join(final_lines) + "\n"


def _load_current_crontab() -> str:
    proc = subprocess.run(
        ["crontab", "-l"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout

    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    if "no crontab" in combined:
        return ""
    raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to read current crontab")


def _apply_crontab(contents: str) -> None:
    proc = subprocess.run(
        ["crontab", "-"],
        input=contents,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to write crontab")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", dest="print_only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    managed_lines = render_cron_lines()

    if args.print_only:
        sys.stdout.write("\n".join(managed_lines) + "\n")
        return 0

    (Path.home() / ".codex" / "log").mkdir(parents=True, exist_ok=True)
    updated_crontab = merge_crontab(_load_current_crontab(), managed_lines)
    _apply_crontab(updated_crontab)
    sys.stdout.write("\n".join(managed_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
