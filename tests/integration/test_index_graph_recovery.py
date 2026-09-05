"""Real index owner, stores and HTTP extraction across a failed replacement and reuse."""

from __future__ import annotations

import asyncio
import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from server.api import index as index_api
from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.indexing.graphrag_schema import canonical_schema_dict, graph_schema_hash
from server.indexing.loader import FileLoader
from server.main import _warm_catalog_views
from server.models.index import (
    GraphSchemaProposal,
    GraphSchemaSample,
    IndexRequest,
    IndexRunSummary,
)
from server.retrieval.qdrant_store import QdrantChunkStore
from server.services import config_store
from tests.integration import test_graphrag_extraction_recovery as recovery
from tests.service_requirements import require_env

recovery_gateway = recovery.recovery_gateway
recovery_store = recovery.recovery_store

pytestmark = [pytest.mark.asyncio, pytest.mark.requires_postgres, pytest.mark.requires_neo4j,
              pytest.mark.requires_qdrant]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("ending", ["success", "cancel", "commit_failure", "cancel_commit_failure"])
async def test_source_and_checkpoint_payloads_live_only_until_their_file_work_drains(
    tmp_path: Path, recovery_store, recovery_gateway, stream: bool, ending: str,
) -> None:
    _warm_catalog_views()
    pg, repo, run = recovery_store
    source = tmp_path / "source"
    source.mkdir()
    for section in (0, 2):
        content = f"Mission section {section}: Apollo 11 used the Eagle lunar module.\n"
        # Every real streaming chunk carries domain content that the provider
        # can extract. Use the public threshold, without a test-only limit.
        (source / f"mission-{section}.txt").write_text((content * 2000)[:100_000] if stream else content)
    discovered = list(FileLoader().iter_repo_files(str(source)))
    first_relative, _ = discovered[0]
    last_relative, last_source = discovered[-1]
    recovery_gateway.failing_section = int(last_source.stem.rsplit("-", 1)[1])
    recovery_gateway.mode = "held-section"
    cfg = load_config().model_copy(deep=True)
    cfg.chat.litellm.base_url = recovery_gateway.base
    cfg.chat.litellm.default_model = "openai.gpt-5.6-sol"
    cfg.graph_indexing.enabled = True
    cfg.graph_indexing.build_code_graph = False
    cfg.graph_indexing.semantic_kg_llm_model = "openai.gpt-5.6-sol"
    cfg.graph_indexing.semantic_kg_reasoning_effort = "low"
    cfg.graph_storage.include_communities = False
    cfg.system_prompts.semantic_kg_extraction = recovery.PROMPT
    cfg.indexing.indexing_workers = 1
    cfg.indexing.skip_dense = True
    cfg.indexing.figures.enabled = False
    cfg.indexing.large_file_mode = "stream" if stream else "read_all"
    cfg.indexing.large_file_stream_chunk_chars = 100_000
    cfg.chunking.chunking_strategy = "fixed_chars"
    cfg.chunking.chunk_size = 5000
    cfg.chunking.chunk_overlap = 0
    cfg.chunking.max_indexable_file_size = 120_000
    cfg.semantic_cache.enabled = False
    await pg.upsert_corpus(repo, name="Apollo per-file resource lifecycle", root_path=str(source))
    await config_store.save_config(cfg, repo_id=repo)
    corpus, cfg = await index_api.load_corpus_and_scoped_config(repo)
    schema = canonical_schema_dict(recovery._schema())
    proposal = GraphSchemaProposal(
        corpus_id=repo, policy="semantic", created_at=datetime.now(UTC),
        input_fingerprint=await index_api.graph_schema_input_fingerprint(corpus, cfg),
        schema_hash=graph_schema_hash(schema), schema=schema,
        sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]), model_alias="openai.gpt-5.6-sol",
    )
    await pg.set_graph_schema_proposal(repo, proposal)
    qdrant = QdrantChunkStore(cfg)
    neo = Neo4jClient(cfg.graph_storage.neo4j_uri, cfg.graph_storage.neo4j_user,
                     cfg.graph_storage.resolve_password(), database=cfg.graph_storage.resolve_database(repo))
    await neo.connect()
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(snapshot_root)
    job = None
    connection = None
    transaction = None
    try:
        request = IndexRequest(corpus_id=repo, repo_path=str(source), approved_graph_schema_hash=proposal.schema_hash)
        job = asyncio.create_task(index_api._background_index_job(request, asyncio.Queue(), run_id=run, config_snapshot=cfg))
        async with asyncio.timeout(60):
            while recovery_gateway.failing_section not in recovery_gateway.requests:
                assert not job.done(), index_api._STATUS.get(repo)
                await asyncio.sleep(0.01)
        snapshots = list(snapshot_root.glob("ragweld-source-*/*"))
        assert len(snapshots) == 1, "the completed first file must not retain its source copy"
        assert snapshots[0].name == last_source.name
        assert snapshots[0].read_bytes() == last_source.read_bytes()
        context = job.get_coro().cr_frame.f_locals["checkpoint_context"]
        completed = context._files[first_relative]
        active = context._files[last_relative]
        assert completed.written and completed._official_chunks == () and completed.identities == ()
        assert active._official_chunks and active.identities and not active.written
        active_keys = active.keys
        first_keys = {row["cache_key"] for row in await pg._pool.fetch(
            "SELECT cache_key FROM graph_extraction_checkpoints WHERE repo_id=$1", repo,
        )}
        assert first_keys
        with pytest.raises(recovery.GraphExtractionCheckpointError):
            await context.finish_success()
        # The provider has not answered the second file. Lock its actual
        # checkpoint commit, then prove both resources survive cancellation
        # until that retained writer has a durable result.
        connection = await asyncpg.connect(require_env("POSTGRES_DSN"))
        transaction = connection.transaction()
        await transaction.start()
        await connection.fetchrow("SELECT repo_id FROM corpora WHERE repo_id=$1 FOR UPDATE", repo)
        blocker_pid = connection.get_server_pid()
        recovery_gateway.release.set()
        async with asyncio.timeout(8):
            while True:
                await connection.execute("SELECT pg_stat_clear_snapshot()")
                blocked = await connection.fetch(
                    "SELECT pid FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))", blocker_pid,
                )
                if blocked:
                    assert len(blocked) == 1
                    break
                await asyncio.sleep(0.01)
        if ending.startswith("cancel"):
            job.cancel()
            await asyncio.sleep(0)
            job.cancel()
            await asyncio.sleep(0)
        assert not job.done()
        assert snapshots[0].exists()
        assert active._official_chunks and active.identities and not active.written
        committing_keys = {key for key, phase in active.outcomes.items() if phase == "dispatching"}
        assert len(committing_keys) == 1
        if ending.endswith("commit_failure"):
            assert await connection.fetchval("SELECT pg_cancel_backend($1)", blocked[0]["pid"])
            async with asyncio.timeout(8):
                while context._write_error is None:
                    await asyncio.sleep(0.01)
            assert isinstance(context._write_error, asyncpg.QueryCanceledError)
        await transaction.rollback()
        transaction = None
        result = (await asyncio.wait_for(asyncio.gather(job, return_exceptions=True), 20))[0]
        assert isinstance(result, asyncio.CancelledError) if ending == "cancel" else result is None
        summary = IndexRunSummary.model_validate_json(index_api._run_summary_path(repo, run).read_text())
        assert summary.status == {"success": "complete", "cancel": "cancelled", "commit_failure": "error", "cancel_commit_failure": "error"}[ending], summary.error
        assert not list(snapshot_root.glob("ragweld-source-*"))
        assert all(task.done() for task in context._writes)
        retained = {row["cache_key"] for row in await pg._pool.fetch(
            "SELECT cache_key FROM graph_extraction_checkpoints WHERE repo_id=$1", repo,
        )}
        assert first_keys <= retained
        if ending.endswith("commit_failure"):
            assert retained == first_keys
        elif ending == "cancel":
            assert committing_keys <= retained
        else:
            assert set(active_keys) <= retained
        for key in retained:
            checkpoint = await pg.get_graph_extraction_checkpoint(repo, key)
            assert checkpoint.identity.file_sha256 == hashlib.sha256((source / checkpoint.identity.file_path).read_bytes()).hexdigest()
        if ending == "success":
            assert active.written and active._official_chunks == () and active.identities == ()
        else:
            with pytest.raises((recovery.GraphExtractionCheckpointError, asyncpg.QueryCanceledError)):
                await context.finish_success()
    finally:
        recovery_gateway.release.set()
        if transaction is not None:
            await transaction.rollback()
        if connection is not None:
            await connection.close()
        if job is not None and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        tempfile.tempdir = previous_tempdir
        await qdrant.delete_corpus(repo)
        await neo.delete_graph(f"__staging__{repo}__{run}")
        await neo.disconnect()
        config_store.get_config_store().clear_cache(repo)


