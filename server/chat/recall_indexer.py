"""Recall: chat conversations indexed as a corpus of real markdown documents.

A recall conversation is a document like any other corpus document. It is written to disk
under the recall corpus root, its chunks carry line ranges that address that document, and a
``documents`` provenance row is recorded for it -- so a recall citation opens in the source
evidence viewer through exactly the contract every other citation uses. Before this, recall
wrote chunk rows and vectors only: `GET /api/corpora/recall_default/documents/view` had no
file to serve and answered 404 for every recall citation the retriever produced (M-04/B-01).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.indexing.text_extractors import document_kind_for_path, extraction_method_for_path
from server.lineage.registry import resolve_project_path
from server.models.chat import Message
from server.models.chat_config import RecallConfig
from server.models.index import Chunk, IndexedDocumentRecord
from server.models.tribrid_config_model import validate_corpus_id_component
from server.retrieval.contracts import contract_hash
from server.retrieval.errors import EmbeddingContractMismatchError, SparseContractMismatchError
from server.retrieval.qdrant_store import QdrantChunkStore

logger = logging.getLogger(__name__)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Conversation ids reach this module straight from the client (`ChatRequest.conversation_id`
# is used verbatim by ConversationStore.get_or_create) and now name a file on disk, so the
# id is constrained here rather than sanitised: a request that cannot be stored honestly is
# refused, never quietly rewritten to a different conversation's file.
_CONVERSATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Conversations live under the corpus root that the registry records for the recall corpus.
_CONVERSATION_DIR = "conversations"


class RecallConversationIdError(ValueError):
    """A conversation id that cannot safely name a file inside the recall corpus root."""


def configured_recall_root(config: RecallConfig, corpus_id: str | None = None) -> Path:
    """The root a recall corpus is CREATED under, from configuration only.

    Read from `RecallConfig.corpus_root` (a typed tunable), never from this module's own
    location: a process's checkout must not be able to decide where the operator's recall
    documents live. `RAGWELD_RECALL_ROOT` is the isolation seam, the same contract as
    `RAGWELD_LINEAGE_ROOT` and `RAGWELD_SYNTHETIC_RUNS_ROOT`, so a disposable lane can point
    its own runs somewhere harmless.

    Once a corpus exists this value is NOT consulted: `recall_corpus_root_from_row` reads the
    registry, which is the one thing every process shares.
    """
    raw = str(os.environ.get("RAGWELD_RECALL_ROOT") or "").strip() or str(config.corpus_root)
    base = resolve_project_path(raw)
    cid = str(corpus_id if corpus_id is not None else config.default_corpus_id)
    return base / validate_corpus_id_component(cid)


def recall_corpus_root_from_row(corpus_row: Mapping[str, Any]) -> Path:
    """The root of an EXISTING recall corpus, as the shared registry records it.

    Reader and writer must agree, so this resolves a registry `path` exactly the way the
    document viewer does (`server/api/documents.py`).
    """
    return resolve_project_path(str(corpus_row.get("path") or ""))


def recall_conversation_path(root: Path, conversation_id: str) -> Path:
    """Absolute path of one conversation's markdown inside a resolved recall corpus root."""
    return Path(root) / _CONVERSATION_DIR / f"{validate_conversation_id(conversation_id)}.md"


def validate_conversation_id(conversation_id: str) -> str:
    """Return the id if it can safely name a file inside the corpus root; raise otherwise.

    Raises `RecallConversationIdError` so callers can answer a typed 4xx instead of turning
    a bad request into a 500.
    """
    text = str(conversation_id or "")
    if not _CONVERSATION_ID_RE.match(text):
        raise RecallConversationIdError(
            "Unsupported recall conversation id: it must be 1-128 characters of letters, "
            "digits, '.', '_' or '-' and start with a letter or digit."
        )
    return text


