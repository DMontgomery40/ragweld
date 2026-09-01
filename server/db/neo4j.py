from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship

_BATCH_SIZE_DEFAULT = 500
_DEFAULT_REPO_SCOPED_NODE_LABELS: tuple[str, ...] = ("Document", "Chunk", "__Entity__")


# The one entity-name predicate. The entity list and the corpus subgraph must select the
# SAME entities for a query, or a search would list rows the visualizer never draws.
ENTITY_NAME_MATCH_CLAUSE = (
    "(toLower({var}.name) CONTAINS $q "
    "OR toLower(replace(replace({var}.name, '_', ' '), '-', ' ')) CONTAINS $q)"
)


def entity_source_file_expr(var: str) -> str:
    """Cypher for an entity's provenance file.

    Code entities store the file that defines them. Semantic entities carry no
    ``file_path`` of their own: the official extractor links them to their source
    chunk with ``FROM_CHUNK`` and never copies the file onto the node, so the
    explorer showed "File: —" for every NASA entity (Task 8 drive defect D16).
    """
    name = str(var or "").strip()
    if not name.isidentifier():
        raise ValueError("entity_source_file_expr needs a Cypher variable name")
    return (
        f"coalesce({name}.file_path, "
        f"head([({name})-[:FROM_CHUNK]->(provenance_chunk:Chunk {{repo_id: $repo_id}}) "
        f"| provenance_chunk.file_path]))"
    )