@pytest.mark.parametrize("first_fails,unusable_source", [
    (False, None), (True, None), (False, "binary"), (False, "empty"), (False, "oversized"),
])
async def test_real_index_owner_persists_reusable_successes_then_promotes_only_complete_replacement(
    tmp_path: Path, recovery_store, recovery_gateway, first_fails: bool, unusable_source: str | None,
) -> None:
    _warm_catalog_views()
    pg, repo, run = recovery_store
    source = tmp_path / "source"
    source.mkdir()
    (source / "mission-a.txt").write_text("Mission section 0: Apollo 11 used the Eagle lunar module.\n")
    (source / "mission-b.txt").write_text("Mission section 2: Apollo 11 used the Eagle lunar module.\n")
    discovered = list(FileLoader().iter_repo_files(str(source)))
    last_relative, last_source = discovered[-1]
    recovery_gateway.failing_section = {"mission-a.txt": 0, "mission-b.txt": 2}[last_relative]
    cfg = load_config().model_copy(deep=True)
    cfg.chat.litellm.base_url = recovery_gateway.base
    cfg.chat.litellm.default_model = "openai.gpt-5.6-sol"
    cfg.graph_indexing.enabled = True
    cfg.graph_indexing.build_code_graph = False
    cfg.graph_indexing.semantic_kg_llm_model = "openai.gpt-5.6-sol"
    cfg.graph_indexing.semantic_kg_reasoning_effort = "low"
    cfg.graph_storage.include_communities = False
    cfg.system_prompts.semantic_kg_extraction = recovery.PROMPT
    cfg.indexing.indexing_workers = 1
    cfg.indexing.skip_dense = True
    cfg.indexing.figures.enabled = False
    cfg.chunking.chunking_strategy = "fixed_chars"
    cfg.chunking.chunk_size = 1000
    cfg.chunking.chunk_overlap = 0
    cfg.chunking.max_indexable_file_size = 10_000
    cfg.semantic_cache.enabled = False
    await pg.upsert_corpus(repo, name="Apollo recovery operator proof", root_path=str(source))
    await config_store.save_config(cfg, repo_id=repo)
    corpus, cfg = await index_api.load_corpus_and_scoped_config(repo)
    schema = canonical_schema_dict(recovery._schema())
    proposal = GraphSchemaProposal(
        corpus_id=repo, policy="semantic", created_at=datetime.now(UTC),
        input_fingerprint=await index_api.graph_schema_input_fingerprint(corpus, cfg),
        schema_hash=graph_schema_hash(schema), schema=schema,
        sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]), model_alias="openai.gpt-5.6-sol",
    )
    await pg.set_graph_schema_proposal(repo, proposal)
    qdrant = QdrantChunkStore(cfg)
    neo = Neo4jClient(cfg.graph_storage.neo4j_uri, cfg.graph_storage.neo4j_user,
                     cfg.graph_storage.resolve_password(), database=cfg.graph_storage.resolve_database(repo))
    await neo.connect()
    graph_ids: list[str] = []
    saved_keys: set[str] = set()
    try:
        for attempt in range(2):
            if attempt:
                if unusable_source is not None:
                    last_source.write_bytes({"binary": b"\x00binary source", "empty": b"",
                                             "oversized": b"a" * 10_001}[unusable_source])
                    corpus, cfg = await index_api.load_corpus_and_scoped_config(repo)
                    proposal = proposal.model_copy(update={
                        "input_fingerprint": await index_api.graph_schema_input_fingerprint(corpus, cfg),
                    })
                    await pg.set_graph_schema_proposal(repo, proposal)
                run = uuid4().hex
                assert (await pg.acquire_index_fence(repo, run, started_at=datetime.now(UTC),
                    owner="pytest:index-recovery", lease_seconds=3600)).acquired
            recovery_gateway.mode = "refusal" if first_fails and attempt == 0 else "valid"
            previous_generation = await pg.get_generation(repo)
            request = IndexRequest(corpus_id=repo, repo_path=str(source), approved_graph_schema_hash=proposal.schema_hash)
            await index_api._background_index_job(request, asyncio.Queue(), run_id=run, config_snapshot=cfg)
            await asyncio.to_thread(index_api._EVENT_WRITE_QUEUE.join)
            result = IndexRunSummary.model_validate_json(index_api._run_summary_path(repo, run).read_text())
            assert result.graph_metadata is not None, result.error
            extraction = result.graph_metadata.extraction
            assert extraction.outcome_version == "checkpoint_v1"
            assert extraction.progress_owner_run_id == run
            selected = 1 if attempt and unusable_source is not None else 2
            assert extraction.selected_chunks == selected
            assert extraction.attempted_chunks == selected
            assert extraction.unfinished_chunks == 0
            current = await pg.get_corpus(repo)
            partition = current["meta"]["graph_extraction_checkpoint_partition"]
            assert pg._pool is not None
            keys = {row["cache_key"] for row in await pg._pool.fetch(
                "SELECT cache_key FROM graph_extraction_checkpoints WHERE repo_id=$1", repo,
            )}
            if attempt and unusable_source is not None:
                assert result.status == "error", result.error
                assert result.graph_promotable is False
                assert extraction.succeeded_chunks == extraction.reused_chunks == 1
                assert partition["complete"] is False
                assert await pg.get_generation(repo) == previous_generation
                assert keys == saved_keys, "An extraction-failed source must not be pruned as deleted"
                continue
            if first_fails and attempt == 0:
                assert result.status == "error", result.error
                assert result.graph_promotable is False
                assert extraction.succeeded_chunks == 1 and extraction.failed_chunks == 1
                assert "extraction_failure" in result.graph_failure_codes
                assert "graph_build_or_promotion_failure" not in result.graph_failure_codes
                assert partition["complete"] is False
                assert await pg.get_generation(repo) is None
            else:
                assert result.status == "complete", result.error
                assert result.graph_promotable is True
                assert extraction.succeeded_chunks == 2 and extraction.failed_chunks == 0
                assert partition["complete"] is True
                generation = await pg.get_generation(repo)
                assert generation is not None and generation.graph_repo_id is not None
                graph_ids.append(generation.graph_repo_id)
                for key in keys:
                    checkpoint = await pg.get_graph_extraction_checkpoint(repo, key)
                    assert checkpoint is not None
                    document = await pg.get_document(repo, checkpoint.identity.file_path)
                    assert document is not None
                    expected = hashlib.sha256((source / checkpoint.identity.file_path).read_bytes()).hexdigest()
                    assert document.sha256 == checkpoint.identity.file_sha256 == expected
            saved_keys = keys
            if attempt:
                assert extraction.reused_chunks == (1 if first_fails else 2)
                if not first_fails:
                    assert extraction.worker_seconds == 0
        assert len(recovery_gateway.requests) == (3 if first_fails else 2)
    finally:
        await qdrant.delete_corpus(repo)
        for graph_id in graph_ids:
            await neo.delete_graph(graph_id)
        await neo.disconnect()
        config_store.get_config_store().clear_cache(repo)
