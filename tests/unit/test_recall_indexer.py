from __future__ import annotations

from datetime import datetime, timezone

from server.chat.recall_indexer import build_recall_chunks
from server.models.chat import Message
from server.models.chat_config import RecallConfig


def test_build_recall_chunks_turn_strategy() -> None:
    cfg = RecallConfig(chunking_strategy="turn")
    conversation_id = "conv_123"
    ts0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts1 = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)

    messages = [
        Message(role="user", content="Hello world. How are you?", timestamp=ts0),
        Message(role="assistant", content="I am fine!", timestamp=ts1),
    ]

    chunks = build_recall_chunks(conversation_id=conversation_id, messages=messages, config=cfg)
    assert len(chunks) == 2

    assert chunks[0].chunk_id == "recall:conv_123:0:0"
    assert chunks[0].file_path == "recall/conversations/conv_123.md"
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 1
    assert chunks[0].language is None
    assert chunks[0].token_count == len(chunks[0].content.split())
    assert chunks[0].metadata["kind"] == "recall_message"
    assert chunks[0].metadata["conversation_id"] == conversation_id
    assert chunks[0].metadata["message_id"] == "0"
    assert chunks[0].metadata["role"] == "user"
    assert chunks[0].metadata["timestamp"] == ts0.isoformat()
    assert chunks[0].metadata["turn_index"] == 0

    assert chunks[1].chunk_id == "recall:conv_123:1:0"
    assert chunks[1].start_line == 2
    assert chunks[1].end_line == 2
    assert chunks[1].metadata["message_id"] == "1"
    assert chunks[1].metadata["role"] == "assistant"
    assert chunks[1].metadata["timestamp"] == ts1.isoformat()
    assert chunks[1].metadata["turn_index"] == 1


def test_build_recall_chunks_sentence_strategy() -> None:
    cfg = RecallConfig(chunking_strategy="sentence")
    conversation_id = "conv_abc"
    ts = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)

    messages = [
        Message(role="user", content="Hello world. How are you?", timestamp=ts),
        Message(role="assistant", content="I am fine!", timestamp=ts),
    ]

    chunks = build_recall_chunks(conversation_id=conversation_id, messages=messages, config=cfg)
    assert len(chunks) == 3

    assert [c.chunk_id for c in chunks] == [
        "recall:conv_abc:0:0",
        "recall:conv_abc:0:1",
        "recall:conv_abc:1:0",
    ]
    assert [c.start_line for c in chunks] == [1, 2, 3]
    assert [c.end_line for c in chunks] == [1, 2, 3]

    assert chunks[0].content == "Hello world."
    assert chunks[1].content == "How are you?"
    assert chunks[2].content == "I am fine!"

    assert chunks[0].token_count == 2
    assert chunks[1].token_count == 3
    assert chunks[2].token_count == 3

    assert chunks[0].metadata["message_id"] == "0"
    assert chunks[1].metadata["message_id"] == "0"
    assert chunks[2].metadata["message_id"] == "1"

