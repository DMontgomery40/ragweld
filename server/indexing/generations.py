"""The active-generation manifest: the single pointer that makes index promotion atomic.

Every full index run stages its output under a fresh generation in each store
(Postgres staging corpus rows, a physical Qdrant collection, a Neo4j graph under
the staging repo id). Promotion is ONE Postgres transaction that swaps the chunk
rows and writes this manifest on the corpus row; every reader of Qdrant and
Neo4j resolves the physical target from it. There is no per-store swap (no
Qdrant alias switch, no Neo4j relabel), so readers never observe new chunk rows
paired with old vectors or an old graph.

Retention: a commit moves the generation it replaces onto the manifest's
``retired`` list with a timestamp. A retired generation stays readable for the
operator's ``indexing.generation_retention_seconds`` (a reader that resolved
the old manifest before the commit keeps finding its collection and graph); a
later commit drops the entries whose grace has elapsed, by exact id, and prunes
them from the manifest. Each store is tracked on its own: a retired entry whose
collection is reused by the live generation still names its old graph for
cleanup. Nothing is ever swept by name prefix while a manifest is live.

Concurrency: a durable per-corpus run fence (``corpora.meta.index_run``) with an
owner, a heartbeat and a lease keeps two index runs from building and retiring
against the same corpus, survives a worker crash (a stale fence is taken over
and its staged resources reclaimed exactly), and is checked again, under row
lock, by the promotion transaction, which builds the new manifest from the
row-locked previous one. Incremental writers (recall, Codex ingest) write rows
and vectors inside one Postgres transaction that holds the same per-corpus
advisory lock, so they serialise with promotion and with each other.

Deletion: de-indexing records the exact Qdrant collections and Neo4j graph ids
it must drop as a tombstone on the corpus row before any external store is
touched. While the tombstone exists every reader and writer of the corpus
fails closed with a typed 503; it is cleared (compare-and-set on its own
timestamp) only when every external cleanup succeeded.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig

logger = logging.getLogger(__name__)

GENERATION_META_KEY = "generation"
INDEX_FENCE_META_KEY = "index_run"
INDEX_TOMBSTONE_META_KEY = "index_tombstone"


class RetiredGeneration(BaseModel):
    """A generation the manifest replaced; each store stays readable until its grace elapses."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    qdrant_collection: str | None = None
    graph_repo_id: str | None = None
    retired_at: datetime = Field(
        description="When the commit that replaced this generation happened."
    )

    def due(self, *, now: datetime, grace_seconds: int) -> bool:
        return self.retired_at + timedelta(seconds=max(0, int(grace_seconds))) <= now

    def masked(
        self, *, live_collection: str | None, live_graph: str | None
    ) -> RetiredGeneration | None:
        """This entry without any resource the live generation reuses; None when nothing is left."""
        collection = None if self.qdrant_collection == live_collection else self.qdrant_collection
        graph = None if self.graph_repo_id == live_graph else self.graph_repo_id
        if collection is None and graph is None:
            return None
        return self.model_copy(update={"qdrant_collection": collection, "graph_repo_id": graph})


