from __future__ import annotations

import re

from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.chat import Message
from server.models.chat_config import RecallConfig
from server.models.index import Chunk

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


async def ensure_recall_corpus(pg: PostgresClient, config: RecallConfig) -> None:
    """Ensure the Recall corpus exists in Postgres.

    Recall is stored using the existing `corpora` + `chunks` tables under
    repo_id == config.default_corpus_id.
    """
    repo_id = config.default_corpus_id
    existing = await pg.get_corpus(repo_id)
    if existing is not None:
        return

    await pg.upsert_corpus(
        repo_id=repo_id,
        name="Recall",
        root_path="data/recall",
        description="Persistent chat recall corpus (auto-managed)",
        meta={"system_kind": "recall", "pinned": True},
    )


def build_recall_chunks(*, conversation_id: str, messages: list[Message], config: RecallConfig) -> list[Chunk]:
    """Build recall chunks for a conversation.

    NOTE: `repo_id` is not part of the Chunk model; the caller supplies it when
    upserting into Postgres.
    """
    file_path = f"recall/conversations/{conversation_id}.md"
    strategy = (config.chunking_strategy or "").strip().lower()

    chunks: list[Chunk] = []
    line_idx = 1  # 1-based monotonically increasing index across produced chunks

    for turn_index, msg in enumerate(messages):
        parts: list[str]
        if strategy == "sentence":
            parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(msg.content or "") if p and p.strip()]
        else:
            # 'turn' or any other strategy => one chunk per message
            parts = [(msg.content or "").strip()] if (msg.content or "").strip() else []

        for part_index, content in enumerate(parts):
            chunk_id = f"recall:{conversation_id}:{turn_index}:{part_index}"
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    content=content,
                    file_path=file_path,
                    start_line=line_idx,
                    end_line=line_idx,
                    language=None,
                    token_count=len(content.split()),
                    metadata={
                        "kind": "recall_message",
                        "conversation_id": conversation_id,
                        "message_id": f"{turn_index}",
                        "role": msg.role,
                        "timestamp": msg.timestamp.isoformat(),
                        "turn_index": turn_index,
                    },
                )
            )
            line_idx += 1

    return chunks


async def index_recall_conversation(
    pg: PostgresClient,
    *,
    conversation_id: str,
    messages: list[Message],
    config: RecallConfig,
    embedder: Embedder,
    ts_config: str = "english",
) -> int:
    """Index a conversation into the Recall corpus (pgvector + FTS)."""
    await ensure_recall_corpus(pg, config)

    chunks = build_recall_chunks(conversation_id=conversation_id, messages=messages, config=config)
    embedded_chunks = await embedder.embed_chunks(chunks)

    await pg.upsert_embeddings(config.default_corpus_id, embedded_chunks)
    await pg.upsert_fts(config.default_corpus_id, embedded_chunks, ts_config=ts_config)

    return len(chunks)

