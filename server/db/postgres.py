from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import asyncpg
from pgvector.asyncpg import register_vector

from server.models.index import (
    Chunk,
    ChunkProvenance,
    GraphGenerationMetadata,
    GraphSchemaProposal,
    IndexedDocumentRecord,
    IndexStats,
)
from server.models.tribrid_config_model import (
    ChunkSummariesLastBuild,
    ChunkSummary,
)

if TYPE_CHECKING:
    from server.indexing.generations import (
        DeletionTombstone,
        FenceClaim,
        GenerationManifest,
        IndexRunFence,
        ReclaimEntry,
        RetiredGeneration,
    )

# -----------------------------------------------------------------------------
# Shared asyncpg pool caching (process-wide)
#
# This codebase creates PostgresClient instances in multiple places (API routes,
# retrieval pipeline, config store). Creating a new asyncpg pool per instance is
# expensive (connect handshake + schema init). We keep one pool per DSN and reuse
# it across all PostgresClient instances.
# -----------------------------------------------------------------------------
_POOLS_BY_DSN: dict[tuple[str, str], asyncpg.Pool] = {}
_POOL_LOCKS_BY_DSN: dict[tuple[str, str], asyncio.Lock] = {}
_VECTOR_AVAILABLE_BY_DSN: dict[tuple[str, str], bool] = {}


_STAGING_REPO_PREFIX = "__staging__"


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


def _sql_literal_text(value: str) -> str:
    return str(value or "").replace("'", "''")


def _sanitize_pg_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.replace("\x00", " ")
    return str(value).replace("\x00", " ")


def _sanitize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace("\x00", " ")
    return str(value).replace("\x00", " ")


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_pg_text(value)
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {_sanitize_pg_text(key): _sanitize_json_value(item) for key, item in value.items()}
    return value


def _json_dumps_sanitized(value: Any) -> str:
    return json.dumps(_sanitize_json_value(value))


def _row_to_chunk(row: Any) -> Chunk:
    """Persistence-to-domain mapping for one ``chunks`` row (vectors never live here)."""
    raw_prov = row.get("provenance")
    provenance: ChunkProvenance | None = None
    if raw_prov is not None:
        provenance = ChunkProvenance.model_validate(_coerce_jsonb_dict(raw_prov))
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
        provenance=provenance,
    )


def _sanitize_chunk_for_storage(chunk: Chunk) -> Chunk:
    return chunk.model_copy(
        update={
            "content": _sanitize_pg_text(chunk.content),
            "file_path": _sanitize_pg_text(chunk.file_path),
            "language": _sanitize_optional_text(chunk.language),
            "metadata": _sanitize_json_value(chunk.metadata or {}),
        }
    )


logger = logging.getLogger(__name__)


_HEARTBEAT_SQL = """
UPDATE corpora
SET meta = jsonb_set(
    meta,
    '{index_run,heartbeat_at}',
    to_jsonb(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '+00:00')
)
WHERE repo_id = $1 AND meta->'index_run'->>'run_id' = $2
RETURNING 1;
"""