class GenerationManifest(BaseModel):
    """Persisted on ``corpora.meta.generation`` (Postgres JSONB): the live generation of a corpus."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(
        min_length=1,
        description="Index run (or incremental/upgrade marker) that produced this generation.",
    )
    qdrant_collection: str | None = Field(
        default=None, description="Physical Qdrant collection holding the live vectors."
    )
    graph_repo_id: str | None = Field(
        default=None, description="repo_id under which the live Neo4j graph is stored."
    )
    promoted_at: datetime = Field(description="When the manifest was committed.")
    retired: list[RetiredGeneration] = Field(
        default_factory=list,
        description="Replaced generations still readable; dropped by exact id once their grace elapses.",
    )

    def due_for_retirement(self, *, now: datetime, grace_seconds: int) -> list[RetiredGeneration]:
        """Retired entries whose grace has elapsed, masked per resource.

        A collection or graph is droppable only when NOTHING alive still names
        it: not the live generation, and not another retired entry that is still
        inside its grace (two entries may share one resource when only the other
        store was rebuilt). Every resource keeps the latest expiry among its holders.
        """
        holders_alive_collections = {self.qdrant_collection} - {None}
        holders_alive_graphs = {self.graph_repo_id} - {None}
        for entry in self.retired:
            if not entry.due(now=now, grace_seconds=grace_seconds):
                holders_alive_collections.add(entry.qdrant_collection)
                holders_alive_graphs.add(entry.graph_repo_id)
        out: list[RetiredGeneration] = []
        for entry in self.retired:
            if not entry.due(now=now, grace_seconds=grace_seconds):
                continue
            collection = (
                None
                if entry.qdrant_collection in holders_alive_collections
                else entry.qdrant_collection
            )
            graph = None if entry.graph_repo_id in holders_alive_graphs else entry.graph_repo_id
            if collection is None and graph is None:
                continue
            out.append(
                entry.model_copy(update={"qdrant_collection": collection, "graph_repo_id": graph})
            )
        return out

    def without_resources(self, dropped: list[RetiredGeneration]) -> list[RetiredGeneration]:
        """The retired list after the given resources were dropped (entries with nothing left go)."""
        gone_collections = {d.qdrant_collection for d in dropped} - {None}
        gone_graphs = {d.graph_repo_id for d in dropped} - {None}
        kept: list[RetiredGeneration] = []
        for entry in self.retired:
            collection = (
                None if entry.qdrant_collection in gone_collections else entry.qdrant_collection
            )
            graph = None if entry.graph_repo_id in gone_graphs else entry.graph_repo_id
            if collection is None and graph is None:
                continue
            kept.append(
                entry.model_copy(update={"qdrant_collection": collection, "graph_repo_id": graph})
            )
        return kept

    def all_qdrant_collections(self) -> list[str]:
        out = [
            c for c in [self.qdrant_collection, *(r.qdrant_collection for r in self.retired)] if c
        ]
        return list(dict.fromkeys(out))

    def all_graph_repo_ids(self) -> list[str]:
        out = [g for g in [self.graph_repo_id, *(r.graph_repo_id for r in self.retired)] if g]
        return list(dict.fromkeys(out))


class IndexRunFence(BaseModel):
    """Persisted on ``corpora.meta.index_run``: the one index run allowed to build/commit for a corpus."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    owner: str = Field(min_length=1, description="Worker holding the fence (host:pid).")
    started_at: datetime
    heartbeat_at: datetime = Field(description="Database time of the last heartbeat.")
    staged_qdrant_collection: str | None = Field(
        default=None, description="Collection this run is building (reclaimed if the run dies)."
    )
    staged_graph_repo_id: str | None = Field(
        default=None, description="Graph id this run is building (reclaimed if the run dies)."
    )

    def is_stale(self, *, now: datetime, lease_seconds: int) -> bool:
        return self.heartbeat_at + timedelta(seconds=max(1, int(lease_seconds))) <= now


class FenceClaim(BaseModel):
    """Outcome of an acquire: the live holder that refused us, or the stale fence we took over."""

    model_config = ConfigDict(extra="forbid")

    held_by: IndexRunFence | None = None
    taken_over: IndexRunFence | None = None

    @property
    def acquired(self) -> bool:
        return self.held_by is None


class DeletionTombstone(BaseModel):
    """Persisted on ``corpora.meta.index_tombstone`` until every external cleanup succeeded."""

    model_config = ConfigDict(extra="forbid")

    qdrant_collections: list[str] = Field(default_factory=list)
    graph_repo_ids: list[str] = Field(default_factory=list)
    created_at: datetime

    def merged(self, other: DeletionTombstone | None) -> DeletionTombstone:
        if other is None:
            return self
        return DeletionTombstone(
            qdrant_collections=list(
                dict.fromkeys([*other.qdrant_collections, *self.qdrant_collections])
            ),
            graph_repo_ids=list(dict.fromkeys([*other.graph_repo_ids, *self.graph_repo_ids])),
            created_at=min(self.created_at, other.created_at),
        )


