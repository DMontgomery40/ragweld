"""Contract tests for the canonical Qdrant chunk store (real Compose-owned Qdrant, no mocks).

Which generation is live is the corpus's generation manifest in Postgres, not
a Qdrant alias: readers pass the manifest's physical collection explicitly.
"""

from __future__ import annotations

import os
import uuid

import pytest

from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.generations import build_generation
from server.models.index import Chunk, ChunkProvenance
from server.retrieval.qdrant_store import (
    QdrantChunkStore,
    QdrantCollectionMissingError,
    QdrantGenerationExistsError,
    corpus_collection_prefix,
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
        metadata={"chunk_ordinal": ordinal},
        provenance=ChunkProvenance(extraction="direct"),
    )


async def test_staged_generations_serve_both_legs_and_retire_after_the_manifest_commit() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-store-{uuid.uuid4().hex[:8]}"
    try:
        # No manifest -> no generation: reads fail closed, never an empty 200.
        assert await store.status(corpus_id, physical=None) is None
        with pytest.raises(QdrantCollectionMissingError):
            await store.vector_search(corpus_id, [1.0, 0.0, 0.0, 0.0], 3, physical=None)

        first = await store.create_generation(corpus_id, embedding_dim=4)
        assert first.startswith(corpus_collection_prefix(corpus_id) + "__")
        chunks = [
            _chunk(
                "a",
                "the salinity array is calibrated every 45 days",
                embedding=[1.0, 0.0, 0.0, 0.0],
                ordinal=0,
            ),
            _chunk(
                "b",
                "sensor drift report for the tidal gauge",
                embedding=[0.0, 1.0, 0.0, 0.0],
                ordinal=1,
            ),
        ]
        assert await store.write_chunks(corpus_id, first, chunks, embedding_dim=4) == 2

        # Once the manifest names it (the Postgres commit does that in the index
        # job), the generation serves both legs.
        status = await store.status(corpus_id, physical=first)
        assert status is not None
        assert status.physical_collection == first
        assert status.points == 2
        assert status.dense_points == 2
        assert status.dense_dimensions == 4

        dense = await store.vector_search(corpus_id, [0.9, 0.1, 0.0, 0.0], 2, physical=first)
        assert [m.chunk_id for m in dense] == ["a", "b"]
        assert dense[0].source == "vector"
        assert dense[0].file_path == "docs/a.md"
        assert dense[0].metadata["corpus_id"] == corpus_id
        assert dense[0].metadata["chunk_ordinal"] == 0
        assert "extraction" not in dense[0].metadata
        assert dense[0].provenance is not None and dense[0].provenance.extraction == "direct"

        sparse = await store.sparse_search(corpus_id, "salinity calibration", 5, physical=first)
        assert sparse and sparse[0].chunk_id == "a"
        assert sparse[0].source == "sparse"
        assert sparse[0].metadata["sparse_engine"] == "qdrant_sparse_idf"
        assert sparse[0].score > 0

        embeddings = await store.get_embeddings(corpus_id, ["a", "b", "missing"], physical=first)
        assert set(embeddings) == {"a", "b"}
        assert len(embeddings["a"]) == 4

        # A second generation is built while the first stays live; after the
        # manifest commit the superseded one is retired.
        second = await store.create_generation(corpus_id, embedding_dim=4)
        await store.write_chunks(
            corpus_id,
            second,
            [
                _chunk(
                    "c", "replacement generation content", embedding=[0.0, 0.0, 1.0, 0.0], ordinal=0
                )
            ],
            embedding_dim=4,
        )
        assert (
            await store.status(corpus_id, physical=first)
        ).points == 2  # untouched until retirement
        await store.drop_generation(
            first
        )  # the index job retires exact ids from the manifest chain
        status = await store.status(corpus_id, physical=second)
        assert status is not None and status.physical_collection == second and status.points == 1
        assert [
            m.chunk_id
            for m in await store.vector_search(corpus_id, [0.0, 0.0, 1.0, 0.0], 5, physical=second)
        ] == ["c"]
        wiped = await store.status(corpus_id, physical=first)
        assert wiped is not None and wiped.physical_collection is None

        from qdrant_client import QdrantClient

        client = QdrantClient(url=store.url)
        try:
            assert not client.collection_exists(first)
            assert not any(
                a.alias_name.startswith("ragweld_chunks_") and corpus_id in a.alias_name
                for a in client.get_aliases().aliases
            )
        finally:
            client.close()
    finally:
        await store.delete_corpus(corpus_id)
    assert await store.status(corpus_id, physical=None) is None


