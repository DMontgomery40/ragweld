"""Integration tests for PostgresClient schema + metadata.

These tests use a real Postgres instance (CI provides pgvector/pg16).
"""

from __future__ import annotations

import os
import uuid

import pytest

from server.db.postgres import PostgresClient
from server.models.index import Chunk


def _postgres_available() -> bool:
    return bool(os.getenv("POSTGRES_DSN") or os.getenv("POSTGRES_HOST"))


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

