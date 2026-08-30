"""Live proof that a recall citation opens in the source evidence viewer.

M-04/B-01: every `recall/conversations/*.md` citation answered 404 "File is not indexed in
corpus recall_default" for documents the retriever had just scored out of that very corpus,
because recall wrote chunk rows and vectors but no document and no provenance row. This
indexes a real conversation through `index_recall_conversation` (real Postgres, real Qdrant,
deterministic embeddings) and then reads it back through the same
`/api/corpora/{id}/documents/view` contract every other citation uses. Nothing is mocked.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from server.chat.recall_indexer import (
    index_recall_conversation,
    recall_conversation_path,
    recall_corpus_root,
)
from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.chat import Message
from server.models.chat_config import RecallConfig
from server.retrieval.qdrant_store import QdrantChunkStore

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_qdrant, pytest.mark.asyncio]

_QUESTION = "How often is the tidal salinity array calibrated?"
_ANSWER = "Every 14 days, and after any sensor swap.\nThe log lives in the calibration handbook."


async def test_a_recall_conversation_opens_in_the_document_viewer(client: AsyncClient) -> None:
    corpus_id = f"recall_test_{uuid.uuid4().hex[:8]}"
    conversation_id = f"conv-{uuid.uuid4().hex[:8]}"
    cfg = load_config()
    recall_cfg = RecallConfig(default_corpus_id=corpus_id, chunking_strategy="turn")
    # Deterministic embeddings: this test proves a viewer contract, not a provider.
    embedder = Embedder(cfg.embedding.model_copy(update={"embedding_backend": "deterministic"}))

    pg = PostgresClient(os.environ.get("POSTGRES_DSN") or cfg.indexing.postgres_url)
    await pg.connect()
    ts = datetime.now(UTC)
    try:
        indexed = await index_recall_conversation(
            pg,
            QdrantChunkStore(cfg),
            conversation_id=conversation_id,
            messages=[
                Message(role="user", content=_QUESTION, timestamp=ts),
                Message(role="assistant", content=_ANSWER, timestamp=ts),
            ],
            config=recall_cfg,
            embedder=embedder,
        )
        assert indexed == 2

        # The conversation is a real file under the corpus root the registry now records.
        path = recall_conversation_path(corpus_id, conversation_id)
        assert path.is_file(), f"recall conversation was not written to {path}"
        corpus_row = await pg.get_corpus(corpus_id)
        assert corpus_row is not None
        assert str(corpus_row["path"]) == str(recall_corpus_root(corpus_id))

        rel = f"conversations/{conversation_id}.md"
        assert await pg.file_is_indexed(corpus_id, rel) is True

        res = await client.get(
            f"/api/corpora/{corpus_id}/documents/view", params={"path": rel}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["file_path"] == rel
        assert body["content"]["text"].count("\n") + 1 == body["content"]["line_count"]
        assert _QUESTION in body["content"]["text"]
        assert "Every 14 days, and after any sensor swap." in body["content"]["text"]

        # Provenance is captured, not the "indexed before provenance existed" state.
        provenance = body["provenance"]
        assert provenance["extraction"] == "direct"
        assert provenance["stale"] is False
        assert provenance["byte_size"] == path.stat().st_size
        assert len(provenance["sha256"]) == 64

        # The raw endpoint serves the same document (the viewer's download path).
        raw = await client.get(f"/api/corpora/{corpus_id}/documents/raw", params={"path": rel})
        assert raw.status_code == 200, raw.text
        assert _QUESTION.encode() in raw.content

        # An unknown conversation in the same corpus is still an honest 404.
        missing = await client.get(
            f"/api/corpora/{corpus_id}/documents/view",
            params={"path": "conversations/does-not-exist.md"},
        )
        assert missing.status_code == 404

        # Re-indexing the same conversation rewrites the one document in place.
        again = await index_recall_conversation(
            pg,
            QdrantChunkStore(cfg),
            conversation_id=conversation_id,
            messages=[
                Message(role="user", content=_QUESTION, timestamp=ts),
                Message(role="assistant", content=_ANSWER, timestamp=ts),
                Message(role="user", content="And who signs it off?", timestamp=ts),
            ],
            config=recall_cfg,
            embedder=embedder,
        )
        assert again == 3
        refetched = await client.get(
            f"/api/corpora/{corpus_id}/documents/view", params={"path": rel}
        )
        assert refetched.status_code == 200, refetched.text
        assert "And who signs it off?" in refetched.json()["content"]["text"]
        assert refetched.json()["provenance"]["stale"] is False
        assert len(list(path.parent.glob("*.md"))) == 1
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
        shutil.rmtree(recall_corpus_root(corpus_id), ignore_errors=True)


async def test_a_conversation_id_that_escapes_the_corpus_root_is_refused() -> None:
    """The id names a file now; a traversing id must be refused, not written somewhere else."""
    cfg = load_config()
    corpus_id = f"recall_test_{uuid.uuid4().hex[:8]}"
    recall_cfg = RecallConfig(default_corpus_id=corpus_id, chunking_strategy="turn")
    embedder = Embedder(cfg.embedding.model_copy(update={"embedding_backend": "deterministic"}))
    pg = PostgresClient(os.environ.get("POSTGRES_DSN") or cfg.indexing.postgres_url)
    await pg.connect()
    try:
        with pytest.raises(ValueError):
            await index_recall_conversation(
                pg,
                QdrantChunkStore(cfg),
                conversation_id="../../../../tmp/ragweld-recall-escape",
                messages=[
                    Message(role="user", content="hello", timestamp=datetime.now(UTC)),
                ],
                config=recall_cfg,
                embedder=embedder,
            )
        # Refused before any side effect: no corpus row, no directory.
        assert await pg.get_corpus(corpus_id) is None
        assert not recall_corpus_root(corpus_id).exists()
    finally:
        shutil.rmtree(recall_corpus_root(corpus_id), ignore_errors=True)
