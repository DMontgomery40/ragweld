from __future__ import annotations

import time
from dataclasses import dataclass

from .models import JournalEvent, MessageStatus, TeamConfig
from .policy import evaluate_message
from .store import TeamStore


@dataclass(slots=True)
class RelayRunResult:
    inspected: int = 0
    delivered: int = 0
    duplicated: int = 0
    rejected: int = 0
    retried: int = 0

    def merge(self, other: RelayRunResult) -> None:
        self.inspected += other.inspected
        self.delivered += other.delivered
        self.duplicated += other.duplicated
        self.rejected += other.rejected
        self.retried += other.retried

    def as_dict(self) -> dict[str, int]:
        return {
            "inspected": self.inspected,
            "delivered": self.delivered,
            "duplicated": self.duplicated,
            "rejected": self.rejected,
            "retried": self.retried,
        }


class TeamRelay:
    def __init__(self, store: TeamStore | None = None) -> None:
        self.store = store or TeamStore()

    def run_once(self, team: str) -> RelayRunResult:
        config = self.store.load_config(team)
        journal = self.store.read_journal(team)
        seen_message_ids = self._seed_seen_ids(team, config, journal)
        result = RelayRunResult()

        for member in config.members:
            outbox = self.store.read_outbox(team, member.name)
            for message in outbox:
                if message.status in {MessageStatus.DELIVERED, MessageStatus.REJECTED, MessageStatus.ACKED}:
                    continue

                result.inspected += 1
                decision = evaluate_message(
                    config=config,
                    message=message,
                    known_message_ids=seen_message_ids,
                    journal_events=journal,
                )
                if not decision.allowed:
                    reject_reason = decision.reason or "policy rejected message"
                    if reject_reason == "sender rate limit exceeded":
                        updated = self.store.mark_outbox_message(
                            team=team,
                            sender=member.name,
                            message_id=message.message_id,
                            status=MessageStatus.RETRY,
                            reason=reject_reason,
                        )
                        event = JournalEvent(
                            team=team,
                            event_type="message_retried",
                            message_id=updated.message_id,
                            from_member=updated.from_member,
                            to_member=updated.to_member,
                            status=updated.status.value,
                            reason=reject_reason,
                        )
                        self.store.append_journal(team, event)
                        journal.append(event)
                        result.retried += 1
                    else:
                        updated = self.store.mark_outbox_message(
                            team=team,
                            sender=member.name,
                            message_id=message.message_id,
                            status=MessageStatus.REJECTED,
                            reason=reject_reason,
                        )
                        event = JournalEvent(
                            team=team,
                            event_type="message_rejected",
                            message_id=updated.message_id,
                            from_member=updated.from_member,
                            to_member=updated.to_member,
                            status=updated.status.value,
                            reason=reject_reason,
                        )
                        self.store.append_journal(team, event)
                        journal.append(event)
                        seen_message_ids.add(updated.message_id)
                        result.rejected += 1
                    continue

                delivered = self.store.deliver_to_inbox(team, message)
                reason = None if delivered else "already delivered to inbox"
                updated = self.store.mark_outbox_message(
                    team=team,
                    sender=member.name,
                    message_id=message.message_id,
                    status=MessageStatus.DELIVERED,
                    reason=reason,
                )
                event = JournalEvent(
                    team=team,
                    event_type="message_delivered",
                    message_id=updated.message_id,
                    from_member=updated.from_member,
                    to_member=updated.to_member,
                    status=updated.status.value,
                    reason=reason,
                )
                self.store.append_journal(team, event)
                journal.append(event)
                seen_message_ids.add(updated.message_id)
                if delivered:
                    result.delivered += 1
                else:
                    result.duplicated += 1

        return result

    def run(
        self,
        team: str,
        *,
        interval_seconds: float = 1.0,
        once: bool = False,
        max_iterations: int | None = None,
    ) -> RelayRunResult:
        if interval_seconds <= 0:
            msg = "interval_seconds must be > 0"
            raise ValueError(msg)
        if max_iterations is not None and max_iterations < 1:
            msg = "max_iterations must be >= 1"
            raise ValueError(msg)
        if once:
            return self.run_once(team)

        aggregated = RelayRunResult()
        iteration = 0
        while True:
            current = self.run_once(team)
            aggregated.merge(current)
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                return aggregated
            time.sleep(interval_seconds)

    def _seed_seen_ids(
        self,
        team: str,
        config: TeamConfig,
        journal: list[JournalEvent],
    ) -> set[str]:
        seen_ids: set[str] = set()
        terminal_events = {"message_delivered", "message_rejected", "message_acked"}
        for event in journal:
            if event.message_id and event.event_type in terminal_events:
                seen_ids.add(event.message_id)

        for member in config.members:
            for message in self.store.read_inbox(team, member.name):
                seen_ids.add(message.message_id)
            for message in self.store.read_outbox(team, member.name):
                if message.status in {MessageStatus.DELIVERED, MessageStatus.REJECTED, MessageStatus.ACKED}:
                    seen_ids.add(message.message_id)
        return seen_ids
