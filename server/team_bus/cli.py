from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from .models import MessageType, TeamMessage
from .relay import TeamRelay
from .store import TeamStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex Agent Teams file-bus CLI")
    parser.add_argument(
        "--base-dir",
        default=None,
        help="team storage root (default: ~/.codex/teams)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list teams")
    list_parser.set_defaults(command="list")

    create_parser = subparsers.add_parser("create", help="create a new team")
    create_parser.add_argument("team", help="team name")
    create_parser.add_argument("--description", default="", help="team description")
    create_parser.add_argument("--lead-name", required=True, help="lead member name")
    create_parser.add_argument("--lead-agent-id", required=True, help="lead agent id")

    add_member_parser = subparsers.add_parser("add-member", help="add a member to a team")
    add_member_parser.add_argument("team", help="team name")
    add_member_parser.add_argument("--name", required=True, help="member name")
    add_member_parser.add_argument("--agent-id", required=True, help="member agent id")
    add_member_parser.add_argument("--role", default="general-purpose", help="member role")
    add_member_parser.add_argument("--model", default=None, help="model name")
    add_member_parser.add_argument("--cwd", default=None, help="member working directory")
    add_member_parser.add_argument("--safety-profile", default=None, help="optional safety profile label")
    add_member_parser.add_argument(
        "--subscription",
        action="append",
        default=[],
        help="add a subscription topic (can repeat)",
    )

    send_parser = subparsers.add_parser("send", help="queue a team message")
    send_parser.add_argument("team", help="team name")
    send_parser.add_argument("--from-member", required=True, help="sender member name or agent id")
    send_parser.add_argument("--to-member", required=True, help="recipient member name or agent id")
    send_parser.add_argument(
        "--type",
        required=True,
        choices=[m.value for m in MessageType],
        help="message type",
    )
    send_parser.add_argument("--text", required=True, help="message body")
    send_parser.add_argument("--subject", default=None, help="optional subject")
    send_parser.add_argument("--correlation-id", default=None, help="optional correlation id")
    send_parser.add_argument("--message-id", default=None, help="optional explicit message id")
    send_parser.add_argument("--requires-ack", action="store_true", help="mark message as requiring ack")
    send_parser.add_argument("--hop-count", type=int, default=0, help="hop count")

    tail_parser = subparsers.add_parser("tail", help="read inbox/outbox/journal events")
    tail_parser.add_argument("team", help="team name")
    tail_parser.add_argument(
        "--box",
        choices=["inbox", "outbox", "journal"],
        default="inbox",
        help="which log/mailbox to read",
    )
    tail_parser.add_argument("--member", default=None, help="member name (required for inbox/outbox)")
    tail_parser.add_argument("--limit", type=int, default=20, help="number of most recent entries")

    ack_parser = subparsers.add_parser("ack", help="ack an inbox message")
    ack_parser.add_argument("team", help="team name")
    ack_parser.add_argument("--member", required=True, help="member acknowledging the message")
    ack_parser.add_argument("--message-id", required=True, help="message id to acknowledge")
    ack_parser.add_argument("--note", default=None, help="optional ack note")
    ack_parser.add_argument(
        "--no-notify-sender",
        action="store_true",
        help="do not queue a status_update back to sender",
    )

    relay_parser = subparsers.add_parser("relay", help="run message relay")
    relay_parser.add_argument("team", help="team name")
    relay_parser.add_argument("--once", action="store_true", help="process one pass and exit")
    relay_parser.add_argument("--interval-seconds", type=float, default=1.0, help="loop interval")
    relay_parser.add_argument("--max-iterations", type=int, default=None, help="optional loop cap")

    validate_parser = subparsers.add_parser("validate", help="validate team files")
    validate_parser.add_argument("team", help="team name")

    import_parser = subparsers.add_parser("import-claude", help="import a Claude team config")
    import_parser.add_argument("team", help="team folder name under Claude root")
    import_parser.add_argument(
        "--claude-root",
        default="~/.claude",
        help="Claude root path containing teams/<team>/config.json",
    )
    import_parser.add_argument("--overwrite", action="store_true", help="overwrite existing Codex team")

    watch_parser = subparsers.add_parser("watch", help="watch team traffic in real time")
    watch_parser.add_argument("team", help="team name")
    watch_parser.add_argument(
        "--box",
        choices=["journal", "inbox", "outbox", "all"],
        default="journal",
        help="stream source",
    )
    watch_parser.add_argument("--member", default=None, help="member name (required for inbox/outbox)")
    watch_parser.add_argument("--limit", type=int, default=20, help="initial backlog entries")
    watch_parser.add_argument("--follow", action="store_true", help="follow new entries")
    watch_parser.add_argument("--poll-interval", type=float, default=0.5, help="poll interval in seconds")
    watch_parser.add_argument("--timeout-seconds", type=float, default=None, help="stop after N seconds")

    wait_parser = subparsers.add_parser("wait", help="wait for next inbox message")
    wait_parser.add_argument("team", help="team name")
    wait_parser.add_argument("--member", required=True, help="member inbox to monitor")
    wait_parser.add_argument("--poll-interval", type=float, default=0.5, help="poll interval in seconds")
    wait_parser.add_argument("--timeout-seconds", type=float, default=120.0, help="wait timeout")
    wait_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="allow returning existing inbox messages instead of only newly arrived ones",
    )
    return parser


