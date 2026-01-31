from __future__ import annotations

import re
from fnmatch import fnmatch

from fastapi import APIRouter, Depends, HTTPException

from server.db.postgres import PostgresClient
from server.models.index import Chunk
from server.models.tribrid_config_model import (
    ChunkSummariesBuildRequest,
    ChunkSummariesLastBuild,
    ChunkSummariesResponse,
    ChunkSummary,
    CorpusScope,
)
from server.services.config_store import get_config

router = APIRouter(tags=["chunk_summaries"])

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")
_DEF_RE = re.compile(r"^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def _path_matches_any_pattern(file_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    fp = (file_path or "").replace("\\", "/")
    base = fp.split("/")[-1]
    for pat in patterns:
        pat = (pat or "").strip()
        if not pat:
            continue
        if fnmatch(fp, pat) or fnmatch(base, pat):
            return True
    return False


def _path_contains_excluded_dir(file_path: str, exclude_dirs: list[str]) -> bool:
    if not exclude_dirs:
        return False
    fp = (file_path or "").replace("\\", "/").lstrip("/")
    parts = [p for p in fp.split("/") if p]
    excl = {d.strip().strip("/").lower() for d in exclude_dirs if str(d).strip()}
    return any(p.lower() in excl for p in parts)


def _content_contains_excluded_keyword(content: str, exclude_keywords: list[str]) -> bool:
    if not exclude_keywords:
        return False
    haystack = (content or "").lower()
    for kw in exclude_keywords:
        k = (kw or "").strip().lower()
        if not k:
            continue
        if k in haystack:
            return True
    return False


def _summarize_chunk(chunk: Chunk, max_symbols: int, purpose_max_length: int, enrich: bool) -> ChunkSummary:
    content = chunk.content or ""
    purpose: str | None = None

    m = _DEF_RE.search(content)
    if m:
        kind, name = m.group(1), m.group(2)
        purpose = f"Defines {kind} {name}."
    else:
        for line in content.splitlines():
            t = line.strip()
            if not t:
                continue
            if t.startswith("#"):
                continue
            purpose = t
            break

    if purpose and len(purpose) > purpose_max_length:
        purpose = purpose[: max(0, purpose_max_length - 1)].rstrip() + "…"

    # Very lightweight symbol extraction (identifiers)
    tokens = _TOKEN_RE.findall(content)
    uniq: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if tok in seen:
            continue
        seen.add(tok)
        uniq.append(tok)
        if len(uniq) >= max_symbols:
            break

    technical_details: str | None = None
    domain_concepts: list[str] = []
    if enrich:
        # Deterministic, lightweight enrichment (no external dependencies)
        technical_details = f"Top identifiers: {', '.join(uniq)}" if uniq else None
        domain_concepts = uniq[:]

    return ChunkSummary(
        chunk_id=chunk.chunk_id,
        file_path=chunk.file_path,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        purpose=purpose,
        symbols=uniq,
        technical_details=technical_details,
        domain_concepts=domain_concepts,
    )


@router.get("/chunk_summaries", response_model=ChunkSummariesResponse)
async def list_chunk_summaries(
    scope: CorpusScope = Depends(),
) -> ChunkSummariesResponse:
    repo_id = scope.resolved_repo_id
    if not repo_id:
        raise HTTPException(status_code=422, detail="Missing corpus_id (or legacy repo_id)")
    cfg = await get_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()

    summaries = await pg.list_chunk_summaries(repo_id)
    last_build = await pg.get_chunk_summaries_last_build(repo_id)

    return ChunkSummariesResponse(repo_id=repo_id, chunk_summaries=summaries, last_build=last_build)


@router.post("/chunk_summaries/build", response_model=ChunkSummariesResponse)
async def build_chunk_summaries(request: ChunkSummariesBuildRequest) -> ChunkSummariesResponse:
    repo_id = request.repo_id

    cfg = await get_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()

    max_out = int(request.max) if request.max is not None else int(cfg.enrichment.chunk_summaries_max)
    max_out = max(1, max_out)
    # Fetch a bounded candidate set to keep this endpoint responsive.
    candidate_limit = min(max_out * 20, 50000)
    chunks = await pg.list_chunks_for_repo(repo_id, limit=candidate_limit)
    if len(chunks) == 0:
        raise HTTPException(status_code=404, detail=f"No indexed chunks found for repo_id={repo_id}. Run Indexing first.")

    exclude_dirs = cfg.chunk_summaries.exclude_dirs
    exclude_patterns = cfg.chunk_summaries.exclude_patterns
    exclude_keywords = cfg.chunk_summaries.exclude_keywords

    enrich_enabled = (
        bool(request.enrich)
        if request.enrich is not None
        else bool(int(cfg.enrichment.chunk_summaries_enrich_default))
    )

    purpose_max_len = int(cfg.chunk_summaries.purpose_max_length)
    max_symbols = int(cfg.chunk_summaries.max_symbols)

    summaries: list[ChunkSummary] = []
    for ch in chunks:
        if _path_contains_excluded_dir(ch.file_path, exclude_dirs):
            continue
        if _path_matches_any_pattern(ch.file_path, exclude_patterns):
            continue
        if _content_contains_excluded_keyword(ch.content, exclude_keywords):
            continue
        summaries.append(
            _summarize_chunk(
                ch,
                max_symbols=max_symbols,
                purpose_max_length=purpose_max_len,
                enrich=enrich_enabled,
            )
        )
        if len(summaries) >= max_out:
            break

    last_build = ChunkSummariesLastBuild(
        repo_id=repo_id,
        total=len(summaries),
        enriched=len(summaries) if enrich_enabled else 0,
    )
    await pg.replace_chunk_summaries(repo_id, summaries=summaries, last_build=last_build)

    return ChunkSummariesResponse(
        repo_id=repo_id,
        chunk_summaries=summaries,
        last_build=last_build,
    )


@router.delete("/chunk_summaries/{chunk_id}")
async def delete_chunk_summary(
    chunk_id: str,
    scope: CorpusScope = Depends(),
) -> dict[str, object]:
    repo_id = scope.resolved_repo_id
    cfg = await get_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    deleted = await pg.delete_chunk_summary(chunk_id, corpus_id=repo_id)
    if deleted <= 0:
        raise HTTPException(status_code=404, detail=f"chunk_id={chunk_id} not found")
    return {"ok": True, "deleted": deleted}
