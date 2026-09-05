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

import os
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from server.db.postgres import PostgresClient, _delete_corpus_staging_rows
from server.indexing.generations import IndexFenceHeldError, IndexRunFence, ReclaimEntry, staging_repo_id
from server.models.index import Chunk, ChunkProvenance, IndexedDocumentRecord
from server.models.tribrid_config_model import ChunkSummariesLastBuild, ChunkSummary
from tests.corpus_reaper import TEST_CORPUS_PREFIX, reap_stale_test_corpora
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


@pytest.mark.parametrize("schema_mode", ["control", "full", "full_without_foreign_keys"])
@pytest.mark.parametrize("operation", ["staging", "corpus", "deindex", "deindex_backlog", "chunks", "reaper", "direct_corpus", pytest.param("api_corpus", marks=[pytest.mark.requires_neo4j, pytest.mark.requires_qdrant])])
async def test_corpus_cleanup_handles_fresh_schema_inventory(
    schema_mode: str, operation: str
) -> None:
    """Bootstrap an empty database, then clear owned rows without relying on FKs."""
    base_dsn = require_env("POSTGRES_DSN")
    database = f"pytest_corpus_cleanup_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(base_dsn)
    await admin.execute(f'CREATE DATABASE "{database}"')
    await admin.execute(f'ALTER DATABASE "{database}" SET search_path TO public, unrelated')
    parts = urlsplit(base_dsn)
    private_dsn = urlunsplit(parts._replace(path=f"/{database}"))
    old_dsn = os.environ.get("POSTGRES_DSN")
    os.environ["POSTGRES_DSN"] = private_dsn
    pg = PostgresClient(private_dsn, schema_mode="control" if schema_mode == "control" else "full")
    conn = None
    try:
        await pg.connect()
        conn = await asyncpg.connect(private_dsn)
        assert await conn.fetchval("SHOW search_path") == "public, unrelated"
        assert pg._pool is not None
        async with pg._pool.acquire() as pooled:
            assert await pooled.fetchval("SHOW search_path") == "public, unrelated"
        tables = ("corpus_configs", "corpora") if schema_mode == "control" else REPO_TABLES
        present = {
            row["tablename"]
            for row in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }
        assert set(tables) <= present
        if schema_mode == "control":
            assert present == set(tables)
        if schema_mode == "full_without_foreign_keys":
            for row in await conn.fetch(
                "SELECT conrelid::regclass::text AS table_name, conname FROM pg_constraint "
                "WHERE contype = 'f' AND confrelid = 'corpora'::regclass"
            ):
                await conn.execute(f'ALTER TABLE {row["table_name"]} DROP CONSTRAINT "{row["conname"]}"')
        corpus = "pytest_cleanup_owner"
        sibling = f"{corpus}__sibling"
        staged_run = uuid.uuid4().hex
        staged = staging_repo_id(corpus, staged_run)
        sibling_staged = staging_repo_id(sibling, uuid.uuid4().hex)
        for repo_id in (corpus, sibling, staged, sibling_staged):
            await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
            if schema_mode == "control":
                await pg.upsert_corpus_config_json(repo_id, {"indexing": {"chunk_size": 512}})
            else:
                await _plant_run_rows(pg, repo_id)
        # A similarly named table outside the intended schema must never be touched.
        await conn.execute("CREATE SCHEMA unrelated")
        await conn.execute("CREATE TABLE unrelated.chunk_summaries_last_build (repo_id text)")
        await conn.execute("INSERT INTO unrelated.chunk_summaries_last_build VALUES ($1), ($2)", corpus, staged)
        if operation == "staging":
            await _delete_corpus_staging_rows(conn, corpus)
            removed, retained = [staged], [corpus, sibling, sibling_staged]
        elif operation.startswith("deindex"):
            now = datetime.now(UTC)
            fence = IndexRunFence(run_id="active", owner="pytest", started_at=now, heartbeat_at=now)
            metadata = {"index_run": fence.model_dump(mode="json"), "keep": "operator metadata"}
            if operation == "deindex_backlog":
                entry = ReclaimEntry(run_id=staged_run, staged_qdrant_collection="pytest_staged_vectors",
                                     staged_graph_repo_id="pytest_staged_graph", recorded_at=now)
                metadata["reclaim_backlog"] = [entry.model_dump(mode="json")]
            await pg.update_corpus_meta(corpus, metadata)
            with pytest.raises(IndexFenceHeldError):
                await pg.delete_index_state(corpus, lease_seconds=3600)
            # A refused deletion changes neither staging data nor the live fence.
            assert await conn.fetchval("SELECT count(*) FROM corpora WHERE repo_id = $1", staged) == 1
            count, tombstone = await pg.delete_index_state(corpus, lease_seconds=3600, allow_fence_run_id="active")
            assert count == (0 if schema_mode == "control" else 1)
            assert tombstone.intent == "deindex"
            assert tombstone.qdrant_collections == (["pytest_staged_vectors"] if operation == "deindex_backlog" else [])
            assert tombstone.graph_repo_ids == (["pytest_staged_graph"] if operation == "deindex_backlog" else [])
            owner = await pg.get_corpus(corpus)
            assert owner is not None
            assert owner["meta"] == {"keep": "operator metadata", "index_tombstone": tombstone.model_dump(mode="json")}
            assert owner["last_indexed"] is None
            repeat_count, repeat_tombstone = await pg.delete_index_state(corpus, lease_seconds=3600)
            assert repeat_count == 0
            assert repeat_tombstone.qdrant_collections == tombstone.qdrant_collections
            assert repeat_tombstone.graph_repo_ids == tombstone.graph_repo_ids
            removed, retained = [corpus, staged], [sibling, sibling_staged]
        elif operation == "chunks":
            assert await pg.delete_chunks(corpus) == (0 if schema_mode == "control" else 1)
            assert await pg.delete_chunks(corpus) == 0
            removed, retained = [corpus], [staged, sibling, sibling_staged]
        elif operation == "direct_corpus":
            await pg.delete_corpus(corpus)
            removed, retained = [corpus, staged], [sibling, sibling_staged]
        elif operation == "api_corpus":
            from httpx import ASGITransport, AsyncClient
            from server.main import app

            _, tombstone = await pg.delete_index_state(corpus, lease_seconds=3600, intent="delete_corpus")
            assert tombstone.intent == "delete_corpus"
            assert await pg.get_corpus(corpus) is not None
            assert await pg.get_corpus_config_json(corpus) is not None
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
                response = await api.delete(f"/api/corpora/{corpus}")
            assert response.status_code == 200, response.text
            removed, retained = [corpus, staged], [sibling, sibling_staged]
        elif operation == "reaper":
            await conn.execute("UPDATE corpora SET created_at = now() - interval '2 hours' WHERE repo_id = ANY($1)", [corpus, staged])
            reaped = await reap_stale_test_corpora(private_dsn, max_age_seconds=3600)
            assert corpus in reaped
            assert sibling not in reaped
            assert sibling_staged not in reaped
            removed, retained = [corpus, staged], [sibling, sibling_staged]
        else:
            await pg.delete_corpus_with_data(corpus)
            removed, retained = [corpus, staged], [sibling, sibling_staged]
        for table in tables:
            table_removed, table_retained = removed, retained
            if (operation.startswith("deindex") and table in ("corpora", "corpus_configs")) or (operation == "chunks" and table not in ("chunks", "documents")):
                table_removed = [repo_id for repo_id in removed if repo_id != corpus]
                table_retained = [*retained, corpus]
            assert await conn.fetchval(f"SELECT count(*) FROM {table} WHERE repo_id = ANY($1)", table_removed) == 0
            assert await conn.fetchval(f"SELECT count(*) FROM {table} WHERE repo_id = ANY($1)", table_retained) == len(table_retained)
        assert await conn.fetchval("SELECT count(*) FROM unrelated.chunk_summaries_last_build") == 2
    finally:
        if conn is not None:
            await conn.close()
        await PostgresClient.close_shared_pools()
        if old_dsn is None:
            os.environ.pop("POSTGRES_DSN", None)
        else:
            os.environ["POSTGRES_DSN"] = old_dsn
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()

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
