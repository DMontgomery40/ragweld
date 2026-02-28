#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import shutil
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHIFT_DOWN_SEQ = b"\x1b[1;2B"
REFRESH_INTERVAL_SECONDS = 1.0
MAX_RECENT_SESSION_FILES = 200
LOOKBACK_SECONDS = 6 * 60 * 60
OUTPUT_BACKLOG_MAX_BYTES = 4 * 1024 * 1024


@dataclass
class SessionMeta:
    session_id: str
    parent_id: str | None
    nickname: str
    role: str | None
    path: Path
    mtime: float


@dataclass
class SessionMetrics:
    tool_uses: int = 0
    total_tokens: int | None = None
    last_ts: datetime | None = None
    last_event_kind: str | None = None


class SessionIndex:
    def __init__(self, sessions_root: Path) -> None:
        self.sessions_root = sessions_root
        self._meta_cache: dict[Path, SessionMeta] = {}
        self._metrics_cache: dict[Path, tuple[int, SessionMetrics]] = {}

    def recent_metas(self, now: datetime) -> list[SessionMeta]:
        entries: list[tuple[float, Path]] = []
        if not self.sessions_root.exists():
            return []
        cutoff = now.timestamp() - LOOKBACK_SECONDS
        for path in self.sessions_root.rglob("rollout-*.jsonl"):
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < cutoff:
                continue
            entries.append((stat.st_mtime, path))
        entries.sort(key=lambda item: item[0], reverse=True)
        entries = entries[:MAX_RECENT_SESSION_FILES]

        out: list[SessionMeta] = []
        for mtime, path in entries:
            cached = self._meta_cache.get(path)
            if cached is not None and abs(cached.mtime - mtime) < 1e-6:
                out.append(cached)
                continue
            meta = self._load_session_meta(path, mtime)
            if meta is None:
                continue
            self._meta_cache[path] = meta
            out.append(meta)
        return out

    def metrics_for(self, path: Path) -> SessionMetrics:
        try:
            stat = path.stat()
        except OSError:
            return SessionMetrics()
        cached = self._metrics_cache.get(path)
        if cached is not None and cached[0] == stat.st_size:
            return cached[1]
        metrics = self._scan_metrics(path)
        self._metrics_cache[path] = (stat.st_size, metrics)
        return metrics

    def _load_session_meta(self, path: Path, mtime: float) -> SessionMeta | None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                first_line = handle.readline()
        except Exception:
            return None
        if not first_line:
            return None
        try:
            payload = json.loads(first_line)
        except Exception:
            return None
        if payload.get("type") != "session_meta":
            return None
        data = payload.get("payload")
        if not isinstance(data, dict):
            return None
        session_id = str(data.get("id") or "").strip()
        if not session_id:
            return None
        source = data.get("source")
        parent_id: str | None = None
        if isinstance(source, dict):
            subagent = source.get("subagent")
            if isinstance(subagent, dict):
                spawn = subagent.get("thread_spawn")
                if isinstance(spawn, dict):
                    raw_parent = spawn.get("parent_thread_id")
                    if raw_parent is not None:
                        parent_id = str(raw_parent).strip() or None
        nickname = str(data.get("agent_nickname") or "").strip()
        if not nickname:
            nickname = str(data.get("agent_role") or "").strip()
        if not nickname:
            nickname = session_id[:12]
        role = data.get("agent_role")
        role_str = None if role is None else str(role)
        return SessionMeta(
            session_id=session_id,
            parent_id=parent_id,
            nickname=nickname,
            role=role_str,
            path=path,
            mtime=mtime,
        )

    def _scan_metrics(self, path: Path) -> SessionMetrics:
        metrics = SessionMetrics()
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        evt = json.loads(raw)
                    except Exception:
                        continue
                    timestamp = _parse_timestamp(evt.get("timestamp"))
                    if timestamp is not None and (metrics.last_ts is None or timestamp >= metrics.last_ts):
                        metrics.last_ts = timestamp

                    evt_type = evt.get("type")
                    if evt_type == "response_item":
                        payload = evt.get("payload")
                        if isinstance(payload, dict):
                            payload_type = str(payload.get("type") or "")
                            if payload_type == "function_call":
                                metrics.tool_uses += 1
                                metrics.last_event_kind = "function_call"
                            elif payload_type:
                                metrics.last_event_kind = payload_type
                    elif evt_type == "event_msg":
                        payload = evt.get("payload")
                        if isinstance(payload, dict):
                            payload_type = str(payload.get("type") or "")
                            if payload_type == "token_count":
                                info = payload.get("info")
                                if isinstance(info, dict):
                                    total_usage = info.get("total_token_usage")
                                    if isinstance(total_usage, dict):
                                        total = total_usage.get("total_tokens")
                                        if isinstance(total, int):
                                            metrics.total_tokens = total
                            if payload_type:
                                metrics.last_event_kind = payload_type
                        elif metrics.last_event_kind is None:
                            metrics.last_event_kind = "event_msg"
                    elif evt_type is not None:
                        metrics.last_event_kind = str(evt_type)
        except OSError:
            return SessionMetrics()
        return metrics


