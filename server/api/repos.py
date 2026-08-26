from __future__ import annotations

import asyncio
import logging
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_neo4j_unavailable_if_applicable,
    raise_postgres_unavailable_if_applicable,
)
from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.dependency_errors import DependencyUnavailableError
from server.indexing.generations import (
    IndexFenceHeldError,
    TombstoneCleanupError,
    drop_tombstoned_stores,
    graph_repo_id_of,
)
from server.indexing.loader import FileLoader
from server.lineage.registry import delete_repo_lineage
from server.models.index import IndexStats
from server.models.tribrid_config_model import (
    Corpus,
    CorpusCreateRequest,
    CorpusStats,
    CorpusUpdateRequest,
    DependencyUnavailableResponse,
    GraphStats,
    IndexDeletionIncompleteResponse,
    IndexRunConflictResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["repos"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)


def _slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"[^a-z0-9._-]+", "-", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v or "corpus"


async def _get_postgres() -> PostgresClient:
    cfg = load_config()
    pg = PostgresClient(cfg.indexing.postgres_url, schema_mode="control")
    try:
        await pg.connect()
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Corpus API")
        raise
    return pg


async def _disconnect_neo4j_quietly(neo4j: Neo4jClient) -> None:
    with suppress(Exception):
        await neo4j.disconnect()


async def _get_neo4j(repo_id: str | None = None) -> Neo4jClient:
    cfg = load_config()
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.resolve_password(),
        database=db_name,
    )
    try:
        await neo4j.connect()
        await neo4j.ping()
    except Exception as exc:
        await _disconnect_neo4j_quietly(neo4j)
        raise_neo4j_unavailable_if_applicable(exc, boundary="Corpus graph setup")
        raise
    return neo4j


async def _get_graph_stats_or_none(neo4j: Neo4jClient, repo_id: str) -> GraphStats | None:
    try:
        graph_stats = await neo4j.get_graph_stats(repo_id)
        if graph_stats.total_entities == 0:
            return None
        return graph_stats
    except Exception as exc:
        raise_neo4j_unavailable_if_applicable(exc, boundary="Corpus graph stats API")
        raise
    finally:
        await _disconnect_neo4j_quietly(neo4j)


@router.get("/repos", response_model=list[Corpus])
async def list_repos() -> list[Corpus]:
    pg = await _get_postgres()
    rows = await pg.list_corpora()
    return [
        Corpus(
            repo_id=r["repo_id"],
            name=r["name"],
            path=r["path"],
            slug=(r.get("meta") or {}).get("slug") or r["repo_id"],
            branch=(r.get("meta") or {}).get("branch"),
            default=(r.get("meta") or {}).get("default"),
            exclude_paths=(r.get("meta") or {}).get("exclude_paths"),
            keywords=(r.get("meta") or {}).get("keywords"),
            path_boosts=(r.get("meta") or {}).get("path_boosts"),
            layer_bonuses=(r.get("meta") or {}).get("layer_bonuses"),
            description=r.get("description"),
            created_at=r.get("created_at") or datetime.now(UTC),
            last_indexed=r.get("last_indexed"),
        )
        for r in rows
    ]


@router.get("/corpora", response_model=list[Corpus])
async def list_corpora() -> list[Corpus]:
    return await list_repos()


@router.post("/repos", response_model=Corpus)
async def add_repo(request: CorpusCreateRequest) -> Corpus:
    corpus_id = request.repo_id or _slugify(request.name)
    pg = await _get_postgres()

    # Validate path exists on server
    root = Path(request.path).expanduser()
    if not root.exists():
        raise HTTPException(status_code=422, detail=f"Path not found: {root}")

    await pg.upsert_corpus(
        corpus_id,
        name=request.name,
        root_path=str(root),
        description=request.description,
        meta={"slug": corpus_id},
    )

    # Seed per-corpus config from current global template
    cfg = load_config()
    await pg.upsert_corpus_config_json(corpus_id, cfg.model_dump())

    # Enterprise option: per-corpus Neo4j databases (multi-db).
    # Only attempted when explicitly enabled in config.
    if (
        cfg.graph_storage.neo4j_database_mode == "per_corpus"
        and cfg.graph_storage.neo4j_auto_create_databases
    ):
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.resolve_password(),
            database=cfg.graph_storage.neo4j_database,
        )
        await neo4j.connect()
        db_name = cfg.graph_storage.resolve_database(corpus_id)
        ok = await neo4j.ensure_database(db_name)
        await neo4j.disconnect()
        if not ok:
            raise HTTPException(
                status_code=503,
                detail="Per-corpus Neo4j databases requested but not supported. "
                "Use Neo4j Enterprise image + license (or switch neo4j_database_mode='shared').",
            )

    return Corpus(
        repo_id=corpus_id,
        name=request.name,
        path=str(root),
        slug=corpus_id,
        description=request.description,
        created_at=datetime.now(UTC),
        last_indexed=None,
    )