class IndexFenceHeldError(RuntimeError):
    """The corpus is fenced by a live index run that is not the caller's."""

    def __init__(self, repo_id: str, fence: IndexRunFence) -> None:
        self.repo_id = repo_id
        self.fence = fence
        super().__init__(
            f"Corpus {repo_id} is fenced by index run {fence.run_id} "
            f"(owner {fence.owner}, started {fence.started_at.isoformat()}, "
            f"last heartbeat {fence.heartbeat_at.isoformat()})"
        )


class IndexFenceLostError(RuntimeError):
    """A run tried to commit after its fence was released, taken over or cleared."""

    def __init__(self, repo_id: str, run_id: str, holder: IndexRunFence | None) -> None:
        self.repo_id = repo_id
        self.run_id = run_id
        self.holder = holder
        super().__init__(
            f"Index run {run_id} no longer holds the fence for corpus {repo_id} "
            f"(held by {holder.run_id + ' / ' + holder.owner if holder else 'nobody'}); refusing to commit"
        )


class IndexFenceCorruptError(RuntimeError):
    """``corpora.meta.index_run`` is present but not a valid fence (never read as absence)."""

    def __init__(self, repo_id: str, raw: Any) -> None:
        self.repo_id = repo_id
        self.raw = raw
        super().__init__(
            f"Corpus {repo_id} carries a malformed index-run fence; de-index the corpus to clear it: {raw!r}"
        )


class DeletionIncompleteError(RuntimeError):
    """The corpus is being de-indexed and its external cleanup has not completed (retry later)."""

    def __init__(self, repo_id: str, tombstone: DeletionTombstone) -> None:
        self.repo_id = repo_id
        self.tombstone = tombstone
        super().__init__(
            f"Corpus {repo_id} is being de-indexed; {len(tombstone.qdrant_collections)} collection(s) and "
            f"{len(tombstone.graph_repo_ids)} graph(s) still to drop (since {tombstone.created_at.isoformat()})"
        )


class PersistedStateCorruptError(RuntimeError):
    """A persisted boundary (manifest or tombstone) is present but not a valid shape; never read as absent."""

    def __init__(self, repo_id: str, key: str, raw: Any) -> None:
        self.repo_id = repo_id
        self.key = key
        self.raw = raw
        super().__init__(
            f"Corpus {repo_id} carries a malformed {key}; de-index the corpus to repair it: {raw!r}"
        )


class TombstoneCleanupError(RuntimeError):
    """An external store named by a deletion tombstone could not be cleaned (retry later)."""

    def __init__(self, dependency: str, operation: str, cause: BaseException) -> None:
        self.dependency = dependency
        self.operation = operation
        self.cause = cause
        super().__init__(f"{operation}: {dependency} cleanup failed: {cause}")


def fence_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def heartbeat_interval_seconds(lease_seconds: int) -> float:
    """Derived from the lease: ten beats per lease keep a live run far from takeover."""
    return max(1.0, float(lease_seconds) / 10.0)


def _dedupe_retired(entries: list[RetiredGeneration]) -> list[RetiredGeneration]:
    seen: set[tuple[str | None, str | None]] = set()
    out: list[RetiredGeneration] = []
    for entry in entries:
        key = (entry.qdrant_collection, entry.graph_repo_id)
        if key in seen or key == (None, None):
            continue
        seen.add(key)
        out.append(entry)
    return out


def build_generation(
    *,
    run_id: str,
    qdrant_collection: str | None,
    graph_repo_id: str | None,
    previous: GenerationManifest | None = None,
    now: datetime | None = None,
) -> GenerationManifest:
    """The manifest for a new live generation; ``previous`` (if any) joins the retired list.

    Resources the new generation reuses are masked out per store, never as a
    whole entry, so a replaced generation that shares one id with the new one
    still names its other store for cleanup. Entries are deduplicated by the
    pair of ids they name.
    """
    stamp = now or datetime.now(UTC)
    live_collection = str(qdrant_collection) if qdrant_collection else None
    live_graph = str(graph_repo_id) if graph_repo_id else None
    retired: list[RetiredGeneration] = list(previous.retired) if previous else []
    if previous is not None:
        retired.append(
            RetiredGeneration(
                run_id=previous.run_id,
                qdrant_collection=previous.qdrant_collection,
                graph_repo_id=previous.graph_repo_id,
                retired_at=stamp,
            )
        )
    masked = [
        m
        for m in (r.masked(live_collection=live_collection, live_graph=live_graph) for r in retired)
        if m is not None
    ]
    return GenerationManifest(
        run_id=str(run_id),
        qdrant_collection=live_collection,
        graph_repo_id=live_graph,
        promoted_at=stamp,
        retired=_dedupe_retired(masked),
    )


