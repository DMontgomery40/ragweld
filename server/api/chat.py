"""Chat API endpoints (Chat 2.0)."""
import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from starlette.responses import StreamingResponse

from server.api.dependency_errors import (
    raise_postgres_unavailable_if_applicable,
    raise_required_dependency_unavailable_if_applicable,
)
from server.api.generation_errors import (
    CHAT_RUNTIME_UNAVAILABLE_RESPONSES,
    generation_unavailable_http_exception,
)
from server.api.retrieval_errors import (
    RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
    required_retrieval_leg_http_exception,
    retrieval_contract_mismatch_http_exception,
)
from server.chat.handler import ChatGenerationError, chat_once
from server.chat.handler import chat_stream as chat_stream_handler
from server.chat.model_discovery import discover_litellm_models
from server.chat.recall_indexer import index_recall_conversation
from server.chat.source_router import resolve_sources
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder, configure_postgres_embedding_cache_backend
from server.models.chat import ChatRequest, ChatResponse, Message
from server.models.tribrid_config_model import (
    ChatModelInfo,
    ChatModelsResponse,
    ChatMultimodalConfig,
    ImageAttachment,
    ProviderHealth,
    ProvidersHealthResponse,
    RecallIndexRequest,
    RecallIndexResponse,
    RecallStatusResponse,
    TracesLatestResponse,
    TriBridConfig,
)
from server.observability.runtime import (
    apply_default_links,
    current_header_values,
    current_trace_payload_fields,
    set_provider_route,
    start_request_observation,
    update_route_summary,
)
from server.retrieval.errors import RequiredRetrievalLegError, RetrievalContractMismatchError
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.conversation_store import get_conversation_store
from server.services.rag import FusionProtocol, build_chat_debug_info
from server.services.traces import get_trace_store

router = APIRouter(tags=["chat"])

logger = logging.getLogger(__name__)


# Dependency holders (can be overridden for testing)
_config: TriBridConfig | None = None
_fusion: FusionProtocol | None = None

def get_config() -> TriBridConfig:
    """Get the current config. Override with set_config() for testing."""
    if _config is not None:
        return _config
    # Default config - LAW provides all defaults via default_factory
    return TriBridConfig()


def get_fusion() -> FusionProtocol:
    """Get the fusion retrieval service. Override with set_fusion() for testing."""
    if _fusion is not None:
        return _fusion
    # Default: real tri-brid fusion over Postgres + Neo4j using per-corpus config.
    return TriBridFusion()


def set_config(config: TriBridConfig | None) -> None:
    """Set the config for dependency injection (primarily for testing)."""
    global _config
    _config = config


def set_fusion(fusion: FusionProtocol | None) -> None:
    """Set the fusion service for dependency injection (primarily for testing)."""
    global _fusion
    _fusion = fusion


def _primary_corpus_id_from_request(request: ChatRequest) -> str | None:
    """Resolve a best-effort config scope for chat settings."""
    corpus_ids = resolve_sources(request.sources)
    if not corpus_ids:
        return None
    # Prefer a non-recall corpus as the primary scope.
    for cid in corpus_ids:
        if cid and cid != "recall_default":
            return cid
    return corpus_ids[0]


