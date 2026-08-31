"""Session-scoped reaper for leaked test corpora.

API tests create corpora against whatever registry the harness points at (the
box's live Postgres in this project). When a run aborts mid-test the row is
never deleted, and ~40 corpora leaked into the operator's live registry in one
wave this way. This reaper deletes stale test corpora at session start and end
so a crashed run's residue is cleaned up by the next run.

Two safety rails, because this runs against the operator's live Postgres:

- **Prefix.** Only rows whose `repo_id` starts with a recognized test-corpus
  prefix are ever touched. The operator's real corpora (``epstein-files-public``,
  ``nasa-apollo-11``, ``ragweld_code``, ``recall_default``) match none of them.
- **Age.** Only rows older than ``REAP_MAX_AGE_SECONDS`` are reaped, so a corpus
  a *concurrent* session created seconds ago on the shared box is never deleted
  out from under it.

Deletion goes through ``PostgresClient.delete_corpus_with_data`` — a pure
Postgres transaction — never ``DELETE /api/corpora``, which needs Neo4j
credentials the test process may lack and would 503 (leaving the row behind).
New fixtures should name corpora with :data:`TEST_CORPUS_PREFIX` so they fall
inside the reaper's match set.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

# The canonical prefix new corpus-creating fixtures should use.
TEST_CORPUS_PREFIX = "pytest_"

# The full set the reaper recognizes as test-generated. Kept deliberately narrow:
# every entry is a name the operator's real corpora never use. Adding a broad or
# ambiguous prefix here risks deleting production data.
TEST_CORPUS_PREFIXES: tuple[str, ...] = (
    "pytest_",
    "test_",
    "test-",
    "recall_test_",
    "ragweld-exhaustive-",
    "heartbeat-",
)

# A row younger than this may belong to a concurrently running session on the
# shared box, so it is left alone; the next session reaps it once it ages out.
REAP_MAX_AGE_SECONDS: float = 30 * 60


def is_test_corpus_id(repo_id: str) -> bool:
    """True when ``repo_id`` is a reap-eligible test corpus name."""
    return bool(repo_id) and repo_id.startswith(TEST_CORPUS_PREFIXES)


async def reap_stale_test_corpora(
    dsn: str,
    *,
    max_age_seconds: float = REAP_MAX_AGE_SECONDS,
) -> list[str]:
    """Delete stale test corpora reachable through ``dsn``; return the reaped ids.

    A row is reaped only when its id matches :func:`is_test_corpus_id` and it is
    at least ``max_age_seconds`` old. A row with no ``created_at`` is treated as
    too fresh and kept, never reaped on a guess.

    Uses a single raw asyncpg connection, not ``PostgresClient``: that client
    shares a process-wide asyncpg pool keyed by DSN, and a pool opened from the
    session-fixture context binds to the wrong event loop and breaks every live
    test that reuses the cached pool. A one-shot raw connection (the same shape
    ``probe_postgres`` uses) touches no shared state. The delete cascade mirrors
    ``PostgresClient.delete_corpus_with_data`` exactly: a Postgres-only, Neo4j-free
    cascade over every table keyed by ``repo_id`` (never ``DELETE /api/corpora``,
    which needs Neo4j credentials the test process may lack).
    """
    import asyncpg

    cutoff = datetime.now(UTC) - timedelta(seconds=max_age_seconds)
    stale: list[str] = []
    reaped: list[str] = []
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT repo_id, created_at FROM corpora;")
        for row in rows:
            repo_id = str(row["repo_id"] or "")
            if not is_test_corpus_id(repo_id):
                continue
            created = row["created_at"]
            if not isinstance(created, datetime):
                continue  # cannot verify age -> never reap on a guess
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created > cutoff:
                continue  # too fresh; a concurrent session may own it
            stale.append(repo_id)

        for repo_id in stale:
            async with conn.transaction():
                await conn.execute("DELETE FROM chunk_summaries_last_build WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM chunk_summaries WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM documents WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM chunks WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM corpus_configs WHERE repo_id = $1;", repo_id)
                await conn.execute("DELETE FROM corpora WHERE repo_id = $1;", repo_id)
            reaped.append(repo_id)
    finally:
        await conn.close()
    return reaped


def reaper_dsn() -> str | None:
    """Best-effort Postgres DSN for the reaper, or None when unconfigured.

    Prefers ``POSTGRES_DSN`` (what the harness composes), else composes one from
    ``POSTGRES_HOST`` and friends the way the service probe does. Returns None
    when neither is present, so the reaper simply no-ops on an unconfigured box.
    """
    dsn = (os.environ.get("POSTGRES_DSN") or "").strip()
    if dsn:
        return dsn
    host = (os.environ.get("POSTGRES_HOST") or "").strip()
    if not host:
        return None
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")
    port = os.environ.get("POSTGRES_PORT", "5432")
    database = os.environ.get("POSTGRES_DB", "tribrid_rag")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def reap_quietly(*, max_age_seconds: float = REAP_MAX_AGE_SECONDS) -> list[str]:
    """Run the reaper best-effort, swallowing every failure.

    Cleanup must never fail a test session: an unreachable or unconfigured
    Postgres, or a delete that races another writer, all resolve to "reaped
    nothing". Returns the ids actually reaped (possibly empty).

    `asyncio.run` here is safe because `reap_stale_test_corpora` uses only a raw
    one-shot asyncpg connection (no shared pool), the same pattern
    `probe_postgres` already runs at collection time — nothing is left bound to
    the throwaway loop.
    """
    dsn = reaper_dsn()
    if not dsn:
        return []
    try:
        # Probe first so an unconfigured/unreachable box no-ops fast instead of
        # waiting out a connect, and reuse the suite's one availability check.
        from tests.service_requirements import probe_postgres

        if not probe_postgres().available:
            return []
        return asyncio.run(reap_stale_test_corpora(dsn, max_age_seconds=max_age_seconds))
    except Exception:
        return []
