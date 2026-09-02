from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from types import TracebackType
from typing import cast

from fastapi import APIRouter, HTTPException, Response
from starlette.responses import StreamingResponse

from server.api.dependency_errors import (
    raise_postgres_unavailable_if_applicable,
    raise_required_dependency_unavailable_if_applicable,
)
from server.api.generation_errors import (
    ANSWER_RUNTIME_UNAVAILABLE_RESPONSES,
    ANSWER_STREAM_RUNTIME_UNAVAILABLE_RESPONSES,
    generation_unavailable_http_exception,
)
from server.api.retrieval_errors import (
    answer_retrieval_failed_http_exception,
    reranker_failed_http_exception,
    RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
    required_retrieval_leg_http_exception,
    retrieval_contract_mismatch_http_exception,
)
from server.config import load_config
from server.db.postgres import PostgresClient
from server.models.retrieval import AnswerRequest, AnswerResponse, SearchRequest, SearchResponse
from server.models.tribrid_config_model import ChatDebugInfo, ChatProviderInfo, TriBridConfig
from server.observability.runtime import (
    apply_default_links,
    current_header_values,
    current_trace_payload_fields,
    set_provider_route,
    start_request_observation,
    start_streaming_observation,
    update_route_summary,
)
from server.retrieval.cache import CacheMode
from server.retrieval.errors import (
    AnswerRetrievalFailedError,
    RequiredRetrievalLegError,
    RerankerFailedError,
    RetrievalContractMismatchError,
)
from server.retrieval.fusion import TriBridFusion
from server.services.answer_service import (
    answer_best_effort,
    retrieve_best_effort,
    stream_answer_best_effort,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.conversation_store import get_conversation_store
from server.services.traces import get_trace_store

router = APIRouter(tags=["search"], responses=RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES)


def _normalize_cache_mode(cache_mode: str | None) -> CacheMode:
    mode = str(cache_mode or "default").strip().lower()
    if mode in {"bypass", "refresh"}:
        return cast(CacheMode, mode)
    return "default"


async def _validated_scoped_config(repo_id: str, *, boundary: str) -> TriBridConfig:
    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    try:
        await pg.connect()
        corpus = await pg.get_corpus(repo_id)
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise

    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {repo_id}")

    try:
        return await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, response: Response) -> SearchResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cfg = await _validated_scoped_config(request.repo_id, boundary="Search API")
    fusion = TriBridFusion()
    request_cache_mode = _normalize_cache_mode(request.cache_mode)
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()

    with start_request_observation(
        config=cfg,
        route_name="search",
        path="/api/search",
        method="POST",
        run_id=run_id,
        repo_id=request.repo_id,
    ):
        apply_default_links(cfg)
        for key, value in current_header_values().items():
            response.headers[key] = value
        trace_enabled = await trace_store.start(
            run_id=run_id,
            repo_id=request.repo_id,
            started_at_ms=started_at_ms,
            config=cfg,
        )
        if trace_enabled:
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.add_event(
                run_id,
                kind="search.request",
                data={
                    "repo_id": request.repo_id,
                    "query": request.query,
                    "include_vector": bool(request.include_vector),
                    "include_sparse": bool(request.include_sparse),
                    "include_graph": bool(request.include_graph),
                    "top_k": int(request.top_k),
                },
            )

        t0 = time.perf_counter()
        try:
            matches = await fusion.search(
                [request.repo_id],
                request.query,
                cfg.fusion,
                include_vector=bool(request.include_vector),
                include_sparse=bool(request.include_sparse),
                include_graph=bool(request.include_graph),
                top_k=int(request.top_k),
                cache_mode=request_cache_mode,
                cache_namespace="search",
            )
        except RetrievalContractMismatchError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="search.error", msg=str(e), data={"code": e.code})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise retrieval_contract_mismatch_http_exception(e) from e
        except RerankerFailedError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="search.error", msg=str(e), data={"kind": "reranker"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise reranker_failed_http_exception(e) from e
        except RequiredRetrievalLegError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="search.error", msg=str(e), data={"kind": "retrieval"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise required_retrieval_leg_http_exception(e) from e
        except Exception as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="search.error", msg=str(e), data={})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise_required_dependency_unavailable_if_applicable(e, boundary="Search retrieval")
            raise
        dt_ms = (time.perf_counter() - t0) * 1000.0

        update_route_summary(
            corpus_ids=[request.repo_id],
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            vector_results=int((fusion.last_debug or {}).get("fusion_vector_results") or 0),
            sparse_results=int((fusion.last_debug or {}).get("fusion_sparse_results") or 0),
            graph_results=int((fusion.last_debug or {}).get("fusion_graph_hydrated_chunks") or 0),
            final_results=len(matches),
            llm_used=False,
            llm_error=None,
        )

        debug = {
            "vector_enabled": bool(request.include_vector),
            "sparse_enabled": bool(request.include_sparse),
            "graph_enabled": bool(request.include_graph),
            "observability_run_id": run_id,
            "observability_trace_id": current_trace_payload_fields().get("trace_id"),
            "observability_correlation_id": current_trace_payload_fields().get("correlation_id"),
            **(fusion.last_debug or {}),
        }

        try:
            if getattr(cfg.tracing, "tracing_enabled", True):
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

        if trace_enabled:
            await trace_store.add_event(
                run_id,
                kind="search.response",
                data={"matches_count": len(matches), "latency_ms": float(dt_ms)},
            )
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id, ended_at_ms=int(time.time() * 1000))

        return SearchResponse(
            query=request.query,
            matches=matches,
            fusion_method=cfg.fusion.method,
            reranker_mode=cfg.reranking.reranker_mode,
            latency_ms=dt_ms,
            debug=debug,
        )