def _approx_base64_bytes(s: str) -> int:
    b64 = (s or "").strip()
    if not b64:
        return 0
    padding = 2 if b64.endswith("==") else 1 if b64.endswith("=") else 0
    return max(0, (len(b64) * 3) // 4 - padding)


def _validate_chat_images(images: list[ImageAttachment], cfg: ChatMultimodalConfig) -> None:
    if not images:
        return
    if not bool(cfg.vision_enabled):
        raise HTTPException(status_code=400, detail="Vision is disabled (config.chat.multimodal.vision_enabled=false)")

    max_images = int(getattr(cfg, "max_images_per_message", 5) or 5)
    if len(images) > max_images:
        raise HTTPException(status_code=400, detail=f"Too many images (max {max_images})")

    max_bytes = int(getattr(cfg, "max_image_size_mb", 20) or 20) * 1024 * 1024
    supported = {str(x).strip().lower() for x in (getattr(cfg, "supported_formats", []) or []) if str(x).strip()}

    for idx, att in enumerate(images):
        mime = str(getattr(att, "mime_type", "") or "").strip().lower()
        if not mime.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"images[{idx}].mime_type must be image/*")

        ext = mime.split("/", 1)[1].strip().lower() if "/" in mime else ""
        if ext == "jpg":
            ext = "jpeg"
        if supported:
            allowed = supported | ({"jpeg"} if "jpg" in supported else set()) | ({"jpg"} if "jpeg" in supported else set())
            if ext and ext not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"images[{idx}] format '{ext}' not supported (allowed: {sorted(allowed)})",
                )

        b64 = getattr(att, "base64", None)
        if isinstance(b64, str) and b64.strip():
            b64s = b64.strip()
            if b64s.startswith("data:") or "base64," in b64s:
                raise HTTPException(
                    status_code=400,
                    detail=f"images[{idx}].base64 must be raw base64 (no data: prefix)",
                )
            if _approx_base64_bytes(b64s) > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"images[{idx}] too large (max {int(max_bytes / (1024 * 1024))} MB)",
                )


async def _append_chat_query_log_entry(
    *,
    config: TriBridConfig,
    fusion: FusionProtocol,
    event_id: str,
    conversation_id: str,
    corpus_ids: list[str],
    query: str,
    top_paths: list[str],
) -> None:
    """Best-effort query log append for triplet mining correlation."""
    if int(getattr(config.tracing, "tracing_enabled", 1) or 0) != 1:
        return

    from server.observability.query_log import append_query_log

    fusion_debug = getattr(fusion, "last_debug", None) or {}
    rag_debug = fusion_debug.get("chat_rag_fusion") if isinstance(fusion_debug, dict) else None
    if not isinstance(rag_debug, dict):
        rag_debug = fusion_debug if isinstance(fusion_debug, dict) else {}

    await append_query_log(
        config,
        entry={
            "event_id": event_id,
            "kind": "chat",
            "conversation_id": conversation_id,
            "corpus_ids": corpus_ids,
            "query": query,
            "reranker_mode": str(rag_debug.get("rerank_mode") or str(config.reranking.reranker_mode or "")),
            "rerank_ok": bool(rag_debug.get("rerank_ok", True)),
            "rerank_applied": bool(rag_debug.get("rerank_applied", False)),
            "rerank_skipped_reason": rag_debug.get("rerank_skipped_reason"),
            "rerank_error": rag_debug.get("rerank_error"),
            "rerank_candidates_reranked": int(rag_debug.get("rerank_candidates_reranked") or 0),
            "top_paths": list(top_paths[:5]),
        },
    )


