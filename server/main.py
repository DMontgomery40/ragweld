from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from server.api.agent import router as agent_router
from server.api.benchmark import router as benchmark_router
from server.api.chat import router as chat_router
from server.api.chunk_summaries import router as chunk_summaries_router
from server.api.config import router as config_router
from server.api.cost import router as cost_router
from server.api.cost import warm_cost_catalog
from server.api.dataset import router as dataset_router
from server.api.docker import router as docker_router
from server.api.eval import router as eval_router
from server.api.feedback import router as feedback_router
from server.api.graph import router as graph_router
from server.api.health import router as health_router
from server.api.index import router as index_router
from server.api.keywords import router as keywords_router
from server.api.lineage import router as lineage_router
from server.api.models import router as models_router
from server.api.observability import router as observability_router
from server.api.prompts import router as prompts_router
from server.api.repos import router as repos_router
from server.api.reranker import router as reranker_router
from server.api.runtime_capabilities import router as runtime_capabilities_router
from server.api.search import router as search_router
from server.api.synthetic import router as synthetic_router
from server.chat.prompt_budget import warm_prompt_budget
from server.config import load_config
from server.gateway_catalog import warm_gateway_catalog
from server.indexing.generations import (
    DeletionIncompleteError,
    PersistedStateCorruptError,
    manifest_upgrade_blocked,
)
from server.mcp.server import get_mcp_server, record_mounted_state
from server.models.index import (
    IndexDeletionIncompleteDetail,
    IndexDeletionIncompleteResponse,
    PersistedStateCorruptDetail,
    PersistedStateCorruptResponse,
)
from server.models.tribrid_config_model import (
    DependencyUnavailableDetail,
    DependencyUnavailableResponse,
)
from server.observability.costing import warm_costing_catalog
from server.observability.metrics import render_latest
from server.observability.runtime import (
    apply_default_links,
    current_header_values,
    start_request_observation,
)
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config


# Load repo-root .env early so env-backed secrets (API keys) are available even
# when the backend is started directly (e.g. `uv run uvicorn ...`) instead of
# through `./start.sh` or Docker Compose.
#
# IMPORTANT:
# - Never override already-set environment variables.
# - No error if .env is missing (CI/prod).
def _load_dotenv_file(dotenv_path: Path) -> bool:
    """Best-effort dotenv loader for local/dev.

    Returns True if a file existed and was loaded, otherwise False.
    Never overrides already-set environment variables.
    """
    try:
        from dotenv import load_dotenv
    except Exception:
        return False

    try:
        if not dotenv_path.exists():
            return False
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return True
    except Exception:
        return False


def _dotenv_loading_enabled(value: str | None = None) -> bool:
    raw = os.environ.get("RAGWELD_LOAD_DOTENV", "1") if value is None else value
    return raw.strip().lower() not in {"0", "false", "no", "off"}


# Best-effort convenience only; never block API startup. Test and integration
# lanes pass configuration explicitly and disable repository dotenv loading.
if _dotenv_loading_enabled():
    _load_dotenv_file(Path(__file__).resolve().parents[1] / ".env")

_global_cfg = load_config()
if _global_cfg.mcp.enabled:
    _mcp = get_mcp_server()


_MANUALLY_INSTRUMENTED_API_PATHS = frozenset(
    {
        "/api/chat",
        "/api/chat/stream",
        "/api/search",
        "/api/answer",
        "/api/answer/stream",
    }
)


async def _enter_lifecycle_cm(cm: Any) -> None:
    """Enter async context manager and best-effort unwind on enter failure."""
    try:
        await cm.__aenter__()
    except BaseException as e:
        try:
            await cm.__aexit__(type(e), e, e.__traceback__)
        except Exception:
            # Keep original startup error.
            pass
        raise


logger = logging.getLogger(__name__)


GATEWAY_CATALOG_REFRESH_SECONDS = 15.0


def _warm_catalog_views() -> None:
    """Blocking: (re)load every in-memory view of data/models.json. Run off the loop."""

    warm_gateway_catalog()
    warm_costing_catalog()
    warm_cost_catalog()
    warm_prompt_budget()