class PostgresClient:
    """Postgres control/state store for corpora.

    Stores the corpus registry, per-corpus config, chunk rows (content +
    provenance, no vectors), chunk summaries, and the semantic/embedding caches.
    Dense and sparse chunk vectors live in Qdrant (`server.retrieval.qdrant_store`);
    the recorded dense/sparse contracts on the corpus row are the index truth
    that retrieval enforces.
    """

    def __init__(self, connection_string: str, *, schema_mode: str = "full"):
        self.connection_string = connection_string
        self._schema_mode = "control" if str(schema_mode).strip().lower() == "control" else "full"
        self._pool: asyncpg.Pool | None = None
        self._resolved_dsn: str | None = None
        self._vector_available: bool | None = None

    # ---------------------------------------------------------------------
    # Connection + schema
    # ---------------------------------------------------------------------

    async def connect(self) -> None:
        if self._pool is not None:
            return

        dsn = self._resolve_dsn(self.connection_string)
        self._resolved_dsn = dsn
        pool_key = (dsn, self._schema_mode)

        # Fast path: pool already exists for this DSN (no locking needed).
        existing = _POOLS_BY_DSN.get(pool_key)
        if existing is not None:
            self._pool = existing
            self._vector_available = _VECTOR_AVAILABLE_BY_DSN.get(pool_key, True)
            return

        # Lazily create a lock per DSN (locks bind to the running loop).
        lock = _POOL_LOCKS_BY_DSN.get(pool_key)
        if lock is None:
            lock = asyncio.Lock()
            _POOL_LOCKS_BY_DSN[pool_key] = lock

        try:
            async with lock:
                pool = _POOLS_BY_DSN.get(pool_key)
                if pool is None:
                    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
                    try:
                        async with pool.acquire() as conn:
                            # Control-plane routes (corpora/config) do not require pgvector.
                            # Keep their bootstrap independent so they remain available
                            # even when vector extensions are not installed.
                            include_vector = self._schema_mode == "full"
                            self._vector_available = await self._ensure_schema(
                                conn, include_vector=include_vector
                            )
                            if include_vector and self._vector_available:
                                await register_vector(conn)
                    except Exception:
                        # Ensure we don't leave a half-initialized pool around.
                        await pool.close()
                        raise
                    _POOLS_BY_DSN[pool_key] = pool
                    _VECTOR_AVAILABLE_BY_DSN[pool_key] = bool(self._vector_available)

                self._pool = pool
        except Exception:
            # Failed initializations for unique DSNs should not accumulate lock objects.
            if _POOLS_BY_DSN.get(pool_key) is None:
                _POOL_LOCKS_BY_DSN.pop(pool_key, None)
            raise

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
        for _pool_key, pool in list(_POOLS_BY_DSN.items()):
            try:
                await pool.close()
            except Exception:
                pass
        _POOLS_BY_DSN.clear()
        _POOL_LOCKS_BY_DSN.clear()
        _VECTOR_AVAILABLE_BY_DSN.clear()

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

    async def _ensure_schema(self, conn: asyncpg.Connection, *, include_vector: bool) -> bool:
        vector_available = False
        if include_vector:
            # Ensure pgvector extension (best-effort).
            try:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                vector_available = True
            except Exception:
                vector_available = False
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
              embedding_backend TEXT,
              embedding_provider TEXT,
              embedding_model TEXT,
              embedding_dimensions INT,
              sparse_contract JSONB
            );
            """
        )
        # Ensure new columns exist when upgrading an existing DB
        await conn.execute(
            "ALTER TABLE corpora ADD COLUMN IF NOT EXISTS meta JSONB NOT NULL DEFAULT '{}'::jsonb;"
        )
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS embedding_backend TEXT;")
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS embedding_provider TEXT;")
        await conn.execute("ALTER TABLE corpora ADD COLUMN IF NOT EXISTS sparse_contract JSONB;")
        # The sparse contract used to be a Postgres FTS ts_config; sparse vectors now live in Qdrant.
        await conn.execute("ALTER TABLE corpora DROP COLUMN IF EXISTS ts_config;")

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

        if not include_vector:
            return vector_available

        # Semantic cache store (search/answer/chat payload cache).
        # Keep parity with chunks.embedding compatibility: prefer undimensioned vector,
        # but fall back to vector(<dim>) on older pgvector installs.
        if not vector_available:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS semantic_cache_entries (
                  scope_key TEXT NOT NULL,
                  endpoint TEXT NOT NULL,
                  exact_key TEXT NOT NULL,
                  query_text TEXT NOT NULL,
                  query_embedding DOUBLE PRECISION[],
                  request_fingerprint TEXT NOT NULL DEFAULT '',
                  payload JSONB NOT NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  expires_at TIMESTAMPTZ NOT NULL,
                  last_hit_at TIMESTAMPTZ,
                  hit_count BIGINT NOT NULL DEFAULT 0,
                  PRIMARY KEY (scope_key, endpoint, exact_key)
                );
                """
            )
        else:
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS semantic_cache_entries (
                      scope_key TEXT NOT NULL,
                      endpoint TEXT NOT NULL,
                      exact_key TEXT NOT NULL,
                      query_text TEXT NOT NULL,
                      query_embedding vector,
                      request_fingerprint TEXT NOT NULL DEFAULT '',
                      payload JSONB NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      expires_at TIMESTAMPTZ NOT NULL,
                      last_hit_at TIMESTAMPTZ,
                      hit_count BIGINT NOT NULL DEFAULT 0,
                      PRIMARY KEY (scope_key, endpoint, exact_key)
                    );
                    """
                )
            except Exception:
                try:
                    from server.config import load_config as _load_global_config

                    dim = int(_load_global_config().embedding.embedding_dim)
                except Exception:
                    from server.models.tribrid_config_model import TriBridConfig

                    dim = int(TriBridConfig().embedding.embedding_dim)
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS semantic_cache_entries (
                      scope_key TEXT NOT NULL,
                      endpoint TEXT NOT NULL,
                      exact_key TEXT NOT NULL,
                      query_text TEXT NOT NULL,
                      query_embedding vector({dim}),
                      request_fingerprint TEXT NOT NULL DEFAULT '',
                      payload JSONB NOT NULL,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      expires_at TIMESTAMPTZ NOT NULL,
                      last_hit_at TIMESTAMPTZ,
                      hit_count BIGINT NOT NULL DEFAULT 0,
                      PRIMARY KEY (scope_key, endpoint, exact_key)
                    );
                    """
                )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_scope_endpoint_expiry
            ON semantic_cache_entries(scope_key, endpoint, expires_at);
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_semantic_cache_last_hit
            ON semantic_cache_entries(last_hit_at);
            """
        )

        # Embedding cache store (indexing-time embedding reuse).
        # Keyed by provider/model/dim/input hash so changing embedding model or
        # dimensions never reuses stale vectors.
        if not vector_available:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embedding_cache_entries (
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  dimensions INT NOT NULL,
                  input_hash TEXT NOT NULL,
                  input_text TEXT NOT NULL DEFAULT '',
                  embedding DOUBLE PRECISION[],
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  PRIMARY KEY (provider, model, dimensions, input_hash)
                );
                """
            )
        else:
            try:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embedding_cache_entries (
                      provider TEXT NOT NULL,
                      model TEXT NOT NULL,
                      dimensions INT NOT NULL,
                      input_hash TEXT NOT NULL,
                      input_text TEXT NOT NULL DEFAULT '',
                      embedding vector,
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      PRIMARY KEY (provider, model, dimensions, input_hash)
                    );
                    """
                )
            except Exception:
                try:
                    from server.config import load_config as _load_global_config

                    dim = int(_load_global_config().embedding.embedding_dim)
                except Exception:
                    from server.models.tribrid_config_model import TriBridConfig

                    dim = int(TriBridConfig().embedding.embedding_dim)
                await conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS embedding_cache_entries (
                      provider TEXT NOT NULL,
                      model TEXT NOT NULL,
                      dimensions INT NOT NULL,
                      input_hash TEXT NOT NULL,
                      input_text TEXT NOT NULL DEFAULT '',
                      embedding vector({dim}),
                      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                      PRIMARY KEY (provider, model, dimensions, input_hash)
                    );
                    """
                )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_embedding_cache_created_at
            ON embedding_cache_entries(created_at);
            """
        )

        # Chunk store: content + provenance rows only. Vectors live in Qdrant.
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
        # Typed chunk provenance (extraction method + page regions). NULL = indexed before capture.
        await conn.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS provenance JSONB;")

        # Per-file provenance record for the source document viewer. Rows are written under the
        # staging corpus id and promoted with the chunks; ``markdown`` is stored for rich kinds
        # (docx/pptx/xlsx/html) only, never for PDFs (those render from the original file).
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
              repo_id TEXT NOT NULL REFERENCES corpora(repo_id) ON DELETE CASCADE,
              file_path TEXT NOT NULL,
              kind TEXT NOT NULL CHECK (kind IN ('text', 'pdf', 'rich')),
              extraction TEXT NOT NULL CHECK (extraction IN ('docling', 'direct')),
              sha256 TEXT NOT NULL,
              byte_size BIGINT NOT NULL,
              markdown TEXT,
              indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (repo_id, file_path)
            );
            """
        )
        # Vector/FTS columns and their indexes moved to Qdrant; remove them from upgraded installs.
        await conn.execute("DROP INDEX IF EXISTS idx_chunks_tsv;")
        await conn.execute("DROP INDEX IF EXISTS idx_chunks_bm25;")
        await conn.execute("DROP INDEX IF EXISTS idx_chunks_recall_embedding_hnsw;")
        stale_vector_indexes = await conn.fetch(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'chunks'
              AND indexname LIKE 'idx_chunks_%_embedding_hnsw';
            """
        )
        for row in stale_vector_indexes:
            await conn.execute(f'DROP INDEX IF EXISTS "{row["indexname"]}";')
        legacy_vector_columns = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'chunks'
              AND column_name IN ('embedding', 'tsv');
            """
        )
        await conn.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS bm25_id;")
        await conn.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS tsv;")
        await conn.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS embedding;")
        if int(legacy_vector_columns or 0) > 0:
            # The vectors that made these corpora "indexed" no longer exist anywhere:
            # they must read as never indexed (empty legs) until re-indexed, not as
            # indexed corpora with a missing Qdrant generation (503 on every leg).
            await conn.execute(
                """
                UPDATE corpora
                SET last_indexed = NULL,
                    embedding_backend = NULL,
                    embedding_provider = NULL,
                    embedding_model = NULL,
                    embedding_dimensions = NULL,
                    sparse_contract = NULL,
                    meta = COALESCE(meta, '{}'::jsonb) - 'embedding_backend';
                """
            )

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
              routes JSONB NOT NULL DEFAULT '[]'::jsonb,
              dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
              patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
              card_source TEXT NOT NULL DEFAULT 'deterministic',
              card_score DOUBLE PRECISION,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (repo_id, chunk_id)
            );
            """
        )
        await conn.execute(
            "ALTER TABLE chunk_summaries ADD COLUMN IF NOT EXISTS routes JSONB NOT NULL DEFAULT '[]'::jsonb;"
        )
        await conn.execute(
            "ALTER TABLE chunk_summaries ADD COLUMN IF NOT EXISTS dependencies JSONB NOT NULL DEFAULT '[]'::jsonb;"
        )
        await conn.execute(
            "ALTER TABLE chunk_summaries ADD COLUMN IF NOT EXISTS patterns JSONB NOT NULL DEFAULT '[]'::jsonb;"
        )
        await conn.execute(
            "ALTER TABLE chunk_summaries ADD COLUMN IF NOT EXISTS card_source TEXT NOT NULL DEFAULT 'deterministic';"
        )
        await conn.execute(
            "ALTER TABLE chunk_summaries ADD COLUMN IF NOT EXISTS card_score DOUBLE PRECISION;"
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
        return vector_available

    # ---------------------------------------------------------------------
    # Chunk rows (content + provenance; vectors live in Qdrant)
    # ---------------------------------------------------------------------

    async def _upsert_chunk_rows(self, conn: Any, repo_id: str, chunks: list[Chunk]) -> None:
        stmt = """
        INSERT INTO chunks (
          repo_id, chunk_id, file_path, start_line, end_line, language, content, token_count,
          metadata, provenance
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)
        ON CONFLICT (repo_id, chunk_id) DO UPDATE SET
          file_path = EXCLUDED.file_path,
          start_line = EXCLUDED.start_line,
          end_line = EXCLUDED.end_line,
          language = EXCLUDED.language,
          content = EXCLUDED.content,
          token_count = EXCLUDED.token_count,
          metadata = EXCLUDED.metadata,
          provenance = EXCLUDED.provenance;
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
                    _json_dumps_sanitized(ch.metadata or {}),
                    json.dumps(ch.provenance.model_dump(mode="json")) if ch.provenance else None,
                )
                for ch in chunks
            ],
        )
        await conn.execute("UPDATE corpora SET last_indexed = now() WHERE repo_id = $1;", repo_id)

    async def upsert_chunks(self, repo_id: str, chunks: list[Chunk]) -> int:
        """Upsert chunk rows for a corpus and stamp corpora.last_indexed (rows only; see upsert_chunks_with_vectors)."""
        if not chunks:
            return 0
        chunks = [_sanitize_chunk_for_storage(ch) for ch in chunks]
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_corpus_row(
                    conn, repo_id, name=repo_id, root_path=".", preserve_identity=True
                )
                await self._upsert_chunk_rows(conn, repo_id, chunks)
        return len(chunks)

    async def upsert_chunks_with_vectors(
        self,
        repo_id: str,
        chunks: list[Chunk],
        *,
        embedding_dim: int,
        qdrant: Any,
    ) -> int:
        """Incremental write of rows AND vectors as one unit of work under the corpus lock.

        One Postgres transaction holds the per-corpus advisory lock (the same
        lock promotion and deletion take), resolves the live generation from
        the row-locked manifest (creating the corpus's first generation when
        there is none), writes the vectors into that collection while the lock
        is held, then upserts the rows. A failed vector write rolls the rows
        back (nothing is ever deleted blindly), so no chunk exists in Postgres
        only; a promotion cannot switch generations under the writer; a
        tombstoned corpus refuses the write.
        """
        from server.indexing.generations import build_generation, generation_from_corpus_row

        if not chunks:
            return 0
        chunks = [_sanitize_chunk_for_storage(ch) for ch in chunks]
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", repo_id)
                await self._ensure_corpus_row(
                    conn, repo_id, name=repo_id, root_path=".", preserve_identity=True
                )
                row = await conn.fetchrow(
                    "SELECT repo_id, meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                meta = _coerce_jsonb_dict(row["meta"]) if row is not None else {}
                generation = generation_from_corpus_row({"repo_id": repo_id, "meta": meta})
                physical = generation.qdrant_collection if generation else None
                new_manifest = None
                if physical is None:
                    physical = await qdrant.create_generation(repo_id, embedding_dim=embedding_dim)
                    # Adding the missing vector store never retires a live graph: the
                    # manifest keeps whatever graph it already named.
                    new_manifest = build_generation(
                        run_id=f"incremental-{uuid.uuid4().hex[:10]}",
                        qdrant_collection=physical,
                        graph_repo_id=generation.graph_repo_id if generation else None,
                        graph_metadata=generation.graph_metadata if generation else None,
                        previous=generation,
                        now=await conn.fetchval("SELECT now();"),
                    )
                try:
                    await qdrant.write_chunks(
                        repo_id, physical, chunks, embedding_dim=embedding_dim
                    )
                except BaseException:
                    if new_manifest is not None:
                        with contextlib.suppress(Exception):
                            await qdrant.drop_generation(physical)
                    raise
                await self._upsert_chunk_rows(conn, repo_id, chunks)
                if new_manifest is not None:
                    await conn.execute(
                        "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                        repo_id,
                        _json_dumps_sanitized({"generation": new_manifest.model_dump(mode="json")}),
                    )
        return len(chunks)

    async def clear_corpus_index_state(self, repo_id: str) -> None:
        """Reset index truth on the corpus row after its chunks and vectors were deleted.

        A de-indexed corpus must read as never indexed (no last_indexed, no
        recorded contracts) so retrieval reports empty legs instead of a
        missing-generation failure, and the next index run records fresh contracts.
        """
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE corpora
                SET last_indexed = NULL,
                    embedding_backend = NULL,
                    embedding_provider = NULL,
                    embedding_model = NULL,
                    embedding_dimensions = NULL,
                    sparse_contract = NULL,
                    meta = (COALESCE(meta, '{}'::jsonb) - 'embedding_backend') - 'generation'
                WHERE repo_id = $1;
                """,
                repo_id,
            )

    async def count_chunks(self, repo_id: str) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*)::int AS n FROM chunks WHERE repo_id = $1;", repo_id
            )
        return int((row or {}).get("n") or 0)

    async def get_chunk(self, repo_id: str, chunk_id: str) -> Chunk | None:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT repo_id, chunk_id, content, file_path, start_line, end_line, language, token_count, metadata, provenance
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
        return _row_to_chunk(row)

    async def get_chunks(self, repo_id: str, chunk_ids: list[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.chunk_id, c.content, c.file_path, c.start_line, c.end_line, c.language, c.token_count, c.metadata, c.provenance
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
            _row_to_chunk(r)
            for r in rows
        ]

    async def get_chunks_by_file_ordinals(
        self, repo_id: str, file_path: str, ordinals: list[int]
    ) -> list[Chunk]:
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
                SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata, provenance
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
            _row_to_chunk(r)
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
        """Return corpus-scoped Postgres storage (bytes) for the Dashboard.

        The Dashboard polls frequently; keep this best-effort and cached. Every
        column is COALESCEd: a single NULL column (language on prose chunks) used
        to null the whole row's sum and the tiles read 0 B (drive finding M22).
        """
        repo_id = (repo_id or "").strip()
        if not repo_id:
            return {"chunks_bytes": 0, "chunk_summaries_bytes": 0}

        now = time.time()
        cached = self._dashboard_storage_cache.get(repo_id)
        if cached is not None:
            ts, payload = cached
            if now - ts <= float(self._dashboard_storage_ttl_s):
                return dict(payload)

        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            chunks_row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(
                    COALESCE(pg_column_size(chunk_id), 0)
                    + COALESCE(pg_column_size(file_path), 0)
                    + COALESCE(pg_column_size(start_line), 0)
                    + COALESCE(pg_column_size(end_line), 0)
                    + COALESCE(pg_column_size(language), 0)
                    + COALESCE(pg_column_size(token_count), 0)
                    + COALESCE(pg_column_size(content), 0)
                    + COALESCE(pg_column_size(metadata), 0)
                  ), 0)::bigint AS chunks_bytes
                FROM chunks
                WHERE repo_id = $1;
                """,
                repo_id,
            )
            summaries_row = await conn.fetchrow(
                """
                SELECT
                  COALESCE(SUM(
                    COALESCE(pg_column_size(chunk_id), 0)
                    + COALESCE(pg_column_size(file_path), 0)
                    + COALESCE(pg_column_size(start_line), 0)
                    + COALESCE(pg_column_size(end_line), 0)
                    + COALESCE(pg_column_size(purpose), 0)
                    + COALESCE(pg_column_size(symbols), 0)
                    + COALESCE(pg_column_size(technical_details), 0)
                    + COALESCE(pg_column_size(domain_concepts), 0)
                  ), 0)::bigint AS chunk_summaries_bytes
                FROM chunk_summaries
                WHERE repo_id = $1;
                """,
                repo_id,
            )

        out = {
            "chunks_bytes": int(chunks_row["chunks_bytes"] or 0) if chunks_row else 0,
            "chunk_summaries_bytes": int(summaries_row["chunk_summaries_bytes"] or 0)
            if summaries_row
            else 0,
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
                WHERE repo_id NOT LIKE $1
                ORDER BY created_at DESC;
                """,
                f"{_STAGING_REPO_PREFIX}%",
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
                SELECT repo_id, name, root_path, description, meta, created_at, last_indexed,
                       embedding_backend, embedding_provider, embedding_model, embedding_dimensions, sparse_contract
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
            "embedding_backend": str(row["embedding_backend"] or ""),
            "embedding_provider": str(row["embedding_provider"] or ""),
            "embedding_model": str(row["embedding_model"] or ""),
            "embedding_dimensions": int(row["embedding_dimensions"] or 0),
            "sparse_contract": _coerce_jsonb_dict(row["sparse_contract"])
            if row["sparse_contract"]
            else None,
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
        """Remove the registry row under the corpus lock (no writer can slip a generation in meanwhile)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", repo_id)
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
                _json_dumps_sanitized(config),
            )

    # ---------------------------------------------------------------------
    # Semantic cache operations
    # ---------------------------------------------------------------------

    async def semantic_cache_lookup_exact(
        self,
        *,
        scope_key: str,
        endpoint: str,
        exact_key: str,
    ) -> dict[str, Any] | None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT scope_key, endpoint, exact_key, request_fingerprint, payload, expires_at
                FROM semantic_cache_entries
                WHERE scope_key = $1
                  AND endpoint = $2
                  AND exact_key = $3
                  AND expires_at > now()
                LIMIT 1;
                """,
                str(scope_key),
                str(endpoint),
                str(exact_key),
            )
        if row is None:
            return None
        return {
            "scope_key": str(row["scope_key"]),
            "endpoint": str(row["endpoint"]),
            "exact_key": str(row["exact_key"]),
            "request_fingerprint": str(row["request_fingerprint"] or ""),
            "payload": _coerce_jsonb_dict(row["payload"]),
            "similarity": 1.0,
        }

    async def semantic_cache_lookup_semantic(
        self,
        *,
        scope_key: str,
        endpoint: str,
        query_embedding: list[float],
        request_fingerprint: str,
        min_similarity: float,
    ) -> dict[str, Any] | None:
        if not query_embedding:
            return None
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if self._vector_available is False:
                row = await conn.fetchrow(
                    """
                    WITH q AS (
                      SELECT $3::double precision[] AS qv
                    ),
                    candidates AS (
                      SELECT scope_key, endpoint, exact_key, request_fingerprint, payload, query_embedding
                      FROM semantic_cache_entries
                      WHERE scope_key = $1
                        AND endpoint = $2
                        AND request_fingerprint = $4
                        AND expires_at > now()
                        AND query_embedding IS NOT NULL
                        AND array_length(query_embedding, 1) = $6
                    ),
                    scored AS (
                      SELECT c.scope_key, c.endpoint, c.exact_key, c.request_fingerprint, c.payload,
                             CASE
                               WHEN v.q_norm = 0 OR v.e_norm = 0 THEN 0::float8
                               ELSE (v.dot / (v.q_norm * v.e_norm))::float8
                             END AS similarity
                      FROM candidates c
                      CROSS JOIN LATERAL (
                        SELECT
                          COALESCE(SUM(qe.q_val * ee.e_val), 0::float8) AS dot,
                          SQRT(COALESCE(SUM(qe.q_val * qe.q_val), 0::float8)) AS q_norm,
                          SQRT(COALESCE(SUM(ee.e_val * ee.e_val), 0::float8)) AS e_norm
                        FROM unnest((SELECT qv FROM q)) WITH ORDINALITY AS qe(q_val, idx)
                        JOIN unnest(c.query_embedding) WITH ORDINALITY AS ee(e_val, idx)
                          ON qe.idx = ee.idx
                      ) AS v
                    )
                    SELECT scope_key, endpoint, exact_key, request_fingerprint, payload, similarity
                    FROM scored
                    WHERE similarity >= $5
                    ORDER BY similarity DESC
                    LIMIT 1;
                    """,
                    str(scope_key),
                    str(endpoint),
                    [float(x) for x in query_embedding],
                    str(request_fingerprint or ""),
                    float(min_similarity),
                    int(len(query_embedding)),
                )
            else:
                try:
                    await register_vector(conn)
                except Exception:
                    pass
                row = await conn.fetchrow(
                    """
                    WITH candidates AS (
                        SELECT scope_key, endpoint, exact_key, request_fingerprint, payload, query_embedding
                        FROM semantic_cache_entries
                        WHERE scope_key = $1
                          AND endpoint = $2
                          AND request_fingerprint = $4
                          AND expires_at > now()
                          AND query_embedding IS NOT NULL
                          AND vector_dims(query_embedding) = $6
                    )
                    SELECT scope_key, endpoint, exact_key, request_fingerprint, payload,
                           (1 - (query_embedding <=> $3))::float8 AS similarity
                    FROM candidates
                    WHERE (1 - (query_embedding <=> $3)) >= $5
                    ORDER BY query_embedding <=> $3
                    LIMIT 1;
                    """,
                    str(scope_key),
                    str(endpoint),
                    [float(x) for x in query_embedding],
                    str(request_fingerprint or ""),
                    float(min_similarity),
                    int(len(query_embedding)),
                )
        if row is None:
            return None
        return {
            "scope_key": str(row["scope_key"]),
            "endpoint": str(row["endpoint"]),
            "exact_key": str(row["exact_key"]),
            "request_fingerprint": str(row["request_fingerprint"] or ""),
            "payload": _coerce_jsonb_dict(row["payload"]),
            "similarity": float(row["similarity"] or 0.0),
        }

    async def semantic_cache_upsert(
        self,
        *,
        scope_key: str,
        endpoint: str,
        exact_key: str,
        query_text: str,
        query_embedding: list[float] | None,
        request_fingerprint: str,
        payload: dict[str, Any],
        ttl_seconds: int,
    ) -> None:
        ttl = max(1, int(ttl_seconds))
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            try:
                await register_vector(conn)
            except Exception:
                pass
            await conn.execute(
                """
                INSERT INTO semantic_cache_entries (
                  scope_key,
                  endpoint,
                  exact_key,
                  query_text,
                  query_embedding,
                  request_fingerprint,
                  payload,
                  created_at,
                  expires_at,
                  last_hit_at,
                  hit_count
                )
                VALUES (
                  $1, $2, $3, $4, $5, $6, $7::jsonb, now(),
                  now() + ($8::text || ' seconds')::interval,
                  NULL, 0
                )
                ON CONFLICT (scope_key, endpoint, exact_key) DO UPDATE SET
                  query_text = EXCLUDED.query_text,
                  query_embedding = EXCLUDED.query_embedding,
                  request_fingerprint = EXCLUDED.request_fingerprint,
                  payload = EXCLUDED.payload,
                  created_at = now(),
                  expires_at = EXCLUDED.expires_at,
                  last_hit_at = NULL,
                  hit_count = 0;
                """,
                str(scope_key),
                str(endpoint),
                str(exact_key),
                _sanitize_pg_text(query_text or ""),
                ([float(x) for x in query_embedding] if query_embedding else None),
                _sanitize_pg_text(request_fingerprint or ""),
                _json_dumps_sanitized(payload or {}),
                str(ttl),
            )

    async def semantic_cache_touch(self, *, scope_key: str, endpoint: str, exact_key: str) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE semantic_cache_entries
                SET last_hit_at = now(),
                    hit_count = hit_count + 1
                WHERE scope_key = $1
                  AND endpoint = $2
                  AND exact_key = $3;
                """,
                str(scope_key),
                str(endpoint),
                str(exact_key),
            )

    async def semantic_cache_delete_expired(
        self, *, scope_key: str | None = None, endpoint: str | None = None
    ) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if scope_key and endpoint:
                result = await conn.execute(
                    """
                    DELETE FROM semantic_cache_entries
                    WHERE scope_key = $1
                      AND endpoint = $2
                      AND expires_at <= now();
                    """,
                    str(scope_key),
                    str(endpoint),
                )
            elif scope_key:
                result = await conn.execute(
                    """
                    DELETE FROM semantic_cache_entries
                    WHERE scope_key = $1
                      AND expires_at <= now();
                    """,
                    str(scope_key),
                )
            elif endpoint:
                result = await conn.execute(
                    """
                    DELETE FROM semantic_cache_entries
                    WHERE endpoint = $1
                      AND expires_at <= now();
                    """,
                    str(endpoint),
                )
            else:
                result = await conn.execute(
                    """
                    DELETE FROM semantic_cache_entries
                    WHERE expires_at <= now();
                    """
                )
        return int(str(result).split()[-1])

    async def semantic_cache_prune_lru(
        self,
        *,
        scope_key: str,
        endpoint: str,
        max_entries: int,
    ) -> int:
        cap = max(1, int(max_entries))
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                WITH ranked AS (
                  SELECT ctid
                  FROM semantic_cache_entries
                  WHERE scope_key = $1
                    AND endpoint = $2
                  ORDER BY COALESCE(last_hit_at, created_at) DESC
                  OFFSET $3
                )
                DELETE FROM semantic_cache_entries
                WHERE ctid IN (SELECT ctid FROM ranked);
                """,
                str(scope_key),
                str(endpoint),
                int(cap),
            )
        return int(str(result).split()[-1])

    async def semantic_cache_clear(
        self, *, scope_key: str | None = None, endpoint: str | None = None
    ) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if scope_key and endpoint:
                result = await conn.execute(
                    "DELETE FROM semantic_cache_entries WHERE scope_key = $1 AND endpoint = $2;",
                    str(scope_key),
                    str(endpoint),
                )
            elif scope_key:
                result = await conn.execute(
                    "DELETE FROM semantic_cache_entries WHERE scope_key = $1;",
                    str(scope_key),
                )
            elif endpoint:
                result = await conn.execute(
                    "DELETE FROM semantic_cache_entries WHERE endpoint = $1;",
                    str(endpoint),
                )
            else:
                result = await conn.execute("DELETE FROM semantic_cache_entries;")
        return int(str(result).split()[-1])

    async def semantic_cache_clear_for_corpus(self, repo_id: str) -> int:
        """Clear semantic cache entries whose scope includes the corpus id."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM semantic_cache_entries
                WHERE scope_key LIKE 'corpora:%'
                  AND $1 = ANY(string_to_array(SUBSTRING(scope_key FROM 9), '|'));
                """,
                str(repo_id or ""),
            )
        return int(str(result).split()[-1])

    async def embedding_cache_lookup_batch(
        self,
        *,
        provider: str,
        model: str,
        dimensions: int,
        input_hashes: list[str],
    ) -> dict[str, list[float]]:
        keys = [str(h or "").strip() for h in (input_hashes or []) if str(h or "").strip()]
        if not keys:
            return {}
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            try:
                await register_vector(conn)
            except Exception:
                pass
            rows = await conn.fetch(
                """
                SELECT input_hash, embedding
                FROM embedding_cache_entries
                WHERE provider = $1
                  AND model = $2
                  AND dimensions = $3
                  AND input_hash = ANY($4::text[]);
                """,
                str(provider or ""),
                str(model or ""),
                int(dimensions),
                keys,
            )
        out: dict[str, list[float]] = {}
        for r in rows:
            h = str(r["input_hash"] or "").strip()
            emb = r["embedding"]
            if not h or emb is None:
                continue
            try:
                out[h] = [float(x) for x in emb]
            except Exception:
                try:
                    out[h] = [float(x) for x in list(emb)]
                except Exception:
                    continue
        return out

    async def embedding_cache_upsert_batch(
        self,
        *,
        provider: str,
        model: str,
        dimensions: int,
        entries: dict[str, tuple[str, list[float]]],
    ) -> int:
        if not entries:
            return 0
        rows: list[tuple[str, str, int, str, str, list[float]]] = []
        for h, payload in entries.items():
            hh = str(h or "").strip()
            if not hh:
                continue
            text, vec = payload
            rows.append(
                (
                    str(provider or ""),
                    str(model or ""),
                    int(dimensions),
                    hh,
                    str(text or ""),
                    [float(x) for x in list(vec)],
                )
            )
        if not rows:
            return 0

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            try:
                await register_vector(conn)
            except Exception:
                pass
            await conn.executemany(
                """
                INSERT INTO embedding_cache_entries (
                  provider, model, dimensions, input_hash, input_text, embedding, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, now())
                ON CONFLICT (provider, model, dimensions, input_hash) DO UPDATE SET
                  input_text = EXCLUDED.input_text,
                  embedding = EXCLUDED.embedding,
                  created_at = now();
                """,
                rows,
            )
        return len(rows)

    async def update_corpus_embedding_meta(
        self,
        repo_id: str,
        *,
        backend: str,
        provider: str,
        model: str,
        dimensions: int,
        sparse_contract: dict[str, Any] | None = None,
    ) -> None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE corpora
                SET embedding_backend = $2::text,
                    embedding_provider = $3::text,
                    embedding_model = $4::text,
                    embedding_dimensions = $5::int,
                    sparse_contract = $6::jsonb,
                    meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object('embedding_backend', $2::text)
                WHERE repo_id = $1;
                """,
                repo_id,
                _sanitize_pg_text(backend or ""),
                _sanitize_pg_text(provider or ""),
                _sanitize_pg_text(model),
                int(dimensions),
                _json_dumps_sanitized(sparse_contract) if sparse_contract else None,
            )

    async def list_chunks_for_repo(self, repo_id: str, limit: int | None = None) -> list[Chunk]:
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            if limit is None:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata, provenance
                    FROM chunks
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC;
                    """,
                    repo_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, content, file_path, start_line, end_line, language, token_count, metadata, provenance
                    FROM chunks
                    WHERE repo_id = $1
                    ORDER BY file_path ASC, start_line ASC, chunk_id ASC
                    LIMIT $2;
                    """,
                    repo_id,
                    int(limit),
                )

        return [
            _row_to_chunk(r)
            for r in rows
        ]

    # ---------------------------------------------------------------------
    # Document provenance records (source document viewer)
    # ---------------------------------------------------------------------

    async def upsert_document(self, repo_id: str, record: IndexedDocumentRecord) -> None:
        """Write the per-file provenance record under ``repo_id`` (staging id during a run)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_corpus_row(
                    conn, repo_id, name=repo_id, root_path=".", preserve_identity=True
                )
                await conn.execute(
                    """
                    INSERT INTO documents (
                      repo_id, file_path, kind, extraction, sha256, byte_size, markdown, indexed_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, now())
                    ON CONFLICT (repo_id, file_path) DO UPDATE SET
                      kind = EXCLUDED.kind,
                      extraction = EXCLUDED.extraction,
                      sha256 = EXCLUDED.sha256,
                      byte_size = EXCLUDED.byte_size,
                      markdown = EXCLUDED.markdown,
                      indexed_at = now();
                    """,
                    repo_id,
                    record.file_path,
                    record.kind,
                    record.extraction,
                    record.sha256,
                    int(record.byte_size),
                    _sanitize_pg_text(record.markdown) if record.markdown is not None else None,
                )

    async def get_document(self, repo_id: str, file_path: str) -> IndexedDocumentRecord | None:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT file_path, kind, extraction, sha256, byte_size, markdown, indexed_at
                FROM documents
                WHERE repo_id = $1 AND file_path = $2;
                """,
                repo_id,
                file_path,
            )
        if not row:
            return None
        return IndexedDocumentRecord(
            file_path=str(row["file_path"]),
            kind=row["kind"],
            extraction=row["extraction"],
            sha256=str(row["sha256"]),
            byte_size=int(row["byte_size"]),
            markdown=row["markdown"],
            indexed_at=row["indexed_at"],
        )

    async def file_is_indexed(self, repo_id: str, file_path: str) -> bool:
        """True when the corpus holds at least one chunk for the file (the viewer's authorization)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            found = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM chunks WHERE repo_id = $1 AND file_path = $2);",
                repo_id,
                file_path,
            )
        return bool(found)

    async def count_documents(self, repo_id: str) -> int:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return int(
                await conn.fetchval("SELECT count(*) FROM documents WHERE repo_id = $1;", repo_id)
                or 0
            )

    async def list_chunk_summaries(
        self, repo_id: str, limit: int | None = None
    ) -> list[ChunkSummary]:
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            if limit is None:
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, file_path, start_line, end_line, purpose, symbols,
                           technical_details, domain_concepts, routes, dependencies, patterns,
                           card_source, card_score
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
                           technical_details, domain_concepts, routes, dependencies, patterns,
                           card_source, card_score
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
            routes = r.get("routes") or []
            if isinstance(routes, str):
                try:
                    routes = json.loads(routes)
                except Exception:
                    routes = []
            dependencies = r.get("dependencies") or []
            if isinstance(dependencies, str):
                try:
                    dependencies = json.loads(dependencies)
                except Exception:
                    dependencies = []
            patterns = r.get("patterns") or []
            if isinstance(patterns, str):
                try:
                    patterns = json.loads(patterns)
                except Exception:
                    patterns = []
            out.append(
                ChunkSummary(
                    chunk_id=str(r["chunk_id"]),
                    file_path=str(r["file_path"]),
                    start_line=int(r["start_line"]) if r["start_line"] is not None else None,
                    end_line=int(r["end_line"]) if r["end_line"] is not None else None,
                    purpose=str(r["purpose"]) if r["purpose"] is not None else None,
                    symbols=[str(x) for x in symbols] if isinstance(symbols, list) else [],
                    technical_details=str(r["technical_details"])
                    if r["technical_details"] is not None
                    else None,
                    domain_concepts=[str(x) for x in domain_concepts]
                    if isinstance(domain_concepts, list)
                    else [],
                    routes=[str(x) for x in routes] if isinstance(routes, list) else [],
                    dependencies=[str(x) for x in dependencies]
                    if isinstance(dependencies, list)
                    else [],
                    patterns=[str(x) for x in patterns] if isinstance(patterns, list) else [],
                    card_source=(
                        "llm"
                        if str(r.get("card_source") or "").strip().lower() == "llm"
                        else "deterministic"
                    ),
                    card_score=(
                        float(r["card_score"]) if r.get("card_score") is not None else None
                    ),
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
            await self._ensure_corpus_row(
                conn, repo_id, name=repo_id, root_path=".", preserve_identity=True
            )
            async with conn.transaction():
                await conn.execute("DELETE FROM chunk_summaries WHERE repo_id = $1;", repo_id)

                if summaries:
                    await conn.executemany(
                        """
                        INSERT INTO chunk_summaries (
                          repo_id, chunk_id, file_path, start_line, end_line,
                          purpose, symbols, technical_details, domain_concepts,
                          routes, dependencies, patterns, card_source, card_score
                        )
                        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12::jsonb,$13,$14);
                        """,
                        [
                            (
                                repo_id,
                                _sanitize_pg_text(s.chunk_id),
                                _sanitize_pg_text(s.file_path),
                                int(s.start_line) if s.start_line is not None else None,
                                int(s.end_line) if s.end_line is not None else None,
                                _sanitize_optional_text(s.purpose),
                                _json_dumps_sanitized(list(s.symbols or [])),
                                _sanitize_optional_text(s.technical_details),
                                _json_dumps_sanitized(list(s.domain_concepts or [])),
                                _json_dumps_sanitized(list(s.routes or [])),
                                _json_dumps_sanitized(list(s.dependencies or [])),
                                _json_dumps_sanitized(list(s.patterns or [])),
                                _sanitize_pg_text(
                                    getattr(s, "card_source", "deterministic") or "deterministic"
                                ),
                                (float(s.card_score) if s.card_score is not None else None),
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
                result = await conn.execute(
                    "DELETE FROM chunk_summaries WHERE chunk_id = $1;", chunk_id
                )
        return int(result.split()[-1])

    async def get_generation(self, repo_id: str) -> GenerationManifest | None:
        """The active-generation manifest of a corpus (None when nothing is promoted)."""
        from server.indexing.generations import generation_from_corpus_row

        return generation_from_corpus_row(await self.get_corpus(repo_id))

    async def set_generation(self, repo_id: str, generation: GenerationManifest) -> None:
        """Point a corpus at a generation outside a full index run (incremental corpora, upgrades)."""
        await self.update_corpus_meta(repo_id, {"generation": generation.model_dump(mode="json")})

    async def database_now(self) -> datetime:
        """The database clock: every lease decision compares against it, never a worker's wall clock."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            now = await conn.fetchval("SELECT now();")
        assert isinstance(now, datetime)
        return now

    async def get_index_fence(self, repo_id: str) -> IndexRunFence | None:
        """The durable fence on the corpus row, validated; a malformed fence raises."""
        from server.indexing.generations import IndexFenceCorruptError, IndexRunFence

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT meta FROM corpora WHERE repo_id = $1;", repo_id)
        if row is None:
            return None
        raw = _coerce_jsonb_dict(row["meta"]).get("index_run")
        if raw is None:
            return None
        try:
            return IndexRunFence.model_validate(raw)
        except Exception as exc:
            raise IndexFenceCorruptError(repo_id, raw) from exc

    async def acquire_index_fence(
        self,
        repo_id: str,
        run_id: str,
        *,
        started_at: datetime,
        owner: str,
        lease_seconds: int,
        heartbeat_at: datetime | None = None,
    ) -> FenceClaim:
        """Durably claim the single index-run slot of a corpus (compare-and-set on the corpus row).

        ``FenceClaim.held_by`` names the live fence that refused the claim;
        ``taken_over`` names a stale fence (heartbeat older than
        ``lease_seconds`` by the DATABASE clock) that this claim replaced so the
        caller can reclaim its staged resources. A present-but-malformed fence
        raises (it is never read as absence). Process-local task maps are not
        enough: a second worker/process could otherwise build and retire
        against the same corpus.
        """
        from server.indexing.generations import (
            DeletionIncompleteError,
            FenceClaim,
            GenerationManifest,
            IndexFenceCorruptError,
            IndexRunFence,
            PersistedStateCorruptError,
            ReclaimEntry,
            reclaim_backlog_from_meta,
            tombstone_from_meta,
        )

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT meta, now() AS db_now FROM corpora WHERE repo_id = $1 FOR UPDATE;",
                    repo_id,
                )
                if row is None:
                    from server.services.config_store import CorpusNotFoundError

                    raise CorpusNotFoundError(f"Corpus not found: {repo_id}")
                db_now: datetime = row["db_now"]
                taken_over: IndexRunFence | None = None
                taken_over_committed = False
                meta = _coerce_jsonb_dict(row["meta"])
                tombstone = tombstone_from_meta(meta, repo_id=repo_id)
                if tombstone is not None:
                    raise DeletionIncompleteError(repo_id, tombstone)
                raw_manifest = meta.get("generation")
                live_manifest = None
                if raw_manifest is not None:
                    try:
                        live_manifest = GenerationManifest.model_validate(raw_manifest)
                    except Exception as exc:
                        # Never fence a corpus whose manifest cannot be read: the run
                        # could only fail at promotion and hold the corpus meanwhile.
                        raise PersistedStateCorruptError(
                            repo_id, "generation", raw_manifest
                        ) from exc
                reclaim_backlog_from_meta(meta, repo_id=repo_id)
                existing = meta.get("index_run")
                backlog_patch: dict[str, Any] | None = None
                if existing is not None:
                    try:
                        held = IndexRunFence.model_validate(existing)
                    except Exception as exc:
                        raise IndexFenceCorruptError(repo_id, existing) from exc
                    if not held.is_stale(now=db_now, lease_seconds=lease_seconds):
                        return FenceClaim(held_by=held)
                    taken_over = held
                    # Only the manifest's run id proves the dead run committed: a
                    # collection id appearing among retained ones is not ownership.
                    taken_over_committed = (
                        live_manifest is not None and live_manifest.run_id == held.run_id
                    )
                    logger.warning(
                        "taking over stale index-run fence on %s: run %s (owner %s) last heartbeat %s%s",
                        repo_id,
                        held.run_id,
                        held.owner,
                        held.heartbeat_at.isoformat(),
                        " (it had committed: finalizing, not reclaiming)"
                        if taken_over_committed
                        else "",
                    )
                    if not taken_over_committed and (
                        held.staged_qdrant_collection or held.staged_graph_repo_id
                    ):
                        # The dead run's staged inventory is preserved durably until its
                        # cleanup is confirmed (the fence itself is about to be replaced).
                        backlog = [
                            e.model_dump(mode="json")
                            for e in reclaim_backlog_from_meta(meta, repo_id=repo_id)
                            if e.run_id != held.run_id
                        ]
                        backlog.append(
                            ReclaimEntry(
                                run_id=held.run_id,
                                staged_qdrant_collection=held.staged_qdrant_collection,
                                staged_graph_repo_id=held.staged_graph_repo_id,
                                recorded_at=db_now,
                            ).model_dump(mode="json")
                        )
                        backlog_patch = {"reclaim_backlog": backlog}
                fence = IndexRunFence(
                    run_id=run_id,
                    owner=owner,
                    started_at=started_at,
                    heartbeat_at=heartbeat_at or db_now,
                )
                patch = {"index_run": fence.model_dump(mode="json"), **(backlog_patch or {})}
                await conn.execute(
                    "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized(patch),
                )
        return FenceClaim(taken_over=taken_over, taken_over_committed=taken_over_committed)

    async def push_reclaim_entry(self, repo_id: str, entry: ReclaimEntry) -> None:
        """Record a dead run's staged inventory durably (before its fence is released)."""
        from server.indexing.generations import reclaim_backlog_from_meta

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                meta = _coerce_jsonb_dict(row["meta"]) if row is not None else {}
                backlog = [
                    e.model_dump(mode="json")
                    for e in reclaim_backlog_from_meta(meta, repo_id=repo_id)
                    if e.run_id != entry.run_id
                ]
                backlog.append(entry.model_dump(mode="json"))
                await conn.execute(
                    "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized({"reclaim_backlog": backlog}),
                )

    async def reclaim_backlog(self, repo_id: str) -> list[ReclaimEntry]:
        from server.indexing.generations import reclaim_backlog_from_meta

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT meta FROM corpora WHERE repo_id = $1;", repo_id)
        if row is None:
            return []
        return reclaim_backlog_from_meta(_coerce_jsonb_dict(row["meta"]), repo_id=repo_id)

    async def clear_reclaim_entry(self, repo_id: str, run_id: str) -> None:
        """The dead run's staged resources are confirmed gone: drop its backlog entry."""
        from server.indexing.generations import reclaim_backlog_from_meta

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                if row is None:
                    return
                meta = _coerce_jsonb_dict(row["meta"])
                backlog = [
                    e.model_dump(mode="json")
                    for e in reclaim_backlog_from_meta(meta, repo_id=repo_id)
                    if e.run_id != run_id
                ]
                await conn.execute(
                    "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized({"reclaim_backlog": backlog}),
                )

    async def record_fence_staging(
        self,
        repo_id: str,
        run_id: str,
        *,
        qdrant_collection: str | None = None,
        graph_repo_id: str | None = None,
    ) -> bool:
        """Name the resources a run is building on its fence (reclaimed exactly if the run dies)."""
        await self._require_pool()
        assert self._pool is not None
        patch: dict[str, Any] = {}
        if qdrant_collection is not None:
            patch["staged_qdrant_collection"] = qdrant_collection
        if graph_repo_id is not None:
            patch["staged_graph_repo_id"] = graph_repo_id
        if not patch:
            return True
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE corpora
                SET meta = jsonb_set(meta, '{index_run}', (meta->'index_run') || $3::jsonb)
                WHERE repo_id = $1 AND meta->'index_run'->>'run_id' = $2
                RETURNING 1;
                """,
                repo_id,
                run_id,
                _json_dumps_sanitized(patch),
            )
        return row is not None

    async def record_fence_phase(self, repo_id: str, run_id: str, phase: str) -> bool:
        """Durable run phase on the fence (e.g. ``retiring`` after the commit); False when not the holder."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE corpora
                SET meta = jsonb_set(meta, '{index_run,phase}', to_jsonb($3::text))
                WHERE repo_id = $1 AND meta->'index_run'->>'run_id' = $2
                RETURNING 1;
                """,
                repo_id,
                run_id,
                phase,
            )
        return row is not None

    @staticmethod
    async def heartbeat_index_fence_standalone(dsn: str, repo_id: str, run_id: str) -> bool:
        """Heartbeat over a DEDICATED connection (for a thread with its own event loop).

        The process-wide pool is bound to the API loop; a heartbeat thread must
        never touch it.
        """
        conn = await asyncpg.connect(PostgresClient._resolve_dsn(dsn))
        try:
            row = await conn.fetchrow(_HEARTBEAT_SQL, repo_id, run_id)
        finally:
            await conn.close()
        return row is not None

    async def heartbeat_index_fence(self, repo_id: str, run_id: str) -> bool:
        """Refresh the fence's heartbeat; False when this run no longer holds it."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_HEARTBEAT_SQL, repo_id, run_id)
        return row is not None

    async def release_index_fence(self, repo_id: str, run_id: str) -> bool:
        """Release the run slot, but only if this run still owns it; False when it did not."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE corpora
                SET meta = COALESCE(meta, '{}'::jsonb) - 'index_run'
                WHERE repo_id = $1 AND meta->'index_run'->>'run_id' = $2
                RETURNING 1;
                """,
                repo_id,
                run_id,
            )
        return row is not None

    async def set_generation_if_absent(self, repo_id: str, generation: GenerationManifest) -> bool:
        """Record a corpus's FIRST generation, under the per-corpus lock; False when one already exists.

        Used by incremental writers and the startup upgrade so two processes can
        never create competing first generations, and so an upgrade can never
        overwrite a manifest a promotion wrote meanwhile.
        """
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", repo_id)
                row = await conn.fetchrow(
                    """
                    UPDATE corpora
                    SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb
                    WHERE repo_id = $1
                      AND (meta->'generation') IS NULL
                      AND (meta->'index_tombstone') IS NULL
                    RETURNING 1;
                    """,
                    repo_id,
                    _json_dumps_sanitized({"generation": generation.model_dump(mode="json")}),
                )
        return row is not None

    async def replace_generation_if_shape(
        self, repo_id: str, generation: GenerationManifest, *, expected_keys: tuple[str, ...]
    ) -> bool:
        """Rewrite a manifest only while it still carries one of ``expected_keys`` (a shape upgrade)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", repo_id)
                row = await conn.fetchrow(
                    "SELECT meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                if row is None:
                    return False
                raw = _coerce_jsonb_dict(row["meta"]).get("generation")
                if not isinstance(raw, dict) or not any(k in raw for k in expected_keys):
                    return False
                await conn.execute(
                    "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized({"generation": generation.model_dump(mode="json")}),
                )
        return True

    async def prune_retired_generations(
        self, repo_id: str, run_id: str, *, dropped: list[RetiredGeneration]
    ) -> bool:
        _dropped = list(dropped)
        """Remove retired entries from the manifest after their stores were dropped.

        Only while the manifest still belongs to ``run_id`` (a newer commit owns
        its own retired list); False otherwise.
        """
        from server.indexing.generations import GenerationManifest as _Manifest

        await self._require_pool()
        assert self._pool is not None
        del dropped  # resources are matched below through GenerationManifest.without_resources
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                if row is None:
                    return False
                raw = _coerce_jsonb_dict(row["meta"]).get("generation")
                if not isinstance(raw, dict):
                    return False
                manifest = _Manifest.model_validate(raw)
                if manifest.run_id != run_id:
                    return False
                manifest.retired = manifest.without_resources(_dropped)
                await conn.execute(
                    "UPDATE corpora SET meta = COALESCE(meta, '{}'::jsonb) || $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized({"generation": manifest.model_dump(mode="json")}),
                )
        return True

    async def get_index_tombstone(self, repo_id: str) -> DeletionTombstone | None:
        """The row's tombstone through the strict reader: a malformed one raises, never reads as absent."""
        from server.indexing.generations import tombstone_from_meta

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT meta FROM corpora WHERE repo_id = $1;", repo_id)
        if row is None:
            return None
        return tombstone_from_meta(_coerce_jsonb_dict(row["meta"]), repo_id=repo_id)

    async def clear_index_tombstone(self, repo_id: str, tombstone: DeletionTombstone) -> bool:
        """Every external cleanup named by THIS tombstone succeeded: clear it, and only it.

        Compare-and-set on the tombstone's REVISION (minted on every write, merges
        included) so a newer tombstone is never cleared by an older cleanup that
        still holds a previous revision. False when the row carries a different
        tombstone or a corpus-delete tombstone.
        """
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE corpora
                SET meta = COALESCE(meta, '{}'::jsonb) - 'index_tombstone'
                WHERE repo_id = $1
                  AND meta->'index_tombstone'->>'revision' = $2
                  AND COALESCE(meta->'index_tombstone'->>'intent', 'deindex') = 'deindex'
                RETURNING 1;
                """,
                repo_id,
                tombstone.revision,
            )
        return row is not None

    async def delete_index_state(
        self,
        repo_id: str,
        *,
        allow_fence_run_id: str | None = None,
        lease_seconds: int,
        intent: Literal["deindex", "delete_corpus"] = "deindex",
    ) -> tuple[int, DeletionTombstone]:
        """De-index a corpus in Postgres in ONE transaction: chunk rows gone, manifest and contracts cleared.

        Runs before the external stores are touched so a failure there leaves a
        corpus that reads as never indexed (no manifest naming a dropped
        collection), never chunk rows paired with missing vectors. The exact
        Qdrant collections and Neo4j graph ids the manifest named (current and
        retired, merged with any earlier unfinished deletion) are recorded as a
        tombstone on the row so the external cleanup can be retried until it
        succeeds. A corpus fenced by a live run that is not ``allow_fence_run_id``
        is refused (``IndexFenceHeldError``); a stale fence is cleared.
        """
        from server.indexing.generations import (
            DeletionTombstone,
            IndexFenceHeldError,
            IndexRunFence,
            build_tombstone,
        )
        from server.indexing.generations import (
            GenerationManifest as _Manifest,
        )

        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", repo_id)
                row = await conn.fetchrow(
                    "SELECT meta, now() AS db_now FROM corpora WHERE repo_id = $1 FOR UPDATE;",
                    repo_id,
                )
                now: datetime = row["db_now"] if row is not None else datetime.now(UTC)
                meta = _coerce_jsonb_dict(row["meta"]) if row is not None else {}
                # De-indexing is the explicit repair path for malformed persisted
                # state: a fence, manifest or tombstone that does not validate is
                # cleared here (loudly), never silently read as absent anywhere else.
                raw_fence = meta.get("index_run")
                fence: IndexRunFence | None = None
                if raw_fence is not None:
                    try:
                        fence = IndexRunFence.model_validate(raw_fence)
                    except Exception:
                        logger.error(
                            "de-index of %s clears a malformed index-run fence: %r",
                            repo_id,
                            raw_fence,
                        )
                        fence = None
                    if (
                        fence is not None
                        and fence.run_id != allow_fence_run_id
                        and not fence.is_stale(now=now, lease_seconds=lease_seconds)
                    ):
                        raise IndexFenceHeldError(repo_id, fence)
                raw_generation = meta.get("generation")
                generation = None
                if raw_generation is not None:
                    try:
                        generation = _Manifest.model_validate(raw_generation)
                    except Exception:
                        logger.error(
                            "de-index of %s clears a malformed generation manifest (its external "
                            "targets are covered by the corpus namespace sweep): %r",
                            repo_id,
                            raw_generation,
                        )
                raw_tombstone = meta.get("index_tombstone")
                earlier = None
                if raw_tombstone is not None:
                    try:
                        earlier = DeletionTombstone.model_validate(raw_tombstone)
                    except Exception:
                        logger.error(
                            "de-index of %s replaces a malformed tombstone: %r",
                            repo_id,
                            raw_tombstone,
                        )
                tombstone = build_tombstone(generation, now=now, intent=intent).merged(earlier)
                # The reclaim backlog is absorbed here too: every entry that validates
                # hands its staged ids to the tombstone (and its staging rows are
                # dropped); the key is removed whatever shape it had, so de-index is
                # a repair path for it as well.
                from server.indexing.generations import ReclaimEntry as _ReclaimEntry
                from server.indexing.generations import staging_repo_id

                raw_backlog = meta.get("reclaim_backlog")
                backlog_collections: list[str] = []
                backlog_graphs: list[str] = []
                staging_tables = (
                    "chunk_summaries_last_build",
                    "chunk_summaries",
                    "chunks",
                    "corpus_configs",
                    "corpora",
                )
                if isinstance(raw_backlog, list):
                    for item in raw_backlog:
                        try:
                            entry = _ReclaimEntry.model_validate(item)
                        except Exception:
                            logger.error(
                                "de-index of %s drops a malformed reclaim entry: %r", repo_id, item
                            )
                            continue
                        if entry.staged_qdrant_collection:
                            backlog_collections.append(entry.staged_qdrant_collection)
                        if entry.staged_graph_repo_id:
                            backlog_graphs.append(entry.staged_graph_repo_id)
                        staged_id = staging_repo_id(repo_id, entry.run_id)
                        for table in staging_tables:
                            await conn.execute(
                                f"DELETE FROM {table} WHERE repo_id = $1;", staged_id
                            )
                elif raw_backlog is not None:
                    logger.error(
                        "de-index of %s drops a malformed reclaim backlog: %r", repo_id, raw_backlog
                    )
                # A fence still on the row here belongs to a dead run (a live one was
                # refused above): its staged inventory is the only record of those
                # ids, so it joins the tombstone exactly like a backlog entry.
                if fence is not None:
                    if fence.staged_qdrant_collection:
                        backlog_collections.append(fence.staged_qdrant_collection)
                    if fence.staged_graph_repo_id:
                        backlog_graphs.append(fence.staged_graph_repo_id)
                # Every staging row of THIS corpus goes too (dead runs whose fence or
                # backlog record was lost or malformed). Staging ids are
                # ``__staging__<corpus>__<run>`` and run ids never contain ``__``, so
                # the remainder after the prefix must be free of ``__``: corpus ``a``
                # never sweeps the staging rows of corpus ``a__b``.
                staging_prefix = staging_repo_id(repo_id, "")
                for table in staging_tables:
                    await conn.execute(
                        f"DELETE FROM {table} WHERE starts_with(repo_id, $1) "
                        "AND position('__' in substr(repo_id, length($1) + 1)) = 0;",
                        staging_prefix,
                    )
                if backlog_collections or backlog_graphs:
                    tombstone = DeletionTombstone(
                        qdrant_collections=list(
                            dict.fromkeys([*tombstone.qdrant_collections, *backlog_collections])
                        ),
                        graph_repo_ids=list(
                            dict.fromkeys([*tombstone.graph_repo_ids, *backlog_graphs])
                        ),
                        created_at=tombstone.created_at,
                        revision=tombstone.revision,
                        intent=tombstone.intent,
                    )

                deleted = await conn.fetchval(
                    "WITH d AS (DELETE FROM chunks WHERE repo_id = $1 RETURNING 1) SELECT count(*) FROM d;",
                    repo_id,
                )
                await conn.execute("DELETE FROM documents WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM chunk_summaries WHERE repo_id = $1;", repo_id)
                await conn.execute(
                    "DELETE FROM chunk_summaries_last_build WHERE repo_id = $1;", repo_id
                )
                if row is not None:
                    await conn.execute(
                        """
                        UPDATE corpora
                        SET last_indexed = NULL,
                            embedding_backend = NULL,
                            embedding_provider = NULL,
                            embedding_model = NULL,
                            embedding_dimensions = NULL,
                            sparse_contract = NULL,
                            meta = (COALESCE(meta, '{}'::jsonb) - 'generation' - 'index_run' - 'reclaim_backlog') || $2::jsonb
                        WHERE repo_id = $1;
                        """,
                        repo_id,
                        _json_dumps_sanitized(
                            {"index_tombstone": tombstone.model_dump(mode="json")}
                        ),
                    )
        return int(deleted or 0), tombstone

    async def update_corpus_meta(self, repo_id: str, meta: dict[str, Any]) -> None:
        await self._require_pool()
        assert self._pool is not None
        meta_json = _json_dumps_sanitized(meta or {})
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

    async def patch_corpus_meta_locked(self, repo_id: str, updates: dict[str, Any]) -> None:
        """Merge top-level corpus metadata while holding the corpus row lock."""
        if not isinstance(updates, dict):
            raise TypeError("corpus metadata updates must be a dict")
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT meta FROM corpora WHERE repo_id = $1 FOR UPDATE;", repo_id
                )
                if row is None:
                    from server.services.config_store import CorpusNotFoundError

                    raise CorpusNotFoundError(repo_id)
                merged = _coerce_jsonb_dict(row["meta"])
                merged.update(updates)
                await conn.execute(
                    "UPDATE corpora SET meta = $2::jsonb WHERE repo_id = $1;",
                    repo_id,
                    _json_dumps_sanitized(merged),
                )

    async def get_graph_schema_proposal(self, repo_id: str) -> GraphSchemaProposal | None:
        row = await self.get_corpus(repo_id)
        raw = ((row or {}).get("meta") or {}).get("graph_schema_proposal")
        return GraphSchemaProposal.model_validate(raw) if raw is not None else None

    async def set_graph_schema_proposal(
        self, repo_id: str, proposal: GraphSchemaProposal
    ) -> None:
        await self.patch_corpus_meta_locked(
            repo_id,
            {"graph_schema_proposal": proposal.model_dump(mode="json")},
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
                args.append(_sanitize_pg_text(name))
                idx += 1

            if path is not None:
                updates.append(f"root_path = ${idx}")
                args.append(_sanitize_pg_text(path))
                idx += 1

            if meta_updates:
                updates.append(f"meta = corpora.meta || ${idx}::jsonb")
                args.append(_json_dumps_sanitized(meta_updates))
                idx += 1

            if not updates:
                # Nothing to update, just return current row
                return await self.get_corpus(repo_id)

            query = f"""
                UPDATE corpora
                SET {", ".join(updates)}
                WHERE repo_id = $1
                RETURNING *;
            """
            row = await conn.fetchrow(query, *args)
            if not row:
                return None
            out = dict(row)
            # One row, one shape. The no-update branch above answers through `get_corpus`,
            # which renames `root_path` to `path`; a caller that had to read both shapes
            # would be a dual-read contract over the same table -- and did in fact raise
            # KeyError on whichever branch it had not been written against.
            # `RETURNING *` always includes root_path (NOT NULL), so pop it without a
            # default: a missing column must fail here, at the source, not surface later
            # as a silent path=None that only trips a Pydantic error far downstream.
            out["path"] = out.pop("root_path")
            out["meta"] = _coerce_jsonb_dict(out.get("meta"))
            return out

    async def delete_chunks(self, repo_id: str) -> int:
        """Hard-delete all chunks for a corpus (used for force_reindex)."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM documents WHERE repo_id = $1;", repo_id)
                result = await conn.execute("DELETE FROM chunks WHERE repo_id = $1;", repo_id)
        return int(result.split()[-1])

    async def delete_corpus_with_data(self, repo_id: str) -> None:
        """Delete a corpus row and all index data tied to it."""
        await self._require_pool()
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM chunk_summaries_last_build WHERE repo_id = $1;", repo_id
                )
                await conn.execute("DELETE FROM chunk_summaries WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM documents WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM chunks WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM corpus_configs WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM corpora WHERE repo_id = $1;", repo_id)

    async def promote_staging_index(
        self,
        *,
        active_repo_id: str,
        staging_repo_id: str,
        active_name: str,
        active_root_path: str,
        active_description: str | None = None,
        run_id: str,
        qdrant_collection: str | None,
        graph_repo_id: str | None,
        graph_metadata: GraphGenerationMetadata | None = None,
    ) -> GenerationManifest:
        """Atomically promote staged chunks/stats into the active corpus id.

        The same transaction records ``generation`` (the Qdrant collection and
        Neo4j graph id of this run) on the corpus row; readers of those stores
        resolve their physical targets from it, which is what makes the cutover
        atomic across all three stores. Returns the previous generation manifest
        so the caller can retire it after the commit.
        """
        await self._require_pool()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                staging = await conn.fetchrow(
                    """
                    SELECT repo_id, name, root_path, description, meta, last_indexed,
                           embedding_backend, embedding_provider, embedding_model, embedding_dimensions, sparse_contract
                    FROM corpora
                    WHERE repo_id = $1;
                    """,
                    staging_repo_id,
                )
                if not staging:
                    raise RuntimeError(f"Staging corpus not found: {staging_repo_id}")

                # The corpus row is locked for the whole commit and the per-corpus
                # advisory lock serialises this commit with incremental writers.
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1));", active_repo_id)
                active = await conn.fetchrow(
                    """
                    SELECT repo_id, name, root_path, description, meta
                    FROM corpora
                    WHERE repo_id = $1
                    FOR UPDATE;
                    """,
                    active_repo_id,
                )

                if active is None:
                    await self._ensure_corpus_row(
                        conn,
                        active_repo_id,
                        name=active_name or str(staging["name"] or active_repo_id),
                        root_path=active_root_path or str(staging["root_path"] or "."),
                        description=active_description
                        if active_description is not None
                        else str(staging["description"] or ""),
                        meta=_coerce_jsonb_dict(staging["meta"]),
                    )

                # Meta comes from the LOCKED row, never from a snapshot the caller
                # took earlier: the fence and any concurrent heartbeat live there.
                merged_meta = (
                    _coerce_jsonb_dict(active["meta"])
                    if active is not None
                    else _coerce_jsonb_dict(staging["meta"])
                )
                from server.indexing.generations import (
                    DeletionIncompleteError,
                    IndexFenceLostError,
                    IndexRunFence,
                    PersistedStateCorruptError,
                    build_generation,
                    tombstone_from_meta,
                )
                from server.indexing.generations import (
                    GenerationManifest as _Manifest,
                )

                raw_fence = merged_meta.get("index_run")
                holder = (
                    IndexRunFence.model_validate(raw_fence) if isinstance(raw_fence, dict) else None
                )
                if holder is None or holder.run_id != run_id:
                    # Released, taken over after a stale heartbeat, or cleared by a
                    # deletion: this run must not commit over someone else's corpus.
                    raise IndexFenceLostError(active_repo_id, run_id, holder)
                tombstone = tombstone_from_meta(merged_meta)
                if tombstone is not None:
                    raise DeletionIncompleteError(active_repo_id, tombstone)

                # The new manifest is built HERE, from the row-locked previous one:
                # a generation that appeared after the caller last looked (an
                # incremental first write) still joins the retired chain.
                raw_previous = merged_meta.get("generation")
                previous_generation = None
                if raw_previous is not None:
                    try:
                        previous_generation = _Manifest.model_validate(raw_previous)
                    except Exception as exc:
                        # A malformed manifest is never overwritten (its resources would
                        # be lost): de-index the corpus to repair it, then re-index.
                        raise PersistedStateCorruptError(
                            active_repo_id, "generation", raw_previous
                        ) from exc
                db_now: datetime = await conn.fetchval("SELECT now();")
                generation = build_generation(
                    run_id=run_id,
                    qdrant_collection=qdrant_collection,
                    graph_repo_id=graph_repo_id,
                    graph_metadata=graph_metadata,
                    previous=previous_generation,
                    now=db_now,
                )
                merged_meta["generation"] = generation.model_dump(mode="json")
                merged_meta.pop("internal_staging", None)

                await conn.execute("DELETE FROM chunks WHERE repo_id = $1;", active_repo_id)
                await conn.execute(
                    "UPDATE chunks SET repo_id = $1 WHERE repo_id = $2;",
                    active_repo_id,
                    staging_repo_id,
                )

                await conn.execute("DELETE FROM documents WHERE repo_id = $1;", active_repo_id)
                await conn.execute(
                    "UPDATE documents SET repo_id = $1 WHERE repo_id = $2;",
                    active_repo_id,
                    staging_repo_id,
                )

                await conn.execute(
                    "DELETE FROM chunk_summaries WHERE repo_id = $1;", active_repo_id
                )
                await conn.execute(
                    "UPDATE chunk_summaries SET repo_id = $1 WHERE repo_id = $2;",
                    active_repo_id,
                    staging_repo_id,
                )

                await conn.execute(
                    "DELETE FROM chunk_summaries_last_build WHERE repo_id = $1;", active_repo_id
                )
                await conn.execute(
                    "UPDATE chunk_summaries_last_build SET repo_id = $1 WHERE repo_id = $2;",
                    active_repo_id,
                    staging_repo_id,
                )

                await conn.execute(
                    """
                    UPDATE corpora
                    SET name = $2,
                        root_path = $3,
                        description = $4,
                        meta = $5::jsonb,
                        last_indexed = $6,
                        embedding_backend = $7,
                        embedding_provider = $8,
                        embedding_model = $9,
                        embedding_dimensions = $10,
                        sparse_contract = $11::jsonb
                    WHERE repo_id = $1;
                    """,
                    active_repo_id,
                    _sanitize_pg_text(
                        (active["name"] if active is not None else None)
                        or active_name
                        or staging["name"]
                        or active_repo_id
                    ),
                    _sanitize_pg_text(
                        (active["root_path"] if active is not None else None)
                        or active_root_path
                        or staging["root_path"]
                        or "."
                    ),
                    (
                        _sanitize_pg_text(active["description"])
                        if (active is not None and active["description"] is not None)
                        else _sanitize_optional_text(
                            active_description
                            if active_description is not None
                            else staging["description"]
                        )
                    ),
                    _json_dumps_sanitized(merged_meta),
                    staging["last_indexed"],
                    _sanitize_pg_text(staging["embedding_backend"] or ""),
                    _sanitize_pg_text(staging["embedding_provider"] or ""),
                    _sanitize_pg_text(staging["embedding_model"] or ""),
                    int(staging["embedding_dimensions"] or 0),
                    staging["sparse_contract"],
                )

                await conn.execute(
                    "DELETE FROM corpus_configs WHERE repo_id = $1;", staging_repo_id
                )
                await conn.execute("DELETE FROM corpora WHERE repo_id = $1;", staging_repo_id)
        return generation

    async def _ensure_corpus_row(
        self,
        conn: asyncpg.Connection,
        repo_id: str,
        *,
        name: str,
        root_path: str,
        description: str | None = None,
        meta: dict[str, Any] | None = None,
        preserve_identity: bool = False,
    ) -> None:
        """Insert the corpus row or update it.

        ``preserve_identity`` is for writers that only need the row to EXIST
        (chunk and summary writers): an existing row keeps its operator-given
        name and description, and the placeholder identity only fills an empty
        one. The registry upsert (an explicit rename) leaves it False.
        """
        meta_json = _json_dumps_sanitized(meta or {})
        if preserve_identity:
            identity_sql = """
              name = CASE
                WHEN corpora.name IS NULL OR corpora.name = '' THEN EXCLUDED.name
                ELSE corpora.name
              END,
              description = COALESCE(corpora.description, EXCLUDED.description),
            """
        else:
            identity_sql = """
              name = EXCLUDED.name,
              description = EXCLUDED.description,
            """
        await conn.execute(
            f"""
            INSERT INTO corpora (repo_id, name, root_path, description, meta)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (repo_id) DO UPDATE SET
              {identity_sql}
              root_path = CASE
                WHEN EXCLUDED.root_path IS NULL OR EXCLUDED.root_path = '' OR EXCLUDED.root_path = '.'
                  THEN corpora.root_path
                ELSE EXCLUDED.root_path
              END,
              meta = corpora.meta || EXCLUDED.meta;
            """,
            _sanitize_pg_text(repo_id),
            _sanitize_pg_text(name),
            _sanitize_pg_text(root_path),
            _sanitize_optional_text(description),
            meta_json,
        )

    async def _require_pool(self) -> None:
        if self._pool is None:
            await self.connect()
