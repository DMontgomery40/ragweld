"""Live Postgres proof for chunk provenance and the ``documents`` provenance record.

Covers every chunk reader, the documents upsert/get, staging → promotion, and the three deletion
paths. Real Postgres only (``requires_postgres``); nothing is mocked.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from server.db.postgres import PostgresClient
from server.indexing.generations import staging_repo_id
from server.models.index import Chunk, ChunkProvenance, IndexedDocumentRecord, PageRegion
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

_PROV = ChunkProvenance(
    extraction="docling",
    page_start=1,
    page_end=2,
    regions=[
        PageRegion(page=1, left=0.1, top=0.8, right=0.9, bottom=0.85),
        PageRegion(page=2, left=0.1, top=0.1, right=0.9, bottom=0.15),
    ],
)
_DOCLING_ONLY = ChunkProvenance(extraction="docling")


def _chunk(file_path: str, ordinal: int, provenance: ChunkProvenance | None) -> Chunk:
    start = ordinal * 100
    return Chunk(
        chunk_id=f"{file_path}:1-2:{start}",
        content=f"body of {file_path} #{ordinal}",
        file_path=file_path,
        start_line=1,
        end_line=2,
        metadata={"chunk_ordinal": ordinal, "char_start": start, "char_end": start + 50},
        provenance=provenance,
    )


async def test_provenance_and_documents_round_trip_promote_and_delete(client: AsyncClient) -> None:
    corpus_id = f"pytest_docs_persist_{uuid.uuid4().hex[:8]}"
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    staging = staging_repo_id(corpus_id, run_id)
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await pg.connect()
    try:
        created = await client.post(
            "/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."}
        )
        assert created.status_code in (200, 201), created.text
        claim = await pg.acquire_index_fence(
            corpus_id, run_id, started_at=datetime.now(UTC), owner="this-test:1", lease_seconds=60
        )
        assert claim.acquired

        chunks = [
            _chunk("a.pdf", 0, _PROV),
            _chunk("a.pdf", 1, _DOCLING_ONLY),
            _chunk("b.md", 0, None),  # a row written before provenance capture
        ]
        assert await pg.upsert_chunks(staging, chunks) == 3
        await pg.upsert_document(
            staging,
            IndexedDocumentRecord(
                file_path="a.pdf", kind="pdf", extraction="docling", sha256="a" * 64, byte_size=10
            ),
        )
        await pg.upsert_document(
            staging,
            IndexedDocumentRecord(
                file_path="c.html",
                kind="rich",
                extraction="docling",
                sha256="b" * 64,
                byte_size=20,
                markdown="# Handbook\n\n| a | b |",
            ),
        )

        # Every chunk reader maps the provenance column back to the typed field (or None).
        expected = {c.chunk_id: c.provenance for c in chunks}
        one = await pg.get_chunk(staging, chunks[0].chunk_id)
        assert one is not None and one.provenance == _PROV
        many = await pg.get_chunks(staging, [c.chunk_id for c in chunks])
        assert [c.provenance for c in many] == [_PROV, _DOCLING_ONLY, None]
        by_ord = await pg.get_chunks_by_file_ordinals(staging, "a.pdf", [0, 1])
        assert [c.provenance for c in by_ord] == [_PROV, _DOCLING_ONLY]
        listed = await pg.list_chunks_for_repo(staging)
        assert {c.chunk_id: c.provenance for c in listed} == expected
        assert all("extraction" not in c.metadata for c in listed)

        # Documents: written under the staging id only, with the database timestamp.
        rich = await pg.get_document(staging, "c.html")
        assert rich is not None and rich.markdown == "# Handbook\n\n| a | b |"
        assert rich.indexed_at is not None and rich.kind == "rich"
        assert await pg.get_document(corpus_id, "c.html") is None
        assert await pg.count_documents(staging) == 2
        assert await pg.count_documents(corpus_id) == 0

        # Re-upsert replaces (no duplicate primary key), new sha wins.
        await pg.upsert_document(
            staging,
            IndexedDocumentRecord(
                file_path="a.pdf", kind="pdf", extraction="docling", sha256="c" * 64, byte_size=11
            ),
        )
        assert await pg.count_documents(staging) == 2
        pdf = await pg.get_document(staging, "a.pdf")
        assert pdf is not None and pdf.sha256 == "c" * 64 and pdf.byte_size == 11

        # Promotion moves documents with the chunks, atomically, under the fence.
        await pg.promote_staging_index(
            active_repo_id=corpus_id,
            staging_repo_id=staging,
            active_name=corpus_id,
            active_root_path=".",
            run_id=run_id,
            qdrant_collection=None,
            graph_repo_id=None,
        )
        assert await pg.count_documents(staging) == 0
        assert await pg.count_documents(corpus_id) == 2
        promoted = await pg.get_chunk(corpus_id, chunks[0].chunk_id)
        assert promoted is not None and promoted.provenance == _PROV
        assert await pg.file_is_indexed(corpus_id, "a.pdf") is True
        assert await pg.file_is_indexed(corpus_id, "b.md") is True
        # A documents row alone does not make a file viewable: chunks are the authorization.
        assert await pg.file_is_indexed(corpus_id, "c.html") is False
        assert await pg.file_is_indexed(corpus_id, "../etc/passwd") is False

        # A second promotion replaces the previous active documents (no leftovers).
        run_two = f"{run_id}-2"
        staging_two = staging_repo_id(corpus_id, run_two)
        assert await pg.release_index_fence(corpus_id, run_id) is True
        claim_two = await pg.acquire_index_fence(
            corpus_id, run_two, started_at=datetime.now(UTC), owner="this-test:2", lease_seconds=60
        )
        assert claim_two.acquired
        await pg.upsert_chunks(staging_two, [_chunk("d.txt", 0, ChunkProvenance(extraction="direct"))])
        await pg.upsert_document(
            staging_two,
            IndexedDocumentRecord(
                file_path="d.txt", kind="text", extraction="direct", sha256="d" * 64, byte_size=5
            ),
        )
        await pg.promote_staging_index(
            active_repo_id=corpus_id,
            staging_repo_id=staging_two,
            active_name=corpus_id,
            active_root_path=".",
            run_id=run_two,
            qdrant_collection=None,
            graph_repo_id=None,
        )
        assert await pg.count_documents(corpus_id) == 1
        assert await pg.get_document(corpus_id, "a.pdf") is None
        assert (await pg.get_document(corpus_id, "d.txt")) is not None
        assert await pg.release_index_fence(corpus_id, run_two) is True

        # delete_chunks (force re-index) drops the provenance records with the chunks.
        assert await pg.delete_chunks(corpus_id) == 1
        assert await pg.count_documents(corpus_id) == 0
        assert await pg.file_is_indexed(corpus_id, "d.txt") is False

        # delete_corpus_with_data leaves nothing behind either.
        await pg.upsert_document(
            corpus_id,
            IndexedDocumentRecord(
                file_path="e.txt", kind="text", extraction="direct", sha256="e" * 64, byte_size=1
            ),
        )
        assert await pg.count_documents(corpus_id) == 1
        await pg.delete_corpus_with_data(corpus_id)
        assert await pg.count_documents(corpus_id) == 0
        assert await pg.get_corpus(corpus_id) is None

        # FK cascade: deleting just the registry row removes documents too.
        await pg.upsert_document(
            corpus_id,
            IndexedDocumentRecord(
                file_path="f.txt", kind="text", extraction="direct", sha256="f" * 64, byte_size=1
            ),
        )
        assert await pg.count_documents(corpus_id) == 1
        await pg.delete_corpus(corpus_id)
        assert await pg.count_documents(corpus_id) == 0
    finally:
        for rid in (staging, staging_repo_id(corpus_id, f"{run_id}-2"), corpus_id):
            try:
                await pg.delete_corpus_with_data(rid)
            except Exception:
                pass
        await pg.disconnect()
