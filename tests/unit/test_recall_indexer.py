from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.chat.recall_indexer import (
    build_recall_document,
    recall_conversation_path,
    recall_corpus_root,
)
from server.models.chat import Message
from server.models.chat_config import RecallConfig


def test_build_recall_document_turn_strategy() -> None:
    cfg = RecallConfig(chunking_strategy="turn")
    conversation_id = "conv_123"
    ts0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts1 = datetime(2026, 1, 1, 0, 1, 0, tzinfo=timezone.utc)

    messages = [
        Message(role="user", content="Hello world. How are you?", timestamp=ts0),
        Message(role="assistant", content="I am fine!", timestamp=ts1),
    ]

    doc = build_recall_document(conversation_id=conversation_id, messages=messages, config=cfg)
    chunks = doc.chunks
    assert len(chunks) == 2

    assert chunks[0].chunk_id == "recall:conv_123:0:0"
    assert chunks[0].file_path == "conversations/conv_123.md"
    assert doc.file_path == "conversations/conv_123.md"
    assert chunks[0].language is None
    assert chunks[0].token_count == len(chunks[0].content.split())
    assert chunks[0].metadata["kind"] == "recall_message"
    assert chunks[0].metadata["conversation_id"] == conversation_id
    assert chunks[0].metadata["message_id"] == "0"
    assert chunks[0].metadata["role"] == "user"
    assert chunks[0].metadata["timestamp"] == ts0.isoformat()
    assert chunks[0].metadata["turn_index"] == 0

    assert chunks[1].chunk_id == "recall:conv_123:1:0"
    assert chunks[1].metadata["message_id"] == "1"
    assert chunks[1].metadata["role"] == "assistant"
    assert chunks[1].metadata["timestamp"] == ts1.isoformat()
    assert chunks[1].metadata["turn_index"] == 1


def test_build_recall_document_sentence_strategy() -> None:
    cfg = RecallConfig(chunking_strategy="sentence")
    conversation_id = "conv_abc"
    ts = datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc)

    messages = [
        Message(role="user", content="Hello world. How are you?", timestamp=ts),
        Message(role="assistant", content="I am fine!", timestamp=ts),
    ]

    chunks = build_recall_document(
        conversation_id=conversation_id, messages=messages, config=cfg
    ).chunks
    assert len(chunks) == 3

    assert [c.chunk_id for c in chunks] == [
        "recall:conv_abc:0:0",
        "recall:conv_abc:0:1",
        "recall:conv_abc:1:0",
    ]

    assert chunks[0].content == "Hello world."
    assert chunks[1].content == "How are you?"
    assert chunks[2].content == "I am fine!"

    assert chunks[0].token_count == 2
    assert chunks[1].token_count == 3
    assert chunks[2].token_count == 3

    assert chunks[0].metadata["message_id"] == "0"
    assert chunks[1].metadata["message_id"] == "0"
    assert chunks[2].metadata["message_id"] == "1"


@pytest.mark.parametrize("strategy", ["turn", "sentence"])
@pytest.mark.parametrize(
    "content",
    [
        "One line only.",
        "First paragraph line one.\nStill the first message.\n\nA third line after a blank one.",
        "  leading and trailing whitespace  ",
    ],
)
def test_every_chunk_line_range_addresses_its_own_text_in_the_document(
    strategy: str, content: str
) -> None:
    """A citation is a promise: `file:start-end` must contain the chunk the retriever scored.

    The recall document and the recall chunks are produced together for exactly this reason;
    before this, `start_line` was a counter with no document behind it at all.
    """
    cfg = RecallConfig(chunking_strategy=strategy)
    ts = datetime(2026, 3, 3, 9, 0, 0, tzinfo=timezone.utc)
    messages = [
        Message(role="user", content=content, timestamp=ts),
        Message(role="assistant", content="Understood.\nHere is the answer.", timestamp=ts),
    ]

    doc = build_recall_document(conversation_id="conv-lines", messages=messages, config=cfg)
    lines = doc.markdown.split("\n")
    assert doc.chunks, "a conversation with content must produce chunks"

    for chunk in doc.chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines), (
            f"{chunk.chunk_id} line range {chunk.start_line}-{chunk.end_line} "
            f"is outside the {len(lines)}-line document"
        )
        cited = "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
        assert chunk.content in cited, (
            f"{chunk.chunk_id} content is not at {chunk.start_line}-{chunk.end_line}: {cited!r}"
        )


def test_the_document_records_every_message_role_and_timestamp() -> None:
    cfg = RecallConfig(chunking_strategy="turn")
    ts = datetime(2026, 4, 4, 8, 30, 0, tzinfo=timezone.utc)
    messages = [
        Message(role="user", content="What is the calibration interval?", timestamp=ts),
        Message(role="assistant", content="Every 14 days.", timestamp=ts),
    ]

    doc = build_recall_document(conversation_id="conv-md", messages=messages, config=cfg)
    assert "conv-md" in doc.markdown
    assert "user" in doc.markdown and "assistant" in doc.markdown
    assert ts.isoformat() in doc.markdown
    assert "What is the calibration interval?" in doc.markdown
    assert "Every 14 days." in doc.markdown


def test_a_conversation_with_no_content_produces_no_document() -> None:
    cfg = RecallConfig(chunking_strategy="turn")
    ts = datetime(2026, 4, 4, 8, 30, 0, tzinfo=timezone.utc)
    doc = build_recall_document(
        conversation_id="conv-empty",
        messages=[Message(role="user", content="   ", timestamp=ts)],
        config=cfg,
    )
    assert doc.chunks == []


@pytest.mark.parametrize(
    "conversation_id",
    ["../../etc/passwd", "a/b", "a\\b", "..", "", "  ", "conv\x00id", "x" * 200],
)
def test_a_conversation_id_that_could_escape_the_corpus_is_refused(conversation_id: str) -> None:
    """Recall conversation ids come straight from the client and now name a file on disk."""
    cfg = RecallConfig(chunking_strategy="turn")
    ts = datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        build_recall_document(
            conversation_id=conversation_id,
            messages=[Message(role="user", content="hello", timestamp=ts)],
            config=cfg,
        )


def test_the_recall_corpus_root_is_absolute_and_per_corpus() -> None:
    """The registry stores an absolute root, so every process resolves the same directory."""
    root_a = recall_corpus_root("recall_default")
    root_b = recall_corpus_root("recall_other")
    assert root_a.is_absolute()
    assert root_a != root_b
    assert root_a.name == "recall_default"


def test_the_conversation_path_stays_inside_the_recall_corpus_root() -> None:
    root = recall_corpus_root("recall_default")
    path = recall_conversation_path("recall_default", "conv_123")
    assert path == root / "conversations" / "conv_123.md"
    assert Path(path).is_relative_to(root)
