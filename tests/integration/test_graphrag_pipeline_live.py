from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from neo4j import GraphDatabase
from neo4j_graphrag.components.graph_pruning import GraphPruning
from neo4j_graphrag.components.kg_writer import KGWriterModel
from neo4j_graphrag.components.schema import (
    GraphSchema,
    NodeType,
    Pattern,
    PropertyType,
    RelationshipType,
)
from neo4j_graphrag.components.types import (
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
    TextChunk,
    TextChunks,
)

from server.api.index import _resolve_semantic_kg_route, graph_schema_input_fingerprint
from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.gateway_catalog import gateway_upstream_for_alias, warm_gateway_catalog
from server.indexing.generations import GenerationManifest
from server.indexing.graphrag_pipeline import (
    GraphScopeCollisionError,
    ScopedNeo4jWriter,
    build_semantic_pipeline,
    lexical_graph_config,
    semantic_entity_relation_extractor,
    semantic_extraction_llm,
    write_code_file_graph,
    write_deferred_code_relationships,
    write_semantic_file_graph,
)
from server.indexing.graphrag_schema import closed_graph_schema
from server.models.index import Chunk, GraphSchemaProposal, GraphSchemaSample
from server.models.tribrid_config_model import TriBridConfig
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [
    pytest.mark.requires_postgres,
    pytest.mark.requires_neo4j,
    pytest.mark.requires_qdrant,
    pytest.mark.asyncio,
]


@pytest.mark.parametrize(
    ("case", "text", "expected_edges"),
    [
        (
            "table_adjacency",
            "## Event timeline\n"
            "| Time | Event |\n| 10:01 | Aster alarm |\n"
            "| 10:02 | Channel reset |\n| 10:03 | Aster alarm |\n\n"
            "## Demonstrated control\nClosing Orion switch inhibits Beacon alarm.",
            {("closing orion switch", "INHIBITS", "beacon alarm")},
        ),
        (
            "section_status",
            "## Coolant pressure anomaly\nThe pressure returned to normal. "
            "This anomaly is closed.\n\n## Water in glove\n"
            "Water began entering the glove after the test started. "
            "The investigation has not established the cause or a repair.",
            set(),
        ),
        (
            "context_not_mechanism",
            "Equipment changes included inhibiting the Sensor Q temperature alarm "
            "and preventing the master alarm during Relay R selection. "
            "Closing Orion switch inhibits Beacon alarm.",
            {("closing orion switch", "INHIBITS", "beacon alarm")},
        ),
        (
            "negation_and_uncertainty",
            "Inspections found that Seal A did not cause Leak A. "
            "Bearing B may have caused Vibration B; the investigation remains open. "
            "Tests established that Gear C caused Jam C.",
            {("gear c", "CAUSES", "jam c")},
        ),
    ],
)
async def test_semantic_extraction_grounds_edges_and_attributes_in_their_own_passage(
    case: str, text: str, expected_edges: set[tuple[str, str, str]],
) -> None:
    """A broad schema must not turn table order, prior headings, or hypotheses into facts."""
    cfg = load_config()
    cfg.graph_indexing.semantic_kg_llm_model = os.environ.get(
        "GRAPH_E2E_KG_MODEL", "openai.gpt-5.6-luna"
    )
    await asyncio.to_thread(warm_gateway_catalog)
    route = _resolve_semantic_kg_route(cfg)
    llm = semantic_extraction_llm(
        route_model=route.model, route_base_url=route.base_url, route_api_key=route.api_key,
        route_upstream=gateway_upstream_for_alias(route.model), llm_timeout_s=120,
        reasoning_effort="medium",
    )
    named = [PropertyType(name="name", type="STRING")]
    schema = closed_graph_schema(GraphSchema(
        node_types=[
            NodeType(label=label, properties=named) for label in ("Event", "Alarm", "Part")
        ] + [NodeType(label="Anomaly", properties=[
            *named, PropertyType(name="status", type="STRING"),
        ])],
        relationship_types=[RelationshipType(label="INHIBITS"), RelationshipType(label="CAUSES")],
        patterns=[
            Pattern(source="Event", relationship="INHIBITS", target="Alarm"),
            Pattern(source="Part", relationship="CAUSES", target="Anomaly"),
        ],
    ))
    lexical = lexical_graph_config()
    extractor = semantic_entity_relation_extractor(
        llm=llm, prompt_template=TriBridConfig().system_prompts.semantic_kg_extraction,
        max_concurrency=1,
    )
    extracted = await extractor.run(
        chunks=TextChunks(chunks=[TextChunk(text=text, index=0, uid=f"grounding:{case}")]),
        schema=schema, lexical_graph_config=lexical,
    )
    pruned = await GraphPruning().run(graph=extracted, schema=schema, lexical_graph_config=lexical)
    entities = {
        node.id: node for node in pruned.graph.nodes
        if node.label not in lexical.lexical_graph_node_labels
    }
    edges = {
        (str(entities[rel.start_node_id].properties["name"]).casefold(), rel.type,
         str(entities[rel.end_node_id].properties["name"]).casefold())
        for rel in pruned.graph.relationships
        if rel.start_node_id in entities and rel.end_node_id in entities
    }
    if case == "context_not_mechanism":
        assert expected_edges <= edges, pruned.graph.model_dump(mode="json")
        assert not any("relay r" in source for source, _, _ in edges), edges
    else:
        assert edges == expected_edges, pruned.graph.model_dump(mode="json")
    if case == "section_status":
        water = [node for node in entities.values()
                 if str(node.properties.get("name", "")).casefold() == "water in glove"]
        assert water, pruned.graph.model_dump(mode="json")
        assert all(str(node.properties.get("status", "")).casefold() != "closed" for node in water)


