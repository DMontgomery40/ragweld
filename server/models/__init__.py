"""Server models - All types exported from THE LAW (tribrid_config_model.py).

Import domain models and config types from this module.
All types ultimately come from tribrid_config_model.py for Pydantic-first architecture.
"""
# Domain models - direct export from THE LAW
from server.models.tribrid_config_model import (
    # Index models
    Chunk,
    IndexRequest,
    IndexStats,
    IndexStatus,
    # Retrieval models
    AnswerRequest,
    AnswerResponse,
    ChunkMatch,
    SearchRequest,
    SearchResponse,
    # Chat models
    ChatRequest,
    ChatResponse,
    Message,
    # Graph models
    Community,
    Entity,
    GraphStats,
    Relationship,
    # Eval models
    EvalComparisonResult,
    EvalDatasetItem,
    EvalMetrics,
    EvalRequest,
    EvalResult,
    EvalRun,
    # Config types
    ChunkingConfig,
    EmbeddingConfig,
    FusionConfig,
    GraphSearchConfig,
    RerankingConfig,
    SparseSearchConfig,
    TracingConfig,
    TriBridConfig,
    VectorSearchConfig,
)

# Re-export from sub-modules for backwards compatibility
from server.models.repo import Repository, RepoStats
from server.models.cost import CostEstimate, CostRecord, CostSummary

# Legacy alias
DatasetEntry = EvalDatasetItem

__all__ = [
    # Index models
    "Chunk",
    "IndexRequest",
    "IndexStats",
    "IndexStatus",
    # Retrieval models
    "AnswerRequest",
    "AnswerResponse",
    "ChunkMatch",
    "SearchRequest",
    "SearchResponse",
    # Chat models
    "ChatRequest",
    "ChatResponse",
    "Message",
    # Graph models
    "Community",
    "Entity",
    "GraphStats",
    "Relationship",
    # Eval models
    "DatasetEntry",  # Legacy alias
    "EvalComparisonResult",
    "EvalDatasetItem",
    "EvalMetrics",
    "EvalRequest",
    "EvalResult",
    "EvalRun",
    # Config types
    "ChunkingConfig",
    "EmbeddingConfig",
    "FusionConfig",
    "GraphSearchConfig",
    "RerankingConfig",
    "SparseSearchConfig",
    "TracingConfig",
    "TriBridConfig",
    "VectorSearchConfig",
    # Repo types
    "Repository",
    "RepoStats",
    # Cost types
    "CostEstimate",
    "CostRecord",
    "CostSummary",
]
