"""Recovery through the official HTTP extractor and real corpus-owned Postgres rows."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import sys
import threading
from collections.abc import AsyncIterator, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from neo4j_graphrag.components.schema import GraphSchema, NodeType, PropertyType, RelationshipType
from neo4j_graphrag.components.types import Neo4jGraph
from neo4j_graphrag.exceptions import LLMGenerationError
from pydantic import ValidationError

from server.db.postgres import PostgresClient
from server.indexing.extraction_checkpoint import ExtractionCheckpointContext, ExtractionProgress
from server.indexing.graphrag_pipeline import (
    GraphScopeCollisionError,
    SemanticPipeline,
    chunks_to_text_chunks,
    document_info,
    extraction_checkpoint_recipe,
    extraction_prompt_template,
    semantic_entity_relation_extractor,
    semantic_extraction_llm,
)
from server.indexing.graphrag_schema import closed_graph_schema
from server.models.graph_extraction_checkpoint import (
    GraphExtractionCheckpointCorruptError,
    GraphExtractionCheckpointError,
    GraphExtractionCheckpointFenceError,
    graph_extraction_cache_key,
)
from server.models.index import Chunk, ChunkProvenance
from server.models.run_accounting import RunRequestCensus
from server.observability.run_census import RunCensusScope, RunIdentity
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.asyncio]

PROMPT = "Extract the Apollo mission facts with this schema: {schema}\n{examples}\n{text}"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _schema() -> GraphSchema:
    return closed_graph_schema(GraphSchema(
        node_types=[NodeType(label=label, properties=[PropertyType(name="name", type="STRING")])
                    for label in ("Mission", "Spacecraft")],
        relationship_types=[RelationshipType(label="USED")],
        patterns=[("Mission", "USED", "Spacecraft")],
        additional_node_types=False, additional_relationship_types=False,
        additional_patterns=False,
    ))


def _chunks(count: int = 4, *, file_path: str = "A11_MissionReport.pdf") -> list[Chunk]:
    return [Chunk(
        chunk_id=f"apollo-section-{index}",
        content=f"Mission section {index}: Apollo 11 used the Eagle lunar module.",
        file_path=file_path, start_line=1 + index * 3, end_line=3 + index * 3,
        metadata={"section": index, "source": {"document": "Apollo 11 mission report"}},
        provenance=ChunkProvenance(extraction="docling"),
    ) for index in range(count)]


def _route(base: str) -> dict[str, Any]:
    return dict(route_model="openai.gpt-5.6-sol", route_base_url=base,
                route_api_key="local-fixture-only", route_upstream="openrouter/openai/gpt-5.6-sol",
                reasoning_effort="low")


@dataclass
class RecoveryGateway:
    base: str = ""
    requests: list[int] = field(default_factory=list)
    mode: str = "valid"
    failing_section: int = 2
    arrival: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def recovery_gateway() -> Iterator[RecoveryGateway]:
    gateway = RecoveryGateway()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:
            pass

        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            match = re.search(r"Mission section (\d+):", json.dumps(payload))
            assert match is not None
            section = int(match.group(1))
            gateway.requests.append(section)
            gateway.arrival.set()
            mode = gateway.mode
            status = 200
            if section == gateway.failing_section and mode in {"timeout", "refusal"}:
                if mode == "timeout":
                    gateway.release.wait(10)
                else:
                    status = 400
            if mode == "held" or (mode == "held-section" and section == gateway.failing_section):
                gateway.release.wait(10)
            graph: dict[str, Any] = {
                "nodes": [
                    {"id": "mission", "label": "Mission", "properties": {"name": "Apollo 11"}},
                    {"id": "eagle", "label": "Spacecraft", "properties": {"name": "Eagle"}},
                ],
                "relationships": [{"start_node_id": "mission", "end_node_id": "eagle", "type": "USED"}],
            }
            if mode == "empty":
                graph = {"nodes": [], "relationships": []}
            elif mode == "prune":
                graph["nodes"][0]["properties"]["unapproved_observation"] = "The mission lasted eight days."
                graph["relationships"][0]["properties"] = {"unapproved_observation": "Eagle landed on the Moon."}
                graph["nodes"].append({"id": "outside", "label": "Unapproved", "properties": {"name": "noise"}})
                graph["relationships"].append({"start_node_id": "mission", "end_node_id": "outside", "type": "USED"})
            elif mode == "conflicting-id":
                graph["nodes"].append({"id": "mission", "label": "Mission", "properties": {"name": "Apollo 12"}})
            elif mode == "identical-id":
                graph["nodes"].append(dict(graph["nodes"][0]))
            elif mode.startswith("reserved-"):
                target = graph["relationships"][0] if "relationship" in mode else graph["nodes"][0]
                if "embedding" in mode:
                    target["embedding_properties"] = {"corpus_id": [0.25]}
                else:
                    target.setdefault("properties", {})["corpus_id"] = "foreign-corpus"
            elif mode == "lexical-node":
                graph["nodes"].append({"id": "lexical", "label": "Chunk", "properties": {"name": "untrusted"}})
            elif mode == "invalid-graph":
                graph["nodes"][0].pop("label")
            body = json.dumps({
                "id": f"apollo-fixture-{section}", "object": "chat.completion", "created": 1,
                "model": "openai.gpt-5.6-sol",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {
                    "role": "assistant", "content": json.dumps(graph),
                }}],
                "usage": {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50},
            } if status == 200 else {"error": {"message": "Apollo fixture refusal", "type": "invalid_request_error"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    gateway.base = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield gateway
    finally:
        gateway.release.set()
        server.shutdown()
        server.server_close()
        thread.join(5)


@pytest_asyncio.fixture
async def recovery_store() -> AsyncIterator[tuple[PostgresClient, str, str]]:
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    repo, run = f"pytest_extraction_recovery_{uuid4().hex}", uuid4().hex
    await pg.connect()
    await pg.upsert_corpus(repo, name="Apollo mission extraction recovery", root_path=".")
    assert (await pg.acquire_index_fence(repo, run, started_at=datetime.now(UTC),
                                       owner="pytest:recovery", lease_seconds=3600)).acquired
    try:
        yield pg, repo, run
    finally:
        await pg.delete_corpus_with_data(repo)
        await pg.disconnect()


async def _next_owner(pg: PostgresClient, repo: str, run: str) -> str:
    assert await pg.release_index_fence(repo, run)
    new_run = uuid4().hex
    assert (await pg.acquire_index_fence(repo, new_run, started_at=datetime.now(UTC),
                                       owner="pytest:restarted-worker", lease_seconds=3600)).acquired
    return new_run


def _context(pg: PostgresClient, repo: str, run: str, base: str, *,
             progress: Any = None, prompt: str = PROMPT, examples: str = "",
             schema: GraphSchema | None = None) -> ExtractionCheckpointContext:
    route = _route(base)
    route.pop("route_api_key")
    return ExtractionCheckpointContext(
        postgres=pg, repo_id=repo, owner_run_id=run, progress=progress,
        recipe=extraction_checkpoint_recipe(schema=schema or _schema(), prompt_template=prompt,
                                             examples=examples, **route),
    )


async def _extract(context: ExtractionCheckpointContext, base: str, *,
                   chunks: list[Chunk] | None = None, timeout: int = 1, concurrency: int = 1,
                   prompt: str = PROMPT, examples: str = "", schema: GraphSchema | None = None,
                   source_digest: str | None = None, census: RunCensusScope | None = None) -> Neo4jGraph:
    selected = chunks if chunks is not None else _chunks()
    graph_schema = schema or _schema()
    llm = semantic_extraction_llm(**_route(base), llm_timeout_s=timeout, census_scope=census)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=prompt,
        max_concurrency=concurrency, checkpoint_context=context, census_scope=census)
    pipeline = SemanticPipeline(llm, extractor)
    try:
        text_chunks = chunks_to_text_chunks(selected)
        file = await context.prepare_file(
            file_path=selected[0].file_path, file_sha256=source_digest or _digest("Apollo source bytes"),
            chunks=selected, text_chunks=text_chunks, schema=graph_schema,
            prompt_template=extraction_prompt_template(prompt), examples=examples,
        )
        return await extractor.run(chunks=text_chunks, document_info=document_info(selected[0].file_path),
            schema=graph_schema, examples=examples, checkpoint_context=file)
    finally:
        await pipeline.aclose()


async def test_successful_checkpoint_tasks_are_released_while_the_file_is_still_running(
    recovery_store, recovery_gateway,
) -> None:
    pg, repo, run = recovery_store
    retained_during_commits: list[int] = []
    events: list[ExtractionProgress] = []

    def observe(event: ExtractionProgress) -> None:
        events.append(event)
        if event.phase == "succeeded":
            # This callback runs inside the current real commit before its task
            # returns. Previous successful tasks must already be released.
            retained_during_commits.append(len(context._writes))

    context = _context(pg, repo, run, recovery_gateway.base, progress=observe)
    graph = await _extract(context, recovery_gateway.base, chunks=_chunks(24), timeout=3)
    assert graph.nodes
    assert retained_during_commits and len(retained_during_commits) == 24
    assert max(retained_during_commits) <= 1, retained_during_commits
    assert recovery_gateway.requests == list(range(24))
    for event in events:
        if event.phase == "succeeded":
            assert await pg.get_graph_extraction_checkpoint(repo, event.cache_key) is not None


@pytest.mark.parametrize("empty", ["both", "source", "official"])
async def test_empty_file_preparation_preserves_existing_durable_checkpoints(
    recovery_store, recovery_gateway, empty: str,
) -> None:
    pg, repo, run = recovery_store
    prior_events: list[ExtractionProgress] = []
    prior = _context(pg, repo, run, recovery_gateway.base, progress=prior_events.append)
    await _extract(prior, recovery_gateway.base, chunks=_chunks(1))
    saved = next(event for event in prior_events if event.phase == "succeeded")
    checkpoint = await pg.get_graph_extraction_checkpoint(repo, saved.cache_key)
    assert checkpoint is not None
    run = await _next_owner(pg, repo, run)
    partition = (await pg.get_corpus(repo))["meta"]["graph_extraction_checkpoint_partition"]
    observations: list[ExtractionProgress] = []
    context = _context(pg, repo, run, recovery_gateway.base, progress=observations.append)
    with pytest.raises(GraphExtractionCheckpointError):
        await context.prepare_file(
            file_path="A11_MissionReport.pdf", file_sha256=_digest("Apollo source bytes"),
            chunks=[] if empty in {"both", "source"} else _chunks(1),
            text_chunks=chunks_to_text_chunks([] if empty in {"both", "official"} else _chunks(1)),
            schema=_schema(), prompt_template=extraction_prompt_template(PROMPT),
        )
    assert context._files == {} and context._writes == set() and observations == []
    assert await pg.get_graph_extraction_checkpoint(repo, saved.cache_key) == checkpoint
    assert (await pg.get_corpus(repo))["meta"]["graph_extraction_checkpoint_partition"] == partition
    assert recovery_gateway.requests == [0]


async def _worker(arguments_path: str) -> None:
    """Separate interpreter: no parent clients, context, or in-memory graphs survive."""
    args = json.loads(Path(arguments_path).read_text())
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await pg.connect()
    events: list[ExtractionProgress] = []

    def progress(event: ExtractionProgress) -> None:
        events.append(event)
        if args.get("exit_after_commit") and event.phase == "succeeded":
            os._exit(23)

    context = _context(pg, args["repo"], args["run"], args["base"], progress=progress)
    try:
        graph = await _extract(context, args["base"], timeout=args.get("timeout", 1),
                               concurrency=args.get("concurrency", 1))
        print(json.dumps({"nodes": len(graph.nodes), "events": [asdict(event) for event in events]}))
    finally:
        await pg.disconnect()


async def _start_worker(tmp_path: Path, *, repo: str, run: str, base: str,
                        exit_after_commit: bool = False, timeout: int = 1,
                        concurrency: int = 1) -> tuple[int, str]:
    args = tmp_path / f"apollo-worker-{uuid4().hex}.json"
    args.write_text(json.dumps(dict(repo=repo, run=run, base=base,
                                   exit_after_commit=exit_after_commit, timeout=timeout, concurrency=concurrency)))
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c",
        "import asyncio,sys; from tests.integration.test_graphrag_extraction_recovery import _worker; asyncio.run(_worker(sys.argv[1]))",
        str(args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    assert process.returncode in {0, 23}, stderr.decode()
    return int(process.returncode), stdout.decode()


@pytest.mark.parametrize("failure", ["timeout", "refusal"])
async def test_new_worker_dispatches_only_missing_chunks_after_partial_failure(
    recovery_store, recovery_gateway: RecoveryGateway, tmp_path: Path, failure: str,
) -> None:
    pg, repo, run = recovery_store
    gateway = recovery_gateway
    gateway.mode = failure
    first_events: list[ExtractionProgress] = []
    with pytest.raises(LLMGenerationError):
        await _extract(_context(pg, repo, run, gateway.base, progress=first_events.append), gateway.base)
    assert [event.chunk_id for event in first_events if event.phase == "succeeded"] == [
        "apollo-section-0", "apollo-section-1",
    ]
    before = list(gateway.requests)
    assert before.count(2) == 1
    gateway.mode = "valid"
    gateway.release.set()
    run = await _next_owner(pg, repo, run)
    _, output = await _start_worker(tmp_path, repo=repo, run=run, base=gateway.base,
                                   timeout=3, concurrency=3)
    assert sorted(gateway.requests[len(before):]) == [2, 3]
    events = json.loads(output)["events"]
    assert sorted(row["chunk_id"] for row in events if row["phase"] == "reused") == [
        "apollo-section-0", "apollo-section-1",
    ]
    assert [row["sequence"] for row in events] == list(range(1, len(events) + 1))


async def test_abrupt_worker_exit_keeps_committed_graph_for_a_separate_restarted_worker(
    recovery_store, recovery_gateway: RecoveryGateway, tmp_path: Path,
) -> None:
    pg, repo, run = recovery_store
    code, _ = await _start_worker(tmp_path, repo=repo, run=run, base=recovery_gateway.base,
                                 exit_after_commit=True)
    assert code == 23
    assert recovery_gateway.requests == [0]
    run = await _next_owner(pg, repo, run)
    await _start_worker(tmp_path, repo=repo, run=run, base=recovery_gateway.base)
    assert recovery_gateway.requests == [0, 1, 2, 3]


@pytest.mark.parametrize("change", ["bytes", "content", "chunk_id", "file_path", "start_line",
                                    "end_line", "order", "metadata", "provenance", "schema",
                                    "prompt", "examples"])
async def test_actual_extraction_identity_inputs_prevent_reuse(recovery_store, recovery_gateway, change: str) -> None:
    pg, repo, run = recovery_store
    base = recovery_gateway.base
    await _extract(_context(pg, repo, run, base), base, chunks=_chunks(2))
    run = await _next_owner(pg, repo, run)
    chunks = _chunks(2)
    schema, prompt, examples = _schema(), PROMPT, ""
    source = _digest("Apollo source bytes")
    if change == "bytes":
        source = _digest("Revised Apollo source bytes")
    elif change == "content":
        chunks[0].content += " The module landed in the Sea of Tranquility."
    elif change == "chunk_id":
        chunks[0].chunk_id += "-revised"
    elif change == "file_path":
        for chunk in chunks:
            chunk.file_path = "archive/A11_MissionReport.pdf"
    elif change == "start_line":
        chunks[0].start_line += 1
    elif change == "end_line":
        chunks[0].end_line += 1
    elif change == "order":
        chunks[0].start_line, chunks[0].end_line = 20, 23
    elif change == "metadata":
        chunks[0].metadata["source"]["revision"] = 2
    elif change == "provenance":
        chunks[0].provenance = ChunkProvenance(extraction="direct")
    elif change == "schema":
        schema = schema.model_copy(update={"node_types": (*schema.node_types, NodeType(label="LandingSite"))})
    elif change == "prompt":
        prompt += " Preserve explicit names."
    elif change == "examples":
        examples = "Apollo 12 used Intrepid."
    before = len(recovery_gateway.requests)
    await _extract(_context(pg, repo, run, base, schema=schema, prompt=prompt, examples=examples),
                   base, chunks=chunks, schema=schema, prompt=prompt, examples=examples, source_digest=source)
    expected = 2 if change in {"bytes", "file_path", "order", "schema", "prompt", "examples"} else 1
    assert len(recovery_gateway.requests) - before == expected


async def test_identical_corpora_do_not_share_extraction_and_runtime_controls_do_not_change_identity(
    recovery_store, recovery_gateway,
) -> None:
    pg, repo, run = recovery_store
    base = recovery_gateway.base
    await _extract(_context(pg, repo, run, base), base)
    run = await _next_owner(pg, repo, run)
    events: list[ExtractionProgress] = []
    census_rows: list[RunRequestCensus] = []
    census = RunCensusScope(RunIdentity(run, repo, "semantic_kg"),
                           lambda row: census_rows.append(RunRequestCensus.model_validate(asdict(row))))
    await _extract(_context(pg, repo, run, base, progress=events.append), base,
                   timeout=4, concurrency=4, census=census)
    census.finish_owner()
    assert len(recovery_gateway.requests) == 4
    assert len([event for event in events if event.phase == "reused"]) == 4
    assert all(event.duration_s == 0 for event in events if event.phase == "reused")
    assert census_rows[-1].started_requests == 0
    sibling, sibling_run = f"{repo}_sibling", uuid4().hex
    await pg.upsert_corpus(sibling, name="Separate Apollo corpus", root_path=".")
    assert (await pg.acquire_index_fence(sibling, sibling_run, started_at=datetime.now(UTC),
                                       owner="pytest:sibling", lease_seconds=3600)).acquired
    try:
        await _extract(_context(pg, sibling, sibling_run, base), base)
        assert len(recovery_gateway.requests) == 8
    finally:
        await pg.delete_corpus_with_data(sibling)


@pytest.mark.parametrize("mode", ["reserved-node", "reserved-relationship", "reserved-node-embedding",
                                  "reserved-relationship-embedding", "conflicting-id", "lexical-node", "invalid-graph"])
async def test_invalid_provider_graph_never_becomes_reusable(recovery_store, recovery_gateway, mode: str) -> None:
    pg, repo, run = recovery_store
    recovery_gateway.mode = mode
    expected_error: type[Exception]
    if mode.startswith("reserved-"):
        expected_error, message = ValidationError, "server-owned scope properties"
    elif mode == "conflicting-id":
        expected_error, message = ValueError, "conflicting identity"
    elif mode == "lexical-node":
        expected_error, message = GraphScopeCollisionError, "server-owned lexical"
    else:
        expected_error, message = LLMGenerationError, "improper format"
    with pytest.raises(expected_error, match=message):
        await _extract(_context(pg, repo, run, recovery_gateway.base), recovery_gateway.base, chunks=_chunks(1))
    assert recovery_gateway.requests == [0]
    assert pg._pool is not None
    assert await pg._pool.fetchval("SELECT count(*) FROM graph_extraction_checkpoints WHERE repo_id=$1", repo) == 0


@pytest.mark.parametrize("mode,removed_nodes,removed_relationships", [("prune", 1, 1), ("identical-id", 1, 0), ("empty", 0, 0)])
async def test_pruned_or_empty_official_graphs_reuse_without_mutating_persisted_ids(
    recovery_store, recovery_gateway, mode: str, removed_nodes: int, removed_relationships: int,
) -> None:
    pg, repo, run = recovery_store
    recovery_gateway.mode = mode
    events: list[ExtractionProgress] = []
    graph = await _extract(_context(pg, repo, run, recovery_gateway.base, progress=events.append),
                           recovery_gateway.base, chunks=_chunks(1))
    success = next(event for event in events if event.phase == "succeeded")
    stored = await pg.get_graph_extraction_checkpoint(repo, success.cache_key)
    assert stored is not None
    assert stored.pruned_nodes == removed_nodes
    assert stored.pruned_relationships == removed_relationships
    assert stored.identity.recipe.approved_schema.relationship_types[0].additional_properties is False
    assert all(set(node.properties) == {"name"} for node in stored.graph.nodes)
    assert all(relationship.properties == {} for relationship in stored.graph.relationships)
    assert all(not node.id.startswith("apollo-section-") for node in stored.graph.nodes)
    original = stored.model_dump(mode="json")
    graph.nodes[0].properties["changed_by_consumer"] = True
    run = await _next_owner(pg, repo, run)
    await _extract(_context(pg, repo, run, recovery_gateway.base), recovery_gateway.base, chunks=_chunks(1))
    assert recovery_gateway.requests == [0]
    assert (await pg.get_graph_extraction_checkpoint(repo, success.cache_key)).model_dump(mode="json") == original


async def _wait_blocked(connection: asyncpg.Connection, blocker_pid: int) -> None:
    async with asyncio.timeout(8):
        while not await connection.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid))", blocker_pid,
        ):
            await asyncio.sleep(0.01)


async def test_cancellation_drains_the_initiated_real_commit_before_closing_the_producer(
    recovery_store, recovery_gateway,
) -> None:
    pg, repo, run = recovery_store
    events: list[ExtractionProgress] = []
    census_rows: list[RunRequestCensus] = []
    census = RunCensusScope(RunIdentity(run, repo, "semantic_kg"),
                           lambda row: census_rows.append(RunRequestCensus.model_validate(asdict(row))))
    context = _context(pg, repo, run, recovery_gateway.base, progress=events.append)
    chunks = _chunks(1)
    text_chunks = chunks_to_text_chunks(chunks)
    file = await context.prepare_file(file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
        chunks=chunks, text_chunks=text_chunks, schema=_schema(), prompt_template=extraction_prompt_template(PROMPT))
    llm = semantic_extraction_llm(**_route(recovery_gateway.base), llm_timeout_s=3, census_scope=census)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=PROMPT, max_concurrency=1,
                                                    checkpoint_context=context, census_scope=census)
    pipeline = SemanticPipeline(llm, extractor)
    assert pg._pool is not None
    task = None
    close = None
    try:
        async with pg._pool.acquire() as connection:
            async with connection.transaction():
                pid = await connection.fetchval("SELECT pg_backend_pid()")
                await connection.fetchrow("SELECT repo_id FROM corpora WHERE repo_id=$1 FOR UPDATE", repo)
                task = asyncio.create_task(extractor.run(chunks=text_chunks, schema=_schema(), checkpoint_context=file))
                await _wait_blocked(connection, pid)
                task.cancel()
                task.cancel()
                close = asyncio.create_task(pipeline.aclose())
                await asyncio.sleep(0)
                assert not close.done()
                assert census_rows[-1].active_producers == 1
                assert not any(event.phase == "succeeded" for event in events)
            await close
        await asyncio.gather(task, return_exceptions=True)
        success = next(event for event in events if event.phase == "succeeded")
        assert await pg.get_graph_extraction_checkpoint(repo, success.cache_key) is not None
        assert census_rows[-1].active_producers == 0
        assert not any(event.phase == "cancelled" for event in events)
        assert recovery_gateway.requests == [0]
    finally:
        await pipeline.aclose()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if close is not None:
            await close


@pytest.mark.parametrize("failure", ["corrupt", "closed-pool", "replaced-fence"])
async def test_checkpoint_read_or_storage_failure_never_dispatches_a_replacement_call(
    recovery_store, recovery_gateway, failure: str,
) -> None:
    pg, repo, run = recovery_store
    events: list[ExtractionProgress] = []
    await _extract(_context(pg, repo, run, recovery_gateway.base, progress=events.append),
                   recovery_gateway.base, chunks=_chunks(1))
    success = next(event for event in events if event.phase == "succeeded")
    run = await _next_owner(pg, repo, run)
    context = _context(pg, repo, run, recovery_gateway.base)
    private_pool = None
    expected_error: type[Exception]
    if failure == "corrupt":
        expected_error = GraphExtractionCheckpointCorruptError
        assert pg._pool is not None
        await pg._pool.execute("UPDATE graph_extraction_checkpoints SET envelope=envelope-'graph' WHERE repo_id=$1", repo)
    elif failure == "replaced-fence":
        expected_error = GraphExtractionCheckpointFenceError
        await _next_owner(pg, repo, run)
    else:
        expected_error = asyncpg.InterfaceError
        private_pg = PostgresClient(require_env("POSTGRES_DSN"))
        private_pool = await asyncpg.create_pool(require_env("POSTGRES_DSN"), min_size=1, max_size=2)
        assert private_pool is not None
        private_pg._pool = private_pool
        context = _context(private_pg, repo, run, recovery_gateway.base)
        private_pool.terminate()
    try:
        with pytest.raises(expected_error):
            await _extract(context, recovery_gateway.base, chunks=_chunks(1))
        assert recovery_gateway.requests == [0]
    finally:
        if private_pool is not None:
            await private_pool.close()
    if failure == "corrupt":
        with pytest.raises(GraphExtractionCheckpointCorruptError):
            await pg.get_graph_extraction_checkpoint(repo, success.cache_key)


async def test_telemetry_callback_failure_does_not_erase_durable_extraction(recovery_store, recovery_gateway) -> None:
    pg, repo, run = recovery_store

    def broken_progress(event: ExtractionProgress) -> None:
        if event.phase == "succeeded":
            raise RuntimeError("The progress consumer rejected this update")

    context = _context(pg, repo, run, recovery_gateway.base, progress=broken_progress)
    await _extract(context, recovery_gateway.base, chunks=_chunks(1))
    assert context.progress_error is not None
    with pytest.raises(GraphExtractionCheckpointError):
        await context.finish_success()
    run = await _next_owner(pg, repo, run)
    await _extract(_context(pg, repo, run, recovery_gateway.base), recovery_gateway.base, chunks=_chunks(1))
    assert recovery_gateway.requests == [0]


async def test_mutated_prepared_inputs_fail_before_dispatch(recovery_store, recovery_gateway) -> None:
    pg, repo, run = recovery_store
    context = _context(pg, repo, run, recovery_gateway.base)
    chunks = _chunks(1)
    official = chunks_to_text_chunks(chunks)
    file = await context.prepare_file(file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
        chunks=chunks, text_chunks=official, schema=_schema(), prompt_template=extraction_prompt_template(PROMPT))
    assert len(file.identities) == 1
    assert graph_extraction_cache_key(file.identities[0]) == file.keys[0]
    official.chunks[0].text += " This sentence was added after selection."
    llm = semantic_extraction_llm(**_route(recovery_gateway.base), llm_timeout_s=3)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=PROMPT, max_concurrency=1,
                                                    checkpoint_context=context)
    try:
        with pytest.raises(GraphExtractionCheckpointError):
            await extractor.run(chunks=official, schema=_schema(), checkpoint_context=file)
        assert recovery_gateway.requests == []
    finally:
        await SemanticPipeline(llm, extractor).aclose()


@pytest.mark.requires_neo4j
@pytest.mark.parametrize("empty", [False, True])
async def test_reused_graphs_follow_the_complete_official_file_pipeline_and_generation_invariants(
    recovery_store, recovery_gateway, empty: bool,
) -> None:
    from neo4j import GraphDatabase

    from server.config import load_config
    from server.db.neo4j import Neo4jClient
    from server.indexing.graph_invariants import evaluate_graph_invariants
    from server.indexing.graphrag_pipeline import (
        build_semantic_pipeline,
        resolve_staged_entities,
        write_semantic_file_graph,
    )
    from server.models.index import GraphExtractionTelemetry

    pg, repo, first_run = recovery_store
    cfg = load_config()
    database = cfg.graph_storage.resolve_database(repo)
    uri = os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri)
    user = os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user)
    password = os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password())
    driver = GraphDatabase.driver(uri, auth=(user, password))
    neo = Neo4jClient(uri, user, password, database=database)
    await neo.connect()
    run = first_run
    staged_ids: list[str] = []
    recovery_gateway.mode = "empty" if empty else "prune"
    try:
        for attempt in range(2):
            if attempt:
                run = await _next_owner(pg, repo, run)
            events: list[ExtractionProgress] = []
            context = _context(pg, repo, run, recovery_gateway.base, progress=events.append)
            staging = f"__staging__{repo}__{run}"
            staged_ids.append(staging)
            pipeline = await asyncio.to_thread(build_semantic_pipeline,
                driver=driver, neo4j_database=database, repo_id=staging, run_id=run,
                **_route(recovery_gateway.base), max_concurrency=2, llm_timeout_s=3,
                prompt_template=PROMPT, checkpoint_context=context)
            try:
                telemetry = await write_semantic_file_graph(pipeline=pipeline,
                    file_path="A11_MissionReport.pdf", chunks=_chunks(3), schema=_schema(),
                    file_sha256=_digest("Apollo source bytes"))
                assert telemetry.pruned_nodes == (0 if empty else 3)
                assert telemetry.pruned_relationships == (0 if empty else 3)
                completed = context._files["A11_MissionReport.pdf"]
                assert completed.written
                assert completed._official_chunks == ()
                assert completed.identities == completed.keys == ()
                assert completed.outcomes == {}
                assert completed._schema == completed._examples_digest == completed._template_digest == ""
                assert completed.pruned_nodes == telemetry.pruned_nodes
                assert completed.pruned_relationships == telemetry.pruned_relationships
                with pytest.raises(GraphExtractionCheckpointError, match="once"):
                    completed.mark_written()
                with pytest.raises(GraphExtractionCheckpointError, match="once"):
                    await context.prepare_file(
                        file_path="A11_MissionReport.pdf", chunks=_chunks(3),
                        text_chunks=chunks_to_text_chunks(_chunks(3)), schema=_schema(),
                        prompt_template=extraction_prompt_template(PROMPT),
                        file_sha256=_digest("Apollo source bytes"),
                    )
                if not empty:
                    await resolve_staged_entities(driver=driver, neo4j_database=database,
                                                  repo_id=staging, policy="semantic")
            finally:
                await pipeline.aclose()
            corpus = await pg.get_corpus(repo)
            assert corpus["meta"]["graph_extraction_checkpoint_partition"]["complete"] is False
            counts = await neo.get_graph_invariant_counts(staging, run, identity_property="name")
            report = evaluate_graph_invariants(policy="semantic", expected_chunks=3,
                schema_hash=_digest("approved Apollo schema"), counts=counts,
                extraction=GraphExtractionTelemetry(
                    selected_chunks=telemetry.selected_chunks, attempted_chunks=telemetry.attempted_chunks,
                    succeeded_chunks=telemetry.succeeded_chunks, failed_chunks=telemetry.failed_chunks,
                    truncated_chunks=len(_chunks(3)) - telemetry.selected_chunks,
                    extracted_entities=telemetry.extracted_entities,
                    semantic_relationships=telemetry.semantic_relationships,
                    from_chunk_relationships=telemetry.from_chunk_relationships,
                ))
            if empty:
                assert not report.promotable
                assert {"zero_entities", "zero_semantic_relationships"} <= set(report.failure_codes)
            else:
                assert report.promotable, report.failure_codes
                await context.finish_success()
                corpus = await pg.get_corpus(repo)
                assert corpus["meta"]["graph_extraction_checkpoint_partition"]["complete"] is True
            links = await neo.execute_cypher(
                "MATCH (:Chunk {repo_id:$repo})-[r:NEXT_CHUNK]->(:Chunk {repo_id:$repo}) RETURN count(r) AS n",
                {"repo": staging})
            assert links == [{"n": 2}]
            documents = await neo.execute_cypher(
                "MATCH (:Chunk {repo_id:$repo})-[:FROM_DOCUMENT]->(d:Document {repo_id:$repo}) "
                "RETURN count(*) AS links, count(DISTINCT d) AS documents", {"repo": staging})
            assert documents == [{"links": 3, "documents": 1}]
            scope = await neo.execute_cypher(
                "MATCH (n {repo_id:$repo}) OPTIONAL MATCH (n)-[r]->() "
                "RETURN count(CASE WHEN n.run_id<>$run OR n.run_id IS NULL THEN 1 END) AS bad_nodes, "
                "count(CASE WHEN r IS NOT NULL AND (r.run_id<>$run OR r.run_id IS NULL OR r.repo_id<>$repo) THEN 1 END) AS bad_relationships",
                {"repo": staging, "run": run})
            assert scope == [{"bad_nodes": 0, "bad_relationships": 0}]
            if attempt:
                assert len([event for event in events if event.phase == "reused"]) == 3
                assert not any(event.phase == "dispatching" for event in events)
            for event in events:
                if event.phase in {"succeeded", "reused"}:
                    stored = await pg.get_graph_extraction_checkpoint(repo, event.cache_key)
                    assert stored is not None
                    assert stored.identity.recipe.approved_schema.relationship_types[0].additional_properties is False
                    assert all(set(node.properties) == {"name"} for node in stored.graph.nodes)
                    assert all(relationship.properties == {} for relationship in stored.graph.relationships)
        assert len(recovery_gateway.requests) == 3
    finally:
        for staging in staged_ids:
            await neo.delete_graph(staging)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def test_failed_file_cannot_finish_the_checkpoint_partition(recovery_store, recovery_gateway) -> None:
    pg, repo, run = recovery_store
    recovery_gateway.mode = "refusal"
    context = _context(pg, repo, run, recovery_gateway.base)
    with pytest.raises(LLMGenerationError):
        await _extract(context, recovery_gateway.base)
    with pytest.raises(GraphExtractionCheckpointError):
        await context.finish_success()
    corpus = await pg.get_corpus(repo)
    assert corpus["meta"]["graph_extraction_checkpoint_partition"]["complete"] is False


@pytest.mark.parametrize("failure", ["closed-pool", "takeover"])
async def test_failure_after_provider_completion_does_not_retry_or_count_reusable_success(
    recovery_store, recovery_gateway, failure: str,
) -> None:
    pg, repo, run = recovery_store
    recovery_gateway.mode = "held"
    events: list[ExtractionProgress] = []
    private_pg = PostgresClient(require_env("POSTGRES_DSN"))
    private_pool = await asyncpg.create_pool(require_env("POSTGRES_DSN"), min_size=1, max_size=2)
    assert private_pool is not None
    private_pg._pool = private_pool
    context = _context(private_pg, repo, run, recovery_gateway.base, progress=events.append)
    task = asyncio.create_task(_extract(context, recovery_gateway.base, chunks=_chunks(1), timeout=5))
    assert await asyncio.to_thread(recovery_gateway.arrival.wait, 5)
    if failure == "closed-pool":
        private_pool.terminate()
    else:
        await _next_owner(pg, repo, run)
    recovery_gateway.release.set()
    try:
        expected_error = asyncpg.InterfaceError if failure == "closed-pool" else GraphExtractionCheckpointFenceError
        with pytest.raises(expected_error):
            await task
        assert recovery_gateway.requests == [0]
        assert not any(event.phase == "succeeded" for event in events)
        assert [event.phase for event in events] == ["selected", "admitted", "dispatching", "failed"]
    finally:
        await private_pool.close()


async def test_corruption_after_preparation_is_rejected_inside_admission_without_dispatch(
    recovery_store, recovery_gateway,
) -> None:
    pg, repo, run = recovery_store
    await _extract(_context(pg, repo, run, recovery_gateway.base), recovery_gateway.base, chunks=_chunks(1))
    run = await _next_owner(pg, repo, run)
    events: list[ExtractionProgress] = []
    context = _context(pg, repo, run, recovery_gateway.base, progress=events.append)
    chunks, schema = _chunks(1), _schema()
    official = chunks_to_text_chunks(chunks)
    file = await context.prepare_file(file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
        chunks=chunks, text_chunks=official, schema=schema, prompt_template=extraction_prompt_template(PROMPT))
    assert pg._pool is not None
    await pg._pool.execute("UPDATE graph_extraction_checkpoints SET envelope=envelope-'graph' WHERE repo_id=$1", repo)
    llm = semantic_extraction_llm(**_route(recovery_gateway.base), llm_timeout_s=3)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=PROMPT, max_concurrency=1,
                                                    checkpoint_context=context)
    try:
        with pytest.raises(GraphExtractionCheckpointCorruptError):
            await extractor.run(chunks=official, schema=schema, checkpoint_context=file)
        assert recovery_gateway.requests == [0]
        assert [event.phase for event in events] == ["selected", "admitted", "failed"]
    finally:
        await SemanticPipeline(llm, extractor).aclose()


async def test_prepared_file_cannot_be_replayed_inside_the_same_execution_context(recovery_store, recovery_gateway) -> None:
    pg, repo, run = recovery_store
    context = _context(pg, repo, run, recovery_gateway.base)
    chunks, schema = _chunks(1), _schema()
    official = chunks_to_text_chunks(chunks)
    file = await context.prepare_file(file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
        chunks=chunks, text_chunks=official, schema=schema, prompt_template=extraction_prompt_template(PROMPT))
    llm = semantic_extraction_llm(**_route(recovery_gateway.base), llm_timeout_s=3)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=PROMPT, max_concurrency=1,
                                                    checkpoint_context=context)
    try:
        await extractor.run(chunks=official, schema=schema, checkpoint_context=file)
        with pytest.raises(GraphExtractionCheckpointError):
            await extractor.run(chunks=official, schema=schema, checkpoint_context=file)
        assert recovery_gateway.requests == [0]
    finally:
        await SemanticPipeline(llm, extractor).aclose()


async def _wait_private_queries_blocked(connection: asyncpg.Connection, application: str, count: int) -> None:
    async with asyncio.timeout(8):
        while await connection.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE application_name=$1 AND wait_event_type='Lock'",
            application,
        ) < count:
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("fault", ["takeover", "query-cancel"])
@pytest.mark.parametrize("cancellation", ["owner", "close", "repeated"])
async def test_cancelled_commit_failure_propagates_after_all_owned_writers_drain(
    recovery_store, recovery_gateway, fault: str, cancellation: str,
) -> None:
    pg, repo, run = recovery_store
    application = f"apollo_checkpoint_commit_{uuid4().hex}"
    private_pool = await asyncpg.create_pool(require_env("POSTGRES_DSN"), min_size=2, max_size=2,
                                             server_settings={"application_name": application})
    assert private_pool is not None
    private_pg = PostgresClient(require_env("POSTGRES_DSN"))
    private_pg._pool = private_pool
    events: list[ExtractionProgress] = []
    census_rows: list[RunRequestCensus] = []
    census = RunCensusScope(RunIdentity(run, repo, "semantic_kg"),
                           lambda row: census_rows.append(RunRequestCensus.model_validate(asdict(row))))
    context = _context(private_pg, repo, run, recovery_gateway.base, progress=events.append)
    chunks, schema = _chunks(2), _schema()
    official = chunks_to_text_chunks(chunks)
    file = await context.prepare_file(file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
        chunks=chunks, text_chunks=official, schema=schema, prompt_template=extraction_prompt_template(PROMPT))
    llm = semantic_extraction_llm(**_route(recovery_gateway.base), llm_timeout_s=3, census_scope=census)
    extractor = semantic_entity_relation_extractor(llm=llm, prompt_template=PROMPT, max_concurrency=2,
                                                    checkpoint_context=context, census_scope=census)
    pipeline = SemanticPipeline(llm, extractor)
    task = None
    close = None
    assert pg._pool is not None
    try:
        async with pg._pool.acquire() as connection:
            async with connection.transaction():
                blocker_pid = await connection.fetchval("SELECT pg_backend_pid()")
                await connection.fetchrow("SELECT repo_id FROM corpora WHERE repo_id=$1 FOR UPDATE", repo)
                task = asyncio.create_task(extractor.run(chunks=official, schema=schema, checkpoint_context=file))
                await _wait_private_queries_blocked(connection, application, 2)
                assert sorted(recovery_gateway.requests) == [0, 1]
                if cancellation != "close":
                    task.cancel()
                close = asyncio.create_task(pipeline.aclose())
                await asyncio.sleep(0)
                if cancellation == "repeated":
                    task.cancel()
                    close.cancel()
                    await asyncio.sleep(0)
                    close.cancel()
                assert not close.done()
                if fault == "takeover":
                    # The same corpus row lock used by real fence takeover holds
                    # the replacement until both retained puts can observe it.
                    await connection.execute(
                        "UPDATE corpora SET meta=jsonb_set(meta, '{index_run,run_id}', to_jsonb($2::text)) WHERE repo_id=$1",
                        repo, uuid4().hex,
                    )
                else:
                    blocked_pid = await connection.fetchval(
                        "SELECT pid FROM pg_stat_activity WHERE application_name=$1 AND $2=ANY(pg_blocking_pids(pid))",
                        application, blocker_pid,
                    )
                    assert blocked_pid is not None
                    assert await connection.fetchval("SELECT pg_cancel_backend($1)", blocked_pid)
                    async with asyncio.timeout(8):
                        while not any(event.phase == "failed" for event in events):
                            await asyncio.sleep(0.01)
                    # A known first failure must not release the producer while
                    # its second already-initiated real commit still owns work.
                    assert not close.done()
                    assert census_rows[-1].active_producers == 1
                    assert not any(event.phase == "succeeded" for event in events)
                assert census_rows[-1].active_producers == 1
            results = await asyncio.wait_for(asyncio.gather(task, close, return_exceptions=True), 10)
        expected_error = GraphExtractionCheckpointFenceError if fault == "takeover" else asyncpg.QueryCanceledError
        assert isinstance(results[0], expected_error), repr(results[0])
        assert isinstance(results[1], expected_error), repr(results[1])
        # Context-level cleanup must retain the same failure even after file
        # drains have observed it and all producers/SDK clients are closed.
        with pytest.raises(expected_error):
            await context.drain_writes()
        assert census_rows[-1].active_producers == census_rows[-1].inflight == 0
        assert llm.client.is_closed() and llm.async_client.is_closed()
        assert sorted(recovery_gateway.requests) == [0, 1]
        terminals = [event for event in events if event.phase in {"succeeded", "failed", "cancelled"}]
        assert len(terminals) == 2
        assert sum(event.phase == "failed" for event in terminals) == (2 if fault == "takeover" else 1)
        for event in terminals:
            checkpoint = await pg.get_graph_extraction_checkpoint(repo, event.cache_key)
            assert (checkpoint is not None) == (event.phase == "succeeded")
    finally:
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)
        await asyncio.gather(pipeline.aclose(), return_exceptions=True)
        await private_pool.close()


@pytest.mark.parametrize(("fault", "cancel"), [
    (None, True), ("takeover", False), ("takeover", True),
    ("query-cancel", False), ("query-cancel", True),
])
async def test_preparation_failure_or_cancellation_terminates_every_selected_identity_after_drain(
    recovery_store, recovery_gateway, fault: str | None, cancel: bool,
) -> None:
    pg, repo, run = recovery_store
    application = f"apollo_checkpoint_prepare_{uuid4().hex}"
    private_pool = await asyncpg.create_pool(require_env("POSTGRES_DSN"), min_size=1, max_size=1,
                                             server_settings={"application_name": application})
    assert private_pool is not None
    private_pg = PostgresClient(require_env("POSTGRES_DSN"))
    private_pg._pool = private_pool
    events: list[ExtractionProgress] = []
    context = _context(private_pg, repo, run, recovery_gateway.base, progress=events.append)
    chunks = _chunks(4)
    task = None
    assert pg._pool is not None
    try:
        async with pg._pool.acquire() as connection:
            async with connection.transaction():
                blocker_pid = await connection.fetchval("SELECT pg_backend_pid()")
                await connection.fetchrow("SELECT repo_id FROM corpora WHERE repo_id=$1 FOR UPDATE", repo)
                task = asyncio.create_task(context.prepare_file(
                    file_path=chunks[0].file_path, file_sha256=_digest("Apollo source bytes"),
                    chunks=chunks, text_chunks=chunks_to_text_chunks(chunks), schema=_schema(),
                    prompt_template=extraction_prompt_template(PROMPT),
                ))
                await _wait_private_queries_blocked(connection, application, 1)
                assert len(events) == 4 and all(event.phase == "selected" for event in events)
                if cancel:
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    await asyncio.sleep(0)
                    assert not task.done()
                    assert all(event.phase == "selected" for event in events)
                if fault == "takeover":
                    await connection.execute(
                        "UPDATE corpora SET meta=jsonb_set(meta, '{index_run,run_id}', to_jsonb($2::text)) WHERE repo_id=$1",
                        repo, uuid4().hex,
                    )
                elif fault == "query-cancel":
                    blocked_pid = await connection.fetchval(
                        "SELECT pid FROM pg_stat_activity WHERE application_name=$1 AND $2=ANY(pg_blocking_pids(pid))",
                        application, blocker_pid,
                    )
                    assert blocked_pid is not None
                    assert await connection.fetchval("SELECT pg_cancel_backend($1)", blocked_pid)
            result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 10))[0]
        expected_error = (GraphExtractionCheckpointFenceError if fault == "takeover" else
                          asyncpg.QueryCanceledError if fault == "query-cancel" else asyncio.CancelledError)
        assert isinstance(result, expected_error), repr(result)
        terminal = "failed" if fault is not None else "cancelled"
        assert [event.sequence for event in events] == list(range(1, 9))
        assert len(events) == 8
        for chunk in chunks:
            assert [event.phase for event in events if event.chunk_id == chunk.chunk_id] == ["selected", terminal]
        assert all(event.duration_s == 0 for event in events)
        assert recovery_gateway.requests == []
        async with private_pool.acquire() as connection:
            assert not await connection.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE application_name=$1 AND wait_event_type='Lock'", application,
            )
    finally:
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(context.drain_writes(), return_exceptions=True)
        await private_pool.close()
