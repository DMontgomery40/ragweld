from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from server.db.neo4j import Neo4jClient
from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["graph"])


@router.get("/graph/{corpus_id}/entities", response_model=list[Entity])
async def list_entities(
    corpus_id: str,
    entity_type: str | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[Entity]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        entities = await neo4j.list_entities(repo_id, entity_type, limit, query=q)
        if not entities and not (q or "").strip():
            raise HTTPException(status_code=404, detail=f"No graph for repo_id={repo_id}")
        return entities
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/entity/{entity_id}", response_model=Entity)
async def get_entity(corpus_id: str, entity_id: str) -> Entity:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        ent = await neo4j.get_entity(entity_id)
        if ent is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return ent
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/entity/{entity_id}/relationships", response_model=list[Relationship])
async def get_entity_relationships(corpus_id: str, entity_id: str) -> list[Relationship]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        return await neo4j.get_relationships(entity_id)
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/entity/{entity_id}/neighbors", response_model=GraphNeighborsResponse)
async def get_entity_neighbors(corpus_id: str, entity_id: str, max_hops: int = 2, limit: int = 200) -> GraphNeighborsResponse:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        out = await neo4j.get_entity_neighbors(repo_id, entity_id, max_hops=max_hops, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        return out
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/community/{community_id}/members", response_model=list[Entity])
async def get_community_members(corpus_id: str, community_id: str, limit: int = 500) -> list[Entity]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        return await neo4j.get_community_members(repo_id, community_id, limit=limit)
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/communities", response_model=list[Community])
async def list_communities(corpus_id: str, level: int | None = None) -> list[Community]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        comms = await neo4j.get_communities(repo_id, level)
        if not comms:
            raise HTTPException(status_code=404, detail=f"No communities for repo_id={repo_id}")
        return comms
    finally:
        await neo4j.disconnect()


@router.get("/graph/{corpus_id}/stats", response_model=GraphStats)
async def get_graph_stats(corpus_id: str) -> GraphStats:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        stats = await neo4j.get_graph_stats(repo_id)
        if stats.total_entities == 0:
            raise HTTPException(status_code=404, detail=f"No graph for repo_id={repo_id}")
        return stats
    finally:
        await neo4j.disconnect()


@router.post("/graph/{corpus_id}/query")
async def graph_query(corpus_id: str, cypher: str) -> list[dict[str, Any]]:
    repo_id = corpus_id
    cfg = await load_scoped_config(repo_id=repo_id)
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    try:
        await neo4j.connect()
        try:
            return await neo4j.execute_cypher(cypher, params={"repo_id": repo_id})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        await neo4j.disconnect()
