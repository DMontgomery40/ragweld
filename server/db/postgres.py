from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

import asyncpg
from pgvector.asyncpg import register_vector

from server.models.index import Chunk, IndexStats
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChunkSummariesLastBuild, ChunkSummary, VocabPreviewTerm

# -----------------------------------------------------------------------------
# Shared asyncpg pool caching (process-wide)
#
# This codebase creates PostgresClient instances in multiple places (API routes,
# retrieval pipeline, config store). Creating a new asyncpg pool per instance is
# expensive (connect handshake + schema init). We keep one pool per DSN and reuse
# it across all PostgresClient instances.
# -----------------------------------------------------------------------------
_POOLS_BY_DSN: dict[str, asyncpg.Pool] = {}
_POOL_LOCKS_BY_DSN: dict[str, asyncio.Lock] = {}


_RELAXED_FTS_TERM_RE = re.compile(r"[A-Za-z0-9_]{3,64}")
_FILE_PATH_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\\-]{1,63}")

# Intentionally small list: we only drop filler words that commonly appear in
# natural-language queries and add noise to FTS OR fallbacks.
_RELAXED_FTS_STOPWORDS = {
    "about",
    "also",
    "and",
    "are",
    "but",
    "can",
    "code",
    "does",
    "document",
    "documents",
    "explain",
    "file",
    "files",
    "find",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "of",
    "on",
    "or",
    "related",
    "show",
    "the",
    "this",
    "to",
    "what",
    "where",
    "which",
    "why",
    "with",
}


def _extract_terms(query: str, *, pattern: re.Pattern[str], max_terms: int, stopwords: set[str]) -> list[str]:
    if not query.strip() or max_terms <= 0:
        return []
    terms: list[str] = []
    seen: set[str] = set()
    for m in pattern.finditer(query):
        t = str(m.group(0)).lower()
        if not t or t in stopwords or t in seen:
            continue
        seen.add(t)
        terms.append(t)
        if len(terms) >= max_terms:
            break
    return terms


def _extract_relaxed_fts_terms(query: str, *, max_terms: int) -> list[str]:
    return _extract_terms(
        query,
        pattern=_RELAXED_FTS_TERM_RE,
        max_terms=max_terms,
        stopwords=_RELAXED_FTS_STOPWORDS,
    )


def _extract_file_path_terms(query: str, *, max_terms: int) -> list[str]:
    stop = _RELAXED_FTS_STOPWORDS | {"path", "paths", "src"}
    return _extract_terms(query, pattern=_FILE_PATH_TERM_RE, max_terms=max_terms, stopwords=stop)


