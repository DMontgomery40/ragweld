"""Contract tests for the canonical Qdrant chunk store (real Compose-owned Qdrant, no mocks)."""

from __future__ import annotations

import uuid

import pytest

from server.config import load_config
from server.models.index import Chunk
from server.retrieval.qdrant_store import (
    QdrantChunkStore,
    QdrantCollectionMissingError,
    corpus_alias,
)

pytestmark = [pytest.mark.requires_qdrant, pytest.mark.asyncio]


def _chunk(chunk_id: str, content: str, *, embedding: list[float] | None, ordinal: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        file_path=f"docs/{chunk_id}.md",
        start_line=1,
        end_line=2,
        language="markdown",
        token_count=len(content.split()),
        embedding=embedding,
        metadata={"chunk_ordinal": ordinal, "extraction": "direct"},
    )


async def test_staged_generation_promotes_atomically_and_serves_both_legs() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-store-{uuid.uuid4().hex[:8]}"
    try:
        assert await store.status(corpus_id) is None
        with pytest.raises(QdrantCollectionMissingError):
            await store.vector_search(corpus_id, [1.0, 0.0, 0.0, 0.0], 3)

        first = await store.create_generation(corpus_id, embedding_dim=4)
        assert first.startswith(corpus_alias(corpus_id) + "__")
        chunks = [
            _chunk("a", "the salinity array is calibrated every 45 days", embedding=[1.0, 0.0, 0.0, 0.0], ordinal=0),
            _chunk("b", "sensor drift report for the tidal gauge", embedding=[0.0, 1.0, 0.0, 0.0], ordinal=1),
        ]
        assert await store.write_chunks(corpus_id, first, chunks, embedding_dim=4) == 2
        # Not visible until promoted.
        assert await store.status(corpus_id) is None

        await store.promote_generation(corpus_id, first)
        status = await store.status(corpus_id)
        assert status is not None
        assert status.physical_collection == first
        assert status.points == 2
        assert status.dense_points == 2
        assert status.dense_dimensions == 4

        dense = await store.vector_search(corpus_id, [0.9, 0.1, 0.0, 0.0], 2)
        assert [m.chunk_id for m in dense] == ["a", "b"]
        assert dense[0].source == "vector"
        assert dense[0].file_path == "docs/a.md"
        assert dense[0].metadata["corpus_id"] == corpus_id
        assert dense[0].metadata["chunk_ordinal"] == 0
        assert dense[0].metadata["extraction"] == "direct"

        sparse = await store.sparse_search(corpus_id, "salinity calibration", 5)
        assert sparse and sparse[0].chunk_id == "a"
        assert sparse[0].source == "sparse"
        assert sparse[0].metadata["sparse_engine"] == "qdrant_sparse_idf"
        assert sparse[0].score > 0

        embeddings = await store.get_embeddings(corpus_id, ["a", "b", "missing"])
        assert set(embeddings) == {"a", "b"}
        assert len(embeddings["a"]) == 4

        # A second generation replaces the first atomically and drops the superseded collection.
        second = await store.create_generation(corpus_id, embedding_dim=4)
        await store.write_chunks(
            corpus_id,
            second,
            [_chunk("c", "replacement generation content", embedding=[0.0, 0.0, 1.0, 0.0], ordinal=0)],
            embedding_dim=4,
        )
        await store.promote_generation(corpus_id, second)
        status = await store.status(corpus_id)
        assert status is not None and status.physical_collection == second and status.points == 1
        assert [m.chunk_id for m in await store.vector_search(corpus_id, [0.0, 0.0, 1.0, 0.0], 5)] == ["c"]

        from qdrant_client import QdrantClient

        client = QdrantClient(url=store.url)
        try:
            assert not client.collection_exists(first)
        finally:
            client.close()
    finally:
        await store.delete_corpus(corpus_id)
    assert await store.status(corpus_id) is None


async def test_sparse_only_generation_serves_sparse_and_reports_zero_dense_points() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-sparse-only-{uuid.uuid4().hex[:8]}"
    try:
        generation = await store.create_generation(corpus_id, embedding_dim=8)
        await store.write_chunks(
            corpus_id,
            generation,
            [_chunk("t", "tool output: github action failed with exit code 1", embedding=None, ordinal=0)],
            embedding_dim=8,
        )
        await store.promote_generation(corpus_id, generation)
        status = await store.status(corpus_id)
        assert status is not None and status.points == 1 and status.dense_points == 0
        hits = await store.sparse_search(corpus_id, "github action failed", 3)
        assert [m.chunk_id for m in hits] == ["t"]
        assert await store.vector_search(corpus_id, [0.0] * 8, 3) == []
    finally:
        await store.delete_corpus(corpus_id)