@router.post("/answer", response_model=AnswerResponse, responses=ANSWER_RUNTIME_UNAVAILABLE_RESPONSES)
async def answer(request: AnswerRequest, response: Response) -> AnswerResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    # Validate corpus exists (return 404 rather than bubbling CorpusNotFoundError as 500).
    cfg = await _validated_scoped_config(request.repo_id, boundary="Answer API")
    fusion = TriBridFusion()
    request_cache_mode = _normalize_cache_mode(request.cache_mode)
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()

    with start_request_observation(
        config=cfg,
        route_name="answer",
        path="/api/answer",
        method="POST",
        run_id=run_id,
        repo_id=request.repo_id,
    ):
        apply_default_links(cfg)
        for key, value in current_header_values().items():
            response.headers[key] = value
        trace_enabled = await trace_store.start(
            run_id=run_id,
            repo_id=request.repo_id,
            started_at_ms=started_at_ms,
            config=cfg,
        )
        if trace_enabled:
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.add_event(
                run_id,
                kind="answer.request",
                data={
                    "repo_id": request.repo_id,
                    "query": request.query,
                    "include_vector": bool(request.include_vector),
                    "include_sparse": bool(request.include_sparse),
                    "include_graph": bool(request.include_graph),
                    "top_k": int(request.top_k),
                    "stream": False,
                },
            )

        t0 = time.perf_counter()
        try:
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
                cache_mode=request_cache_mode,
            )
        except RetrievalContractMismatchError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"code": e.code})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise retrieval_contract_mismatch_http_exception(e) from e
        except RerankerFailedError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"kind": "reranker"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise reranker_failed_http_exception(e) from e
        except RequiredRetrievalLegError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"kind": "retrieval"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise required_retrieval_leg_http_exception(e) from e
        except AnswerRetrievalFailedError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"kind": "retrieval"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise answer_retrieval_failed_http_exception(e, operation="Answer retrieval") from e
        except Exception as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise_required_dependency_unavailable_if_applicable(e, boundary="Answer retrieval")
            # Generation failed after retrieval: the same typed 503 the chat lane raises,
            # never a "retrieval-only" 200 assembled from the sources.
            raise generation_unavailable_http_exception(e, operation="Answer generation") from e

        dt_ms = (time.perf_counter() - t0) * 1000.0

        set_provider_route(provider_info)
        update_route_summary(
            corpus_ids=[request.repo_id],
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            vector_results=int(debug.vector_results or 0),
            sparse_results=int(debug.sparse_results or 0),
            graph_results=int(debug.graph_hydrated_chunks or 0),
            final_results=len(sources),
            llm_used=bool(debug.llm_used),
            llm_error=debug.llm_error,
        )

        if trace_enabled:
            await trace_store.add_event(
                run_id,
                kind="answer.response",
                data={
                    "sources_count": len(sources),
                    "latency_ms": float(dt_ms),
                    "model": str(provider_info.model) if provider_info is not None else "",
                },
            )
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id, ended_at_ms=int(time.time() * 1000))

        if provider_info is None or not debug.llm_used:
            raise HTTPException(status_code=500, detail="Answer completed without a generation provider")
        model = provider_info.model

        return AnswerResponse(
            query=request.query,
            answer=text,
            sources=sources,
            model=model,
            tokens_used=0,
            latency_ms=float(dt_ms),
            debug=debug,
        )


