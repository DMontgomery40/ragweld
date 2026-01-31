"""In-memory conversation history with provider response ID tracking for OpenAI Responses API."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from server.models.chat import Message


@dataclass
class Conversation:
    """A conversation with message history and OpenAI Responses API tracking."""

    id: str
    messages: list[Message] = field(default_factory=list)
    last_provider_response_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ConversationStore:
    """Thread-safe in-memory conversation storage.

    Tracks conversation history and OpenAI Responses API response IDs
    for multi-turn context continuity.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}

    def get_or_create(self, conversation_id: str | None) -> Conversation:
        """Get existing conversation or create a new one.

        Args:
            conversation_id: Existing conversation ID, or None to create new.

        Returns:
            Conversation instance with message history.
        """
        if conversation_id and conversation_id in self._conversations:
            return self._conversations[conversation_id]

        new_id = conversation_id or str(uuid.uuid4())
        conv = Conversation(id=new_id)
        self._conversations[new_id] = conv
        return conv

    def get(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID, or None if not found."""
        return self._conversations.get(conversation_id)

    def add_message(
        self,
        conversation_id: str,
        message: Message,
        provider_response_id: str | None = None,
    ) -> None:
        """Add a message to a conversation.

        Args:
            conversation_id: The conversation to add to.
            message: The message to add.
            provider_response_id: OpenAI Responses API response ID (for assistant messages).
        """
        conv = self._conversations.get(conversation_id)
        if conv is None:
            raise KeyError(f"Conversation not found: {conversation_id}")

        conv.messages.append(message)
        if provider_response_id:
            conv.last_provider_response_id = provider_response_id
        conv.updated_at = datetime.now(UTC)

    def get_messages(self, conversation_id: str) -> list[Message]:
        """Get all messages in a conversation.

        Args:
            conversation_id: The conversation ID.

        Returns:
            List of messages, or empty list if conversation not found.
        """
        conv = self._conversations.get(conversation_id)
        return list(conv.messages) if conv else []

    def clear(self, conversation_id: str) -> bool:
        """Clear a conversation's history.

        Args:
            conversation_id: The conversation to clear.

        Returns:
            True if conversation was found and cleared, False otherwise.
        """
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False

    def list_conversations(self) -> list[str]:
        """List all conversation IDs."""
        return list(self._conversations.keys())


# Global singleton instance
_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    """Get the global conversation store singleton."""
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store
