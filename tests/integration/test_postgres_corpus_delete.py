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

import asyncio
import json
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from httpx import AsyncClient

from server.config import DEFAULT_CONFIG_PATH, load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient, _delete_corpus_staging_rows
from server.indexing.generations import (
    IndexFenceHeldError,
    IndexRunFence,
    ReclaimEntry,
    build_generation,
    staging_repo_id,
)
from server.lineage.registry import lineage_root
from server.models.index import Chunk, ChunkProvenance, IndexedDocumentRecord
from server.models.tribrid_config_model import ChunkSummariesLastBuild, ChunkSummary
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services.config_store import ConfigStore
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


@pytest.mark.requires_neo4j
@pytest.mark.requires_qdrant
@pytest.mark.parametrize("route", ["corpora", "repos"])
@pytest.mark.parametrize("config_state", ["current", "absent", "migratable", "global_migration"])
@pytest.mark.parametrize(
    "state",
    ["indexed", "unindexed", "active", "missing", "manual", "explicit_manual", "complete_advisory", "complete_row"],
)
async def test_conditional_corpus_delete_preserves_indexed_data(
    client: AsyncClient, route: str, state: str, config_state: str
) -> None:
    """Cleanup's freshness condition holds at the write lock, including a just-finished index."""
    dsn = require_env("POSTGRES_DSN")
    cfg = load_config()
    corpus = f"{TEST_CORPUS_PREFIX}conditional_delete_{uuid.uuid4().hex[:12]}"
    staged = staging_repo_id(corpus, uuid.uuid4().hex)
    pg = PostgresClient(dsn)
    qdrant = QdrantChunkStore(cfg)
    neo4j = Neo4jClient(
        require_env("NEO4J_URI"), require_env("NEO4J_USER"), require_env("NEO4J_PASSWORD"),
        database=cfg.graph_storage.neo4j_database,
    )
    marker = lineage_root() / "bundles" / corpus / "operator-note.txt"
    deletion: asyncio.Task | None = None
    indexed = state in {"indexed", "manual", "explicit_manual"}
    race = state.startswith("complete_")
    try:
        await pg.connect()
        await neo4j.connect()
        if state != "missing":
            await pg.upsert_corpus(corpus, name="Apollo 11 descent fuel", root_path=".")
            if indexed:
                await _plant_run_rows(pg, corpus)
            await pg.upsert_corpus_config_json(corpus, cfg.model_dump(mode="serialization"))
            if config_state == "absent":
                assert pg._pool is not None
                async with pg._pool.acquire() as conn:
                    await conn.execute("DELETE FROM corpus_configs WHERE repo_id = $1", corpus)
            elif config_state == "migratable":
                raw = cfg.model_dump(mode="serialization")
                raw["reranking"]["reranker_timeout"] = 10
                await pg.upsert_corpus_config_json(corpus, raw)
        if config_state == "global_migration":
            raw_global = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
            raw_global["reranking"]["reranker_timeout"] = 10
            DEFAULT_CONFIG_PATH.write_text(json.dumps(raw_global), encoding="utf-8")
        await _plant_run_rows(pg, staged)
        chunk = _chunk(corpus, "A11_MissionReport.pdf", 0).model_copy(update={"embedding": [1.0, 0.0]})
        physical = await qdrant.create_generation(corpus, embedding_dim=2)
        assert await qdrant.write_chunks(corpus, physical, [chunk], embedding_dim=2) == 1
        async with neo4j._require_driver().session(database=neo4j.database) as session:
            await session.run(
                "CREATE (:__Entity__ {repo_id: $repo_id, id: $id, name: $name})",
                repo_id=staged, id=f"{staged}:eagle", name="Eagle descent fuel",
            )
        generation = build_generation(
            run_id="completed-flight-report", qdrant_collection=physical, graph_repo_id=staged
        )
        metadata = {"operator_note": "Preserve the descent fuel evidence"}
        if indexed:
            metadata["generation"] = generation.model_dump(mode="json")
        if state != "missing":
            await pg.update_corpus_meta(corpus, metadata)
        if state == "active":
            assert (await pg.acquire_index_fence(
                corpus, "active-flight-report", started_at=datetime.now(UTC), owner="pytest:conditional-delete",
                lease_seconds=cfg.indexing.index_run_lease_seconds,
            )).acquired
        marker.parent.mkdir(parents=True)
        marker.write_text("Apollo 11 descent fuel evidence must survive refused cleanup.", encoding="utf-8")
        before = await pg.get_corpus(corpus)
        before_config = await pg.get_corpus_config_json(corpus)
        before_global_bytes = DEFAULT_CONFIG_PATH.read_bytes()
        assert pg._pool is not None
        async with pg._pool.acquire() as conn:
            before_config_row = await conn.fetchrow(
                "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
            )
        before_counts = await _row_counts(dsn, [corpus, staged])
        assert before_counts["chunks"] == (2 if indexed else 1)
        assert (await neo4j.get_graph_stats(staged)).total_entities == 1
        status = await qdrant.status(corpus, physical=physical)
        assert status is not None and status.points == 1
        params = {} if state == "manual" else {"only_unindexed": "false" if state == "explicit_manual" else "true"}
        if race:
            # This is the fresh preflight seen by the cleanup UI. Completion is still
            # uncommitted while its DELETE reaches the database's real lock queue.
            preflight = await client.get(f"/api/corpora/{corpus}")
            assert preflight.status_code == 200, preflight.text
            assert preflight.json()["last_indexed"] is None
            conn = await asyncpg.connect(dsn)
            try:
                async with conn.transaction():
                    if state == "complete_advisory":
                        await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", corpus)
                    await conn.fetchrow("SELECT repo_id FROM corpora WHERE repo_id = $1 FOR UPDATE", corpus)
                    blocker_pid = await conn.fetchval("SELECT pg_backend_pid()")
                    deletion = asyncio.create_task(client.delete(f"/api/{route}/{corpus}", params=params))
                    async with asyncio.timeout(15):
                        while not await conn.fetchval(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname = current_database() "
                            "AND wait_event_type = 'Lock' AND $1 = ANY(pg_blocking_pids(pid)))",
                            blocker_pid,
                        ):
                            assert not deletion.done(), "DELETE must wait for the corpus write lock"
                            await asyncio.sleep(0.01)
                    # The same chunk writer used by indexing stamps last_indexed in
                    # this transaction. The waiting delete must read that committed value.
                    await pg._upsert_chunk_rows(conn, corpus, [chunk])
                    metadata["generation"] = generation.model_dump(mode="json")
                    await conn.execute("UPDATE corpora SET meta = $2::jsonb WHERE repo_id = $1", corpus, json.dumps(metadata))
                    assert before is not None
                    before["last_indexed"] = await conn.fetchval("SELECT last_indexed FROM corpora WHERE repo_id = $1", corpus)
                    before["meta"] = metadata
                    before_counts["chunks"] += 1
            finally:
                await conn.close()
            response = await asyncio.wait_for(deletion, timeout=30)
        else:
            response = await client.delete(f"/api/{route}/{corpus}", params=params)

        if state in {"indexed", "complete_advisory", "complete_row"}:
            assert response.status_code == 409, response.text
            from server.models.corpus import CorpusAlreadyIndexedResponse

            conflict = CorpusAlreadyIndexedResponse.model_validate(response.json()).detail
            assert conflict.code == "corpus_already_indexed"
            assert conflict.corpus_id == corpus
            assert before is not None and conflict.last_indexed == before["last_indexed"]
            assert conflict.message and conflict.operator_hint
        elif state == "active":
            assert response.status_code == 409, response.text
            assert response.json()["detail"]["code"] == "index_run_in_progress"
            assert response.json()["detail"]["run_id"] == "active-flight-report"
        elif state == "missing":
            assert response.status_code == 404, response.text
        else:
            assert response.status_code == 200, response.text
            assert response.json() == {"ok": True}

        refused = state not in {"unindexed", "manual", "explicit_manual"}
        if refused:
            assert DEFAULT_CONFIG_PATH.read_bytes() == before_global_bytes
            assert await pg.get_corpus(corpus) == before
            assert await pg.get_corpus_config_json(corpus) == before_config
            async with pg._pool.acquire() as conn:
                after_config_row = await conn.fetchrow(
                    "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
                )
            assert after_config_row == before_config_row
            assert await _row_counts(dsn, [corpus, staged]) == before_counts
            assert await pg.get_index_tombstone(corpus) is None
            assert (await neo4j.get_graph_stats(staged)).total_entities == 1
            status = await qdrant.status(corpus, physical=physical)
            assert status is not None and status.physical_collection == physical and status.points == 1
            assert marker.read_text(encoding="utf-8").startswith("Apollo 11 descent fuel")
        else:
            assert await pg.get_corpus(corpus) is None
            assert await _row_counts(dsn, [corpus, staged]) == dict.fromkeys(REPO_TABLES, 0)
            assert (await neo4j.get_graph_stats(staged)).total_entities == 0
            status = await qdrant.status(corpus, physical=physical)
            assert status is not None and status.physical_collection is None
            assert not marker.exists()
    finally:
        if deletion is not None and not deletion.done():
            deletion.cancel()
            with suppress(asyncio.CancelledError):
                await deletion
        await qdrant.delete_corpus(corpus)
        await neo4j.delete_graph(staged)
        await pg.delete_corpus_with_data(corpus)
        await neo4j.disconnect()
        await pg.disconnect()


