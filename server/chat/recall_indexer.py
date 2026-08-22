from __future__ import annotations

import re

from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.chat import Message
from server.models.chat_config import RecallConfig
from server.models.index import Chunk
from server.retrieval.contracts import contract_hash
from server.retrieval.errors import EmbeddingContractMismatchError, SparseContractMismatchError
from server.retrieval.qdrant_store import QdrantChunkStore

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


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


async def ensure_recall_corpus(pg: PostgresClient, config: RecallConfig) -> None:
    """Ensure the Recall corpus exists in Postgres.

    Recall is stored using the existing `corpora` + `chunks` tables under
    repo_id == config.default_corpus_id; its vectors live in Qdrant like any
    other corpus.
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
    qdrant: QdrantChunkStore,
    *,
    conversation_id: str,
    messages: list[Message],
    config: RecallConfig,
    embedder: Embedder,
) -> int:
    """Index a conversation into the Recall corpus (chunk rows in Postgres, dense + sparse vectors in Qdrant)."""
    await ensure_recall_corpus(pg, config)
    await _ensure_recall_contracts(
        pg,
        repo_id=config.default_corpus_id,
        embedder=embedder,
        qdrant=qdrant,
    )

    chunks = build_recall_chunks(conversation_id=conversation_id, messages=messages, config=config)
    if not chunks:
        return 0
    embedded_chunks = await embedder.embed_chunks(chunks)

    await pg.upsert_chunks(config.default_corpus_id, embedded_chunks)
    await qdrant.upsert_chunks(config.default_corpus_id, embedded_chunks, embedding_dim=int(embedder.dim))

    return len(chunks)
