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
            relationships=[_rel("a1", "a2"), _rel("a2", "a3"), _rel("a1", "a3"), _rel("b1", "b2"), _rel("b2", "b3")],
        )
        await neo.upsert_graphrag_graph(staging, entities, lexical_graph_config=lexical_cfg)

        detected = await neo.detect_communities(staging)
        assert len(detected) == 2, [c.model_dump() for c in detected]
        member_sets = sorted(sorted(c.member_ids) for c in detected)
        assert member_sets == [["a1", "a2", "a3"], ["b1", "b2", "b3"]]
        for community in detected:
            assert community.community_id.startswith("c-")
            assert staging not in community.community_id and active not in community.community_id
            assert community.name in {"Aurora Tidal Observatory", "Pelican gateway"}, community.name
            assert "linked entities around" in community.summary
        assert all("z1" not in c.member_ids for c in detected)

        # Staging -> active promotion rewrites repo_id only; community ids stay valid.
        await neo.promote_repo_graph(active_repo_id=active, staging_repo_id=staging)
        listed = await client.get(f"/api/graph/{active}/communities")
        assert listed.status_code == 200, listed.text
        promoted = listed.json()
        assert {c["community_id"] for c in promoted} == {c.community_id for c in detected}
        assert sorted(sorted(c["member_ids"]) for c in promoted) == member_sets

        members = await client.get(f"/api/graph/{active}/community/{detected[0].community_id}/members")
        assert members.status_code == 200 and len(members.json()) == 3, members.text

        # The whole-corpus view gets entities AND the edges between them.
        subgraph = await client.get(f"/api/graph/{active}/subgraph", params={"limit": 50})
        assert subgraph.status_code == 200, subgraph.text
        payload = subgraph.json()
        assert {e["entity_id"] for e in payload["entities"]} == {"a1", "a2", "a3", "b1", "b2", "b3", "z1"}
        edges = {tuple(sorted((r["source_id"], r["target_id"]))) for r in payload["relationships"]}
        assert edges == {("a1", "a2"), ("a2", "a3"), ("a1", "a3"), ("b1", "b2"), ("b2", "b3")}
        assert all(r["relation_type"] == "associated_with" for r in payload["relationships"])
        # A capped view keeps the best-connected entities: a1/a2/a3/b2 all have
        # degree 2, and the deterministic name tie-break keeps "Aurora Tidal
        # Observatory", "Dr. Mireille Okafor" and "Pelican gateway".
        capped = await client.get(f"/api/graph/{active}/subgraph", params={"limit": 3})
        assert capped.status_code == 200
        assert {e["entity_id"] for e in capped.json()["entities"]} == {"a1", "a2", "b2"}
        assert {tuple(sorted((r["source_id"], r["target_id"]))) for r in capped.json()["relationships"]} == {("a1", "a2")}
    finally:
        for repo_id in (active, staging):
            try:
                await neo.delete_graph(repo_id)
            except Exception:
                pass
        await neo.disconnect()
        await client.delete(f"/api/corpora/{active}")