def _store_from_args(args: argparse.Namespace) -> TeamStore:
    if args.base_dir:
        return TeamStore(base_dir=Path(args.base_dir).expanduser())
    return TeamStore()


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=True))


T = TypeVar("T")


def _tail_entries(items: list[T], limit: int) -> list[T]:
    if limit <= 0:
        return []
    return items[-limit:]


def _mailbox_signatures(messages: list[TeamMessage], box: str, member: str) -> set[str]:
    out: set[str] = set()
    for msg in messages:
        out.add(
            "|".join(
                [
                    box,
                    member,
                    msg.message_id,
                    msg.status.value,
                    str(msg.delivery_attempts),
                ]
            )
        )
    return out


def _dump_json_line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True))
    sys.stdout.flush()


def _watch_journal(
    *,
    store: TeamStore,
    team: str,
    limit: int,
    follow: bool,
    poll_interval: float,
    timeout_seconds: float | None,
) -> int:
    events = store.read_journal(team)
    for event in _tail_entries(events, limit):
        _dump_json_line({"stream": "journal", "event": event.model_dump(mode="json", by_alias=True)})

    seen_ids = {event.event_id for event in events}
    if not follow:
        return 0

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return 0
        time.sleep(poll_interval)
        for event in store.read_journal(team):
            if event.event_id in seen_ids:
                continue
            seen_ids.add(event.event_id)
            _dump_json_line({"stream": "journal", "event": event.model_dump(mode="json", by_alias=True)})


def _watch_mailbox(
    *,
    store: TeamStore,
    team: str,
    box: str,
    member: str,
    limit: int,
    follow: bool,
    poll_interval: float,
    timeout_seconds: float | None,
) -> int:
    if box == "inbox":
        messages = store.read_inbox(team, member)
    else:
        messages = store.read_outbox(team, member)
    for msg in _tail_entries(messages, limit):
        _dump_json_line(
            {
                "stream": box,
                "member": member,
                "message": msg.model_dump(mode="json", by_alias=True),
            }
        )

    seen = _mailbox_signatures(messages, box, member)
    if not follow:
        return 0

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return 0
        time.sleep(poll_interval)
        if box == "inbox":
            current = store.read_inbox(team, member)
        else:
            current = store.read_outbox(team, member)
        for msg in current:
            signature = "|".join(
                [
                    box,
                    member,
                    msg.message_id,
                    msg.status.value,
                    str(msg.delivery_attempts),
                ]
            )
            if signature in seen:
                continue
            seen.add(signature)
            _dump_json_line(
                {
                    "stream": box,
                    "member": member,
                    "message": msg.model_dump(mode="json", by_alias=True),
                }
            )