@pytest.mark.parametrize("config_state", ["current", "absent", "migratable"])
async def test_config_preview_preserves_storage_and_cache(config_state: str) -> None:
    """A preview neither persists migrations nor prevents a later ordinary read from doing so."""
    dsn = require_env("POSTGRES_DSN")
    corpus = f"{TEST_CORPUS_PREFIX}config_preview_{uuid.uuid4().hex[:12]}"
    pg = PostgresClient(dsn, schema_mode="control")
    cfg = load_config()
    raw_global = cfg.model_dump(mode="serialization")
    raw_global["reranking"]["reranker_timeout"] = 10
    DEFAULT_CONFIG_PATH.write_text(json.dumps(raw_global), encoding="utf-8")
    global_bytes = DEFAULT_CONFIG_PATH.read_bytes()
    conn = await asyncpg.connect(dsn)
    try:
        await pg.connect()
        await pg.upsert_corpus(corpus, name="Apollo 11 config preview", root_path=".")
        if config_state != "absent":
            raw = cfg.model_dump(mode="serialization")
            raw["indexing"]["index_run_lease_seconds"] = 123
            raw["reranking"]["reranker_timeout"] = 10 if config_state == "migratable" else 30
            await pg.upsert_corpus_config_json(corpus, raw)
        before = await conn.fetchrow(
            "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
        )
        store = ConfigStore(dsn)
        preview = await store.get(repo_id=corpus, persist=False)
        lease = cfg.indexing.index_run_lease_seconds if config_state == "absent" else 123
        assert preview.indexing.index_run_lease_seconds == lease
        assert preview.reranking.reranker_timeout == 30
        assert DEFAULT_CONFIG_PATH.read_bytes() == global_bytes
        assert await conn.fetchrow(
            "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
        ) == before
        assert store._cache == {}

        # The preview must not warm a cache that would suppress the normal write.
        persisted = await store.get(repo_id=corpus)
        assert persisted == preview
        assert json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))["reranking"]["reranker_timeout"] == 30
        saved = await pg.get_corpus_config_json(corpus)
        assert saved is not None and saved["reranking"]["reranker_timeout"] == 30
        if config_state == "current":
            assert await conn.fetchrow(
                "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
            ) == before
        else:
            assert await conn.fetchrow(
                "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
            ) != before

        # A warm cache stays available to ordinary reads; previews see the actual
        # saved scoped lease and must not replace or mutate that cached snapshot.
        saved["indexing"]["index_run_lease_seconds"] = 124
        await pg.upsert_corpus_config_json(corpus, saved)
        warm_before = await conn.fetchrow(
            "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
        )
        warm_global_bytes = DEFAULT_CONFIG_PATH.read_bytes()
        fresh_preview = await store.get(repo_id=corpus, persist=False)
        assert fresh_preview.indexing.index_run_lease_seconds == 124
        assert store._cache[corpus].indexing.index_run_lease_seconds == lease
        fresh_preview.indexing.index_run_lease_seconds = 125
        assert (await store.get(repo_id=corpus)).indexing.index_run_lease_seconds == lease
        assert DEFAULT_CONFIG_PATH.read_bytes() == warm_global_bytes
        assert await conn.fetchrow(
            "SELECT config, updated_at FROM corpus_configs WHERE repo_id = $1", corpus
        ) == warm_before
        store.clear_cache()
        assert (await store.get(repo_id=corpus)).indexing.index_run_lease_seconds == 124
    finally:
        await pg.delete_corpus_with_data(corpus)
        await pg.disconnect()
        await conn.close()