@dataclass
class TeamMemberStats:
    name: str
    agent_id: str
    inbox_pending: int
    outbox_active: int


@dataclass
class TeamSnapshot:
    team_name: str
    lead_name: str
    members: list[TeamMemberStats]


@dataclass
class OverlayRuntime:
    team_index: SessionIndex
    sessions_root: Path
    teams_root: Path
    panel_open: bool = False
    child_backlog: bytearray = field(default_factory=bytearray)
    next_render_at: float = 0.0


def _safe_load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_box(path: Path) -> list[dict[str, Any]]:
    raw = _safe_load_json(path)
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
        return out
    return []


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        ts = datetime.fromisoformat(text)
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
    except ValueError:
        return None


def _format_tokens(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return str(value)


def _format_age(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _member_status(metrics: SessionMetrics | None, now: datetime, outbox_active: int) -> str:
    if metrics is None or metrics.last_ts is None:
        return "Running" if outbox_active > 0 else "Idle"
    age = max(0, int((now - metrics.last_ts).total_seconds()))
    if metrics.last_event_kind != "task_complete" and age <= 15:
        return "Running"
    return f"Idle for {_format_age(age)}"


def _active_team(teams_root: Path) -> TeamSnapshot | None:
    if not teams_root.exists():
        return None
    candidates: list[tuple[float, Path]] = []
    for team_dir in teams_root.iterdir():
        if not team_dir.is_dir():
            continue
        config_path = team_dir / "config.json"
        if not config_path.exists():
            continue
        score = config_path.stat().st_mtime
        journal_path = team_dir / "journal" / "events.jsonl"
        if journal_path.exists():
            score = max(score, journal_path.stat().st_mtime)
        candidates.append((score, team_dir))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    team_dir = candidates[0][1]
    config = _safe_load_json(team_dir / "config.json")
    if not isinstance(config, dict):
        return None
    members_raw = config.get("members")
    if not isinstance(members_raw, list):
        return None

    lead_agent_id = str(config.get("leadAgentId") or "")
    members: list[TeamMemberStats] = []
    lead_name = ""
    for raw_member in members_raw:
        if not isinstance(raw_member, dict):
            continue
        name = str(raw_member.get("name") or "").strip()
        if not name:
            continue
        agent_id = str(raw_member.get("agentId") or "").strip()
        if not lead_name and (agent_id == lead_agent_id or not lead_agent_id):
            lead_name = name
        inbox = _load_box(team_dir / "inboxes" / f"{name}.json")
        outbox = _load_box(team_dir / "outboxes" / f"{name}.json")
        inbox_pending = sum(1 for msg in inbox if str(msg.get("status") or "") == "pending")
        outbox_active = sum(1 for msg in outbox if str(msg.get("status") or "") in {"queued", "retry"})
        members.append(
            TeamMemberStats(
                name=name,
                agent_id=agent_id,
                inbox_pending=inbox_pending,
                outbox_active=outbox_active,
            )
        )
    if not members:
        return None
    if not lead_name:
        lead_name = members[0].name
    return TeamSnapshot(team_name=team_dir.name, lead_name=lead_name, members=members)


def _is_descendant(meta: SessionMeta, index: dict[str, SessionMeta], root_id: str) -> bool:
    current: SessionMeta | None = meta
    seen: set[str] = set()
    while current is not None:
        if current.session_id == root_id:
            return True
        if current.session_id in seen:
            break
        seen.add(current.session_id)
        if current.parent_id is None:
            break
        current = index.get(current.parent_id)
    return False


def _session_tree(
    *,
    session_index: SessionIndex,
    now: datetime,
) -> tuple[dict[str, SessionMeta], dict[str, list[str]], str | None]:
    metas = session_index.recent_metas(now)
    if not metas:
        return {}, {}, None

    by_id: dict[str, SessionMeta] = {}
    for meta in metas:
        existing = by_id.get(meta.session_id)
        if existing is None or meta.mtime >= existing.mtime:
            by_id[meta.session_id] = meta

    roots = [meta for meta in by_id.values() if meta.parent_id is None]
    if roots:
        roots.sort(key=lambda item: item.mtime, reverse=True)
        active_root = roots[0]
    else:
        ranked = sorted(by_id.values(), key=lambda item: item.mtime, reverse=True)
        active_root = ranked[0]
    active_root_id = active_root.session_id

    active_nodes: dict[str, SessionMeta] = {}
    for sid, meta in by_id.items():
        if _is_descendant(meta, by_id, active_root_id):
            active_nodes[sid] = meta
    children: dict[str, list[str]] = {}
    for sid, meta in active_nodes.items():
        parent_id = meta.parent_id
        if not parent_id:
            continue
        if parent_id not in active_nodes:
            continue
        children.setdefault(parent_id, []).append(sid)
    for parent, child_ids in list(children.items()):
        child_ids.sort(key=lambda sid: active_nodes[sid].nickname.lower())
        children[parent] = child_ids
    return active_nodes, children, active_root_id


def _status_line(
    name: str,
    *,
    metrics: SessionMetrics | None,
    now: datetime,
    outbox_active: int,
    inbox_pending: int,
) -> str:
    status = _member_status(metrics, now, outbox_active)
    tool_uses = metrics.tool_uses if metrics is not None else 0
    token_text = _format_tokens(metrics.total_tokens if metrics is not None else None)
    suffix = ""
    if inbox_pending > 0:
        suffix = f" · inbox {inbox_pending}"
    if outbox_active > 0:
        suffix = f"{suffix} · outbox {outbox_active}"
    return f"{name}: {status} · {tool_uses} tool uses · {token_text} tokens{suffix}"


def _limit_width(line: str, width: int) -> str:
    if width <= 1:
        return ""
    if len(line) <= width:
        return line
    if width <= 4:
        return line[:width]
    return line[: width - 3] + "..."


def _panel_lines(runtime: OverlayRuntime) -> list[str]:
    now = datetime.now(UTC)
    sessions, children, active_root_id = _session_tree(
        session_index=runtime.team_index,
        now=now,
    )
    metrics_by_id: dict[str, SessionMetrics] = {}
    for sid, meta in sessions.items():
        metrics_by_id[sid] = runtime.team_index.metrics_for(meta.path)

    lines: list[str] = []
    lines.append("Codex Agent Teams")
    lines.append("")
    team = _active_team(runtime.teams_root)

    session_name_map: dict[str, str] = {}
    for sid, meta in sessions.items():
        session_name_map[meta.nickname.casefold()] = sid

    if team is not None:
        lead_sid = session_name_map.get(team.lead_name.casefold())
        lead_metrics = metrics_by_id.get(lead_sid) if lead_sid else None
        lead_tokens = _format_tokens(lead_metrics.total_tokens if lead_metrics is not None else None)
        lines.append(f"|- {team.lead_name} · {lead_tokens} tokens")
        for member in team.members:
            if member.name == team.lead_name:
                continue
            sid = session_name_map.get(member.name.casefold())
            if sid is None and member.agent_id in sessions:
                sid = member.agent_id
            metrics = metrics_by_id.get(sid) if sid is not None else None
            lines.append(
                "|- "
                + _status_line(
                    member.name,
                    metrics=metrics,
                    now=now,
                    outbox_active=member.outbox_active,
                    inbox_pending=member.inbox_pending,
                )
            )
    elif active_root_id is not None:
        root_meta = sessions.get(active_root_id)
        if root_meta is not None:
            root_metrics = metrics_by_id.get(active_root_id)
            root_tokens = _format_tokens(root_metrics.total_tokens if root_metrics is not None else None)
            lines.append(f"|- {root_meta.nickname} · {root_tokens} tokens")

            def append_children(parent_id: str, prefix: str) -> None:
                for child_id in children.get(parent_id, []):
                    child_meta = sessions[child_id]
                    child_metrics = metrics_by_id.get(child_id)
                    lines.append(
                        f"{prefix}|- "
                        + _status_line(
                            child_meta.nickname,
                            metrics=child_metrics,
                            now=now,
                            outbox_active=0,
                            inbox_pending=0,
                        )
                    )
                    append_children(child_id, prefix + "   ")

            append_children(active_root_id, "")
    else:
        lines.append(f"no team or active sessions found under {runtime.teams_root}")

    lines.append("")
    lines.append("Shift+Down to return. Panel auto-refreshes.")
    return lines


def _render_panel(runtime: OverlayRuntime, stdout_fd: int) -> None:
    width, height = shutil.get_terminal_size(fallback=(120, 40))
    lines = _panel_lines(runtime)
    max_lines = max(height - 1, 1)
    lines = lines[:max_lines]
    body = "\r\n".join(_limit_width(line, width) for line in lines)
    if len(lines) < max_lines:
        body += "\r\n" * (max_lines - len(lines))
    payload = "\x1b[H\x1b[2J" + body
    os.write(stdout_fd, payload.encode("utf-8", errors="replace"))


def _enter_panel(runtime: OverlayRuntime, stdout_fd: int) -> None:
    runtime.panel_open = True
    runtime.next_render_at = 0.0
    os.write(stdout_fd, b"\x1b[?1049h\x1b[?25l")


def _exit_panel(runtime: OverlayRuntime, stdout_fd: int) -> None:
    runtime.panel_open = False
    os.write(stdout_fd, b"\x1b[?25h\x1b[?1049l")
    if runtime.child_backlog:
        os.write(stdout_fd, bytes(runtime.child_backlog))
        runtime.child_backlog.clear()


def _forward_input(
    *,
    buffer: bytes,
    master_fd: int,
    runtime: OverlayRuntime,
    stdout_fd: int,
) -> bytes:
    while buffer:
        if runtime.panel_open:
            if buffer.startswith(SHIFT_DOWN_SEQ):
                _exit_panel(runtime, stdout_fd)
                buffer = buffer[len(SHIFT_DOWN_SEQ) :]
                continue
            if buffer.startswith(b"q") or buffer.startswith(b"Q") or buffer.startswith(b"\x03"):
                _exit_panel(runtime, stdout_fd)
                buffer = buffer[1:]
                continue
            if buffer.startswith(b"\x1b"):
                # Ignore control sequences while the panel is open.
                if len(buffer) == 1:
                    _exit_panel(runtime, stdout_fd)
                    buffer = buffer[1:]
                    continue
                if buffer[1] in {ord("["), ord("O")}:
                    for idx in range(2, len(buffer)):
                        code = buffer[idx]
                        if 0x40 <= code <= 0x7E:
                            buffer = buffer[idx + 1 :]
                            break
                    else:
                        return buffer
                    continue
                buffer = buffer[1:]
                continue
            buffer = buffer[1:]
            continue

        idx = buffer.find(SHIFT_DOWN_SEQ)
        if idx < 0:
            os.write(master_fd, buffer)
            return b""
        if idx > 0:
            os.write(master_fd, buffer[:idx])
        _enter_panel(runtime, stdout_fd)
        buffer = buffer[idx + len(SHIFT_DOWN_SEQ) :]
    return buffer


def _run_overlay(real_codex: str, codex_args: list[str], teams_root: Path, sessions_root: Path) -> int:
    pid, master_fd = pty.fork()
    if pid == 0:
        os.execv(real_codex, [real_codex, *codex_args])
        raise SystemExit(127)

    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    old_tty = termios.tcgetattr(stdin_fd)
    input_buffer = b""
    stdin_open = True
    stdin_closed_at: float | None = None
    term_sent = False
    runtime = OverlayRuntime(
        team_index=SessionIndex(sessions_root=sessions_root),
        sessions_root=sessions_root,
        teams_root=teams_root,
    )
    exit_code = 1
    try:
        tty.setraw(stdin_fd)
        while True:
            timeout = 0.1
            if runtime.panel_open:
                now_monotonic = time.monotonic()
                if runtime.next_render_at <= now_monotonic:
                    _render_panel(runtime, stdout_fd)
                    runtime.next_render_at = now_monotonic + REFRESH_INTERVAL_SECONDS
                timeout = min(timeout, max(runtime.next_render_at - now_monotonic, 0.01))

            fds = [master_fd]
            if stdin_open:
                fds.append(stdin_fd)
            readable, _, _ = select.select(fds, [], [], timeout)
            if master_fd in readable:
                try:
                    chunk = os.read(master_fd, 8192)
                except OSError:
                    chunk = b""
                if not chunk:
                    _, status = os.waitpid(pid, 0)
                    if os.WIFEXITED(status):
                        exit_code = os.WEXITSTATUS(status)
                    elif os.WIFSIGNALED(status):
                        sig = os.WTERMSIG(status)
                        exit_code = 128 + sig
                    break
                if runtime.panel_open:
                    runtime.child_backlog.extend(chunk)
                    if len(runtime.child_backlog) > OUTPUT_BACKLOG_MAX_BYTES:
                        trim = len(runtime.child_backlog) - OUTPUT_BACKLOG_MAX_BYTES
                        del runtime.child_backlog[:trim]
                else:
                    os.write(stdout_fd, chunk)

            if stdin_open and stdin_fd in readable:
                incoming = os.read(stdin_fd, 1024)
                if not incoming:
                    stdin_open = False
                    stdin_closed_at = time.monotonic()
                    try:
                        os.kill(pid, signal.SIGHUP)
                    except OSError:
                        pass
                    continue
                input_buffer += incoming
                input_buffer = _forward_input(
                    buffer=input_buffer,
                    master_fd=master_fd,
                    runtime=runtime,
                    stdout_fd=stdout_fd,
                )

            if stdin_closed_at is not None:
                elapsed = time.monotonic() - stdin_closed_at
                if elapsed >= 2.0 and not term_sent:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        pass
                    term_sent = True
                if elapsed >= 4.0:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass
    finally:
        if runtime.panel_open:
            _exit_panel(runtime, stdout_fd)
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_tty)
        try:
            os.close(master_fd)
        except OSError:
            pass
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--real-codex", required=True)
    parser.add_argument("--teams-root", default=str(Path.home() / ".codex" / "teams"))
    parser.add_argument("--sessions-root", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args()

    codex_args = list(ns.args)
    if codex_args and codex_args[0] == "--":
        codex_args = codex_args[1:]

    real_codex = str(Path(ns.real_codex).expanduser())
    if not Path(real_codex).exists():
        print(f"real codex binary not found: {real_codex}", file=sys.stderr)
        return 1

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        os.execv(real_codex, [real_codex, *codex_args])
        return 127

    teams_root = Path(ns.teams_root).expanduser()
    sessions_root = Path(ns.sessions_root).expanduser()
    try:
        return _run_overlay(
            real_codex=real_codex,
            codex_args=codex_args,
            teams_root=teams_root,
            sessions_root=sessions_root,
        )
    except Exception as exc:
        if os.environ.get("CODEX_TEAM_OVERLAY_DEBUG") == "1":
            print(f"[codex-overlay] fallback to real codex after error: {exc}", file=sys.stderr)
        os.execv(real_codex, [real_codex, *codex_args])
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
