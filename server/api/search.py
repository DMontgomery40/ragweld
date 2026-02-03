from __future__ import annotations

import os
import time

from fastapi import APIRouter, HTTPException
from pydantic_ai.exceptions import ModelHTTPError
from starlette.responses import StreamingResponse

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.retrieval import AnswerRequest, AnswerResponse, SearchRequest, SearchResponse
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import get_config as load_scoped_config
from server.services.conversation_store import get_conversation_store
from server.services.rag import generate_response, stream_response
from server.observability.metrics import SEARCH_REQUESTS_TOTAL

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    SEARCH_REQUESTS_TOTAL.inc()

    # Validate corpus exists (prevents auto-creating configs on search)
    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    await pg.connect()
    corpus = await pg.get_corpus(request.repo_id)
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {request.repo_id}")

    cfg = await load_scoped_config(repo_id=request.repo_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    t0 = time.perf_counter()
    matches = await fusion.search(
        [request.repo_id],
        request.query,
        cfg.fusion,
        include_vector=bool(request.include_vector),
        include_sparse=bool(request.include_sparse),
        include_graph=bool(request.include_graph),
        top_k=int(request.top_k),
    )
    dt_ms = (time.perf_counter() - t0) * 1000.0

    return SearchResponse(
        query=request.query,
        matches=matches,
        fusion_method=cfg.fusion.method,
        reranker_mode=cfg.reranking.reranker_mode,
        latency_ms=dt_ms,
        debug={
            "vector_enabled": bool(request.include_vector),
            "sparse_enabled": bool(request.include_sparse),
            "graph_enabled": bool(request.include_graph),
            **(fusion.last_debug or {}),
        },
    )


@router.post("/answer", response_model=AnswerResponse)
async def answer(request: AnswerRequest) -> AnswerResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    # Require an OpenAI key for now (provider-backed generation comes later)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="No LLM configured (set OPENAI_API_KEY)")

    cfg = await load_scoped_config(repo_id=request.repo_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    store = get_conversation_store()
    conv = store.get_or_create(None)

    try:
        text, sources, _provider_id = await generate_response(
            message=request.query,
            repo_id=request.repo_id,
            conversation=conv,
            config=cfg,
            fusion=fusion,
        )
    except ModelHTTPError as e:
        # Surface auth/config errors as "no LLM configured" for dev UX and tests.
        # (httpx ASGITransport raises app exceptions by default unless converted to HTTPException.)
        raise HTTPException(status_code=503, detail=f"LLM request failed: {e}") from e

    return AnswerResponse(
        query=request.query,
        answer=text,
        sources=sources,
        model=cfg.generation.gen_model,
        tokens_used=0,
        latency_ms=0.0,
    )


@router.post("/answer/stream")
async def answer_stream(request: AnswerRequest) -> StreamingResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="No LLM configured (set OPENAI_API_KEY)")

    cfg = await load_scoped_config(repo_id=request.repo_id)
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    store = get_conversation_store()
    conv = store.get_or_create(None)

    return StreamingResponse(
        stream_response(
            message=request.query,
            repo_id=request.repo_id,
            conversation=conv,
            config=cfg,
            fusion=fusion,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
