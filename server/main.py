from fastapi import FastAPI

from server.api.chat import router as chat_router
from server.api.chunk_summaries import router as chunk_summaries_router
from server.api.config import router as config_router
from server.api.cost import router as cost_router
from server.api.dataset import router as dataset_router
from server.api.docker import router as docker_router
from server.api.eval import router as eval_router
from server.api.graph import router as graph_router
from server.api.health import router as health_router
from server.api.index import router as index_router
from server.api.keywords import router as keywords_router
from server.api.models import router as models_router
from server.api.repos import router as repos_router
from server.api.reranker import router as reranker_router
from server.api.search import router as search_router

app = FastAPI(title="TriBridRAG", version="0.1.0")

app.include_router(health_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(repos_router, prefix="/api")
app.include_router(index_router, prefix="/api")
app.include_router(chunk_summaries_router, prefix="/api")
app.include_router(keywords_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(graph_router, prefix="/api")
app.include_router(eval_router, prefix="/api")
app.include_router(dataset_router, prefix="/api")
app.include_router(cost_router, prefix="/api")
app.include_router(docker_router, prefix="/api")
app.include_router(models_router)  # Already has /api/models prefix
app.include_router(reranker_router, prefix="/api")
