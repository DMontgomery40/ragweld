from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from neo4j import GraphDatabase
from neo4j_graphrag.components.schema import (
    GraphSchema,
    NodeType,
    Pattern,
    PropertyType,
    RelationshipType,
)

from server.api.index import graph_schema_input_fingerprint
from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import GenerationManifest, build_generation
from server.indexing.graph_invariants import GraphPromotionRefusedError, verify_graph_promotion
from server.models.index import (
    GraphExtractionTelemetry,
    GraphSchemaProposal,
    GraphSchemaSample,
)
from server.services import config_store
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_neo4j, pytest.mark.asyncio]


def _extraction(case: str) -> GraphExtractionTelemetry:
    values = {
        "selected_chunks": 2,
        "attempted_chunks": 2,
        "succeeded_chunks": 2,
        "failed_chunks": 0,
        "truncated_chunks": 0,
        "extracted_entities": 2,
        "semantic_relationships": 1,
        "from_chunk_relationships": 2,
    }
    if case == "extraction_failure":
        values.update(failed_chunks=1, succeeded_chunks=1)
    elif case == "silent_truncation":
        values.update(attempted_chunks=1, succeeded_chunks=1, truncated_chunks=1)
    return GraphExtractionTelemetry(**values)


async def _write(driver, database: str, query: str, parameters: dict) -> None:
    await asyncio.to_thread(
        driver.execute_query,
        query,
        parameters_=parameters,
        database_=database,
    )


async def _seed_valid_graph(driver, database: str, repo_id: str, run_id: str) -> None:
    await _write(
        driver,
        database,
        """
        CREATE (d:Document {repo_id: $repo_id, run_id: $run_id, file_path: 'facts.md'})
        CREATE (c1:Chunk {repo_id: $repo_id, run_id: $run_id, chunk_id: 'c1'})
        CREATE (c2:Chunk {repo_id: $repo_id, run_id: $run_id, chunk_id: 'c2'})
        CREATE (a:__Entity__:Person {
            repo_id: $repo_id, run_id: $run_id, entity_id: 'ada', name: 'Ada'
        })
        CREATE (b:__Entity__:Organization {
            repo_id: $repo_id, run_id: $run_id, entity_id: 'engines', name: 'Analytical Engines'
        })
        CREATE (c1)-[:FROM_DOCUMENT {repo_id: $repo_id, run_id: $run_id}]->(d)
        CREATE (c2)-[:FROM_DOCUMENT {repo_id: $repo_id, run_id: $run_id}]->(d)
        CREATE (c1)-[:NEXT_CHUNK {repo_id: $repo_id, run_id: $run_id}]->(c2)
        CREATE (a)-[:FROM_CHUNK {repo_id: $repo_id, run_id: $run_id}]->(c1)
        CREATE (b)-[:FROM_CHUNK {repo_id: $repo_id, run_id: $run_id}]->(c2)
        CREATE (a)-[:CREATED {repo_id: $repo_id, run_id: $run_id}]->(b)
        """,
        {"repo_id": repo_id, "run_id": run_id},
    )


async def _mutate(driver, database: str, case: str, repo_id: str, run_id: str) -> None:
    if case == "zero_entities":
        await _write(
            driver,
            database,
            "MATCH (n:__Entity__ {repo_id: $repo_id}) DETACH DELETE n",
            {"repo_id": repo_id},
        )
    elif case == "zero_semantic_relationships":
        await _write(
            driver,
            database,
            "MATCH (:__Entity__ {repo_id: $repo_id})-[r:CREATED]->(:__Entity__) DELETE r",
            {"repo_id": repo_id},
        )
    elif case == "missing_from_chunk_provenance":
        await _write(
            driver,
            database,
            "MATCH (:__Entity__ {repo_id: $repo_id})-[r:FROM_CHUNK]->(:Chunk) DELETE r",
            {"repo_id": repo_id},
        )
    elif case == "cross_generation_node":
        await _write(
            driver,
            database,
            "MATCH (n:__Entity__:Person {repo_id: $repo_id}) SET n.repo_id = 'foreign-generation'",
            {"repo_id": repo_id},
        )
    elif case == "cross_generation_relationship":
        await _write(
            driver,
            database,
            "MATCH (:__Entity__ {repo_id: $repo_id})-[r:CREATED]->(:__Entity__) SET r.repo_id = 'foreign-generation'",
            {"repo_id": repo_id},
        )
    elif case == "unresolved_duplicate_entity":
        await _write(
            driver,
            database,
            """
            CREATE (:__Entity__:Person {
                repo_id: $repo_id, run_id: $run_id,
                entity_id: 'ada-duplicate', name: 'Ada'
            })
            """,
            {"repo_id": repo_id, "run_id": run_id},
        )


