"""Chat API endpoints (Chat 2.0)."""
import asyncio
import json
import os
import time
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from server.chat.handler import chat_once
from server.chat.handler import chat_stream as chat_stream_handler
from server.chat.model_discovery import discover_models
from server.chat.recall_indexer import index_recall_conversation
from server.chat.source_router import resolve_sources
from server.db.postgres import PostgresClient
from server.indexing.embedder import Embedder
from server.models.chat import ChatRequest, ChatResponse, Message
from server.models.tribrid_config_model import (
    ChatModelInfo,
    ChatModelsResponse,
    ProviderHealth,
    ProvidersHealthResponse,
    RecallIndexRequest,
    RecallIndexResponse,
    RecallStatusResponse,
    TracesLatestResponse,
    TriBridConfig,
)
from server.retrieval.fusion import TriBridFusion
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.conversation_store import get_conversation_store
from server.services.rag import FusionProtocol, build_chat_debug_info
from server.services.traces import get_trace_store

router = APIRouter(tags=["chat"])


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
    return TriBridFusion(vector=None, sparse=None, graph=None)


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


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
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

    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_repo_id = primary or (resolve_sources(request.sources)[0] if resolve_sources(request.sources) else "")
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=trace_repo_id,
        started_at_ms=started_at_ms,
        config=config,
    )
    if trace_enabled:
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
            },
        )

    try:
        response_text, sources, provider_id, recall_plan = await chat_once(
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
        )
        if trace_enabled:
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
            await trace_store.end(run_id, ended_at_ms=ended_at_ms)

        # Store the exchange
        user_msg = Message(role="user", content=request.message)
        assistant_msg = Message(role="assistant", content=response_text)
        store.add_message(conv.id, user_msg, None)
        store.add_message(conv.id, assistant_msg, provider_id)

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
                await index_recall_conversation(
                    pg,
                    conversation_id=conv.id,
                    messages=store.get_messages(conv.id),
                    config=config.chat.recall,
                    embedder=embedder,
                    ts_config="english",
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
            tokens_used=0,  # TODO: extract from result.usage() when available
        )

    except Exception as e:
        if trace_enabled:
            await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            await trace_store.end(run_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat/stream")
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

    fusion = get_fusion()
    run_id = str(uuid.uuid4())
    started_at_ms = int(time.time() * 1000)
    trace_store = get_trace_store()
    trace_repo_id = primary or (resolve_sources(request.sources)[0] if resolve_sources(request.sources) else "")
    trace_enabled = await trace_store.start(
        run_id=run_id,
        repo_id=trace_repo_id,
        started_at_ms=started_at_ms,
        config=config,
    )
    if trace_enabled:
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
            },
        )

    # Store the user message before streaming
    user_msg = Message(role="user", content=request.message)
    store.add_message(conv.id, user_msg, None)

    async def wrapped_stream() -> Any:
        ended_at_ms: int | None = None
        accumulated = ""
        try:
            async for sse in chat_stream_handler(
                request=request,
                config=config,
                fusion=fusion,
                conversation=conv,
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
                    store.add_message(conv.id, assistant_msg, None)

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
                            await index_recall_conversation(
                                pg,
                                conversation_id=conv.id,
                                messages=store.get_messages(conv.id),
                                config=config.chat.recall,
                                embedder=embedder,
                                ts_config="english",
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

                    debug = build_chat_debug_info(
                        config=config,
                        fusion=fusion,
                        include_vector=bool(request.include_vector),
                        include_sparse=bool(request.include_sparse),
                        include_graph=bool(request.include_graph),
                        top_k=request.top_k,
                        sources=src_objs,
                        recall_plan=recall_plan_obj,
                    )
                    payload["debug"] = debug.model_dump(mode="serialization", by_alias=True)

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

                    yield f"data: {json.dumps(payload)}\n\n"
                    continue

                yield sse
        except Exception as e:
            if trace_enabled:
                await trace_store.add_event(run_id, kind="chat.error", msg=str(e), data={})
            raise
        finally:
            if trace_enabled:
                await trace_store.end(run_id, ended_at_ms=ended_at_ms)

    return StreamingResponse(
        wrapped_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/models", response_model=ChatModelsResponse)
async def list_chat_models(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope provider config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ChatModelsResponse:
    """Return available chat models (cloud direct + OpenRouter + local)."""
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    if _config is not None:
        cfg = _config
    else:
        try:
            cfg = await load_scoped_config(repo_id=scope_id) if scope_id else TriBridConfig()
        except CorpusNotFoundError:
            cfg = TriBridConfig()

    models: list[ChatModelInfo] = []

    # Only advertise cloud_direct providers that are actually configured + supported.
    # Chat 2.0 currently supports direct OpenAI calls via OPENAI_API_KEY.
    cloud_direct_ready: set[str] = set()
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    openai_base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or "https://api.openai.com/v1"

    # Validate cloud provider credentials best-effort so the UI doesn't advertise unusable providers.
    openai_valid = False
    if openai_api_key:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(
                    f"{openai_base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {openai_api_key}"},
                )
                openai_valid = r.status_code == 200
        except Exception:
            openai_valid = False

    openrouter_valid = False
    if bool(cfg.chat.openrouter.enabled) and openrouter_api_key:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                base = cfg.chat.openrouter.base_url.rstrip("/")
                r = await client.get(f"{base}/key", headers={"Authorization": f"Bearer {openrouter_api_key}"})
                openrouter_valid = r.status_code == 200
        except Exception:
            openrouter_valid = False

    # OpenAI models are usable either via direct OpenAI OR via OpenRouter proxy (when enabled + valid).
    if openai_valid or openrouter_valid:
        cloud_direct_ready.add("openai")

    # Cloud-direct models from models.json (GEN component).
    try:
        from server.api.models import _load_catalog  # local import to avoid cycles at import time

        catalog = _load_catalog()
        raw = catalog.get("models") if isinstance(catalog, dict) else None
        if isinstance(raw, list):
            for m in raw:
                if not isinstance(m, dict):
                    continue
                comps = m.get("components") or []
                if not isinstance(comps, list) or "GEN" not in comps:
                    continue
                provider = str(m.get("provider") or "").strip() or "Cloud"
                provider_slug = str(provider).strip().lower()
                if provider_slug not in cloud_direct_ready:
                    continue
                model_id = str(m.get("model") or "").strip()
                if not model_id:
                    continue
                model_full = model_id if "/" in model_id else f"{provider}/{model_id}" if provider and provider != "Cloud" else model_id
                models.append(
                    ChatModelInfo(
                        id=model_full,
                        provider=provider,
                        source="cloud_direct",
                        provider_type=str(provider).lower(),
                        base_url=openai_base_url if provider_slug == "openai" else None,
                        supports_vision=False,
                    )
                )
    except Exception:
        # Best-effort; allow discovery even if catalog missing.
        pass

    # Provider discovery (best-effort).
    discovered = await discover_models(cfg.chat.local_models, cfg.chat.openrouter)
    for d in discovered:
        try:
            models.append(
                ChatModelInfo(
                    id=str(d.get("id") or ""),
                    provider=str(d.get("provider") or ""),
                    source=str(d.get("source") or "local"),  # type: ignore[arg-type]
                    provider_type=(str(d.get("provider_type")) if d.get("provider_type") else None),
                    base_url=(str(d.get("base_url")) if d.get("base_url") else None),
                    supports_vision=False,
                )
            )
        except Exception:
            continue

    # De-dupe by (source, provider, id)
    uniq: dict[tuple[str, str, str], ChatModelInfo] = {}
    for m in models:
        key = (str(m.source), str(m.provider), str(m.id))
        uniq[key] = m

    return ChatModelsResponse(models=list(uniq.values()))


@router.get("/chat/health", response_model=ProvidersHealthResponse)
async def chat_health(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope provider config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> ProvidersHealthResponse:
    """Return health status for chat providers."""
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    if _config is not None:
        cfg = _config
    else:
        try:
            cfg = await load_scoped_config(repo_id=scope_id) if scope_id else TriBridConfig()
        except CorpusNotFoundError:
            cfg = TriBridConfig()
    out: list[ProviderHealth] = []

    # OpenRouter
    if cfg.chat.openrouter.enabled:
        api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        if not api_key:
            out.append(
                ProviderHealth(
                    provider="OpenRouter",
                    kind="openrouter",
                    base_url=cfg.chat.openrouter.base_url,
                    reachable=False,
                    detail="Missing OPENROUTER_API_KEY",
                )
            )
        else:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    base = cfg.chat.openrouter.base_url.rstrip("/")
                    r = await client.get(f"{base}/key", headers={"Authorization": f"Bearer {api_key}"})
                    ok = r.status_code == 200
                    detail = None
                    if not ok:
                        # Best-effort parse error message without leaking anything sensitive.
                        msg = None
                        try:
                            payload = r.json()
                            msg = (
                                (payload.get("error") or {}).get("message")
                                if isinstance(payload, dict)
                                else None
                            )
                        except Exception:
                            msg = None
                        detail = msg or f"HTTP {r.status_code}"
                out.append(
                    ProviderHealth(
                        provider="OpenRouter",
                        kind="openrouter",
                        base_url=cfg.chat.openrouter.base_url,
                        reachable=bool(ok),
                        detail=detail,
                    )
                )
            except Exception as e:
                out.append(
                    ProviderHealth(
                        provider="OpenRouter",
                        kind="openrouter",
                        base_url=cfg.chat.openrouter.base_url,
                        reachable=False,
                        detail=str(e),
                    )
                )

    # Local providers
    for p in cfg.chat.local_models.providers:
        if not p.enabled:
            continue
        base_url = str(p.base_url or "").rstrip("/")
        # Be forgiving: some UIs/examples include a trailing /v1. Normalize to the provider root.
        if base_url.endswith("/v1"):
            base_url = base_url[: -len("/v1")]
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                r = await client.get(f"{base_url}/v1/models")
                ok = r.status_code < 400
            out.append(
                ProviderHealth(
                    provider=p.name,
                    kind="local",
                    base_url=base_url or p.base_url,
                    reachable=bool(ok),
                    detail=None if ok else f"HTTP {r.status_code}",
                )
            )
        except Exception as e:
            out.append(
                ProviderHealth(
                    provider=p.name,
                    kind="local",
                    base_url=base_url or p.base_url,
                    reachable=False,
                    detail=str(e),
                )
            )

    return ProvidersHealthResponse(providers=out)


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
    n = await index_recall_conversation(
        pg,
        conversation_id=request.conversation_id,
        messages=msgs,
        config=cfg.chat.recall,
        embedder=embedder,
        ts_config="english",
    )
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
