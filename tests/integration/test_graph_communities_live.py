"""Graph communities and the whole-corpus subgraph against a live Neo4j.

Regressions for the 2026-08-25 drive findings G1 (communities were a
"top-level directory" heuristic whose single "(root)" bucket carried the STAGING
corpus id after promotion) and G2 (the whole-corpus view had no relationships to
draw). Real Neo4j, real Postgres corpus row, no mocks.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from httpx import AsyncClient
from neo4j import GraphDatabase
from neo4j_graphrag.components.types import (
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
)

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.graph.communities import detect_leiden_communities
from server.indexing.generations import build_generation
from server.indexing.graphrag_pipeline import ScopedNeo4jWriter
from server.indexing.official_graphrag import write_lexical_graph_with_graphrag
from server.models.index import Chunk
from tests.service_requirements import require_env

pytestmark = [pytest.mark.requires_postgres, pytest.mark.requires_neo4j, pytest.mark.asyncio]

_CORPUS_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "acceptance_corpus")


def _entity(entity_id: str, name: str, entity_type: str, label: str) -> Neo4jNode:
    return Neo4jNode(
        id=entity_id,
        label=label,
        properties={
            "entity_id": entity_id,
            "name": name,
            "entity_type": entity_type,
            "description": f"{name} ({entity_type})",
            "file_path": "observatory-overview.md",
        },
    )


def _rel(
    a: str,
    b: str,
    *,
    weight: float = 1.0,
    relationship_type: str = "associated_with",
) -> Neo4jRelationship:
    return Neo4jRelationship(
        start_node_id=a,
        end_node_id=b,
        type=relationship_type,
        properties={"weight": weight},
    )


async def _write_graph(
    repo_id: str,
    run_id: str,
    graph: Neo4jGraph,
    lexical: LexicalGraphConfig,
) -> None:
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "password"),
        ),
    )
    try:
        writer = await asyncio.to_thread(
            ScopedNeo4jWriter,
            driver=driver,
            repo_id=repo_id,
            run_id=run_id,
        )
        await writer.run(graph, lexical)
    finally:
        await asyncio.to_thread(driver.close)


async def test_gds_leiden_communities_are_scoped_stable_and_feed_the_subgraph(client: AsyncClient) -> None:
    active = f"graph-comm-{uuid4().hex[:8]}"
    run_id = uuid4().hex
    staging = f"__staging__{active}__{run_id}"
    foreign = f"__staging__foreign-{uuid4().hex[:8]}__{uuid4().hex}"
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    created = await client.post(
        "/api/corpora", json={"corpus_id": active, "name": active, "path": os.path.abspath(_CORPUS_PATH)}
    )
    assert created.status_code in (200, 201), created.text
    await neo.connect()
    try:
        chunk = Chunk(
            chunk_id="obs-1",
            content="Aurora Tidal Observatory overview",
            file_path="observatory-overview.md",
            start_line=1,
            end_line=15,
            token_count=5,
            embedding=[0.1, 0.2],
        )
        lexical, lexical_cfg = await write_lexical_graph_with_graphrag(
            repo_id=staging, run_id=run_id, file_path="observatory-overview.md", chunks=[chunk]
        )
        await _write_graph(staging, run_id, lexical, lexical_cfg)

        # Two weighted cliques joined by one weak bridge.
        entities = Neo4jGraph(
            nodes=[
                _entity("a1", "Aurora Tidal Observatory", "org", "Org"),
                _entity("a2", "Dr. Mireille Okafor", "person", "Person"),
                _entity("a3", "Tidal calibration campaign", "event", "Event"),
                _entity("b1", "KestrelDB", "concept", "Concept"),
                _entity("b2", "Pelican gateway", "concept", "Concept"),
                _entity("b3", "Sensor ingest pipeline", "concept", "Concept"),
            ],
            relationships=[
                _rel("a1", "a2", weight=5.0),
                _rel("a2", "a3", weight=5.0),
                _rel("a1", "a3", weight=5.0),
                _rel("b1", "b2", weight=5.0),
                _rel("b2", "b3", weight=5.0),
                _rel("b1", "b3", weight=5.0),
                _rel("a3", "b1", weight=0.01),
            ],
        )
        await _write_graph(staging, run_id, entities, lexical_cfg)
        compatibility_driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            await asyncio.to_thread(
                compatibility_driver.execute_query,
                "MATCH (:__Entity__ {repo_id: $repo_id, entity_id: 'a1'})"
                "-[r:associated_with]->"
                "(:__Entity__ {repo_id: $repo_id, entity_id: 'a2'}) REMOVE r.repo_id",
                parameters_={"repo_id": staging},
                database_="neo4j",
            )
        finally:
            await asyncio.to_thread(compatibility_driver.close)
        await _write_graph(
            foreign,
            run_id,
            Neo4jGraph(
                nodes=[_entity("foreign-1", "Untouched entity", "concept", "Concept")],
                relationships=[],
            ),
            lexical_cfg,
        )
        foreign_driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            await asyncio.to_thread(
                foreign_driver.execute_query,
                "MATCH (e:__Entity__ {repo_id: $repo_id}) "
                "SET e.communityPath = ['untouched'], e.communityId = 'untouched'",
                parameters_={"repo_id": foreign},
                database_="neo4j",
            )
        finally:
            await asyncio.to_thread(foreign_driver.close)

        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            first_telemetry = await detect_leiden_communities(
                driver=driver, neo4j_database="neo4j", repo_id=staging
            )
            first_properties = await neo.execute_cypher(
                """
                MATCH (e:__Entity__ {repo_id: $repo_id})
                RETURN e.entity_id AS entity_id,
                       e.communityPath AS communityPath,
                       e.communityId AS communityId
                ORDER BY entity_id
                """,
                {"repo_id": staging},
            )
            second_telemetry = await detect_leiden_communities(
                driver=driver, neo4j_database="neo4j", repo_id=staging
            )
            second_properties = await neo.execute_cypher(
                """
                MATCH (e:__Entity__ {repo_id: $repo_id})
                RETURN e.entity_id AS entity_id,
                       e.communityPath AS communityPath,
                       e.communityId AS communityId
                ORDER BY entity_id
                """,
                {"repo_id": staging},
            )
            projections, _, _ = await asyncio.to_thread(
                driver.execute_query,
                "CALL gds.graph.list() YIELD graphName "
                "WHERE graphName STARTS WITH 'ragweld_' RETURN graphName",
                database_="neo4j",
            )
        finally:
            await asyncio.to_thread(driver.close)
        assert first_telemetry == second_telemetry
        assert first_telemetry.community_count == 2
        assert first_telemetry.nodes_written == 6
        assert first_telemetry.did_converge is True
        assert first_properties == second_properties
        assert all(row["communityPath"] for row in first_properties)
        assert all(row["communityId"] == row["communityPath"][-1] for row in first_properties)
        assert projections == []
        assert await neo.execute_cypher(
            "MATCH (e:__Entity__ {repo_id: $repo_id}) "
            "RETURN e.communityPath AS path, e.communityId AS id",
            {"repo_id": foreign},
        ) == [{"path": ["untouched"], "id": "untouched"}]

        # Force a real database failure after projection and Leiden have succeeded:
        # members of one community cannot share communityId while this temporary
        # uniqueness constraint exists. The named in-memory projection must still
        # be removed, and a clean retry must restore the derived scalar property.
        constraint_name = f"task7_community_id_unique_{uuid4().hex}"
        failure_label = f"Task7CommunityFailure{uuid4().hex}"
        failure_driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            await asyncio.to_thread(
                failure_driver.execute_query,
                f"MATCH (e:__Entity__ {{repo_id: $repo_id}}) "
                f"REMOVE e.communityId SET e:{failure_label}",
                parameters_={"repo_id": staging},
                database_="neo4j",
            )
            await asyncio.to_thread(
                failure_driver.execute_query,
                f"CREATE CONSTRAINT {constraint_name} IF NOT EXISTS "
                f"FOR (e:{failure_label}) REQUIRE e.communityId IS UNIQUE",
                database_="neo4j",
            )
            with pytest.raises(Exception, match="Constraint|constraint|unique"):
                await detect_leiden_communities(
                    driver=failure_driver, neo4j_database="neo4j", repo_id=staging
                )
            failure_projections, _, _ = await asyncio.to_thread(
                failure_driver.execute_query,
                "CALL gds.graph.list() YIELD graphName "
                "WHERE graphName STARTS WITH 'ragweld_' RETURN graphName",
                database_="neo4j",
            )
            assert failure_projections == []
        finally:
            await asyncio.to_thread(
                failure_driver.execute_query,
                f"DROP CONSTRAINT {constraint_name} IF EXISTS",
                database_="neo4j",
            )
            await asyncio.to_thread(
                failure_driver.execute_query,
                f"MATCH (e:{failure_label} {{repo_id: $repo_id}}) REMOVE e:{failure_label}",
                parameters_={"repo_id": staging},
                database_="neo4j",
            )
            await asyncio.to_thread(failure_driver.close)

        retry_driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            assert (
                await detect_leiden_communities(
                    driver=retry_driver, neo4j_database="neo4j", repo_id=staging
                )
            ).nodes_written == 6
        finally:
            await asyncio.to_thread(retry_driver.close)

        legacy = await neo.execute_cypher(
            """
            MATCH (node {repo_id: $repo_id})
            OPTIONAL MATCH (node)-[relationship]->()
            RETURN count(DISTINCT CASE WHEN node:Community THEN node END) AS nodes,
                   count(DISTINCT CASE WHEN type(relationship) = 'IN_COMMUNITY' THEN relationship END) AS relationships
            """,
            {"repo_id": staging},
        )
        assert legacy == [{"nodes": 0, "relationships": 0}]

        detected = await neo.get_communities(staging, None)
        assert len(detected) == 2, [c.model_dump() for c in detected]
        member_sets = sorted(sorted(c.member_ids) for c in detected)
        assert member_sets == [["a1", "a2", "a3"], ["b1", "b2", "b3"]]
        for community in detected:
            assert staging not in community.community_id and active not in community.community_id
            assert community.name in {"Tidal calibration campaign", "KestrelDB"}, community.name  # the bridge endpoints are the hubs
            assert "related entities around" in community.summary

        # Promotion is the manifest write on the corpus row (no relabel); the API
        # resolves the graph generation id from it and community ids stay valid.
        pg = PostgresClient(require_env("POSTGRES_DSN"))
        await pg.connect()
        try:
            await pg.set_generation(
                active, build_generation(run_id=run_id, qdrant_collection=None, graph_repo_id=staging)
            )
        finally:
            await pg.disconnect()
        listed = await client.get(f"/api/graph/{active}/communities")
        assert listed.status_code == 200, listed.text
        promoted = listed.json()
        assert {c["community_id"] for c in promoted} == {c.community_id for c in detected}
        assert sorted(sorted(c["member_ids"]) for c in promoted) == member_sets

        members = await client.get(f"/api/graph/{active}/community/{detected[0].community_id}/members")
        assert members.status_code == 200 and len(members.json()) == 3, members.text

        # The community subgraph carries the same pre-limit contract; it used to leave
        # total_matched at the model default of 0 (review F-03).
        for cap, expected_shown in ((50, 3), (1, 1)):
            community_sub = await client.get(
                f"/api/graph/{active}/community/{detected[0].community_id}/subgraph",
                params={"limit": cap},
            )
            assert community_sub.status_code == 200, community_sub.text
            body = community_sub.json()
            assert len(body["entities"]) == expected_shown
            assert body["limit"] == cap
            assert body["total_matched"] == 3, (
                f"community total_matched must be the pre-limit member count, got "
                f"{body['total_matched']} at limit={cap}"
            )

        # The whole-corpus view gets entities AND the edges between them.
        subgraph = await client.get(f"/api/graph/{active}/subgraph", params={"limit": 50})
        assert subgraph.status_code == 200, subgraph.text
        payload = subgraph.json()
        assert {e["entity_id"] for e in payload["entities"]} == {"a1", "a2", "a3", "b1", "b2", "b3"}
        edges = {tuple(sorted((r["source_id"], r["target_id"]))) for r in payload["relationships"]}
        assert edges == {("a1", "a2"), ("a2", "a3"), ("a1", "a3"), ("b1", "b2"), ("b2", "b3"), ("b1", "b3"), ("a3", "b1")}
        assert all(r["relation_type"] == "associated_with" for r in payload["relationships"])
        # A capped view keeps the best-connected entities: a3 and b1 (degree 3)
        # come first, then the degree-2 entities by name ("Aurora Tidal Observatory").
        capped = await client.get(f"/api/graph/{active}/subgraph", params={"limit": 3})
        assert capped.status_code == 200
        assert {e["entity_id"] for e in capped.json()["entities"]} == {"a3", "b1", "a1"}
        assert {tuple(sorted((r["source_id"], r["target_id"]))) for r in capped.json()["relationships"]} == {("a1", "a3"), ("a3", "b1")}
    finally:
        for repo_id in (active, staging, foreign):
            try:
                await neo.delete_graph(repo_id)
            except Exception:
                pass
        await neo.disconnect()
        await client.delete(f"/api/corpora/{active}")


def _code_entity(entity_id: str, name: str, entity_type: str) -> Neo4jNode:
    """A code-graph entity: its id is a corpus-relative source path with `/` and `::`."""
    return Neo4jNode(
        id=entity_id,
        label="Concept",
        properties={
            "entity_id": entity_id,
            "name": name,
            "entity_type": entity_type,
            "description": f"{name} ({entity_type})",
            "file_path": entity_id.split("::", 1)[0],
        },
    )


async def test_code_entity_ids_round_trip_and_a_search_carries_its_own_edges(
    client: AsyncClient,
) -> None:
    """M-01, M-61, M-62 against a live Neo4j.

    M-01: every entity route must accept an id containing `/` and `::` (every code
    entity has both) and return the real neighborhood, not 404.
    M-62: a search must return the relationships that run BETWEEN its results, or the
    visualizer draws unconnected dots ("101 nodes - 1 edges" on `ragweld_code`).
    M-61: the response must carry the total match count so the UI can print a
    denominator instead of an undenominated "200 shown".
    """
    active = f"graph-code-{uuid4().hex[:8]}"
    run_id = uuid4().hex
    staging = f"__staging__{active}__{run_id}"
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    created = await client.post(
        "/api/corpora", json={"corpus_id": active, "name": active, "path": os.path.abspath(_CORPUS_PATH)}
    )
    assert created.status_code in (200, 201), created.text

    reranker = "server/retrieval/rerank.py::Reranker"
    rerank_init = "server/retrieval/rerank.py::Reranker.__init__"
    mlx_reranker = "server/retrieval/mlx_qwen3.py::MLXQwen3Reranker"
    module = "server/retrieval/rerank.py"
    unrelated = "server/api/graph.py::list_entities"

    await neo.connect()
    try:
        chunk = Chunk(
            chunk_id="code-1",
            content="class Reranker: ...",
            file_path="server/retrieval/rerank.py",
            start_line=108,
            end_line=523,
            token_count=5,
            embedding=[0.1, 0.2],
        )
        _lexical, lexical_cfg = await write_lexical_graph_with_graphrag(
            repo_id=staging,
            run_id=run_id,
            file_path="server/retrieval/rerank.py",
            chunks=[chunk],
        )
        graph = Neo4jGraph(
            nodes=[
                _code_entity(reranker, "Reranker", "class"),
                _code_entity(rerank_init, "Reranker.__init__", "function"),
                _code_entity(mlx_reranker, "MLXQwen3Reranker", "class"),
                _code_entity(module, "rerank.py", "module"),
                _code_entity(unrelated, "list_entities", "function"),
            ],
            relationships=[
                _rel(module, reranker, relationship_type="contains"),
                _rel(reranker, rerank_init, relationship_type="contains"),
                # MLXQwen3Reranker matches "reranker" too but links only OUTSIDE the
                # result set, so the induced-edge query must not invent an edge for it.
                _rel(mlx_reranker, unrelated, relationship_type="imports"),
            ],
        )
        await _write_graph(staging, run_id, graph, lexical_cfg)

        driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
            auth=(
                os.environ.get("NEO4J_USER", "neo4j"),
                os.environ.get("NEO4J_PASSWORD", "password"),
            ),
        )
        try:
            code_telemetry = await detect_leiden_communities(
                driver=driver, neo4j_database="neo4j", repo_id=staging
            )
        finally:
            await asyncio.to_thread(driver.close)
        assert code_telemetry.community_count == 2
        assert code_telemetry.nodes_written == 5

        pg = PostgresClient(require_env("POSTGRES_DSN"))
        await pg.connect()
        try:
            await pg.set_generation(
                active, build_generation(run_id=run_id, qdrant_collection=None, graph_repo_id=staging)
            )
        finally:
            await pg.disconnect()

        # M-01: the id travels as a query parameter and every entity route resolves.
        entity = await client.get(f"/api/graph/{active}/entity", params={"entity_id": reranker})
        assert entity.status_code == 200, entity.text
        assert entity.json()["entity_id"] == reranker

        neighbors = await client.get(
            f"/api/graph/{active}/entity/neighbors",
            params={"entity_id": reranker, "max_hops": 2, "limit": 200},
        )
        assert neighbors.status_code == 200, neighbors.text
        neighborhood = neighbors.json()
        # The center plus both hops - a 200 carrying only the center would mean the
        # neighborhood query itself is broken.
        assert {e["entity_id"] for e in neighborhood["entities"]} == {reranker, rerank_init, module}
        assert len(neighborhood["relationships"]) == 2

        rels = await client.get(
            f"/api/graph/{active}/entity/relationships", params={"entity_id": module}
        )
        assert rels.status_code == 200, rels.text
        assert [r["target_id"] for r in rels.json()] == [reranker]

        # An id that is not in the graph is a 404 that names the id, not a silent empty.
        missing = await client.get(
            f"/api/graph/{active}/entity/neighbors", params={"entity_id": "server/does/not.py::Exist"}
        )
        assert missing.status_code == 404, missing.text
        assert "server/does/not.py::Exist" in missing.json()["detail"]

        # M-62: a search returns the edges between its own results, and only those.
        found = await client.get(f"/api/graph/{active}/subgraph", params={"q": "reranker", "limit": 200})
        assert found.status_code == 200, found.text
        payload = found.json()
        assert {e["entity_id"] for e in payload["entities"]} == {reranker, rerank_init, mlx_reranker}
        assert {tuple(sorted((r["source_id"], r["target_id"]))) for r in payload["relationships"]} == {
            tuple(sorted((reranker, rerank_init)))
        }
        # M-61: the denominator is the match count, independent of the display limit.
        assert payload["total_matched"] == 3
        assert payload["limit"] == 200

        capped = await client.get(f"/api/graph/{active}/subgraph", params={"q": "reranker", "limit": 1})
        assert capped.status_code == 200, capped.text
        assert len(capped.json()["entities"]) == 1
        assert capped.json()["total_matched"] == 3, "the total must not shrink with the display limit"

        whole = await client.get(f"/api/graph/{active}/subgraph", params={"limit": 200})
        assert whole.status_code == 200, whole.text
        assert whole.json()["total_matched"] == 5

        # `total_matched` means "before limit" on EVERY producer, not only /subgraph.
        # get_entity_neighbors used to report len(entities), which equals `limit` as soon
        # as a neighborhood is truncated - a 500-neighbour entity said "200 of 200"
        # (review F-03). `module` reaches Reranker (1 hop) and Reranker.__init__ (2 hops),
        # so with the centre the pre-limit total is 3 however small the display cap is.
        for cap, expected_shown in ((200, 3), (1, 1)):
            capped = await client.get(
                f"/api/graph/{active}/entity/neighbors",
                params={"entity_id": module, "max_hops": 2, "limit": cap},
            )
            assert capped.status_code == 200, capped.text
            body = capped.json()
            assert len(body["entities"]) == expected_shown
            assert body["limit"] == cap
            assert body["total_matched"] == 3, (
                f"total_matched must be the pre-limit neighbour count, got {body['total_matched']} "
                f"at limit={cap}"
            )

        # The entity list and the search subgraph must select the SAME entities, or the
        # list would show rows the visualizer never draws.
        listed = await client.get(f"/api/graph/{active}/entities", params={"q": "reranker", "limit": 200})
        assert listed.status_code == 200, listed.text
        assert {e["entity_id"] for e in listed.json()} == {e["entity_id"] for e in payload["entities"]}
    finally:
        for repo_id in (active, staging):
            try:
                await neo.delete_graph(repo_id)
            except Exception:
                pass
        await neo.disconnect()
        await client.delete(f"/api/corpora/{active}")


async def test_neighbors_never_return_the_centre_twice_on_a_cyclic_graph(
    client: AsyncClient,
) -> None:
    """Review N-02: above 2 hops a path can return to the centre and bind it as its own
    neighbour. The entity list then carried a duplicate row (a duplicate React key in the
    entities table, two nodes sharing one nodeId in the visualizer) and the pre-limit count
    added a second unit for it. The two errors cancelled in the total, so only a uniqueness
    assertion catches it - a count assertion would have passed throughout.

    The graph is a triangle so that a 3-hop walk from any node reaches that node again;
    max hops is operator-settable 1-5, so this is reachable from the UI.
    """
    active = f"graph-cycle-{uuid4().hex[:8]}"
    run_id = uuid4().hex
    staging = f"__staging__{active}__{run_id}"
    neo = Neo4jClient(
        os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687"),
        os.environ.get("NEO4J_USER", "neo4j"),
        os.environ.get("NEO4J_PASSWORD", "password"),
    )
    created = await client.post(
        "/api/corpora", json={"corpus_id": active, "name": active, "path": os.path.abspath(_CORPUS_PATH)}
    )
    assert created.status_code in (200, 201), created.text

    a, b, c = "pkg/a.py::A", "pkg/b.py::B", "pkg/c.py::C"
    await neo.connect()
    try:
        chunk = Chunk(
            chunk_id="cycle-1",
            content="class A: ...",
            file_path="pkg/a.py",
            start_line=1,
            end_line=3,
            token_count=4,
            embedding=[0.3, 0.4],
        )
        _lexical, lexical_cfg = await write_lexical_graph_with_graphrag(
            repo_id=staging, run_id=run_id, file_path="pkg/a.py", chunks=[chunk]
        )
        await _write_graph(
            staging,
            run_id,
            Neo4jGraph(
                nodes=[
                    _code_entity(a, "A", "class"),
                    _code_entity(b, "B", "class"),
                    _code_entity(c, "C", "class"),
                ],
                relationships=[_rel(a, b), _rel(b, c), _rel(c, a)],
            ),
            lexical_cfg,
        )

        pg = PostgresClient(require_env("POSTGRES_DSN"))
        await pg.connect()
        try:
            await pg.set_generation(
                active, build_generation(run_id=run_id, qdrant_collection=None, graph_repo_id=staging)
            )
        finally:
            await pg.disconnect()

        for hops in (1, 2, 3, 4, 5):
            response = await client.get(
                f"/api/graph/{active}/entity/neighbors",
                params={"entity_id": a, "max_hops": hops, "limit": 200},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            ids = [e["entity_id"] for e in body["entities"]]
            assert len(ids) == len(set(ids)), f"duplicate entity rows at hops={hops}: {ids}"
            assert a in ids, f"the centre must always be returned (hops={hops})"
            # Every node of the triangle is within one hop of A in an undirected walk,
            # so the answer is the whole graph at every hop count - and exactly once.
            assert set(ids) == {a, b, c}, f"hops={hops} returned {ids}"
            assert body["total_matched"] == 3, (
                f"total_matched must count the centre once, got {body['total_matched']} at hops={hops}"
            )
    finally:
        for repo_id in (active, staging):
            try:
                await neo.delete_graph(repo_id)
            except Exception:
                pass
        await neo.disconnect()
        await client.delete(f"/api/corpora/{active}")
