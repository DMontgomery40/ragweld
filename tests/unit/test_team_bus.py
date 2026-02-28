"""Tests for the Codex Agent Teams file bus."""

from server.team_bus.models import MessageStatus, MessageType, TeamMessage
from server.team_bus.relay import TeamRelay
from server.team_bus.store import TeamStore


def _make_team(tmp_path) -> TeamStore:
    store = TeamStore(base_dir=tmp_path / "teams")
    store.create_team(
        name="alpha",
        description="test team",
        lead_name="lead",
        lead_agent_id="agent-lead",
    )
    store.add_member(
        team="alpha",
        name="worker",
        agent_id="agent-worker",
        role="worker",
    )
    return store


def test_create_team_and_add_member(tmp_path) -> None:
    store = TeamStore(base_dir=tmp_path / "teams")
    cfg = store.create_team(
        name="alpha",
        description="test team",
        lead_name="lead",
        lead_agent_id="agent-lead",
    )
    assert cfg.name == "alpha"
    assert [m.name for m in cfg.members] == ["lead"]
    assert store.validate_team("alpha") == []

    cfg = store.add_member(team="alpha", name="worker", agent_id="agent-worker")
    assert {m.name for m in cfg.members} == {"lead", "worker"}
    assert store.validate_team("alpha") == []


def test_send_and_relay_delivery(tmp_path) -> None:
    store = _make_team(tmp_path)
    relay = TeamRelay(store=store)

    queued = store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="lead",
            to_member="worker",
            type=MessageType.TASK_ASSIGNMENT,
            text="Run the integration suite",
        ),
    )
    assert queued.requires_ack is True

    result = relay.run_once("alpha")
    assert result.delivered == 1
    assert result.rejected == 0

    outbox = store.read_outbox("alpha", "lead")
    assert len(outbox) == 1
    assert outbox[0].status is MessageStatus.DELIVERED

    inbox = store.read_inbox("alpha", "worker")
    assert len(inbox) == 1
    assert inbox[0].message_id == queued.message_id
    assert inbox[0].status is MessageStatus.PENDING


def test_route_rejection_for_worker_to_worker(tmp_path) -> None:
    store = _make_team(tmp_path)
    store.add_member(team="alpha", name="worker2", agent_id="agent-worker2")
    relay = TeamRelay(store=store)

    queued = store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="worker",
            to_member="worker2",
            type=MessageType.STATUS_UPDATE,
            text="Ping from worker to worker",
        ),
    )

    result = relay.run_once("alpha")
    assert result.rejected == 1

    outbox = store.read_outbox("alpha", "worker")
    assert len(outbox) == 1
    assert outbox[0].message_id == queued.message_id
    assert outbox[0].status is MessageStatus.REJECTED

    journal = store.read_journal("alpha")
    assert any(
        evt.event_type == "message_rejected"
        and evt.message_id == queued.message_id
        and evt.reason == "route not allowed"
        for evt in journal
    )


def test_inbox_dedupes_on_message_id(tmp_path) -> None:
    store = _make_team(tmp_path)

    queued = store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="lead",
            to_member="worker",
            type=MessageType.STATUS_UPDATE,
            text="Same message delivered twice",
        ),
    )
    delivered_once = store.deliver_to_inbox("alpha", queued)
    delivered_twice = store.deliver_to_inbox("alpha", queued)

    assert delivered_once is True
    assert delivered_twice is False
    inbox = store.read_inbox("alpha", "worker")
    assert len(inbox) == 1


def test_ack_roundtrip_queues_status_update_and_relays_to_sender(tmp_path) -> None:
    store = _make_team(tmp_path)
    relay = TeamRelay(store=store)

    queued = store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="lead",
            to_member="worker",
            type=MessageType.TASK_ASSIGNMENT,
            text="Handle this task",
        ),
    )
    relay.run_once("alpha")
    inbox = store.read_inbox("alpha", "worker")
    assert len(inbox) == 1

    acked = store.ack_inbox_message(
        team="alpha",
        member="worker",
        message_id=queued.message_id,
        note="done",
        notify_sender=True,
    )
    assert acked.status is MessageStatus.ACKED

    worker_outbox = store.read_outbox("alpha", "worker")
    assert len(worker_outbox) == 1
    assert worker_outbox[0].type is MessageType.STATUS_UPDATE
    assert worker_outbox[0].ack_of == queued.message_id

    relay.run_once("alpha")
    lead_inbox = store.read_inbox("alpha", "lead")
    assert any(msg.ack_of == queued.message_id for msg in lead_inbox)


def test_outbox_event_meta_contains_message_preview(tmp_path) -> None:
    store = _make_team(tmp_path)

    queued = store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="lead",
            to_member="worker",
            type=MessageType.STATUS_UPDATE,
            text="hello from lead to worker",
        ),
    )

    journal = store.read_journal("alpha")
    event = next(
        evt for evt in journal if evt.event_type == "outbox_queued" and evt.message_id == queued.message_id
    )
    assert event.meta["messageType"] == MessageType.STATUS_UPDATE.value
    assert event.meta["textPreview"] == "hello from lead to worker"
