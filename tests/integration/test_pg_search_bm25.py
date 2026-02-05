"""Integration tests for ParadeDB pg_search BM25 (environment-aware, no mocks)."""

from __future__ import annotations

import os

import pytest

from server.db.postgres import PostgresClient
from server.models.index import Chunk


@pytest.mark.asyncio
async def test_pg_search_bm25_returns_relevant_chunks() -> None:
    """If pg_search is available, ensure BM25 path returns relevant results."""
    # Prefer explicit DSN from env; otherwise use the repo default.
    dsn = os.getenv("POSTGRES_DSN") or "postgresql://postgres:postgres@localhost:5432/tribrid_rag"
    pg = PostgresClient(dsn)

    try:
        await pg.connect()
    except Exception:
        pytest.skip("Postgres not reachable for integration test")

    repo_id = f"it_pg_search_bm25_{os.getpid()}"
    try:
        if not await pg.pg_search_available():
            pytest.skip("pg_search extension not available")

        await pg.upsert_corpus(repo_id, name=repo_id, root_path=".")

        chunks = [
            Chunk(
                chunk_id="c1",
                content="Jeffrey Epstein court filing transcript excerpt",
                file_path="epstein.txt",
                start_line=1,
                end_line=1,
                language=None,
                token_count=0,
                metadata={"chunk_ordinal": 0},
            ),
            Chunk(
                chunk_id="c2",
                content="Unrelated content about gardening and soil health",
                file_path="other.txt",
                start_line=1,
                end_line=1,
                language=None,
                token_count=0,
                metadata={"chunk_ordinal": 0},
            ),
        ]

        # Insert rows (content + metadata); BM25 index (if present) should pick them up.
        await pg.upsert_fts(repo_id, chunks, ts_config="english")

        hits = await pg.bm25_search_pg_search(repo_id, "Epstein filing transcript", 5, query_mode="plain")
        assert hits, "Expected at least one BM25 hit"
        assert any("epstein" in (h.content or "").lower() for h in hits)
    finally:
        # Best-effort cleanup.
        try:
            await pg.delete_corpus(repo_id)
        except Exception:
            pass
        try:
            await pg.disconnect()
        except Exception:
            pass

