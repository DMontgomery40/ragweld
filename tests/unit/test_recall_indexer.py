from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.chat.recall_indexer import (
    RecallConversationIdError,
    build_recall_document,
    configured_recall_root,
    recall_conversation_path,
    recall_corpus_root_from_row,
)
from server.models.chat import Message
from server.models.chat_config import RecallConfig


def test_build_recall_document_turn_strategy() -> None:
    cfg = RecallConfig(chunking_strategy="turn")
    conversation_id = "conv_123"
    ts0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    ts1 = datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC)

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
    ts = datetime(2026, 2, 2, 12, 0, 0, tzinfo=UTC)

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
    ts = datetime(2026, 3, 3, 9, 0, 0, tzinfo=UTC)
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
    ts = datetime(2026, 4, 4, 8, 30, 0, tzinfo=UTC)
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
    ts = datetime(2026, 4, 4, 8, 30, 0, tzinfo=UTC)
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
    ts = datetime(2026, 5, 5, 0, 0, 0, tzinfo=UTC)
    with pytest.raises(RecallConversationIdError):
        build_recall_document(
            conversation_id=conversation_id,
            messages=[Message(role="user", content="hello", timestamp=ts)],
            config=cfg,
        )


def test_the_conversation_id_refusal_is_typed_so_the_api_can_answer_4xx() -> None:
    """A bare ValueError at the router became a 500 for what is a bad request."""
    assert issubclass(RecallConversationIdError, ValueError)


def test_a_registered_corpus_root_does_not_depend_on_the_reading_process(tmp_path: Path) -> None:
    """Two processes in different worktrees must resolve one corpus to one directory.

    The registry row is the only thing they share, so it is the authority. This is the
    defect class M-04 exists to fix; deriving the root from the running module's own
    location just moved it from read time to a write on shared state.
    """
    row = {"repo_id": "recall_default", "path": str(tmp_path / "srv" / "recall" / "recall_default")}
    worktree_a = tmp_path / "worktree-a"
    worktree_b = tmp_path / "worktree-b"
    worktree_a.mkdir()
    worktree_b.mkdir()

    origin = Path.cwd()
    try:
        os.chdir(worktree_a)
        from_a = recall_corpus_root_from_row(row)
        os.chdir(worktree_b)
        from_b = recall_corpus_root_from_row(row)
    finally:
        os.chdir(origin)

    assert from_a == from_b
    assert from_a.is_absolute()
    assert from_a.name == "recall_default"


def test_the_creation_root_comes_from_config_not_from_this_module() -> None:
    cfg = RecallConfig(corpus_root="/srv/ragweld/recall")
    assert configured_recall_root(cfg, "recall_default") == Path("/srv/ragweld/recall/recall_default")


def test_the_isolation_seam_overrides_the_configured_root() -> None:
    """Same contract as RAGWELD_LINEAGE_ROOT: a disposable lane points its runs elsewhere."""
    cfg = RecallConfig(corpus_root="/srv/ragweld/recall")
    previous = os.environ.get("RAGWELD_RECALL_ROOT")
    os.environ["RAGWELD_RECALL_ROOT"] = "/tmp/lane-recall"
    try:
        assert configured_recall_root(cfg, "recall_default") == Path("/tmp/lane-recall/recall_default")
    finally:
        if previous is None:
            os.environ.pop("RAGWELD_RECALL_ROOT", None)
        else:
            os.environ["RAGWELD_RECALL_ROOT"] = previous


@pytest.mark.parametrize("corpus_id", ["a/b", "a\\b", ".", "..", "", "  ", "with space"])
def test_a_corpus_id_that_is_not_one_path_component_is_refused(corpus_id: str) -> None:
    with pytest.raises(ValueError):
        configured_recall_root(RecallConfig(), corpus_id)


def test_a_corpus_id_the_registry_accepts_is_not_rejected_here(tmp_path: Path) -> None:
    """Regression: the corpus id used the CONVERSATION regex, which is strictly narrower.

    `_recall` is a legal corpus id by `validate_corpus_id_component`, but the conversation
    rule requires an alphanumeric first character - and because `ensure_recall_corpus` runs
    on the chat hot path, that turned every send into a 500 for such a configured id.
    """
    cfg = RecallConfig(default_corpus_id="_recall", corpus_root=str(tmp_path))
    assert configured_recall_root(cfg) == tmp_path / "_recall"


@pytest.mark.parametrize("corpus_id", ["_recall", "recall.v2", "recall-2026"])
def test_recall_config_accepts_every_id_the_corpus_rule_allows(corpus_id: str) -> None:
    assert RecallConfig(default_corpus_id=corpus_id).default_corpus_id == corpus_id


@pytest.mark.parametrize("corpus_id", ["a/b", "..", "", "two words"])
def test_recall_config_refuses_an_id_it_could_never_store(corpus_id: str) -> None:
    """Refused at config load, not deep inside a request."""
    with pytest.raises(ValidationError):
        RecallConfig(default_corpus_id=corpus_id)


def test_the_conversation_path_stays_inside_the_recall_corpus_root(tmp_path: Path) -> None:
    path = recall_conversation_path(tmp_path, "conv_123")
    assert path == tmp_path / "conversations" / "conv_123.md"
    assert Path(path).is_relative_to(tmp_path)
