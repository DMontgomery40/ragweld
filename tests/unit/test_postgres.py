"""Integration tests for PostgresClient schema + metadata.

These tests use a real Postgres instance (CI provides pgvector/pg16).
"""

from __future__ import annotations

import os
import uuid
from contextlib import suppress

import pytest

from server.db.postgres import (
    PostgresClient,
    _json_dumps_sanitized,
    _sanitize_chunk_for_storage,
    _vector_index_name,
)
from server.models.index import Chunk
from server.models.tribrid_config_model import (
    ChunkSummariesLastBuild,
    ChunkSummary,
    RecallIntensity,
)


def _postgres_available() -> bool:
    return bool(os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST"))


def test_vector_index_name_is_stable_and_bounded() -> None:
    repo_id = "codex-sessions-2026-semantic"
    first = _vector_index_name(repo_id)
    second = _vector_index_name(repo_id)
    assert first == second
    assert first.startswith("idx_chunks_")
    assert first.endswith("_embedding_hnsw")
    assert len(first) < 63


def test_sanitize_chunk_for_storage_strips_nul_bytes() -> None:
    chunk = Chunk(
        chunk_id="c1",
        content="bad\x00content",
        file_path="file\x00path.txt",
        start_line=1,
        end_line=1,
        language="text\x00plain",
        token_count=2,
        embedding=[0.0, 0.1, 0.2],
        summary=None,
        metadata={"bad\x00key": "bad\x00value"},
    )
    sanitized = _sanitize_chunk_for_storage(chunk)
    assert "\x00" not in sanitized.content
    assert "\x00" not in sanitized.file_path
    assert sanitized.language is not None and "\x00" not in sanitized.language
    assert "\x00" not in str(sanitized.metadata)


def test_json_dumps_sanitized_preserves_str_enum_values() -> None:
    payload = {"default_intensity": RecallIntensity.standard}
    dumped = _json_dumps_sanitized(payload)
    assert '"standard"' in dumped
    assert "RecallIntensity.standard" not in dumped


@pytest.mark.asyncio
async def test_upsert_fts_stores_metadata_and_get_chunk_returns_it() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_meta_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        ch = Chunk(
            chunk_id="c1",
            content="hello world",
            file_path="a.txt",
            start_line=1,
            end_line=1,
            language=None,
            token_count=2,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test", "n": 1},
        )
        await pg.upsert_fts(repo_id, [ch], ts_config="english")

        got = await pg.get_chunk(repo_id, "c1")
        assert got is not None
        assert got.metadata.get("kind") == "unit_test"
        assert got.metadata.get("n") == 1
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_vector_search_returns_metadata() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_vecmeta_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        ch = Chunk(
            chunk_id="c1",
            content="hello world",
            file_path="a.txt",
            start_line=1,
            end_line=1,
            language=None,
            token_count=2,
            embedding=[0.0, 0.1, 0.2],
            summary=None,
            metadata={"kind": "unit_test", "n": 2},
        )
        try:
            await pg.upsert_embeddings(repo_id, [ch])
        except Exception as e:  # pragma: no cover
            pytest.skip(f"vector insert failed (pgvector dims?): {e}")

        matches = await pg.vector_search(repo_id, [0.0, 0.1, 0.2], top_k=1)
        assert len(matches) == 1
        assert matches[0].chunk_id == "c1"
        assert matches[0].metadata.get("kind") == "unit_test"
        assert matches[0].metadata.get("n") == 2
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_fts_search_relaxed_or_finds_hits_when_plain_is_empty() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_relaxfts_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        ch = Chunk(
            chunk_id="c1",
            content="authentication flow token refresh login",
            file_path="src/auth.py",
            start_line=1,
            end_line=1,
            language="python",
            token_count=5,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        )
        await pg.upsert_fts(repo_id, [ch], ts_config="english")

        # plainto_tsquery uses AND semantics; include a term that is not in the doc.
        q = "Where is the authentication flow unicorn token refresh code?"
        plain = await pg.fts_search(repo_id, q, top_k=5, ts_config="english", query_mode="plain")
        assert plain == []

        relaxed = await pg.fts_search_relaxed_or(repo_id, q, top_k=5, ts_config="english", max_terms=8)
        assert any(m.chunk_id == "c1" for m in relaxed)
        assert relaxed[0].metadata.get("sparse_engine") == "postgres_fts_relaxed_or"
        assert relaxed[0].metadata.get("sparse_relaxed") is True
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_file_path_search_finds_filename_like_queries() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_filepath_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        ch = Chunk(
            chunk_id="c1",
            content="def handler():\n    pass\n",
            file_path="src/auth/login_controller.py",
            start_line=1,
            end_line=2,
            language="python",
            token_count=3,
            embedding=None,
            summary=None,
            metadata={"kind": "unit_test"},
        )
        await pg.upsert_fts(repo_id, [ch], ts_config="english")

        hits = await pg.file_path_search(repo_id, "login controller", top_k=5, max_terms=6)
        assert hits
        assert hits[0].chunk_id == "c1"
        assert hits[0].metadata.get("sparse_engine") == "file_path"
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_chunk_summaries_roundtrip_extended_fields() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_chunk_summary_ext_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        summaries = [
            ChunkSummary(
                chunk_id="c1",
                file_path="server/api/example.py",
                start_line=1,
                end_line=10,
                purpose="Example summary",
                symbols=["foo", "bar"],
                technical_details="details",
                domain_concepts=["auth"],
                routes=["/api/example"],
                dependencies=["fastapi"],
                patterns=["async_io"],
                card_source="llm",
                card_score=8.5,
            )
        ]
        last_build = ChunkSummariesLastBuild(repo_id=repo_id, total=1, enriched=1)
        await pg.replace_chunk_summaries(repo_id, summaries=summaries, last_build=last_build)

        listed = await pg.list_chunk_summaries(repo_id)
        assert len(listed) == 1
        got = listed[0]
        assert got.routes == ["/api/example"]
        assert got.dependencies == ["fastapi"]
        assert got.patterns == ["async_io"]
        assert got.card_source == "llm"
        assert got.card_score == pytest.approx(8.5)
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_ensure_vector_index_creates_partial_hnsw_index() -> None:
    if not _postgres_available():
        pytest.skip("POSTGRES_DSN/POSTGRES_HOST not set")

    repo_id = f"test_vecidx_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    index_name = _vector_index_name(repo_id)
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        chunk = Chunk(
            chunk_id="c1",
            content="hello vector world",
            file_path="a.txt",
            start_line=1,
            end_line=1,
            language=None,
            token_count=3,
            embedding=[0.0, 0.1, 0.2],
            summary=None,
            metadata={"kind": "unit_test"},
        )
        try:
            await pg.upsert_embeddings(repo_id, [chunk])
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"vector insert failed (pgvector dims?): {exc}")

        await pg._require_pool()
        assert pg._pool is not None
        async with pg._pool.acquire() as conn:
            corpus = await conn.fetchrow(
                """
                SELECT embedding_dimensions
                FROM corpora
                WHERE repo_id = $1
                """,
                repo_id,
            )
        assert corpus is not None
        assert int(corpus["embedding_dimensions"] or 0) == 3

        created = await pg.ensure_vector_index(repo_id)
        assert created == index_name
        async with pg._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND indexname = $1
                """,
                index_name,
            )
        assert row is not None
        assert "USING hnsw" in str(row["indexdef"])
        assert repo_id in str(row["indexdef"])
    finally:
        with suppress(Exception):
            assert pg._pool is not None
            async with pg._pool.acquire() as conn:
                await conn.execute(f"DROP INDEX IF EXISTS {index_name};")
        with suppress(Exception):
            await pg.delete_corpus(repo_id)