@dataclass(frozen=True)
class RecallDocument:
    """One conversation as a document plus the chunks that address it.

    ``chunks`` carry line ranges into ``markdown``: they are built together precisely so a
    citation's ``file:start-end`` resolves to the text the retriever scored.
    """

    file_path: str
    markdown: str
    chunks: list[Chunk]


async def _ensure_recall_contracts(
    pg: PostgresClient,
    *,
    repo_id: str,
    embedder: Embedder,
    qdrant: QdrantChunkStore,
) -> None:
    """Record the dense + sparse contracts on first write; refuse to mix incompatible vectors.

    The file indexer records the corpus contracts at index time and the
    retrieval path enforces them. Recall writes go around the file indexer, so
    they must uphold the same contracts instead of silently mixing vector spaces.
    """
    corpus = await pg.get_corpus(repo_id)
    if corpus is None:
        return

    current_backend = str(getattr(embedder.config, "embedding_backend", "") or "").strip().lower() or "deterministic"
    current_provider = str(getattr(embedder.config, "embedding_type", "") or "").strip().lower()
    current_model = str(getattr(embedder.config, "effective_model", "") or "").strip()
    current_dim = int(getattr(embedder, "dim", 0) or 0)

    stored_dim = int(corpus.get("embedding_dimensions") or 0)
    if stored_dim == 0:
        await pg.update_corpus_embedding_meta(
            repo_id,
            backend=current_backend,
            provider=current_provider,
            model=current_model,
            dimensions=current_dim,
            sparse_contract=qdrant.sparse_contract,
        )
        return

    stored_backend = str(corpus.get("embedding_backend") or "").strip().lower()
    stored_provider = str(corpus.get("embedding_provider") or "").strip().lower()
    stored_model = str(corpus.get("embedding_model") or "").strip()
    both_deterministic = stored_backend == "deterministic" and current_backend == "deterministic"

    mismatch = (
        stored_dim != current_dim
        or (bool(stored_backend) and stored_backend != current_backend)
        or (not both_deterministic and bool(stored_provider) and stored_provider != current_provider)
        or (not both_deterministic and bool(stored_model) and stored_model != current_model)
    )
    if mismatch:
        raise EmbeddingContractMismatchError(
            corpus_id=repo_id,
            expected_contract={
                "backend": stored_backend,
                "provider": stored_provider,
                "model": stored_model,
                "dimensions": stored_dim,
            },
            current_contract={
                "backend": current_backend,
                "provider": current_provider,
                "model": current_model,
                "dimensions": current_dim,
            },
        )

    stored_sparse = corpus.get("sparse_contract")
    stored_sparse = dict(stored_sparse) if isinstance(stored_sparse, dict) else {}
    if contract_hash(stored_sparse) != contract_hash(qdrant.sparse_contract):
        raise SparseContractMismatchError(
            corpus_id=repo_id,
            expected_contract=stored_sparse,
            current_contract=dict(qdrant.sparse_contract),
        )


async def ensure_recall_corpus(pg: PostgresClient, config: RecallConfig) -> Path:
    """Ensure the Recall corpus exists in Postgres; return the root it is registered under.

    Recall is stored using the existing `corpora` + `chunks` tables under
    repo_id == config.default_corpus_id; its vectors live in Qdrant like any
    other corpus.

    An EXISTING row's `root_path` is never rewritten. It is one row in one shared Postgres,
    and this runs on the chat hot path, so any process serving a request from another
    checkout would otherwise repoint the operator's recall corpus at its own tree - the
    same class of defect (a path that means something different per process) that M-04
    exists to fix, moved to a write on shared state where the last writer wins.
    """
    repo_id = config.default_corpus_id
    existing = await pg.get_corpus(repo_id)
    if existing is not None:
        root = recall_corpus_root_from_row(existing)
    else:
        root = configured_recall_root(config, repo_id)
        await pg.upsert_corpus(
            repo_id=repo_id,
            name="Recall",
            root_path=str(root),
            description="Persistent chat recall corpus (auto-managed)",
            meta={"system_kind": "recall", "pinned": True},
        )
    await asyncio.to_thread(lambda: (root / _CONVERSATION_DIR).mkdir(parents=True, exist_ok=True))
    return root