def _recover_artifact_stores() -> None:
    """Blocking: repair trained-artifact promotions that crashed mid-flight. Run off the loop.

    Uses the global config's store roots (per-corpus overrides of these paths are additionally
    recovered at the start of every promotion against that root). Each trainer's run records
    are the truth for whether a stranded promotion's work committed. A store whose marker or
    pointer is unreadable is reported loudly and left untouched (fail closed): readers and
    promotions raise the same error until the operator repairs it.
    """
    from server.api.agent import _promotion_recorded as agent_promotion_recorded
    from server.api.reranker import _promotion_recorded as reranker_promotion_recorded
    from server.reranker.artifacts import resolve_project_path
    from server.training.artifact_store import ArtifactStoreError, recover_artifact_store

    training = _global_cfg.training
    for label, raw, recorded in (
        (
            "learning reranker",
            str(getattr(training, "tribrid_reranker_model_path", "") or ""),
            reranker_promotion_recorded,
        ),
        (
            "learning agent",
            str(getattr(training, "ragweld_agent_model_path", "") or ""),
            agent_promotion_recorded,
        ),
    ):
        if not raw.strip():
            continue
        root = resolve_project_path(raw)
        try:
            action = recover_artifact_store(root, promotion_recorded=recorded)
        except ArtifactStoreError as error:
            logger.error(
                "artifact store for the %s at %s needs operator repair (nothing was touched): %s",
                label,
                root,
                error,
            )
            continue
        if action is not None:
            logger.warning(
                "artifact store for the %s at %s recovered at startup: %s", label, root, action
            )


async def _catalog_refresh_loop() -> None:
    """Pick up catalog changes made by the refresh CLI without restarting the API.

    `warm_gateway_catalog` is stamp-cached (stat only unless the file changed),
    so this costs one stat per interval in a worker thread.
    """

    while True:
        await asyncio.sleep(GATEWAY_CATALOG_REFRESH_SECONDS)
        try:
            await asyncio.to_thread(_warm_catalog_views)
        except (OSError, ValueError) as error:
            logger.warning(
                "generation gateway catalog refresh failed; keeping the last good snapshot: %s",
                error,
            )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        await asyncio.to_thread(_warm_catalog_views)
    except (OSError, ValueError) as error:
        logger.warning(
            "generation gateway catalog not loaded at startup (generation fails closed): %s", error
        )
    await asyncio.to_thread(_recover_artifact_stores)
    from server.indexing.generations import (
        ensure_generation_manifests,
        ensure_generation_manifests_until_done,
    )

    # Manifest shape upgrades run before requests are served when Postgres answers
    # promptly (no request reads a pre-upgrade shape); otherwise they retry in the
    # background until they succeed once, never blocking liveness.
    manifest_upgrade_task: asyncio.Task[None] | None = None
    try:
        upgraded = await asyncio.wait_for(ensure_generation_manifests(_global_cfg), timeout=15.0)
        if upgraded:
            logger.info("upgraded generation manifests for %d corpora", upgraded)
    except Exception as error:
        logger.warning("generation manifest upgrade deferred to the background: %s", error)
        manifest_upgrade_task = asyncio.create_task(
            ensure_generation_manifests_until_done(_global_cfg), name="generation-manifest-upgrade"
        )
    from server.observability.profiling import start_profiling

    await asyncio.to_thread(start_profiling, _global_cfg)
    catalog_refresh_task = asyncio.create_task(
        _catalog_refresh_loop(), name="gateway-catalog-refresh"
    )
    mcp_session_cm = None
    if _global_cfg.mcp.enabled:
        mcp_session_cm = _mcp.session_manager.run()
        await _enter_lifecycle_cm(mcp_session_cm)
    try:
        yield
    finally:
        from server.api.index import shutdown_event_writer, stop_index_runs

        # Index runs first (their terminal handlers still persist), then the writer
        # they persist through, then the housekeeping tasks.
        await stop_index_runs()
        await shutdown_event_writer()
        catalog_refresh_task.cancel()
        if manifest_upgrade_task is not None:
            manifest_upgrade_task.cancel()
        for task in (catalog_refresh_task, manifest_upgrade_task):
            if task is None:
                continue
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if mcp_session_cm is not None:
            await mcp_session_cm.__aexit__(None, None, None)


app = FastAPI(title="TriBridRAG", version="0.1.0", lifespan=lifespan)

# Allow local dev UIs (Vite, etc.) to call the API without CORS issues.
# In production, the UI is typically served from the same origin (/web), so this is harmless.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    # MCP streamable HTTP uses this header for session management.
    expose_headers=["Mcp-Session-Id"],
)


_MANIFEST_ROUTE_PREFIXES = (
    "/api/search",
    "/api/chat",
    "/api/index",
    "/api/graph",
    "/api/corpora",
    "/api/repos",
    "/api/mcp",
)


@app.middleware("http")
async def _manifest_upgrade_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
    """While a failed manifest upgrade has not succeeded, manifest-dependent routes answer 503.

    Liveness and readiness stay reachable; readiness reports `index_manifests`.
    """
    if (
        manifest_upgrade_blocked()
        and request.url.path.startswith(_MANIFEST_ROUTE_PREFIXES)
        and request.method.upper() != "DELETE"  # de-index / corpus delete are the repair path
    ):
        detail = DependencyUnavailableDetail(
            code="dependency_unavailable",
            dependency="postgres",
            operation="generation manifest upgrade",
            message="The generation-manifest upgrade failed at startup and has not succeeded yet.",
            retryable=True,
            operator_hint=(
                "Index and retrieval routes stay closed until the upgrade completes (it retries every 60s); "
                "check /api/ready (index_manifests) and the Postgres/Qdrant services."
            ),
        )
        return JSONResponse(
            status_code=503,
            content=DependencyUnavailableResponse(detail=detail).model_dump(mode="json"),
        )
    return await call_next(request)