@pytest.mark.parametrize(
    "case",
    [
        "extraction_failure",
        "silent_truncation",
        "zero_entities",
        "zero_semantic_relationships",
        "missing_from_chunk_provenance",
        "cross_generation_node",
        "cross_generation_relationship",
        "unresolved_duplicate_entity",
    ],
)
async def test_each_invalid_staged_graph_is_typed_and_cannot_replace_active_manifest(
    case: str,
) -> None:
    active_id = f"promotion-active-{uuid4().hex[:8]}"
    active_run = uuid4().hex
    staged_run = uuid4().hex
    staged_id = f"__staging__{active_id}__{staged_run}"
    cfg = load_config()
    database = cfg.graph_storage.resolve_database(active_id)
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        auth=(
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        ),
    )
    previous = build_generation(
        run_id=active_run,
        qdrant_collection=f"active_{active_run}",
        graph_repo_id=f"active-graph-{active_run}",
        now=datetime.now(UTC),
    )
    await pg.connect()
    await neo.connect()
    try:
        await pg.upsert_corpus(
            active_id,
            active_id,
            "/tmp",
            meta={"generation": previous.model_dump(mode="json")},
        )
        await _seed_valid_graph(driver, database, staged_id, staged_run)
        await _mutate(driver, database, case, staged_id, staged_run)

        with pytest.raises(GraphPromotionRefusedError) as raised:
            await verify_graph_promotion(
                neo4j=neo,
                repo_id=staged_id,
                policy="semantic",
                expected_chunks=2,
                extraction=_extraction(case),
                schema_hash="a" * 64,
            )

        assert case in raised.value.report.failure_codes
        active = await pg.get_corpus(active_id)
        manifest = GenerationManifest.model_validate((active or {})["meta"]["generation"])
        assert manifest.run_id == active_run
        assert manifest.graph_repo_id == previous.graph_repo_id
    finally:
        await _write(
            driver,
            database,
            "MATCH (n) WHERE n.run_id = $run_id DETACH DELETE n",
            {"run_id": staged_run},
        )
        await neo.disconnect()
        await asyncio.to_thread(driver.close)
        await pg.delete_corpus(active_id)
        await pg.disconnect()


async def _wait_for_terminal(client: AsyncClient, corpus_id: str) -> dict:
    for _ in range(600):
        response = await client.get(f"/api/index/{corpus_id}/status")
        assert response.status_code == 200, response.text
        payload = response.json()
        if payload["status"] in {"complete", "error", "cancelled"}:
            return payload
        await asyncio.sleep(0.25)
    raise AssertionError("index run did not reach a terminal state")


async def test_real_empty_semantic_run_is_refused_then_authenticated_chunk_only_override_is_audited(
    client: AsyncClient,
    tmp_path: Path,
) -> None:
    corpus_id = f"promotion-refusal-{uuid4().hex[:8]}"
    corpus_root = tmp_path / "entity-sparse"
    corpus_root.mkdir()
    (corpus_root / "measurements.txt").write_text(
        ("0000 1111 2222 3333 4444 5555.\n" * 20),
        encoding="utf-8",
    )
    created = await client.post(
        "/api/corpora",
        json={"corpus_id": corpus_id, "name": corpus_id, "path": str(corpus_root)},
    )
    assert created.status_code in (200, 201), created.text
    pg = PostgresClient(require_env("POSTGRES_DSN"))
    await pg.connect()
    try:
        cfg = load_config()
        cfg.embedding.embedding_backend = "deterministic"
        cfg.chunking.chunking_strategy = "fixed_chars"
        cfg.chunking.chunk_size = 1000
        cfg.chunking.chunk_overlap = 0
        cfg.indexing.figures.enabled = False
        cfg.graph_indexing.enabled = True
        cfg.graph_indexing.build_code_graph = False
        cfg.graph_indexing.semantic_kg_llm_model = os.environ.get(
            "GRAPH_E2E_KG_MODEL", "deepseek.deepseek-v4-flash"
        )
        cfg.chat.litellm.enabled = True
        await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump(mode="serialization"))
        previous_run = uuid4().hex
        previous = build_generation(
            run_id=previous_run,
            qdrant_collection=None,
            graph_repo_id=None,
            now=datetime.now(UTC),
        )
        await pg.patch_corpus_meta_locked(
            corpus_id,
            {"generation": previous.model_dump(mode="json")},
        )
        config_store._store = None
        corpus = await pg.get_corpus(corpus_id)
        fingerprint = await graph_schema_input_fingerprint(corpus or {}, cfg)
        named = [PropertyType(name="name", type="STRING")]
        schema = GraphSchema(
            node_types=[
                NodeType(label="Person", description="A named person", properties=named),
                NodeType(
                    label="Organization",
                    description="A named organization",
                    properties=named,
                ),
            ],
            relationship_types=[
                RelationshipType(label="WORKS_FOR", description="Employment")
            ],
            patterns=[
                Pattern(source="Person", relationship="WORKS_FOR", target="Organization")
            ],
            additional_node_types=False,
            additional_relationship_types=False,
            additional_patterns=False,
        )
        schema_payload = schema.model_dump(mode="json")
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
                sample=GraphSchemaSample(seed=0, chunk_ids=[], chunk_hashes=[]),
                model_alias=cfg.graph_indexing.semantic_kg_llm_model,
                created_at=datetime.now(UTC),
            ),
        )

        anonymous_override = await client.post(
            "/api/index",
            json={
                "corpus_id": corpus_id,
                "repo_path": str(corpus_root),
                "force_reindex": True,
                "approved_graph_schema_hash": schema_hash,
                "graph_empty_override_reason": (
                    "The reviewed measurements corpus is intentionally entity sparse."
                ),
            },
        )
        assert anonymous_override.status_code == 403, anonymous_override.text

        started = await client.post(
            "/api/index",
            json={
                "corpus_id": corpus_id,
                "repo_path": str(corpus_root),
                "force_reindex": True,
                "approved_graph_schema_hash": schema_hash,
            },
        )
        assert started.status_code == 200, started.text
        final = await _wait_for_terminal(client, corpus_id)
        assert final["status"] == "error", final
        assert "Graph promotion refused" in str(final["error"])

        latest = await client.get(f"/api/index/{corpus_id}/runs/latest")
        assert latest.status_code == 200, latest.text
        replay = latest.json()
        assert replay["graph_promotable"] is False
        assert replay["graph_failure_codes"] == [
            "zero_entities",
            "zero_semantic_relationships",
        ]
        assert replay["graph_metadata"]["extraction"]["failed_chunks"] == 0
        assert replay["graph_metadata"]["extraction"]["attempted_chunks"] == 1

        active = await pg.get_corpus(corpus_id)
        manifest = GenerationManifest.model_validate((active or {})["meta"]["generation"])
        assert manifest.run_id == previous_run
        assert manifest.graph_repo_id is None

        reason = "The reviewed measurements corpus is intentionally entity sparse."
        restarted = await client.post(
            "/api/index",
            headers={"Remote-User": "operator@example.test"},
            json={
                "corpus_id": corpus_id,
                "repo_path": str(corpus_root),
                "force_reindex": True,
                "approved_graph_schema_hash": schema_hash,
                "graph_empty_override_reason": reason,
            },
        )
        assert restarted.status_code == 200, restarted.text
        overridden = await _wait_for_terminal(client, corpus_id)
        assert overridden["status"] == "complete", overridden

        active = await pg.get_corpus(corpus_id)
        manifest = GenerationManifest.model_validate((active or {})["meta"]["generation"])
        assert manifest.run_id != previous_run
        assert manifest.graph_repo_id is None
        assert manifest.graph_metadata is not None
        assert manifest.graph_metadata.partial is True
        assert manifest.graph_metadata.override is not None
        assert manifest.graph_metadata.override.actor == "operator@example.test"
        assert manifest.graph_metadata.override.reason == reason
        assert manifest.graph_metadata.override.failure_codes == [
            "zero_entities",
            "zero_semantic_relationships",
        ]
    finally:
        config_store._store = None
        await client.delete(f"/api/index/{corpus_id}")
        await client.delete(f"/api/corpora/{corpus_id}")
        await pg.disconnect()


