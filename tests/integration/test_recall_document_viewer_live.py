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
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient

from server.chat.recall_indexer import (
    RecallConversationIdError,
    configured_recall_root,
    ensure_recall_corpus,
    index_recall_conversation,
    recall_conversation_path,
    recall_corpus_root_from_row,
)
from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.chat import Message
from server.models.chat_config import RecallConfig
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services.conversation_store import get_conversation_store

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_qdrant, pytest.mark.asyncio]

_QUESTION = "How often is the tidal salinity array calibrated?"
_ANSWER = "Every 14 days, and after any sensor swap.\nThe log lives in the calibration handbook."


async def test_a_recall_conversation_opens_in_the_document_viewer(client: AsyncClient) -> None:
    corpus_id = f"recall_test_{uuid.uuid4().hex[:8]}"
    conversation_id = f"conv-{uuid.uuid4().hex[:8]}"
    cfg = load_config()
    recall_root = Path(tempfile.mkdtemp(prefix="ragweld-recall-"))
    recall_cfg = RecallConfig(
        default_corpus_id=corpus_id, chunking_strategy="turn", corpus_root=str(recall_root)
    )
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
        corpus_row = await pg.get_corpus(corpus_id)
        assert corpus_row is not None
        assert str(corpus_row["path"]) == str(configured_recall_root(recall_cfg, corpus_id))
        path = recall_conversation_path(recall_corpus_root_from_row(corpus_row), conversation_id)
        assert path.is_file(), f"recall conversation was not written to {path}"

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
        shutil.rmtree(recall_root, ignore_errors=True)


async def test_an_existing_recall_row_is_never_repointed_at_another_checkout(
    client: AsyncClient,
) -> None:
    """One row, one shared Postgres, and this runs on every chat send.

    A process serving a request from another checkout must not be able to move the
    operator's recall corpus onto its own tree - the last writer would win and every recall
    citation would 404 again until the next production send flipped it back.
    """
    corpus_id = f"recall_test_{uuid.uuid4().hex[:8]}"
    operator_root = Path(tempfile.mkdtemp(prefix="ragweld-recall-operator-"))
    other_checkout = Path(tempfile.mkdtemp(prefix="ragweld-recall-other-"))
    cfg = load_config()
    pg = PostgresClient(os.environ.get("POSTGRES_DSN") or cfg.indexing.postgres_url)
    await pg.connect()
    try:
        registered = operator_root / corpus_id
        await pg.upsert_corpus(
            repo_id=corpus_id,
            name="Recall",
            root_path=str(registered),
            description="Persistent chat recall corpus (auto-managed)",
            meta={"system_kind": "recall", "pinned": True},
        )

        # A second process, configured to a different tree, ensures the same corpus.
        intruder_cfg = RecallConfig(default_corpus_id=corpus_id, corpus_root=str(other_checkout))
        root = await ensure_recall_corpus(pg, intruder_cfg)

        row = await pg.get_corpus(corpus_id)
        assert row is not None
        assert str(row["path"]) == str(registered), "the registered root was repointed"
        assert root == registered, "the writer must follow the registry, not its own config"
    finally:
        await client.delete(f"/api/corpora/{corpus_id}")
        shutil.rmtree(operator_root, ignore_errors=True)
        shutil.rmtree(other_checkout, ignore_errors=True)


async def test_an_unstorable_conversation_id_is_a_422_not_a_500(client: AsyncClient) -> None:
    """`POST /api/recall/index` answered 500 for what is a bad request."""
    store = get_conversation_store()
    bad_id = "../../../../tmp/ragweld-recall-escape"
    store.get_or_create(bad_id)
    store.add_message(bad_id, Message(role="user", content="hello", timestamp=datetime.now(UTC)))
    try:
        response = await client.post("/api/recall/index", json={"conversation_id": bad_id})
        assert response.status_code == 422, response.text
        assert "conversation id" in response.text
    finally:
        store.clear(bad_id)


async def test_a_conversation_id_that_escapes_the_corpus_root_is_refused() -> None:
    """The id names a file now; a traversing id must be refused, not written somewhere else."""
    cfg = load_config()
    corpus_id = f"recall_test_{uuid.uuid4().hex[:8]}"
    recall_root = Path(tempfile.mkdtemp(prefix="ragweld-recall-"))
    recall_cfg = RecallConfig(
        default_corpus_id=corpus_id, chunking_strategy="turn", corpus_root=str(recall_root)
    )
    embedder = Embedder(cfg.embedding.model_copy(update={"embedding_backend": "deterministic"}))
    pg = PostgresClient(os.environ.get("POSTGRES_DSN") or cfg.indexing.postgres_url)
    await pg.connect()
    try:
        with pytest.raises(RecallConversationIdError):
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
        assert not (recall_root / corpus_id).exists()
    finally:
        shutil.rmtree(recall_root, ignore_errors=True)
