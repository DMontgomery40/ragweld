from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from server.config import load_config
from server.db.neo4j import Neo4jClient
from server.db.postgres import PostgresClient
from server.indexing.loader import FileLoader
from server.models.index import IndexStats
from server.models.tribrid_config_model import Corpus, CorpusCreateRequest, CorpusStats, CorpusUpdateRequest

router = APIRouter(tags=["repos"])


def _slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"[^a-z0-9._-]+", "-", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v or "corpus"


async def _get_postgres() -> PostgresClient:
    cfg = load_config()
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    return pg


async def _get_neo4j(repo_id: str | None = None) -> Neo4jClient:
    cfg = load_config()
    db_name = cfg.graph_storage.resolve_database(repo_id)
    neo4j = Neo4jClient(
        cfg.graph_storage.neo4j_uri,
        cfg.graph_storage.neo4j_user,
        cfg.graph_storage.neo4j_password,
        database=db_name,
    )
    await neo4j.connect()
    return neo4j


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
    if cfg.graph_storage.neo4j_database_mode == "per_corpus" and cfg.graph_storage.neo4j_auto_create_databases:
        neo4j = Neo4jClient(
            cfg.graph_storage.neo4j_uri,
            cfg.graph_storage.neo4j_user,
            cfg.graph_storage.neo4j_password,
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
    except Exception:
        index_stats = None

    graph_stats = None
    try:
        neo4j = await _get_neo4j(repo_id)
        graph_stats = await neo4j.get_graph_stats(repo_id)
        await neo4j.disconnect()
        if graph_stats.total_entities == 0:
            graph_stats = None
    except Exception:
        graph_stats = None

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


@router.delete("/repos/{corpus_id}")
async def delete_repo(corpus_id: str) -> dict[str, Any]:
    repo_id = corpus_id
    pg = await _get_postgres()
    await pg.delete_corpus(repo_id)
    try:
        neo4j = await _get_neo4j(repo_id)
        await neo4j.delete_graph(repo_id)
        await neo4j.disconnect()
    except Exception:
        pass
    return {"ok": True}


@router.delete("/corpora/{corpus_id}")
async def delete_corpus(corpus_id: str) -> dict[str, Any]:
    return await delete_repo(corpus_id)
