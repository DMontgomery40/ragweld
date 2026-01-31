from __future__ import annotations

import re
from collections import Counter

from fastapi import APIRouter, HTTPException

from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import KeywordsGenerateRequest, KeywordsGenerateResponse
from server.services.config_store import get_config

router = APIRouter(tags=["keywords"])

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,63}")


@router.post("/keywords/generate", response_model=KeywordsGenerateResponse)
async def generate_keywords(request: KeywordsGenerateRequest) -> KeywordsGenerateResponse:
    repo_id = request.repo_id

    cfg = await get_config(repo_id=repo_id)
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    chunks = await pg.list_chunks_for_repo(repo_id)
    if len(chunks) == 0:
        raise HTTPException(status_code=404, detail=f"No indexed chunks found for repo_id={repo_id}. Run Indexing first.")

    counter: Counter[str] = Counter()
    for ch in chunks:
        tokens = _TOKEN_RE.findall((ch.content or "").lower())
        counter.update(tokens)

    min_freq = int(cfg.keywords.keywords_min_freq)
    max_kw = int(cfg.keywords.keywords_max_per_repo)

    candidates = [(tok, freq) for tok, freq in counter.items() if freq >= min_freq]
    candidates.sort(key=lambda t: (-t[1], t[0]))
    keywords = [tok for tok, _ in candidates[: max_kw]]

    # Persist for later use (search weighting, UI display)
    await pg.update_corpus_meta(repo_id, {"keywords": keywords})

    return KeywordsGenerateResponse(repo_id=repo_id, keywords=keywords, count=len(keywords))