async def test_sparse_only_generation_serves_sparse_and_reports_zero_dense_points() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-sparse-only-{uuid.uuid4().hex[:8]}"
    try:
        generation = await store.create_generation(corpus_id, embedding_dim=8)
        await store.write_chunks(
            corpus_id,
            generation,
            [
                _chunk(
                    "t",
                    "tool output: github action failed with exit code 1",
                    embedding=None,
                    ordinal=0,
                )
            ],
            embedding_dim=8,
        )
        status = await store.status(corpus_id, physical=generation)
        assert status is not None and status.points == 1 and status.dense_points == 0
        hits = await store.sparse_search(corpus_id, "github action failed", 3, physical=generation)
        assert [m.chunk_id for m in hits] == ["t"]
        assert await store.vector_search(corpus_id, [0.0] * 8, 3, physical=generation) == []
    finally:
        await store.delete_corpus(corpus_id)


@pytest.mark.requires_postgres
async def test_incremental_upsert_records_a_manifest_then_appends() -> None:
    """Recall-style writers get a generation and its manifest on first write (real Postgres corpus row)."""
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-recall-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        await pg.upsert_corpus(
            corpus_id, name="Aurora buoy notes", root_path=".", description="Operator notes"
        )
        assert await pg.get_generation(corpus_id) is None
        await store.upsert_chunks(
            corpus_id,
            [
                _chunk(
                    "m1",
                    "first conversation turn about tide tables",
                    embedding=[1.0, 0.0],
                    ordinal=0,
                )
            ],
            embedding_dim=2,
            pg=pg,
        )
        generation = await pg.get_generation(corpus_id)
        # Incremental writers build no graph: the manifest is honest about it.
        assert generation and generation.qdrant_collection and generation.graph_repo_id is None
        # The first generation is set-if-absent under the corpus lock: a competing
        # first write (another process, or the startup upgrade racing a promotion)
        # cannot overwrite an existing manifest.
        assert (
            await pg.set_generation_if_absent(
                corpus_id,
                build_generation(
                    run_id="competing", qdrant_collection="ragweld_chunks_never", graph_repo_id=None
                ),
            )
            is False
        )
        assert await pg.get_generation(corpus_id) == generation
        await store.upsert_chunks(
            corpus_id,
            [
                _chunk(
                    "m2", "second turn mentions sensor calibration", embedding=[0.0, 1.0], ordinal=1
                )
            ],
            embedding_dim=2,
            pg=pg,
        )
        assert (
            await pg.get_generation(corpus_id)
        ).qdrant_collection == generation.qdrant_collection
        status = await store.status(corpus_id, physical=generation.qdrant_collection)
        assert status is not None and status.points == 2 and status.dense_points == 2
        hits = await store.vector_search(
            corpus_id, [0.0, 1.0], 1, physical=generation.qdrant_collection
        )
        assert [m.chunk_id for m in hits] == ["m2"]
        # Incremental writes only need the corpus row to exist: the operator-given
        # name and description are never overwritten by the writer's placeholder.
        row = await pg.get_corpus(corpus_id)
        assert row is not None and row["name"] == "Aurora buoy notes", row
        assert row["description"] == "Operator notes", row
    finally:
        await store.delete_corpus(corpus_id)
        try:
            await pg.delete_corpus_with_data(corpus_id)
        finally:
            await pg.disconnect()