def _driver_and_database(corpus_id: str):
    cfg = load_config()
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        auth=(
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        ),
    )
    return cfg, driver, cfg.graph_storage.resolve_database(corpus_id)


def _schema() -> GraphSchema:
    named = [PropertyType(name="name", type="STRING")]
    return GraphSchema(
        node_types=[
            NodeType(label="Person", description="A named person", properties=named),
            NodeType(
                label="Organization",
                description="A named organization",
                properties=named,
            ),
            NodeType(label="Location", description="A named place", properties=named),
        ],
        relationship_types=[
            RelationshipType(label="WORKS_FOR", description="Employment"),
            RelationshipType(label="LOCATED_IN", description="Location"),
        ],
        patterns=[
            Pattern(source="Person", relationship="WORKS_FOR", target="Organization"),
            Pattern(
                source="Organization", relationship="LOCATED_IN", target="Location"
            ),
        ],
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    )


async def _count(neo: Neo4jClient, query: str, repo_id: str) -> int:
    rows = await neo.execute_cypher(query, {"repo_id": repo_id})
    return int((rows[0] if rows else {}).get("n") or 0)


def _writer_fixture(prefix: str, *, with_nodes: bool = True, with_edge: bool = True) -> Neo4jGraph:
    return Neo4jGraph(
        nodes=[
            Neo4jNode(id=f"{prefix}:ada", label="Person", properties={"name": "Ada"}),
            Neo4jNode(id=f"{prefix}:grace", label="Person", properties={"name": "Grace"}),
        ] if with_nodes else [],
        relationships=[Neo4jRelationship(
            start_node_id=f"{prefix}:ada", end_node_id=f"{prefix}:grace", type="WROTE_TO"
        )] if with_edge else [],
    )