def _coerce_jsonb_dict(value: Any) -> dict[str, Any]:
    """Coerce asyncpg JSON/JSONB values to a dict (robust across codecs)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    try:
        return dict(value)
    except Exception:
        return {}


class PostgresClient:
    """Postgres index store (pgvector + FTS).

    Stores all indexed chunks in PostgreSQL and supports:
    - Dense retrieval via pgvector
    - Sparse retrieval via PostgreSQL full-text search (tsvector + tsquery)
    - Corpus separation via repo_id partition key (repo_id == corpus_id)

    NOTE: This is intentionally "real" storage: the source of truth is Postgres.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self._pool: asyncpg.Pool | None = None
        self._resolved_dsn: str | None = None
        self._pg_search_available: bool | None = None

    # ---------------------------------------------------------------------
    # Connection + schema
    # ---------------------------------------------------------------------

    async def connect(self) -> None:
        if self._pool is not None:
            return

        dsn = self._resolve_dsn(self.connection_string)
        self._resolved_dsn = dsn

        # Fast path: pool already exists for this DSN (no locking needed).
        existing = _POOLS_BY_DSN.get(dsn)
        if existing is not None:
            self._pool = existing
            return

        # Lazily create a lock per DSN (locks bind to the running loop).
        lock = _POOL_LOCKS_BY_DSN.get(dsn)
        if lock is None:
            lock = asyncio.Lock()
            _POOL_LOCKS_BY_DSN[dsn] = lock

        async with lock:
            pool = _POOLS_BY_DSN.get(dsn)
            if pool is None:
                pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
                try:
                    async with pool.acquire() as conn:
                        # Ensure extension exists before registering pgvector codecs.
                        await self._ensure_schema(conn)
                        await register_vector(conn)
                except Exception:
                    # Ensure we don't leave a half-initialized pool around.
                    await pool.close()
                    raise
                _POOLS_BY_DSN[dsn] = pool

            self._pool = pool

        # Cache extension presence for this client instance (best-effort).
        try:
            self._pg_search_available = await self._detect_pg_search()
        except Exception:
            self._pg_search_available = False

    async def disconnect(self) -> None:
        # NOTE: Pools are shared per DSN. We intentionally do not close the
        # process-wide pool on per-instance disconnect; many request paths call
        # disconnect() and closing would destroy the performance benefit.
        if self._pool is None:
            return
        self._pool = None
        self._resolved_dsn = None

    @classmethod
    async def close_shared_pools(cls) -> None:
        """Close all shared pools (best-effort).

        Intended for tests/shutdown hooks. Production request paths should not
        call this.
        """
        for dsn, pool in list(_POOLS_BY_DSN.items()):
            try:
                await pool.close()
            except Exception:
                pass
        _POOLS_BY_DSN.clear()
        _POOL_LOCKS_BY_DSN.clear()

    @staticmethod
    def _resolve_dsn(connection_string: str) -> str:
        """Resolve a connection string, preferring env vars when available."""
        env_dsn = os.getenv("POSTGRES_DSN")
        if env_dsn:
            return env_dsn

        host = os.getenv("POSTGRES_HOST")
        if host:
            port = int(os.getenv("POSTGRES_PORT", "5432"))
            db = os.getenv("POSTGRES_DB", "tribrid_rag")
            user = os.getenv("POSTGRES_USER", "postgres")
            password = os.getenv("POSTGRES_PASSWORD", "postgres")
            return f"postgresql://{user}:{password}@{host}:{port}/{db}"

        return connection_string

    async def _ensure_schema(self, conn: asyncpg.Connection) -> None:
        # Ensure pgvector extension
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        # Best-effort: ParadeDB pg_search extension (BM25). If unavailable, we fall back to built-in FTS.
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_search;")
        except Exception:
            pass

        # Corpus registry (repo_id == corpus_id)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS corpora (
              repo_id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              root_path TEXT NOT NULL,
              description TEXT,
              meta JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              last_indexed TIMESTAMPTZ,
              embedding_provider TEXT,
              embedding_model TEXT,
              embedding_dimensions INT
            );
            """
        )
        # Ensure new columns exist when upgrading an existing DB
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;")
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS embedding_provider TEXT;")

        # Per-corpus config (TriBridConfig JSON)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS corpus_configs (
              repo_id TEXT PRIMARY KEY REFERENCES corpora(repo_id) ON DELETE CASCADE,
              config JSONB NOT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )

        # Chunk store
        #
        # pgvector supports both dimensioned and (in newer versions) undimensioned vector columns.
        # Prefer undimensioned to support per-corpus embedding dims; fall back to a fixed dim when
        # running against older pgvector versions that require an explicit dimension.
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                  repo_id TEXT NOT NULL REFERENCES corpora(repo_id) ON DELETE CASCADE,
                  chunk_id TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  start_line INT NOT NULL,
                  end_line INT NOT NULL,
                  language TEXT,
                  content TEXT NOT NULL,
                  token_count INT NOT NULL DEFAULT 0,
                  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                  embedding vector,
                  tsv tsvector,
                  PRIMARY KEY (repo_id, chunk_id)
                );
                """
            )
        except Exception:
            # Fallback: fixed dimension (matches THE LAW embedding.embedding_dim).
            # NOTE: This fallback is only needed on older pgvector versions that require
            # an explicit vector dimension in the schema.
            try:
                from server.config import load_config as _load_global_config

                dim = int(_load_global_config().embedding.embedding_dim)
            except Exception:
                from server.models.tribrid_config_model import TriBridConfig

                dim = int(TriBridConfig().embedding.embedding_dim)
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunks (
                  repo_id TEXT NOT NULL REFERENCES corpora(repo_id) ON DELETE CASCADE,
                  chunk_id TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  start_line INT NOT NULL,
                  end_line INT NOT NULL,
                  language TEXT,
                  content TEXT NOT NULL,
                  token_count INT NOT NULL DEFAULT 0,
                  metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                  embedding vector({dim}),
                  tsv tsvector,
                  PRIMARY KEY (repo_id, chunk_id)
                );
                """
            )

        # Schema upgrade: chat requires arbitrary chunk metadata (JSONB).
        # Must run every boot; idempotent for existing installs.
        await conn.execute(
            "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;"
        )

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_repo_file ON chunks (repo_id, file_path);"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);")

        # Optional recall-only HNSW index for low-latency Recall vector search.
        # Best-effort: do not block startup if the pgvector build lacks HNSW support.
        try:
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_recall_embedding_hnsw
                  ON chunks USING hnsw (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64)
                  WHERE repo_id = 'recall_default' AND embedding IS NOT NULL;
                """
            )
        except Exception:
            pass

        # Optional BM25 index via ParadeDB pg_search.
        #
        # Best-effort: do not block startup if pg_search is not installed or not preload-enabled.
        # Use a globally-unique key_field to avoid cross-corpus key collisions.
        try:
            await conn.execute(
                """
                ALTER TABLE chunks
                ADD COLUMN IF NOT EXISTS bm25_id TEXT
                GENERATED ALWAYS AS (repo_id || '::' || chunk_id) STORED;
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_bm25
                  ON chunks
                  USING bm25 (bm25_id, repo_id, content, file_path)
                  WITH (key_field='bm25_id');
                """
            )
        except Exception:
            pass

        # Chunk summaries (data quality layer)
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunk_summaries (
              repo_id TEXT NOT NULL REFERENCES corpora(repo_id) ON DELETE CASCADE,
              chunk_id TEXT NOT NULL,
              file_path TEXT NOT NULL,
              start_line INT,
              end_line INT,
              purpose TEXT,
              symbols JSONB NOT NULL DEFAULT '[]'::jsonb,
              technical_details TEXT,
              domain_concepts JSONB NOT NULL DEFAULT '[]'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (repo_id, chunk_id)
            );
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunk_summaries_repo_file ON chunk_summaries (repo_id, file_path, start_line);"
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chunk_summaries_last_build (
              repo_id TEXT PRIMARY KEY REFERENCES corpora(repo_id) ON DELETE CASCADE,
              timestamp TIMESTAMPTZ NOT NULL,
              total INT NOT NULL,
              enriched INT NOT NULL
            );
            """
        )

    async def _detect_pg_search(self) -> bool:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 AS ok FROM pg_extension WHERE extname = 'pg_search' LIMIT 1;"
            )
        return bool(row is not None)

    async def pg_search_available(self) -> bool:
        if self._pg_search_available is None:
            try:
                self._pg_search_available = await self._detect_pg_search()
            except Exception:
                self._pg_search_available = False
        return bool(self._pg_search_available)

    async def bm25_search_pg_search(
        self,
        repo_id: str,
        query: str,
        top_k: int,
        *,
        query_mode: str = "plain",
    ) -> list[ChunkMatch]:
        """BM25 search using ParadeDB pg_search (@@@ operator + paradedb.score).

        Falls back by raising on missing extension; caller should handle.
        """
        if not query.strip() or top_k <= 0:
            return []
        await self._require_pool()
        assert self._pool is not None

        qm = str(query_mode or "plain").strip().lower()
        q = query.strip()
        if qm == "phrase":
            # Ensure the entire query is treated as a phrase.
            if not (q.startswith('"') and q.endswith('"')):
                q = f"\"{q}\""

        if not await self.pg_search_available():
            raise RuntimeError("pg_search extension not available")

        async with self._pool.acquire() as conn:
            # Ensure the key + index exist (idempotent, best-effort).
            try:
                await conn.execute(
                    """
                    ALTER TABLE chunks
                    ADD COLUMN IF NOT EXISTS bm25_id TEXT
                    GENERATED ALWAYS AS (repo_id || '::' || chunk_id) STORED;
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chunks_bm25
                      ON chunks
                      USING bm25 (bm25_id, repo_id, content, file_path)
                      WITH (key_field='bm25_id');
                    """
                )
            except Exception:
                pass

            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language, metadata,
                       paradedb.score(bm25_id)::float8 AS score
                FROM chunks
                WHERE repo_id = $2 AND chunks @@@ $1
                ORDER BY score DESC
                LIMIT $3;
                """,
                q,
                repo_id,
                int(top_k),
            )

        return [
            ChunkMatch(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                score=float(r["score"] or 0.0),
                source="sparse",
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    # Vector operations
    async def upsert_embeddings(self, repo_id: str, chunks: list[Chunk]) -> int:
        if not chunks:
            return 0
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await register_vector(conn)
            await self._ensure_corpus_row(conn, repo_id, name=repo_id, root_path=".")

            stmt = """
            INSERT INTO chunks (
              repo_id, chunk_id, file_path, start_line, end_line, language, content, token_count, metadata, embedding
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10)
            ON CONFLICT (repo_id, chunk_id) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              start_line = EXCLUDED.start_line,
              end_line = EXCLUDED.end_line,
              language = EXCLUDED.language,
              content = EXCLUDED.content,
              token_count = EXCLUDED.token_count,
              metadata = EXCLUDED.metadata,
              embedding = EXCLUDED.embedding;
            """

            await conn.executemany(
                stmt,
                [
                    (
                        repo_id,
                        ch.chunk_id,
                        ch.file_path,
                        int(ch.start_line),
                        int(ch.end_line),
                        ch.language,
                        ch.content,
                        int(ch.token_count or 0),
                        json.dumps(ch.metadata or {}),
                        ch.embedding,
                    )
                    for ch in chunks
                ],
            )
            await conn.execute(
                "UPDATE corpora SET last_indexed = $2 WHERE repo_id = $1;",
                repo_id,
                datetime.now(UTC),
            )
        return len(chunks)

    async def vector_search(self, repo_id: str, embedding: list[float], top_k: int) -> list[ChunkMatch]:
        if top_k <= 0:
            return []
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await register_vector(conn)
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language, metadata,
                       (1 - (embedding <=> $1))::float8 AS score
                FROM chunks
                WHERE repo_id = $2 AND embedding IS NOT NULL
                ORDER BY embedding <=> $1
                LIMIT $3;
                """,
                embedding,
                repo_id,
                int(top_k),
            )

        return [
            ChunkMatch(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                score=float(r["score"] or 0.0),
                source="vector",
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    async def delete_embeddings(self, repo_id: str) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE chunks SET embedding = NULL WHERE repo_id = $1 AND embedding IS NOT NULL;",
                repo_id,
            )
        # asyncpg returns "UPDATE <n>"
        return int(result.split()[-1])

    # FTS operations
    async def upsert_fts(self, repo_id: str, chunks: list[Chunk], *, ts_config: str) -> int:
        if not chunks:
            return 0
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await self._ensure_corpus_row(conn, repo_id, name=repo_id, root_path=".")
            # Update tsv for each chunk (ensure row exists first)
            stmt = """
            INSERT INTO chunks (
              repo_id, chunk_id, file_path, start_line, end_line, language, content, token_count, metadata, tsv
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,to_tsvector($10::regconfig, $7))
            ON CONFLICT (repo_id, chunk_id) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              start_line = EXCLUDED.start_line,
              end_line = EXCLUDED.end_line,
              language = EXCLUDED.language,
              content = EXCLUDED.content,
              token_count = EXCLUDED.token_count,
              metadata = EXCLUDED.metadata,
              tsv = to_tsvector($10::regconfig, EXCLUDED.content);
            """
            await conn.executemany(
                stmt,
                [
                    (
                        repo_id,
                        ch.chunk_id,
                        ch.file_path,
                        int(ch.start_line),
                        int(ch.end_line),
                        ch.language,
                        ch.content,
                        int(ch.token_count or 0),
                        json.dumps(ch.metadata or {}),
                        ts_config,
                    )
                    for ch in chunks
                ],
            )
            await conn.execute(
                "UPDATE corpora SET last_indexed = $2 WHERE repo_id = $1;",
                repo_id,
                datetime.now(UTC),
            )
        return len(chunks)

    async def sparse_search(self, repo_id: str, query: str, top_k: int, *, ts_config: str) -> list[ChunkMatch]:
        """Back-compat sparse search (postgres_fts + plainto_tsquery)."""
        return await self.fts_search(repo_id, query, top_k, ts_config=ts_config, query_mode="plain")

    async def fts_search(
        self,
        repo_id: str,
        query: str,
        top_k: int,
        *,
        ts_config: str,
        query_mode: str = "plain",
    ) -> list[ChunkMatch]:
        if not query.strip() or top_k <= 0:
            return []
        await self._require_pool()
        assert self._pool is not None

        qm = str(query_mode or "plain").strip().lower()
        if qm == "phrase":
            tsquery = "phraseto_tsquery($4::regconfig, $1)"
        elif qm == "boolean":
            tsquery = "websearch_to_tsquery($4::regconfig, $1)"
        else:
            tsquery = "plainto_tsquery($4::regconfig, $1)"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT chunk_id, content, file_path, start_line, end_line, language, metadata,
                       ts_rank_cd(tsv, {tsquery})::float8 AS score
                FROM chunks
                WHERE repo_id = $2 AND tsv @@ {tsquery}
                ORDER BY score DESC
                LIMIT $3;
                """,
                query,
                repo_id,
                int(top_k),
                ts_config,
            )

        return [
            ChunkMatch(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                score=float(r["score"] or 0.0),
                source="sparse",
                metadata={**_coerce_jsonb_dict(r.get("metadata")), "sparse_engine": "postgres_fts"},
            )
            for r in rows
        ]

    async def fts_search_relaxed_or(
        self,
        repo_id: str,
        query: str,
        top_k: int,
        *,
        ts_config: str,
        max_terms: int,
    ) -> list[ChunkMatch]:
        if not query.strip() or top_k <= 0:
            return []
        max_terms = int(max_terms)
        if max_terms <= 0:
            return []

        terms = _extract_relaxed_fts_terms(query, max_terms=max_terms)
        if not terms:
            return []
        tsquery_text = " | ".join(f"{t}:*" for t in terms)

        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language, metadata,
                       ts_rank_cd(tsv, to_tsquery($4::regconfig, $1))::float8 AS score
                FROM chunks
                WHERE repo_id = $2 AND tsv @@ to_tsquery($4::regconfig, $1)
                ORDER BY score DESC
                LIMIT $3;
                """,
                tsquery_text,
                repo_id,
                int(top_k),
                ts_config,
            )

        return [
            ChunkMatch(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                score=float(r["score"] or 0.0),
                source="sparse",
                metadata={
                    **_coerce_jsonb_dict(r.get("metadata")),
                    "sparse_engine": "postgres_fts_relaxed_or",
                    "sparse_relaxed": True,
                },
            )
            for r in rows
        ]

    async def file_path_search(self, repo_id: str, query: str, top_k: int, *, max_terms: int) -> list[ChunkMatch]:
        if not query.strip() or top_k <= 0:
            return []
        max_terms = int(max_terms)
        if max_terms <= 0:
            return []

        terms = _extract_file_path_terms(query, max_terms=max_terms)
        if not terms:
            return []

        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH terms(term) AS (
                  SELECT unnest($2::text[])
                ),
                matches AS (
                  SELECT c.chunk_id, c.content, c.file_path, c.start_line, c.end_line, c.language, c.metadata,
                         COUNT(DISTINCT t.term)::int AS match_count
                  FROM chunks c
                  JOIN terms t
                    ON c.file_path ILIKE '%' || t.term || '%'
                  WHERE c.repo_id = $1
                  GROUP BY c.chunk_id, c.content, c.file_path, c.start_line, c.end_line, c.language, c.metadata
                )
                SELECT chunk_id, content, file_path, start_line, end_line, language, metadata,
                       match_count::float8 AS score
                FROM matches
                ORDER BY match_count DESC, file_path ASC
                LIMIT $3;
                """,
                repo_id,
                list(terms),
                int(top_k),
            )

        return [
            ChunkMatch(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                score=float(r["score"] or 0.0),
                source="sparse",
                metadata={**_coerce_jsonb_dict(r.get("metadata")), "sparse_engine": "file_path"},
            )
            for r in rows
        ]

    async def sparse_search_engine(
        self,
        repo_id: str,
        query: str,
        top_k: int,
        *,
        ts_config: str,
        engine: str,
        query_mode: str = "plain",
        highlight: bool = False,
        relax_on_empty: bool = True,
        relax_max_terms: int = 8,
    ) -> list[ChunkMatch]:
        eng = str(engine or "postgres_fts").strip().lower()
        qm = str(query_mode or "plain").strip().lower()
        if eng == "pg_search_bm25":
            try:
                rows = await self.bm25_search_pg_search(repo_id, query, top_k, query_mode=qm)
                # Tag engine in metadata for UI/debug.
                results = [
                    r.model_copy(update={"metadata": {**(r.metadata or {}), "sparse_engine": "pg_search_bm25"}})
                    for r in rows
                ]
            except Exception:
                # Clean fallback.
                results = await self.fts_search(repo_id, query, top_k, ts_config=ts_config, query_mode=qm)
        else:
            results = await self.fts_search(repo_id, query, top_k, ts_config=ts_config, query_mode=qm)

        _ = highlight
        if results:
            return results
        if not bool(relax_on_empty):
            return results
        return await self.fts_search_relaxed_or(
            repo_id, query, top_k, ts_config=ts_config, max_terms=int(relax_max_terms)
        )

    async def delete_fts(self, repo_id: str) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE chunks SET tsv = NULL WHERE repo_id = $1 AND tsv IS NOT NULL;",
                repo_id,
            )
        return int(result.split()[-1])

    async def vocab_preview(self, repo_id: str, top_n: int) -> tuple[list[VocabPreviewTerm], int]:
        """Return top terms (by doc frequency) from the FTS vocabulary for a corpus.

        NOTE: This reads from `chunks.tsv`, which is the source of truth for sparse retrieval.
        """
        top_n = int(top_n)
        if top_n <= 0:
            return ([], 0)
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH per_term AS (
                  SELECT term, COUNT(*)::int AS doc_count
                  FROM (
                    SELECT DISTINCT chunk_id, unnest(tsvector_to_array(tsv)) AS term
                    FROM chunks
                    WHERE repo_id = $1 AND tsv IS NOT NULL
                  ) t
                  GROUP BY term
                )
                SELECT term, doc_count, COUNT(*) OVER ()::int AS total_terms
                FROM per_term
                ORDER BY doc_count DESC, term ASC
                LIMIT $2;
                """,
                repo_id,
                top_n,
            )

        if not rows:
            return ([], 0)

        total_terms = int(rows[0]["total_terms"] or 0)
        terms = [
            VocabPreviewTerm(term=str(r["term"]), doc_count=int(r["doc_count"] or 0))
            for r in rows
        ]
        return (terms, total_terms)

    # Metadata
    async def get_chunk(self, repo_id: str, chunk_id: str) -> Chunk | None:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT repo_id, chunk_id, content, file_path, start_line, end_line, language, token_count, metadata
                FROM chunks
                WHERE repo_id = $1
                  AND chunk_id = $2
                LIMIT 1;
                """,
                repo_id,
                chunk_id,
            )
        if not row:
            return None
        return Chunk(
            chunk_id=str(row["chunk_id"]),
            content=str(row["content"]),
            file_path=str(row["file_path"]),
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            language=str(row["language"]) if row["language"] is not None else None,
            token_count=int(row["token_count"] or 0),
            embedding=None,
            summary=None,
            metadata=_coerce_jsonb_dict(row.get("metadata")),
        )

    async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.chunk_id, c.content, c.file_path, c.start_line, c.end_line, c.language, c.token_count, c.metadata
                FROM unnest($2::text[]) WITH ORDINALITY AS u(chunk_id, ord)
                JOIN chunks c
                  ON c.repo_id = $1
                 AND c.chunk_id = u.chunk_id
                ORDER BY u.ord ASC;
                """,
                repo_id,
                chunk_ids,
            )
        return [
            Chunk(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                token_count=int(r["token_count"] or 0),
                embedding=None,
                summary=None,
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    async def get_embeddings(self, repo_id: str, chunk_ids: list[str]) -> dict[str, list[float]]:
        """Fetch dense embeddings for a list of chunk_ids (best-effort).

        Returns a mapping of chunk_id -> embedding vector. Missing/null embeddings are omitted.
        """
        if not chunk_ids:
            return {}
        await self._require_pool()
        assert self._pool is not None

        # De-dupe while preserving order for predictable query size.
        ids = list(dict.fromkeys([str(cid) for cid in chunk_ids if str(cid).strip()]))
        if not ids:
            return {}

        async with self._pool.acquire() as conn:
            # Ensure pgvector codecs are registered for this connection (idempotent).
            try:
                await register_vector(conn)
            except Exception:
                pass

            rows = await conn.fetch(
                """
                SELECT c.chunk_id, c.embedding
                FROM unnest($2::text[]) AS u(chunk_id)
                JOIN chunks c
                  ON c.repo_id = $1
                 AND c.chunk_id = u.chunk_id
                WHERE c.embedding IS NOT NULL;
                """,
                repo_id,
                ids,
            )

        out: dict[str, list[float]] = {}
        for r in rows:
            cid = str(r["chunk_id"])
            emb = r["embedding"]
            if emb is None:
                continue
            try:
                # pgvector may decode to list[float] or a Vector wrapper.
                out[cid] = [float(x) for x in list(emb)]
            except Exception:
                try:
                    out[cid] = [float(x) for x in emb]
                except Exception:
                    continue
        return out

    async def get_chunks_by_file_ordinals(self, repo_id: str, file_path: str, ordinals: list[int]) -> list[Chunk]:
        """Fetch chunks for a file by chunk_ordinal (stored in metadata)."""
        if not ordinals:
            return []
        await self._require_pool()
        assert self._pool is not None

        ords = sorted({int(o) for o in ordinals if int(o) >= 0})
        if not ords:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata
                FROM chunks
                WHERE repo_id = $1
                  AND file_path = $2
                  AND (NULLIF((metadata->>'chunk_ordinal'), '')::int) = ANY($3::int[])
                ORDER BY (NULLIF((metadata->>'chunk_ordinal'), '')::int) ASC, start_line ASC, chunk_id ASC;
                """,
                repo_id,
                file_path,
                ords,
            )

        return [
            Chunk(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                token_count=int(r["token_count"] or 0),
                embedding=None,
                summary=None,
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    async def get_index_stats(self, repo_id: str) -> IndexStats:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            corpus = await conn.fetchrow(
                """
                SELECT repo_id, embedding_provider, embedding_model, embedding_dimensions, last_indexed
                FROM corpora
                WHERE repo_id = $1;
                """,
                repo_id,
            )
            if not corpus:
                return IndexStats(
                    repo_id=repo_id,
                    total_files=0,
                    total_chunks=0,
                    total_tokens=0,
                    embedding_provider="",
                    embedding_model="",
                    embedding_dimensions=0,
                    last_indexed=None,
                    file_breakdown={},
                )

            agg = await conn.fetchrow(
                """
                SELECT COUNT(*)::int AS total_chunks,
                       COALESCE(SUM(token_count), 0)::bigint AS total_tokens
                FROM chunks
                WHERE repo_id = $1;
                """,
                repo_id,
            )

            file_rows = await conn.fetch(
                "SELECT DISTINCT file_path FROM chunks WHERE repo_id = $1;",
                repo_id,
            )

        files = [str(r["file_path"]) for r in file_rows]
        breakdown: dict[str, int] = defaultdict(int)
        for fp in files:
            ext = "." + fp.split(".")[-1] if "." in fp else ""
            breakdown[ext] += 1

        return IndexStats(
            repo_id=repo_id,
            total_files=len(files),
            total_chunks=int(agg["total_chunks"] or 0),
            total_tokens=int(agg["total_tokens"] or 0),
            embedding_provider=str(corpus["embedding_provider"] or ""),
            embedding_model=str(corpus["embedding_model"] or ""),
            embedding_dimensions=int(corpus["embedding_dimensions"] or 0),
            last_indexed=corpus["last_indexed"],
            file_breakdown=dict(breakdown),
        )

    # ---------------------------------------------------------------------
    # Dashboard storage metrics (bytes)
    # ---------------------------------------------------------------------

    _dashboard_storage_cache: dict[str, tuple[float, dict[str, int]]] = {}
    _dashboard_storage_ttl_s: float = 30.0

    async def get_dashboard_storage_breakdown(self, repo_id: str) -> dict[str, int]:
        """Return a dashboard-oriented storage breakdown for a corpus (bytes).

        The Dashboard polls frequently; keep this best-effort and cached.
        """
        repo_id = (repo_id or "").strip()
        if not repo_id:
            return {
                "chunks_bytes": 0,
                "embeddings_bytes": 0,
                "pgvector_index_bytes": 0,
                "bm25_index_bytes": 0,
                "chunk_summaries_bytes": 0,
            }

        now = time.time()
        cached = self._dashboard_storage_cache.get(repo_id)
        if cached is not None:
            ts, payload = cached
            if now - ts <= float(self._dashboard_storage_ttl_s):
                return dict(payload)

        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            # Chunks table: estimate corpus-scoped storage for core columns.
            # We intentionally split out tsv (BM25) and embedding (dense) so the UI can
            # present them as separate components.
            chunks_row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*)::bigint AS chunk_rows,
                  COALESCE(SUM(
                    pg_column_size(chunk_id)
                    + pg_column_size(file_path)
                    + pg_column_size(start_line)
                    + pg_column_size(end_line)
                    + pg_column_size(language)
                    + pg_column_size(token_count)
                    + pg_column_size(content)
                    + pg_column_size(metadata)
                  ), 0)::bigint AS chunks_bytes,
                  COUNT(*) FILTER (WHERE embedding IS NOT NULL)::bigint AS embedding_rows,
                  COALESCE(SUM(pg_column_size(embedding)), 0)::bigint AS embeddings_bytes,
                  COUNT(*) FILTER (WHERE tsv IS NOT NULL)::bigint AS tsv_rows,
                  COALESCE(SUM(pg_column_size(tsv)), 0)::bigint AS tsv_bytes
                FROM chunks
                WHERE repo_id = $1;
                """,
                repo_id,
            )

            chunks_bytes = int(chunks_row["chunks_bytes"] or 0) if chunks_row else 0
            embeddings_bytes = int(chunks_row["embeddings_bytes"] or 0) if chunks_row else 0
            embedding_rows = int(chunks_row["embedding_rows"] or 0) if chunks_row else 0
            tsv_rows = int(chunks_row["tsv_rows"] or 0) if chunks_row else 0
            tsv_bytes = int(chunks_row["tsv_bytes"] or 0) if chunks_row else 0

            # Chunk summaries table: corpus-scoped bytes.
            summaries_row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(
                    pg_column_size(chunk_id)
                    + pg_column_size(file_path)
                    + pg_column_size(start_line)
                    + pg_column_size(end_line)
                    + pg_column_size(purpose)
                    + pg_column_size(symbols)
                    + pg_column_size(technical_details)
                    + pg_column_size(domain_concepts)
                  ), 0)::bigint AS chunk_summaries_bytes
                FROM chunk_summaries
                WHERE repo_id = $1;
                """,
                repo_id,
            )
            chunk_summaries_bytes = int(summaries_row["chunk_summaries_bytes"] or 0) if summaries_row else 0

            # Global counts for index allocation (shared indexes cannot be attributed directly per corpus).
            totals_row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) FILTER (WHERE embedding IS NOT NULL)::bigint AS embedding_rows_all,
                  COUNT(*) FILTER (WHERE tsv IS NOT NULL)::bigint AS tsv_rows_all
                FROM chunks;
                """
            )
            embedding_rows_all = int(totals_row["embedding_rows_all"] or 0) if totals_row else 0
            tsv_rows_all = int(totals_row["tsv_rows_all"] or 0) if totals_row else 0

            # GIN FTS index size (shared). Allocate proportional to tsv rows.
            gin_row = await conn.fetchrow(
                """
                SELECT COALESCE(pg_relation_size(c.oid), 0)::bigint AS bytes
                FROM pg_class c
                WHERE c.relname = 'idx_chunks_tsv'
                LIMIT 1;
                """
            )
            gin_total = int(gin_row["bytes"] or 0) if gin_row else 0
            gin_alloc = 0
            if gin_total > 0 and tsv_rows_all > 0 and tsv_rows > 0:
                gin_alloc = int(round((gin_total * float(tsv_rows)) / float(tsv_rows_all)))

            # Optional BM25 index size (pg_search). Allocate proportional to chunk rows.
            bm25_row = await conn.fetchrow(
                """
                SELECT COALESCE(pg_relation_size(c.oid), 0)::bigint AS bytes
                FROM pg_class c
                WHERE c.relname = 'idx_chunks_bm25'
                LIMIT 1;
                """
            )
            bm25_total = int(bm25_row["bytes"] or 0) if bm25_row else 0
            bm25_alloc = 0
            chunk_rows = int(chunks_row["chunk_rows"] or 0) if chunks_row else 0
            totals_all = await conn.fetchrow("SELECT COUNT(*)::bigint AS n FROM chunks;")
            chunk_rows_all = int(totals_all["n"] or 0) if totals_all else 0
            if bm25_total > 0 and chunk_rows_all > 0 and chunk_rows > 0:
                bm25_alloc = int(round((bm25_total * float(chunk_rows)) / float(chunk_rows_all)))

            # Vector index size (if present). Allocate proportional to embedding rows.
            vec_idx_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(pg_relation_size(i.indexrelid)), 0)::bigint AS bytes
                FROM pg_index i
                JOIN pg_class t ON t.oid = i.indrelid
                WHERE t.relname = 'chunks'
                  AND pg_get_indexdef(i.indexrelid) ILIKE '%embedding%';
                """
            )
            vec_idx_total = int(vec_idx_row["bytes"] or 0) if vec_idx_row else 0
            vec_idx_alloc = 0
            if vec_idx_total > 0 and embedding_rows_all > 0 and embedding_rows > 0:
                vec_idx_alloc = int(round((vec_idx_total * float(embedding_rows)) / float(embedding_rows_all)))

        # Prefer pg_search BM25 index allocation when present; otherwise fall back to FTS storage estimate.
        bm25_index_bytes = int(bm25_alloc) if int(bm25_alloc) > 0 else int(tsv_bytes + gin_alloc)
        out = {
            "chunks_bytes": int(chunks_bytes),
            "embeddings_bytes": int(embeddings_bytes),
            "pgvector_index_bytes": int(vec_idx_alloc),
            "bm25_index_bytes": int(bm25_index_bytes),
            "chunk_summaries_bytes": int(chunk_summaries_bytes),
        }
        self._dashboard_storage_cache[repo_id] = (now, out)
        return dict(out)

    # ---------------------------------------------------------------------
    # Corpus management (repo_id == corpus_id)
    # ---------------------------------------------------------------------

    async def list_corpora(self) -> list[dict[str, Any]]:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT repo_id, name, root_path, description, meta, created_at, last_indexed
                FROM corpora
                ORDER BY created_at DESC;
                """
            )
        return [
            {
                "repo_id": str(r["repo_id"]),
                "name": str(r["name"]),
                "path": str(r["root_path"]),
                "description": str(r["description"]) if r["description"] is not None else None,
                "meta": _coerce_jsonb_dict(r["meta"]),
                "created_at": r["created_at"],
                "last_indexed": r["last_indexed"],
            }
            for r in rows
        ]

    async def get_corpus(self, repo_id: str) -> dict[str, Any] | None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT repo_id, name, root_path, description, meta, created_at, last_indexed
                FROM corpora
                WHERE repo_id = $1;
                """,
                repo_id,
            )
        if not row:
            return None
        return {
            "repo_id": str(row["repo_id"]),
            "name": str(row["name"]),
            "path": str(row["root_path"]),
            "description": str(row["description"]) if row["description"] is not None else None,
            "meta": _coerce_jsonb_dict(row["meta"]),
            "created_at": row["created_at"],
            "last_indexed": row["last_indexed"],
        }

    async def upsert_corpus(
        self,
        repo_id: str,
        name: str,
        root_path: str,
        description: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await self._ensure_corpus_row(
                conn, repo_id, name=name, root_path=root_path, description=description, meta=meta
            )

    async def delete_corpus(self, repo_id: str) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM corpora WHERE repo_id = $1;", repo_id)

    async def get_corpus_config_json(self, repo_id: str) -> dict[str, Any] | None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT config FROM corpus_configs WHERE repo_id = $1;",
                repo_id,
            )
        if not row:
            return None
        cfg = row["config"]
        if isinstance(cfg, str):
            parsed = json.loads(cfg)
            if isinstance(parsed, dict):
                return cast(dict[str, Any], parsed)
            return None
        return cast(dict[str, Any], dict(cfg))

    async def upsert_corpus_config_json(self, repo_id: str, config: dict[str, Any]) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO corpus_configs (repo_id, config, updated_at)
                VALUES ($1, $2::jsonb, now())
                ON CONFLICT (repo_id) DO UPDATE SET
                  config = EXCLUDED.config,
                  updated_at = now();
                """,
                repo_id,
                json.dumps(config),
            )

    async def update_corpus_embedding_meta(self, repo_id: str, *, provider: str, model: str, dimensions: int) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE corpora
                SET embedding_provider = $2,
                    embedding_model = $3,
                    embedding_dimensions = $4
                WHERE repo_id = $1;
                """,
                repo_id,
                str(provider or ""),
                model,
                int(dimensions),
            )

    async def get_chunks_for_file_span(
        self, repo_id: str, file_path: str, start_line: int, end_line: int, limit: int = 5
    ) -> list[Chunk]:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata
                FROM chunks
                WHERE repo_id = $1
                  AND file_path = $2
                  AND NOT (end_line < $3 OR start_line > $4)
                ORDER BY start_line ASC
                LIMIT $5;
                """,
                repo_id,
                file_path,
                int(start_line),
                int(end_line),
                int(limit),
            )
        return [
            Chunk(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                token_count=int(r["token_count"] or 0),
                embedding=None,
                summary=None,
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    async def list_chunks_for_repo(self, repo_id: str, limit: int | None = None) -> list[Chunk]:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            if limit is None:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata
                    FROM chunks
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC;
                    """,
                    repo_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata
                    FROM chunks
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC
                    LIMIT $2;
                    """,
                    repo_id,
                    int(limit),
                )

        return [
            Chunk(
                chunk_id=str(r["chunk_id"]),
                content=str(r["content"]),
                file_path=str(r["file_path"]),
                start_line=int(r["start_line"]),
                end_line=int(r["end_line"]),
                language=str(r["language"]) if r["language"] is not None else None,
                token_count=int(r["token_count"] or 0),
                embedding=None,
                summary=None,
                metadata=_coerce_jsonb_dict(r.get("metadata")),
            )
            for r in rows
        ]

    async def list_chunk_summaries(self, repo_id: str, limit: int | None = None) -> list[ChunkSummary]:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if limit is None:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, file_path, start_line, end_line, purpose, symbols,
                           technical_details, domain_concepts
                    FROM chunk_summaries
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC;
                    """,
                    repo_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, file_path, start_line, end_line, purpose, symbols,
                           technical_details, domain_concepts
                    FROM chunk_summaries
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC
                    LIMIT $2;
                    """,
                    repo_id,
                    int(limit),
                )

        out: list[ChunkSummary] = []
        for r in rows:
            symbols = r.get("symbols") or []
            if isinstance(symbols, str):
                try:
                    symbols = json.loads(symbols)
                except Exception:
                    symbols = []
            domain_concepts = r.get("domain_concepts") or []
            if isinstance(domain_concepts, str):
                try:
                    domain_concepts = json.loads(domain_concepts)
                except Exception:
                    domain_concepts = []
            out.append(
                ChunkSummary(
                    chunk_id=str(r["chunk_id"]),
                    file_path=str(r["file_path"]),
                    start_line=int(r["start_line"]) if r["start_line"] is not None else None,
                    end_line=int(r["end_line"]) if r["end_line"] is not None else None,
                    purpose=str(r["purpose"]) if r["purpose"] is not None else None,
                    symbols=[str(x) for x in symbols] if isinstance(symbols, list) else [],
                    technical_details=str(r["technical_details"]) if r["technical_details"] is not None else None,
                    domain_concepts=[str(x) for x in domain_concepts] if isinstance(domain_concepts, list) else [],
                )
            )
        return out

    async def get_chunk_summaries_last_build(self, repo_id: str) -> ChunkSummariesLastBuild | None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT repo_id, timestamp, total, enriched
                FROM chunk_summaries_last_build
                WHERE repo_id = $1;
                """,
                repo_id,
            )
        if not row:
            return None
        return ChunkSummariesLastBuild(
            repo_id=str(row["repo_id"]),
            timestamp=row["timestamp"],
            total=int(row["total"] or 0),
            enriched=int(row["enriched"] or 0),
        )

    async def replace_chunk_summaries(
        self, repo_id: str, summaries: list[ChunkSummary], last_build: ChunkSummariesLastBuild
    ) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await self._ensure_corpus_row(conn, repo_id, name=repo_id, root_path=".")
            async with conn.transaction():
                await conn.execute("DELETE FROM chunk_summaries WHERE repo_id = $1;", repo_id)

                if summaries:
                    await conn.executemany(
                        """
                        INSERT INTO chunk_summaries (
                          repo_id, chunk_id, file_path, start_line, end_line,
                          purpose, symbols, technical_details, domain_concepts
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9::jsonb);
                        """,
                        [
                            (
                                repo_id,
                                s.chunk_id,
                                s.file_path,
                                int(s.start_line) if s.start_line is not None else None,
                                int(s.end_line) if s.end_line is not None else None,
                                s.purpose,
                                json.dumps(list(s.symbols or [])),
                                s.technical_details,
                                json.dumps(list(s.domain_concepts or [])),
                            )
                            for s in summaries
                        ],
                    )

                await conn.execute(
                    """
                    INSERT INTO chunk_summaries_last_build (repo_id, timestamp, total, enriched)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (repo_id) DO UPDATE SET
                      timestamp = EXCLUDED.timestamp,
                      total = EXCLUDED.total,
                      enriched = EXCLUDED.enriched;
                    """,
                    repo_id,
                    last_build.timestamp,
                    int(last_build.total),
                    int(last_build.enriched),
                )

    async def delete_chunk_summary(self, chunk_id: str, corpus_id: str | None = None) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if corpus_id:
                result = await conn.execute(
                    "DELETE FROM chunk_summaries WHERE repo_id = $1 AND chunk_id = $2;",
                    corpus_id,
                    chunk_id,
                )
            else:
                result = await conn.execute("DELETE FROM chunk_summaries WHERE chunk_id = $1;", chunk_id)
        return int(result.split()[-1])

    async def update_corpus_meta(self, repo_id: str, meta: dict[str, Any]) -> None:
        await self._require_pool()
        assert self._pool is not None
        meta_json = json.dumps(meta or {})
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE corpora
                SET meta = corpora.meta || $2::jsonb
                WHERE repo_id = $1;
                """,
                repo_id,
                meta_json,
            )

    async def update_corpus(
        self,
        repo_id: str,
        *,
        name: str | None = None,
        path: str | None = None,
        meta_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Update corpus fields. Returns updated row or None if not found."""
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            # Build dynamic SET clause
            updates: list[str] = []
            args: list[Any] = [repo_id]
            idx = 2

            if name is not None:
                updates.append(f"name = ${idx}")
                args.append(name)
                idx += 1

            if path is not None:
                updates.append(f"root_path = ${idx}")
                args.append(path)
                idx += 1

            if meta_updates:
                updates.append(f"meta = corpora.meta || ${idx}::jsonb")
                args.append(json.dumps(meta_updates))
                idx += 1

            if not updates:
                # Nothing to update, just return current row
                return await self.get_corpus(repo_id)

            query = f"""
                UPDATE corpora
                SET {', '.join(updates)}
                WHERE repo_id = $1
                RETURNING *;
            """
            row = await conn.fetchrow(query, *args)
            if not row:
                return None
            out = dict(row)
            out["meta"] = _coerce_jsonb_dict(out.get("meta"))
            return out

    async def delete_chunks(self, repo_id: str) -> int:
        """Hard-delete all chunks for a corpus (used for force_reindex)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM chunks WHERE repo_id = $1;", repo_id)
        return int(result.split()[-1])

    async def _ensure_corpus_row(
        self,
        conn: asyncpg.Connection,
        repo_id: str,
        *,
        name: str,
        root_path: str,
        description: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        meta_json = json.dumps(meta or {})
        await conn.execute(
            """
            INSERT INTO corpora (repo_id, name, root_path, description, meta)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (repo_id) DO UPDATE SET
              name = EXCLUDED.name,
              root_path = CASE
                WHEN EXCLUDED.root_path IS NULL OR EXCLUDED.root_path = '' OR EXCLUDED.root_path = '.'
                  THEN corpora.root_path
                ELSE EXCLUDED.root_path
              END,
              description = EXCLUDED.description,
              meta = corpora.meta || EXCLUDED.meta;
            """,
            repo_id,
            name,
            root_path,
            description,
            meta_json,
        )

    async def _require_pool(self) -> None:
        if self._pool is None:
            await self.connect()