def tombstone_from_meta(
    meta: dict[str, Any] | None, *, repo_id: str = ""
) -> DeletionTombstone | None:
    """The deletion tombstone on a row's meta; a present-but-malformed one raises (never reads as absent)."""
    raw = meta.get(INDEX_TOMBSTONE_META_KEY) if isinstance(meta, dict) else None
    if raw is None:
        return None
    try:
        return DeletionTombstone.model_validate(raw)
    except Exception as exc:
        raise PersistedStateCorruptError(repo_id, INDEX_TOMBSTONE_META_KEY, raw) from exc


def generation_from_corpus_row(row: dict[str, Any] | None) -> GenerationManifest | None:
    """The manifest stored on a corpus row, or None when the corpus has no promoted generation.

    A corpus whose de-index tombstone is still being cleaned up raises
    ``DeletionIncompleteError``: readers and writers fail closed (typed 503)
    instead of reading an empty index while collections are half-dropped. A
    present-but-malformed manifest raises (loudly) instead of reading as
    unpromoted: that would silently disable retrieval for an indexed corpus.
    """
    if not row:
        return None
    repo_id = str(row.get("repo_id") or "")
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    tombstone = tombstone_from_meta(meta, repo_id=repo_id)
    if tombstone is not None:
        raise DeletionIncompleteError(repo_id, tombstone)
    generation = meta.get(GENERATION_META_KEY)
    if generation is None:
        return None
    try:
        return GenerationManifest.model_validate(generation)
    except Exception as exc:
        raise PersistedStateCorruptError(repo_id, GENERATION_META_KEY, generation) from exc


def qdrant_collection_of(generation: GenerationManifest | None) -> str | None:
    return generation.qdrant_collection if generation else None


def graph_repo_id_of(generation: GenerationManifest | None) -> str | None:
    return generation.graph_repo_id if generation else None


def build_tombstone(
    generation: GenerationManifest | None, *, now: datetime | None = None
) -> DeletionTombstone:
    return DeletionTombstone(
        qdrant_collections=generation.all_qdrant_collections() if generation else [],
        graph_repo_ids=generation.all_graph_repo_ids() if generation else [],
        created_at=now or datetime.now(UTC),
    )


async def drop_tombstoned_stores(
    config: TriBridConfig, repo_id: str, tombstone: DeletionTombstone
) -> int:
    """Drop every external resource a deletion tombstone names (plus the corpus's staged namespace).

    The tombstone blocks every writer of the corpus (no generation can appear
    while it exists), so the staged-namespace sweep can only meet collections
    of runs that died before de-indexing. Raises ``TombstoneCleanupError`` on
    the first store that fails; the caller keeps the tombstone so the next
    attempt retries exactly these targets. Returns the number of Qdrant
    collections removed.
    """
    from server.db.neo4j import Neo4jClient
    from server.retrieval.qdrant_store import QdrantChunkStore

    try:
        qdrant = QdrantChunkStore(config)
        removed = 0
        for collection in tombstone.qdrant_collections:
            removed += int(await qdrant.drop_generation(collection))
        removed += int(await qdrant.delete_corpus(repo_id) or 0)
    except Exception as exc:
        raise TombstoneCleanupError("qdrant", "Index deletion", exc) from exc
    try:
        neo4j = Neo4jClient(
            config.graph_storage.neo4j_uri,
            config.graph_storage.neo4j_user,
            config.graph_storage.resolve_password(),
            database=config.graph_storage.resolve_database(repo_id),
        )
        await neo4j.connect()
        try:
            for graph_id in dict.fromkeys([*tombstone.graph_repo_ids, repo_id]):
                await neo4j.delete_graph(graph_id)
            await neo4j.delete_staged_graphs(repo_id)
        finally:
            await neo4j.disconnect()
    except Exception as exc:
        raise TombstoneCleanupError("neo4j", "Index deletion", exc) from exc
    return int(removed or 0)


