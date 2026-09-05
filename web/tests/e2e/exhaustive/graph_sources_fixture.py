"""Real store fixture for source pagination UI; never indexes or calls a model."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx

from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import build_generation
from server.models.index import Chunk
from tests.service_requirements import postgres_dsn_from_env, require_env


async def main() -> None:
    operation, api_base = sys.argv[1:3]
    fixture = json.loads(sys.argv[3]) if len(sys.argv) > 3 else None
    dsn = postgres_dsn_from_env()
    if not dsn:
        raise RuntimeError("Postgres is not configured for the graph source browser fixture")
    pg = PostgresClient(dsn)
    neo = Neo4jClient(require_env("NEO4J_URI"), require_env("NEO4J_USER"), require_env("NEO4J_PASSWORD"))
    await pg.connect()
    await neo.connect()
    try:
        if operation == "create":
            corpus = f"pytest_graph_sources_ui_{uuid4().hex[:8]}"
            run = uuid4().hex
            graph = f"__staging__{corpus}__{run}"
            root = Path(tempfile.mkdtemp(prefix="ragweld-graph-sources-"))
            lines = [f"Fuel tank inspection record {i}: pressure stable." for i in range(1, 27)]
            (root / "tank.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            async with httpx.AsyncClient() as client:
                created = await client.post(f"{api_base}/corpora", json={"corpus_id": corpus, "name": corpus, "path": str(root)})
                created.raise_for_status()
            fixture = {"corpus": corpus, "graph": graph, "run": run, "root": str(root), "entity": "merged/tank::1"}
            chunks = [Chunk(chunk_id=f"source-{i:02}", file_path="tank.md", start_line=i, end_line=i, content=line)
                      for i, line in enumerate(lines, 1)]
            await pg.upsert_chunks(corpus, chunks)
            await pg.set_generation(corpus, build_generation(run_id=run, qdrant_collection=None, graph_repo_id=graph))
            async with neo._require_driver().session(database=neo.database) as session:
                await session.run(
                    "CREATE (e:__Entity__ {repo_id: $repo, run_id: $run, entity_id: $entity, name: 'Fuel tank', entity_type: 'Tank'}) "
                    "WITH e UNWIND $chunks AS row "
                    "CREATE (c:Chunk {repo_id: $repo, run_id: $run, chunk_id: row.chunk_id, file_path: row.file_path, "
                    "start_line: row.start_line, end_line: row.end_line, text: row.content}) "
                    "CREATE (e)-[:FROM_CHUNK {repo_id: $repo, run_id: $run}]->(c)",
                    repo=graph, run=run, entity=fixture["entity"],
                    chunks=[chunk.model_dump(include={"chunk_id", "file_path", "start_line", "end_line", "content"}) for chunk in chunks],
                )
            print(json.dumps(fixture))
        elif operation == "advance":
            assert fixture is not None
            await pg.set_generation(fixture["corpus"], build_generation(run_id=uuid4().hex, qdrant_collection=None, graph_repo_id=fixture["graph"]))
        elif operation == "delete":
            assert fixture is not None
            await neo.delete_graph(fixture["graph"])
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.delete(f"{api_base}/corpora/{fixture['corpus']}")
                response.raise_for_status()
            root = Path(fixture["root"])
            if root.name.startswith("ragweld-graph-sources-"):
                shutil.rmtree(root)
        else:
            raise ValueError("Unknown fixture operation")
    finally:
        await neo.disconnect()
        await pg.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
