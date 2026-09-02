"""The store-residue reaper deletes orphan test generations and nothing else.

Against live Postgres + Neo4j + Qdrant. Three corpora are planted with real
store residue (a staged Neo4j generation of two entities and one Qdrant
generation each):

- an orphan: test-prefixed, NO registry row -> its residue is reaped;
- a kept one: test-prefixed WITH a registry row (a concurrent session's corpus
  looks exactly like this while it runs) -> its residue survives;
- a control: no test prefix and no registry row (a leak the reaper has no
  business touching) -> its residue survives.

Every id here is created and removed by this test; the orphan and the kept one
are prefixed so a crash mid-test leaves only residue the reaper itself would
later clean up. The pre-existing non-test residue on the box (the operator's
generations included) is snapshotted and must survive the reap untouched.
"""

from __future__ import annotations

import contextlib
import os
import uuid

import pytest

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import STAGING_REPO_PREFIX, staging_repo_id
from server.retrieval.qdrant_store import QdrantChunkStore
from tests.corpus_reaper import (
    TEST_CORPUS_PREFIX,
    is_test_corpus_id,
    live_registry_ids,
    qdrant_test_collection_prefixes,
    reap_orphan_store_residue,
)
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]


async def _plant_staged_entities(neo4j: Neo4jClient, staged_id: str) -> None:
    driver = neo4j._require_driver()
    async with driver.session(database=neo4j.database) as session:
        for name in ("Halcyon reference brine", "Pelican gateway"):
            await session.run(
                "CREATE (:__Entity__ {repo_id: $repo_id, name: $name, id: $id})",
                repo_id=staged_id,
                name=name,
                id=f"{staged_id}:{name.lower().replace(' ', '-')}",
            )


async def _staged_ids(neo4j: Neo4jClient) -> set[str]:
    rows = await neo4j.execute_cypher(
        "MATCH (n) WHERE n.repo_id STARTS WITH $prefix RETURN DISTINCT n.repo_id AS repo_id;",
        {"prefix": STAGING_REPO_PREFIX},
    )
    return {str(row["repo_id"]) for row in rows}


def _collections(url: str) -> set[str]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=url, timeout=30)
    try:
        return {str(item.name) for item in client.get_collections().collections}
    finally:
        client.close()


async def test_reaper_deletes_orphan_residue_and_spares_registered_and_unprefixed() -> None:
    dsn = require_env("POSTGRES_DSN")
    cfg = load_config()
    suffix = uuid.uuid4().hex[:8]
    orphan = f"{TEST_CORPUS_PREFIX}reaper_orphan_{suffix}"  # test prefix, no row -> reaped
    kept = f"{TEST_CORPUS_PREFIX}reaper_kept_{suffix}"  # test prefix, row -> kept
    control = f"reaper-control-{suffix}"  # no test prefix, no row -> kept
    assert is_test_corpus_id(orphan) and is_test_corpus_id(kept)
    assert not is_test_corpus_id(control)
    staged = {cid: staging_repo_id(cid, uuid.uuid4().hex) for cid in (orphan, kept, control)}

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "password")
    neo4j_database = cfg.graph_storage.neo4j_database
    pg = PostgresClient(dsn)
    qdrant = QdrantChunkStore(cfg)
    neo4j = Neo4jClient(neo4j_uri, neo4j_user, neo4j_password, database=neo4j_database)
    collections: dict[str, str] = {}
    try:
        await pg.connect()
        await neo4j.connect()
        # The registry row goes in first: it is the rail that keeps a live corpus's residue.
        await pg.upsert_corpus(kept, name=kept, root_path=".")
        dim = int(cfg.embedding.embedding_dim)
        for cid in (orphan, kept, control):
            await _plant_staged_entities(neo4j, staged[cid])
            collections[cid] = await qdrant.create_generation(cid, embedding_dim=dim)
            assert (await neo4j.get_graph_stats(staged[cid])).total_entities == 2
            status = await qdrant.status(cid, physical=collections[cid])
            assert status is not None and status.physical_collection == collections[cid]

        registry_ids = await live_registry_ids(dsn)
        assert kept in registry_ids, registry_ids
        assert orphan not in registry_ids and control not in registry_ids, registry_ids

        # Everything else on the box that is NOT a test corpus's residue must survive.
        ours = set(staged.values()) | set(collections.values())
        non_test_staged_before = {
            sid for sid in await _staged_ids(neo4j) if not is_test_corpus_id(sid)
        } - ours
        non_test_collections_before = {
            name
            for name in _collections(qdrant.url)
            if not name.startswith(qdrant_test_collection_prefixes())
        } - ours
        assert collections[control] in non_test_collections_before | ours

        report = await reap_orphan_store_residue(
            registry_ids=registry_ids,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            qdrant_url=qdrant.url,
        )
        assert staged[orphan] in report["neo4j"], report
        assert staged[kept] not in report["neo4j"], report
        assert staged[control] not in report["neo4j"], report
        assert collections[orphan] in report["qdrant"], report
        assert collections[kept] not in report["qdrant"], report
        assert collections[control] not in report["qdrant"], report

        # Physically: the orphan's residue is gone, the other two are intact.
        assert (await neo4j.get_graph_stats(staged[orphan])).total_entities == 0
        assert (await neo4j.get_graph_stats(staged[kept])).total_entities == 2
        assert (await neo4j.get_graph_stats(staged[control])).total_entities == 2
        wiped = await qdrant.status(orphan, physical=collections[orphan])
        assert wiped is not None and wiped.physical_collection is None, wiped
        for cid in (kept, control):
            status = await qdrant.status(cid, physical=collections[cid])
            assert status is not None and status.physical_collection == collections[cid], cid
        staged_after = await _staged_ids(neo4j)
        assert non_test_staged_before <= staged_after, non_test_staged_before - staged_after
        collections_after = _collections(qdrant.url)
        assert non_test_collections_before <= collections_after, (
            non_test_collections_before - collections_after
        )

        # Idempotent: a second pass finds nothing of ours left and still spares the rest.
        again = await reap_orphan_store_residue(
            registry_ids=registry_ids,
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            qdrant_url=qdrant.url,
        )
        assert not (set(staged.values()) & set(again["neo4j"])), again
        assert not (set(collections.values()) & set(again["qdrant"])), again
        assert (await neo4j.get_graph_stats(staged[kept])).total_entities == 2
        assert (await neo4j.get_graph_stats(staged[control])).total_entities == 2
    finally:
        for cid in (orphan, kept, control):
            with contextlib.suppress(Exception):
                await neo4j.delete_graph(staged[cid])
            with contextlib.suppress(Exception):
                await qdrant.delete_corpus(cid)
        with contextlib.suppress(Exception):
            await neo4j.disconnect()
        with contextlib.suppress(Exception):
            await pg.delete_corpus_with_data(kept)
        with contextlib.suppress(Exception):
            await pg.disconnect()
