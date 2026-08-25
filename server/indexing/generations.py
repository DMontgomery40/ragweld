"""The active-generation manifest: the single pointer that makes index promotion atomic.

Every full index run stages its output under a fresh generation in each store
(Postgres staging corpus rows, a physical Qdrant collection, a Neo4j graph under
the staging repo id). Promotion is ONE Postgres transaction that swaps the chunk
rows and writes this manifest on the corpus row; every reader of Qdrant and
Neo4j resolves the physical target from it. There is no per-store swap (no
Qdrant alias switch, no Neo4j relabel), so readers never observe new chunk rows
paired with old vectors or an old graph. Superseded generations are retired
after the commit, best-effort.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import TriBridConfig

logger = logging.getLogger(__name__)

GENERATION_META_KEY = "generation"


def build_generation(*, run_id: str, qdrant_collection: str | None, graph_repo_id: str | None) -> dict[str, Any]:
    return {
        "run_id": str(run_id),
        "qdrant_collection": str(qdrant_collection) if qdrant_collection else None,
        "graph_repo_id": str(graph_repo_id) if graph_repo_id else None,
        "promoted_at": datetime.now(UTC).isoformat(),
    }


def generation_from_corpus_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    """The manifest stored on a corpus row, or None when the corpus has no promoted generation."""
    if not row:
        return None
    meta = row.get("meta")
    generation = meta.get(GENERATION_META_KEY) if isinstance(meta, dict) else None
    if isinstance(generation, dict) and str(generation.get("run_id") or "").strip():
        return dict(generation)
    return None


def qdrant_collection_of(generation: dict[str, Any] | None) -> str | None:
    value = (generation or {}).get("qdrant_collection")
    return str(value) if value else None


def graph_repo_id_of(generation: dict[str, Any] | None) -> str | None:
    value = (generation or {}).get("graph_repo_id")
    return str(value) if value else None


async def ensure_generation_manifests(config: TriBridConfig) -> int:
    """One-time upgrade for corpora indexed before the manifest existed.

    Such corpora still route through a Qdrant alias and keep their graph under
    their own corpus id. This records that state as their generation manifest
    (idempotent: corpora that already carry one are untouched) so readers can
    be strict afterwards. Returns the number of corpora upgraded.
    """
    from server.retrieval.qdrant_store import QdrantChunkStore

    pg = PostgresClient(config.indexing.postgres_url)
    await pg.connect()
    upgraded = 0
    try:
        qdrant = QdrantChunkStore(config)
        for row in await pg.list_corpora():
            repo_id = str(row.get("repo_id") or "").strip()
            if not repo_id or repo_id.startswith("__staging__") or generation_from_corpus_row(row) is not None:
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
                build_generation(run_id=f"legacy-{repo_id}", qdrant_collection=legacy, graph_repo_id=repo_id),
            )
            upgraded += 1
            logger.info("generation manifest recorded for pre-manifest corpus %s (qdrant=%s)", repo_id, legacy)
    finally:
        await pg.disconnect()
    return upgraded
