"""Graph communities and the whole-corpus subgraph against a live Neo4j.

Regressions for the 2026-08-25 drive findings G1 (communities were a
"top-level directory" heuristic whose single "(root)" bucket carried the STAGING
corpus id after promotion) and G2 (the whole-corpus view had no relationships to
draw). Real Neo4j, real Postgres corpus row, no mocks.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from httpx import AsyncClient
from neo4j_graphrag.experimental.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import build_generation
from server.indexing.official_graphrag import write_lexical_graph_with_graphrag
from server.models.index import Chunk

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


def _rel(a: str, b: str) -> Neo4jRelationship:
    return Neo4jRelationship(start_node_id=a, end_node_id=b, type="associated_with", properties={"weight": 1.0})


async def test_label_propagation_communities_survive_promotion_and_feed_the_subgraph(client: AsyncClient) -> None:
    active = f"graph-comm-{uuid4().hex[:8]}"
    staging = f"__staging__{active}__{uuid4().hex[:6]}"
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
        await neo.ensure_schema()
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
            repo_id=staging, run_id="communities-live", file_path="observatory-overview.md", chunks=[chunk]
        )
        await neo.upsert_graphrag_graph(staging, lexical, lexical_graph_config=lexical_cfg)

        # Two linked groups (a triangle and a chain) plus one isolated entity.
        entities = Neo4jGraph(
            nodes=[
                _entity("a1", "Aurora Tidal Observatory", "org", "Org"),
                _entity("a2", "Dr. Mireille Okafor", "person", "Person"),
                _entity("a3", "Tidal calibration campaign", "event", "Event"),
                _entity("b1", "KestrelDB", "concept", "Concept"),
                _entity("b2", "Pelican gateway", "concept", "Concept"),
                _entity("b3", "Sensor ingest pipeline", "concept", "Concept"),
                _entity("z1", "Unlinked footnote", "concept", "Concept"),
            ],
            # One bridge (a3 -> b1) joins the groups: community detection must still
            # separate them (connected-component grouping would not).
            relationships=[
                _rel("a1", "a2"),
                _rel("a2", "a3"),
                _rel("a1", "a3"),
                _rel("b1", "b2"),
                _rel("b2", "b3"),
                _rel("b1", "b3"),
                _rel("a3", "b1"),
            ],
        )
        await neo.upsert_graphrag_graph(staging, entities, lexical_graph_config=lexical_cfg)

        detected = await neo.detect_communities(staging)
        assert len(detected) == 2, [c.model_dump() for c in detected]
        member_sets = sorted(sorted(c.member_ids) for c in detected)
        assert member_sets == [["a1", "a2", "a3"], ["b1", "b2", "b3"]]
        for community in detected:
            assert community.community_id.startswith("c-")
            assert staging not in community.community_id and active not in community.community_id
            assert community.name in {"Tidal calibration campaign", "KestrelDB"}, community.name  # the bridge endpoints are the hubs
            assert "linked entities around" in community.summary
        assert all("z1" not in c.member_ids for c in detected)

        # Promotion is the manifest write on the corpus row (no relabel); the API
        # resolves the graph generation id from it and community ids stay valid.
        pg = PostgresClient(os.environ["POSTGRES_DSN"])
        await pg.connect()
        try:
            await pg.set_generation(
                active, build_generation(run_id="communities-live", qdrant_collection=None, graph_repo_id=staging)
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
        assert {e["entity_id"] for e in payload["entities"]} == {"a1", "a2", "a3", "b1", "b2", "b3", "z1"}
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
        for repo_id in (active, staging):
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
    staging = f"__staging__{active}__{uuid4().hex[:6]}"
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
        await neo.ensure_schema()
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
            run_id="code-live",
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
                _rel(module, reranker),
                _rel(reranker, rerank_init),
                # MLXQwen3Reranker matches "reranker" too but links only OUTSIDE the
                # result set, so the induced-edge query must not invent an edge for it.
                _rel(mlx_reranker, unrelated),
            ],
        )
        await neo.upsert_graphrag_graph(staging, graph, lexical_graph_config=lexical_cfg)

        pg = PostgresClient(os.environ["POSTGRES_DSN"])
        await pg.connect()
        try:
            await pg.set_generation(
                active, build_generation(run_id="code-live", qdrant_collection=None, graph_repo_id=staging)
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
