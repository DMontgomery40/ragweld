"""Private real-app/real-store response scheduler for Graph browser regressions.

It holds complete responses from the actual API, then forwards their original ASGI messages
byte-for-byte. One registry-only fault mode captures the complete real response before raising so
Uvicorn exposes an actual server failure. It never manufactures browser response payloads.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class HoldRequest(BaseModel):
    path: str
    query: str | None = None


class RemoveRequest(BaseModel):
    corpus: str
    entity: str


@dataclass
class HeldResponse:
    rule: HoldRequest
    fail_before_forward: bool = False
    wait_before_failure: bool = False
    release: asyncio.Event = field(default_factory=asyncio.Event)
    captured: bool = False
    claimed: bool = False
    delivered: bool = False
    faulted: bool = False
    status: int | None = None
    sha256: str | None = None


def preflight() -> None:
    if platform.system() != "Linux":
        raise RuntimeError("Graph browser fixtures execute on LXC only")
    dsn = os.environ["RAGWELD_GRAPH_ORDERING_TEST_DSN"]
    database = urlsplit(dsn)
    neo4j = os.environ["RAGWELD_GRAPH_ORDERING_TEST_NEO4J_URI"]
    if (database.hostname, database.port, database.path) != ("127.0.0.1", 55439, "/astra_graph_ordering"):
        raise RuntimeError("Only the dedicated disposable graph-ordering database is allowed")
    if neo4j != "bolt://127.0.0.1:57689":
        raise RuntimeError("Only the explicitly bound disposable Neo4j is allowed")
    cfg = json.loads(Path(os.environ["RAGWELD_CONFIG_PATH"]).read_text())
    if cfg["indexing"]["postgres_url"] != dsn or cfg["graph_storage"]["neo4j_uri"] != neo4j:
        raise RuntimeError("API config and explicit fixture store bindings must match")
    if os.environ.get("RAGWELD_LOAD_DOTENV") != "0":
        raise RuntimeError("Fixture may not discover runtime.env or .env")


class GraphOrderingApp:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.holds: dict[str, HeldResponse] = {}
        self.corpora: dict[str, str] = {}
        self.reserved_corpora: set[str] = set()

    def owned_corpus_ids(self) -> set[str]:
        return set(self.corpora) | self.reserved_corpora

    async def stores(self):
        from server.db.neo4j import Neo4jClient
        from server.db.postgres import PostgresClient

        pg = PostgresClient(os.environ["RAGWELD_GRAPH_ORDERING_TEST_DSN"])
        neo = Neo4jClient(os.environ["RAGWELD_GRAPH_ORDERING_TEST_NEO4J_URI"],
                          os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
        await pg.connect()
        await neo.connect()
        return pg, neo

    async def seed(self) -> list[str]:
        from server.indexing.generations import build_generation

        pg, neo = await self.stores()
        result = []
        try:
            for suffix in ("a", "b"):
                corpus = f"pytest_graph_ordering_{uuid4().hex}_{suffix}"
                run = uuid4().hex
                graph = f"__staging__{corpus}__{run}"
                await pg.upsert_corpus(corpus, corpus, tempfile.gettempdir())
                self.corpora[corpus] = graph
                await pg.set_generation(corpus, build_generation(run_id=run, qdrant_collection=None, graph_repo_id=graph))
                rows = ([
                    {"id": "harvard", "name": "Harvard Test Observatory", "type": "Organization", "community": 0},
                    {"id": "memo", "name": "Beacon calibration memo", "type": "Document", "community": 0},
                    {"id": "mira", "name": "Mira Chen", "type": "Person", "community": 1},
                ] if suffix == "a" else [
                    {"id": "orion", "name": "Orion research institute", "type": "Organization", "community": 2},
                ])
                async with neo._require_driver().session(database=neo.database) as session:
                    await (await session.run(
                        "UNWIND $rows AS row CREATE (:__Entity__ {repo_id:$graph, run_id:$run, "
                        "entity_id:row.id, name:row.name, entity_type:row.type, communityId:row.community, communityPath:[row.community]})",
                        rows=rows, graph=graph, run=run,
                    )).consume()
                    if suffix == "a":
                        await (await session.run(
                            "MATCH (a:__Entity__ {repo_id:$graph,entity_id:'mira'}), "
                            "(b:__Entity__ {repo_id:$graph,entity_id:'harvard'}), "
                            "(c:__Entity__ {repo_id:$graph,entity_id:'memo'}) "
                            "CREATE (a)-[:MEMBER_OF {repo_id:$graph,run_id:$run}]->(b), "
                            "(a)-[:AUTHORED {repo_id:$graph,run_id:$run}]->(c)", graph=graph, run=run,
                        )).consume()
                result.append(corpus)
        finally:
            await neo.disconnect()
            await pg.disconnect()
        return result

    async def control(self, request: Request) -> JSONResponse:
        operation = request.url.path.removeprefix("/__graph_fixture__/")
        if operation == "ready" and request.method == "GET":
            return JSONResponse({"fixture": "real-graph-ordering"})
        if operation == "seed" and request.method == "POST":
            return JSONResponse({"corpora": await self.seed()})
        if operation == "reserve-corpus" and request.method == "POST":
            corpus = f"pytest_graph_ordering_{uuid4().hex}_created"
            self.reserved_corpora.add(corpus)
            return JSONResponse({"corpus": corpus, "path": tempfile.gettempdir()})
        if operation == "remove-entity" and request.method == "POST":
            target = RemoveRequest.model_validate(await request.json())
            if target.corpus not in self.corpora:
                return JSONResponse({"error": "Only owned fixture entities may be removed"}, status_code=400)
            pg, neo = await self.stores()
            try:
                async with neo._require_driver().session(database=neo.database) as session:
                    await (await session.run(
                        "MATCH (e:__Entity__ {repo_id:$graph,entity_id:$entity}) DETACH DELETE e",
                        graph=self.corpora[target.corpus], entity=target.entity,
                    )).consume()
            finally:
                await neo.disconnect()
                await pg.disconnect()
            return JSONResponse({"removed": True})
        if operation in {"hold", "fail-after-capture", "fail-after-release"} and request.method == "POST":
            rule = HoldRequest.model_validate(await request.json())
            owned_graph = any(rule.path.startswith(f"/api/graph/{corpus}/") for corpus in self.corpora)
            owned_config = rule.path == "/api/config" and rule.query in self.corpora
            owned_registry = rule.path == "/api/corpora" and rule.query is None and bool(self.owned_corpus_ids())
            if not (owned_graph or owned_config or owned_registry):
                return JSONResponse({
                    "error": "Only the isolated corpus registry, owned graph routes, or scoped config GETs can be held",
                }, status_code=400)
            if operation != "hold" and not owned_registry:
                return JSONResponse({
                    "error": "Transport failure is limited to the isolated owned corpus registry",
                }, status_code=400)
            token = uuid4().hex
            self.holds[token] = HeldResponse(
                rule,
                fail_before_forward=operation != "hold",
                wait_before_failure=operation == "fail-after-release",
            )
            return JSONResponse({"token": token})
        if operation.startswith("state/"):
            held = self.holds[operation.split("/", 1)[1]]
            return JSONResponse({"captured": held.captured, "delivered": held.delivered,
                                 "faulted": held.faulted,
                                 "status": held.status, "sha256": held.sha256,
                                 "path": held.rule.path, "query": held.rule.query})
        if operation.startswith("release/") and request.method == "POST":
            self.holds[operation.split("/", 1)[1]].release.set()
            return JSONResponse({"released": True})
        if operation == "cleanup" and request.method == "POST":
            for held in self.holds.values():
                held.release.set()
            pg, neo = await self.stores()
            try:
                for graph in self.corpora.values():
                    await neo.delete_graph(graph)
                for corpus in self.owned_corpus_ids():
                    await pg.delete_corpus(corpus)
                self.corpora.clear()
                self.reserved_corpora.clear()
                self.holds.clear()
            finally:
                await neo.disconnect()
                await pg.disconnect()
            return JSONResponse({"cleaned": True})
        return JSONResponse({"error": "Unknown fixture operation"}, status_code=404)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"].startswith("/__graph_fixture__/"):
            response = await self.control(Request(scope, receive))
            await response(scope, receive, send)
            return
        query_key = "corpus_id" if scope["path"] == "/api/config" else "q"
        query = parse_qs(scope["query_string"].decode()).get(query_key, [None])[0]
        held = next((item for item in self.holds.values() if not item.claimed
                     and scope["method"] == "GET"
                     and item.rule.path == scope["path"] and item.rule.query == query), None)
        if held is None:
            await self.app(scope, receive, send)
            return
        held.claimed = True
        messages: list[Message] = []

        async def capture(message: Message) -> None:
            messages.append(message.copy())

        await self.app(scope, receive, capture)
        held.status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        held.sha256 = hashlib.sha256(b"".join(item.get("body", b"") for item in messages)).hexdigest()
        held.captured = True
        if held.wait_before_failure:
            await asyncio.wait_for(held.release.wait(), timeout=30)
        if held.fail_before_forward:
            held.faulted = True
            raise RuntimeError("Fixture transport failure after complete private API response capture")
        await asyncio.wait_for(held.release.wait(), timeout=30)
        for message in messages:
            await send(message)
        held.delivered = True


if __name__ == "__main__":
    preflight()
    import uvicorn

    from server.main import _warm_catalog_views, app

    _warm_catalog_views()
    uvicorn.run(GraphOrderingApp(app), host="127.0.0.1", port=58131, lifespan="off")
