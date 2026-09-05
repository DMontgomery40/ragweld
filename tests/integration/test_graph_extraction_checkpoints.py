"""Real Postgres contracts for durable, corpus-owned extraction checkpoints."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, time, timedelta, timezone

import asyncpg
import pytest
import pytest_asyncio
from neo4j_graphrag.components.schema import GraphSchema, PropertyType
from neo4j_graphrag.components.types import GeoPoint, Neo4jGraph, Neo4jNode, Neo4jRelationship
from pydantic import ValidationError

from server.db.postgres import PostgresClient
from server.gateway_reasoning import reasoning_model_params
from server.indexing.generations import staging_repo_id
from server.indexing.graphrag_schema import closed_graph_schema
from server.models.graph_extraction_checkpoint import (
    GraphExtractionCheckpoint,
    GraphExtractionCheckpointConflictError,
    GraphExtractionCheckpointCorruptError,
    GraphExtractionCheckpointError,
    GraphExtractionCheckpointIdentity,
    GraphExtractionCheckpointRecipe,
    graph_extraction_cache_key,
    graph_extraction_recipe_hash,
)
from server.models.index import ChunkProvenance
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _recipe() -> GraphExtractionCheckpointRecipe:
    return GraphExtractionCheckpointRecipe(
        approved_schema=GraphSchema(
            node_types=["Mission", "Spacecraft"], relationship_types=["USED"],
            patterns=[("Mission", "USED", "Spacecraft")],
            additional_node_types=False, additional_relationship_types=False,
            additional_patterns=False,
        ),
        prompt_template_sha256=_digest("Extract the approved mission graph: {schema} {text}"),
        examples_sha256=_digest(""),
        model_alias="fixture-semantic", model_upstream="openrouter/openai/fixture-model",
        model_endpoint="http://litellm:4000/v1",
        model_parameters={"temperature": 0, "extra_body": {"reasoning": {"effort": "none"}}},
        neo4j_graphrag_version="1.19.0", extractor_version="official-extraction-v1",
        pruner_version="official-pruning-v1",
    )


def _checkpoint(
    repo_id: str, run_id: str, *, file_path: str = "A11_MissionReport.pdf",
    chunk_index: int = 0, recipe: GraphExtractionCheckpointRecipe | None = None,
    empty: bool = False,
) -> GraphExtractionCheckpoint:
    identity = GraphExtractionCheckpointIdentity(
        repo_id=repo_id, file_path=file_path, file_sha256=_digest(file_path),
        chunk_id=f"{file_path}:chunk:{chunk_index}", chunk_index=chunk_index,
        chunk_content_sha256=_digest(f"Apollo 11 used Eagle. Section {chunk_index}"),
        chunk_metadata_sha256=_digest("{}"), start_line=1, end_line=3,
        chunk_provenance=ChunkProvenance(extraction="docling"),
        rendered_prompt_sha256=_digest(f"approved-schema Apollo 11 used Eagle {chunk_index}"),
        recipe=recipe or _recipe(),
    )
    graph = Neo4jGraph() if empty else Neo4jGraph(
        nodes=[
            Neo4jNode(id="mission", label="Mission", properties={"name": "Apollo 11"}),
            Neo4jNode(id="spacecraft", label="Spacecraft", properties={"name": "Eagle"}),
        ],
        relationships=[Neo4jRelationship(
            start_node_id="mission", end_node_id="spacecraft", type="USED",
        )],
    )
    return GraphExtractionCheckpoint(
        identity=identity, cache_key=graph_extraction_cache_key(identity), graph=graph,
        originating_run_id=run_id, created_at=datetime.now(UTC),
        pruned_nodes=0, pruned_relationships=0,
    )


@pytest_asyncio.fixture
async def checkpoint_store() -> AsyncIterator[tuple[PostgresClient, str, str]]:
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    repo_id, run_id = f"pytest_checkpoint_{uuid.uuid4().hex}", uuid.uuid4().hex
    await pg.connect()
    await pg.upsert_corpus(repo_id, name="Apollo mission checkpoint fixture", root_path=".")
    claim = await pg.acquire_index_fence(
        repo_id, run_id, started_at=datetime.now(UTC), owner="pytest:checkpoint",
        lease_seconds=3600,
    )
    assert claim.acquired
    try:
        yield pg, repo_id, run_id
    finally:
        await pg.delete_corpus_with_data(repo_id)
        await pg.disconnect()


async def _prepare(pg: PostgresClient, checkpoint: GraphExtractionCheckpoint) -> None:
    await pg.prepare_graph_extraction_checkpoint_file(
        checkpoint.identity.repo_id, checkpoint.originating_run_id,
        graph_extraction_recipe_hash(checkpoint.identity.recipe),
        checkpoint.identity.file_path, [checkpoint.cache_key],
    )


@pytest.mark.parametrize("empty", [False, True])
async def test_checkpoint_roundtrip_and_idempotence_preserve_the_original_record(
    checkpoint_store: tuple[PostgresClient, str, str], empty: bool,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id, empty=empty)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) is None
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    later = checkpoint.model_copy(update={"created_at": checkpoint.created_at + timedelta(hours=1)})
    await asyncio.gather(*[
        pg.put_graph_extraction_checkpoint(repo_id, run_id, later) for _ in range(3)
    ])
    stored = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert stored == checkpoint
    assert isinstance(stored.graph, Neo4jGraph)
    if stored.graph.nodes:
        stored.graph.nodes[0].properties["name"] = "mutated local copy"
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


@pytest.mark.parametrize("conflict", ["graph", "pruned_nodes", "pruned_relationships"])
async def test_conflicting_checkpoint_never_overwrites_first_validated_result(
    checkpoint_store: tuple[PostgresClient, str, str], conflict: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    changed = checkpoint.model_copy(deep=True)
    if conflict == "graph":
        changed.graph.nodes[0].properties["name"] = "Apollo 12"
    else:
        changed = changed.model_copy(update={conflict: 1})
    with pytest.raises(GraphExtractionCheckpointConflictError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, changed)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


@pytest.mark.parametrize("invalid", ["corpus", "cache_key", "origin", "staging_corpus"])
async def test_write_revalidates_untrusted_or_mutated_envelopes(
    checkpoint_store: tuple[PostgresClient, str, str], invalid: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    target = repo_id
    if invalid == "corpus":
        target = f"{repo_id}__sibling"
    elif invalid == "staging_corpus":
        target = staging_repo_id(repo_id, run_id)
    elif invalid == "cache_key":
        checkpoint = checkpoint.model_copy(update={"cache_key": "0" * 64})
    else:
        checkpoint = checkpoint.model_copy(update={"originating_run_id": uuid.uuid4().hex})
    with pytest.raises((GraphExtractionCheckpointError, ValidationError, ValueError)):
        await pg.put_graph_extraction_checkpoint(target, run_id, checkpoint)
    assert await pg.get_graph_extraction_checkpoint(repo_id, graph_extraction_cache_key(checkpoint.identity)) is None


@pytest.mark.parametrize("corruption", [
    "missing_identity", "missing_graph", "incomplete_graph", "invalid_node", "extra_envelope",
    "wrong_corpus", "wrong_key", "wrong_file_column", "wrong_recipe_column",
    "scoped_node", "scoped_relationship", "scoped_embedding", "negative_pruning", "non_object",
])
async def test_corrupt_rows_fail_closed_on_read_and_duplicate_write(
    checkpoint_store: tuple[PostgresClient, str, str], corruption: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    payload = checkpoint.model_dump(mode="json")
    file_path = checkpoint.identity.file_path
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    if corruption == "missing_identity":
        del payload["identity"]
    elif corruption == "missing_graph":
        del payload["graph"]
    elif corruption == "incomplete_graph":
        del payload["graph"]["nodes"]
    elif corruption == "invalid_node":
        payload["graph"]["nodes"][0].pop("label")
    elif corruption == "extra_envelope":
        payload["raw_response"] = "unvalidated provider output"
    elif corruption == "wrong_corpus":
        payload["identity"]["repo_id"] = f"{repo_id}__sibling"
    elif corruption == "wrong_key":
        payload["cache_key"] = "0" * 64
    elif corruption == "wrong_file_column":
        file_path = "A12_MissionReport.pdf"
    elif corruption == "wrong_recipe_column":
        recipe_hash = "0" * 64
    elif corruption == "scoped_node":
        payload["graph"]["nodes"][0]["properties"]["repo_id"] = repo_id
    elif corruption == "scoped_relationship":
        payload["graph"]["relationships"][0]["properties"]["run_id"] = run_id
    elif corruption == "scoped_embedding":
        payload["graph"]["nodes"][0]["embedding_properties"]["graphJoinId"] = [1.0]
    elif corruption == "negative_pruning":
        payload["pruned_nodes"] = -1
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO graph_extraction_checkpoints "
            "(repo_id, cache_key, recipe_hash, file_path, created_at, envelope) "
            "VALUES ($1,$2,$3,$4,$5,$6::jsonb)",
            repo_id, checkpoint.cache_key, recipe_hash, file_path, checkpoint.created_at,
            json.dumps([] if corruption == "non_object" else payload),
        )
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)


@pytest.mark.parametrize("operation", ["put", "prepare", "finish"])
@pytest.mark.parametrize("fence_state", ["absent", "replaced", "malformed", "retiring", "tombstone", "missing_corpus"])
async def test_every_checkpoint_mutation_requires_the_current_building_fence(
    checkpoint_store: tuple[PostgresClient, str, str], operation: str, fence_state: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    if fence_state == "absent":
        assert await pg.release_index_fence(repo_id, run_id)
    elif fence_state == "missing_corpus":
        await pg.delete_corpus_with_data(repo_id)
    elif fence_state == "replaced":
        assert await pg.release_index_fence(repo_id, run_id)
        claim = await pg.acquire_index_fence(
            repo_id, uuid.uuid4().hex, started_at=datetime.now(UTC),
            owner="pytest:successor", lease_seconds=3600,
        )
        assert claim.acquired
    elif fence_state == "malformed":
        await pg.update_corpus_meta(repo_id, {"index_run": {"run_id": run_id}})
    elif fence_state == "retiring":
        assert await pg.record_fence_phase(repo_id, run_id, "retiring")
    else:
        await pg.update_corpus_meta(repo_id, {"index_tombstone": {"incomplete": True}})
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    with pytest.raises(GraphExtractionCheckpointError):
        if operation == "put":
            await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
        elif operation == "prepare":
            await pg.prepare_graph_extraction_checkpoint_file(
                repo_id, run_id, recipe_hash, checkpoint.identity.file_path, [],
            )
        else:
            await pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [])
    remaining = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert remaining == (None if fence_state == "missing_corpus" else checkpoint)


async def test_preparation_rotates_recipe_and_prunes_only_complete_file_inventory(
    checkpoint_store: tuple[PostgresClient, str, str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    old, keep, deleted_file = (
        _checkpoint(repo_id, run_id, chunk_index=0),
        _checkpoint(repo_id, run_id, chunk_index=1),
        _checkpoint(repo_id, run_id, file_path="A12_MissionReport.pdf"),
    )
    recipe_hash = graph_extraction_recipe_hash(old.identity.recipe)
    await pg.prepare_graph_extraction_checkpoint_file(
        repo_id, run_id, recipe_hash, old.identity.file_path, [old.cache_key, keep.cache_key],
    )
    await _prepare(pg, deleted_file)
    for checkpoint in (old, keep, deleted_file):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    await pg.prepare_graph_extraction_checkpoint_file(
        repo_id, run_id, recipe_hash, old.identity.file_path, [keep.cache_key],
    )
    assert await pg.get_graph_extraction_checkpoint(repo_id, old.cache_key) is None
    assert await pg.get_graph_extraction_checkpoint(repo_id, keep.cache_key) == keep
    assert await pg.get_graph_extraction_checkpoint(repo_id, deleted_file.cache_key) == deleted_file
    await pg.finish_graph_extraction_checkpoint_run(
        repo_id, run_id, recipe_hash, [keep.identity.file_path],
    )
    assert await pg.get_graph_extraction_checkpoint(repo_id, deleted_file.cache_key) is None
    # A later owner changes the recipe; old-run writes may not resurrect its partition.
    assert await pg.release_index_fence(repo_id, run_id)
    next_run = uuid.uuid4().hex
    claim = await pg.acquire_index_fence(
        repo_id, next_run, started_at=datetime.now(UTC), owner="pytest:next", lease_seconds=3600,
    )
    assert claim.acquired
    recipe = _recipe().model_copy(update={"extractor_version": "official-extraction-v2"})
    current = _checkpoint(repo_id, next_run, recipe=recipe)
    await _prepare(pg, current)
    assert await pg.get_graph_extraction_checkpoint(repo_id, keep.cache_key) is None
    await pg.put_graph_extraction_checkpoint(repo_id, next_run, current)
    with pytest.raises(GraphExtractionCheckpointError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, keep)


async def test_partition_cannot_change_mid_run_or_accept_unprepared_recipe(
    checkpoint_store: tuple[PostgresClient, str, str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    with pytest.raises(GraphExtractionCheckpointError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    changed = _checkpoint(repo_id, run_id, recipe=_recipe().model_copy(update={"pruner_version": "v2"}))
    with pytest.raises(GraphExtractionCheckpointError):
        await _prepare(pg, changed)
    with pytest.raises(GraphExtractionCheckpointError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, changed)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


@pytest.mark.parametrize("operation", ["deindex", "delete_corpus", "delete_corpus_with_data", "foreign_key", "failed_staging"])
async def test_checkpoint_lifecycle_and_corpus_isolation(
    checkpoint_store: tuple[PostgresClient, str, str], operation: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    sibling_id, sibling_run = f"{repo_id}__sibling", uuid.uuid4().hex
    staged_id = staging_repo_id(repo_id, run_id)
    await pg.upsert_corpus(staged_id, name="Failed staging fixture", root_path=".")
    await pg.upsert_corpus(sibling_id, name="Sibling corpus fixture", root_path=".")
    claim = await pg.acquire_index_fence(
        sibling_id, sibling_run, started_at=datetime.now(UTC), owner="pytest:sibling", lease_seconds=3600,
    )
    assert claim.acquired
    sibling_checkpoint = _checkpoint(sibling_id, sibling_run)
    await _prepare(pg, sibling_checkpoint)
    await pg.put_graph_extraction_checkpoint(sibling_id, sibling_run, sibling_checkpoint)
    try:
        if operation == "deindex":
            _, tombstone = await pg.delete_index_state(repo_id, allow_fence_run_id=run_id, lease_seconds=3600)
            assert tombstone.intent == "deindex"
            corpus = await pg.get_corpus(repo_id)
            assert corpus is not None
            assert "graph_extraction_checkpoint_partition" not in corpus["meta"]
        elif operation == "foreign_key":
            assert pg._pool is not None
            async with pg._pool.acquire() as conn:
                await conn.execute("DELETE FROM corpora WHERE repo_id = $1", repo_id)
        elif operation == "failed_staging":
            await pg.delete_corpus_with_data(staged_id)
            assert await pg.release_index_fence(repo_id, run_id)
        elif operation == "delete_corpus":
            await pg.delete_corpus(repo_id)
        else:
            await pg.delete_corpus_with_data(repo_id)
        assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == (
            checkpoint if operation == "failed_staging" else None
        )
        assert await pg.get_graph_extraction_checkpoint(sibling_id, sibling_checkpoint.cache_key) == sibling_checkpoint
        assert await pg.get_graph_extraction_checkpoint(sibling_id, checkpoint.cache_key) is None
    finally:
        await pg.delete_corpus_with_data(sibling_id)
        await pg.delete_corpus_with_data(staged_id)


async def _wait_for_blocked_checkpoint(
    conn: asyncpg.Connection, blocker_pid: int, *, minimum: int = 1,
) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if await conn.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE $1 = ANY(pg_blocking_pids(pid))",
            blocker_pid,
        ) >= minimum:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Checkpoint operation never waited on the held corpus row lock")


@pytest.mark.parametrize("operation", ["put", "prepare", "finish"])
async def test_fence_check_and_mutation_share_one_transaction(
    checkpoint_store: tuple[PostgresClient, str, str], operation: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    assert pg._pool is not None
    task: asyncio.Task[None] | None = None
    try:
        async with pg._pool.acquire() as conn:
            async with conn.transaction():
                blocker_pid = await conn.fetchval("SELECT pg_backend_pid()")
                await conn.fetchrow("SELECT repo_id FROM corpora WHERE repo_id = $1 FOR UPDATE", repo_id)
                if operation == "put":
                    work = pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
                elif operation == "prepare":
                    work = pg.prepare_graph_extraction_checkpoint_file(
                        repo_id, run_id, recipe_hash, checkpoint.identity.file_path, [],
                    )
                else:
                    work = pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [])
                task = asyncio.create_task(work)
                await _wait_for_blocked_checkpoint(conn, blocker_pid)
                assert not task.done()
                # The older worker must validate the replacement after acquiring the lock.
                await conn.execute(
                    "UPDATE corpora SET meta = jsonb_set(meta, '{index_run,run_id}', to_jsonb($2::text)) WHERE repo_id=$1",
                    repo_id, uuid.uuid4().hex,
                )
        with pytest.raises(GraphExtractionCheckpointError):
            await asyncio.wait_for(task, timeout=5)
        assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("operation", ["deindex", "delete_corpus", "delete_corpus_with_data"])
@pytest.mark.parametrize("order", ["writer_first", "deletion_first"])
async def test_concurrent_deletion_and_checkpoint_write_share_lock_order(
    checkpoint_store: tuple[PostgresClient, str, str], operation: str, order: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)

    async def delete() -> None:
        if operation == "deindex":
            await pg.delete_index_state(repo_id, allow_fence_run_id=run_id, lease_seconds=3600)
        elif operation == "delete_corpus":
            await pg.delete_corpus(repo_id)
        else:
            await pg.delete_corpus_with_data(repo_id)

    assert pg._pool is not None
    tasks: list[asyncio.Task[None]] = []
    try:
        async with pg._pool.acquire() as conn:
            async with conn.transaction():
                blocker_pid = await conn.fetchval("SELECT pg_backend_pid()")
                await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", repo_id)
                # Queue actual public operations in both orders, then prove each is
                # waiting in Postgres before release; no wall-clock scheduling guess.
                if order == "writer_first":
                    writer = asyncio.create_task(pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint))
                    tasks.append(writer)
                    await _wait_for_blocked_checkpoint(conn, blocker_pid)
                    deletion = asyncio.create_task(delete())
                    tasks.append(deletion)
                else:
                    deletion = asyncio.create_task(delete())
                    tasks.append(deletion)
                    await _wait_for_blocked_checkpoint(conn, blocker_pid)
                    writer = asyncio.create_task(pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint))
                    tasks.append(writer)
                await _wait_for_blocked_checkpoint(conn, blocker_pid, minimum=2)
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        assert results[0] is None
        if order == "writer_first":
            assert results[1] is None
        else:
            assert isinstance(results[1], GraphExtractionCheckpointError), results[1]
        assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) is None
        assert await pg.get_index_fence(repo_id) is None
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("operation", ["prepare_file", "rotate_recipe", "finish"])
async def test_pruning_corrupt_checkpoints_fails_closed_before_removing_work(
    checkpoint_store: tuple[PostgresClient, str, str], operation: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        await conn.execute(
            "UPDATE graph_extraction_checkpoints SET envelope = envelope - 'graph' WHERE repo_id = $1", repo_id,
        )
    owner = run_id
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    if operation == "rotate_recipe":
        assert await pg.release_index_fence(repo_id, run_id)
        owner = uuid.uuid4().hex
        claim = await pg.acquire_index_fence(
            repo_id, owner, started_at=datetime.now(UTC), owner="pytest:rotation", lease_seconds=3600,
        )
        assert claim.acquired
        recipe_hash = _digest("new recipe partition")
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        if operation == "finish":
            await pg.finish_graph_extraction_checkpoint_run(repo_id, owner, recipe_hash, [])
        else:
            await pg.prepare_graph_extraction_checkpoint_file(
                repo_id, owner, recipe_hash, checkpoint.identity.file_path, [],
            )
    async with pg._pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM graph_extraction_checkpoints WHERE repo_id=$1", repo_id) == 1


async def test_successor_reuses_identity_without_rewriting_origin_or_time(
    checkpoint_store: tuple[PostgresClient, str, str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert await pg.release_index_fence(repo_id, run_id)
    next_run = uuid.uuid4().hex
    claim = await pg.acquire_index_fence(
        repo_id, next_run, started_at=datetime.now(UTC), owner="pytest:reuse", lease_seconds=3600,
    )
    assert claim.acquired
    duplicate = checkpoint.model_copy(update={
        "originating_run_id": next_run, "created_at": checkpoint.created_at + timedelta(hours=1),
    })
    await _prepare(pg, duplicate)
    await pg.put_graph_extraction_checkpoint(repo_id, next_run, duplicate)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


async def test_finished_partition_rejects_late_writers_and_empty_completion_prunes_old_files(
    checkpoint_store: tuple[PostgresClient, str, str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    await pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [checkpoint.identity.file_path])
    with pytest.raises(GraphExtractionCheckpointError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert await pg.release_index_fence(repo_id, run_id)
    next_run = uuid.uuid4().hex
    claim = await pg.acquire_index_fence(
        repo_id, next_run, started_at=datetime.now(UTC), owner="pytest:empty", lease_seconds=3600,
    )
    assert claim.acquired
    await pg.finish_graph_extraction_checkpoint_run(repo_id, next_run, recipe_hash, [])
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) is None


@pytest.mark.parametrize("field,value", [
    ("repo_id", "pytest_other_corpus"), ("file_path", "A12_MissionReport.pdf"),
    ("file_sha256", _digest("new file bytes")), ("chunk_id", "other-chunk"),
    ("chunk_index", 1), ("chunk_content_sha256", _digest("different exact text")),
    ("chunk_metadata_sha256", _digest("changed chunk metadata")),
    ("start_line", 2), ("end_line", 4), ("chunk_provenance", {"extraction": "direct"}),
    ("rendered_prompt_sha256", _digest("changed rendered prompt")),
])
async def test_every_source_and_chunk_identity_dimension_changes_the_key(field: str, value: object) -> None:
    identity = _checkpoint("pytest_identity", "origin").identity
    raw = identity.model_dump(mode="json")
    raw[field] = value
    changed = GraphExtractionCheckpointIdentity.model_validate(raw)
    assert graph_extraction_cache_key(changed) != graph_extraction_cache_key(identity)


@pytest.mark.parametrize("field,value", [
    ("prompt_template_sha256", _digest("new template")), ("examples_sha256", _digest("new example")),
    ("model_alias", "new-alias"), ("model_upstream", "openrouter/openai/new-model"),
    ("model_endpoint", "http://different-gateway:4000/v1"),
    ("model_parameters", {"temperature": 0.1}), ("neo4j_graphrag_version", "1.20.0"),
    ("extractor_version", "v2"), ("pruner_version", "v2"),
])
async def test_every_recipe_dimension_changes_partition_and_cache_identity(field: str, value: object) -> None:
    identity = _checkpoint("pytest_identity", "origin").identity
    raw = identity.model_dump(mode="json")
    raw["recipe"][field] = value
    changed = GraphExtractionCheckpointIdentity.model_validate(raw)
    assert graph_extraction_recipe_hash(changed.recipe) != graph_extraction_recipe_hash(identity.recipe)
    assert graph_extraction_cache_key(changed) != graph_extraction_cache_key(identity)


async def test_schema_is_identity_and_object_key_order_is_not() -> None:
    identity = _checkpoint("pytest_identity", "origin").identity
    raw = identity.model_dump(mode="json")
    reordered = dict(reversed(list(raw.items())))
    reordered["recipe"]["model_parameters"] = {"extra_body": {"reasoning": {"effort": "none"}}, "temperature": 0}
    assert graph_extraction_cache_key(GraphExtractionCheckpointIdentity.model_validate(reordered)) == graph_extraction_cache_key(identity)
    changed = copy.deepcopy(raw)
    changed["recipe"]["approved_schema"]["node_types"][0]["description"] = "An approved lunar mission"
    assert graph_extraction_cache_key(GraphExtractionCheckpointIdentity.model_validate(changed)) != graph_extraction_cache_key(identity)


def _schema_recipe(*, closed: bool, relationship_properties: bool) -> GraphExtractionCheckpointRecipe:
    schema = _recipe().approved_schema.model_copy(deep=True)
    if relationship_properties:
        schema.relationship_types[0].properties = [PropertyType(name="purpose", type="STRING")]
    if closed:
        schema = closed_graph_schema(schema)
    else:
        for item in (*schema.node_types, *schema.relationship_types):
            item.additional_properties = True
    return _recipe().model_copy(update={"approved_schema": schema})


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("relationship_properties", [False, True])
@pytest.mark.parametrize("input_mode", ["instance", "python", "json"])
async def test_approved_schema_roundtrip_and_hash_keep_exact_property_permissions(
    closed: bool, relationship_properties: bool, input_mode: str,
) -> None:
    original = _schema_recipe(closed=closed, relationship_properties=relationship_properties)
    expected = original.model_dump(mode="json")
    if input_mode == "instance":
        recipe = GraphExtractionCheckpointRecipe(**{
            **original.model_dump(mode="python"), "approved_schema": original.approved_schema,
        })
    elif input_mode == "python":
        recipe = GraphExtractionCheckpointRecipe.model_validate(original.model_dump(mode="python"))
    else:
        recipe = GraphExtractionCheckpointRecipe.model_validate_json(original.model_dump_json())
    assert recipe.model_dump(mode="json") == expected
    assert original.model_dump(mode="json") == expected, "validation must not mutate the approved input"
    exact_hash = hashlib.sha256(json.dumps(
        expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    assert graph_extraction_recipe_hash(recipe) == exact_hash
    checkpoint = _checkpoint("pytest_schema_identity", "origin", recipe=recipe)
    identity_json = checkpoint.identity.model_dump(mode="json")
    assert graph_extraction_cache_key(checkpoint.identity) == hashlib.sha256(json.dumps(
        identity_json, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode()).hexdigest()
    restored = GraphExtractionCheckpoint.from_persisted_payload(checkpoint.model_dump(mode="json"))
    assert restored.model_dump(mode="json") == checkpoint.model_dump(mode="json")
    opposite_schema = recipe.approved_schema.model_copy(deep=True)
    opposite_schema.relationship_types[0].additional_properties = closed
    opposite = recipe.model_copy(update={"approved_schema": opposite_schema})
    assert graph_extraction_recipe_hash(opposite) != graph_extraction_recipe_hash(recipe)


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("relationship_properties", [False, True])
@pytest.mark.parametrize("empty", [False, True])
async def test_postgres_roundtrip_preserves_the_exact_approved_schema(
    checkpoint_store: tuple[PostgresClient, str, str], closed: bool,
    relationship_properties: bool, empty: bool,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    recipe = _schema_recipe(closed=closed, relationship_properties=relationship_properties)
    approved = recipe.approved_schema.model_dump(mode="json")
    checkpoint = _checkpoint(repo_id, run_id, recipe=recipe, empty=empty)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    loaded = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert loaded is not None
    assert loaded.identity.recipe.approved_schema.model_dump(mode="json") == approved
    assert loaded.model_dump(mode="json") == checkpoint.model_dump(mode="json")
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == loaded


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("input_mode", ["instance", "python", "json"])
async def test_zero_property_nodes_cannot_bypass_the_official_schema_boundary(closed: bool, input_mode: str) -> None:
    recipe = _schema_recipe(closed=closed, relationship_properties=False)
    recipe.approved_schema.node_types[0].properties = []
    payload = recipe.model_dump(mode="python")
    if input_mode == "instance":
        payload["approved_schema"] = recipe.approved_schema
    with pytest.raises(ValidationError):
        if input_mode == "json":
            GraphExtractionCheckpointRecipe.model_validate_json(recipe.model_dump_json())
        else:
            GraphExtractionCheckpointRecipe.model_validate(payload)


@pytest.mark.parametrize("kind", ["node_types", "relationship_types"])
@pytest.mark.parametrize("bad_value", [None, "false", 0, 0.0, "missing"])
async def test_closed_schema_permission_corruption_is_not_repaired(
    checkpoint_store: tuple[PostgresClient, str, str], kind: str, bad_value: object,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id, recipe=_schema_recipe(closed=True, relationship_properties=False))
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    payload = checkpoint.model_dump(mode="json")
    item = payload["identity"]["recipe"]["approved_schema"][kind][0]
    if bad_value == "missing":
        del item["additional_properties"]
    else:
        item["additional_properties"] = bad_value
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        await conn.execute(
            "UPDATE graph_extraction_checkpoints SET envelope=$2::jsonb WHERE repo_id=$1", repo_id, json.dumps(payload),
        )
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)


@pytest.mark.parametrize("endpoint", [
    "http://user:secret@gateway/v1", "http://gateway/v1?api_key=secret",
    "http://gateway/v1#credential", "file:///private/key", "http://gateway/v1?",
])
async def test_checkpoint_recipe_rejects_unsanitized_endpoints(endpoint: str) -> None:
    raw = _recipe().model_dump(mode="json")
    raw["model_endpoint"] = endpoint
    with pytest.raises(ValidationError):
        GraphExtractionCheckpointRecipe.model_validate(raw)


@pytest.mark.parametrize("key", ["api_key", "timeout", "concurrency", "max_retries", "messages", "prompt", "authorization"])
async def test_checkpoint_recipe_rejects_credentials_prompts_and_execution_controls(key: str) -> None:
    raw = _recipe().model_dump(mode="json")
    raw["model_parameters"] = {"extra_body": {key: "must not be persisted"}}
    with pytest.raises(ValidationError):
        GraphExtractionCheckpointRecipe.model_validate(raw)


@pytest.mark.parametrize("key", [
    "client_secret", "openai_api_key", "x-api-key", "system_prompt", "systemInstruction",
    "azureOpenAIApiKey", "anthropic-api-key", "clientSecret", "google_application_credentials",
    "userPrompt", "developer_prompt", "raw_prompt", "provider_access_token", "refreshToken",
    "http_authorization", "requestTimeoutSeconds", "maxConcurrency", "provider_max_retries",
    "openai_input", "client_token", "system_message", "vendor_prompt", "renderedPrompt",
    "provider_credentials", "xApiKey", "ＡＰＩ＿ＫＥＹ",
])
@pytest.mark.parametrize("placement", ["top", "nested", "list"])
async def test_checkpoint_rejects_vendor_and_spelling_aliases_before_any_storage(
    checkpoint_store: tuple[PostgresClient, str, str], key: str, placement: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    params = {key: "private value must never persist"}
    if placement == "nested":
        params = {"extra_body": {"provider": params}}
    elif placement == "list":
        params = {"extra_body": {"options": [params]}}
    raw = checkpoint.identity.recipe.model_dump(mode="json")
    raw["model_parameters"] = params
    with pytest.raises(ValidationError):
        GraphExtractionCheckpointRecipe.model_validate(raw)
    # A nested model mutation must meet the same boundary when persisted.
    checkpoint.identity.recipe.model_parameters.clear()
    checkpoint.identity.recipe.model_parameters.update(params)
    with pytest.raises((ValidationError, ValueError, GraphExtractionCheckpointError)):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM graph_extraction_checkpoints WHERE repo_id=$1", repo_id) == 0


@pytest.mark.parametrize("key", [
    "oauthToken", "promptText",
    *(f"{prefix}{suffix}" for prefix in ("future_", "vendorExtension_", "xCustom") for suffix in ("Setting", "Option", "V2")),
])
@pytest.mark.parametrize("path", [[], ["extra_body"], ["extra_body", "reasoning"], ["extra_body", "provider"]])
async def test_unreviewed_parameter_names_fail_closed_at_every_object_boundary(
    checkpoint_store: tuple[PostgresClient, str, str], key: str, path: list[str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    for value in ("private text", 23, True, {"options": [{"nested": "private text"}]}):
        params = {key: value}
        for parent_key in reversed(path):
            params = {parent_key: params}
        raw = _recipe().model_dump(mode="json")
        raw["model_parameters"] = params
        with pytest.raises(ValidationError):
            GraphExtractionCheckpointRecipe.model_validate(raw)
        checkpoint.identity.recipe.model_parameters.clear()
        checkpoint.identity.recipe.model_parameters.update(params)
        with pytest.raises((ValidationError, ValueError, GraphExtractionCheckpointError)):
            await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM graph_extraction_checkpoints WHERE repo_id=$1", repo_id) == 0


@pytest.mark.parametrize("params", [
    {"extra_body": {"options": [{"oauthToken": "private text"}]}},
    {"extra_body": {"options": [{"promptText": "private text"}]}},
    {"extra_body": {"reasoning": {"effort": {"high": "private text"}}}},
    {"extra_body": {"provider": {"order": [{"openai": "private text"}]}}},
    {"extra_body": {"provider": {"allow_fallbacks": "false"}}},
    {"extra_body": {"provider": {"require_parameters": 1}}},
    {"extra_body": {"top_k": True}}, {"extra_body": {"min_p": "0.5"}},
    {"reasoning_effort": "unreviewed-effort"}, {"temperature": True}, {"top_p": "0.9"},
    {"max_tokens": 512.0}, {"max_completion_tokens": True}, {"seed": "123"},
    {"logit_bias": {"credential": "private text"}}, {"logit_bias": {"100": {"value": 1}}},
    {"stop": [{"text": "private text"}]}, {"response_format": {"type": "json_object", "options": "private text"}},
    {"response_format": {"type": "json_schema", "json_schema": {"description": "private text"}}},
])
async def test_semantic_parameter_shapes_reject_freeform_payloads_and_type_coercion(params: dict) -> None:
    raw = _recipe().model_dump(mode="json")
    raw["model_parameters"] = params
    with pytest.raises(ValidationError):
        GraphExtractionCheckpointRecipe.model_validate(raw)


@pytest.mark.parametrize("effort", ["none", "minimal", "low", "medium", "high", "xhigh"])
@pytest.mark.parametrize("upstream", ["openrouter/openai/fixture-model", "openai/fixture-model"])
async def test_current_graph_llm_factory_parameters_roundtrip_without_projection_loss(
    checkpoint_store: tuple[PostgresClient, str, str], effort: str, upstream: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    params = reasoning_model_params(reasoning_effort=effort, route_upstream=upstream)
    raw = _recipe().model_dump(mode="json")
    raw.update(model_parameters=params, model_upstream=upstream)
    checkpoint = _checkpoint(repo_id, run_id, recipe=GraphExtractionCheckpointRecipe.model_validate(raw))
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    loaded = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert loaded is not None
    assert json.dumps(loaded.identity.recipe.model_parameters, sort_keys=True) == json.dumps(params, sort_keys=True)


async def test_legitimate_semantic_model_parameters_retain_exact_values(
    checkpoint_store: tuple[PostgresClient, str, str],
) -> None:
    pg, repo_id, run_id = checkpoint_store
    params = {
        "temperature": 0.1, "top_p": 0.95, "max_tokens": 4096, "max_completion_tokens": 8192,
        "frequency_penalty": 0.2, "presence_penalty": 0.4, "seed": 123,
        "reasoning_effort": "high", "stop": ["END"], "logprobs": True, "top_logprobs": 3,
        "verbosity": "low",
        "logit_bias": {"100": -0.5}, "response_format": {"type": "json_object"},
        "extra_body": {
            "reasoning": {"effort": "none", "max_tokens": 1024, "enabled": True, "exclude": False},
            "top_k": 10, "repetition_penalty": 1.1, "min_p": 0.05,
            "provider": {"order": ["openai"], "allow_fallbacks": False, "require_parameters": True},
        },
    }
    raw = _recipe().model_dump(mode="json")
    raw["model_parameters"] = params
    recipe = GraphExtractionCheckpointRecipe.model_validate(raw)
    assert json.dumps(recipe.model_parameters, sort_keys=True) == json.dumps(params, sort_keys=True)
    checkpoint = _checkpoint(repo_id, run_id, recipe=recipe)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    loaded = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert loaded is not None
    assert json.dumps(loaded.identity.recipe.model_parameters, sort_keys=True) == json.dumps(params, sort_keys=True)


@pytest.mark.parametrize("path,operation,value", [
    (["format_version"], "delete", None), (["identity", "identity_version"], "delete", None),
    (["format_version"], "set", True), (["format_version"], "set", 1.0),
    (["identity", "identity_version"], "set", True), (["identity", "identity_version"], "set", 1.0),
    (["identity", "recipe", "approved_schema", "additional_patterns"], "delete", None),
    (["identity", "recipe", "approved_schema", "constraints"], "delete", None),
    (["identity", "recipe", "approved_schema", "unexpected"], "set", "ignored schema field"),
    (["identity", "recipe", "approved_schema", "node_types", 0, "unexpected"], "set", "ignored node field"),
    (["identity", "recipe", "approved_schema", "node_types", 0, "properties", 0, "unexpected"], "set", "ignored property field"),
    (["identity", "recipe", "approved_schema", "additional_patterns"], "set", "false"),
    (["identity", "chunk_provenance", "unexpected"], "set", "ignored source field"),
    (["identity", "chunk_provenance", "regions"], "delete", None),
    (["graph", "nodes", 0, "properties"], "delete", None),
    (["graph", "nodes", 0, "embedding_properties"], "delete", None),
    (["graph", "relationships", 0, "properties"], "delete", None),
    (["graph", "relationships", 0, "embedding_properties"], "delete", None),
])
async def test_persisted_envelope_cannot_gain_defaults_drop_nested_extras_or_coerce_types(
    checkpoint_store: tuple[PostgresClient, str, str], path: list[str | int], operation: str, value: object,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    payload = checkpoint.model_dump(mode="json")
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    if operation == "delete":
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        await conn.execute(
            "UPDATE graph_extraction_checkpoints SET envelope=$2::jsonb WHERE repo_id=$1", repo_id, json.dumps(payload),
        )
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)


@pytest.mark.parametrize("field,value", [
    ("complete", None), ("complete", "false"), ("complete", 0),
    ("complete", 1), ("complete", 0.0), ("owner_run_id", None),
    ("recipe_hash", None), ("unexpected", "ignored partition field"),
])
@pytest.mark.parametrize("operation", ["put", "prepare", "finish"])
async def test_persisted_finished_partition_corruption_never_reopens_mutations(
    checkpoint_store: tuple[PostgresClient, str, str], field: str, value: object, operation: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    await pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [checkpoint.identity.file_path])
    corpus = await pg.get_corpus(repo_id)
    assert corpus is not None
    partition = corpus["meta"]["graph_extraction_checkpoint_partition"]
    if value is None:
        del partition[field]
    else:
        partition[field] = value
    await pg.update_corpus_meta(repo_id, {"graph_extraction_checkpoint_partition": partition})
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        if operation == "put":
            await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
        elif operation == "prepare":
            await pg.prepare_graph_extraction_checkpoint_file(repo_id, run_id, recipe_hash, checkpoint.identity.file_path, [])
        else:
            await pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [])
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


@pytest.mark.parametrize("missing", [False, True])
async def test_missing_or_null_partition_cannot_reopen_existing_checkpoint_work(
    checkpoint_store: tuple[PostgresClient, str, str], missing: bool,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    recipe_hash = graph_extraction_recipe_hash(checkpoint.identity.recipe)
    await pg.finish_graph_extraction_checkpoint_run(repo_id, run_id, recipe_hash, [checkpoint.identity.file_path])
    assert pg._pool is not None
    async with pg._pool.acquire() as conn:
        if missing:
            await conn.execute("UPDATE corpora SET meta = meta - 'graph_extraction_checkpoint_partition' WHERE repo_id=$1", repo_id)
        else:
            await conn.execute("UPDATE corpora SET meta = jsonb_set(meta, '{graph_extraction_checkpoint_partition}', 'null') WHERE repo_id=$1", repo_id)
    with pytest.raises(GraphExtractionCheckpointCorruptError):
        await _prepare(pg, checkpoint)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) == checkpoint


@pytest.mark.parametrize("kind", ["node", "relationship"])
@pytest.mark.parametrize("original,replacement", [
    (True, 1), (True, 1.0), (1, 1.0), (False, 0), (0, 0.0),
    ([True], [1]), ([True], [1.0]), ([1], [1.0]),
])
async def test_duplicate_graph_property_types_must_match_exactly(
    checkpoint_store: tuple[PostgresClient, str, str], kind: str, original: object, replacement: object,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    target = checkpoint.graph.nodes[0] if kind == "node" else checkpoint.graph.relationships[0]
    target.properties["measurement"] = original
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    changed = checkpoint.model_copy(deep=True)
    target = changed.graph.nodes[0] if kind == "node" else changed.graph.relationships[0]
    target.properties["measurement"] = replacement
    with pytest.raises(GraphExtractionCheckpointConflictError):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, changed)
    stored = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert stored is not None
    target = stored.graph.nodes[0] if kind == "node" else stored.graph.relationships[0]
    value = target.properties["measurement"]
    assert type(value) is type(original)
    if isinstance(original, list):
        assert isinstance(value, list)
        assert type(value[0]) is type(original[0])


@pytest.mark.parametrize("kind", ["node", "relationship"])
@pytest.mark.parametrize("value", [
    date(1969, 7, 20), time(20, 17, 40), time(20, 17, 40, tzinfo=UTC),
    datetime(1969, 7, 20, 20, 17, 40), datetime(1969, 7, 20, 20, 17, 40, tzinfo=UTC),
    datetime(1969, 7, 20, 14, 17, 40, tzinfo=timezone(timedelta(hours=-6))),
])
async def test_checkpoint_rejects_python_temporal_values_before_serialization(
    checkpoint_store: tuple[PostgresClient, str, str], kind: str, value: date | time,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    await _prepare(pg, checkpoint)
    target = checkpoint.graph.nodes[0] if kind == "node" else checkpoint.graph.relationships[0]
    target.properties["occurred_at"] = value
    # These are legal official Neo4j DTO values, but not the JSON-valued raw
    # extractor boundary being checkpointed. Never silently turn them into text.
    with pytest.raises(ValidationError, match="temporal"):
        GraphExtractionCheckpoint.model_validate(checkpoint.model_dump(mode="python"))
    with pytest.raises(ValidationError, match="temporal"):
        await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    assert await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key) is None


@pytest.mark.parametrize("kind", ["node", "relationship"])
async def test_official_json_temporal_strings_and_geopoints_roundtrip_without_type_loss(
    checkpoint_store: tuple[PostgresClient, str, str], kind: str,
) -> None:
    pg, repo_id, run_id = checkpoint_store
    checkpoint = _checkpoint(repo_id, run_id)
    values = {
        "mission_date": "1969-07-20", "mission_time": "20:17:40", "mission_zoned_time": "20:17:40Z",
        "mission_datetime": "1969-07-20T20:17:40", "mission_zoned_datetime": "1969-07-20T20:17:40Z",
        "duration": "P1D", "location": GeoPoint(latitude=0.674, longitude=23.473, height=0.0),
    }
    target = checkpoint.graph.nodes[0] if kind == "node" else checkpoint.graph.relationships[0]
    target.properties.update(values)
    # Confirm the exact official JSON reader used by extract_for_chunk keeps
    # date-looking provider strings as strings before we persist anything.
    official = Neo4jGraph.model_validate_json(checkpoint.graph.model_dump_json())
    item = official.nodes[0] if kind == "node" else official.relationships[0]
    assert all(type(item.properties[key]) is type(value) for key, value in values.items())
    await _prepare(pg, checkpoint)
    await pg.put_graph_extraction_checkpoint(repo_id, run_id, checkpoint)
    stored = await pg.get_graph_extraction_checkpoint(repo_id, checkpoint.cache_key)
    assert stored is not None
    target = stored.graph.nodes[0] if kind == "node" else stored.graph.relationships[0]
    for key, value in values.items():
        assert type(target.properties[key]) is type(value)
        assert target.properties[key] == value
