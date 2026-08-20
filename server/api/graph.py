from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, HTTPException

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    raise_neo4j_unavailable_if_applicable,
    raise_postgres_unavailable_if_applicable,
)
from server.db.neo4j import Neo4jClient
from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["graph"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)


@asynccontextmanager
async def _graph_client(repo_id: str, *, boundary: str) -> AsyncIterator[Neo4jClient]:
    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        yield neo4j
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
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph entities API") as neo4j:
        entities = await neo4j.list_entities(repo_id, entity_type, limit, query=q)
        return entities


@router.get("/graph/{corpus_id}/entity/{entity_id}", response_model=Entity)
async def get_entity(corpus_id: str, entity_id: str) -> Entity:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph entity API") as neo4j:
        ent = await neo4j.get_entity(entity_id)
        if ent is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return ent


@router.get("/graph/{corpus_id}/entity/{entity_id}/relationships", response_model=list[Relationship])
async def get_entity_relationships(corpus_id: str, entity_id: str) -> list[Relationship]:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph relationships API") as neo4j:
        return await neo4j.get_relationships(entity_id)


@router.get("/graph/{corpus_id}/entity/{entity_id}/neighbors", response_model=GraphNeighborsResponse)
async def get_entity_neighbors(corpus_id: str, entity_id: str, max_hops: int = 2, limit: int = 200) -> GraphNeighborsResponse:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph neighbors API") as neo4j:
        out = await neo4j.get_entity_neighbors(repo_id, entity_id, max_hops=max_hops, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return out


@router.get("/graph/{corpus_id}/community/{community_id}/members", response_model=list[Entity])
async def get_community_members(corpus_id: str, community_id: str, limit: int = 500) -> list[Entity]:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph community members API") as neo4j:
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
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph community subgraph API") as neo4j:
        out = await neo4j.get_community_subgraph(repo_id, community_id, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail="Community not found")
        return out


@router.get("/graph/{corpus_id}/communities", response_model=list[Community])
async def list_communities(corpus_id: str, level: int | None = None) -> list[Community]:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph communities API") as neo4j:
        comms = await neo4j.get_communities(repo_id, level)
        return comms


@router.get("/graph/{corpus_id}/stats", response_model=GraphStats)
async def get_graph_stats(corpus_id: str) -> GraphStats:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph stats API") as neo4j:
        stats = await neo4j.get_graph_stats(repo_id)
        return stats


@router.post("/graph/{corpus_id}/query")
async def graph_query(corpus_id: str, cypher: str) -> list[dict[str, Any]]:
    repo_id = corpus_id
    async with _graph_client(repo_id, boundary="Graph query API") as neo4j:
        try:
            return await neo4j.execute_cypher(cypher, params={"repo_id": repo_id})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