async def _close_answer_trace(run_id: str, ended_at_ms: int | None) -> None:
    trace_store = get_trace_store()
    await trace_store.annotate(run_id, **current_trace_payload_fields())
    await trace_store.end(run_id, ended_at_ms=ended_at_ms)


@router.post("/answer/stream", responses=ANSWER_STREAM_RUNTIME_UNAVAILABLE_RESPONSES)
async def answer_stream(request: AnswerRequest) -> StreamingResponse:
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Query must not be empty")

    # Validate corpus exists (return 404 rather than bubbling CorpusNotFoundError as 500).
    cfg = await _validated_scoped_config(request.repo_id, boundary="Streaming answer API")
    fusion = TriBridFusion()
    request_cache_mode = _normalize_cache_mode(request.cache_mode)
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()

    # The retrieval below and the streamed body run in different asyncio tasks (Starlette
    # iterates a StreamingResponse body in its own anyio task), so each makes the request
    # span current for its own half and the span is ended once, by whichever half ends the
    # request. Attaching in one and detaching in the other logged `Failed to detach context`
    # for every streamed request.
    observation = start_streaming_observation(
        config=cfg,
        route_name="answer_stream",
        path="/api/answer/stream",
        method="POST",
        run_id=run_id,
        repo_id=request.repo_id,
    )
    setup_scope = observation.scope()
    setup_scope.__enter__()
    apply_default_links(cfg)
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=request.repo_id,
        started_at_ms=started_at_ms,
        config=cfg,
    )
    if trace_enabled:
        await trace_store.annotate(run_id, **current_trace_payload_fields())
        await trace_store.add_event(
            run_id,
            kind="answer.request",
            data={
                "repo_id": request.repo_id,
                "query": request.query,
                "include_vector": bool(request.include_vector),
                "include_sparse": bool(request.include_sparse),
                "include_graph": bool(request.include_graph),
                "top_k": int(request.top_k),
                "stream": True,
            },
        )

    store = get_conversation_store()
    conv = store.get_or_create(None)
    try:
        prefetched_chunks, _ = await retrieve_best_effort(
            query=request.query,
            corpus_id=request.repo_id,
            config=cfg,
            fusion=fusion,
            include_vector=bool(request.include_vector),
            include_sparse=bool(request.include_sparse),
            include_graph=bool(request.include_graph),
            top_k=int(request.top_k),
            cache_mode=request_cache_mode,
        )
    except asyncio.CancelledError:
        # Cancelled while retrieval was pending: the wrapper that would close the trace and
        # the span has not started yet, so close them here and re-raise.
        if trace_enabled:
            try:
                await asyncio.shield(trace_store.end(run_id))
            except asyncio.CancelledError:
                pass
        setup_scope.__exit__(None, None, None)
        observation.finish((None, None, None))
        raise
    except RetrievalContractMismatchError as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"code": e.code})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        setup_scope.__exit__(type(e), e, e.__traceback__)
        observation.finish((type(e), e, e.__traceback__))
        raise retrieval_contract_mismatch_http_exception(e) from e
    except RerankerFailedError as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"kind": "reranker"})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        setup_scope.__exit__(type(e), e, e.__traceback__)
        observation.finish((type(e), e, e.__traceback__))
        raise reranker_failed_http_exception(e) from e
    except RequiredRetrievalLegError as e:
        # Same close-out as its two sibling branches: the generator never runs on any of
        # them, so this is the only place that can end the span and the trace.
        if trace_enabled:
            await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        setup_scope.__exit__(type(e), e, e.__traceback__)
        observation.finish((type(e), e, e.__traceback__))
        raise required_retrieval_leg_http_exception(e) from e
    except AnswerRetrievalFailedError as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={"kind": "retrieval"})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        setup_scope.__exit__(type(e), e, e.__traceback__)
        observation.finish((type(e), e, e.__traceback__))
        raise answer_retrieval_failed_http_exception(e, operation="Answer stream retrieval") from e
    except Exception as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        setup_scope.__exit__(type(e), e, e.__traceback__)
        observation.finish((type(e), e, e.__traceback__))
        raise_required_dependency_unavailable_if_applicable(e, boundary="Streaming answer retrieval")
        raise HTTPException(status_code=500, detail="Streaming answer retrieval failed") from e

    async def wrapped_stream() -> AsyncIterator[str]:
        ended_at_ms: int | None = None
        caught_exc: tuple[type[BaseException] | None, BaseException | None, TracebackType | None] = (None, None, None)
        # This is the task that owns the rest of the request, so it attaches and detaches
        # the span itself rather than inheriting a token from the endpoint coroutine.
        stream_scope = observation.scope()
        stream_scope.__enter__()
        try:
            async for sse in stream_answer_best_effort(
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
                cache_mode=request_cache_mode,
                prefetched_chunks=prefetched_chunks,
                conversation_id=conv.id,
                run_id=run_id,
                started_at_ms=started_at_ms,
            ):
                if not sse.startswith("data: "):
                    yield sse
                    continue
                try:
                    payload = json.loads(sse.replace("data: ", "").strip())
                except Exception:
                    yield sse
                    continue
                if payload.get("type") != "done":
                    yield sse
                    continue

                ended_at_ms = int(time.time() * 1000)

                provider_obj: ChatProviderInfo | None = None
                raw_provider = payload.get("provider")
                if isinstance(raw_provider, dict):
                    try:
                        provider_obj = ChatProviderInfo.model_validate(raw_provider)
                    except Exception:
                        provider_obj = None
                set_provider_route(provider_obj)

                debug_obj: ChatDebugInfo | None = None
                raw_debug = payload.get("debug")
                if isinstance(raw_debug, dict):
                    try:
                        debug_obj = ChatDebugInfo.model_validate(raw_debug)
                    except Exception:
                        debug_obj = None

                update_route_summary(
                    corpus_ids=[request.repo_id],
                    include_vector=bool(request.include_vector),
                    include_sparse=bool(request.include_sparse),
                    include_graph=bool(request.include_graph),
                    vector_results=int(getattr(debug_obj, "vector_results", 0) or 0),
                    sparse_results=int(getattr(debug_obj, "sparse_results", 0) or 0),
                    graph_results=int(getattr(debug_obj, "graph_hydrated_chunks", 0) or 0),
                    final_results=len(payload.get("sources") or []),
                    llm_used=bool(getattr(debug_obj, "llm_used", True)),
                    llm_error=getattr(debug_obj, "llm_error", None),
                )

                if trace_enabled:
                    await trace_store.add_event(
                        run_id,
                        kind=(
                            "answer.error"
                            if debug_obj is not None and not bool(debug_obj.llm_used)
                            else "answer.response"
                        ),
                        data={
                            "sources_count": len(payload.get("sources") or []),
                            "latency_ms": float(max(0, ended_at_ms - started_at_ms)),
                            "model": str(provider_obj.model) if provider_obj is not None else "",
                        },
                    )
                    await trace_store.annotate(run_id, **current_trace_payload_fields())

                yield sse
        except Exception as e:
            caught_exc = (type(e), e, e.__traceback__)
            if trace_enabled:
                await trace_store.add_event(run_id, kind="answer.error", msg=str(e), data={})
            raise
        finally:
            if trace_enabled:
                # Shielded: a cancellation delivered here must not leave the trace open.
                try:
                    await asyncio.shield(_close_answer_trace(run_id, ended_at_ms))
                except asyncio.CancelledError:
                    pass
            observation.finish(caught_exc)
            stream_scope.__exit__(*caught_exc)

    # Built while the setup scope is still active: `current_header_values` reads the
    # observation off the contextvar this task set.
    response = StreamingResponse(
        wrapped_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            **current_header_values(),
        },
    )
    setup_scope.__exit__(None, None, None)
    return response