@pytest.mark.parametrize("second_cleans", [False, True])
async def test_interleaved_writers_keep_endpoints_and_cleanup_inside_their_generation(
    second_cleans: bool,
) -> None:
    runs = [uuid4().hex, uuid4().hex]
    repos = [f"__staging__pytest_writer_scope_{i}__{run}" for i, run in enumerate(runs)]
    cfg, driver, database = _driver_and_database("pytest_writer_scope")
    neo = Neo4jClient(cfg.graph_storage.neo4j_uri, cfg.graph_storage.neo4j_user,
                      cfg.graph_storage.resolve_password(), database=database)
    await neo.connect()
    prefix = uuid4().hex
    try:
        writers = [await asyncio.to_thread(
            ScopedNeo4jWriter, driver=driver, neo4j_database=database,
            repo_id=repo, run_id=run, clean_db=second_cleans and i == 1,
        ) for i, (repo, run) in enumerate(zip(repos, runs, strict=True))]
        await writers[0].run(_writer_fixture(prefix, with_edge=False), LexicalGraphConfig())
        await writers[1].run(_writer_fixture(prefix), LexicalGraphConfig())
        # The other writer's automatic cleanup must leave our deferred endpoints usable.
        assert await _count(neo,
            "MATCH (n {repo_id: $repo_id}) WHERE n.__tmp_internal_id IS NOT NULL RETURN count(n) AS n",
            repos[0]) == 2
        await writers[0].run(_writer_fixture(prefix, with_nodes=False), LexicalGraphConfig())
        for repo in repos:
            rows = await neo.execute_cypher(
                "MATCH (a)-[r:WROTE_TO {repo_id:$repo_id}]->(b) "
                "RETURN count(r) AS edges, "
                "sum(CASE WHEN a.repo_id=$repo_id AND b.repo_id=$repo_id THEN 0 ELSE 1 END) AS foreign",
                {"repo_id": repo},
            )
            assert rows == [{"edges": 1, "foreign": 0}]
        await writers[0].finalize()
        if not second_cleans:
            assert await _count(neo,
                "MATCH (n {repo_id: $repo_id}) WHERE n.__tmp_internal_id IS NOT NULL RETURN count(n) AS n",
                repos[1]) == 2
        await writers[1].finalize()
    finally:
        for repo in repos:
            await neo.delete_graph(repo)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def test_complete_writes_in_one_generation_do_not_clean_another_invocation() -> None:
    """Pause real writer phases to prove the cleanup race deterministically; no fake DB results."""
    ready = threading.Barrier(2)
    first_cleaned = threading.Event()

    class InterleavingWriter(ScopedNeo4jWriter):
        async def run(
            self, graph: Neo4jGraph, lexical_graph_config: LexicalGraphConfig | None = None
        ) -> KGWriterModel:
            return await super().run(graph, lexical_graph_config)

        def _upsert_nodes(self, nodes, lexical_graph_config):
            super()._upsert_nodes(nodes, lexical_graph_config)
            ready.wait(timeout=20)

        def _upsert_relationships(self, rels):
            if rels[0].start_node_id.endswith(":second:ada"):
                assert first_cleaned.wait(timeout=20)
            super()._upsert_relationships(rels)

        def _db_cleaning(self):
            super()._db_cleaning()
            first_cleaned.set()

    run = uuid4().hex
    repo = f"__staging__pytest_writer_invocations__{run}"
    cfg, driver, database = _driver_and_database("pytest_writer_invocations")
    neo = Neo4jClient(cfg.graph_storage.neo4j_uri, cfg.graph_storage.neo4j_user,
                      cfg.graph_storage.resolve_password(), database=database)
    await neo.connect()
    try:
        writer = await asyncio.to_thread(
            InterleavingWriter, driver=driver, neo4j_database=database, repo_id=repo, run_id=run
        )
        results = await asyncio.gather(
            writer.run(_writer_fixture(f"{run}:first"), LexicalGraphConfig()),
            writer.run(_writer_fixture(f"{run}:second"), LexicalGraphConfig()),
            return_exceptions=True,
        )
        assert not [result for result in results if isinstance(result, BaseException)]
        assert await _count(neo,
            "MATCH ()-[r:WROTE_TO {repo_id:$repo_id}]->() RETURN count(r) AS n", repo) == 2
        assert await _count(neo,
            "MATCH (n {repo_id:$repo_id}) WHERE n.__tmp_internal_id IS NOT NULL RETURN count(n) AS n",
            repo) == 0
    finally:
        await neo.delete_graph(repo)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def _wait_for_index(
    client: AsyncClient, corpus_id: str, *, timeout_s: float = 300.0
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    last: dict = {}
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/api/index/{corpus_id}/status")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"complete", "error", "cancelled"}:
            return last
        await asyncio.sleep(0.5)
    raise AssertionError(f"index did not finish within {timeout_s}s: {last}")


async def test_semantic_and_code_files_use_scoped_official_writer_contract(
    tmp_path: Path,
) -> None:
    semantic_run = uuid4().hex
    code_run = uuid4().hex
    semantic_repo = f"__staging__pytest_pipeline_semantic__{semantic_run}"
    code_repo = f"__staging__pytest_pipeline_code__{code_run}"
    cfg, driver, database = _driver_and_database("pytest_pipeline_live")
    cfg.graph_indexing.semantic_kg_llm_model = os.environ.get(
        "GRAPH_E2E_KG_MODEL", "openai.gpt-5.6-luna"
    )
    await asyncio.to_thread(warm_gateway_catalog)
    route = _resolve_semantic_kg_route(cfg)
    await asyncio.to_thread(driver.verify_connectivity)
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    await neo.connect()
    try:
        pipeline = await asyncio.to_thread(
            build_semantic_pipeline,
            driver=driver,
            neo4j_database=database,
            repo_id=semantic_repo,
            run_id=semantic_run,
            route_model=str(route.model or ""),
            route_base_url=str(route.base_url or ""),
            route_api_key=str(route.api_key or ""),
            route_upstream=gateway_upstream_for_alias(str(route.model or "")),
            max_concurrency=2,
            llm_timeout_s=int(cfg.graph_indexing.semantic_kg_llm_timeout_s),
            reasoning_effort=str(cfg.graph_indexing.semantic_kg_reasoning_effort),
            prompt_template=str(cfg.system_prompts.semantic_kg_extraction),
        )
        semantic_chunks = [
            Chunk(
                chunk_id="mission.md:1-3:0",
                content=(
                    "Alice Chen works for Northwind Labs. "
                    "Northwind Labs is located in Denver."
                ),
                file_path="mission.md",
                start_line=1,
                end_line=3,
                embedding=[0.1, 0.2],
            )
        ]
        telemetry = await write_semantic_file_graph(
            pipeline=pipeline,
            file_path="mission.md",
            chunks=semantic_chunks,
            schema=_schema(),
        )
        assert telemetry.succeeded_chunks == 1
        assert telemetry.extracted_entities >= 3
        assert telemetry.semantic_relationships >= 2
        assert telemetry.from_chunk_relationships >= 1

        code_writer = await asyncio.to_thread(
            ScopedNeo4jWriter,
            driver=driver,
            neo4j_database=database,
            repo_id=code_repo,
            run_id=code_run,
            clean_db=False,
        )
        source = "def helper(x):\n    return x\n\nclass Runner:\n    def run(self):\n        return helper(1)\n"
        code_file = "pkg/runner.py"
        code_path = tmp_path / code_file
        code_path.parent.mkdir(parents=True)
        code_path.write_text(source, encoding="utf-8")
        code_chunks = [
            Chunk(
                chunk_id=f"{code_file}:1-6:0",
                content=source,
                file_path=code_file,
                start_line=1,
                end_line=6,
                language="python",
                embedding=[0.3, 0.4],
            )
        ]
        deferred = []
        code_telemetry = await write_code_file_graph(
            writer=code_writer,
            cfg=cfg,
            repo_root=tmp_path,
            file_path=code_file,
            source=source,
            language="python",
            chunks=code_chunks,
            deferred_relationships=deferred,
        )
        await write_deferred_code_relationships(code_writer, deferred)
        assert code_telemetry.extracted_entities >= 3
        assert code_telemetry.from_chunk_relationships >= 3

        for repo_id, run_id in (
            (semantic_repo, semantic_run),
            (code_repo, code_run),
        ):
            bad_nodes = await neo.execute_cypher(
                """
                MATCH (n {repo_id: $repo_id})
                WHERE n.run_id IS NULL OR n.run_id <> $run_id
                RETURN count(n) AS n
                """,
                {"repo_id": repo_id, "run_id": run_id},
            )
            bad_relationships = await neo.execute_cypher(
                """
                MATCH (a {repo_id: $repo_id})-[r]->(b)
                WHERE r.repo_id IS NULL OR r.run_id <> $run_id
                RETURN count(r) AS n
                """,
                {"repo_id": repo_id, "run_id": run_id},
            )
            assert int(bad_nodes[0]["n"]) == 0
            assert int(bad_relationships[0]["n"]) == 0

        invalid = await neo.execute_cypher(
            """
            MATCH (n {repo_id: $repo_id})
            OPTIONAL MATCH (n)-[r]->()
            WITH collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
            RETURN
              size([n IN nodes WHERE n:Chunk AND (n.graphJoinId IS NULL OR n.embedding IS NOT NULL)]) AS bad_chunks,
              size([n IN nodes WHERE n:__Entity__ AND (n.entity_id IS NULL OR n.entity_type IS NULL)]) AS bad_entities,
              size([r IN rels WHERE type(r) IN ['IN_CHUNK', 'IN_COMMUNITY']]) AS legacy_rels,
              size([n IN nodes WHERE n:Community]) AS communities
            """,
            {"repo_id": semantic_repo},
        )
        assert invalid == [
            {"bad_chunks": 0, "bad_entities": 0, "legacy_rels": 0, "communities": 0}
        ]
        assert await _count(
            neo,
            "MATCH (:__Entity__ {repo_id: $repo_id})-[r:FROM_CHUNK]->(:Chunk) RETURN count(r) AS n",
            semantic_repo,
        ) >= 1

        writer = pipeline.get_node_by_name("writer").component
        before = await _count(
            neo, "MATCH (n {repo_id: $repo_id}) RETURN count(n) AS n", semantic_repo
        )
        with pytest.raises(GraphScopeCollisionError, match="repo_id"):
            await writer.run(
                Neo4jGraph(
                    nodes=[
                        Neo4jNode(
                            id="reserved",
                            label="Person",
                            properties={"name": "Reserved", "repo_id": "attacker"},
                        )
                    ]
                )
            )
        after = await _count(
            neo, "MATCH (n {repo_id: $repo_id}) RETURN count(n) AS n", semantic_repo
        )
        assert after == before
    finally:
        for repo_id in (semantic_repo, code_repo):
            await neo.delete_graph(repo_id)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def test_code_policy_keeps_lexical_graph_for_non_ast_files() -> None:
    run_id = uuid4().hex
    repo_id = f"__staging__pytest_pipeline_code_markdown__{run_id}"
    cfg, driver, database = _driver_and_database("pytest_pipeline_code_markdown")
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    await neo.connect()
    try:
        writer = await asyncio.to_thread(
            ScopedNeo4jWriter,
            driver=driver,
            neo4j_database=database,
            repo_id=repo_id,
            run_id=run_id,
            clean_db=False,
        )
        telemetry = await write_code_file_graph(
            writer=writer,
            cfg=cfg,
            repo_root=Path("/tmp"),
            file_path="README.md",
            source="# Read me\nThis file has no AST lane.",
            language="markdown",
            chunks=[
                Chunk(
                    chunk_id="markdown-1",
                    content="This file has no AST lane.",
                    file_path="README.md",
                    language="markdown",
                    start_line=1,
                    end_line=2,
                    token_count=7,
                )
            ],
        )

        assert telemetry.selected_chunks == 1
        assert telemetry.attempted_chunks == 1
        assert telemetry.succeeded_chunks == 1
        assert telemetry.extracted_entities == 0
        assert await _count(
            neo,
            "MATCH (:Chunk {repo_id: $repo_id})-[:FROM_DOCUMENT]->(:Document {repo_id: $repo_id}) RETURN count(*) AS n",
            repo_id,
        ) == 1
    finally:
        await neo.delete_graph(repo_id)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def test_live_writer_keeps_event_loop_responsive_for_ten_thousand_nodes() -> None:
    run_id = uuid4().hex
    repo_id = f"__staging__pytest_pipeline_ticker__{run_id}"
    cfg, driver, database = _driver_and_database("pytest_pipeline_ticker")
    await asyncio.to_thread(driver.verify_connectivity)
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    await neo.connect()
    writer = await asyncio.to_thread(
        ScopedNeo4jWriter,
        driver=driver,
        neo4j_database=database,
        repo_id=repo_id,
        run_id=run_id,
        batch_size=1000,
    )
    graph = Neo4jGraph(
        nodes=[
            Neo4jNode(id=f"entity-{index}", label="LoadNode", properties={"name": f"N{index}"})
            for index in range(10_000)
        ]
    )
    ticks = 0
    finished = asyncio.Event()

    async def _ticker() -> None:
        nonlocal ticks
        while not finished.is_set():
            ticks += 1
            await asyncio.sleep(0)

    ticker = asyncio.create_task(_ticker())
    try:
        await writer.run(graph)
        finished.set()
        await ticker
        assert ticks > 10
        assert await _count(
            neo, "MATCH (n:LoadNode {repo_id: $repo_id}) RETURN count(n) AS n", repo_id
        ) == 10_000
    finally:
        finished.set()
        await ticker
        await neo.delete_graph(repo_id)
        await neo.disconnect()
        await asyncio.to_thread(driver.close)


async def test_full_index_promotes_the_approved_official_pipeline_generation(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"pytest_pipeline_index_{uuid4().hex[:8]}"
    corpus_path = tmp_path / "acceptance_corpus"
    corpus_path.mkdir()
    combined_fixture = "\n\n".join(
        (
            f"Record {index}: Ada Lovelace works for Aurora Tidal Observatory. "
            "Aurora Tidal Observatory is located in Meridian Strait."
        )
        for index in range(24)
    )
    (corpus_path / "combined-acceptance-corpus.md").write_text(
        combined_fixture,
        encoding="utf-8",
    )
    model_alias = os.environ.get("GRAPH_E2E_KG_MODEL", "openai.gpt-5.6-luna")
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await pg.connect()
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_path)},
    )
    assert created.status_code in (200, 201), created.text
    neo: Neo4jClient | None = None
    try:
        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        cfg.chunking.chunking_strategy = "fixed_chars"
        cfg.chunking.chunk_size = 200
        cfg.chunking.chunk_overlap = 0
        cfg.indexing.indexing_batch_size = 10
        cfg.indexing.figures.enabled = False
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_code_graph = False
        cfg.graph_indexing.semantic_kg_llm_model = model_alias
        cfg.chat.litellm.enabled = True
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        config_store._store = None
        corpus = await pg.get_corpus(corpus_id)
        fingerprint = await graph_schema_input_fingerprint(corpus or {}, cfg)
        schema_payload = _schema().model_dump(mode="json")
        schema_hash = hashlib.sha256(
            json.dumps(schema_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        await pg.set_graph_schema_proposal(
            corpus_id,
            GraphSchemaProposal(
                corpus_id=corpus_id,
                policy="semantic",
                input_fingerprint=fingerprint,
                schema_hash=schema_hash,
                schema_payload=schema_payload,
                sample=GraphSchemaSample(chunk_ids=[], chunk_hashes=[]),
                model_alias=model_alias,
                created_at=datetime.now(UTC),
            ),
        )

        started = await client.post(
            "/api/index",
            json={
                "corpus_id": corpus_id,
                "repo_path": str(corpus_path),
                "force_reindex": True,
                "approved_graph_schema_hash": schema_hash,
            },
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_index(client, corpus_id)
        assert final["status"] == "complete", final

        latest = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert latest.status_code == 200, latest.text
        replay = latest.json()
        assert replay["graph_promotable"] is True
        assert replay["graph_failure_codes"] == []
        assert replay["graph_metadata"]["policy"] == "semantic"
        assert replay["graph_metadata"]["extraction"]["attempted_chunks"] > 10
        assert replay["graph_metadata"]["extraction"]["failed_chunks"] == 0
        assert replay["graph_metadata"]["resolution"]["unresolved_duplicate_groups"] == 0

        corpus = await pg.get_corpus(corpus_id)
        manifest = GenerationManifest.model_validate((corpus or {})["meta"]["generation"])
        assert manifest.graph_repo_id
        assert manifest.graph_metadata is not None
        assert manifest.graph_metadata.schema_hash == schema_hash
        assert manifest.graph_metadata.policy == "semantic"

        neo = Neo4jClient(
            os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
            database=cfg.graph_storage.resolve_database(corpus_id),
        )
        await neo.connect()
        graph_repo_id = str(manifest.graph_repo_id)
        assert await _count(
            neo,
            "MATCH (:__Entity__ {repo_id: $repo_id})-[r:FROM_CHUNK]->(:Chunk) RETURN count(r) AS n",
            graph_repo_id,
        ) > 0
        assert await _count(
            neo,
            "MATCH (c:Chunk {repo_id: $repo_id}) WHERE c.embedding IS NOT NULL RETURN count(c) AS n",
            graph_repo_id,
        ) == 0
        assert await _count(
            neo,
            "MATCH ()-[r:IN_CHUNK|IN_COMMUNITY]->() WHERE r.repo_id = $repo_id RETURN count(r) AS n",
            graph_repo_id,
        ) == 0
        file_chains = await neo.execute_cypher(
            """
            MATCH (d:Document {repo_id: $repo_id})<-[:FROM_DOCUMENT]-(c:Chunk)
            WITH d, count(c) AS chunks
            RETURN max(chunks) AS max_chunks, sum(chunks) AS total_chunks, count(d) AS documents
            """,
            {"repo_id": graph_repo_id},
        )
        chain = file_chains[0]
        assert int(chain["max_chunks"]) > cfg.indexing.indexing_batch_size, (
            "fixture must cross a complete vector batch so NEXT_CHUNK proves file-level graph assembly"
        )
        next_edges = await _count(
            neo,
            "MATCH (:Chunk {repo_id: $repo_id})-[r:NEXT_CHUNK]->(:Chunk {repo_id: $repo_id}) RETURN count(r) AS n",
            graph_repo_id,
        )
        assert next_edges == int(chain["total_chunks"]) - int(chain["documents"])
    finally:
        config_store._store = None
        if neo is not None:
            await neo.disconnect()
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()
