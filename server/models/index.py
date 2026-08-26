"""Index-domain boundary models (owned here; registered for TypeScript generation through the aggregate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


class Chunk(BaseModel):
    """A code chunk from the indexed repository."""
    chunk_id: str = Field(description="Unique identifier for this chunk")
    content: str = Field(description="The actual code/text content")
    file_path: str = Field(description="Path to the source file")
    start_line: int = Field(description="Starting line number in source file")
    end_line: int = Field(description="Ending line number in source file")
    language: str | None = Field(default=None, description="Programming language")
    token_count: int = Field(default=0, description="Token count for embedding budget")
    embedding: list[float] | None = Field(default=None, description="Vector embedding")
    summary: str | None = Field(default=None, description="AI-generated chunk summary")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary chunk metadata")


class IndexRequest(BaseModel):
    """Request to index a repository."""
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    repo_path: str = Field(description="Path to repository on disk")
    force_reindex: bool = Field(default=False, description="Force full reindex even if up-to-date")


class IndexStatus(BaseModel):
    """Current status of repository indexing."""
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: Literal["idle", "indexing", "complete", "error", "cancelled"] = Field(description="Current indexing state")
    progress: float = Field(ge=0.0, le=1.0, description="Progress from 0.0 to 1.0")
    current_file: str | None = Field(default=None, description="File currently being indexed")
    error: str | None = Field(default=None, description="Error message if status is 'error'")
    started_at: datetime | None = Field(default=None, description="When indexing started")
    completed_at: datetime | None = Field(default=None, description="When indexing completed")


class IndexRunSummary(BaseModel):
    """Persisted indexing run summary for replay/status truthfulness."""

    run_id: str = Field(description="Unique indexing run identifier")
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: Literal["indexing", "complete", "error", "cancelled"] = Field(description="Final or current run state")
    started_at: datetime = Field(description="When indexing run started")
    completed_at: datetime | None = Field(default=None, description="When indexing run completed")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="Best-effort progress for this run")
    error: str | None = Field(default=None, description="Error message when status='error'")
    total_files: int = Field(default=0, ge=0, description="Indexed file count for this run")
    total_chunks: int = Field(default=0, ge=0, description="Indexed chunk count for this run")
    total_tokens: int = Field(default=0, ge=0, description="Indexed token count for this run")
    embedding_provider: str | None = Field(default=None, description="Embedding provider used by this run")
    embedding_model: str | None = Field(default=None, description="Embedding model used by this run")
    embedding_dimensions: int | None = Field(default=None, ge=0, description="Embedding dimensions used by this run")


class IndexRunEvent(BaseModel):
    """Persisted index terminal event for replay."""

    run_id: str = Field(description="Run identifier")
    ts: datetime = Field(description="Event timestamp (UTC)")
    type: str = Field(description="Event type (log/progress/warning/error/complete/cancelled)")
    message: str | None = Field(default=None, description="Human-readable message")
    percent: int | None = Field(default=None, ge=0, le=100, description="Progress percentage when present")
    current_file: str | None = Field(default=None, description="Current file when present")
    meta: dict[str, Any] = Field(default_factory=dict, description="Additional event payload")


class IndexStats(BaseModel):
    """Statistics about an indexed repository."""
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    total_files: int = Field(description="Number of files indexed")
    total_chunks: int = Field(description="Number of chunks created")
    total_tokens: int = Field(description="Total token count across all chunks")
    embedding_provider: str = Field(
        default="",
        description="Embedding provider used for embeddings (embedding.embedding_type) at index time",
    )
    embedding_model: str = Field(description="Model used for embeddings")
    embedding_dimensions: int = Field(description="Dimension of embedding vectors")
    last_indexed: datetime | None = Field(default=None, description="When last indexed")
    file_breakdown: dict[str, int] = Field(default_factory=dict, description="Count by file extension")


class IndexEstimate(BaseModel):
    """Best-effort estimate for indexing cost/time before running the indexer.

    Notes:
    - Token count is an approximation (byte-based heuristic).
    - Time is an intentionally rough range (depends on machine, provider latency,
      GraphRAG extraction scope, and local hardware throughput).
    """

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    repo_path: str = Field(description="Resolved path on disk used for the estimate")
    total_files: int = Field(ge=0, description="Estimated number of files that will be processed")
    total_size_bytes: int = Field(ge=0, description="Estimated total bytes across included files")
    skipped_large_files: int = Field(ge=0, description="Count of files skipped due to size limits")
    estimated_total_tokens: int = Field(ge=0, description="Estimated total tokens to be chunked/embedded")
    estimated_total_chunks: int = Field(ge=0, description="Estimated number of chunks (heuristic)")
    embedding_backend: Literal["deterministic", "provider"] = Field(
        description="Embedding backend used for indexing (deterministic has no external cost)"
    )
    embedding_provider: str = Field(description="Embedding provider used for indexing (embedding.embedding_type)")
    embedding_model: str = Field(description="Embedding model used for indexing (effective model)")
    skip_dense: bool = Field(description="Whether dense embeddings are skipped (indexing.skip_dense)")
    embedding_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated embedding cost (USD) when pricing data is available (0 for local/deterministic).",
    )
    semantic_kg_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated GraphRAG semantic extraction cost (USD) when enabled and pricing data is available.",
    )
    total_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated total indexing cost (USD): embedding + semantic KG (when applicable).",
    )
    estimated_seconds_low: float | None = Field(
        default=None, ge=0.0, description="Very rough low-end estimate for total indexing time (seconds)"
    )
    estimated_seconds_high: float | None = Field(
        default=None, ge=0.0, description="Very rough high-end estimate for total indexing time (seconds)"
    )
    estimated_seconds_semantic_kg: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated GraphRAG semantic phase time (seconds) when enabled.",
    )
    assumptions: list[str] = Field(default_factory=list, description="Human-readable assumptions used for the estimate")


# =============================================================================
# DASHBOARD MODELS - Index summary + storage breakdown
# =============================================================================


class IndexRunConflictDetail(BaseModel):
    """Public error detail returned (HTTP 409) when a corpus is fenced by a running index run."""

    code: Literal["index_run_in_progress"] = "index_run_in_progress"
    corpus_id: str = Field(description="Corpus whose index-run fence is held")
    run_id: str = Field(description="Index run that holds the fence")
    owner: str = Field(description="Worker that holds the fence (host:pid)")
    started_at: datetime = Field(description="When the holding run started")
    heartbeat_at: datetime = Field(description="Last heartbeat of the holding run")
    message: str = Field(description="Stable, non-sensitive conflict summary")
    operator_hint: str = Field(description="What the operator can do next")


class IndexFenceCorruptDetail(BaseModel):
    """Public error detail returned (HTTP 409) when a corpus carries a malformed index-run fence."""

    code: Literal["index_fence_corrupt"] = "index_fence_corrupt"
    corpus_id: str = Field(description="Corpus whose index-run fence is malformed")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class IndexRunConflictResponse(BaseModel):
    """FastAPI response envelope for every index-run fence conflict (HTTP 409)."""

    detail: IndexRunConflictDetail | IndexFenceCorruptDetail = Field(discriminator="code")


class IndexDeletionIncompleteDetail(BaseModel):
    """Public error detail (HTTP 503) while a corpus's de-index tombstone is still being cleaned up."""

    code: Literal["index_deletion_incomplete"] = "index_deletion_incomplete"
    corpus_id: str = Field(description="Corpus whose external index cleanup has not completed")
    qdrant_collections: list[str] = Field(default_factory=list, description="Collections still to drop")
    graph_repo_ids: list[str] = Field(default_factory=list, description="Neo4j graphs still to drop")
    created_at: datetime = Field(description="When the deletion tombstone was written")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class PersistedStateCorruptDetail(BaseModel):
    """Public error detail (HTTP 409) when a corpus's persisted index state does not validate."""

    code: Literal["persisted_state_corrupt"] = "persisted_state_corrupt"
    corpus_id: str = Field(description="Corpus whose persisted state is malformed")
    key: str = Field(description="Which persisted key is malformed (generation, index_tombstone, index_run)")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="The repair action (de-index the corpus, then re-index)")


class PersistedStateCorruptResponse(BaseModel):
    """FastAPI response envelope for a persisted-state corruption detail."""

    detail: PersistedStateCorruptDetail


class IndexDeletionIncompleteResponse(BaseModel):
    """FastAPI response envelope for an incomplete-deletion detail."""

    detail: IndexDeletionIncompleteDetail


__all__ = [
    "Chunk",
    "IndexDeletionIncompleteDetail",
    "IndexDeletionIncompleteResponse",
    "IndexEstimate",
    "IndexFenceCorruptDetail",
    "IndexRequest",
    "IndexRunConflictDetail",
    "IndexRunConflictResponse",
    "IndexRunEvent",
    "IndexRunSummary",
    "IndexStats",
    "IndexStatus",
    "PersistedStateCorruptDetail",
    "PersistedStateCorruptResponse",
]
