from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from server.api.dependency_errors import (
    MANIFEST_READER_UNAVAILABLE_RESPONSES,
    raise_neo4j_unavailable_if_applicable,
    raise_postgres_unavailable_if_applicable,
)
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.generations import graph_repo_id_of
from server.indexing.graphrag_pipeline import require_staging_graph_id
from server.models.graph import Community, Entity, GraphNeighborsResponse, GraphStats, Relationship
from server.models.graph_sources import (
    GraphEntitySourcesResponse,
    GraphSourceGenerationChangedDetail,
    GraphSourceGenerationChangedResponse,
    GraphSourceReindexRequiredDetail,
    GraphSourceReindexRequiredResponse,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["graph"], responses=MANIFEST_READER_UNAVAILABLE_RESPONSES)


def _entity_missing_detail(entity_id: str) -> str:
    """A 404 the operator can act on: which id was looked up, not a bare 'not found'."""
    return f"Entity not found in this corpus graph: {entity_id}"


@dataclass(frozen=True)
class GraphScope:
    """A connected Neo4j client plus the graph generation id that is live for the corpus.

    ``graph_repo_id`` is None when the corpus has no promoted graph generation
    (graph indexing off, or never indexed); routes answer with empty results.
    """

    neo4j: Neo4jClient
    graph_repo_id: str | None
    run_id: str | None
    postgres_url: str


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
            generation = await pg.get_generation(repo_id)
            graph_repo_id = graph_repo_id_of(generation)
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
        yield GraphScope(
            neo4j=neo4j,
            graph_repo_id=graph_repo_id,
            run_id=generation.run_id if generation else None,
            postgres_url=cfg.indexing.postgres_url,
        )
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


# Entity ids are corpus-relative source paths (`server/retrieval/rerank.py::Reranker`), so
# they carry `/` and `::`. They travel as a QUERY parameter, never as a path segment: a
# `{entity_id:path}` segment is greedy and swallows the `/neighbors` and `/relationships`
# suffixes of its own sibling routes, which is how every code entity 404ed.
EntityIdQuery = Annotated[str, Query(min_length=1, description="Entity id within the corpus graph")]


@router.get("/graph/{corpus_id}/entity", response_model=Entity)
async def get_entity(corpus_id: str, entity_id: EntityIdQuery) -> Entity:
    async with _graph_client(corpus_id, boundary="Graph entity API") as scope:
        neo4j = scope.neo4j
        if scope.graph_repo_id is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        ent = await neo4j.get_entity(scope.graph_repo_id, entity_id)
        if ent is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        return ent


@router.get("/graph/{corpus_id}/entity/relationships", response_model=list[Relationship])
async def get_entity_relationships(corpus_id: str, entity_id: EntityIdQuery) -> list[Relationship]:
    async with _graph_client(corpus_id, boundary="Graph relationships API") as scope:
        neo4j = scope.neo4j
        if scope.graph_repo_id is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        return await neo4j.get_relationships(scope.graph_repo_id, entity_id)


@router.get(
    "/graph/{corpus_id}/entity/sources",
    response_model=GraphEntitySourcesResponse,
    responses={409: {"model": GraphSourceGenerationChangedResponse | GraphSourceReindexRequiredResponse}},
)
async def get_entity_sources(
    corpus_id: str,
    entity_id: EntityIdQuery,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    run_id: str | None = Query(default=None, min_length=1),
) -> GraphEntitySourcesResponse:
    """Direct entity mention sources; these do not establish evidence for an edge."""
    async with _graph_client(corpus_id, boundary="Graph entity sources API") as scope:
        if scope.graph_repo_id is None or scope.run_id is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        # A newer manifest may intentionally reuse an older graph resource. Its
        # token fences pagination; the validated graph ID owns the stored run.
        try:
            graph_run_id = require_staging_graph_id(scope.graph_repo_id).rsplit("__", 1)[-1]
        except ValueError as exc:
            # Migrated manifests can retain a corpus-keyed graph, including
            # under a newer incremental run. Never guess scope for its mentions.
            raise HTTPException(status_code=409, detail=GraphSourceReindexRequiredDetail().model_dump()) from exc
        if run_id is not None and run_id != scope.run_id:
            raise HTTPException(status_code=409, detail=GraphSourceGenerationChangedDetail().model_dump())
        sources = await scope.neo4j.get_entity_sources(
            scope.graph_repo_id, graph_run_id, entity_id, limit=limit, offset=offset
        )
        pg = PostgresClient(scope.postgres_url)
        try:
            await pg.connect()
            chunks = await pg.get_chunks(corpus_id, [source.chunk_id for source in sources[:limit]]) if sources else []
            # Every completed graph lookup must still belong to the manifest we
            # started with, including empty pages and missing entities.
            current = await pg.get_generation(corpus_id)
            if current is None or (current.run_id, current.graph_repo_id) != (scope.run_id, scope.graph_repo_id):
                raise HTTPException(status_code=409, detail=GraphSourceGenerationChangedDetail().model_dump())
        except Exception as exc:
            raise_postgres_unavailable_if_applicable(exc, boundary="Graph entity source locations")
            raise
        finally:
            with contextlib.suppress(Exception):
                await pg.disconnect()
        if sources is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        page = GraphEntitySourcesResponse(
            entity_id=entity_id, run_id=scope.run_id, sources=sources[:limit],
            next_offset=offset + limit if len(sources) > limit else None,
        )
        # Only enrich from the exact same indexed text/location. A newer Postgres
        # chunk must not attach its page regions to an older graph mention.
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        for source in page.sources:
            chunk = by_id.get(source.chunk_id)
            if chunk is not None and (
                chunk.file_path, chunk.start_line, chunk.end_line, chunk.content
            ) == (source.file_path, source.start_line, source.end_line, source.content):
                source.metadata = chunk.metadata
                source.provenance = chunk.provenance
        return page


@router.get("/graph/{corpus_id}/entity/neighbors", response_model=GraphNeighborsResponse)
async def get_entity_neighbors(
    corpus_id: str,
    entity_id: EntityIdQuery,
    max_hops: int = 2,
    limit: int = 200,
) -> GraphNeighborsResponse:
    async with _graph_client(corpus_id, boundary="Graph neighbors API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        out = await neo4j.get_entity_neighbors(repo_id, entity_id, max_hops=max_hops, limit=limit)
        if out is None:
            raise HTTPException(status_code=404, detail=_entity_missing_detail(entity_id))
        return out


@router.get("/graph/{corpus_id}/community/{community_id}/members", response_model=list[Entity])
async def get_community_members(
    corpus_id: str, community_id: str, limit: int = 500
) -> list[Entity]:
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
async def get_repo_subgraph(
    corpus_id: str,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    q: str | None = None,
) -> GraphNeighborsResponse:
    """Induced subgraph over the best-connected entities of the corpus, or of a search.

    `q` filters by entity name with the same predicate as the entity list, and the
    response carries the relationships between the matched entities plus the total
    match count, so a search renders as a graph with a denominator rather than as
    undenominated unconnected dots (M-61, M-62).
    """
    async with _graph_client(corpus_id, boundary="Graph subgraph API") as scope:
        neo4j = scope.neo4j
        repo_id = scope.graph_repo_id
        if repo_id is None:
            return GraphNeighborsResponse(
                entities=[], relationships=[], total_matched=0, limit=limit
            )
        return await neo4j.get_repo_subgraph(repo_id, limit=limit, query=q)


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
            return GraphStats(
                repo_id=corpus_id, total_entities=0, total_relationships=0, total_communities=0
            )
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