def _watch_all(
    *,
    store: TeamStore,
    team: str,
    limit: int,
    follow: bool,
    poll_interval: float,
    timeout_seconds: float | None,
) -> int:
    cfg = store.load_config(team)
    seen: set[str] = set()

    for member in cfg.members:
        inbox = store.read_inbox(team, member.name)
        outbox = store.read_outbox(team, member.name)
        for msg in _tail_entries(inbox, limit):
            signature = "|".join(["inbox", member.name, msg.message_id, msg.status.value, str(msg.delivery_attempts)])
            seen.add(signature)
            _dump_json_line(
                {
                    "stream": "inbox",
                    "member": member.name,
                    "message": msg.model_dump(mode="json", by_alias=True),
                }
            )
        for msg in _tail_entries(outbox, limit):
            signature = "|".join(["outbox", member.name, msg.message_id, msg.status.value, str(msg.delivery_attempts)])
            seen.add(signature)
            _dump_json_line(
                {
                    "stream": "outbox",
                    "member": member.name,
                    "message": msg.model_dump(mode="json", by_alias=True),
                }
            )

    if not follow:
        return 0

    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            return 0
        time.sleep(poll_interval)
        cfg = store.load_config(team)
        for member in cfg.members:
            for box in ("inbox", "outbox"):
                if box == "inbox":
                    messages = store.read_inbox(team, member.name)
                else:
                    messages = store.read_outbox(team, member.name)
                for msg in messages:
                    signature = "|".join(
                        [box, member.name, msg.message_id, msg.status.value, str(msg.delivery_attempts)]
                    )
                    if signature in seen:
                        continue
                    seen.add(signature)
                    _dump_json_line(
                        {
                            "stream": box,
                            "member": member.name,
                            "message": msg.model_dump(mode="json", by_alias=True),
                        }
                    )