def build_recall_document(
    *, conversation_id: str, messages: list[Message], config: RecallConfig
) -> RecallDocument:
    """Render a conversation to markdown and chunk it against that exact markdown.

    NOTE: `repo_id` is not part of the Chunk model; the caller supplies it when
    upserting into Postgres.
    """
    conversation_id = validate_conversation_id(conversation_id)
    file_path = f"{_CONVERSATION_DIR}/{conversation_id}.md"
    strategy = (config.chunking_strategy or "").strip().lower()

    lines: list[str] = [f"# Conversation {conversation_id}", ""]
    chunks: list[Chunk] = []

    for turn_index, msg in enumerate(messages):
        parts: list[str]
        if strategy == "sentence":
            parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(msg.content or "") if p and p.strip()]
        else:
            # 'turn' or any other strategy => one chunk per message
            parts = [(msg.content or "").strip()] if (msg.content or "").strip() else []
        if not parts:
            continue

        lines.append(f"## {msg.role} - {msg.timestamp.isoformat()}")
        lines.append("")
        for part_index, content in enumerate(parts):
            part_lines = content.split("\n")
            start_line = len(lines) + 1
            lines.extend(part_lines)
            end_line = len(lines)
            lines.append("")
            chunks.append(
                Chunk(
                    chunk_id=f"recall:{conversation_id}:{turn_index}:{part_index}",
                    content=content,
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
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

    return RecallDocument(file_path=file_path, markdown="\n".join(lines), chunks=chunks)


def _write_recall_document(path: Path, markdown: str) -> tuple[str, int]:
    """Write the conversation markdown atomically; return (sha256, byte_size).

    Atomic because a reader can arrive at any moment: the viewer serves whatever is on disk,
    and a half-written conversation is a corrupt citation, not a slow one.
    """
    payload = markdown.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest(), len(payload)


async def index_recall_conversation(
    pg: PostgresClient,
    qdrant: QdrantChunkStore,
    *,
    conversation_id: str,
    messages: list[Message],
    config: RecallConfig,
    embedder: Embedder,
) -> int:
    """Index a conversation into the Recall corpus (chunk rows in Postgres, dense + sparse vectors in Qdrant)."""
    # Before any side effect: a conversation that cannot be stored under a safe name must
    # not leave a corpus row, a directory or a contract behind.
    validate_conversation_id(conversation_id)
    root = await ensure_recall_corpus(pg, config)
    await _ensure_recall_contracts(
        pg,
        repo_id=config.default_corpus_id,
        embedder=embedder,
        qdrant=qdrant,
    )

    doc = build_recall_document(conversation_id=conversation_id, messages=messages, config=config)
    if not doc.chunks:
        return 0

    repo_id = config.default_corpus_id
    # The root comes from the registry row, which is what the viewer reads: writer and
    # reader cannot disagree about where a conversation lives.
    path = recall_conversation_path(root, conversation_id)
    # The document lands before its rows: a chunk row must never cite a file that is not there.
    sha256, byte_size = await asyncio.to_thread(_write_recall_document, path, doc.markdown)

    embedded_chunks = await embedder.embed_chunks(doc.chunks)

    # Rows and vectors are one unit of work under the corpus lock (see
    # PostgresClient.upsert_chunks_with_vectors): no chunk ever exists in one store only.
    await qdrant.upsert_chunks(repo_id, embedded_chunks, embedding_dim=int(embedder.dim), pg=pg)

    # Provenance last: it claims "this file is indexed", which is only true once it is.
    await pg.upsert_document(
        repo_id,
        IndexedDocumentRecord(
            file_path=doc.file_path,
            kind=document_kind_for_path(path),
            extraction=extraction_method_for_path(path),
            sha256=sha256,
            byte_size=byte_size,
        ),
    )

    return len(doc.chunks)
