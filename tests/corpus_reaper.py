"""Session-scoped reaper for leaked test corpora and their store residue.

API tests create corpora against whatever registry the harness points at (the
box's live Postgres in this project) and index them for real into Qdrant and
Neo4j. When a run aborts mid-test the registry row is never deleted (~40 corpora
leaked into the operator's live registry in one wave this way), and the Qdrant
collections and staged Neo4j generations written for the corpus outlive even a
deleted row, because every failure-path cleanup was Postgres-only. This reaper
runs at session start and end so a crashed run's residue is cleaned up by the
next run, in all three stores.

Safety rails, because this runs against the operator's live stores:

- **Prefix.** Only ids that start with a recognized test-corpus prefix are ever
  touched, in every form the id takes: the registry row, its staged generation
  (``__staging__<corpus>__<run>``) and its Qdrant collections
  (``ragweld_chunks_<slug>_<hash>__<generation>``). The operator's real corpora
  (``epstein-files-public``, ``nasa-apollo-11``, ``ragweld_code``,
  ``recall_default``) match none of them in any form.
- **Age** (registry rows). Only rows older than ``REAP_MAX_AGE_SECONDS`` are
  reaped, so a corpus a *concurrent* session created seconds ago on the shared
  box is never deleted out from under it.
- **No registry row** (store residue). Neo4j nodes and Qdrant collections carry
  no timestamp, so their rail is the registry itself: every store-writing test
  creates its ``corpora`` row before it writes a generation, so a test corpus a
  concurrent session is using always has its row, and residue whose corpus has
  NO row belongs to a run that is over. The store reap runs only after the
  registry was read successfully; no registry, no store reap.

Deletion goes through ``PostgresClient.delete_corpus_with_data``'s cascade,
``Neo4jClient.delete_staged_graphs`` and the Qdrant collection API directly,
never ``DELETE /api/corpora``, which needs every store up and would 503
(leaving the row behind). New fixtures should name corpora with
:data:`TEST_CORPUS_PREFIX` so they fall inside the reaper's match set.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from server.indexing.generations import STAGING_REPO_PREFIX
from server.retrieval.qdrant_store import _COLLECTION_PREFIX, corpus_collection_prefix

# The canonical prefix new corpus-creating fixtures should use.
TEST_CORPUS_PREFIX = "pytest_"

# The full set the reaper recognizes as test-generated. Kept deliberately narrow:
# every entry is a name the operator's real corpora never use. Adding a broad or
# ambiguous prefix here risks deleting production data. ``promoted-lane-`` and
# ``relroot_`` are the pre-rename names of tests/integration/test_index_promoted_lane.py
# and tests/api/test_index_relative_corpus_root.py (now ``pytest_promoted_lane_`` /
# ``pytest_relroot_``): they stay listed so residue from older runs is reapable.
TEST_CORPUS_PREFIXES: tuple[str, ...] = (
    "pytest_",
    "test_",
    "test-",
    "recall_test_",
    "ragweld-exhaustive-",
    "heartbeat-",
    "promoted-lane-",
    "relroot_",
)

# A row younger than this may belong to a concurrently running session on the
# shared box, so it is left alone; the next session reaps it once it ages out.
REAP_MAX_AGE_SECONDS: float = 30 * 60


def staged_corpus_of(repo_id: str) -> str | None:
    """The corpus a ``__staging__<corpus>__<run>`` id belongs to, else None.

    Run ids never contain ``__`` (``Neo4jClient.delete_staged_graphs`` and the
    Postgres staging sweep rely on the same fact), so the corpus is everything
    before the LAST ``__``: ``__staging__a__b__<run>`` belongs to corpus ``a__b``.
    """
    text = str(repo_id or "")
    if not text.startswith(STAGING_REPO_PREFIX):
        return None
    corpus, separator, run = text[len(STAGING_REPO_PREFIX) :].rpartition("__")
    if not separator or not corpus or not run:
        return None
    return corpus


def is_test_corpus_id(repo_id: str) -> bool:
    """True when ``repo_id`` is a reap-eligible test corpus name.

    A staged generation of a test corpus (``__staging__<corpus>__<run>``, the id
    a run stages its Postgres rows and Neo4j graph under) is test residue too.
    """
    text = str(repo_id or "")
    if not text:
        return False
    staged = staged_corpus_of(text)
    if staged is not None:
        return staged.startswith(TEST_CORPUS_PREFIXES)
    return text.startswith(TEST_CORPUS_PREFIXES)


def qdrant_test_collection_prefixes() -> tuple[str, ...]:
    """Collection-name prefixes every test corpus's Qdrant generations start with.

    ``corpus_collection_prefix`` rewrites the corpus id (each run of anything
    but ``[A-Za-z0-9_]`` becomes one ``_``, lowercased) before appending a hash
    of the exact id, so a test prefix must be mapped the same way. The hash makes
    reverse-mapping a collection to its corpus impossible, which is why orphan
    detection compares against the prefixes of every LIVE registry corpus rather
    than parsing the name.
    """
    return tuple(
        f"{_COLLECTION_PREFIX}{re.sub(r'[^A-Za-z0-9_]+', '_', prefix).lower()}"
        for prefix in TEST_CORPUS_PREFIXES
    )


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


async def live_registry_ids(dsn: str) -> set[str]:
    """Every ``corpora.repo_id`` reachable through ``dsn`` (the store reap's safety rail).

    Same one-shot raw asyncpg connection as :func:`reap_stale_test_corpora`, for
    the same event-loop reason.
    """
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT repo_id FROM corpora;")
    finally:
        await conn.close()
    return {str(row["repo_id"]) for row in rows if row["repo_id"]}


async def _reap_neo4j_orphan_generations(
    *,
    uri: str,
    user: str,
    password: str,
    database: str | None,
    registry_ids: set[str],
) -> list[str]:
    """Delete every staged generation of a test corpus that has no registry row.

    Lists the distinct ``__staging__*`` repo_ids present, keeps only those whose
    corpus is test-prefixed AND absent from ``registry_ids``, and removes them
    with ``Neo4jClient.delete_staged_graphs`` (the production, batched sweep of
    one corpus's staged generations). Returns the staged ids removed.
    """
    from server.db.neo4j import Neo4jClient

    client = Neo4jClient(uri, user, password, database=database)
    await client.connect()
    try:
        rows = await client.execute_cypher(
            "MATCH (n) WHERE n.repo_id STARTS WITH $prefix "
            "RETURN DISTINCT n.repo_id AS repo_id;",
            {"prefix": STAGING_REPO_PREFIX},
        )
        orphans: dict[str, list[str]] = {}
        for row in rows:
            staged = str(row.get("repo_id") or "")
            corpus = staged_corpus_of(staged)
            if corpus is None or not is_test_corpus_id(corpus) or corpus in registry_ids:
                continue
            orphans.setdefault(corpus, []).append(staged)
        reaped: list[str] = []
        for corpus in sorted(orphans):
            await client.delete_staged_graphs(corpus)
            reaped.extend(sorted(orphans[corpus]))
        return reaped
    finally:
        await client.disconnect()


def _reap_qdrant_orphan_collections(*, url: str, registry_ids: set[str]) -> list[str]:
    """Delete every test-prefixed collection that belongs to no registry corpus.

    A collection is a candidate when its name starts with a test prefix mapped
    the way ``corpus_collection_prefix`` maps it; it is kept when it is a
    generation (or the legacy alias) of ANY live registry corpus, computed with
    the same function. Returns the collection names removed.
    """
    from qdrant_client import QdrantClient

    live_prefixes = {corpus_collection_prefix(cid) for cid in registry_ids if cid}
    test_prefixes = qdrant_test_collection_prefixes()
    client = QdrantClient(url=url, timeout=30)
    try:
        reaped: list[str] = []
        for collection in list(client.get_collections().collections):
            name = str(collection.name)
            if not name.startswith(test_prefixes):
                continue
            if any(name == live or name.startswith(f"{live}__") for live in live_prefixes):
                continue
            client.delete_collection(name)
            reaped.append(name)
        return sorted(reaped)
    finally:
        client.close()


async def reap_orphan_store_residue(
    *,
    registry_ids: set[str],
    neo4j_uri: str | None,
    qdrant_url: str | None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
    neo4j_database: str | None = None,
) -> dict[str, list[str]]:
    """Delete Neo4j and Qdrant residue of test corpora that have no registry row.

    ``registry_ids`` is the complete set of live ``corpora.repo_id`` values (see
    :func:`live_registry_ids`); it is the only thing that separates a concurrent
    session's in-flight corpus from a dead run's leftovers, so callers must pass
    the real registry, never a guess. A store whose address is ``None`` is
    skipped. Returns ``{"neo4j": [staged ids removed], "qdrant": [collections
    removed]}``; failures propagate (``reap_quietly`` is the best-effort wrapper).
    """
    report: dict[str, list[str]] = {"neo4j": [], "qdrant": []}
    if neo4j_uri:
        report["neo4j"] = await _reap_neo4j_orphan_generations(
            uri=neo4j_uri,
            user=neo4j_user or "neo4j",
            password=neo4j_password or "password",
            database=neo4j_database,
            registry_ids=registry_ids,
        )
    if qdrant_url:
        report["qdrant"] = await asyncio.to_thread(
            _reap_qdrant_orphan_collections, url=qdrant_url, registry_ids=registry_ids
        )
    return report


def reaper_dsn() -> str | None:
    """Best-effort Postgres DSN for the reaper, or None when unconfigured.

    Prefers ``POSTGRES_DSN`` (what the harness composes), else composes one from
    ``POSTGRES_HOST`` and friends the way the service probe does. Returns None
    when neither is present, so the reaper simply no-ops on an unconfigured box.
    """
    from tests.service_requirements import postgres_dsn_from_env

    return postgres_dsn_from_env()


@dataclass(frozen=True)
class ReapReport:
    """What one best-effort reap removed, per store (each list possibly empty)."""

    corpora: list[str] = field(default_factory=list)  # registry rows, Postgres cascade
    neo4j: list[str] = field(default_factory=list)  # orphan staged generations
    qdrant: list[str] = field(default_factory=list)  # orphan collections


def reap_quietly(*, max_age_seconds: float = REAP_MAX_AGE_SECONDS) -> ReapReport:
    """Run the reaper best-effort, swallowing every failure.

    Cleanup must never fail a test session: an unreachable or unconfigured
    store, or a delete that races another writer, all resolve to "reaped
    nothing" for that store. The registry reap runs first; the store reaps run
    only once the registry was read successfully (its rows are their safety
    rail), each in its own guard so one store's outage never skips the other.

    `asyncio.run` here is safe because every step uses one-shot connections (a
    raw asyncpg connection, a per-call Neo4j driver, a per-call Qdrant client),
    the same pattern the service probes already run at collection time; nothing
    is left bound to the throwaway loop.
    """
    from tests.service_requirements import (
        probe_neo4j,
        probe_postgres,
        probe_qdrant,
        qdrant_url_from_env,
    )

    report = ReapReport()
    dsn = reaper_dsn()
    if not dsn:
        return report
    try:
        # Probe first so an unconfigured/unreachable box no-ops fast instead of
        # waiting out a connect, and reuse the suite's one availability check.
        if not probe_postgres().available:
            return report
        report.corpora.extend(asyncio.run(reap_stale_test_corpora(dsn, max_age_seconds=max_age_seconds)))
        registry_ids = asyncio.run(live_registry_ids(dsn))
    except Exception:
        return report
    neo4j_uri = os.environ.get("NEO4J_URI")
    try:
        if neo4j_uri and probe_neo4j().available:
            report.neo4j.extend(
                asyncio.run(
                    reap_orphan_store_residue(
                        registry_ids=registry_ids,
                        neo4j_uri=neo4j_uri,
                        neo4j_user=os.environ.get("NEO4J_USER"),
                        neo4j_password=os.environ.get("NEO4J_PASSWORD"),
                        neo4j_database=os.environ.get("NEO4J_DATABASE"),
                        qdrant_url=None,
                    )
                )["neo4j"]
            )
    except Exception:
        pass
    try:
        if probe_qdrant().available:
            report.qdrant.extend(
                asyncio.run(
                    reap_orphan_store_residue(
                        registry_ids=registry_ids,
                        neo4j_uri=None,
                        qdrant_url=qdrant_url_from_env(),
                    )
                )["qdrant"]
            )
    except Exception:
        pass
    return report
