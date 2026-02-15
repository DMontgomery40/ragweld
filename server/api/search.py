from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.retrieval import AnswerRequest, AnswerResponse, SearchRequest, SearchResponse
from server.models.tribrid_config_model import TriBridConfig
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import CorpusNotFoundError, get_config as load_scoped_config
from server.services.answer_service import answer_best_effort, stream_answer_best_effort
from server.services.conversation_store import get_conversation_store
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
    corpus_validation_error: str | None = None
    corpus = None
    try:
        await pg.connect()
        corpus = await pg.get_corpus(request.repo_id)
    except Exception as e:
        # Fail open: we can't validate corpus existence if Postgres is down, but we still return a 200
        # with best-effort retrieval debug.
        corpus_validation_error = str(e)

    if corpus_validation_error is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {request.repo_id}")

    try:
        cfg = await load_scoped_config(repo_id=request.repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        # Fail open: fall back to LAW defaults (fusion will also fail open if config load fails downstream).
        cfg = TriBridConfig()
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

    # Best-effort query log append for triplet mining.
    try:
        if int(getattr(cfg.tracing, "tracing_enabled", 1) or 0) == 1:
            from server.observability.query_log import append_query_log

            await append_query_log(
                cfg,
                entry={
                    "event_id": str(uuid.uuid4()),
                    "kind": "search",
                    "corpus_id": request.repo_id,
                    "query": request.query,
                    "reranker_mode": str(cfg.reranking.reranker_mode or ""),
                    "rerank_ok": bool((fusion.last_debug or {}).get("rerank_ok", True)),
                    "rerank_applied": bool((fusion.last_debug or {}).get("rerank_applied", False)),
                    "rerank_skipped_reason": (fusion.last_debug or {}).get("rerank_skipped_reason"),
                    "rerank_error": (fusion.last_debug or {}).get("rerank_error"),
                    "rerank_candidates_reranked": int((fusion.last_debug or {}).get("rerank_candidates_reranked") or 0),
                    "top_paths": [m.file_path for m in matches[:5]],
                },
            )
    except Exception:
        pass

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
            "corpus_validation_error": corpus_validation_error,
            **(fusion.last_debug or {}),
        },
    )


@router.post("/answer", response_model=AnswerResponse)
async def answer(request: AnswerRequest) -> AnswerResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    # Validate corpus exists (return 404 rather than bubbling CorpusNotFoundError as 500).
    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    corpus_validation_error: str | None = None
    corpus = None
    try:
        await pg.connect()
        corpus = await pg.get_corpus(request.repo_id)
    except Exception as e:
        corpus_validation_error = str(e)

    if corpus_validation_error is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {request.repo_id}")

    try:
        cfg = await load_scoped_config(repo_id=request.repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        cfg = TriBridConfig()
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    t0 = time.perf_counter()
    text, sources, provider_info, debug = await answer_best_effort(
        query=request.query,
        corpus_id=request.repo_id,
        config=cfg,
        fusion=fusion,
        include_vector=bool(request.include_vector),
        include_sparse=bool(request.include_sparse),
        include_graph=bool(request.include_graph),
        top_k=int(request.top_k),
        system_prompt_override=request.system_prompt,
        model_override=str(request.model_override or ""),
    )
    dt_ms = (time.perf_counter() - t0) * 1000.0

    if corpus_validation_error:
        debug = debug.model_copy(
            update={
                "fusion_debug": {**(debug.fusion_debug or {}), "corpus_validation_error": corpus_validation_error}
            }
        )

    model = provider_info.model if (provider_info is not None and debug.llm_used) else "retrieval-only"

    return AnswerResponse(
        query=request.query,
        answer=text,
        sources=sources,
        model=model,
        tokens_used=0,
        latency_ms=float(dt_ms),
        debug=debug,
    )


@router.post("/answer/stream")
async def answer_stream(request: AnswerRequest) -> StreamingResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    # Validate corpus exists (return 404 rather than bubbling CorpusNotFoundError as 500).
    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    corpus_validation_error: str | None = None
    corpus = None
    try:
        await pg.connect()
        corpus = await pg.get_corpus(request.repo_id)
    except Exception as e:
        corpus_validation_error = str(e)

    if corpus_validation_error is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {request.repo_id}")

    try:
        cfg = await load_scoped_config(repo_id=request.repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception:
        cfg = TriBridConfig()
    fusion = TriBridFusion(vector=None, sparse=None, graph=None)

    store = get_conversation_store()
    conv = store.get_or_create(None)

    return StreamingResponse(
        stream_answer_best_effort(
            query=request.query,
            corpus_id=request.repo_id,
            config=cfg,
            fusion=fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=int(request.top_k),
            system_prompt_override=request.system_prompt,
            model_override=str(request.model_override or ""),
            conversation_id=conv.id,
            started_at_ms=int(time.time() * 1000),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
