"""Integration tests for PostgresClient schema + metadata.

These tests use a real Postgres instance (CI provides pgvector/pg16).
"""

from __future__ import annotations

import uuid
from contextlib import suppress

import pytest

from server.db.postgres import (
    PostgresClient,
    _json_dumps_sanitized,
    _sanitize_chunk_for_storage,
)
from server.models.index import Chunk
from server.models.tribrid_config_model import (
    ChunkSummariesLastBuild,
    ChunkSummary,
    RecallIntensity,
)


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


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_upsert_chunks_stores_metadata_and_get_chunk_returns_it() -> None:
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
        await pg.upsert_chunks(repo_id, [ch])

        got = await pg.get_chunk(repo_id, "c1")
        assert got is not None
        assert got.metadata.get("kind") == "unit_test"
        assert got.metadata.get("n") == 1
        assert await pg.count_chunks(repo_id) == 1
        corpus = await pg.get_corpus(repo_id)
        assert corpus is not None and corpus["last_indexed"] is not None
    finally:
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_chunk_summaries_roundtrip_extended_fields() -> None:
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


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_corpus_contract_metadata_round_trips_sparse_contract() -> None:
    repo_id = f"test_contract_meta_{uuid.uuid4().hex[:10]}"
    pg = PostgresClient("postgresql://ignored")
    await pg.connect()
    try:
        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")
        sparse = {"engine": "qdrant_sparse_idf", "model": "Qdrant/bm25", "k1": 1.2, "b": 0.4, "language": "english", "stemmer": True}
        await pg.update_corpus_embedding_meta(
            repo_id,
            backend="deterministic",
            provider="",
            model="",
            dimensions=384,
            sparse_contract=sparse,
        )
        corpus = await pg.get_corpus(repo_id)
        assert corpus is not None
        assert corpus["embedding_dimensions"] == 384
        assert corpus["sparse_contract"] == sparse
        assert "ts_config" not in corpus
    finally:
        with suppress(Exception):
            await pg.delete_corpus(repo_id)