@router.get("/traces/latest", response_model=TracesLatestResponse)
async def get_latest_trace(
    repo: str | None = Query(default=None, description="Optional corpus_id to filter by"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    run_id: str | None = Query(default=None, description="Optional run_id to fetch"),
) -> TracesLatestResponse:
    """Return the latest local trace (dev tooling)."""
    repo_id = (repo or corpus_id or "").strip() or None
    store = get_trace_store()
    return await store.latest(repo=repo_id, run_id=(run_id or "").strip() or None)


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses=CHAT_RUNTIME_UNAVAILABLE_RESPONSES,
)
async def chat(request: ChatRequest, response: Response) -> ChatResponse:
    """Process a chat message and return a response (Chat 2.0)."""
    store = get_conversation_store()
    conv = store.get_or_create(request.conversation_id)

    # Choose config scope from selected sources (best-effort).
    primary = _primary_corpus_id_from_request(request)
    if _config is not None:
        config = _config
    else:
        try:
            config = await load_scoped_config(repo_id=primary) if primary else TriBridConfig()
        except CorpusNotFoundError:
            config = TriBridConfig()
        except Exception as e:
            raise_postgres_unavailable_if_applicable(e, boundary="Chat config load")
            raise

    _validate_chat_images(list(request.images or []), config.chat.multimodal)

    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_repo_id = primary or (resolve_sources(request.sources)[0] if resolve_sources(request.sources) else "")
    with start_request_observation(
        config=config,
        route_name="chat",
        path="/api/chat",
        method="POST",
        run_id=run_id,
        repo_id=trace_repo_id,
    ):
        apply_default_links(config)
        for key, value in current_header_values().items():
            response.headers[key] = value

        trace_enabled = await trace_store.start(
            run_id=run_id,
            repo_id=trace_repo_id,
            started_at_ms=started_at_ms,
            config=config,
        )
        if trace_enabled:
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.add_event(
                run_id,
                kind="chat.request",
                data={
                    "conversation_id": request.conversation_id,
                    "corpus_ids": resolve_sources(request.sources),
                    "include_vector": bool(request.include_vector),
                    "include_sparse": bool(request.include_sparse),
                    "include_graph": bool(request.include_graph),
                    "top_k_override": request.top_k,
                    "stream": False,
                    "images_count": len(list(request.images or [])),
                },
            )

        try:
            response_text, sources, provider_id, recall_plan, provider_info, llm_used, llm_error = await chat_once(
                request=request,
                config=config,
                fusion=fusion,
                conversation=conv,
            )
            ended_at_ms = int(time.time() * 1000)
            debug = build_chat_debug_info(
                config=config,
                fusion=fusion,
                include_vector=bool(request.include_vector),
                include_sparse=bool(request.include_sparse),
                include_graph=bool(request.include_graph),
                top_k=request.top_k,
                sources=sources,
                recall_plan=recall_plan,
                provider=provider_info,
            ).model_copy(update={"llm_used": bool(llm_used), "llm_error": llm_error})

            set_provider_route(provider_info)
            update_route_summary(
                corpus_ids=resolve_sources(request.sources),
                include_vector=bool(request.include_vector),
                include_sparse=bool(request.include_sparse),
                include_graph=bool(request.include_graph),
                vector_results=debug.vector_results,
                sparse_results=debug.sparse_results,
                graph_results=debug.graph_hydrated_chunks,
                final_results=len(sources),
                llm_used=bool(llm_used),
                llm_error=llm_error,
            )

            if trace_enabled:
                try:
                    fusion_debug = getattr(fusion, "last_debug", None) or {}
                    rag_debug = fusion_debug.get("chat_rag_fusion") if isinstance(fusion_debug, dict) else None
                    if not isinstance(rag_debug, dict):
                        rag_debug = fusion_debug if isinstance(fusion_debug, dict) else {}

                    recall_id = str(config.chat.recall.default_corpus_id or "recall_default")
                    rag_sources = [
                        s
                        for s in sources
                        if str((s.metadata or {}).get("corpus_id") or "").strip() != recall_id
                    ]

                    await trace_store.add_event(
                        run_id,
                        kind="reranker.rank",
                        data={
                            "enabled": bool(rag_debug.get("rerank_enabled")),
                            "mode": str(rag_debug.get("rerank_mode") or config.reranking.reranker_mode or "none"),
                            "ok": bool(rag_debug.get("rerank_ok", True)),
                            "applied": bool(rag_debug.get("rerank_applied", False)),
                            "skipped_reason": rag_debug.get("rerank_skipped_reason"),
                            "error": rag_debug.get("rerank_error"),
                            "candidates_reranked": int(rag_debug.get("rerank_candidates_reranked") or 0),
                            "output_topK": len(rag_sources),
                            "scores": [
                                {"path": s.file_path, "score": float(s.score)}
                                for s in (rag_sources[: min(len(rag_sources), 50)])
                            ],
                        },
                    )
                except Exception:
                    pass

                await trace_store.add_event(
                    run_id,
                    kind="retrieval.fusion",
                    data={
                        "fusion_debug": getattr(fusion, "last_debug", None) or {},
                        "chat_debug": debug.model_dump(mode="serialization", by_alias=True),
                        "sources": [
                            {
                                "file_path": s.file_path,
                                "start_line": int(s.start_line),
                                "end_line": int(s.end_line),
                                "score": float(s.score),
                                "source": str(s.source),
                            }
                            for s in sources
                        ],
                    },
                )
                await trace_store.add_event(
                    run_id,
                    kind="chat.response",
                    data={
                        "sources_count": len(sources),
                        "tokens_used": 0,
                    },
                )
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id, ended_at_ms=ended_at_ms)

            try:
                await _append_chat_query_log_entry(
                    config=config,
                    fusion=fusion,
                    event_id=run_id,
                    conversation_id=conv.id,
                    corpus_ids=resolve_sources(request.sources),
                    query=request.message,
                    top_paths=[s.file_path for s in sources[:5]],
                )
            except Exception:
                pass

            user_msg = Message(role="user", content=request.message)
            assistant_msg = Message(role="assistant", content=response_text)
            store.add_message(conv.id, user_msg, None)
            store.add_message(conv.id, assistant_msg, provider_id)

            corpus_ids = resolve_sources(request.sources)
            if (
                config.chat.recall.enabled
                and config.chat.recall.auto_index
                and (config.chat.recall.default_corpus_id in set(corpus_ids))
            ):
                async def _do_index() -> None:
                    delay = int(config.chat.recall.index_delay_seconds or 0)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    pg = PostgresClient(config.indexing.postgres_url)
                    await pg.connect()
                    embedder = Embedder(config.embedding)
                    configure_postgres_embedding_cache_backend(embedder, pg)
                    try:
                        await index_recall_conversation(
                            pg,
                            conversation_id=conv.id,
                            messages=store.get_messages(conv.id),
                            config=config.chat.recall,
                            embedder=embedder,
                            ts_config="english",
                        )
                    except RetrievalContractMismatchError as e:
                        logger.warning(
                            "Recall auto-index blocked by embedding contract mismatch: %s", e
                        )

                asyncio.create_task(_do_index())

            return ChatResponse(
                run_id=run_id,
                started_at_ms=started_at_ms,
                ended_at_ms=ended_at_ms,
                debug=debug,
                conversation_id=conv.id,
                message=assistant_msg,
                sources=sources,
                tokens_used=0,
            )

        except RetrievalContractMismatchError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={"code": e.code})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise retrieval_contract_mismatch_http_exception(e) from e
        except RequiredRetrievalLegError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={"kind": "retrieval"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise required_retrieval_leg_http_exception(e) from e
        except ChatGenerationError as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={"kind": "generation"})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise generation_unavailable_http_exception(e, operation="Chat generation") from e
        except Exception as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id)
            raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/chat/stream",
    responses=RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES,
)
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream a chat response using Server-Sent Events.

    Returns SSE events with:
    - type: "text" - content chunks as they arrive
    - type: "done" - final event with sources
    - type: "error" - if something goes wrong
    """
    store = get_conversation_store()
    conv = store.get_or_create(request.conversation_id)

    primary = _primary_corpus_id_from_request(request)
    if _config is not None:
        config = _config
    else:
        try:
            config = await load_scoped_config(repo_id=primary) if primary else TriBridConfig()
        except CorpusNotFoundError:
            config = TriBridConfig()
        except Exception as e:
            raise_postgres_unavailable_if_applicable(e, boundary="Chat stream config load")
            raise

    _validate_chat_images(list(request.images or []), config.chat.multimodal)

    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_repo_id = primary or (resolve_sources(request.sources)[0] if resolve_sources(request.sources) else "")
    obs_cm = start_request_observation(
        config=config,
        route_name="chat_stream",
        path="/api/chat/stream",
        method="POST",
        run_id=run_id,
        repo_id=trace_repo_id,
    )
    obs_cm.__enter__()
    apply_default_links(config)
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=trace_repo_id,
        started_at_ms=started_at_ms,
        config=config,
    )
    if trace_enabled:
        await trace_store.annotate(run_id, **current_trace_payload_fields())
        await trace_store.add_event(
            run_id,
            kind="chat.request",
            data={
                "conversation_id": request.conversation_id,
                "corpus_ids": resolve_sources(request.sources),
                "include_vector": bool(request.include_vector),
                "include_sparse": bool(request.include_sparse),
                "include_graph": bool(request.include_graph),
                "top_k_override": request.top_k,
                "stream": True,
                "images_count": len(list(request.images or [])),
            },
        )

    # Store the user message before streaming
    user_msg = Message(role="user", content=request.message)
    store.add_message(conv.id, user_msg, None)

    handler_stream = chat_stream_handler(
        request=request,
        config=config,
        fusion=fusion,
        conversation=conv,
        run_id=run_id,
        started_at_ms=started_at_ms,
    )
    try:
        first_sse = await anext(handler_stream)
    except StopAsyncIteration:
        first_sse = None
    except Exception as e:
        try:
            store.remove_last_message(conv.id, role="user", content=request.message)
        except Exception:
            pass
        if trace_enabled:
            await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            await trace_store.annotate(run_id, **current_trace_payload_fields())
            await trace_store.end(run_id)
        obs_cm.__exit__(type(e), e, e.__traceback__)
        if isinstance(e, RetrievalContractMismatchError):
            raise retrieval_contract_mismatch_http_exception(e) from e
        if isinstance(e, RequiredRetrievalLegError):
            raise required_retrieval_leg_http_exception(e) from e
        raise_required_dependency_unavailable_if_applicable(e, boundary="Chat stream retrieval")
        raise HTTPException(status_code=500, detail="Chat stream initialization failed") from e

    async def primed_handler_stream() -> Any:
        if first_sse is not None:
            yield first_sse
        async for sse in handler_stream:
            yield sse

    async def wrapped_stream() -> Any:
        ended_at_ms: int | None = None
        accumulated = ""
        query_log_appended = False
        assistant_persisted = False
        caught_exc: tuple[type[BaseException] | None, BaseException | None, Any] = (None, None, None)
        try:
            async for sse in primed_handler_stream():
                if not sse.startswith("data: "):
                    yield sse
                    continue
                try:
                    payload = json.loads(sse.replace("data: ", "").strip())
                except Exception:
                    yield sse
                    continue

                typ = payload.get("type")
                if typ == "text":
                    delta = payload.get("content")
                    if isinstance(delta, str):
                        accumulated += delta
                    yield sse
                    continue

                if typ == "done":
                    ended_at_ms = int(time.time() * 1000)

                    # Persist assistant message now that we have full content.
                    assistant_msg = Message(role="assistant", content=accumulated)
                    provider_id: str | None = None
                    raw_provider_id = payload.get("provider_response_id")
                    if isinstance(raw_provider_id, str) and raw_provider_id.strip():
                        provider_id = raw_provider_id.strip()
                    store.add_message(conv.id, assistant_msg, provider_id)
                    assistant_persisted = True

                    # Best-effort Recall indexing (only when recall_default is selected).
                    corpus_ids = resolve_sources(request.sources)
                    if (
                        config.chat.recall.enabled
                        and config.chat.recall.auto_index
                        and (config.chat.recall.default_corpus_id in set(corpus_ids))
                    ):
                        async def _do_index() -> None:
                            delay = int(config.chat.recall.index_delay_seconds or 0)
                            if delay > 0:
                                await asyncio.sleep(delay)
                            pg = PostgresClient(config.indexing.postgres_url)
                            await pg.connect()
                            embedder = Embedder(config.embedding)
                            configure_postgres_embedding_cache_backend(embedder, pg)
                            try:
                                await index_recall_conversation(
                                    pg,
                                    conversation_id=conv.id,
                                    messages=store.get_messages(conv.id),
                                    config=config.chat.recall,
                                    embedder=embedder,
                                    ts_config="english",
                                )
                            except RetrievalContractMismatchError as e:
                                logger.warning(
                                    "Recall auto-index blocked by embedding contract mismatch: %s", e
                                )

                        asyncio.create_task(_do_index())

                    # Attach debug info for frontend compatibility.
                    from server.models.chat_config import RecallPlan as RecallPlanModel
                    from server.models.retrieval import ChunkMatch as ChunkMatchModel

                    src_objs: list[ChunkMatchModel] = []
                    for s in payload.get("sources") or []:
                        try:
                            src_objs.append(ChunkMatchModel.model_validate(s))
                        except Exception:
                            continue

                    raw_recall_plan = payload.get("recall_plan")
                    recall_plan_obj = None
                    if isinstance(raw_recall_plan, dict):
                        try:
                            recall_plan_obj = RecallPlanModel.model_validate(raw_recall_plan)
                        except Exception:
                            recall_plan_obj = None

                    # Provider route info (optional).
                    from server.models.tribrid_config_model import (
                        ChatProviderInfo as ChatProviderInfoModel,
                    )

                    provider_obj = None
                    raw_provider = payload.get("provider")
                    if isinstance(raw_provider, dict):
                        try:
                            provider_obj = ChatProviderInfoModel.model_validate(raw_provider)
                        except Exception:
                            provider_obj = None
                    set_provider_route(provider_obj)

                    debug = build_chat_debug_info(
                        config=config,
                        fusion=fusion,
                        include_vector=bool(request.include_vector),
                        include_sparse=bool(request.include_sparse),
                        include_graph=bool(request.include_graph),
                        top_k=request.top_k,
                        sources=src_objs,
                        recall_plan=recall_plan_obj,
                        provider=provider_obj,
                    )
                    llm_used_raw = payload.get("llm_used")
                    llm_error_raw = payload.get("llm_error")
                    llm_used = bool(llm_used_raw) if isinstance(llm_used_raw, bool) else True
                    llm_error: str | None = None
                    if isinstance(llm_error_raw, str) and llm_error_raw.strip():
                        llm_error = llm_error_raw.strip()
                    debug = debug.model_copy(update={"llm_used": llm_used, "llm_error": llm_error})
                    update_route_summary(
                        corpus_ids=resolve_sources(request.sources),
                        include_vector=bool(request.include_vector),
                        include_sparse=bool(request.include_sparse),
                        include_graph=bool(request.include_graph),
                        vector_results=debug.vector_results,
                        sparse_results=debug.sparse_results,
                        graph_results=debug.graph_hydrated_chunks,
                        final_results=len(src_objs),
                        llm_used=llm_used,
                        llm_error=llm_error,
                    )
                    payload["debug"] = debug.model_dump(mode="serialization", by_alias=True)

                    if not query_log_appended:
                        try:
                            await _append_chat_query_log_entry(
                                config=config,
                                fusion=fusion,
                                event_id=run_id,
                                conversation_id=conv.id,
                                corpus_ids=resolve_sources(request.sources),
                                query=request.message,
                                top_paths=[s.file_path for s in src_objs[:5]],
                            )
                            query_log_appended = True
                        except Exception:
                            pass

                    if trace_enabled:
                        await trace_store.add_event(
                            run_id,
                            kind="retrieval.fusion",
                            data={
                                "fusion_debug": getattr(fusion, "last_debug", None) or {},
                                "sources": payload.get("sources") or [],
                            },
                        )
                        await trace_store.add_event(
                            run_id,
                            kind="chat.response",
                            data={"sources_count": len(payload.get("sources") or [])},
                        )
                        await trace_store.annotate(run_id, **current_trace_payload_fields())

                    yield f"data: {json.dumps(payload)}\n\n"
                    continue

                if typ == "error":
                    raw_message = payload.get("message")
                    if isinstance(raw_message, str) and raw_message.strip():
                        accumulated = accumulated.strip() or f"Error: {raw_message.strip()}"
                    yield sse
                    continue

                yield sse
        except Exception as e:
            caught_exc = (type(e), e, e.__traceback__)
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            raise
        finally:
            if not assistant_persisted:
                if accumulated.strip():
                    try:
                        store.add_message(conv.id, Message(role="assistant", content=accumulated), None)
                        assistant_persisted = True
                    except Exception:
                        pass
                else:
                    try:
                        store.remove_last_message(
                            conv.id,
                            role="user",
                            content=request.message,
                        )
                    except Exception:
                        pass
            if trace_enabled:
                await trace_store.annotate(run_id, **current_trace_payload_fields())
                await trace_store.end(run_id, ended_at_ms=ended_at_ms)
            obs_cm.__exit__(*caught_exc)

    return StreamingResponse(
        wrapped_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            **current_header_values(),
        },
    )


@router.get("/chat/models", response_model=ChatModelsResponse)
async def list_chat_models(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope provider config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ChatModelsResponse:
    """Return authenticated LiteLLM aliases available to ordinary Chat users."""
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    if _config is not None:
        cfg = _config
    else:
        try:
            cfg = await load_scoped_config(repo_id=scope_id) if scope_id else TriBridConfig()
        except CorpusNotFoundError:
            cfg = TriBridConfig()

    try:
        discovered = await discover_litellm_models(cfg.chat.litellm)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    models: list[ChatModelInfo] = []
    for row in discovered:
        model_id = str(row.get("id") or "").strip()
        if not model_id or model_id == "ragweld-openrouter-smoke":
            continue
        models.append(
            ChatModelInfo(
                id=model_id,
                override=f"litellm:{model_id}",
                provider="LiteLLM",
                provider_key="litellm",
                catalog_model=None,
                components=["GEN"],
                source="litellm",
                provider_type="litellm",
                base_url=str(row.get("base_url") or "") or None,
                supports_vision=False,
            )
        )
    return ChatModelsResponse(models=models)


@router.get("/chat/health", response_model=ProvidersHealthResponse)
async def chat_health(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope provider config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ProvidersHealthResponse:
    """Report the one application-visible generation gateway."""
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    if _config is not None:
        cfg = _config
    else:
        try:
            cfg = await load_scoped_config(repo_id=scope_id) if scope_id else TriBridConfig()
        except CorpusNotFoundError:
            cfg = TriBridConfig()

    try:
        rows = await discover_litellm_models(cfg.chat.litellm)
        base_url = str(rows[0].get("base_url") or cfg.chat.litellm.base_url) if rows else cfg.chat.litellm.base_url
        health = ProviderHealth(
            provider="LiteLLM",
            kind="litellm",
            base_url=base_url,
            reachable=True,
            detail=None,
        )
    except RuntimeError as error:
        health = ProviderHealth(
            provider="LiteLLM",
            kind="litellm",
            base_url=cfg.chat.litellm.base_url,
            reachable=False,
            detail=str(error),
        )
    return ProvidersHealthResponse(providers=[health])


@router.post("/recall/index", response_model=RecallIndexResponse)
async def recall_index(request: RecallIndexRequest) -> RecallIndexResponse:
    """Manually index a conversation into Recall."""
    cfg = get_config()
    if not cfg.chat.recall.enabled:
        raise HTTPException(status_code=400, detail="Recall is disabled")

    store = get_conversation_store()
    msgs = store.get_messages(request.conversation_id)
    if not msgs:
        return RecallIndexResponse(ok=True, conversation_id=request.conversation_id, chunks_indexed=0)

    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    embedder = Embedder(cfg.embedding)
    configure_postgres_embedding_cache_backend(embedder, pg)
    try:
        n = await index_recall_conversation(
            pg,
            conversation_id=request.conversation_id,
            messages=msgs,
            config=cfg.chat.recall,
            embedder=embedder,
            ts_config="english",
        )
    except RetrievalContractMismatchError as e:
        raise retrieval_contract_mismatch_http_exception(e) from e
    return RecallIndexResponse(ok=True, conversation_id=request.conversation_id, chunks_indexed=int(n))


@router.get("/recall/status", response_model=RecallStatusResponse)
async def recall_status() -> RecallStatusResponse:
    """Return Recall corpus bootstrap/index status."""
    cfg = get_config()
    corpus_id = str(cfg.chat.recall.default_corpus_id or "recall_default")

    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    exists = await pg.get_corpus(corpus_id) is not None
    chunk_count = 0
    if exists:
        try:
            stats = await pg.get_index_stats(corpus_id)
            chunk_count = int(stats.total_chunks or 0)
        except Exception:
            chunk_count = 0

    return RecallStatusResponse(
        enabled=bool(cfg.chat.recall.enabled),
        corpus_id=corpus_id,
        exists=bool(exists),
        chunk_count=int(chunk_count),
    )


@router.get("/chat/history/{conversation_id}", response_model=list[Message])
async def get_chat_history(conversation_id: str) -> list[Message]:
    """Get the message history for a conversation."""
    store = get_conversation_store()
    messages = store.get_messages(conversation_id)
    return messages


@router.delete("/chat/history/{conversation_id}")
async def clear_chat_history(conversation_id: str) -> dict[str, Any]:
    """Clear a conversation's history."""
    store = get_conversation_store()
    cleared = store.clear(conversation_id)
    if not cleared:
        raise HTTPException(status_code=404, detail=f"Conversation not found: {conversation_id}")
    return {"status": "cleared", "conversation_id": conversation_id}