async def test_wiped_physical_generation_reads_as_missing() -> None:
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-wiped-{uuid.uuid4().hex[:8]}"
    try:
        generation = await store.create_generation(corpus_id, embedding_dim=2)
        await store.write_chunks(
            corpus_id,
            generation,
            [
                _chunk(
                    "w",
                    "The salinity sensor is calibrated every two weeks against a reference brine.",
                    embedding=[1.0, 0.0],
                    ordinal=0,
                )
            ],
            embedding_dim=2,
        )
        await store.drop_generation(generation)
        # A manifest that names a wiped collection reads as wiped (never as an empty result set).
        wiped = await store.status(corpus_id, physical=generation)
        assert wiped is not None and wiped.physical_collection is None and wiped.points == 0
        with pytest.raises(QdrantCollectionMissingError):
            await store.sparse_search(
                corpus_id, "How often is the salinity sensor calibrated?", 3, physical=generation
            )
        with pytest.raises(QdrantCollectionMissingError):
            await store.vector_search(corpus_id, [1.0, 0.0], 3, physical=generation)
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
            chunk = _chunk(
                "c1",
                f"content-{cid} salinity sensor calibration interval",
                embedding=None,
                ordinal=0,
            )
            chunk = chunk.model_copy(update={"file_path": f"{cid}.txt"})
            embedded = await embedder.embed_chunks([chunk])
            await pg.upsert_chunks(cid, embedded)
            await store.upsert_chunks(cid, embedded, embedding_dim=int(embedder.dim), pg=pg)
        config_store._store = None

        out = await TriBridFusion().search(
            corpus_ids=corpus_ids,
            query="How often is the salinity sensor calibrated?",
            config=FusionConfig(method="rrf", rrf_k=60),
            include_vector=True,
            include_sparse=False,
            include_graph=False,
            top_k=5,
            cache_mode="bypass",
        )
        assert len(out) == 2
        assert {c.content for c in out} == {
            f"content-{cid} salinity sensor calibration interval" for cid in corpus_ids
        }
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