async def test_incremental_upsert_creates_live_generation_then_appends() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-recall-{uuid.uuid4().hex[:8]}"
    try:
        await store.upsert_chunks(
            corpus_id,
            [_chunk("m1", "first conversation turn about tide tables", embedding=[1.0, 0.0], ordinal=0)],
            embedding_dim=2,
        )
        await store.upsert_chunks(
            corpus_id,
            [_chunk("m2", "second turn mentions sensor calibration", embedding=[0.0, 1.0], ordinal=1)],
            embedding_dim=2,
        )
        status = await store.status(corpus_id)
        assert status is not None and status.points == 2 and status.dense_points == 2
        assert [m.chunk_id for m in await store.vector_search(corpus_id, [0.0, 1.0], 1)] == ["m2"]
    finally:
        await store.delete_corpus(corpus_id)


async def test_wiped_physical_generation_reads_as_missing() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-wiped-{uuid.uuid4().hex[:8]}"
    try:
        generation = await store.create_generation(corpus_id, embedding_dim=2)
        await store.write_chunks(corpus_id, generation, [_chunk("w", "wiped soon", embedding=[1.0, 0.0], ordinal=0)], embedding_dim=2)
        await store.promote_generation(corpus_id, generation)
        await store.drop_generation(generation)
        # Qdrant removes the alias together with its physical collection: a wiped
        # generation reads as "no generation" (never as an empty result set).
        assert await store.status(corpus_id) is None
        with pytest.raises(QdrantCollectionMissingError):
            await store.sparse_search(corpus_id, "wiped", 3)
        with pytest.raises(QdrantCollectionMissingError):
            await store.vector_search(corpus_id, [1.0, 0.0], 3)
    finally:
        await store.delete_corpus(corpus_id)


@pytest.mark.requires_postgres
async def test_fusion_keeps_same_chunk_id_distinct_across_corpora() -> None:
    """Same chunk_id in different corpora must not collide in fusion (real Postgres + Qdrant)."""
    import os

    from server.db.postgres import PostgresClient
    from server.indexing.embedder import Embedder
    from server.models.tribrid_config_model import FusionConfig
    from server.retrieval.contracts import sparse_contract_from_config
    from server.retrieval.fusion import TriBridFusion
    from server.services import config_store

    suffix = uuid.uuid4().hex[:8]
    corpus_ids = [f"fusion-a-{suffix}", f"fusion-b-{suffix}"]
    cfg = load_config()
    cfg.embedding.embedding_backend = "deterministic"
    cfg.vector_search.enabled = True
    cfg.sparse_search.enabled = False
    cfg.graph_search.enabled = False
    cfg.chat.litellm.enabled = False
    cfg.semantic_cache.enabled = 0
    cfg.retrieval.final_k = 10
    store = QdrantChunkStore(cfg)
    embedder = Embedder(cfg.embedding, cfg.tokenization)
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    try:
        await pg.connect()
        for cid in corpus_ids:
            await pg.upsert_corpus(cid, name=cid, root_path=".")
            await pg.upsert_corpus_config_json(cid, cfg.model_dump(mode="serialization"))
            await pg.update_corpus_embedding_meta(
                cid,
                backend="deterministic",
                provider=str(cfg.embedding.embedding_type or ""),
                model=str(cfg.embedding.effective_model or ""),
                dimensions=int(embedder.dim),
                sparse_contract=sparse_contract_from_config(cfg),
            )
            chunk = _chunk("c1", f"content-{cid} foo", embedding=None, ordinal=0)
            chunk = chunk.model_copy(update={"file_path": f"{cid}.txt"})
            embedded = await embedder.embed_chunks([chunk])
            await pg.upsert_chunks(cid, embedded)
            await store.upsert_chunks(cid, embedded, embedding_dim=int(embedder.dim))
        config_store._store = None

        out = await TriBridFusion().search(
            corpus_ids=corpus_ids,
            query="foo",
            config=FusionConfig(method="rrf", rrf_k=60),
            include_vector=True,
            include_sparse=False,
            include_graph=False,
            top_k=5,
            cache_mode="bypass",
        )
        assert len(out) == 2
        assert {c.content for c in out} == {f"content-{cid} foo" for cid in corpus_ids}
        assert {str((c.metadata or {}).get("corpus_id")) for c in out} == set(corpus_ids)
        assert all(c.source == "vector" for c in out)
    finally:
        config_store._store = None
        for cid in corpus_ids:
            try:
                await store.delete_corpus(cid)
            except Exception:
                pass
            try:
                await pg.delete_corpus_with_data(cid)
            except Exception:
                pass
        await pg.disconnect()
