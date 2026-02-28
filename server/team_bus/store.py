from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    JournalEvent,
    MessageStatus,
    MessageType,
    TeamConfig,
    TeamMember,
    TeamMessage,
    TeamPolicy,
    TeamRoute,
)
from .policy import resolve_member_name
from .utils import atomic_write_json, file_lock, parse_timestamp


class TeamStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (Path.home() / ".codex" / "teams")

    def list_teams(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        out: list[str] = []
        for p in self.base_dir.iterdir():
            if p.is_dir() and (p / "config.json").exists():
                out.append(p.name)
        return sorted(out)

    def team_exists(self, team: str) -> bool:
        return self._team_dir(team).exists()

    def create_team(self, *, name: str, description: str, lead_name: str, lead_agent_id: str) -> TeamConfig:
        team_name = name.strip()
        if not team_name:
            msg = "team name cannot be empty"
            raise ValueError(msg)
        if self.team_exists(team_name):
            msg = f"team already exists: {team_name}"
            raise ValueError(msg)
        lead = TeamMember(agent_id=lead_agent_id, name=lead_name, role="team-lead")
        cfg = TeamConfig(
            name=team_name,
            description=description.strip(),
            lead_agent_id=lead.agent_id,
            members=[lead],
            policy=TeamPolicy(
                allowed_routes=[
                    TeamRoute(from_member="*", to_member=lead.name),
                    TeamRoute(from_member=lead.name, to_member="*"),
                ]
            ),
        )
        self._ensure_team_dirs(team_name)
        self.save_config(cfg)
        self._save_box(team_name, self._inbox_path(team_name, lead.name), [])
        self._save_box(team_name, self._outbox_path(team_name, lead.name), [])
        return cfg

    def load_config(self, team: str) -> TeamConfig:
        path = self._config_path(team)
        if not path.exists():
            msg = f"team config not found: {team}"
            raise FileNotFoundError(msg)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return TeamConfig.model_validate(raw)

    def save_config(self, config: TeamConfig) -> None:
        self._ensure_team_dirs(config.name)
        lock = self._lock_path(config.name, "config.lock")
        with file_lock(lock):
            atomic_write_json(self._config_path(config.name), config.model_dump(mode="json", by_alias=True))

    def validate_team(self, team: str) -> list[str]:
        errors: list[str] = []
        try:
            cfg = self.load_config(team)
        except Exception as exc:
            return [f"config invalid: {exc}"]

        names = {m.name for m in cfg.members}
        ids = {m.agent_id for m in cfg.members}
        if cfg.lead_agent_id not in ids:
            errors.append("leadAgentId does not match any member agentId")

        for route in cfg.policy.allowed_routes:
            if route.from_member != "*" and route.from_member not in names:
                errors.append(f"route from-member does not exist: {route.from_member}")
            if route.to_member != "*" and route.to_member not in names:
                errors.append(f"route to-member does not exist: {route.to_member}")

        for m in cfg.members:
            for box in (self._inbox_path(team, m.name), self._outbox_path(team, m.name)):
                try:
                    self._load_box(box)
                except Exception as exc:
                    errors.append(f"invalid box file {box}: {exc}")
        return errors

    def add_member(
        self,
        *,
        team: str,
        name: str,
        agent_id: str,
        role: str = "general-purpose",
        model: str | None = None,
        cwd: str | None = None,
        safety_profile: str | None = None,
        subscriptions: list[str] | None = None,
    ) -> TeamConfig:
        cfg = self.load_config(team)
        member = TeamMember(
            agent_id=agent_id,
            name=name,
            role=role,
            model=model,
            cwd=cwd,
            safety_profile=safety_profile,
            subscriptions=subscriptions or [],
        )
        cfg.members = [*cfg.members, member]
        self.save_config(cfg)
        self._save_box(team, self._inbox_path(team, member.name), [])
        self._save_box(team, self._outbox_path(team, member.name), [])
        return cfg

    def read_inbox(self, team: str, member: str) -> list[TeamMessage]:
        return self._load_box(self._inbox_path(team, member))

    def read_outbox(self, team: str, member: str) -> list[TeamMessage]:
        return self._load_box(self._outbox_path(team, member))

    def save_inbox(self, team: str, member: str, messages: list[TeamMessage]) -> None:
        self._save_box(team, self._inbox_path(team, member), messages)

    def save_outbox(self, team: str, member: str, messages: list[TeamMessage]) -> None:
        self._save_box(team, self._outbox_path(team, member), messages)

    def read_journal(self, team: str) -> list[JournalEvent]:
        path = self._journal_path(team)
        if not path.exists():
            return []
        out: list[JournalEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw:
                continue
            out.append(JournalEvent.model_validate_json(raw))
        return out

    def append_journal(self, team: str, event: JournalEvent) -> None:
        path = self._journal_path(team)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._lock_path(team, "journal.lock")
        with file_lock(lock):
            with path.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json(by_alias=True) + "\n")

    def known_message_ids(self, team: str) -> set[str]:
        ids: set[str] = set()
        for evt in self.read_journal(team):
            if evt.message_id:
                ids.add(evt.message_id)
        cfg = self.load_config(team)
        for member in cfg.members:
            for msg in self.read_inbox(team, member.name):
                ids.add(msg.message_id)
            for msg in self.read_outbox(team, member.name):
                ids.add(msg.message_id)
        return ids

    def queue_message(self, team: str, message: TeamMessage) -> TeamMessage:
        cfg = self.load_config(team)
        sender = resolve_member_name(cfg, message.from_member or "")
        recipient = resolve_member_name(cfg, message.to_member or "")
        if sender is None:
            msg = f"unknown sender: {message.from_member}"
            raise ValueError(msg)
        if recipient is None:
            msg = f"unknown recipient: {message.to_member}"
            raise ValueError(msg)
        requires_ack = bool(message.requires_ack)
        if message.type in set(cfg.policy.require_ack_types):
            requires_ack = True
        msg_obj = message.model_copy(
            update={
                "team": team,
                "from_member": sender,
                "to_member": recipient,
                "requires_ack": requires_ack,
                "status": MessageStatus.QUEUED,
            }
        )
        outbox = self.read_outbox(team, sender)
        outbox.append(msg_obj)
        self.save_outbox(team, sender, outbox)
        self.append_journal(
            team,
            JournalEvent(
                team=team,
                event_type="outbox_queued",
                message_id=msg_obj.message_id,
                from_member=sender,
                to_member=recipient,
                status=msg_obj.status.value,
                meta=self._message_event_meta(msg_obj),
            ),
        )
        return msg_obj

    def deliver_to_inbox(self, team: str, message: TeamMessage) -> bool:
        inbox = self.read_inbox(team, message.to_member)
        if any(m.message_id == message.message_id for m in inbox):
            return False
        inbox_msg = message.model_copy(update={"status": MessageStatus.PENDING})
        inbox.append(inbox_msg)
        self.save_inbox(team, message.to_member, inbox)
        return True

    def mark_outbox_message(
        self,
        *,
        team: str,
        sender: str,
        message_id: str,
        status: MessageStatus,
        reason: str | None = None,
    ) -> TeamMessage:
        outbox = self.read_outbox(team, sender)
        for idx, msg in enumerate(outbox):
            if msg.message_id != message_id:
                continue
            updated = msg.model_copy(update={"status": status, "delivery_attempts": msg.delivery_attempts + 1})
            if reason:
                meta = dict(updated.meta)
                meta["reason"] = reason
                updated = updated.model_copy(update={"meta": meta})
            outbox[idx] = updated
            self.save_outbox(team, sender, outbox)
            return updated
        raise KeyError(f"message not found in outbox: {message_id}")

    def ack_inbox_message(
        self,
        *,
        team: str,
        member: str,
        message_id: str,
        note: str | None = None,
        notify_sender: bool = True,
    ) -> TeamMessage:
        inbox = self.read_inbox(team, member)
        target: TeamMessage | None = None
        for idx, msg in enumerate(inbox):
            if msg.message_id != message_id:
                continue
            meta = dict(msg.meta)
            if note:
                meta["ack_note"] = note
            meta["acked_at"] = parse_timestamp(None).isoformat()
            target = msg.model_copy(update={"status": MessageStatus.ACKED, "meta": meta})
            inbox[idx] = target
            break
        if target is None:
            raise KeyError(f"message not found in inbox: {message_id}")
        self.save_inbox(team, member, inbox)
        self.append_journal(
            team,
            JournalEvent(
                team=team,
                event_type="message_acked",
                message_id=target.message_id,
                from_member=member,
                to_member=target.from_member,
                status=target.status.value,
                reason=note,
            ),
        )
        if notify_sender:
            ack = TeamMessage(
                team=team,
                from_member=member,
                to_member=target.from_member,
                type=MessageType.STATUS_UPDATE,
                text=f"Acked message {target.message_id}",
                ack_of=target.message_id,
                correlation_id=target.correlation_id,
            )
            self.queue_message(team, ack)
        return target

    def import_claude_team(
        self,
        *,
        claude_root: Path,
        team_name: str,
        overwrite: bool = False,
    ) -> TeamConfig:
        cfg_path = claude_root / "teams" / team_name / "config.json"
        if not cfg_path.exists():
            msg = f"Claude team config not found: {cfg_path}"
            raise FileNotFoundError(msg)
        if self.team_exists(team_name) and not overwrite:
            msg = f"team already exists: {team_name} (use --overwrite)"
            raise ValueError(msg)

        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        members_raw = raw.get("members") or []
        members: list[TeamMember] = []
        for entry in members_raw:
            members.append(
                TeamMember(
                    agent_id=str(entry.get("agentId") or ""),
                    name=str(entry.get("name") or ""),
                    role=str(entry.get("agentType") or "general-purpose"),
                    model=str(entry.get("model") or "") or None,
                    cwd=str(entry.get("cwd") or "") or None,
                    subscriptions=[str(x) for x in (entry.get("subscriptions") or [])],
                )
            )
        if not members:
            msg = f"no members in Claude team config: {cfg_path}"
            raise ValueError(msg)
        lead_agent_id = str(raw.get("leadAgentId") or members[0].agent_id)
        cfg = TeamConfig(
            name=team_name,
            description=str(raw.get("description") or ""),
            lead_agent_id=lead_agent_id,
            members=members,
            policy=TeamPolicy(
                allowed_routes=[
                    TeamRoute(from_member="*", to_member=members[0].name),
                    TeamRoute(from_member=members[0].name, to_member="*"),
                ]
            ),
        )

        if overwrite and self.team_exists(team_name):
            for path in sorted(self._team_dir(team_name).rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        pass
        self._ensure_team_dirs(team_name)
        self.save_config(cfg)
        for m in members:
            self._save_box(team_name, self._inbox_path(team_name, m.name), [])
            self._save_box(team_name, self._outbox_path(team_name, m.name), [])

        inbox_root = claude_root / "teams" / team_name / "inboxes"
        if inbox_root.exists():
            for path in sorted(inbox_root.glob("*.json")):
                recipient = path.stem
                if recipient not in {m.name for m in members}:
                    continue
                raw_messages = json.loads(path.read_text(encoding="utf-8"))
                converted: list[TeamMessage] = []
                for item in raw_messages:
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    sender = str(item.get("from") or members[0].name)
                    sender_name = resolve_member_name(cfg, sender) or members[0].name
                    converted.append(
                        TeamMessage(
                            team=team_name,
                            from_member=sender_name,
                            to_member=recipient,
                            type=MessageType.STATUS_UPDATE,
                            text=text,
                            timestamp=parse_timestamp(item.get("timestamp")),
                            status=MessageStatus.PENDING,
                            meta={"imported_from_claude": True},
                        )
                    )
                self._save_box(team_name, self._inbox_path(team_name, recipient), converted)
        self.append_journal(
            team_name,
            JournalEvent(
                team=team_name,
                event_type="imported",
                reason=f"imported from {claude_root}/teams/{team_name}",
                status="ok",
            ),
        )
        return cfg

    def _load_box(self, path: Path) -> list[TeamMessage]:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            msg = f"mailbox file must be a JSON list: {path}"
            raise ValueError(msg)
        return [TeamMessage.model_validate(x) for x in raw]

    def _save_box(self, team: str, path: Path, messages: list[TeamMessage]) -> None:
        lock = self._lock_path(team, f"{path.stem}.lock")
        with file_lock(lock):
            atomic_write_json(path, [m.model_dump(mode="json", by_alias=True) for m in messages])

    def _message_event_meta(self, message: TeamMessage) -> dict[str, Any]:
        preview = message.text
        if len(preview) > 220:
            preview = preview[:217] + "..."
        return {
            "messageType": message.type.value,
            "subject": message.subject,
            "requiresAck": message.requires_ack,
            "correlationId": message.correlation_id,
            "textPreview": preview,
        }

    def _team_dir(self, team: str) -> Path:
        return self.base_dir / team

    def _ensure_team_dirs(self, team: str) -> None:
        td = self._team_dir(team)
        (td / "inboxes").mkdir(parents=True, exist_ok=True)
        (td / "outboxes").mkdir(parents=True, exist_ok=True)
        (td / "journal").mkdir(parents=True, exist_ok=True)
        (td / "locks").mkdir(parents=True, exist_ok=True)

    def _config_path(self, team: str) -> Path:
        return self._team_dir(team) / "config.json"

    def _inbox_path(self, team: str, member: str) -> Path:
        return self._team_dir(team) / "inboxes" / f"{member}.json"

    def _outbox_path(self, team: str, member: str) -> Path:
        return self._team_dir(team) / "outboxes" / f"{member}.json"

    def _journal_path(self, team: str) -> Path:
        return self._team_dir(team) / "journal" / "events.jsonl"

    def _lock_path(self, team: str, name: str) -> Path:
        return self._team_dir(team) / "locks" / name