@app.exception_handler(PersistedStateCorruptError)
async def _persisted_state_corrupt_handler(
    _request: Request, exc: PersistedStateCorruptError
) -> JSONResponse:
    """Malformed persisted index state answers a typed, repairable 409 (never reads as absent)."""
    detail = PersistedStateCorruptDetail(
        corpus_id=exc.repo_id,
        key=exc.key,
        message=f"Corpus {exc.repo_id} carries a malformed {exc.key}.",
        operator_hint=(
            f"De-index the corpus (DELETE /api/index/{exc.repo_id}) to clear the malformed state "
            "(its collections and graphs are swept by namespace), then re-index."
        ),
    )
    return JSONResponse(
        status_code=409,
        content=PersistedStateCorruptResponse(detail=detail).model_dump(mode="json"),
    )


@app.exception_handler(DeletionIncompleteError)
async def _deletion_incomplete_handler(
    _request: Request, exc: DeletionIncompleteError
) -> JSONResponse:
    """A corpus whose de-index cleanup has not completed fails closed everywhere (retryable 503)."""
    detail = IndexDeletionIncompleteDetail(
        corpus_id=exc.repo_id,
        qdrant_collections=list(exc.tombstone.qdrant_collections),
        graph_repo_ids=list(exc.tombstone.graph_repo_ids),
        created_at=exc.tombstone.created_at,
        message=(
            f"Corpus {exc.repo_id} is being "
            + ("deleted" if exc.tombstone.intent == "delete_corpus" else "de-indexed")
            + "; its external cleanup has not completed."
        ),
        operator_hint=(
            (
                f"Retry the corpus deletion (DELETE /api/corpora/{exc.repo_id}) once Qdrant and Neo4j answer; "
                "a de-index cannot clear a corpus-deletion tombstone."
            )
            if exc.tombstone.intent == "delete_corpus"
            else (
                f"Retry the de-index (DELETE /api/index/{exc.repo_id}) once Qdrant and Neo4j answer; the "
                "tombstone names exactly what is still to drop and is cleared when that succeeds."
            )
        ),
    )
    return JSONResponse(
        status_code=503,
        content=IndexDeletionIncompleteResponse(detail=detail).model_dump(mode="json"),
    )


if _global_cfg.mcp.enabled:
    app.mount(_global_cfg.mcp.mount_path, _mcp.streamable_http_app())
record_mounted_state(
    enabled=bool(_global_cfg.mcp.enabled), mount_path=str(_global_cfg.mcp.mount_path)
)


@app.get("/metrics")
async def metrics() -> Response:
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)


def _request_observability_scope_id(request: Request) -> str | None:
    for key in ("repo_id", "repo", "corpus_id"):
        value = str(request.query_params.get(key) or "").strip()
        if value:
            return value
    return None


def _request_observability_route_name(path: str) -> str:
    clean = str(path or "").strip().strip("/")
    if not clean:
        return "root"
    return clean.replace("/", ".").replace("-", "_")


async def _load_request_observability_config(request: Request):
    scope_id = _request_observability_scope_id(request)
    if not scope_id:
        return load_config()
    try:
        return await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        return load_config()
    except Exception:
        return load_config()


@app.middleware("http")
async def observability_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = request.url.path
    if not path.startswith("/api") or path in _MANUALLY_INSTRUMENTED_API_PATHS:
        return await call_next(request)

    config = await _load_request_observability_config(request)
    scope_id = _request_observability_scope_id(request)

    with start_request_observation(
        config=config,
        route_name=_request_observability_route_name(path),
        path=path,
        method=request.method,
        correlation_id=request.headers.get("X-Correlation-ID"),
        repo_id=scope_id,
    ) as observation:
        apply_default_links(config)
        response = await call_next(request)
        if observation is not None:
            observation.span.set_attribute("http.response.status_code", int(response.status_code))
        for key, value in current_header_values().items():
            response.headers.setdefault(key, value)
        return response


app.include_router(health_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(repos_router, prefix="/api")
app.include_router(index_router, prefix="/api")
app.include_router(chunk_summaries_router, prefix="/api")
app.include_router(keywords_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(benchmark_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(eval_router, prefix="/api")
app.include_router(dataset_router, prefix="/api")
app.include_router(prompts_router, prefix="/api")
app.include_router(cost_router, prefix="/api")
app.include_router(docker_router, prefix="/api")
app.include_router(models_router)  # Already has /api/models prefix
app.include_router(runtime_capabilities_router)
app.include_router(observability_router)
app.include_router(lineage_router)
app.include_router(reranker_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(synthetic_router, prefix="/api")