async def test_code_policy_keeps_same_name_entities_with_distinct_ids_promotable() -> None:
    """Task 8 drive defect D14: once code resolution keyed on ``entity_id`` (D7), the promotion
    invariant still grouped duplicates by ``name``, so every code graph with two ``__init__``
    methods was refused (live run ``c58050a6``: 6,237 entities, resolver duplicates 0, invariant
    ``unresolved_duplicate_entity``). The invariant must count duplicates on the policy's
    resolution property: ``entity_id`` for code, ``name`` for semantic.
    """
    active_id = f"promotion-code-{uuid4().hex[:8]}"
    staged_run = uuid4().hex
    staged_id = f"__staging__{active_id}__{staged_run}"
    cfg = load_config()
    database = cfg.graph_storage.resolve_database(active_id)
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
        os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        database=database,
    )
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", cfg.graph_storage.neo4j_uri),
        auth=(
            os.environ.get("NEO4J_USER", cfg.graph_storage.neo4j_user),
            os.environ.get("NEO4J_PASSWORD", cfg.graph_storage.resolve_password()),
        ),
    )
    await neo.connect()
    try:
        await _seed_valid_graph(driver, database, staged_id, staged_run)
        await _mutate(driver, database, "unresolved_duplicate_entity", staged_id, staged_run)

        report = await verify_graph_promotion(
            neo4j=neo,
            repo_id=staged_id,
            policy="code",
            expected_chunks=2,
            extraction=_extraction("valid"),
            schema_hash=None,
        )
        assert report.promotable
        assert report.failure_codes == ()
        assert report.total_entities == 3
        assert report.duplicate_groups == 0

        with pytest.raises(GraphPromotionRefusedError) as raised:
            await verify_graph_promotion(
                neo4j=neo,
                repo_id=staged_id,
                policy="semantic",
                expected_chunks=2,
                extraction=_extraction("valid"),
                schema_hash="a" * 64,
            )
        assert raised.value.report.failure_codes == ("unresolved_duplicate_entity",)
        assert raised.value.report.duplicate_groups == 1
    finally:
        await _write(
            driver,
            database,
            "MATCH (n) WHERE n.run_id = $run_id DETACH DELETE n",
            {"run_id": staged_run},
        )
        await neo.disconnect()
        await asyncio.to_thread(driver.close)