def _wait_for_next_message(
    *,
    store: TeamStore,
    team: str,
    member: str,
    include_existing: bool,
    poll_interval: float,
    timeout_seconds: float,
) -> int:
    wait_started_at = datetime.now(UTC)
    baseline = set()
    if not include_existing:
        baseline = {msg.message_id for msg in store.read_inbox(team, member) if msg.timestamp < wait_started_at}

    deadline = time.monotonic() + timeout_seconds
    while True:
        inbox = store.read_inbox(team, member)
        for msg in inbox:
            if include_existing:
                _print_json(msg.model_dump(mode="json", by_alias=True))
                return 0
            if msg.timestamp >= wait_started_at:
                _print_json(msg.model_dump(mode="json", by_alias=True))
                return 0
            if msg.message_id not in baseline:
                _print_json(msg.model_dump(mode="json", by_alias=True))
                return 0
        if time.monotonic() >= deadline:
            err_msg = f"timeout waiting for message for member={member}"
            raise TimeoutError(err_msg)
        time.sleep(poll_interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = _store_from_args(args)

    try:
        if args.command == "list":
            _print_json({"teams": store.list_teams()})
            return 0

        if args.command == "create":
            config = store.create_team(
                name=args.team,
                description=args.description,
                lead_name=args.lead_name,
                lead_agent_id=args.lead_agent_id,
            )
            _print_json(config.model_dump(mode="json", by_alias=True))
            return 0

        if args.command == "add-member":
            config = store.add_member(
                team=args.team,
                name=args.name,
                agent_id=args.agent_id,
                role=args.role,
                model=args.model,
                cwd=args.cwd,
                safety_profile=args.safety_profile,
                subscriptions=list(args.subscription),
            )
            _print_json(config.model_dump(mode="json", by_alias=True))
            return 0

        if args.command == "send":
            message_data: dict[str, Any] = {
                "team": args.team,
                "from_member": args.from_member,
                "to_member": args.to_member,
                "type": MessageType(args.type),
                "subject": args.subject,
                "text": args.text,
                "correlation_id": args.correlation_id,
                "requires_ack": bool(args.requires_ack),
                "hop_count": args.hop_count,
            }
            if args.message_id:
                message_data["message_id"] = args.message_id
            message = TeamMessage(
                **message_data
            )
            queued = store.queue_message(args.team, message)
            _print_json(queued.model_dump(mode="json", by_alias=True))
            return 0

        if args.command == "tail":
            limit = max(args.limit, 0)
            if args.box == "journal":
                events = store.read_journal(args.team)
                payload = [evt.model_dump(mode="json", by_alias=True) for evt in _tail_entries(events, limit)]
                _print_json(payload)
                return 0
            if not args.member:
                msg = "--member is required for inbox/outbox"
                raise ValueError(msg)
            if args.box == "inbox":
                messages = store.read_inbox(args.team, args.member)
            else:
                messages = store.read_outbox(args.team, args.member)
            payload = [msg.model_dump(mode="json", by_alias=True) for msg in _tail_entries(messages, limit)]
            _print_json(payload)
            return 0

        if args.command == "ack":
            acked = store.ack_inbox_message(
                team=args.team,
                member=args.member,
                message_id=args.message_id,
                note=args.note,
                notify_sender=not bool(args.no_notify_sender),
            )
            _print_json(acked.model_dump(mode="json", by_alias=True))
            return 0

        if args.command == "relay":
            relay = TeamRelay(store=store)
            result = relay.run(
                args.team,
                interval_seconds=float(args.interval_seconds),
                once=bool(args.once),
                max_iterations=args.max_iterations,
            )
            _print_json(result.as_dict())
            return 0

        if args.command == "validate":
            errors = store.validate_team(args.team)
            validate_result = {"team": args.team, "valid": not errors, "errors": errors}
            _print_json(validate_result)
            return 0 if not errors else 1

        if args.command == "import-claude":
            config = store.import_claude_team(
                claude_root=Path(args.claude_root).expanduser(),
                team_name=args.team,
                overwrite=bool(args.overwrite),
            )
            _print_json(config.model_dump(mode="json", by_alias=True))
            return 0

        if args.command == "watch":
            if args.poll_interval <= 0:
                msg = "--poll-interval must be > 0"
                raise ValueError(msg)
            if args.box == "journal":
                return _watch_journal(
                    store=store,
                    team=args.team,
                    limit=max(args.limit, 0),
                    follow=bool(args.follow),
                    poll_interval=float(args.poll_interval),
                    timeout_seconds=args.timeout_seconds,
                )
            if args.box in {"inbox", "outbox"}:
                if not args.member:
                    msg = "--member is required for inbox/outbox watch"
                    raise ValueError(msg)
                return _watch_mailbox(
                    store=store,
                    team=args.team,
                    box=args.box,
                    member=args.member,
                    limit=max(args.limit, 0),
                    follow=bool(args.follow),
                    poll_interval=float(args.poll_interval),
                    timeout_seconds=args.timeout_seconds,
                )
            return _watch_all(
                store=store,
                team=args.team,
                limit=max(args.limit, 0),
                follow=bool(args.follow),
                poll_interval=float(args.poll_interval),
                timeout_seconds=args.timeout_seconds,
            )

        if args.command == "wait":
            if args.poll_interval <= 0:
                msg = "--poll-interval must be > 0"
                raise ValueError(msg)
            if args.timeout_seconds <= 0:
                msg = "--timeout-seconds must be > 0"
                raise ValueError(msg)
            return _wait_for_next_message(
                store=store,
                team=args.team,
                member=args.member,
                include_existing=bool(args.include_existing),
                poll_interval=float(args.poll_interval),
                timeout_seconds=float(args.timeout_seconds),
            )

    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 1

    print(json.dumps({"error": f"unknown command: {args.command}"}, ensure_ascii=True), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
