from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, cast

from neo4j import AsyncDriver, AsyncGraphDatabase

from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.models.index import Chunk
from server.models.retrieval import ChunkMatch

EntityType = Literal["function", "class", "module", "variable", "concept"]
RelationshipType = Literal["calls", "imports", "inherits", "contains", "references", "related_to"]


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str, database: str | None = None):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database or "neo4j"
        self._driver: AsyncDriver | None = None

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
            res = await session.run("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition LIMIT 1;")
            rec = await res.single()
        if not rec:
            return {"ok": True, "name": None, "versions": None, "edition": None}
        versions = rec.get("versions")
        return {
            "ok": True,
            "name": str(rec.get("name") or ""),
            "versions": [str(v) for v in (versions or [])] if isinstance(versions, list) else [],
            "edition": str(rec.get("edition") or ""),
        }

    async def database_exists(self, database: str) -> bool:
        """Return True if a database exists (Neo4j 5 multi-db aware)."""
        db = _sanitize_database_name(database)
        if not db:
            return False
        driver = self._require_driver()
        async with driver.session(database="system") as session:
            res = await session.run("SHOW DATABASES YIELD name WHERE name = $name RETURN count(*) AS n;", name=db)
            rec = await res.single()
        return bool(int(rec.get("n") or 0) > 0) if rec else False

    async def ensure_database(self, database: str, *, wait_online: bool = True, timeout_s: float = 10.0) -> bool:
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

    # ------------------------------------------------------------------
    # Lexical chunk graph (Document/Chunk) + vector index
    # ------------------------------------------------------------------

    async def ensure_vector_index(
        self,
        *,
        index_name: str,
        label: str,
        embedding_property: str,
        dimensions: int,
        similarity_function: Literal["cosine", "euclidean"] = "cosine",
        wait_online: bool = True,
        timeout_s: float = 60.0,
    ) -> bool:
        """Ensure a Neo4j vector index exists and is ONLINE."""
        idx = _sanitize_cypher_identifier(index_name)
        prop = _sanitize_cypher_identifier(embedding_property)
        lbl = _sanitize_cypher_identifier(label)
        if not idx:
            raise ValueError(f"Invalid Neo4j vector index name: {index_name!r}")
        if not prop:
            raise ValueError(f"Invalid Neo4j embedding property name: {embedding_property!r}")
        if not lbl:
            raise ValueError(f"Invalid Neo4j label name: {label!r}")

        sim = (similarity_function or "cosine").strip().lower()
        if sim not in {"cosine", "euclidean"}:
            raise ValueError(f"Invalid similarity_function: {similarity_function!r}")

        driver = self._require_driver()
        cypher = f"""
        CREATE VECTOR INDEX `{idx}` IF NOT EXISTS
        FOR (n:`{lbl}`)
        ON (n.`{prop}`)
        OPTIONS {{
          indexConfig: {{
            `vector.dimensions`: {int(dimensions)},
            `vector.similarity_function`: '{sim}'
          }}
        }};
        """
        async with driver.session(database=self.database) as session:
            await session.run(cypher)

        if not wait_online:
            return True

        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.1, float(timeout_s))
        while loop.time() < deadline:
            async with driver.session(database=self.database) as session:
                res = await session.run(
                    "SHOW INDEXES YIELD name, state WHERE name = $name RETURN state AS state LIMIT 1;",
                    name=idx,
                )
                rec = await res.single()
            state = str(rec.get("state") if rec else "").upper()
            if state == "ONLINE":
                return True
            await asyncio.sleep(0.25)
        return False

    async def upsert_document_and_chunks(
        self,
        repo_id: str,
        file_path: str,
        chunks: list[Chunk],
        *,
        store_embeddings: bool,
        embedding_property: str = "embedding",
    ) -> int:
        """Upsert a lexical Document/Chunk graph for a single file.

        Stores Chunk nodes keyed by (repo_id, chunk_id) and links them with:
        - (Document)-[:HAS_CHUNK]->(Chunk)
        - (Chunk)-[:NEXT_CHUNK]->(Chunk) in file order
        """
        if not chunks:
            return 0
        prop = _sanitize_cypher_identifier(embedding_property)
        if not prop:
            raise ValueError(f"Invalid Neo4j embedding property name: {embedding_property!r}")

        driver = self._require_driver()
        payload: list[dict[str, Any]] = []
        for i, ch in enumerate(chunks):
            payload.append(
                {
                    "seq": int(i),
                    "chunk_id": ch.chunk_id,
                    "file_path": ch.file_path,
                    "start_line": int(ch.start_line),
                    "end_line": int(ch.end_line),
                    "language": ch.language,
                    "token_count": int(ch.token_count or 0),
                    "embedding": ch.embedding,
                }
            )

        cypher = f"""
        // Ensure the Document exists
        MERGE (d:Document {{repo_id: $repo_id, file_path: $file_path}})

        // Remove prior edges from this Document (we rebuild deterministically)
        WITH d
        OPTIONAL MATCH (d)-[old:HAS_CHUNK]->(:Chunk)
        WITH d, collect(old) AS olds
        FOREACH (r IN olds | DELETE r)

        // Upsert chunks + reattach
        WITH d
        UNWIND $chunks AS ch
        WITH d, ch
        ORDER BY ch.seq ASC
        MERGE (c:Chunk {{repo_id: $repo_id, chunk_id: ch.chunk_id}})
        SET c.file_path = ch.file_path,
            c.start_line = ch.start_line,
            c.end_line = ch.end_line,
            c.language = ch.language,
            c.token_count = ch.token_count
        FOREACH (_ IN CASE WHEN $store_embeddings AND ch.embedding IS NOT NULL THEN [1] ELSE [] END |
            SET c.`{prop}` = ch.embedding
        )
        MERGE (d)-[:HAS_CHUNK]->(c)
        WITH collect(c) AS cs

        // Clear previous NEXT_CHUNK edges for this file (avoid stale adjacency)
        OPTIONAL MATCH (a:Chunk {{repo_id: $repo_id, file_path: $file_path}})-[r:NEXT_CHUNK]->(b:Chunk {{repo_id: $repo_id, file_path: $file_path}})
        WITH cs, collect(r) AS rels
        FOREACH (r IN rels | DELETE r)

        // Recreate NEXT_CHUNK edges in order
        WITH cs
        UNWIND CASE WHEN size(cs) < 2 THEN [] ELSE range(0, size(cs)-2) END AS i
        WITH cs[i] AS a, cs[i+1] AS b
        MERGE (a)-[:NEXT_CHUNK]->(b);
        """

        async with driver.session(database=self.database) as session:
            await session.run(
                cypher,
                repo_id=repo_id,
                file_path=str(file_path),
                chunks=payload,
                store_embeddings=bool(store_embeddings),
            )
        return len(chunks)

    async def chunk_vector_search(
        self,
        repo_id: str,
        embedding: list[float],
        *,
        index_name: str,
        top_k: int,
        neighbor_window: int = 0,
        overfetch_multiplier: int = 1,
    ) -> list[tuple[str, float]]:
        """Vector search over Chunk nodes in Neo4j; returns (chunk_id, score)."""
        if not embedding or top_k <= 0:
            return []

        driver = self._require_driver()
        seed_k = max(1, int(top_k) * max(1, int(overfetch_multiplier)))
        window = max(0, int(neighbor_window))

        # Neo4j does not allow parameterized variable-length patterns (e.g., *0..$window),
        # so we safely inline the integer window (validated + clamped above).
        cypher = f"""
        CALL db.index.vector.queryNodes($index_name, $seed_k, $embedding) YIELD node, score
        WITH node, score
        WHERE node.repo_id = $repo_id
        WITH node, score
        ORDER BY score DESC
        LIMIT $top_k
        CALL {{
          WITH node, score
          MATCH p = (node)-[:NEXT_CHUNK*0..{window}]-(n:Chunk {{repo_id: $repo_id}})
          RETURN n.chunk_id AS chunk_id,
                 min(length(p)) AS dist,
                 max(score) AS seed_score
        }}
        WITH chunk_id,
             min(dist) AS dist,
             max(seed_score) AS seed_score
        RETURN chunk_id AS chunk_id,
               (seed_score / (1 + dist)) AS score
        ORDER BY score DESC
        LIMIT $top_k;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                index_name=str(index_name),
                seed_k=int(seed_k),
                embedding=embedding,
                top_k=int(top_k),
            )
            records = await res.data()

        out: list[tuple[str, float]] = []
        for r in records:
            cid = str(r.get("chunk_id") or "").strip()
            if not cid:
                continue
            out.append((cid, float(r.get("score") or 0.0)))
        return out

    # Entity operations
    async def upsert_entity(self, repo_id: str, entity: Entity) -> None:
        await self.upsert_entities(repo_id, [entity])

    async def upsert_entities(self, repo_id: str, entities: list[Entity]) -> int:
        if not entities:
            return 0
        driver = self._require_driver()

        payload = []
        for e in entities:
            props = e.properties or {}
            start_line = props.get("start_line")
            end_line = props.get("end_line")
            payload.append(
                {
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "entity_type": e.entity_type,
                    "file_path": e.file_path,
                    "description": e.description,
                    "properties_json": json.dumps(e.properties or {}),
                    "start_line": int(start_line) if start_line is not None else None,
                    "end_line": int(end_line) if end_line is not None else None,
                }
            )

        query = """
        UNWIND $entities AS e
        MERGE (n:Entity {repo_id: $repo_id, entity_id: e.entity_id})
        SET n.name = e.name,
            n.entity_type = e.entity_type,
            n.file_path = e.file_path,
            n.description = e.description,
            n.properties_json = e.properties_json,
            n.start_line = e.start_line,
            n.end_line = e.end_line;
        """

        async with driver.session(database=self.database) as session:
            await session.run(query, repo_id=repo_id, entities=payload)
        return len(entities)

    async def get_entity(self, entity_id: str) -> Entity | None:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            row = await session.run(
                """
                MATCH (n:Entity {entity_id: $entity_id})
                RETURN n.repo_id AS repo_id,
                       n.entity_id AS entity_id,
                       n.name AS name,
                       n.entity_type AS entity_type,
                       n.file_path AS file_path,
                       n.description AS description,
                       n.properties_json AS properties_json
                LIMIT 1;
                """,
                entity_id=entity_id,
            )
            rec = await row.single()
        if not rec:
            return None
        return _entity_from_record(rec)

    async def list_entities(self, repo_id: str, entity_type: str | None, limit: int, query: str | None = None) -> list[Entity]:
        driver = self._require_driver()
        where = "WHERE n.repo_id = $repo_id"
        params: dict[str, Any] = {"repo_id": repo_id, "limit": int(limit)}
        if entity_type:
            where += " AND n.entity_type = $entity_type"
            params["entity_type"] = entity_type
        q = (query or "").strip().lower()
        if q:
            where += " AND toLower(n.name) CONTAINS $q"
            params["q"] = q
        query = f"""
        MATCH (n:Entity)
        {where}
        RETURN n.repo_id AS repo_id,
               n.entity_id AS entity_id,
               n.name AS name,
               n.entity_type AS entity_type,
               n.file_path AS file_path,
               n.description AS description,
               n.properties_json AS properties_json
        ORDER BY name ASC
        LIMIT $limit;
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(query, **params)
            records = await res.data()
        return [_entity_from_mapping(r) for r in records]

    async def delete_entities(self, repo_id: str) -> int:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            result = await session.run(
                """
                MATCH (n:Entity {repo_id: $repo_id})
                WITH n, count(n) AS n_count
                DETACH DELETE n
                RETURN n_count AS n_count;
                """,
                repo_id=repo_id,
            )
            rec = await result.single()
        return int(rec["n_count"] if rec else 0)

    # Relationship operations
    async def upsert_relationship(self, repo_id: str, rel: Relationship) -> None:
        await self.upsert_relationships(repo_id, [rel])

    async def upsert_relationships(self, repo_id: str, rels: list[Relationship]) -> int:
        if not rels:
            return 0
        driver = self._require_driver()

        allowed = {
            "calls",
            "imports",
            "inherits",
            "contains",
            "references",
            "related_to",
        }
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rels:
            rel_type = str(r.relation_type)
            if rel_type not in allowed:
                continue
            grouped[rel_type].append(
                {
                    "source_id": r.source_id,
                    "target_id": r.target_id,
                    "weight": float(r.weight or 0.0),
                    "properties_json": json.dumps(r.properties or {}),
                }
            )

        async with driver.session(database=self.database) as session:
            for rel_type, payload in grouped.items():
                # Relationship type must be literal in Cypher; rel_type is validated against allowed.
                query = f"""
                UNWIND $rels AS r
                MATCH (a:Entity {{repo_id: $repo_id, entity_id: r.source_id}})
                MATCH (b:Entity {{repo_id: $repo_id, entity_id: r.target_id}})
                MERGE (a)-[rel:{rel_type}]->(b)
                SET rel.weight = r.weight,
                    rel.properties_json = r.properties_json;
                """
                await session.run(query, repo_id=repo_id, rels=payload)
        return sum(len(v) for v in grouped.values())

    async def get_relationships(self, entity_id: str) -> list[Relationship]:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            res = await session.run(
                """
                MATCH (a:Entity {entity_id: $entity_id})-[r]->(b:Entity)
                RETURN a.entity_id AS source_id,
                       b.entity_id AS target_id,
                       type(r) AS relation_type,
                       coalesce(r.weight, 1.0) AS weight,
                       r.properties_json AS properties_json;
                """,
                entity_id=entity_id,
            )
            records = await res.data()
        out: list[Relationship] = []
        allowed: set[str] = {
            "calls",
            "imports",
            "inherits",
            "contains",
            "references",
            "related_to",
        }
        for r in records:
            props = {}
            if r.get("properties_json"):
                try:
                    props = json.loads(r["properties_json"])
                except Exception:
                    props = {}
            rel_type = str(r.get("relation_type") or "")
            if rel_type not in allowed:
                continue
            out.append(
                Relationship(
                    source_id=str(r["source_id"]),
                    target_id=str(r["target_id"]),
                    relation_type=cast(RelationshipType, rel_type),
                    weight=float(r.get("weight") or 1.0),
                    properties=props,
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

        allowed_rels = ["calls", "imports", "inherits", "contains", "references", "related_to"]
        driver = self._require_driver()

        cypher = f"""
        MATCH (center:Entity {{repo_id: $repo_id, entity_id: $entity_id}})

        OPTIONAL MATCH p = (center)-[rels*1..{hops}]-(n:Entity {{repo_id: $repo_id}})
        WHERE ALL(r IN rels WHERE type(r) IN $allowed_rels)
        WITH center, n, min(length(p)) AS min_hops
        ORDER BY min_hops ASC, n.name ASC
        LIMIT $limit

        WITH center, [x IN collect(DISTINCT n) WHERE x IS NOT NULL] AS neighbors
        WITH neighbors + [center] AS nodes

        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b)
        WHERE b IN nodes AND type(r) IN $allowed_rels
        WITH nodes, [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels

        RETURN
          [n IN nodes |
            {{
              entity_id: n.entity_id,
              name: n.name,
              entity_type: n.entity_type,
              file_path: n.file_path,
              description: n.description,
              properties_json: n.properties_json
            }}
          ] AS entities,
          [r IN rels |
            {{
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties_json: r.properties_json
            }}
          ] AS relationships;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                entity_id=entity_id,
                allowed_rels=allowed_rels,
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
        allowed: set[str] = {"calls", "imports", "inherits", "contains", "references", "related_to"}
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                if rel_type not in allowed:
                    continue
                props = {}
                if r.get("properties_json"):
                    try:
                        props = json.loads(str(r["properties_json"]))
                    except Exception:
                        props = {}
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=cast(RelationshipType, rel_type),
                        weight=weight,
                        properties=props,
                    )
                )

        return GraphNeighborsResponse(entities=entities, relationships=rels)

    async def get_community_members(self, repo_id: str, community_id: str, *, limit: int = 500) -> list[Entity]:
        lim = int(max(0, limit or 0))
        lim = min(lim, 5000)
        if not community_id.strip() or lim <= 0:
            return []

        driver = self._require_driver()
        query = """
        MATCH (c:Community {repo_id: $repo_id, community_id: $community_id})
        MATCH (e:Entity {repo_id: $repo_id})-[:IN_COMMUNITY]->(c)
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.entity_type AS entity_type,
               e.file_path AS file_path,
               e.description AS description,
               e.properties_json AS properties_json
        ORDER BY name ASC
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

        allowed_rels = ["calls", "imports", "inherits", "contains", "references", "related_to"]
        driver = self._require_driver()

        cypher = """
        MATCH (c:Community {repo_id: $repo_id, community_id: $community_id})
        MATCH (e:Entity {repo_id: $repo_id})-[:IN_COMMUNITY]->(c)
        WITH e
        ORDER BY e.name ASC
        LIMIT $limit

        WITH collect(e) AS nodes
        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b:Entity {repo_id: $repo_id})
        WHERE b IN nodes AND type(r) IN $allowed_rels
        WITH nodes, [x IN collect(DISTINCT r) WHERE x IS NOT NULL] AS rels

        RETURN
          [n IN nodes |
            {
              entity_id: n.entity_id,
              name: n.name,
              entity_type: n.entity_type,
              file_path: n.file_path,
              description: n.description,
              properties_json: n.properties_json
            }
          ] AS entities,
          [r IN rels |
            {
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties_json: r.properties_json
            }
          ] AS relationships;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                community_id=community_id,
                allowed_rels=allowed_rels,
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
        allowed: set[str] = {"calls", "imports", "inherits", "contains", "references", "related_to"}
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                if rel_type not in allowed:
                    continue
                props = {}
                if r.get("properties_json"):
                    try:
                        props = json.loads(str(r["properties_json"]))
                    except Exception:
                        props = {}
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=cast(RelationshipType, rel_type),
                        weight=weight,
                        properties=props,
                    )
                )

        if not entities:
            return None
        return GraphNeighborsResponse(entities=entities, relationships=rels)

    # Community operations
    async def detect_communities(self, repo_id: str) -> list[Community]:
        # Heuristic community detection (works without GDS): group by top-level directory.
        #
        # IMPORTANT:
        # - Code entities have file_path.
        # - Semantic KG entities (concepts) may have file_path=None but link to Chunk nodes via IN_CHUNK.
        #   We still want them to appear in communities, so we infer a "home" group from linked chunks.
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            res = await session.run(
                """
                MATCH (e:Entity {repo_id: $repo_id})
                OPTIONAL MATCH (e)-[:IN_CHUNK]->(c:Chunk {repo_id: $repo_id})
                WITH e, replace(coalesce(e.file_path, c.file_path), '\\\\', '/') AS fp
                WITH
                  e.entity_id AS entity_id,
                  CASE
                    WHEN fp IS NULL THEN '(root)'
                    WHEN fp CONTAINS '/' THEN split(fp, '/')[0]
                    ELSE '(root)'
                  END AS grp
                WITH entity_id, grp, count(*) AS n
                ORDER BY entity_id, n DESC, grp ASC
                WITH entity_id, collect({grp: grp, n: n})[0] AS best
                RETURN entity_id, best.grp AS grp;
                """,
                repo_id=repo_id,
            )
            records = await res.data()

        by_group: dict[str, list[str]] = defaultdict(list)
        for r in records:
            eid = str(r.get("entity_id") or "").strip()
            grp = str(r.get("grp") or "(root)").strip() or "(root)"
            if not eid:
                continue
            by_group[grp].append(eid)

        communities: list[Community] = []
        for group, member_ids in sorted(by_group.items(), key=lambda t: (-len(t[1]), t[0])):
            community_id = f"{repo_id}:{group}"
            communities.append(
                Community(
                    community_id=community_id,
                    name=group,
                    summary=f"Entities in '{group}'",
                    member_ids=member_ids,
                    level=0,
                )
            )

        await self._store_communities(repo_id, communities)
        return communities

    async def get_communities(self, repo_id: str, level: int | None) -> list[Community]:
        driver = self._require_driver()
        where = "WHERE c.repo_id = $repo_id"
        params: dict[str, Any] = {"repo_id": repo_id}
        if level is not None:
            where += " AND c.level = $level"
            params["level"] = int(level)

        query = f"""
        MATCH (c:Community)
        {where}
        OPTIONAL MATCH (e:Entity {{repo_id: $repo_id}})-[:IN_COMMUNITY]->(c)
        WITH c, collect(e.entity_id) AS member_ids
        RETURN c.community_id AS community_id,
               c.name AS name,
               c.summary AS summary,
               c.level AS level,
               member_ids AS member_ids;
        """
        async with driver.session(database=self.database) as session:
            res = await session.run(query, **params)
            records = await res.data()

        out: list[Community] = []
        for r in records:
            out.append(
                Community(
                    community_id=str(r["community_id"]),
                    name=str(r["name"]),
                    summary=str(r["summary"] or ""),
                    member_ids=[str(x) for x in (r.get("member_ids") or [])],
                    level=int(r.get("level") or 0),
                )
            )
        return out

    # Search
    async def graph_search(self, repo_id: str, query: str, max_hops: int, top_k: int) -> list[ChunkMatch]:
        if not query.strip() or top_k <= 0:
            return []
        driver = self._require_driver()

        # Tokenize query for deterministic matching (no LLM).
        tokens = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,63}", query)]
        # Fall back to whole-string match if we got no tokens (e.g. symbols-only queries).
        if not tokens:
            tokens = [query.strip().lower()]
        # Cap token count to keep Cypher params small and stable.
        tokens = list(dict.fromkeys(tokens))[:8]

        max_hops = int(max(0, max_hops or 0))
        allowed_rels = ["calls", "imports", "inherits", "contains", "references", "related_to"]
        # Neo4j does not allow parameterized variable-length patterns (*0..$max_hops),
        # so we safely inline the integer hop limit (validated + clamped above).
        cypher = f"""
        MATCH (seed:Entity {{repo_id: $repo_id}})
        WHERE any(tok IN $tokens WHERE toLower(seed.name) CONTAINS tok)
        MATCH p = (seed)-[rels*0..{max_hops}]-(e:Entity {{repo_id: $repo_id}})
        WHERE ALL(r IN rels WHERE type(r) IN $allowed_rels)
        WITH
          e,
          min(length(p)) AS hops,
          any(tok IN $tokens WHERE toLower(e.name) CONTAINS tok) AS direct_match
        RETURN DISTINCT
          e.entity_id AS entity_id,
          e.file_path AS file_path,
          e.properties_json AS properties_json,
          e.name AS name,
          hops AS hops,
          direct_match AS direct_match
        ORDER BY direct_match DESC, hops ASC, name ASC
        LIMIT $limit;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                tokens=tokens,
                allowed_rels=allowed_rels,
                limit=int(top_k),
            )
            records = await res.data()

        out: list[ChunkMatch] = []
        for r in records:
            fp = r.get("file_path")
            props: dict[str, Any] = {}
            if r.get("properties_json"):
                try:
                    props = json.loads(r["properties_json"])
                except Exception:
                    props = {}
            hops = int(r.get("hops") or 0)
            direct_match = bool(r.get("direct_match"))
            # Deterministic score: direct matches outrank neighbors; deeper hops decay.
            base = 1.0 if direct_match else 0.7
            score = float(base / float(1 + max(0, hops)))
            # Graph returns entity-level hits; chunk hydration happens in higher-level retriever.
            out.append(
                ChunkMatch(
                    chunk_id=str(r.get("entity_id")),
                    content=str(r.get("name") or ""),
                    file_path=str(fp) if fp is not None else "",
                    start_line=int(props.get("start_line") or 0),
                    end_line=int(props.get("end_line") or 0),
                    language=None,
                    score=score,
                    source="graph",
                    metadata={
                        "entity_id": str(r.get("entity_id")),
                        "entity_name": str(r.get("name") or ""),
                        "hops": hops,
                        "direct_match": direct_match,
                        "tokens": tokens,
                    },
                )
            )
        return out

    async def rebuild_entity_chunk_links(self, repo_id: str) -> int:
        """(Re)create Entity->Chunk links for a corpus.

        Requires:
        - Entity nodes with numeric start_line/end_line properties
        - Chunk nodes with file_path/start_line/end_line
        """
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            # Clear existing links for this corpus
            await session.run(
                """
                MATCH (e:Entity {repo_id: $repo_id})-[r:IN_CHUNK]->(c:Chunk {repo_id: $repo_id})
                WHERE e.file_path IS NOT NULL
                  AND e.start_line IS NOT NULL
                  AND e.end_line IS NOT NULL
                DELETE r;
                """,
                repo_id=repo_id,
            )
            # Rebuild deterministically by line-overlap
            res = await session.run(
                """
                MATCH (e:Entity {repo_id: $repo_id})
                WHERE e.file_path IS NOT NULL
                  AND e.start_line IS NOT NULL
                  AND e.end_line IS NOT NULL
                MATCH (c:Chunk {repo_id: $repo_id, file_path: e.file_path})
                WHERE NOT (c.end_line < e.start_line OR c.start_line > e.end_line)
                MERGE (e)-[:IN_CHUNK]->(c)
                RETURN count(*) AS n;
                """,
                repo_id=repo_id,
            )
            rec = await res.single()
        return int(rec.get("n") or 0) if rec else 0

    async def link_entities_to_chunks(self, repo_id: str, links: list[dict[str, str]]) -> int:
        """Create (Entity)-[:IN_CHUNK]->(Chunk) links in batch.

        Expects each link dict to contain:
        - entity_id
        - chunk_id
        """
        if not links:
            return 0
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            await session.run(
                """
                UNWIND $links AS l
                MATCH (e:Entity {repo_id: $repo_id, entity_id: l.entity_id})
                MATCH (c:Chunk {repo_id: $repo_id, chunk_id: l.chunk_id})
                MERGE (e)-[:IN_CHUNK]->(c);
                """,
                repo_id=repo_id,
                links=links,
            )
        return len(links)

    async def expand_chunks_via_entities(
        self,
        repo_id: str,
        seeds: list[tuple[str, float]],
        *,
        max_hops: int,
        top_k: int,
    ) -> list[tuple[str, float]]:
        """Expand from seed chunks through Entity graph and return (chunk_id, score)."""
        if not seeds or top_k <= 0:
            return []
        hops = int(max(0, max_hops or 0))
        if hops <= 0:
            return []

        driver = self._require_driver()
        payload = [{"chunk_id": cid, "score": float(score)} for cid, score in seeds if cid]
        if not payload:
            return []

        # Neo4j does not allow parameterized variable-length patterns (*0..$max_hops),
        # so we safely inline the integer hop limit (validated + clamped above).
        cypher = f"""
        UNWIND $seeds AS s
        MATCH (seed:Chunk {{repo_id: $repo_id, chunk_id: s.chunk_id}})
        WITH seed, toFloat(s.score) AS seed_score
        MATCH (seed)<-[:IN_CHUNK]-(seed_e:Entity {{repo_id: $repo_id}})
        MATCH p = (seed_e)-[rels*0..{hops}]-(e:Entity {{repo_id: $repo_id}})
        WHERE ALL(r IN rels WHERE type(r) IN $allowed_rels)
        WITH e, min(length(p)) AS hops, seed_score
        MATCH (e)-[:IN_CHUNK]->(c:Chunk {{repo_id: $repo_id}})
        WITH c.chunk_id AS chunk_id,
             max(seed_score / (1.0 + toFloat(hops))) AS score
        RETURN chunk_id AS chunk_id, score AS score
        ORDER BY score DESC
        LIMIT $limit;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                seeds=payload,
                allowed_rels=["calls", "imports", "inherits", "contains", "references", "related_to"],
                limit=int(top_k),
            )
            records = await res.data()

        out: list[tuple[str, float]] = []
        for r in records:
            cid = str(r.get("chunk_id") or "").strip()
            if not cid:
                continue
            out.append((cid, float(r.get("score") or 0.0)))
        return out

    async def entity_chunk_search(
        self, repo_id: str, query: str, max_hops: int, top_k: int
    ) -> list[tuple[str, float]]:
        """Entity-graph search that returns real chunk_ids via Entity-[:IN_CHUNK]->Chunk."""
        if not query.strip() or top_k <= 0:
            return []
        driver = self._require_driver()

        tokens = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,63}", query)]
        if not tokens:
            tokens = [query.strip().lower()]
        tokens = list(dict.fromkeys(tokens))[:8]

        max_hops = int(max(0, max_hops or 0))
        allowed_rels = ["calls", "imports", "inherits", "contains", "references", "related_to"]
        # Neo4j does not allow parameterized variable-length patterns (*0..$max_hops),
        # so we safely inline the integer hop limit (validated + clamped above).
        cypher = f"""
        MATCH (seed:Entity {{repo_id: $repo_id}})
        WHERE any(tok IN $tokens WHERE toLower(seed.name) CONTAINS tok)
        MATCH p = (seed)-[rels*0..{max_hops}]-(e:Entity {{repo_id: $repo_id}})
        WHERE ALL(r IN rels WHERE type(r) IN $allowed_rels)
        WITH
          e,
          min(length(p)) AS hops,
          any(tok IN $tokens WHERE toLower(e.name) CONTAINS tok) AS direct_match
        WITH
          e,
          hops,
          direct_match,
          (CASE WHEN direct_match THEN 1.0 ELSE 0.7 END) / (1.0 + toFloat(hops)) AS entity_score
        MATCH (e)-[:IN_CHUNK]->(c:Chunk {{repo_id: $repo_id}})
        RETURN c.chunk_id AS chunk_id,
               max(entity_score) AS score
        ORDER BY score DESC
        LIMIT $limit;
        """

        async with driver.session(database=self.database) as session:
            res = await session.run(
                cypher,
                repo_id=repo_id,
                tokens=tokens,
                allowed_rels=allowed_rels,
                limit=int(top_k),
            )
            records = await res.data()

        out: list[tuple[str, float]] = []
        for r in records:
            cid = str(r.get("chunk_id") or "").strip()
            if not cid:
                continue
            out.append((cid, float(r.get("score") or 0.0)))
        return out

    async def execute_cypher(self, query: str, params: dict[str, Any] | None) -> list[dict[str, Any]]:
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
                OPTIONAL MATCH (e:Entity {repo_id: $repo_id})
                WITH count(e) AS total_entities
                OPTIONAL MATCH (:Entity {repo_id: $repo_id})-[r]->(:Entity {repo_id: $repo_id})
                WITH total_entities, count(r) AS total_relationships
                OPTIONAL MATCH (c:Community {repo_id: $repo_id})
                WITH total_entities, total_relationships, count(c) AS total_communities
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
                MATCH (e:Entity {repo_id: $repo_id})
                RETURN e.entity_type AS t, count(e) AS n;
                """,
                repo_id=repo_id,
            )
            entity_rows = await entity_breakdown_res.data()

            rel_breakdown_res = await session.run(
                """
                MATCH (:Entity {repo_id: $repo_id})-[r]->(:Entity {repo_id: $repo_id})
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

    async def delete_graph(self, repo_id: str) -> None:
        """Delete all graph data (entities, rels, communities) for a corpus."""
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            await session.run("MATCH (n {repo_id: $repo_id}) DETACH DELETE n;", repo_id=repo_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _require_driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4j driver is not connected. Call connect() first.")
        return self._driver

    async def _store_communities(self, repo_id: str, communities: Iterable[Community]) -> None:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            # Clear existing communities + membership edges
            await session.run(
                """
                MATCH (c:Community {repo_id: $repo_id})
                DETACH DELETE c;
                """,
                repo_id=repo_id,
            )

            comm_payload = [
                {
                    "community_id": c.community_id,
                    "name": c.name,
                    "summary": c.summary,
                    "level": int(c.level),
                    "member_ids": list(c.member_ids),
                }
                for c in communities
            ]

            await session.run(
                """
                UNWIND $communities AS c
                MERGE (comm:Community {repo_id: $repo_id, community_id: c.community_id})
                SET comm.name = c.name,
                    comm.summary = c.summary,
                    comm.level = c.level;
                """,
                repo_id=repo_id,
                communities=comm_payload,
            )

            await session.run(
                """
                UNWIND $communities AS c
                MATCH (comm:Community {repo_id: $repo_id, community_id: c.community_id})
                UNWIND c.member_ids AS mid
                MATCH (e:Entity {repo_id: $repo_id, entity_id: mid})
                MERGE (e)-[:IN_COMMUNITY]->(comm);
                """,
                repo_id=repo_id,
                communities=comm_payload,
            )


def _entity_from_record(record: Any) -> Entity:
    props = {}
    if record.get("properties_json"):
        try:
            props = json.loads(record["properties_json"])
        except Exception:
            props = {}
    return Entity(
        entity_id=str(record["entity_id"]),
        name=str(record["name"]),
        entity_type=_coerce_entity_type(str(record["entity_type"])),
        file_path=str(record["file_path"]) if record.get("file_path") is not None else None,
        description=str(record["description"]) if record.get("description") is not None else None,
        properties=props,
    )


def _entity_from_mapping(mapping: dict[str, Any]) -> Entity:
    props = {}
    if mapping.get("properties_json"):
        try:
            props = json.loads(mapping["properties_json"])
        except Exception:
            props = {}
    return Entity(
        entity_id=str(mapping["entity_id"]),
        name=str(mapping["name"]),
        entity_type=_coerce_entity_type(str(mapping["entity_type"])),
        file_path=str(mapping["file_path"]) if mapping.get("file_path") is not None else None,
        description=str(mapping["description"]) if mapping.get("description") is not None else None,
        properties=props,
    )


def _coerce_entity_type(value: str) -> EntityType:
    allowed: set[str] = {"function", "class", "module", "variable", "concept"}
    if value in allowed:
        return cast(EntityType, value)
    return "concept"


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


def _sanitize_cypher_identifier(name: str) -> str:
    """Conservative Cypher identifier sanitizer (labels, properties, index names).

    Neo4j allows more via backticks, but we intentionally restrict to a safe subset
    since these identifiers can be config-driven.
    """
    raw = (name or "").strip()
    raw = re.sub(r"[^A-Za-z0-9_]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_")
    if not raw:
        return ""
    if raw[0].isdigit():
        raw = f"x_{raw}"
    return raw[:63]
