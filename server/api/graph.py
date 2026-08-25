from __future__ import annotations

from collections.abc import AsyncIterator
import contextlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    raise_neo4j_unavailable_if_applicable,
    raise_postgres_unavailable_if_applicable,
)
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import graph_repo_id_of
from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["graph"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)


@dataclass(frozen=True)
class GraphScope:
    """A connected Neo4j client plus the graph generation id that is live for the corpus.

    ``graph_repo_id`` is None when the corpus has no promoted graph generation
    (graph indexing off, or never indexed); routes answer with empty results.
    """

    neo4j: Neo4jClient
    graph_repo_id: str | None


@asynccontextmanager
async def _graph_client(repo_id: str, *, boundary: str) -> AsyncIterator[GraphScope]:
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise
    try:
        pg = PostgresClient(cfg.indexing.postgres_url)
        await pg.connect()
        try:
            graph_repo_id = graph_repo_id_of(await pg.get_generation(repo_id))
        finally:
            with contextlib.suppress(Exception):
                await pg.disconnect()
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise

    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.resolve_password(),
        database=cfg.graph_storage.resolve_database(repo_id),
    )
    try:
        await neo4j.connect()
        await neo4j.ping()
        yield GraphScope(neo4j=neo4j, graph_repo_id=graph_repo_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise_neo4j_unavailable_if_applicable(exc, boundary=boundary)
        raise
    finally:
        try:
            await neo4j.disconnect()
        except Exception:
            pass


@router.get("/graph/{corpus_id}/entities", response_model=list[Entity])
async def list_entities(
    corpus_id: str,
    entity_type: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[Entity]:
    async with _graph_client(corpus_id, boundary="Graph entities API") as scope:
        if scope.graph_repo_id is None:
            return []
        return await scope.neo4j.list_entities(scope.graph_repo_id, entity_type, limit, query=q)


@router.get("/graph/{corpus_id}/entity/{entity_id}", response_model=Entity)
async def get_entity(corpus_id: str, entity_id: str) -> Entity:
    async with _graph_client(corpus_id, boundary="Graph entity API") as scope:
        neo4j = scope.neo4j
        if scope.graph_repo_id is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        ent = await neo4j.get_entity(entity_id)
        if ent is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return ent


@router.get("/graph/{corpus_id}/entity/{entity_id}/relationships", response_model=list[Relationship])
async def get_entity_relationships(corpus_id: str, entity_id: str) -> list[Relationship]:
    async with _graph_client(corpus_id, boundary="Graph relationships API") as scope:
        neo4j = scope.neo4j
        if scope.graph_repo_id is None:
            return []
        return await neo4j.get_relationships(entity_id)


@router.get("/graph/{corpus_id}/entity/{entity_id}/neighbors", response_model=GraphNeighborsResponse)
async def get_entity_neighbors(corpus_id: str, entity_id: str, max_hops: int = 2, limit: int = 200) -> GraphNeighborsResponse:
    async with _graph_client(corpus_id, boundary="Graph neighbors API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        out = await neo4j.get_entity_neighbors(repo_id, entity_id, max_hops=max_hops, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return out


@router.get("/graph/{corpus_id}/community/{community_id}/members", response_model=list[Entity])
async def get_community_members(corpus_id: str, community_id: str, limit: int = 500) -> list[Entity]:
    async with _graph_client(corpus_id, boundary="Graph community members API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return []
        return await neo4j.get_community_members(repo_id, community_id, limit=limit)


@router.get(
    "/graph/{corpus_id}/community/{community_id}/subgraph",
    response_model=GraphNeighborsResponse,
)
async def get_community_subgraph(
    corpus_id: str,
    community_id: str,
    limit: int = 200,
) -> GraphNeighborsResponse:
    """Return a community subgraph (members + edges between members)."""
    async with _graph_client(corpus_id, boundary="Graph community subgraph API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            raise HTTPException(status_code=404, detail="Community not found")
        out = await neo4j.get_community_subgraph(repo_id, community_id, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail="Community not found")
        return out


@router.get("/graph/{corpus_id}/subgraph", response_model=GraphNeighborsResponse)
async def get_repo_subgraph(corpus_id: str, limit: int = 200) -> GraphNeighborsResponse:
    """Induced subgraph over the best-connected entities of the corpus (whole-corpus visualizer)."""
    async with _graph_client(corpus_id, boundary="Graph subgraph API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return GraphNeighborsResponse(entities=[], relationships=[])
        return await neo4j.get_repo_subgraph(repo_id, limit=limit)


@router.get("/graph/{corpus_id}/communities", response_model=list[Community])
async def list_communities(corpus_id: str, level: int | None = None) -> list[Community]:
    async with _graph_client(corpus_id, boundary="Graph communities API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return []
        return await neo4j.get_communities(repo_id, level)


@router.get("/graph/{corpus_id}/stats", response_model=GraphStats)
async def get_graph_stats(corpus_id: str) -> GraphStats:
    async with _graph_client(corpus_id, boundary="Graph stats API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return GraphStats(repo_id=corpus_id, total_entities=0, total_relationships=0, total_communities=0)
        stats = await neo4j.get_graph_stats(repo_id)
        # Report the corpus id the operator knows, not the physical generation id.
        return stats.model_copy(update={"repo_id": corpus_id})


@router.post("/graph/{corpus_id}/query")
async def graph_query(corpus_id: str, cypher: str) -> list[dict[str, Any]]:
    async with _graph_client(corpus_id, boundary="Graph query API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return []
        try:
            return await neo4j.execute_cypher(cypher, params={"repo_id": repo_id})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
