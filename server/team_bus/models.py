from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MessageType(StrEnum):
    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    BLOCKER = "blocker"
    APPROVAL_REQUEST = "approval_request"
    SHUTDOWN_REQUEST = "shutdown_request"
    IDLE_NOTIFICATION = "idle_notification"
    CUSTOM = "custom"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    PENDING = "pending"
    ACKED = "acked"
    RETRY = "retry"
    REJECTED = "rejected"


class TeamRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_member: str = Field(validation_alias=AliasChoices("from_member", "from"), serialization_alias="from")
    to_member: str = Field(validation_alias=AliasChoices("to_member", "to"), serialization_alias="to")


class TeamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_routes: list[TeamRoute] = Field(
        default_factory=list,
        validation_alias=AliasChoices("allowed_routes", "allowedRoutes"),
        serialization_alias="allowedRoutes",
    )
    allowed_message_types: list[MessageType] = Field(
        default_factory=lambda: list(MessageType),
        validation_alias=AliasChoices("allowed_message_types", "allowedMessageTypes"),
        serialization_alias="allowedMessageTypes",
    )
    max_message_bytes: int = Field(
        default=32768,
        ge=256,
        validation_alias=AliasChoices("max_message_bytes", "maxMessageBytes"),
        serialization_alias="maxMessageBytes",
    )
    max_messages_per_minute: int = Field(
        default=120,
        ge=1,
        validation_alias=AliasChoices("max_messages_per_minute", "maxMessagesPerMinute"),
        serialization_alias="maxMessagesPerMinute",
    )
    max_hops: int = Field(
        default=3,
        ge=0,
        validation_alias=AliasChoices("max_hops", "maxHops"),
        serialization_alias="maxHops",
    )
    require_ack_types: list[MessageType] = Field(
        default_factory=lambda: [MessageType.TASK_ASSIGNMENT, MessageType.APPROVAL_REQUEST],
        validation_alias=AliasChoices("require_ack_types", "requireAckTypes"),
        serialization_alias="requireAckTypes",
    )


class TeamMember(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(validation_alias=AliasChoices("agent_id", "agentId"), serialization_alias="agentId")
    name: str
    role: str = "general-purpose"
    model: str | None = None
    cwd: str | None = None
    subscriptions: list[str] = Field(default_factory=list)
    safety_profile: str | None = Field(
        default=None,
        validation_alias=AliasChoices("safety_profile", "safetyProfile"),
        serialization_alias="safetyProfile",
    )
    joined_at: datetime = Field(
        default_factory=_utc_now,
        validation_alias=AliasChoices("joined_at", "joinedAt"),
        serialization_alias="joinedAt",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        out = value.strip()
        if not out:
            msg = "member name cannot be empty"
            raise ValueError(msg)
        return out


class TeamConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, validation_alias=AliasChoices("schema_version", "schemaVersion"), serialization_alias="schemaVersion")
    name: str
    description: str = ""
    created_at: datetime = Field(
        default_factory=_utc_now,
        validation_alias=AliasChoices("created_at", "createdAt"),
        serialization_alias="createdAt",
    )
    lead_agent_id: str = Field(
        validation_alias=AliasChoices("lead_agent_id", "leadAgentId"),
        serialization_alias="leadAgentId",
    )
    members: list[TeamMember]
    policy: TeamPolicy = Field(default_factory=TeamPolicy)

    @field_validator("members")
    @classmethod
    def _validate_members_unique(cls, members: list[TeamMember]) -> list[TeamMember]:
        ids: set[str] = set()
        names: set[str] = set()
        for m in members:
            if m.agent_id in ids:
                msg = f"duplicate member agent_id: {m.agent_id}"
                raise ValueError(msg)
            if m.name in names:
                msg = f"duplicate member name: {m.name}"
                raise ValueError(msg)
            ids.add(m.agent_id)
            names.add(m.name)
        return members


class TeamMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, validation_alias=AliasChoices("schema_version", "schemaVersion"), serialization_alias="schemaVersion")
    message_id: str = Field(
        default_factory=lambda: str(uuid4()),
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    team: str
    from_member: str = Field(validation_alias=AliasChoices("from_member", "from"), serialization_alias="from")
    to_member: str = Field(validation_alias=AliasChoices("to_member", "to"), serialization_alias="to")
    type: MessageType
    subject: str | None = None
    text: str
    timestamp: datetime = Field(default_factory=_utc_now)
    correlation_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("correlation_id", "correlationId"),
        serialization_alias="correlationId",
    )
    requires_ack: bool = Field(
        default=False, validation_alias=AliasChoices("requires_ack", "requiresAck"), serialization_alias="requiresAck"
    )
    ack_of: str | None = Field(default=None, validation_alias=AliasChoices("ack_of", "ackOf"), serialization_alias="ackOf")
    hop_count: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("hop_count", "hopCount"),
        serialization_alias="hopCount",
    )
    status: MessageStatus = MessageStatus.QUEUED
    delivery_attempts: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("delivery_attempts", "deliveryAttempts"),
        serialization_alias="deliveryAttempts",
    )
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def _validate_text_not_empty(cls, value: str) -> str:
        out = value.strip()
        if not out:
            msg = "message text cannot be empty"
            raise ValueError(msg)
        return out


class JournalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        validation_alias=AliasChoices("event_id", "eventId"),
        serialization_alias="eventId",
    )
    team: str
    timestamp: datetime = Field(default_factory=_utc_now)
    event_type: Literal[
        "outbox_queued",
        "message_delivered",
        "message_rejected",
        "message_retried",
        "message_acked",
        "imported",
        "validation_error",
    ] = Field(validation_alias=AliasChoices("event_type", "eventType"), serialization_alias="eventType")
    message_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("message_id", "messageId"),
        serialization_alias="messageId",
    )
    from_member: str | None = Field(
        default=None, validation_alias=AliasChoices("from_member", "from"), serialization_alias="from"
    )
    to_member: str | None = Field(default=None, validation_alias=AliasChoices("to_member", "to"), serialization_alias="to")
    status: str | None = None
    reason: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
