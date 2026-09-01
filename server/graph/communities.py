"""Scoped deterministic GDS Leiden community detection for staged graphs."""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

from neo4j import Driver

from server.indexing.graphrag_pipeline import require_staging_graph_id
from server.models.index import GraphCommunityTelemetry

GDS_VERSION_PREFIX = "2.13."
GDS_LEIDEN_ALGORITHM = "gds-leiden-2.13"


def projection_name(_repo_id: str) -> str:
    return f"ragweld_{uuid.uuid4().hex}"


def projection_queries() -> tuple[str, str]:
    node_query = """
    MATCH (entity:__Entity__ {repo_id: $repo_id})
    RETURN id(entity) AS id
    """
    relationship_query = """
    MATCH (source:__Entity__ {repo_id: $repo_id})-[r]->(target:__Entity__ {repo_id: $repo_id})
    RETURN id(source) AS source, id(target) AS target, coalesce(r.weight, 1.0) AS weight
    UNION ALL
    MATCH (source:__Entity__ {repo_id: $repo_id})-[r]->(target:__Entity__ {repo_id: $repo_id})
    RETURN id(target) AS source, id(source) AS target, coalesce(r.weight, 1.0) AS weight
    """
    return node_query, relationship_query


def leiden_write_query() -> str:
    return """
    CALL gds.leiden.write($graph_name, {
      writeProperty: 'communityPath',
      relationshipTypes: ['UNDIRECTED'],
      relationshipWeightProperty: 'weight',
      includeIntermediateCommunities: true,
      randomSeed: 19,
      concurrency: 1
    })
    YIELD communityCount, ranLevels, modularity, modularities,
          nodeCount, didConverge, nodePropertiesWritten
    RETURN communityCount, ranLevels, modularity, modularities,
           nodeCount, didConverge, nodePropertiesWritten
    """


def _rows(
    driver: Driver, query: str, parameters: dict[str, Any], database: str
) -> list[dict[str, Any]]:
    records, _, _ = driver.execute_query(
        query,
        parameters_=parameters,
        database_=database,
    )
    return [dict(record) for record in records]


def _detect_sync(
    *, driver: Driver, neo4j_database: str, repo_id: str
) -> GraphCommunityTelemetry:
    scoped_repo_id = require_staging_graph_id(repo_id)
    graph_name = projection_name(scoped_repo_id)
    node_query, relationship_query = projection_queries()
    projected = False
    try:
        version_rows = _rows(
            driver,
            "CALL gds.version() YIELD gdsVersion RETURN gdsVersion",
            {},
            neo4j_database,
        )
        version = str(version_rows[0].get("gdsVersion") or "") if version_rows else ""
        if not version.startswith(GDS_VERSION_PREFIX):
            raise RuntimeError(
                f"GDS {GDS_VERSION_PREFIX}x is required for Leiden; found {version or 'none'}"
            )

        projection_rows = _rows(
            driver,
            """
            CALL gds.graph.project.cypher(
              $graph_name,
              $node_query,
              $relationship_query,
              {parameters: {repo_id: $repo_id}, validateRelationships: true}
            )
            YIELD graphName, nodeCount, relationshipCount
            RETURN graphName, nodeCount, relationshipCount
            """,
            {
                "graph_name": graph_name,
                "node_query": node_query,
                "relationship_query": relationship_query,
                "repo_id": scoped_repo_id,
            },
            neo4j_database,
        )
        projected = True
        projected_nodes = int(
            (projection_rows[0].get("nodeCount") if projection_rows else 0) or 0
        )
        scoped_rows = _rows(
            driver,
            "MATCH (e:__Entity__ {repo_id: $repo_id}) RETURN count(e) AS n",
            {"repo_id": scoped_repo_id},
            neo4j_database,
        )
        scoped_nodes = int((scoped_rows[0].get("n") if scoped_rows else 0) or 0)
        if projected_nodes != scoped_nodes:
            raise RuntimeError(
                f"GDS projection contained {projected_nodes} nodes but scoped graph has {scoped_nodes}"
            )
        if projected_nodes == 0:
            return GraphCommunityTelemetry(
                community_count=0,
                levels=0,
                modularity=0.0,
                did_converge=True,
                nodes_written=0,
            )

        _rows(
            driver,
            """
            CALL gds.graph.relationships.toUndirected($graph_name, {
              relationshipType: '__ALL__',
              mutateRelationshipType: 'UNDIRECTED',
              aggregation: 'SINGLE'
            })
            YIELD relationshipsWritten
            RETURN relationshipsWritten
            """,
            {"graph_name": graph_name},
            neo4j_database,
        )

        rows = _rows(
            driver,
            leiden_write_query(),
            {"graph_name": graph_name},
            neo4j_database,
        )
        row = rows[0] if rows else {}
        _rows(
            driver,
            """
            MATCH (entity:__Entity__ {repo_id: $repo_id})
            WHERE entity.communityPath IS NOT NULL
            SET entity.communityId = last(entity.communityPath)
            """,
            {"repo_id": scoped_repo_id},
            neo4j_database,
        )
        verified = _rows(
            driver,
            """
            MATCH (entity:__Entity__ {repo_id: $repo_id})
            RETURN count(entity) AS eligible,
                   count(entity.communityPath) AS paths,
                   count(entity.communityId) AS ids
            """,
            {"repo_id": scoped_repo_id},
            neo4j_database,
        )
        counts = verified[0] if verified else {}
        eligible = int(counts.get("eligible") or 0)
        paths = int(counts.get("paths") or 0)
        ids = int(counts.get("ids") or 0)
        nodes_written = int(row.get("nodePropertiesWritten") or 0)
        if (paths, ids, nodes_written) != (eligible, eligible, eligible):
            raise RuntimeError(
                "GDS Leiden did not write complete scoped community properties: "
                f"eligible={eligible} paths={paths} ids={ids} written={nodes_written}"
            )
        return GraphCommunityTelemetry(
            community_count=int(row.get("communityCount") or 0),
            levels=int(row.get("ranLevels") or 0),
            modularity=float(row.get("modularity") or 0.0),
            did_converge=bool(row.get("didConverge")),
            nodes_written=nodes_written,
        )
    finally:
        if projected:
            active_failure = sys.exc_info()[0] is not None
            try:
                _rows(
                    driver,
                    "CALL gds.graph.drop($graph_name, false) YIELD graphName RETURN graphName",
                    {"graph_name": graph_name},
                    neo4j_database,
                )
            except Exception:
                # Preserve the original projection/Leiden failure when cleanup also fails.
                # A cleanup failure on an otherwise-successful run must remain fatal.
                if not active_failure:
                    raise


async def detect_leiden_communities(
    *, driver: Driver, neo4j_database: str, repo_id: str
) -> GraphCommunityTelemetry:
    return await asyncio.to_thread(
        _detect_sync,
        driver=driver,
        neo4j_database=neo4j_database,
        repo_id=repo_id,
    )


__all__ = [
    "GDS_LEIDEN_ALGORITHM",
    "GDS_VERSION_PREFIX",
    "detect_leiden_communities",
    "leiden_write_query",
    "projection_name",
    "projection_queries",
]