def normalize_entity_query(query: str | None) -> str:
    """Lower-cased, separator-folded search term; empty string means "no filter"."""
    q = (query or "").strip().lower()
    if not q:
        return ""
    q = re.sub(r"[_-]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str, database: str | None = None):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database or "neo4j"
        self._driver: AsyncDriver | None = None
        self._server_version: str | None = None

    async def connect(self) -> None:
        uri = os.getenv("NEO4J_URI") or self.uri
        user = os.getenv("NEO4J_USER") or self.user
        password = os.getenv("NEO4J_PASSWORD") or self.password
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None

    async def ping(self) -> dict[str, Any]:
        """Lightweight connectivity + server info probe.

        Returns minimal server info, including edition/version when available.
        """
        driver = self._require_driver()
        async with driver.session(database="system") as session:
            # Works in Neo4j 5+; returns (name, versions, edition).
            res = await session.run(
                "CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition LIMIT 1;"
            )
            rec: Any | None
            if hasattr(res, "single"):
                rec = await res.single()
            else:
                # Test doubles may only implement data().
                rows = await res.data() if hasattr(res, "data") else []
                rec = rows[0] if rows else None
        if not rec:
            return {"ok": True, "name": None, "versions": None, "edition": None}
        versions = rec.get("versions")
        parsed_versions = [str(v) for v in (versions or [])] if isinstance(versions, list) else []
        if parsed_versions:
            self._server_version = parsed_versions[0]
        return {
            "ok": True,
            "name": str(rec.get("name") or ""),
            "versions": parsed_versions,
            "edition": str(rec.get("edition") or ""),
        }

    async def gds_version(self) -> str:
        """Return the installed Graph Data Science version or fail closed."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            result = await session.run(
                "CALL gds.version() YIELD gdsVersion RETURN gdsVersion LIMIT 1"
            )
            record = await result.single()
        return str(record.get("gdsVersion") or "") if record else ""

    async def database_exists(self, database: str) -> bool:
        """Return True if a database exists (Neo4j 5 multi-db aware)."""
        db = _sanitize_database_name(database)
        if not db:
            return False
        driver = self._require_driver()
        async with driver.session(database="system") as session:
            res = await session.run(
                "SHOW DATABASES YIELD name WHERE name = $name RETURN count(*) AS n;", name=db
            )
            rec = await res.single()
        return bool(int(rec.get("n") or 0) > 0) if rec else False

    async def ensure_database(
        self, database: str, *, wait_online: bool = True, timeout_s: float = 10.0
    ) -> bool:
        """Create a database if missing (Enterprise). No-op if it already exists.

        Returns True if the database exists/was created, False if creation is not supported.
        """
        db = _sanitize_database_name(database)
        if not db:
            raise ValueError(f"Invalid Neo4j database name: {database!r}")

        driver = self._require_driver()
        try:
            async with driver.session(database="system") as session:
                # Database name cannot be safely parameterized; sanitize then inline.
                await session.run(f"CREATE DATABASE `{db}` IF NOT EXISTS;")
        except Exception:
            # Community edition does not support multi-database creation.
            return False

        if not wait_online:
            return True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, float(timeout_s))
        while loop.time() < deadline:
            async with driver.session(database="system") as session:
                res = await session.run(
                    "SHOW DATABASES YIELD name, currentStatus WHERE name = $name RETURN currentStatus AS status;",
                    name=db,
                )
                rec = await res.single()
            status = str(rec.get("status", "") if rec else "").upper()
            if status in {"ONLINE"}:
                return True
            # STATES: ONLINE, OFFLINE, STARTING, STOPPING, STORE_COPYING, INITIAL, DRAINING...
            await asyncio.sleep(0.2)
        return False

    async def get_entity(self, repo_id: str, entity_id: str) -> Entity | None:
        """An entity of ONE graph generation; entity ids are only unique within a corpus/generation."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            row = await session.run(
                f"""
                MATCH (n:__Entity__ {{repo_id: $repo_id, entity_id: $entity_id}})
                RETURN n.repo_id AS repo_id,
                       n.entity_id AS entity_id,
                       n.name AS name,
                       n.entity_type AS entity_type,
                       {entity_source_file_expr("n")} AS file_path,
                       n.description AS description,
                       properties(n) AS properties
                LIMIT 1;
                """,
                repo_id=repo_id,
                entity_id=entity_id,
            )
            rec = await row.single()
        if not rec:
            return None
        return _entity_from_record(rec)

    async def list_entities(
        self, repo_id: str, entity_type: str | None, limit: int, query: str | None = None
    ) -> list[Entity]:
        driver = self._require_driver()
        where = "WHERE n.repo_id = $repo_id"
        params: dict[str, Any] = {"repo_id": repo_id, "limit": int(limit)}
        if entity_type:
            where += " AND n.entity_type = $entity_type"
            params["entity_type"] = entity_type
        q = normalize_entity_query(query)
        if q:
            where += f" AND {ENTITY_NAME_MATCH_CLAUSE.format(var='n')}"
            params["q"] = q
        query = f"""
        MATCH (n:__Entity__)
        {where}
        RETURN n.repo_id AS repo_id,
               n.entity_id AS entity_id,
               n.name AS name,
               n.entity_type AS entity_type,
               {entity_source_file_expr("n")} AS file_path,
               n.description AS description,
               properties(n) AS properties
        ORDER BY name ASC
        LIMIT $limit;
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(query, **params)
            records = await res.data()
        return [_entity_from_mapping(r) for r in records]

    async def get_relationships(self, repo_id: str, entity_id: str) -> list[Relationship]:
        """Outgoing relationships of an entity within ONE graph generation (both endpoints scoped)."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            res = await session.run(
                """
                MATCH (a:__Entity__ {repo_id: $repo_id, entity_id: $entity_id})-[r]->(b:__Entity__ {repo_id: $repo_id})
                RETURN a.entity_id AS source_id,
                       b.entity_id AS target_id,
                       type(r) AS relation_type,
                       coalesce(r.weight, 1.0) AS weight,
                       properties(r) AS properties;
                """,
                repo_id=repo_id,
                entity_id=entity_id,
            )
            records = await res.data()
        out: list[Relationship] = []
        for r in records:
            out.append(
                Relationship(
                    source_id=str(r["source_id"]),
                    target_id=str(r["target_id"]),
                    relation_type=str(r.get("relation_type") or ""),
                    weight=float(r.get("weight") or 1.0),
                    properties=_relationship_properties_from_mapping(r),
                )
            )
        return out

    async def get_entity_neighbors(
        self,
        repo_id: str,
        entity_id: str,
        *,
        max_hops: int,
        limit: int,
    ) -> GraphNeighborsResponse | None:
        """Return a neighbor subgraph centered on an Entity.

        Notes:
        - Uses a single Cypher query to avoid N+1 fetches
        - Neo4j does not allow parameterized variable-length patterns (*1..$hops),
          so hop limits are validated + inlined.
        """
        hops = int(max(1, max_hops or 1))
        hops = min(hops, 5)
        lim = int(max(0, limit or 0))
        lim = min(lim, 2000)

        driver = self._require_driver()

        # The approved schema owns the edge vocabulary, so edges are never filtered by
        # type. The walk is confined to entity nodes of this generation instead: a
        # path that crossed a Chunk node would report co-mentioned entities as
        # neighbours (Task 8 drive defect D1).
        cypher = f"""
        MATCH (center:__Entity__ {{repo_id: $repo_id, entity_id: $entity_id}})

        OPTIONAL MATCH p = (center)-[*1..{hops}]-(n:__Entity__ {{repo_id: $repo_id}})
        WHERE ALL(x IN nodes(p) WHERE x:__Entity__ AND x.repo_id = $repo_id) AND n <> center
        WITH center, n, min(length(p)) AS min_hops
        ORDER BY min_hops ASC, n.name ASC
        LIMIT $limit

        WITH center, [x IN collect(DISTINCT n) WHERE x IS NOT NULL] AS neighbors
        WITH neighbors + [center] AS nodes

        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b:__Entity__)
        WHERE b IN nodes
        WITH nodes, [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels

        RETURN
          [n IN nodes |
            {{
              entity_id: n.entity_id,
              name: n.name,
              entity_type: n.entity_type,
              file_path: {entity_source_file_expr("n")},
              description: n.description,
              properties: properties(n)
            }}
          ] AS entities,
          [r IN rels |
            {{
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties: properties(r)
            }}
          ] AS relationships;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                entity_id=entity_id,
                limit=lim,
            )
            records = await res.data()
        if not records:
            return None

        rec = records[0] or {}
        entities_raw = rec.get("entities") or []
        relationships_raw = rec.get("relationships") or []

        entities: list[Entity] = []
        if isinstance(entities_raw, list):
            for item in entities_raw:
                if isinstance(item, dict):
                    entities.append(_entity_from_mapping(item))

        rels: list[Relationship] = []
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=rel_type,
                        weight=weight,
                        properties=_relationship_properties_from_mapping(r),
                    )
                )

        # `limit` caps the ENTITIES returned, the same as on the corpus and community
        # subgraphs. The Cypher caps the neighbour scan, which yielded limit+1 rows once
        # the centre was appended (review F-03); lowering that scan to limit-1 instead made
        # a limit of 1 return no rows at all and 404 an entity that exists. So the trim
        # happens here, centre first, with the edges narrowed to the entities that survive.
        entities.sort(key=lambda e: e.entity_id != entity_id)
        entities = entities[:lim]
        kept = {e.entity_id for e in entities}
        rels = [r for r in rels if r.source_id in kept and r.target_id in kept]

        return GraphNeighborsResponse(
            entities=entities,
            relationships=rels,
            total_matched=await self.count_entity_neighbors(repo_id, entity_id, max_hops=hops),
            limit=lim,
        )

    async def count_entity_neighbors(self, repo_id: str, entity_id: str, *, max_hops: int) -> int:
        """Reachable neighbours within ``max_hops``, plus the centre, BEFORE any display limit.

        ``total_matched`` promises a pre-limit count. Reporting ``len(entities)`` made it
        equal ``limit`` for any entity with more neighbours than the cap, so a 500-neighbour
        entity said "200 of 200" (review F-03).

        ``n <> center`` matters above 2 hops: a path that returns to the centre binds ``n``
        to it, so the centre counted as one of its own neighbours AND was appended again by
        the caller. The two errors cancelled in the total, which is why the numbers agreed -
        luck, not correctness - while the entity list carried a real duplicate row (N-02).
        """
        hops = min(max(1, int(max_hops or 1)), 5)
        driver = self._require_driver()
        cypher = f"""
        MATCH (center:__Entity__ {{repo_id: $repo_id, entity_id: $entity_id}})
        OPTIONAL MATCH p = (center)-[*1..{hops}]-(n:__Entity__ {{repo_id: $repo_id}})
        WHERE ALL(x IN nodes(p) WHERE x:__Entity__ AND x.repo_id = $repo_id) AND n <> center
        RETURN count(DISTINCT n) AS neighbours;
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(cypher, repo_id=repo_id, entity_id=entity_id)
            rec = await res.single()
        if rec is None:
            return 0
        # The centre is part of the returned subgraph, so it counts toward the total.
        return int(rec.get("neighbours") or 0) + 1

    async def count_community_members(self, repo_id: str, community_id: str) -> int:
        """Members of a community BEFORE any display limit."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            res = await session.run(
                """
                MATCH (e:__Entity__ {repo_id: $repo_id})
                WHERE toString(e.communityId) = $community_id
                RETURN count(DISTINCT e) AS members;
                """,
                repo_id=repo_id,
                community_id=community_id,
            )
            rec = await res.single()
        return int((rec.get("members") if rec else 0) or 0)

    async def get_community_members(
        self, repo_id: str, community_id: str, *, limit: int = 500
    ) -> list[Entity]:
        lim = int(max(0, limit or 0))
        lim = min(lim, 5000)
        if not community_id.strip() or lim <= 0:
            return []

        driver = self._require_driver()
        query = f"""
        MATCH (e:__Entity__ {{repo_id: $repo_id}})
        WHERE toString(e.communityId) = $community_id
        OPTIONAL MATCH (e)-[degree_rel]-(other:__Entity__ {{repo_id: $repo_id}})
        WITH e, count(DISTINCT degree_rel) AS degree
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.entity_type AS entity_type,
               {entity_source_file_expr("e")} AS file_path,
               e.description AS description,
               properties(e) AS properties
        ORDER BY degree DESC, name ASC, entity_id ASC
        LIMIT $limit;
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(
                query,
                repo_id=repo_id,
                community_id=community_id,
                limit=lim,
            )
            records = await res.data()

        return [_entity_from_mapping(r) for r in records]

    async def get_community_subgraph(
        self,
        repo_id: str,
        community_id: str,
        *,
        limit: int = 200,
    ) -> GraphNeighborsResponse | None:
        """Return an induced subgraph for a community (members + edges between members).

        This is used by the UI force-graph visualization so community selection can show edges,
        not just a flat member list.
        """
        lim = int(max(0, limit or 0))
        lim = min(lim, 2000)
        if not community_id.strip() or lim <= 0:
            return None

        driver = self._require_driver()

        cypher = f"""
        MATCH (e:__Entity__ {{repo_id: $repo_id}})
        WHERE toString(e.communityId) = $community_id
        OPTIONAL MATCH (e)-[degree_rel]-(other:__Entity__ {{repo_id: $repo_id}})
        WITH e, count(DISTINCT degree_rel) AS degree
        ORDER BY degree DESC, e.name ASC, e.entity_id ASC
        LIMIT $limit

        WITH collect(e) AS nodes
        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b:__Entity__ {{repo_id: $repo_id}})
        WHERE b IN nodes
        WITH nodes, [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels

        RETURN
          [n IN nodes |
            {{
              entity_id: n.entity_id,
              name: n.name,
              entity_type: n.entity_type,
              file_path: {entity_source_file_expr("n")},
              description: n.description,
              properties: properties(n)
            }}
          ] AS entities,
          [r IN rels |
            {{
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties: properties(r)
            }}
          ] AS relationships;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                community_id=community_id,
                limit=lim,
            )
            records = await res.data()
        if not records:
            return None

        rec = records[0] or {}
        entities_raw = rec.get("entities") or []
        relationships_raw = rec.get("relationships") or []

        entities: list[Entity] = []
        if isinstance(entities_raw, list):
            for item in entities_raw:
                if isinstance(item, dict):
                    entities.append(_entity_from_mapping(item))

        rels: list[Relationship] = []
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=rel_type,
                        weight=weight,
                        properties=_relationship_properties_from_mapping(r),
                    )
                )

        if not entities:
            return None
        return GraphNeighborsResponse(
            entities=entities,
            relationships=rels,
            total_matched=await self.count_community_members(repo_id, community_id),
            limit=lim,
        )

    async def get_repo_subgraph(
        self, repo_id: str, *, limit: int = 200, query: str | None = None
    ) -> GraphNeighborsResponse:
        """Return the induced subgraph over the ``limit`` best-connected matching entities.

        The whole-corpus visualizer needs edges, not just the entity list; this is
        the one query that returns both, ranked by degree so a capped view keeps
        the hubs. With ``query`` set it is the search view: the same entities the
        entity list shows, PLUS the relationships that run between them, so a
        search stops rendering as unconnected dots (M-62).

        ``total_matched`` reports how many entities matched before ``limit``, so the
        operator sees a denominator rather than a bare count (M-61).
        """
        lim = int(max(0, limit or 0))
        lim = min(lim, 2000)
        q = normalize_entity_query(query)
        total = await self.count_entities(repo_id, query=q)
        if lim <= 0 or total == 0:
            return GraphNeighborsResponse(
                entities=[], relationships=[], total_matched=total, limit=lim
            )

        driver = self._require_driver()
        match_filter = f" AND {ENTITY_NAME_MATCH_CLAUSE.format(var='e')}" if q else ""
        cypher = f"""
        MATCH (e:__Entity__)
        WHERE e.repo_id = $repo_id{match_filter}
        OPTIONAL MATCH (e)-[r]-(:__Entity__ {{repo_id: $repo_id}})
        WITH e, count(r) AS degree
        ORDER BY degree DESC, e.name ASC, e.entity_id ASC
        LIMIT $limit

        WITH collect(e) AS nodes
        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b:__Entity__ {{repo_id: $repo_id}})
        WHERE b IN nodes
        WITH nodes, [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels

        RETURN
          [n IN nodes |
            {{
              entity_id: n.entity_id,
              name: n.name,
              entity_type: n.entity_type,
              file_path: {entity_source_file_expr("n")},
              description: n.description,
              properties: properties(n)
            }}
          ] AS entities,
          [r IN rels |
            {{
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties: properties(r)
            }}
          ] AS relationships;
        """
        params: dict[str, Any] = {"repo_id": repo_id, "limit": lim}
        if q:
            params["q"] = q
        async with driver.session(database=self.database) as session:
            res = await session.run(cypher, **params)
            records = await res.data()
        if not records:
            return GraphNeighborsResponse(
                entities=[], relationships=[], total_matched=total, limit=lim
            )
        rec = records[0] or {}
        entities = [
            _entity_from_mapping(item)
            for item in (rec.get("entities") or [])
            if isinstance(item, dict)
        ]
        rels: list[Relationship] = []
        for r in rec.get("relationships") or []:
            if not isinstance(r, dict):
                continue
            rel_type = str(r.get("relation_type") or "")
            weight = max(0.0, min(1.0, float(r.get("weight") or 1.0)))
            rels.append(
                Relationship(
                    source_id=str(r.get("source_id") or ""),
                    target_id=str(r.get("target_id") or ""),
                    relation_type=rel_type,
                    weight=weight,
                    properties=_relationship_properties_from_mapping(r),
                )
            )
        return GraphNeighborsResponse(
            entities=entities, relationships=rels, total_matched=total, limit=lim
        )

    async def count_entities(self, repo_id: str, *, query: str | None = None) -> int:
        """How many entities a corpus (optionally a search) has, before any display limit."""
        q = normalize_entity_query(query)
        driver = self._require_driver()
        match_filter = f" AND {ENTITY_NAME_MATCH_CLAUSE.format(var='n')}" if q else ""
        cypher = f"""
        MATCH (n:__Entity__)
        WHERE n.repo_id = $repo_id{match_filter}
        RETURN count(n) AS total;
        """
        params: dict[str, Any] = {"repo_id": repo_id}
        if q:
            params["q"] = q
        async with driver.session(database=self.database) as session:
            res = await session.run(cypher, **params)
            rec = await res.single()
        return int((rec.get("total") if rec else 0) or 0)

    async def get_communities(self, repo_id: str, level: int | None) -> list[Community]:
        driver = self._require_driver()
        query = """
        MATCH (e:__Entity__ {repo_id: $repo_id})
        WHERE e.communityId IS NOT NULL AND e.communityPath IS NOT NULL
        OPTIONAL MATCH (e)-[degree_rel]-(other:__Entity__ {repo_id: $repo_id})
        WITH e,
             count(DISTINCT degree_rel) AS degree,
             toString(e.communityId) AS community_id,
             size(e.communityPath) - 1 AS level
        WHERE $level IS NULL OR level = $level
        ORDER BY community_id ASC, degree DESC, e.name ASC, e.entity_id ASC
        WITH community_id, level,
             collect({entity_id: e.entity_id, name: e.name, degree: degree}) AS ranked
        RETURN community_id,
               level,
               ranked[0].name AS name,
               [row IN ranked | row.entity_id] AS member_ids,
               [row IN ranked | row.name] AS member_names
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(
                query,
                repo_id=repo_id,
                level=int(level) if level is not None else None,
            )
            records = await res.data()

        out: list[Community] = []
        for r in records:
            member_ids = [str(x) for x in (r.get("member_ids") or [])]
            member_names = [str(x) for x in (r.get("member_names") or [])]
            preview = ", ".join(member_names[:5])
            if len(member_names) > 5:
                preview += f", +{len(member_names) - 5} more"
            out.append(
                Community(
                    community_id=str(r["community_id"]),
                    name=str(r["name"]),
                    summary=(
                        f"{len(member_ids)} related entities around {str(r['name'])}: {preview}"
                    ),
                    member_ids=member_ids,
                    level=int(r.get("level") or 0),
                )
            )
        return sorted(
            out,
            key=lambda community: (
                -len(community.member_ids),
                community.name,
                community.community_id,
            ),
        )

    async def execute_cypher(
        self, query: str, params: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        driver = self._require_driver()
        p = params or {}

        # Guardrail: only allow read-only statements from this debug endpoint.
        lowered = query.strip().lower()
        banned = ("create ", "merge ", "delete ", "set ", "drop ", "call dbms", "call gds")
        if any(b in lowered for b in banned):
            raise ValueError("Only read-only Cypher is allowed (MATCH/RETURN).")

        async with driver.session(database=self.database) as session:
            res = await session.run(query, **p)
            records: list[dict[str, Any]] = await res.data()
        return records

    _store_size_cache: dict[str, tuple[float, int]] = {}
    _store_size_ttl_s: float = 30.0

    @staticmethod
    def _dir_size_bytes(root: Path) -> int:
        """Return total size of all files under root (best-effort)."""
        total = 0
        stack: list[Path] = [root]
        while stack:
            p = stack.pop()
            try:
                for child in p.iterdir():
                    try:
                        if child.is_dir():
                            stack.append(child)
                        elif child.is_file():
                            total += child.stat().st_size
                    except Exception:
                        continue
            except Exception:
                continue
        return int(total)

    @staticmethod
    def _resolve_host_neo4j_data_dir() -> Path | None:
        """Resolve the host path where docker-compose mounts Neo4j /data.

        This is used as a fallback when Neo4j JMX store beans are unavailable.
        """
        # docker-compose uses TRIBRID_DB_DIR (default ../tribrid-rag-db) and mounts:
        #   ${TRIBRID_DB_DIR}/neo4j/data  -> /data
        repo_root = Path(__file__).resolve().parents[2]
        raw = os.getenv("TRIBRID_DB_DIR") or "../tribrid-rag-db"
        base = Path(raw).expanduser()
        if not base.is_absolute():
            base = (repo_root / base).resolve()
        data_dir = (base / "neo4j" / "data").resolve()
        if data_dir.exists():
            return data_dir
        return None

    async def get_store_size_bytes(self) -> int:
        """Return the total Neo4j store size (bytes) for this database.

        Uses JMX exposure via Cypher (works in Neo4j 5+):
        `CALL dbms.queryJmx(\"org.neo4j:instance=kernel#0,name=Store file sizes\")`.
        """
        db_key = str(self.database or "neo4j")
        now = time.time()
        cached = self._store_size_cache.get(db_key)
        if cached is not None:
            ts, size = cached
            if now - ts <= float(self._store_size_ttl_s):
                return int(size)

        size = 0

        # 1) Try Neo4j store-size MBean (may not be registered in some builds/configs)
        try:
            driver = self._require_driver()
            async with driver.session(database=self.database) as session:
                res = await session.run(
                    """
                    CALL dbms.queryJmx("org.neo4j:instance=kernel#0,name=Store file sizes")
                    YIELD attributes
                    RETURN attributes AS attrs
                    LIMIT 1;
                    """
                )
                rec = await res.single()

            attrs = rec.get("attrs") if rec else None
            if isinstance(attrs, dict):
                raw = attrs.get("TotalStoreSize") or attrs.get("totalStoreSize")
                if isinstance(raw, dict):
                    raw = raw.get("value")
                size = int(raw or 0)
        except Exception:
            size = 0

        # 2) Fallback: host filesystem measurement (docker-compose local dev)
        if size <= 0:
            data_dir = self._resolve_host_neo4j_data_dir()
            if data_dir is not None:
                db_dir = data_dir / "databases" / db_key
                tx_dir = data_dir / "transactions" / db_key
                size = 0
                if db_dir.exists():
                    size += await asyncio.to_thread(self._dir_size_bytes, db_dir)
                if tx_dir.exists():
                    size += await asyncio.to_thread(self._dir_size_bytes, tx_dir)

        self._store_size_cache[db_key] = (now, int(size))
        return int(size)

    # Stats
    async def get_graph_stats(self, repo_id: str) -> GraphStats:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            counts = await session.run(
                """
                OPTIONAL MATCH (e:__Entity__ {repo_id: $repo_id})
                WITH count(e) AS total_entities
                OPTIONAL MATCH (:__Entity__ {repo_id: $repo_id})-[r]->(:__Entity__ {repo_id: $repo_id})
                WITH total_entities, count(r) AS total_relationships
                OPTIONAL MATCH (community_entity:__Entity__ {repo_id: $repo_id})
                WHERE community_entity.communityId IS NOT NULL
                WITH total_entities, total_relationships,
                     count(DISTINCT community_entity.communityId) AS total_communities
                OPTIONAL MATCH (d:Document {repo_id: $repo_id})
                WITH total_entities, total_relationships, total_communities, count(d) AS total_documents
                OPTIONAL MATCH (k:Chunk {repo_id: $repo_id})
                RETURN total_entities, total_relationships, total_communities, total_documents, count(k) AS total_chunks;
                """,
                repo_id=repo_id,
            )
            rec = await counts.single()

            entity_breakdown_res = await session.run(
                """
                MATCH (e:__Entity__ {repo_id: $repo_id})
                RETURN e.entity_type AS t, count(e) AS n;
                """,
                repo_id=repo_id,
            )
            entity_rows = await entity_breakdown_res.data()

            rel_breakdown_res = await session.run(
                """
                MATCH (:__Entity__ {repo_id: $repo_id})-[r]->(:__Entity__ {repo_id: $repo_id})
                RETURN type(r) AS t, count(r) AS n;
                """,
                repo_id=repo_id,
            )
            rel_rows = await rel_breakdown_res.data()

        entity_breakdown = {str(r["t"]): int(r["n"]) for r in entity_rows}
        rel_breakdown = {str(r["t"]): int(r["n"]) for r in rel_rows}
        return GraphStats(
            repo_id=repo_id,
            total_entities=int(rec["total_entities"] if rec else 0),
            total_relationships=int(rec["total_relationships"] if rec else 0),
            total_communities=int(rec["total_communities"] if rec else 0),
            total_documents=int(rec["total_documents"] if rec else 0),
            total_chunks=int(rec["total_chunks"] if rec else 0),
            entity_breakdown=entity_breakdown,
            relationship_breakdown=rel_breakdown,
        )

    async def get_graph_invariant_counts(
        self, repo_id: str, run_id: str, *, identity_property: str
    ) -> dict[str, int]:
        """Count the staged generation's promotion invariants.

        ``identity_property`` is the property the policy resolves entities on
        (``name`` for semantic graphs, ``entity_id`` for code graphs); two
        entities that share it and their domain labels form one duplicate group.
        """
        identity = str(identity_property or "").strip()
        if not identity:
            raise ValueError("identity_property must name the policy's resolution property")
        rows = await self.execute_cypher(
            """
            CALL () {
                MATCH (chunk:Chunk {repo_id: $repo_id})
                RETURN count(chunk) AS total_chunks
            }
            CALL () {
                MATCH (entity:__Entity__ {repo_id: $repo_id})
                RETURN count(entity) AS total_entities
            }
            CALL () {
                MATCH (:__Entity__ {repo_id: $repo_id})-[relationship]->
                      (:__Entity__ {repo_id: $repo_id})
                WHERE relationship.repo_id = $repo_id
                RETURN count(relationship) AS semantic_relationships
            }
            CALL () {
                MATCH (:__Entity__ {repo_id: $repo_id})-[relationship:FROM_CHUNK]->
                      (chunk:Chunk {repo_id: $repo_id})
                WHERE relationship.repo_id = $repo_id
                RETURN count(relationship) AS from_chunk_relationships,
                       count(DISTINCT chunk) AS linked_chunks
            }
            CALL () {
                MATCH (entity:__Entity__ {repo_id: $repo_id})
                WHERE entity[$identity_property] IS NOT NULL
                WITH entity[$identity_property] AS identity,
                     apoc.coll.sort([label IN labels(entity)
                        WHERE NOT label IN ['__Entity__', '__KGBuilder__']]) AS domain_labels,
                     count(*) AS n
                WHERE n > 1
                RETURN count(*) AS duplicate_groups
            }
            CALL () {
                MATCH (node)
                WHERE node.run_id = $run_id
                  AND (node.repo_id IS NULL OR node.repo_id <> $repo_id)
                RETURN count(node) AS cross_scope_nodes
            }
            CALL () {
                MATCH (start)-[relationship]->(finish)
                WHERE relationship.run_id = $run_id
                  AND (
                    relationship.repo_id IS NULL OR relationship.repo_id <> $repo_id
                    OR start.repo_id IS NULL OR start.repo_id <> $repo_id
                    OR finish.repo_id IS NULL OR finish.repo_id <> $repo_id
                  )
                RETURN count(relationship) AS cross_scope_relationships
            }
            RETURN total_chunks, total_entities, semantic_relationships,
                   from_chunk_relationships, linked_chunks, duplicate_groups,
                   cross_scope_nodes, cross_scope_relationships
            """,
            {"repo_id": repo_id, "run_id": run_id, "identity_property": identity},
        )
        row = rows[0] if rows else {}
        return {
            key: int(row.get(key) or 0)
            for key in (
                "total_chunks",
                "total_entities",
                "semantic_relationships",
                "from_chunk_relationships",
                "linked_chunks",
                "duplicate_groups",
                "cross_scope_nodes",
                "cross_scope_relationships",
            )
        }

    async def delete_graph(self, repo_id: str) -> None:
        """Delete all graph data (entities, rels, communities) for a corpus."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            batch_size = int(_BATCH_SIZE_DEFAULT * 10)
            labels = await self._resolve_repo_scoped_labels(session)
            for label in labels:
                while True:
                    res = await session.run(
                        f"""
                        MATCH (n:{label} {{repo_id: $repo_id}})
                        WITH n LIMIT $batch_size
                        DETACH DELETE n
                        RETURN count(*) AS n;
                        """,
                        repo_id=repo_id,
                        batch_size=batch_size,
                    )
                    rec = await res.single()
                    deleted = int(rec.get("n") or 0) if rec else 0
                    if deleted <= 0:
                        break

            # Safety sweep for legacy/unlabeled nodes that still carry repo_id.
            while True:
                res = await session.run(
                    """
                    MATCH (n {repo_id: $repo_id})
                    WHERE none(lbl IN labels(n) WHERE lbl IN $known_labels)
                    WITH n LIMIT $batch_size
                    DETACH DELETE n
                    RETURN count(*) AS n;
                    """,
                    repo_id=repo_id,
                    known_labels=labels,
                    batch_size=batch_size,
                )
                rec = await res.single()
                deleted = int(rec.get("n") or 0) if rec else 0
                if deleted <= 0:
                    break

    async def delete_staged_graphs(self, corpus_id: str) -> int:
        """Delete every staged graph generation of ONE corpus.

        Staging ids are ``__staging__<corpus>__<run>`` and run ids never contain
        ``__``, so the remainder after the prefix must be free of ``__``: corpus
        ``a`` must not sweep the staging graphs of corpus ``a__b``.
        """
        prefix = f"__staging__{str(corpus_id or '').strip()}__"
        if prefix == "__staging____":
            return 0
        driver = self._require_driver()
        removed = 0
        async with driver.session(database=self.database) as session:
            batch_size = int(_BATCH_SIZE_DEFAULT * 10)
            while True:
                res = await session.run(
                    """
                    MATCH (n)
                    WHERE n.repo_id STARTS WITH $prefix
                      AND NOT substring(n.repo_id, size($prefix)) CONTAINS '__'
                    WITH n LIMIT $batch_size
                    DETACH DELETE n
                    RETURN count(*) AS n;
                    """,
                    prefix=prefix,
                    batch_size=batch_size,
                )
                rec = await res.single()
                deleted = int(rec.get("n") or 0) if rec else 0
                removed += deleted
                if deleted <= 0:
                    break
        return removed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4j driver is not connected. Call connect() first.")
        return self._driver

    async def _resolve_repo_scoped_labels(self, session: Any) -> list[str]:
        """Resolve node labels that carry repo_id from schema constraints.

        Defaults ensure stable behavior even when schema introspection is
        unavailable (permissions/older server versions).
        """
        labels: set[str] = set(_DEFAULT_REPO_SCOPED_NODE_LABELS)
        try:
            res = await session.run(
                """
                SHOW CONSTRAINTS YIELD entityType, labelsOrTypes, properties
                WHERE entityType = 'NODE'
                RETURN labelsOrTypes, properties;
                """
            )
            rows = await res.data()
            for row in rows:
                props = row.get("properties")
                if not isinstance(props, list) or "repo_id" not in {str(p) for p in props}:
                    continue
                labels_or_types = row.get("labelsOrTypes")
                if isinstance(labels_or_types, list):
                    for label in labels_or_types:
                        lbl = str(label or "").strip()
                        if lbl:
                            labels.add(lbl)
        except Exception:
            pass
        return sorted(labels)


def _entity_from_record(record: Any) -> Entity:
    props = _entity_properties_from_mapping(record)
    return Entity(
        entity_id=str(record["entity_id"]),
        name=str(record.get("name") or ""),
        entity_type=str(record["entity_type"] or ""),
        file_path=str(record["file_path"]) if record.get("file_path") is not None else None,
        description=str(record["description"]) if record.get("description") is not None else None,
        properties=props,
    )


def _entity_from_mapping(mapping: dict[str, Any]) -> Entity:
    props = _entity_properties_from_mapping(mapping)
    return Entity(
        entity_id=str(mapping["entity_id"]),
        name=str(mapping.get("name") or ""),
        entity_type=str(mapping["entity_type"] or ""),
        file_path=str(mapping["file_path"]) if mapping.get("file_path") is not None else None,
        description=str(mapping["description"]) if mapping.get("description") is not None else None,
        properties=props,
    )


def _relationship_properties_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    raw_properties = mapping.get("properties")
    if isinstance(raw_properties, dict):
        cleaned = dict(raw_properties)
        cleaned.pop("repo_id", None)
        cleaned.pop("run_id", None)
        return cleaned
    if mapping.get("properties_json"):
        try:
            parsed = json.loads(mapping["properties_json"])
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _entity_properties_from_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    raw_properties = mapping.get("properties")
    if isinstance(raw_properties, dict):
        cleaned = dict(raw_properties)
        for key in (
            "repo_id",
            "run_id",
            "entity_id",
            "entity_type",
            "name",
            "description",
            "file_path",
        ):
            cleaned.pop(key, None)
        return cleaned
    if mapping.get("properties_json"):
        try:
            parsed = json.loads(mapping["properties_json"])
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _sanitize_database_name(name: str) -> str:
    """Conservative Neo4j database name sanitizer.

    Keeps only letters/digits/underscore and enforces a non-empty result.
    """
    raw = (name or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    # Neo4j names must be non-empty; prefix if we ended up with digits only.
    if not raw:
        return ""
    if raw[0].isdigit():
        raw = f"db_{raw}"
    # Be conservative with length.
    return raw[:63]
