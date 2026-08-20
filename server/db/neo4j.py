from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j_graphrag.experimental.components.types import LexicalGraphConfig, Neo4jGraph

from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.models.index import Chunk
from server.models.retrieval import ChunkMatch

EntityType = Literal["function", "class", "module", "variable", "concept", "person", "org", "location", "event"]
RelationshipType = Literal[
    "calls",
    "imports",
    "inherits",
    "contains",
    "associated_with",
    "met_with",
    "communicated_with",
    "works_for",
    "member_of",
    "founded",
    "owns",
    "funded",
    "participated_in",
    "located_in",
    "references",
    "related_to",
]

CODE_RELATION_TYPES: set[str] = {"calls", "imports", "inherits", "contains"}
SEMANTIC_RELATION_TYPES: set[str] = {
    "associated_with",
    "met_with",
    "communicated_with",
    "works_for",
    "member_of",
    "founded",
    "owns",
    "funded",
    "participated_in",
    "located_in",
    "references",
    "related_to",
}
ALL_RELATION_TYPES: set[str] = CODE_RELATION_TYPES | SEMANTIC_RELATION_TYPES

_BATCH_SIZE_DEFAULT = 500
_DEFAULT_REPO_SCOPED_NODE_LABELS: tuple[str, ...] = ("Document", "Chunk", "__Entity__", "Community")


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
            res = await session.run("CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition LIMIT 1;")
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

    async def ensure_schema(self) -> None:
        """Ensure identity constraints used by MERGE paths exist."""
        driver = self._require_driver()
        statements = [
            (
                "CREATE CONSTRAINT rw_document_repo_file IF NOT EXISTS "
                "FOR (d:Document) REQUIRE (d.repo_id, d.file_path) IS UNIQUE;"
            ),
            (
                "CREATE CONSTRAINT rw_chunk_repo_chunk IF NOT EXISTS "
                "FOR (c:Chunk) REQUIRE (c.repo_id, c.chunk_id) IS UNIQUE;"
            ),
            (
                "CREATE CONSTRAINT rw_entity_repo_entity IF NOT EXISTS "
                "FOR (e:__Entity__) REQUIRE (e.repo_id, e.entity_id) IS UNIQUE;"
            ),
            (
                "CREATE CONSTRAINT rw_community_repo_community IF NOT EXISTS "
                "FOR (c:Community) REQUIRE (c.repo_id, c.community_id) IS UNIQUE;"
            ),
        ]
        async with driver.session(database=self.database) as session:
            for stmt in statements:
                await session.run(stmt)

    async def _get_server_version(self) -> str:
        if self._server_version:
            return self._server_version
        info = await self.ping()
        versions = info.get("versions") if isinstance(info, dict) else None
        if isinstance(versions, list) and versions:
            self._server_version = str(versions[0] or "").strip()
        else:
            self._server_version = ""
        return self._server_version or ""

    async def _supports_search_clause_vector(self) -> bool:
        """Best-effort capability gate for SEARCH-clause vector querying."""
        version = await self._get_server_version()
        if not version:
            return False
        # Current runtime pin is 5.x; SEARCH support is expected in newer tracks.
        if version.startswith("2026.") or version.startswith("6."):
            return True
        return False

    async def _resolve_vector_query_mode(self, mode: str) -> str:
        normalized = str(mode or "auto").strip().lower()
        if normalized == "auto":
            if await self._supports_search_clause_vector():
                return "search"
            return "procedure"
        if normalized in {"procedure", "search"}:
            return normalized
        return "procedure"

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
                rec = None
                try:
                    res = await session.run(
                        "SHOW VECTOR INDEXES YIELD name, state WHERE name = $name RETURN state AS state LIMIT 1;",
                        name=idx,
                    )
                    rec = await res.single()
                except Exception:
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

    async def upsert_graphrag_graph(
        self,
        repo_id: str,
        graph: Neo4jGraph,
        *,
        lexical_graph_config: LexicalGraphConfig,
    ) -> None:
        if not graph.nodes and not graph.relationships:
            return
        await self._upsert_graphrag_nodes(repo_id, graph, lexical_graph_config=lexical_graph_config)
        await self._upsert_graphrag_relationships(repo_id, graph, lexical_graph_config=lexical_graph_config)

    async def _upsert_graphrag_nodes(
        self,
        repo_id: str,
        graph: Neo4jGraph,
        *,
        lexical_graph_config: LexicalGraphConfig,
    ) -> None:
        driver = self._require_driver()
        document_label = _sanitize_cypher_identifier(lexical_graph_config.document_node_label)
        chunk_label = _sanitize_cypher_identifier(lexical_graph_config.chunk_node_label)
        chunk_embedding_property = _sanitize_cypher_identifier(lexical_graph_config.chunk_embedding_property)
        if not document_label or not chunk_label or not chunk_embedding_property:
            raise ValueError("Invalid GraphRAG lexical graph configuration")

        document_rows: list[dict[str, Any]] = []
        chunk_rows: list[dict[str, Any]] = []
        entity_rows_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)

        lexical_labels = set(lexical_graph_config.lexical_graph_node_labels)
        for node in graph.nodes:
            label = str(node.label or "").strip()
            props = dict(node.properties or {})
            if label == lexical_graph_config.document_node_label:
                file_path = str(props.get("file_path") or props.get("path") or "").strip()
                if not file_path:
                    continue
                document_rows.append(
                    {
                        "document_id": str(props.get("document_id") or node.id),
                        "file_path": file_path,
                        "properties": props,
                    }
                )
                continue
            if label == lexical_graph_config.chunk_node_label:
                chunk_rows.append(
                    {
                        "chunk_id": str(props.get("chunk_id") or node.id),
                        "properties": props,
                        "embedding": dict(node.embedding_properties or {}).get(
                            lexical_graph_config.chunk_embedding_property
                        ),
                    }
                )
                continue
            if label in lexical_labels:
                continue
            entity_label = _sanitize_cypher_identifier(label)
            if not entity_label:
                continue
            entity_rows_by_label[entity_label].append(
                {
                    "entity_id": str(props.get("entity_id") or node.id),
                    "entity_type": str(props.get("entity_type") or label).strip(),
                    "properties": props,
                }
            )

        async with driver.session(database=self.database) as session:
            if document_rows:
                query = f"""
                UNWIND $rows AS row
                MERGE (d:`{document_label}` {{repo_id: $repo_id, file_path: row.file_path}})
                SET d += row.properties,
                    d.repo_id = $repo_id,
                    d.file_path = row.file_path,
                    d.document_id = row.document_id;
                """
                for batch in _iter_batches(document_rows):
                    await session.run(query, repo_id=repo_id, rows=batch)

            if chunk_rows:
                query = f"""
                UNWIND $rows AS row
                MERGE (c:`{chunk_label}` {{repo_id: $repo_id, chunk_id: row.chunk_id}})
                SET c += row.properties,
                    c.repo_id = $repo_id,
                    c.chunk_id = row.chunk_id
                FOREACH (_ IN CASE WHEN row.embedding IS NOT NULL THEN [1] ELSE [] END |
                    SET c.`{chunk_embedding_property}` = row.embedding
                );
                """
                for batch in _iter_batches(chunk_rows):
                    await session.run(query, repo_id=repo_id, rows=batch)

            for entity_label, rows in entity_rows_by_label.items():
                query = f"""
                UNWIND $rows AS row
                MERGE (e:__Entity__:`{entity_label}` {{repo_id: $repo_id, entity_id: row.entity_id}})
                SET e += row.properties,
                    e.repo_id = $repo_id,
                    e.entity_id = row.entity_id,
                    e.entity_type = row.entity_type;
                """
                for batch in _iter_batches(rows):
                    await session.run(query, repo_id=repo_id, rows=batch)

    async def _upsert_graphrag_relationships(
        self,
        repo_id: str,
        graph: Neo4jGraph,
        *,
        lexical_graph_config: LexicalGraphConfig,
    ) -> None:
        if not graph.relationships:
            return
        driver = self._require_driver()
        document_label = _sanitize_cypher_identifier(lexical_graph_config.document_node_label)
        chunk_label = _sanitize_cypher_identifier(lexical_graph_config.chunk_node_label)
        if not document_label or not chunk_label:
            raise ValueError("Invalid GraphRAG lexical graph configuration")

        rel_rows_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for rel in graph.relationships:
            rel_type = _sanitize_cypher_identifier(str(rel.type or ""))
            if not rel_type:
                continue
            rel_rows_by_type[rel_type].append(
                {
                    "start_node_id": str(rel.start_node_id),
                    "end_node_id": str(rel.end_node_id),
                    "properties": dict(rel.properties or {}),
                }
            )

        async with driver.session(database=self.database) as session:
            for rel_type, rows in rel_rows_by_type.items():
                if rel_type == _sanitize_cypher_identifier(lexical_graph_config.chunk_to_document_relationship_type):
                    query = f"""
                    UNWIND $rows AS row
                    MATCH (c:`{chunk_label}` {{repo_id: $repo_id, chunk_id: row.start_node_id}})
                    MATCH (d:`{document_label}` {{repo_id: $repo_id, document_id: row.end_node_id}})
                    MERGE (c)-[rel:`{rel_type}`]->(d)
                    SET rel += row.properties;
                    """
                elif rel_type == _sanitize_cypher_identifier(lexical_graph_config.next_chunk_relationship_type):
                    query = f"""
                    UNWIND $rows AS row
                    MATCH (a:`{chunk_label}` {{repo_id: $repo_id, chunk_id: row.start_node_id}})
                    MATCH (b:`{chunk_label}` {{repo_id: $repo_id, chunk_id: row.end_node_id}})
                    MERGE (a)-[rel:`{rel_type}`]->(b)
                    SET rel += row.properties;
                    """
                elif rel_type == _sanitize_cypher_identifier(lexical_graph_config.node_to_chunk_relationship_type):
                    query = f"""
                    UNWIND $rows AS row
                    MATCH (e:__Entity__ {{repo_id: $repo_id, entity_id: row.start_node_id}})
                    MATCH (c:`{chunk_label}` {{repo_id: $repo_id, chunk_id: row.end_node_id}})
                    MERGE (e)-[rel:`{rel_type}`]->(c)
                    SET rel += row.properties;
                    """
                else:
                    query = f"""
                    UNWIND $rows AS row
                    MATCH (a:__Entity__ {{repo_id: $repo_id, entity_id: row.start_node_id}})
                    MATCH (b:__Entity__ {{repo_id: $repo_id, entity_id: row.end_node_id}})
                    MERGE (a)-[rel:`{rel_type}`]->(b)
                    SET rel += row.properties;
                    """
                for batch in _iter_batches(rows):
                    await session.run(query, repo_id=repo_id, rows=batch)

    async def chunk_vector_search(
        self,
        repo_id: str,
        embedding: list[float],
        *,
        index_name: str,
        top_k: int,
        neighbor_window: int = 0,
        overfetch_multiplier: int = 1,
        query_mode: str = "auto",
    ) -> list[tuple[str, float]]:
        """Vector search over Chunk nodes in Neo4j; returns (chunk_id, score)."""
        if not embedding or top_k <= 0:
            return []

        driver = self._require_driver()
        resolved_mode = await self._resolve_vector_query_mode(query_mode)
        seed_k = max(1, int(top_k) * max(1, int(overfetch_multiplier)))
        window = max(0, int(neighbor_window))

        # On the pinned runtime, procedure mode is the authoritative implementation.
        # SEARCH mode is version-gated and currently falls back to procedure querying.
        _ = resolved_mode

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
        MERGE (n:__Entity__ {repo_id: $repo_id, entity_id: e.entity_id})
        SET n.name = e.name,
            n.entity_type = e.entity_type,
            n.file_path = e.file_path,
            n.description = e.description,
            n.properties_json = e.properties_json,
            n.start_line = e.start_line,
            n.end_line = e.end_line;
        """

        async with driver.session(database=self.database) as session:
            for batch in _iter_batches(payload):
                await session.run(query, repo_id=repo_id, entities=batch)
        return len(entities)

    async def get_entity(self, entity_id: str) -> Entity | None:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            row = await session.run(
                """
                MATCH (n:__Entity__ {entity_id: $entity_id})
                RETURN n.repo_id AS repo_id,
                       n.entity_id AS entity_id,
                       n.name AS name,
                       n.entity_type AS entity_type,
                       n.file_path AS file_path,
                       n.description AS description,
                       properties(n) AS properties
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
            q = re.sub(r"[_-]+", " ", q)
            q = re.sub(r"\s+", " ", q).strip()
            where += (
                " AND (toLower(n.name) CONTAINS $q "
                "OR toLower(replace(replace(n.name, '_', ' '), '-', ' ')) CONTAINS $q)"
            )
            params["q"] = q
        query = f"""
        MATCH (n:__Entity__)
        {where}
        RETURN n.repo_id AS repo_id,
               n.entity_id AS entity_id,
               n.name AS name,
               n.entity_type AS entity_type,
               n.file_path AS file_path,
               n.description AS description,
               properties(n) AS properties
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
                MATCH (n:__Entity__ {repo_id: $repo_id})
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

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rels:
            rel_type = str(r.relation_type)
            if rel_type not in ALL_RELATION_TYPES:
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
                MATCH (a:__Entity__ {{repo_id: $repo_id, entity_id: r.source_id}})
                MATCH (b:__Entity__ {{repo_id: $repo_id, entity_id: r.target_id}})
                MERGE (a)-[rel:{rel_type}]->(b)
                SET rel.weight = r.weight,
                    rel.properties_json = r.properties_json;
                """
                for batch in _iter_batches(payload):
                    await session.run(query, repo_id=repo_id, rels=batch)
        return sum(len(v) for v in grouped.values())

    async def get_relationships(self, entity_id: str) -> list[Relationship]:
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            res = await session.run(
                """
                MATCH (a:__Entity__ {entity_id: $entity_id})-[r]->(b:__Entity__)
                RETURN a.entity_id AS source_id,
                       b.entity_id AS target_id,
                       type(r) AS relation_type,
                       coalesce(r.weight, 1.0) AS weight,
                       properties(r) AS properties;
                """,
                entity_id=entity_id,
            )
            records = await res.data()
        out: list[Relationship] = []
        allowed: set[str] = set(ALL_RELATION_TYPES)
        for r in records:
            rel_type = str(r.get("relation_type") or "")
            if rel_type not in allowed:
                continue
            out.append(
                Relationship(
                    source_id=str(r["source_id"]),
                    target_id=str(r["target_id"]),
                    relation_type=cast(RelationshipType, rel_type),
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

        allowed_rels = sorted(ALL_RELATION_TYPES)
        driver = self._require_driver()

        cypher = f"""
        MATCH (center:__Entity__ {{repo_id: $repo_id, entity_id: $entity_id}})

        OPTIONAL MATCH p = (center)-[rels*1..{hops}]-(n:__Entity__ {{repo_id: $repo_id}})
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
        allowed: set[str] = set(ALL_RELATION_TYPES)
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                if rel_type not in allowed:
                    continue
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=cast(RelationshipType, rel_type),
                        weight=weight,
                        properties=_relationship_properties_from_mapping(r),
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
        MATCH (e:__Entity__ {repo_id: $repo_id})-[:IN_COMMUNITY]->(c)
        RETURN e.entity_id AS entity_id,
               e.name AS name,
               e.entity_type AS entity_type,
               e.file_path AS file_path,
               e.description AS description,
               properties(e) AS properties
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

        allowed_rels = sorted(ALL_RELATION_TYPES)
        driver = self._require_driver()

        cypher = """
        MATCH (c:Community {repo_id: $repo_id, community_id: $community_id})
        MATCH (e:__Entity__ {repo_id: $repo_id})-[:IN_COMMUNITY]->(c)
        WITH e
        ORDER BY e.name ASC
        LIMIT $limit

        WITH collect(e) AS nodes
        UNWIND nodes AS a
        OPTIONAL MATCH (a)-[r]-(b:__Entity__ {repo_id: $repo_id})
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
              properties: properties(n)
            }
          ] AS entities,
          [r IN rels |
            {
              source_id: startNode(r).entity_id,
              target_id: endNode(r).entity_id,
              relation_type: type(r),
              weight: coalesce(r.weight, 1.0),
              properties: properties(r)
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
        allowed: set[str] = set(ALL_RELATION_TYPES)
        if isinstance(relationships_raw, list):
            for r in relationships_raw:
                if not isinstance(r, dict):
                    continue
                rel_type = str(r.get("relation_type") or "")
                if rel_type not in allowed:
                    continue
                raw_weight = float(r.get("weight") or 1.0)
                weight = max(0.0, min(1.0, raw_weight))
                rels.append(
                    Relationship(
                        source_id=str(r.get("source_id") or ""),
                        target_id=str(r.get("target_id") or ""),
                        relation_type=cast(RelationshipType, rel_type),
                        weight=weight,
                        properties=_relationship_properties_from_mapping(r),
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
                MATCH (e:__Entity__ {repo_id: $repo_id})
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
        OPTIONAL MATCH (e:__Entity__ {{repo_id: $repo_id}})-[:IN_COMMUNITY]->(c)
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
        allowed_rels = sorted(ALL_RELATION_TYPES)
        # Neo4j does not allow parameterized variable-length patterns (*0..$max_hops),
        # so we safely inline the integer hop limit (validated + clamped above).
        cypher = f"""
        MATCH (seed:__Entity__ {{repo_id: $repo_id}})
        WHERE any(tok IN $tokens WHERE toLower(seed.name) CONTAINS tok)
        MATCH p = (seed)-[rels*0..{max_hops}]-(e:__Entity__ {{repo_id: $repo_id}})
        WHERE ALL(r IN rels WHERE type(r) IN $allowed_rels)
        WITH
          e,
          min(length(p)) AS hops,
          any(tok IN $tokens WHERE toLower(e.name) CONTAINS tok) AS direct_match
        RETURN DISTINCT
          e.entity_id AS entity_id,
          e.file_path AS file_path,
          properties(e) AS properties,
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
            props = _entity_properties_from_mapping(r)
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
                MATCH (e:__Entity__ {repo_id: $repo_id})-[r:IN_CHUNK]->(c:Chunk {repo_id: $repo_id})
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
                MATCH (e:__Entity__ {repo_id: $repo_id})
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
            for batch in _iter_batches(links):
                await session.run(
                    """
                    UNWIND $links AS l
                    MATCH (e:__Entity__ {repo_id: $repo_id, entity_id: l.entity_id})
                    MATCH (c:Chunk {repo_id: $repo_id, chunk_id: l.chunk_id})
                    MERGE (e)-[:IN_CHUNK]->(c);
                    """,
                    repo_id=repo_id,
                    links=batch,
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
        MATCH (seed)<-[:IN_CHUNK]-(seed_e:__Entity__ {{repo_id: $repo_id}})
        MATCH p = (seed_e)-[rels*0..{hops}]-(e:__Entity__ {{repo_id: $repo_id}})
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
                allowed_rels=sorted(ALL_RELATION_TYPES),
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
        allowed_rels = sorted(ALL_RELATION_TYPES)
        # Neo4j does not allow parameterized variable-length patterns (*0..$max_hops),
        # so we safely inline the integer hop limit (validated + clamped above).
        cypher = f"""
        MATCH (seed:__Entity__ {{repo_id: $repo_id}})
        WHERE any(tok IN $tokens WHERE toLower(seed.name) CONTAINS tok)
        MATCH p = (seed)-[rels*0..{max_hops}]-(e:__Entity__ {{repo_id: $repo_id}})
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
                OPTIONAL MATCH (e:__Entity__ {repo_id: $repo_id})
                WITH count(e) AS total_entities
                OPTIONAL MATCH (:__Entity__ {repo_id: $repo_id})-[r]->(:__Entity__ {repo_id: $repo_id})
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

    async def promote_repo_graph(self, *, active_repo_id: str, staging_repo_id: str) -> None:
        """Promote a staged graph to active by repo_id swap using bounded batches.

        Large corpora can exceed Neo4j transaction memory limits when deleting or
        updating all nodes in one statement. Run bounded batches to keep memory
        usage predictable during promotion.
        """
        driver = self._require_driver()
        async with driver.session(database=self.database) as session:
            batch_size = int(_BATCH_SIZE_DEFAULT * 10)
            labels = await self._resolve_repo_scoped_labels(session)
            for label in labels:
                while True:
                    res = await session.run(
                        f"""
                        MATCH (n:{label} {{repo_id: $active_repo_id}})
                        WITH n LIMIT $batch_size
                        DETACH DELETE n
                        RETURN count(*) AS n;
                        """,
                        active_repo_id=active_repo_id,
                        batch_size=batch_size,
                    )
                    rec = await res.single()
                    deleted = int(rec.get("n") or 0) if rec else 0
                    if deleted <= 0:
                        break

                while True:
                    res = await session.run(
                        f"""
                        MATCH (n:{label} {{repo_id: $staging_repo_id}})
                        WITH n LIMIT $batch_size
                        SET n.repo_id = $active_repo_id
                        RETURN count(*) AS n;
                        """,
                        staging_repo_id=staging_repo_id,
                        active_repo_id=active_repo_id,
                        batch_size=batch_size,
                    )
                    rec = await res.single()
                    moved = int(rec.get("n") or 0) if rec else 0
                    if moved <= 0:
                        break

            # Safety sweep for legacy/unlabeled nodes.
            while True:
                res = await session.run(
                    """
                    MATCH (n {repo_id: $active_repo_id})
                    WHERE none(lbl IN labels(n) WHERE lbl IN $known_labels)
                    WITH n LIMIT $batch_size
                    DETACH DELETE n
                    RETURN count(*) AS n;
                    """,
                    active_repo_id=active_repo_id,
                    known_labels=labels,
                    batch_size=batch_size,
                )
                rec = await res.single()
                deleted = int(rec.get("n") or 0) if rec else 0
                if deleted <= 0:
                    break

            while True:
                res = await session.run(
                    """
                    MATCH (n {repo_id: $staging_repo_id})
                    WHERE none(lbl IN labels(n) WHERE lbl IN $known_labels)
                    WITH n LIMIT $batch_size
                    SET n.repo_id = $active_repo_id
                    RETURN count(*) AS n;
                    """,
                    staging_repo_id=staging_repo_id,
                    active_repo_id=active_repo_id,
                    known_labels=labels,
                    batch_size=batch_size,
                )
                rec = await res.single()
                moved = int(rec.get("n") or 0) if rec else 0
                if moved <= 0:
                    break

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
                MATCH (e:__Entity__ {repo_id: $repo_id, entity_id: mid})
                MERGE (e)-[:IN_COMMUNITY]->(comm);
                """,
                repo_id=repo_id,
                communities=comm_payload,
            )


def _entity_from_record(record: Any) -> Entity:
    props = _entity_properties_from_mapping(record)
    return Entity(
        entity_id=str(record["entity_id"]),
        name=str(record["name"]),
        entity_type=_coerce_entity_type(str(record["entity_type"])),
        file_path=str(record["file_path"]) if record.get("file_path") is not None else None,
        description=str(record["description"]) if record.get("description") is not None else None,
        properties=props,
    )


def _entity_from_mapping(mapping: dict[str, Any]) -> Entity:
    props = _entity_properties_from_mapping(mapping)
    return Entity(
        entity_id=str(mapping["entity_id"]),
        name=str(mapping["name"]),
        entity_type=_coerce_entity_type(str(mapping["entity_type"])),
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
            return json.loads(mapping["properties_json"])
        except Exception:
            return {}
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
            return json.loads(mapping["properties_json"])
        except Exception:
            return {}
    return {}


def _coerce_entity_type(value: str) -> EntityType:
    allowed: set[str] = {"function", "class", "module", "variable", "concept", "person", "org", "location", "event"}
    if value in allowed:
        return cast(EntityType, value)
    return "concept"


_T = TypeVar("_T")


def _iter_batches(items: list[_T], batch_size: int = _BATCH_SIZE_DEFAULT) -> Iterable[list[_T]]:
    size = max(1, int(batch_size or _BATCH_SIZE_DEFAULT))
    for i in range(0, len(items), size):
        yield items[i : i + size]


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
