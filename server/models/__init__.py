"""Server models - All types exported from THE LAW (tribrid_config_model.py).

Import domain models and config types from this module.
All types ultimately come from tribrid_config_model.py for Pydantic-first architecture.
"""
# Domain models - direct export from THE LAW
from server.models.cost import CostEstimate, CostRecord, CostSummary

# Re-export from sub-modules for backwards compatibility
from server.models.repo import Repository, RepoStats
from server.models.tribrid_config_model import (
    # Retrieval models
    AnswerRequest,
    AnswerResponse,
    # Chat models
    ChatRequest,
    ChatResponse,
    # Index models
    Chunk,
    # Config types
    ChunkingConfig,
    ChunkMatch,
    # Graph models
    Community,
    # Corpus models
    Corpus,
    CorpusCreateRequest,
    CorpusStats,
    EmbeddingConfig,
    Entity,
    # Eval models
    EvalComparisonResult,
    EvalAnalyzeComparisonResponse,
    EvalDoc,
    EvalDatasetItem,
    EvalMetrics,
    EvalRequest,
    EvalTestRequest,
    EvalResult,
    EvalRun,
    EvalRunMeta,
    EvalRunsResponse,
    FusionConfig,
    GraphSearchConfig,
    GraphStats,
    IndexRequest,
    IndexStats,
    IndexStatus,
    Message,
    Relationship,
    RerankingConfig,
    SearchRequest,
    SearchResponse,
    SparseSearchConfig,
    TracingConfig,
    TriBridConfig,
    VectorSearchConfig,
)

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
    "EvalAnalyzeComparisonResponse",
    "EvalDoc",
    "EvalDatasetItem",
    "EvalMetrics",
    "EvalRequest",
    "EvalTestRequest",
    "EvalResult",
    "EvalRun",
    "EvalRunMeta",
    "EvalRunsResponse",
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
    # Corpus types
    "Corpus",
    "CorpusStats",
    "CorpusCreateRequest",
    # Cost types
    "CostEstimate",
    "CostRecord",
    "CostSummary",
]