@router.post("/corpora", response_model=Corpus)
async def add_corpus(request: CorpusCreateRequest) -> Corpus:
    return await add_repo(request)


@router.get("/repos/{corpus_id}", response_model=Corpus)
async def get_repo(corpus_id: str) -> Corpus:
    repo_id = corpus_id
    pg = await _get_postgres()
    row = await pg.get_corpus(repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")
    meta = row.get("meta") or {}
    return Corpus(
        repo_id=row["repo_id"],
        name=row["name"],
        path=row["path"],
        slug=meta.get("slug") or row["repo_id"],
        branch=meta.get("branch"),
        default=meta.get("default"),
        exclude_paths=meta.get("exclude_paths"),
        keywords=meta.get("keywords"),
        path_boosts=meta.get("path_boosts"),
        layer_bonuses=meta.get("layer_bonuses"),
        description=row.get("description"),
        created_at=row.get("created_at") or datetime.now(UTC),
        last_indexed=row.get("last_indexed"),
    )


@router.get("/corpora/{corpus_id}", response_model=Corpus)
async def get_corpus(corpus_id: str) -> Corpus:
    return await get_repo(corpus_id)


@router.patch("/repos/{corpus_id}", response_model=Corpus)
async def update_repo(corpus_id: str, request: CorpusUpdateRequest) -> Corpus:
    """Update an existing corpus."""
    repo_id = corpus_id
    pg = await _get_postgres()

    # Check corpus exists
    existing = await pg.get_corpus(repo_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")

    # Build meta updates for JSONB fields
    meta_updates: dict[str, list[str] | dict[str, dict[str, float]]] = {}
    if request.exclude_paths is not None:
        meta_updates["exclude_paths"] = request.exclude_paths
    if request.keywords is not None:
        meta_updates["keywords"] = request.keywords
    if request.path_boosts is not None:
        meta_updates["path_boosts"] = request.path_boosts
    if request.layer_bonuses is not None:
        meta_updates["layer_bonuses"] = request.layer_bonuses
    if request.branch is not None:
        meta_updates["branch"] = request.branch  # type: ignore[assignment]

    # Update corpus
    updated = await pg.update_corpus(
        repo_id,
        name=request.name,
        path=request.path,
        meta_updates=meta_updates if meta_updates else None,
    )

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")

    meta = updated.get("meta") or {}
    return Corpus(
        repo_id=updated["repo_id"],
        name=updated["name"],
        path=updated["root_path"],
        slug=updated["repo_id"],
        branch=meta.get("branch"),
        default=meta.get("default"),
        exclude_paths=meta.get("exclude_paths"),
        keywords=meta.get("keywords"),
        path_boosts=meta.get("path_boosts"),
        layer_bonuses=meta.get("layer_bonuses"),
        created_at=updated.get("created_at") or datetime.now(UTC),
        last_indexed=updated.get("last_indexed"),
    )


@router.patch("/corpora/{corpus_id}", response_model=Corpus)
async def update_corpus_endpoint(corpus_id: str, request: CorpusUpdateRequest) -> Corpus:
    """Update an existing corpus (alias)."""
    return await update_repo(corpus_id, request)


@router.get("/repos/{corpus_id}/stats", response_model=CorpusStats)
async def get_repo_stats(corpus_id: str) -> CorpusStats:
    repo_id = corpus_id
    pg = await _get_postgres()
    row = await pg.get_corpus(repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")

    # If graph storage is down, the whole endpoint is a structured 503; fail fast
    # before walking the corpus tree or loading index stats from Postgres.
    neo4j = await _get_neo4j(repo_id)
    graph_generation_id = graph_repo_id_of(await pg.get_generation(repo_id))
    graph_stats = (
        await _get_graph_stats_or_none(neo4j, graph_generation_id) if graph_generation_id else None
    )

    # Compute file stats from disk (best-effort for now)
    root_path = row["path"]
    loader = FileLoader(ignore_patterns=[])
    total_size = 0
    file_count = 0
    lang_breakdown: dict[str, int] = {}
    root = Path(root_path).expanduser().resolve()
    if root.exists():
        for rel, p in loader.iter_repo_files(str(root)):
            file_count += 1
            try:
                total_size += p.stat().st_size
            except Exception:
                pass
            lang = loader.detect_language(rel) or "unknown"
            lang_breakdown[lang] = lang_breakdown.get(lang, 0) + 1

    # Index stats from Postgres (404 if no chunks)
    index_stats: IndexStats | None = None
    try:
        index_stats = await pg.get_index_stats(repo_id)
        if index_stats.total_chunks == 0:
            index_stats = None
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Corpus index stats API")
        raise

    return CorpusStats(
        repo_id=repo_id,
        file_count=file_count,
        total_size_bytes=total_size,
        language_breakdown=lang_breakdown,
        index_stats=index_stats,
        graph_stats=graph_stats,
    )


@router.get("/corpora/{corpus_id}/stats", response_model=CorpusStats)
async def get_corpus_stats(corpus_id: str) -> CorpusStats:
    return await get_repo_stats(corpus_id)


@router.delete(
    "/repos/{corpus_id}",
    responses={
        409: {
            "model": IndexRunConflictResponse,
            "description": "A live index run holds this corpus; stop it first.",
        },
        503: {
            "model": DependencyUnavailableResponse | IndexDeletionIncompleteResponse,
            "description": "External cleanup failed; the deletion tombstone stays for the next attempt.",
        },
    },
)
async def delete_repo(corpus_id: str) -> dict[str, Any]:
    repo_id = corpus_id
    pg = await _get_postgres()
    row = await pg.get_corpus(repo_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")

    # Postgres first, in one transaction: chunk rows, manifest and contracts go
    # before any external store is touched, and the exact Qdrant/Neo4j targets are
    # recorded as a tombstone so a failure below leaves a corpus that reads as
    # never indexed plus a retryable cleanup list. A corpus fenced by a live index
    # run is refused (409): stop that run first.
    cfg = load_config()
    try:
        _, tombstone = await pg.delete_index_state(
            repo_id, lease_seconds=cfg.indexing.index_run_lease_seconds
        )
    except IndexFenceHeldError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "index_run_in_progress",
                "corpus_id": repo_id,
                "run_id": exc.fence.run_id,
                "owner": exc.fence.owner,
                "started_at": exc.fence.started_at.isoformat(),
                "heartbeat_at": exc.fence.heartbeat_at.isoformat(),
                "message": f"Corpus {repo_id} is fenced by index run {exc.fence.run_id}.",
                "operator_hint": "Stop that index run (or wait for its lease to expire) before deleting the corpus.",
            },
        ) from exc
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Corpus deletion API")
        raise
    try:
        await drop_tombstoned_stores(cfg, repo_id, tombstone)
    except TombstoneCleanupError as exc:
        raise dependency_unavailable_http_exception(
            exc.dependency, boundary="Corpus deletion API", exc=exc
        ) from exc
    if not await pg.clear_index_tombstone(repo_id, tombstone):
        raise HTTPException(
            status_code=409,
            detail=f"Corpus {repo_id}: a newer de-index tombstone appeared during cleanup; retry the deletion",
        )

    # Corpus-scoped lineage (aliases, bundles) goes with the corpus. It runs before
    # the registry row is removed so a failed removal answers a typed, retryable 503
    # while the corpus is still registered, instead of leaving orphaned alias/bundle
    # directories behind under data/lineage. Deletion as a whole is still a
    # non-transactional saga (Qdrant -> Neo4j -> lineage -> Postgres): a failure at
    # any step leaves the registry row with the earlier stores already gone, and the
    # retry finishes the job. A durable "deleting" tombstone is tracked as tech debt.
    try:
        await asyncio.to_thread(delete_repo_lineage, repo_id)
    except DependencyUnavailableError as exc:
        raise dependency_unavailable_http_exception(
            exc.dependency, boundary="Corpus deletion API", exc=exc
        ) from exc

    try:
        await pg.delete_corpus(repo_id)
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary="Corpus deletion API")
        raise

    return {"ok": True}


@router.delete("/corpora/{corpus_id}")
async def delete_corpus(corpus_id: str) -> dict[str, Any]:
    return await delete_repo(corpus_id)
