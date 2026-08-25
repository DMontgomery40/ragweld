"""The active-generation manifest: the single pointer that makes index promotion atomic.

Every full index run stages its output under a fresh generation in each store
(Postgres staging corpus rows, a physical Qdrant collection, a Neo4j graph under
the staging repo id). Promotion is ONE Postgres transaction that swaps the chunk
rows and writes this manifest on the corpus row; every reader of Qdrant and
Neo4j resolves the physical target from it. There is no per-store swap (no
Qdrant alias switch, no Neo4j relabel), so readers never observe new chunk rows
paired with old vectors or an old graph.

Retention is current + previous: a commit keeps the generation it replaces
alive (so a reader that resolved the manifest just before the commit still
finds its collection/graph) and retires the one before that. A durable
per-corpus run fence (also on the corpus row) keeps two index runs from
building and retiring against the same corpus at once.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig

logger = logging.getLogger(__name__)

GENERATION_META_KEY = "generation"
INDEX_FENCE_META_KEY = "index_run"


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
    previous_qdrant_collection: str | None = Field(
        default=None,
        description="Collection of the generation this one replaced (kept until the next commit).",
    )
    previous_graph_repo_id: str | None = Field(
        default=None,
        description="Graph id of the generation this one replaced (kept until the next commit).",
    )


class IndexRunFence(BaseModel):
    """Persisted on ``corpora.meta.index_run``: the one index run allowed to build/commit for a corpus."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    started_at: datetime


def build_generation(
    *,
    run_id: str,
    qdrant_collection: str | None,
    graph_repo_id: str | None,
    previous: GenerationManifest | None = None,
) -> GenerationManifest:
    return GenerationManifest(
        run_id=str(run_id),
        qdrant_collection=str(qdrant_collection) if qdrant_collection else None,
        graph_repo_id=str(graph_repo_id) if graph_repo_id else None,
        promoted_at=datetime.now(UTC),
        previous_qdrant_collection=previous.qdrant_collection if previous else None,
        previous_graph_repo_id=previous.graph_repo_id if previous else None,
    )


def generation_from_corpus_row(row: dict[str, Any] | None) -> GenerationManifest | None:
    """The manifest stored on a corpus row, or None when the corpus has no promoted generation.

    A present-but-malformed manifest raises (loudly) instead of reading as
    unpromoted: that would silently disable retrieval for an indexed corpus.
    """
    if not row:
        return None
    meta = row.get("meta")
    generation = meta.get(GENERATION_META_KEY) if isinstance(meta, dict) else None
    if generation is None:
        return None
    return GenerationManifest.model_validate(generation)


def qdrant_collection_of(generation: GenerationManifest | None) -> str | None:
    return generation.qdrant_collection if generation else None


def graph_repo_id_of(generation: GenerationManifest | None) -> str | None:
    return generation.graph_repo_id if generation else None


async def ensure_generation_manifests(config: TriBridConfig) -> int:
    """One-time upgrade for corpora indexed before the manifest existed.

    Such corpora still route through a Qdrant alias and keep their graph under
    their own corpus id. This records that state as their generation manifest
    and removes the alias (there are no aliases in the manifest world); corpora
    that already carry a manifest are untouched, so the call is idempotent.
    Returns the number of corpora upgraded.
    """
    from server.retrieval.qdrant_store import QdrantChunkStore

    pg = PostgresClient(config.indexing.postgres_url)
    await pg.connect()
    upgraded = 0
    try:
        qdrant = QdrantChunkStore(config)
        for row in await pg.list_corpora():
            repo_id = str(row.get("repo_id") or "").strip()
            if (
                not repo_id
                or repo_id.startswith("__staging__")
                or generation_from_corpus_row(row) is not None
            ):
                continue
            # A pre-manifest corpus is live iff its Qdrant alias still points at a
            # collection (an indexed corpus, or an incremental one that wrote
            # before the manifest existed). Anything else has nothing to point at:
            # it reads as unpromoted until it is indexed or written to.
            legacy = await qdrant.legacy_alias_target(repo_id)
            if legacy is None:
                continue
            await pg.set_generation(
                repo_id,
                build_generation(
                    run_id=f"legacy-{repo_id}", qdrant_collection=legacy, graph_repo_id=repo_id
                ),
            )
            await qdrant.drop_legacy_alias(repo_id)
            upgraded += 1
            logger.info(
                "generation manifest recorded for pre-manifest corpus %s (qdrant=%s)",
                repo_id,
                legacy,
            )
    finally:
        await pg.disconnect()
    return upgraded


async def ensure_generation_manifests_until_done(
    config: TriBridConfig, *, retry_seconds: float = 60.0
) -> None:
    """Run the upgrade until it succeeds once (stores may be down at startup); never blocks liveness."""
    while True:
        try:
            upgraded = await ensure_generation_manifests(config)
            if upgraded:
                logger.info("recorded generation manifests for %d pre-manifest corpora", upgraded)
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "generation manifest upgrade not possible yet (pre-manifest corpora read as unpromoted until it runs); retrying in %ss: %s",
                retry_seconds,
                error,
            )
            await asyncio.sleep(retry_seconds)