async def reclaim_stale_run(config: TriBridConfig, repo_id: str, fence: IndexRunFence) -> None:
    """Best-effort exact cleanup of a dead run's staged resources (its fence was taken over)."""
    from server.db.neo4j import Neo4jClient
    from server.retrieval.qdrant_store import QdrantChunkStore

    if fence.staged_qdrant_collection:
        try:
            await QdrantChunkStore(config).drop_generation(fence.staged_qdrant_collection)
        except Exception as exc:
            logger.warning(
                "reclaiming staged collection %s of dead run %s failed: %s",
                fence.staged_qdrant_collection,
                fence.run_id,
                exc,
            )
    if fence.staged_graph_repo_id:
        try:
            neo4j = Neo4jClient(
                config.graph_storage.neo4j_uri,
                config.graph_storage.neo4j_user,
                config.graph_storage.resolve_password(),
                database=config.graph_storage.resolve_database(repo_id),
            )
            await neo4j.connect()
            try:
                await neo4j.delete_graph(fence.staged_graph_repo_id)
            finally:
                await neo4j.disconnect()
        except Exception as exc:
            logger.warning(
                "reclaiming staged graph %s of dead run %s failed: %s",
                fence.staged_graph_repo_id,
                fence.run_id,
                exc,
            )


_PRE_RETENTION_KEYS = ("previous_qdrant_collection", "previous_graph_repo_id")


def upgrade_pre_retention_manifest(raw: dict[str, Any]) -> GenerationManifest | None:
    """One-time shape upgrade for manifests written before the ``retired`` list existed.

    Those carried a single ``previous_*`` slot. The slot becomes a retired entry
    stamped with the manifest's own promotion time; ids equal to the live ones
    are masked and an entry naming nothing is not added. Returns None when
    ``raw`` is not of that shape.
    """
    if not any(k in raw for k in _PRE_RETENTION_KEYS):
        return None
    body = {k: v for k, v in raw.items() if k not in _PRE_RETENTION_KEYS}
    manifest = GenerationManifest.model_validate(body)
    prev_collection = raw.get("previous_qdrant_collection")
    prev_graph = raw.get("previous_graph_repo_id")
    entry = RetiredGeneration(
        run_id=f"pre-retention-{manifest.run_id}",
        qdrant_collection=str(prev_collection) if prev_collection else None,
        graph_repo_id=str(prev_graph) if prev_graph else None,
        retired_at=manifest.promoted_at,
    ).masked(live_collection=manifest.qdrant_collection, live_graph=manifest.graph_repo_id)
    if entry is not None:
        manifest.retired.append(entry)
    manifest.retired = _dedupe_retired(manifest.retired)
    return manifest


_UPGRADE_STATE = {"complete": False, "failed": False}


def manifest_upgrade_complete() -> bool:
    """Whether the durable manifest upgrades ran to completion once in this process."""
    return bool(_UPGRADE_STATE["complete"])


def manifest_upgrade_blocked() -> bool:
    """An upgrade attempt failed and none has succeeded since: manifest routes must fail closed."""
    return bool(_UPGRADE_STATE["failed"]) and not bool(_UPGRADE_STATE["complete"])


