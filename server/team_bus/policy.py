from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .models import JournalEvent, TeamConfig, TeamMessage


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None


def resolve_member_name(config: TeamConfig, value: str) -> str | None:
    needle = value.strip()
    for m in config.members:
        if m.name == needle or m.agent_id == needle:
            return m.name
    return None


def _route_matches(pattern: str, candidate: str) -> bool:
    return pattern == "*" or pattern == candidate


def is_route_allowed(config: TeamConfig, from_name: str, to_name: str) -> bool:
    if from_name == to_name:
        return True
    for route in config.policy.allowed_routes:
        if _route_matches(route.from_member, from_name) and _route_matches(route.to_member, to_name):
            return True
    return False


def _count_sender_events_last_minute(events: list[JournalEvent], sender: str) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    out = 0
    for evt in events:
        if evt.event_type != "outbox_queued":
            continue
        if evt.from_member != sender:
            continue
        if evt.timestamp >= cutoff:
            out += 1
    return out


def evaluate_message(
    *,
    config: TeamConfig,
    message: TeamMessage,
    known_message_ids: set[str],
    journal_events: list[JournalEvent],
) -> PolicyDecision:
    if message.message_id in known_message_ids:
        return PolicyDecision(False, "duplicate message_id")

    from_name = resolve_member_name(config, message.from_member)
    if from_name is None:
        return PolicyDecision(False, "unknown sender")
    to_name = resolve_member_name(config, message.to_member)
    if to_name is None:
        return PolicyDecision(False, "unknown recipient")

    if not is_route_allowed(config, from_name, to_name):
        return PolicyDecision(False, "route not allowed")

    if message.type not in set(config.policy.allowed_message_types):
        return PolicyDecision(False, f"message type not allowed: {message.type.value}")

    if message.hop_count > config.policy.max_hops:
        return PolicyDecision(False, "max hop count exceeded")

    byte_size = len(message.model_dump_json(by_alias=True).encode("utf-8"))
    if byte_size > config.policy.max_message_bytes:
        return PolicyDecision(False, f"message too large ({byte_size} bytes)")

    recent = _count_sender_events_last_minute(journal_events, from_name)
    if recent >= config.policy.max_messages_per_minute:
        return PolicyDecision(False, "sender rate limit exceeded")

    return PolicyDecision(True, None)
