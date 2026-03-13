from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from server.api.agent import router as agent_router
from server.api.benchmark import router as benchmark_router
from server.api.chat import router as chat_router
from server.api.chunk_summaries import router as chunk_summaries_router
from server.api.config import router as config_router
from server.api.cost import router as cost_router
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
from server.api.prompts import router as prompts_router
from server.api.repos import router as repos_router
from server.api.reranker import router as reranker_router
from server.api.runtime_capabilities import router as runtime_capabilities_router
from server.api.search import router as search_router
from server.api.synthetic import router as synthetic_router
from server.config import load_config
from server.mcp.server import get_mcp_server
from server.observability.metrics import render_latest


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


# Best-effort convenience only; never block API startup.
_load_dotenv_file(Path(__file__).resolve().parents[1] / ".env")

_global_cfg = load_config()
if _global_cfg.mcp.enabled:
    _mcp = get_mcp_server()


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


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    mcp_session_cm = None
    if _global_cfg.mcp.enabled:
        mcp_session_cm = _mcp.session_manager.run()
        await _enter_lifecycle_cm(mcp_session_cm)
    try:
        yield
    finally:
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

if _global_cfg.mcp.enabled:
    app.mount(_global_cfg.mcp.mount_path, _mcp.streamable_http_app())


@app.get("/metrics")
async def metrics() -> Response:
    body, content_type = render_latest()
    return Response(content=body, media_type=content_type)


@app.middleware("http")
async def metrics_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # Keep middleware minimal: only measure /api/search to avoid high-cardinality labels.
    if request.url.path == "/api/search":
        from server.observability.metrics import SEARCH_ERRORS_TOTAL, SEARCH_LATENCY_SECONDS

        with SEARCH_LATENCY_SECONDS.time():
            try:
                response = await call_next(request)
                if response.status_code >= 500:
                    SEARCH_ERRORS_TOTAL.inc()
                return response
            except Exception:
                SEARCH_ERRORS_TOTAL.inc()
                raise
    return await call_next(request)

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
app.include_router(lineage_router)
app.include_router(reranker_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(synthetic_router, prefix="/api")
