"""``delete_corpus_with_data`` takes the corpus's staging rows with it.

Live Postgres only (``requires_postgres``), nothing mocked. Every id here is
test-prefixed (``pytest_``) so the session reaper cleans up after a crash mid-test.

An index run writes its rows under ``__staging__<corpus>__<run>`` (a corpus row, chunks,
documents, chunk summaries with their last-build row, and a scoped config row) and
promotion moves them under the corpus id. A run that dies before promotion leaves those
rows behind. ``delete_index_state`` sweeps them, but ``delete_corpus_with_data`` (the
reaper's cascade, ``reclaim_stale_run``, every test teardown) deleted only the corpus's
own rows, so a deleted corpus kept leaking its dead runs' staging rows into every
registry table.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from server.db.postgres import PostgresClient
from server.indexing.generations import staging_repo_id
from server.models.index import Chunk, ChunkProvenance, IndexedDocumentRecord
from server.models.tribrid_config_model import ChunkSummariesLastBuild, ChunkSummary
from tests.corpus_reaper import TEST_CORPUS_PREFIX
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

# Every table an index run writes under a repo_id (the corpus's own id or a staging id).
REPO_TABLES = (
    "chunk_summaries_last_build",
    "chunk_summaries",
    "documents",
    "chunks",
    "corpus_configs",
    "corpora",
)


def _chunk(repo_id: str, file_path: str, ordinal: int) -> Chunk:
    start = ordinal * 100
    return Chunk(
        chunk_id=f"{file_path}:1-2:{start}",
        content=(
            f"Apollo 11 mission report ({repo_id}): the lunar module Eagle landed in the Sea of "
            f"Tranquility on 20 July 1969 with about 25 seconds of descent fuel remaining. #{ordinal}"
        ),
        file_path=file_path,
        start_line=1,
        end_line=2,
        metadata={"chunk_ordinal": ordinal, "char_start": start, "char_end": start + 50},
        provenance=ChunkProvenance(extraction="docling"),
    )


async def _plant_run_rows(pg: PostgresClient, repo_id: str) -> None:
    """Write one run's rows under ``repo_id`` the way the index job does, in every table."""
    chunk = _chunk(repo_id, "A11_MissionReport.pdf", 0)
    assert await pg.upsert_chunks(repo_id, [chunk]) == 1  # also creates the corpora row
    await pg.upsert_document(
        repo_id,
        IndexedDocumentRecord(
            file_path="A11_MissionReport.pdf",
            kind="pdf",
            extraction="docling",
            sha256=uuid.uuid5(uuid.NAMESPACE_URL, repo_id).hex * 2,
            byte_size=4096,
        ),
    )
    await pg.replace_chunk_summaries(
        repo_id,
        [
            ChunkSummary(
                chunk_id=chunk.chunk_id,
                file_path=chunk.file_path,
                start_line=1,
                end_line=2,
                purpose="Eagle's landing in the Sea of Tranquility and the descent fuel margin",
                domain_concepts=["lunar module", "descent fuel"],
            )
        ],
        ChunkSummariesLastBuild(repo_id=repo_id, total=1, enriched=0),
    )
    await pg.upsert_corpus_config_json(repo_id, {"indexing": {"chunk_size": 512}})


async def _row_counts(dsn: str, ids: list[str]) -> dict[str, int]:
    conn = await asyncpg.connect(dsn)
    try:
        return {
            table: int(
                await conn.fetchval(
                    f"SELECT count(*) FROM {table} WHERE repo_id = ANY($1::text[]);", ids
                )
            )
            for table in REPO_TABLES
        }
    finally:
        await conn.close()


async def test_delete_corpus_with_data_sweeps_the_corpus_staging_rows_and_spares_siblings() -> None:
    dsn = require_env("POSTGRES_DSN")
    suffix = uuid.uuid4().hex[:8]
    corpus = f"{TEST_CORPUS_PREFIX}corpus_delete_{suffix}"
    # ``a`` must never sweep the staging rows of ``a__b``: run ids never contain ``__``,
    # and this is the sibling the prefix rule in delete_index_state is written for.
    sibling = f"{corpus}__b"
    dead_runs = [staging_repo_id(corpus, uuid.uuid4().hex) for _ in range(2)]
    sibling_run = staging_repo_id(sibling, uuid.uuid4().hex)
    pg = PostgresClient(dsn)
    await pg.connect()
    try:
        for owner in (corpus, sibling):
            await pg.upsert_corpus(owner, name=owner, root_path=".")
        for repo_id in (corpus, sibling, *dead_runs, sibling_run):
            await _plant_run_rows(pg, repo_id)

        # Planted for real: one row per table under every id (corpora counts one row each).
        planted = await _row_counts(dsn, [*dead_runs])
        assert planted == dict.fromkeys(REPO_TABLES, len(dead_runs)), planted
        sibling_before = await _row_counts(dsn, [sibling, sibling_run])
        assert sibling_before == dict.fromkeys(REPO_TABLES, 2), sibling_before

        await pg.delete_corpus_with_data(corpus)

        # The corpus and both of its dead runs are gone from every table...
        remaining = await _row_counts(dsn, [corpus, *dead_runs])
        assert remaining == dict.fromkeys(REPO_TABLES, 0), remaining
        assert await pg.get_corpus(corpus) is None
        for staged in dead_runs:
            assert await pg.get_corpus(staged) is None
        # ... and the sibling corpus, with its own staged run, is untouched.
        assert await _row_counts(dsn, [sibling, sibling_run]) == sibling_before
        assert await pg.get_corpus(sibling) is not None
        assert await pg.get_corpus(sibling_run) is not None
    finally:
        for repo_id in (sibling, sibling_run, corpus, *dead_runs):
            try:
                await pg.delete_corpus_with_data(repo_id)
            except Exception:
                pass
        await pg.disconnect()
