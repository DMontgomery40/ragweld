#!/usr/bin/env python3
"""Install or print the three host cron lanes that drive Ragweld codex exec."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CRON_PATH = (
    "/Library/Frameworks/Python.framework/Versions/3.12/bin:"
    "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
)
HOME = Path.home()
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTOMATION_ROOT = HOME / ".codex" / "automations"
CRON_SCRIPT = REPO_ROOT / "scripts" / "codex_exec_automation.py"

_DAY_NAME_TO_CRON = {
    "MO": "1",
    "TU": "2",
    "WE": "3",
    "TH": "4",
    "FR": "5",
    "SA": "6",
    "SU": "0",
}


@dataclass(frozen=True)
class LaneMetadata:
    cron_tag: str
    automation_id: str
    log_name: str


@dataclass(frozen=True)
class CronSchedule:
    minute: str
    hour: str
    day_of_month: str = "*"
    month: str = "*"
    day_of_week: str = "*"

    @property
    def expression(self) -> str:
        return " ".join(
            [self.minute, self.hour, self.day_of_month, self.month, self.day_of_week]
        )


LANE_METADATA: tuple[LaneMetadata, ...] = (
    LaneMetadata(
        cron_tag="RAGWELD_CODEX_EXEC_STABILITY",
        automation_id="ragweld-stability-loop",
        log_name="cron-ragweld-stability-loop.log",
    ),
    LaneMetadata(
        cron_tag="RAGWELD_CODEX_EXEC_UI_PROOF",
        automation_id="ragweld-ui-proof-loop",
        log_name="cron-ragweld-ui-proof-loop.log",
    ),
    LaneMetadata(
        cron_tag="RAGWELD_CODEX_EXEC_EVAL_DATA",
        automation_id="ragweld-eval-data-loop",
        log_name="cron-ragweld-eval-data-loop.log",
    ),
)
MANAGED_CRON_TAGS = frozenset(lane.cron_tag for lane in LANE_METADATA)


def _default_python_bin() -> str:
    return str(Path(sys.executable).resolve())


def _quote_shell_arg(value: str | Path) -> str:
    return shlex.quote(str(value))


def _parse_int_field(*, value: str | None, field: str, minimum: int, maximum: int, default: int) -> int:
    raw = str(value).strip() if value is not None else ""
    parsed = default if not raw else int(raw)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}, got {parsed}")
    return parsed


def _parse_byday(value: str | None) -> str:
    raw = str(value).strip().upper() if value is not None else ""
    if not raw:
        return "*"
    days: list[str] = []
    for token in raw.split(","):
        cleaned = token.strip()
        if cleaned not in _DAY_NAME_TO_CRON:
            raise ValueError(f"unsupported BYDAY token: {cleaned!r}")
        days.append(_DAY_NAME_TO_CRON[cleaned])
    if not days:
        raise ValueError("BYDAY must not be empty when provided")
    return ",".join(days)


def _parse_rrule(rrule: str) -> CronSchedule:
    fields: dict[str, str] = {}
    for part in str(rrule).split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"invalid RRULE segment: {chunk!r}")
        key, value = chunk.split("=", 1)
        fields[key.strip().upper()] = value.strip().upper()

    freq = fields.get("FREQ")
    if freq == "HOURLY":
        interval = _parse_int_field(
            value=fields.get("INTERVAL"),
            field="INTERVAL",
            minimum=1,
            maximum=24,
            default=1,
        )
        minute = _parse_int_field(
            value=fields.get("BYMINUTE"),
            field="BYMINUTE",
            minimum=0,
            maximum=59,
            default=0,
        )
        if "BYHOUR" in fields:
            raise ValueError("HOURLY RRULE must not set BYHOUR")
        hour = "*" if interval == 1 else f"*/{interval}"
        return CronSchedule(
            minute=str(minute),
            hour=hour,
            day_of_week=_parse_byday(fields.get("BYDAY")),
        )

    if freq == "WEEKLY":
        hour = _parse_int_field(
            value=fields.get("BYHOUR"),
            field="BYHOUR",
            minimum=0,
            maximum=23,
            default=0,
        )
        minute = _parse_int_field(
            value=fields.get("BYMINUTE"),
            field="BYMINUTE",
            minimum=0,
            maximum=59,
            default=0,
        )
        day_of_week = _parse_byday(fields.get("BYDAY"))
        if day_of_week == "*":
            raise ValueError("WEEKLY RRULE must provide BYDAY")
        return CronSchedule(minute=str(minute), hour=str(hour), day_of_week=day_of_week)

    raise ValueError(f"unsupported RRULE frequency: {freq!r}")


def _load_automation_doc(*, automation_root: Path, automation_id: str) -> dict[str, object]:
    path = automation_root / automation_id / "automation.toml"
    if not path.exists():
        raise FileNotFoundError(f"missing automation TOML: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _schedule_for_lane(*, automation_root: Path, automation_id: str) -> CronSchedule:
    automation = _load_automation_doc(automation_root=automation_root, automation_id=automation_id)
    rrule = automation.get("rrule")
    if not isinstance(rrule, str) or not rrule.strip():
        raise ValueError(f"automation is missing rrule: {automation_id}")
    return _parse_rrule(rrule)


def render_cron_lines(
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
    automation_root: Path = DEFAULT_AUTOMATION_ROOT,
    python_bin: str | None = None,
) -> list[str]:
    resolved_home = HOME if home is None else home
    resolved_python_bin = _default_python_bin() if python_bin is None else python_bin
    log_dir = resolved_home / ".codex" / "log"
    script_path = repo_root / "scripts" / "codex_exec_automation.py"

    lines: list[str] = []
    for lane in LANE_METADATA:
        schedule = _schedule_for_lane(
            automation_root=automation_root,
            automation_id=lane.automation_id,
        )
        lines.append(
            (
                f"{schedule.expression} "
                f"PATH={DEFAULT_CRON_PATH} "
                f"HOME={resolved_home} "
                f"CRON_TAG={lane.cron_tag} "
                f"{_quote_shell_arg(resolved_python_bin)} "
                f"{_quote_shell_arg(script_path)} "
                f"{_quote_shell_arg(lane.automation_id)} "
                f">> {_quote_shell_arg(log_dir / lane.log_name)} 2>&1"
            )
        )
    return lines


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


def _load_current_crontab(*, crontab_bin: str = "crontab") -> str:
    proc = subprocess.run(
        [crontab_bin, "-l"],
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


def _apply_crontab(contents: str, *, crontab_bin: str = "crontab") -> None:
    proc = subprocess.run(
        [crontab_bin, "-"],
        input=contents,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "failed to write crontab")


def install_managed_crontab(
    *,
    repo_root: Path = REPO_ROOT,
    home: Path | None = None,
    automation_root: Path = DEFAULT_AUTOMATION_ROOT,
    python_bin: str | None = None,
    crontab_bin: str = "crontab",
) -> list[str]:
    managed_lines = render_cron_lines(
        repo_root=repo_root,
        home=home,
        automation_root=automation_root,
        python_bin=python_bin,
    )
    resolved_home = HOME if home is None else home
    (resolved_home / ".codex" / "log").mkdir(parents=True, exist_ok=True)
    updated_crontab = merge_crontab(
        _load_current_crontab(crontab_bin=crontab_bin),
        managed_lines,
    )
    _apply_crontab(updated_crontab, crontab_bin=crontab_bin)
    return managed_lines


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print", dest="print_only", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.print_only:
        sys.stdout.write("\n".join(render_cron_lines()) + "\n")
        return 0

    managed_lines = install_managed_crontab()
    sys.stdout.write("\n".join(managed_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
