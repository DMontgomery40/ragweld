from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any, cast

import asyncpg
from pgvector.asyncpg import register_vector

from server.models.index import Chunk, IndexStats
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import ChunkSummariesLastBuild, ChunkSummary, VocabPreviewTerm


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

    # ---------------------------------------------------------------------
    # Connection + schema
    # ---------------------------------------------------------------------

    async def connect(self) -> None:
        if self._pool is not None:
            return

        dsn = self._resolve_dsn(self.connection_string)
        self._pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)

        async with self._pool.acquire() as conn:
            # Ensure extension exists before registering pgvector codecs.
            await self._ensure_schema(conn)
            await register_vector(conn)

    async def disconnect(self) -> None:
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

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
              embedding_model TEXT,
              embedding_dimensions INT
            );
            """
        )
        # Ensure new columns exist when upgrading an existing DB
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;")

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
                  embedding vector,
                  tsv tsvector,
                  PRIMARY KEY (repo_id, chunk_id)
                );
                """
            )
        except Exception:
            # Fallback: fixed dimension (matches LAW default, can be overridden via TRIBRID_EMBEDDING_DIM)
            dim = int(os.getenv("TRIBRID_EMBEDDING_DIM", "3072"))
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
                  embedding vector({dim}),
                  tsv tsvector,
                  PRIMARY KEY (repo_id, chunk_id)
                );
                """
            )

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_repo_file ON chunks (repo_id, file_path);"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING GIN (tsv);")
        # Optional vector index (HNSW preferred on newer pgvector; keep minimal here).
        # Index creation can be expensive; create lazily in a later iteration.

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
              repo_id, chunk_id, file_path, start_line, end_line, language, content, token_count, embedding
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (repo_id, chunk_id) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              start_line = EXCLUDED.start_line,
              end_line = EXCLUDED.end_line,
              language = EXCLUDED.language,
              content = EXCLUDED.content,
              token_count = EXCLUDED.token_count,
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
                SELECT chunk_id, content, file_path, start_line, end_line, language,
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
                metadata={},
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
              repo_id, chunk_id, file_path, start_line, end_line, language, content, token_count, tsv
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,to_tsvector($9::regconfig, $7))
            ON CONFLICT (repo_id, chunk_id) DO UPDATE SET
              file_path = EXCLUDED.file_path,
              start_line = EXCLUDED.start_line,
              end_line = EXCLUDED.end_line,
              language = EXCLUDED.language,
              content = EXCLUDED.content,
              token_count = EXCLUDED.token_count,
              tsv = to_tsvector($9::regconfig, EXCLUDED.content);
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
        if not query.strip() or top_k <= 0:
            return []
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT chunk_id, content, file_path, start_line, end_line, language,
                       ts_rank_cd(tsv, plainto_tsquery($4::regconfig, $1))::float8 AS score
                FROM chunks
                WHERE repo_id = $2 AND tsv @@ plainto_tsquery($4::regconfig, $1)
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
                metadata={},
            )
            for r in rows
        ]

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
                SELECT repo_id, chunk_id, content, file_path, start_line, end_line, language, token_count
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
        )

    async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.chunk_id, c.content, c.file_path, c.start_line, c.end_line, c.language, c.token_count
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
            )
            for r in rows
        ]

    async def get_index_stats(self, repo_id: str) -> IndexStats:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            corpus = await conn.fetchrow(
                """
                SELECT repo_id, embedding_model, embedding_dimensions, last_indexed
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
            embedding_model=str(corpus["embedding_model"] or ""),
            embedding_dimensions=int(corpus["embedding_dimensions"] or 0),
            last_indexed=corpus["last_indexed"],
            file_breakdown=dict(breakdown),
        )

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

    async def update_corpus_embedding_meta(self, repo_id: str, model: str, dimensions: int) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE corpora
                SET embedding_model = $2,
                    embedding_dimensions = $3
                WHERE repo_id = $1;
                """,
                repo_id,
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
                SELECT chunk_id, content, file_path, start_line, end_line, language, token_count
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
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count
                    FROM chunks
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC;
                    """,
                    repo_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count
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