async def ensure_generation_manifests(config: TriBridConfig) -> int:
    """Durable one-time upgrades for corpora written before the current manifest shape.

    * Corpora indexed before the manifest existed still route through a Qdrant
      alias and keep their graph under their own corpus id: that state is
      recorded as their manifest (set-if-absent under the corpus lock, so a
      promotion racing this upgrade can never be overwritten) and the alias is
      removed.
    * Manifests written with the single ``previous_*`` slot are rewritten with
      the ``retired`` list (same lock; only if the row still carries that shape).

    Idempotent: corpora already in the current shape are untouched. Returns the
    number of corpora changed and marks the upgrade complete for readiness.
    """
    from server.retrieval.qdrant_store import QdrantChunkStore

    pg = PostgresClient(config.indexing.postgres_url)
    await pg.connect()
    upgraded = 0
    try:
        qdrant = QdrantChunkStore(config)
        for row in await pg.list_corpora():
            repo_id = str(row.get("repo_id") or "").strip()
            if not repo_id or repo_id.startswith("__staging__"):
                continue
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            raw = meta.get(GENERATION_META_KEY)
            if isinstance(raw, dict):
                # Alias removal is its own idempotent step: a manifest recorded by an
                # earlier pass whose alias drop failed still loses its alias here.
                if await qdrant.legacy_alias_target(repo_id) is not None:
                    await qdrant.drop_legacy_alias(repo_id)
                upgraded_manifest = upgrade_pre_retention_manifest(raw)
                if upgraded_manifest is None:
                    continue
                if await pg.replace_generation_if_shape(
                    repo_id, upgraded_manifest, expected_keys=_PRE_RETENTION_KEYS
                ):
                    upgraded += 1
                    logger.info(
                        "generation manifest of %s upgraded to the retained-list shape", repo_id
                    )
                continue
            if tombstone_from_meta(meta) is not None:
                continue
            # A pre-manifest corpus is live iff its Qdrant alias still points at a
            # collection (an indexed corpus, or an incremental one that wrote
            # before the manifest existed). Anything else has nothing to point at:
            # it reads as unpromoted until it is indexed or written to.
            legacy = await qdrant.legacy_alias_target(repo_id)
            if legacy is None:
                continue
            recorded = await pg.set_generation_if_absent(
                repo_id,
                build_generation(
                    run_id=f"legacy-{repo_id}", qdrant_collection=legacy, graph_repo_id=repo_id
                ),
            )
            await qdrant.drop_legacy_alias(repo_id)
            if not recorded:
                # A full run promoted this corpus while we looked: its manifest wins.
                continue
            upgraded += 1
            logger.info(
                "generation manifest recorded for pre-manifest corpus %s (qdrant=%s)",
                repo_id,
                legacy,
            )
    except BaseException:
        _UPGRADE_STATE["failed"] = True
        raise
    finally:
        await pg.disconnect()
    _UPGRADE_STATE["complete"] = True
    _UPGRADE_STATE["failed"] = False
    return upgraded


async def ensure_generation_manifests_until_done(
    config: TriBridConfig, *, retry_seconds: float = 60.0
) -> None:
    """Run the upgrade until it succeeds once (stores may be down at startup); never blocks liveness."""
    while True:
        try:
            upgraded = await ensure_generation_manifests(config)
            if upgraded:
                logger.info("upgraded generation manifests for %d corpora", upgraded)
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "generation manifest upgrade not possible yet (readiness reports it pending); retrying in %ss: %s",
                retry_seconds,
                error,
            )
            await asyncio.sleep(retry_seconds)


__all__ = [
    "DeletionIncompleteError",
    "DeletionTombstone",
    "FenceClaim",
    "GenerationManifest",
    "IndexFenceCorruptError",
    "IndexFenceHeldError",
    "IndexFenceLostError",
    "IndexRunFence",
    "PersistedStateCorruptError",
    "RetiredGeneration",
    "TombstoneCleanupError",
    "ValidationError",
    "build_generation",
    "build_tombstone",
    "drop_tombstoned_stores",
    "ensure_generation_manifests",
    "ensure_generation_manifests_until_done",
    "fence_owner",
    "generation_from_corpus_row",
    "graph_repo_id_of",
    "heartbeat_interval_seconds",
    "manifest_upgrade_blocked",
    "manifest_upgrade_complete",
    "qdrant_collection_of",
    "reclaim_stale_run",
    "tombstone_from_meta",
    "upgrade_pre_retention_manifest",
]