@pytest.mark.requires_postgres
async def test_startup_upgrade_records_manifests_for_pre_manifest_corpora() -> None:
    """A corpus that still routes through a legacy Qdrant alias gets a manifest once; others are untouched."""
    from qdrant_client import QdrantClient
    from qdrant_client import models as qmodels

    from server.indexing.generations import ensure_generation_manifests

    cfg = load_config()
    store = QdrantChunkStore(cfg)
    legacy_id = f"legacy-alias-{uuid.uuid4().hex[:8]}"
    fresh_id = f"never-indexed-{uuid.uuid4().hex[:8]}"
    pg = PostgresClient(os.environ["POSTGRES_DSN"])
    await pg.connect()
    try:
        for cid in (legacy_id, fresh_id):
            await pg.upsert_corpus(cid, name=cid, root_path=".")
        physical = await store.create_generation(legacy_id, embedding_dim=2)
        await store.write_chunks(
            legacy_id,
            physical,
            [_chunk("l", "legacy alias content", embedding=[1.0, 0.0], ordinal=0)],
            embedding_dim=2,
        )
        client = QdrantClient(url=store.url)
        try:  # the pre-manifest world: a corpus alias pointing at its live generation
            client.update_collection_aliases(
                change_aliases_operations=[
                    qmodels.CreateAliasOperation(
                        create_alias=qmodels.CreateAlias(
                            collection_name=physical, alias_name=corpus_collection_prefix(legacy_id)
                        )
                    )
                ]
            )
        finally:
            client.close()

        assert await ensure_generation_manifests(cfg) >= 1
        legacy = await pg.get_generation(legacy_id)
        assert legacy and legacy.qdrant_collection == physical and legacy.graph_repo_id == legacy_id
        assert await pg.get_generation(fresh_id) is None, (
            "a corpus with nothing to point at stays unpromoted"
        )
        # Idempotent: a second run changes nothing.
        before = legacy  # Pydantic models compare by field
        await ensure_generation_manifests(cfg)
        assert await pg.get_generation(legacy_id) == before
        assert (await store.status(legacy_id, physical=physical)).points == 1

        # Round-3 manifests carried one previous_* slot: the upgrade rewrites them to
        # the retired list (stamped with the manifest's own promotion time), masks ids
        # equal to the live ones, and never records the same pair twice.
        shaped_id = f"legacy-shape-{uuid.uuid4().hex[:8]}"
        await pg.upsert_corpus(shaped_id, name=shaped_id, root_path=".")
        await pg.update_corpus_meta(
            shaped_id,
            {
                "generation": {
                    "run_id": "r3",
                    "qdrant_collection": "ragweld_chunks_shape_live",
                    "graph_repo_id": "shape-graph-live",
                    "promoted_at": "2026-08-25T00:00:00+00:00",
                    "previous_qdrant_collection": "ragweld_chunks_shape_old",
                    "previous_graph_repo_id": "shape-graph-live",
                }
            },
        )
        equal_id = f"legacy-equal-{uuid.uuid4().hex[:8]}"
        await pg.upsert_corpus(equal_id, name=equal_id, root_path=".")
        await pg.update_corpus_meta(
            equal_id,
            {
                "generation": {
                    "run_id": "r3",
                    "qdrant_collection": "ragweld_chunks_equal_live",
                    "graph_repo_id": None,
                    "promoted_at": "2026-08-25T00:00:00+00:00",
                    "previous_qdrant_collection": "ragweld_chunks_equal_live",
                    "previous_graph_repo_id": None,
                }
            },
        )
        try:
            assert await ensure_generation_manifests(cfg) >= 2
            shaped = await pg.get_generation(shaped_id)
            assert (
                shaped
                and shaped.run_id == "r3"
                and shaped.qdrant_collection == "ragweld_chunks_shape_live"
            )
            assert [(r.qdrant_collection, r.graph_repo_id) for r in shaped.retired] == [
                ("ragweld_chunks_shape_old", None)  # the graph id equal to the live one is masked
            ], shaped
            assert shaped.retired[0].retired_at == shaped.promoted_at
            equal = await pg.get_generation(equal_id)
            assert equal and equal.retired == [], equal  # nothing left to retire once masked
            assert await ensure_generation_manifests(cfg) == 0  # idempotent
        finally:
            for cid in (shaped_id, equal_id):
                await pg.delete_corpus_with_data(cid)
    finally:
        for cid in (legacy_id, fresh_id):
            await store.delete_corpus(cid)
            await pg.delete_corpus_with_data(cid)
        await pg.disconnect()


async def test_a_generation_is_never_recreated_over_an_existing_collection() -> None:
    """Generation names cannot collide (128-bit suffix) and a create never wipes an existing collection."""
    store = QdrantChunkStore(load_config())
    corpus_id = f"qdrant-no-recreate-{uuid.uuid4().hex[:8]}"
    try:
        first = await store.create_generation(corpus_id, embedding_dim=4)
        prefix, _, suffix = first.rpartition("__")
        assert prefix == corpus_collection_prefix(corpus_id)
        assert len(suffix) == 32 and int(suffix, 16) >= 0, suffix
        assert (
            await store.write_chunks(
                corpus_id,
                first,
                [
                    _chunk("a", "salinity array calibrated every 45 days", embedding=[1, 0, 0, 0], ordinal=0),
                    _chunk("b", "tidal gauge drift report", embedding=[0, 1, 0, 0], ordinal=1),
                ],
                embedding_dim=4,
            )
            == 2
        )
        # A planned name that already exists (a live or retained generation, or a
        # run whose create response was lost) is refused, and the data survives.
        with pytest.raises(QdrantGenerationExistsError):
            await store.create_generation(corpus_id, embedding_dim=4, physical=first)
        assert await store.count_points(first) == 2
        assert (await store.status(corpus_id, physical=first)).points == 2
    finally:
        await store.delete_corpus(corpus_id)
