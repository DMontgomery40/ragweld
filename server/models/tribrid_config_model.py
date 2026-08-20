"""Pydantic models for tribrid_config.json validation and type safety.

This module defines the schema for tunable RAG parameters stored in tribrid_config.json.
Using Pydantic provides:
- Type validation at load time
- Range validation (e.g., rrf_k_div must be 1-200)
- Clear error messages for invalid configs
- Default values that match current hardcoded values
- JSON schema generation for documentation

This is THE LAW - all domain models and config types must be defined here.
Other files should re-export from this module.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

try:
    from typing import Self
except ImportError:
    from typing import Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from server.models.runtime_gateway import BenchmarkConfig as BenchmarkConfig
from server.models.runtime_gateway import ChatModelInfo as ChatModelInfo
from server.models.runtime_gateway import ChatModelsResponse as ChatModelsResponse
from server.models.runtime_gateway import ChatProviderInfo as ChatProviderInfo
from server.models.runtime_gateway import GenerationConfig as GenerationConfig
from server.models.runtime_gateway import LiteLLMConfig as LiteLLMConfig
from server.models.runtime_gateway import LocalModelConfig as LocalModelConfig
from server.models.runtime_gateway import LocalProviderEntry as LocalProviderEntry
from server.models.runtime_gateway import OpenRouterConfig as OpenRouterConfig
from server.models.runtime_gateway import ProviderHealth as ProviderHealth
from server.models.runtime_gateway import ProvidersHealthResponse as ProvidersHealthResponse
from server.models.runtime_gateway import VLLMConfig as VLLMConfig
from server.models.synthetic import SyntheticConfig as SyntheticConfig
from server.models.synthetic import SyntheticGeneratorConfig as SyntheticGeneratorConfig
from server.models.synthetic import SyntheticJudgeConfig as SyntheticJudgeConfig
from server.models.synthetic import SyntheticQualityGateConfig as SyntheticQualityGateConfig
from server.models.synthetic import SyntheticRunDegradation as SyntheticRunDegradation

# =============================================================================
# DOMAIN MODELS - Core data types for the tribrid RAG system
# =============================================================================
# These models define the shapes of data flowing through the system.
# Frontend TypeScript types are generated from these via generate_types.py.


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
    skip_dense: bool = Field(description="Whether dense embeddings are skipped (indexing.skip_dense=1)")
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


class RetrievalPilotPackageStatus(BaseModel):
    """Availability status for one OSS retrieval pilot dependency."""

    package: str = Field(description="Import/package name checked by the pilot.")
    label: str = Field(description="Human-readable dependency label.")
    available: bool = Field(description="Whether the package is importable in the current environment.")
    detail: str | None = Field(default=None, description="Short operator-facing note about the dependency state.")


class RetrievalPilotStatusResponse(BaseModel):
    """Operator status for the OSS retrieval/indexing sidecar pilot."""

    ok: bool = Field(default=True)
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    repo_path: str = Field(description="Resolved corpus path used by the pilot.")
    backend: Literal["haystack_qdrant_sidecar"] = Field(
        default="haystack_qdrant_sidecar",
        description="Current pilot backend target.",
    )
    export_dir: str = Field(description="Directory where pilot export artifacts are stored.")
    documents_path: str = Field(description="JSONL export path for pilot-ready chunk documents.")
    manifest_path: str = Field(description="Manifest JSON path for the most recent pilot export.")
    export_exists: bool = Field(description="Whether a pilot export already exists on disk.")
    exported_file_count: int = Field(default=0, ge=0, description="Files exported into the pilot sidecar.")
    exported_chunk_count: int = Field(default=0, ge=0, description="Chunks exported into the pilot sidecar.")
    skipped_large_files: int = Field(default=0, ge=0, description="Files skipped because they exceeded indexing size limits.")
    skipped_unreadable_files: int = Field(
        default=0,
        ge=0,
        description="Files seen by the loader but skipped because text extraction produced no usable content.",
    )
    last_exported_at: datetime | None = Field(default=None, description="When the current pilot export was generated.")
    provenance_fields: list[str] = Field(
        default_factory=list,
        description="Metadata fields preserved for provenance-correct pilot chunks.",
    )
    package_status: list[RetrievalPilotPackageStatus] = Field(
        default_factory=list,
        description="Availability of Docling, Haystack, and Qdrant dependencies for the pilot.",
    )
    execution_backend: Literal["haystack_qdrant_local"] = Field(
        default="haystack_qdrant_local",
        description="Execution backend used by the real pilot ingest/search lane.",
    )
    execution_ready: bool = Field(
        default=False,
        description="Whether the real Haystack/Qdrant execution lane is hydrated and ready to search.",
    )
    qdrant_path: str = Field(description="Filesystem path for the local Qdrant store used by the pilot.")
    collection_name: str = Field(description="Qdrant collection/index name for this pilot corpus.")
    indexed_document_count: int = Field(
        default=0,
        ge=0,
        description="Number of documents currently ingested into the real pilot execution lane.",
    )
    last_indexed_at: datetime | None = Field(
        default=None,
        description="When the Haystack/Qdrant execution lane was last hydrated from the sidecar export.",
    )
    search_preview_ready: bool = Field(
        default=False,
        description="Whether preview search can run against the exported pilot sidecar.",
    )
    operator_hint: str | None = Field(default=None, description="High-signal next-step guidance for the operator.")


class RetrievalPilotExportRequest(BaseModel):
    """Request to generate the OSS retrieval pilot sidecar export."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    repo_path: str = Field(description="Path to the corpus root on disk.")
    force_rebuild: bool = Field(default=False, description="Rebuild the pilot export even if it already exists.")


class RetrievalPilotExportResponse(BaseModel):
    """Response for a retrieval pilot export request."""

    ok: bool = Field(default=True)
    status: RetrievalPilotStatusResponse = Field(description="Current pilot status after export.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal export warnings.")


class RetrievalPilotSearchPreviewRequest(BaseModel):
    """Request to search over the exported retrieval pilot sidecar."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    query: str = Field(description="Search query to run against the exported pilot documents.")
    top_k: int = Field(default=5, ge=1, le=20, description="Maximum results to return.")


class RetrievalPilotSearchPreviewResult(BaseModel):
    """One preview-search hit from the retrieval pilot sidecar."""

    chunk_id: str = Field(description="Exported chunk identifier.")
    file_path: str = Field(description="Corpus-relative path for the matched chunk.")
    source_path: str = Field(description="Absolute source path for the matched chunk.")
    start_line: int = Field(ge=1, description="Start line of the matched chunk.")
    end_line: int = Field(ge=1, description="End line of the matched chunk.")
    language: str | None = Field(default=None, description="Detected language for the chunk.")
    score: float = Field(ge=0.0, description="Preview relevance score.")
    excerpt: str = Field(description="Short excerpt centered on the first match when possible.")


class RetrievalPilotSearchPreviewResponse(BaseModel):
    """Response for retrieval pilot preview search."""

    ok: bool = Field(default=True)
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    query: str = Field(description="Query executed against the pilot export.")
    results: list[RetrievalPilotSearchPreviewResult] = Field(default_factory=list)
    status: RetrievalPilotStatusResponse = Field(description="Pilot status snapshot used for the preview search.")


class RetrievalPilotIngestRequest(BaseModel):
    """Request to hydrate the real Haystack/Qdrant execution lane from the sidecar export."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    force_rebuild: bool = Field(default=False, description="Rebuild the local Qdrant collection from scratch.")


class RetrievalPilotIngestResponse(BaseModel):
    """Response for retrieval pilot ingest."""

    ok: bool = Field(default=True)
    status: RetrievalPilotStatusResponse = Field(description="Pilot status snapshot after ingest.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal ingest warnings.")


class RetrievalPilotSearchRequest(BaseModel):
    """Request to search the real Haystack/Qdrant execution lane."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    query: str = Field(description="Search query to execute against the real pilot lane.")
    top_k: int = Field(default=5, ge=1, le=20, description="Maximum hits to return.")


class RetrievalPilotSearchResult(BaseModel):
    """One result from the real Haystack/Qdrant pilot lane."""

    chunk_id: str = Field(description="Exported chunk identifier.")
    file_path: str = Field(description="Corpus-relative path for the matched chunk.")
    source_path: str = Field(description="Absolute source path for the matched chunk.")
    start_line: int = Field(ge=1, description="Start line of the matched chunk.")
    end_line: int = Field(ge=1, description="End line of the matched chunk.")
    language: str | None = Field(default=None, description="Detected language for the chunk.")
    score: float = Field(ge=0.0, description="Haystack/Qdrant relevance score.")
    excerpt: str = Field(description="Short excerpt centered on the first match when possible.")


class RetrievalPilotSearchResponse(BaseModel):
    """Response for real Haystack/Qdrant pilot search."""

    ok: bool = Field(default=True)
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    backend: Literal["haystack_qdrant_local"] = Field(
        default="haystack_qdrant_local",
        description="Search backend used for this response.",
    )
    query: str = Field(description="Query executed against the real pilot lane.")
    results: list[RetrievalPilotSearchResult] = Field(default_factory=list)
    status: RetrievalPilotStatusResponse = Field(description="Pilot status snapshot used for the real search.")


# =============================================================================
# DASHBOARD MODELS - Index summary + storage breakdown
# =============================================================================


class DashboardIndexStorageBreakdown(BaseModel):
    """Storage breakdown for the Dashboard index summary (bytes).

    NOTE:
    - Values are best-effort and may be allocated/estimated when a storage
      component cannot be attributed to a single corpus directly (e.g., shared
      Postgres indexes).
    """

    chunks_bytes: int = Field(
        default=0,
        ge=0,
        description="Bytes used by chunk content + metadata in Postgres (corpus-scoped).",
    )
    embeddings_bytes: int = Field(
        default=0,
        ge=0,
        description="Bytes used by stored embeddings in Postgres (corpus-scoped).",
    )
    pgvector_index_bytes: int = Field(
        default=0,
        ge=0,
        description="Bytes used by pgvector index structures (0 if not created; may be allocated/estimated).",
    )
    bm25_index_bytes: int = Field(
        default=0,
        ge=0,
        description="Allocated bytes for Postgres full-text (BM25/FTS) index (may be allocated/estimated).",
    )
    chunk_summaries_bytes: int = Field(
        default=0,
        ge=0,
        description="Bytes used by chunk_summaries in Postgres (corpus-scoped).",
    )
    neo4j_store_bytes: int = Field(
        default=0,
        ge=0,
        description="Total Neo4j store size for the resolved database (bytes).",
    )

    postgres_total_bytes: int = Field(
        default=0,
        ge=0,
        description="Total Postgres bytes (sum of Postgres components, including allocations).",
    )
    total_storage_bytes: int = Field(
        default=0,
        ge=0,
        description="Total storage bytes across Postgres + Neo4j.",
    )


class DashboardEmbeddingConfigSummary(BaseModel):
    """Embedding configuration summary for dashboard display."""

    provider: str | None = Field(default=None, description="Embedding provider (embedding.embedding_type).")
    model: str | None = Field(default=None, description="Effective embedding model name.")
    dimensions: int | None = Field(default=None, ge=1, description="Embedding vector dimensions.")
    precision: str | None = Field(
        default=None,
        description="Storage precision label (e.g., float32).",
    )


class DashboardIndexCosts(BaseModel):
    """Indexing cost summary for dashboard display."""

    total_tokens: int = Field(default=0, ge=0, description="Total tokens processed during indexing.")
    embedding_cost: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated embedding cost (USD) when pricing data is available.",
    )
    semantic_kg_cost: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated GraphRAG semantic extraction cost (USD) when enabled.",
    )
    total_cost: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated total indexing cost (USD): embedding + semantic KG (when applicable).",
    )


class DashboardIndexStatusMetadata(BaseModel):
    """Metadata payload for the dashboard index status panel."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    current_repo: str = Field(description="Display name for the active corpus.")
    current_branch: str | None = Field(default=None, description="Current git branch for the corpus (if available).")
    timestamp: datetime = Field(description="Timestamp for this status snapshot (UTC).")

    embedding_config: DashboardEmbeddingConfigSummary | None = Field(
        default=None, description="Embedding configuration summary."
    )
    costs: DashboardIndexCosts | None = Field(default=None, description="Indexing cost summary.")
    storage_breakdown: DashboardIndexStorageBreakdown = Field(
        default_factory=DashboardIndexStorageBreakdown,
        description="Storage breakdown (bytes) for major components.",
    )

    keywords_count: int = Field(default=0, ge=0, description="Number of keywords for this corpus (if generated).")
    total_storage: int = Field(default=0, ge=0, description="Total storage bytes (Postgres + Neo4j).")


class DashboardIndexStatusResponse(BaseModel):
    """Response payload for Dashboard index status panel."""

    lines: list[str] = Field(default_factory=list, description="Human-readable status lines for fallback display.")
    metadata: DashboardIndexStatusMetadata | None = Field(default=None, description="Structured status metadata.")
    running: bool = Field(default=False, description="Whether indexing is currently running for this corpus.")
    progress: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Indexing progress from 0.0 to 1.0 when running.",
    )
    current_file: str | None = Field(default=None, description="File currently being indexed (if running).")


class DashboardIndexStatsResponse(BaseModel):
    """Response payload for Dashboard storage panels."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    storage_breakdown: DashboardIndexStorageBreakdown = Field(
        default_factory=DashboardIndexStorageBreakdown,
        description="Storage breakdown (bytes) for major components.",
    )
    keywords_count: int = Field(default=0, ge=0, description="Number of keywords for this corpus (if generated).")
    total_storage: int = Field(default=0, ge=0, description="Total storage bytes (Postgres + Neo4j).")


class DevStackStatusResponse(BaseModel):
    """Status of the local dev stack (frontend + backend)."""

    frontend_running: bool = Field(description="Whether the dev frontend (Vite) is reachable.")
    backend_running: bool = Field(description="Whether the dev backend (FastAPI/Uvicorn) is reachable.")
    frontend_port: int = Field(ge=1024, le=65535, description="Port for dev frontend (Vite).")
    backend_port: int = Field(ge=1024, le=65535, description="Port for dev backend (Uvicorn).")

    frontend_url: str | None = Field(default=None, description="Resolved frontend URL (if known).")
    backend_url: str | None = Field(default=None, description="Resolved backend URL (if known).")
    details: list[str] = Field(
        default_factory=list,
        description="Human-readable diagnostic details (best-effort).",
    )


# =============================================================================
# HEALTH + INFRASTRUCTURE API MODELS
# =============================================================================


class HealthServiceStatus(BaseModel):
    """Per-service status entry for /api/health."""

    status: str = Field(description="Service health status label (e.g., up/unknown/down).")
    error: str | None = Field(default=None, description="Optional error message if unhealthy/unreachable.")


class HealthStatus(BaseModel):
    """System health status payload for /api/health."""

    ok: bool = Field(default=True, description="Overall health boolean.")
    status: Literal["healthy", "unhealthy", "unknown"] = Field(default="healthy", description="Overall status label.")
    ts: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp for this health snapshot (UTC).",
    )
    services: dict[str, HealthServiceStatus] = Field(
        default_factory=dict,
        description="Map of service name -> status entry.",
    )


class ReadinessDependencyStatus(BaseModel):
    """Sanitized readiness state for one required runtime dependency."""

    ok: bool = Field(default=False)
    error: str | None = Field(default=None, description="Stable, non-sensitive failure summary.")
    operator_hint: str | None = Field(default=None, description="High-signal next step for the operator.")
    database: str | None = Field(default=None, description="Resolved logical database name when applicable.")
    database_exists: bool | None = Field(default=None)
    info: dict[str, Any] | None = Field(default=None, description="Sanitized dependency readiness metadata.")


class ReadinessStatus(BaseModel):
    """Readiness payload; unavailable required dependencies are served with HTTP 503."""

    ready: bool
    corpus_id: str | None = None
    corpus_error: str | None = None
    dependencies: dict[Literal["postgres", "neo4j"], ReadinessDependencyStatus]


class DockerContainer(BaseModel):
    """Ragweld-owned Compose service exposed to the local Docker control surface."""

    id: str = Field(description="Full container ID.")
    short_id: str = Field(description="Short container ID (first 12 chars).")
    name: str = Field(description="Container name.")
    image: str = Field(description="Container image reference.")
    state: str = Field(description="Container state (lowercase, best-effort).")
    status: str = Field(description="Human-readable docker status string.")
    ports: str | None = Field(default=None, description="Port mapping summary string (may be empty).")
    compose_project: str = Field(description="Exact Docker Compose project label; always ragweld on this surface.")
    compose_service: str = Field(description="Allowlisted Docker Compose service label.")
    managed: bool = Field(description="Whether exact Ragweld project and ownership labels authorize local control.")


class DockerContainersResponse(BaseModel):
    """Response payload for the project-scoped /api/docker/services endpoint."""

    containers: list[DockerContainer] = Field(default_factory=list, description="List of Docker containers.")


class DockerStatus(BaseModel):
    """Response payload for /api/docker/status."""

    running: bool = Field(default=False, description="Whether Docker is available and responding.")
    runtime: str = Field(default="", description="Runtime label/version string (best-effort).")
    project_name: Literal["ragweld"] = Field(
        default="ragweld",
        description="Fixed Docker Compose project authorized by this local control surface.",
    )
    containers_count: int = Field(default=0, ge=0, description="Number of authorized Ragweld service containers.")


class DockerServiceLogsResponse(BaseModel):
    """Typed response for project-scoped Docker service logs."""

    success: bool = Field(description="Whether Docker returned logs successfully.")
    logs: str = Field(default="", description="Recent logs for the authorized Ragweld service.")
    error: str | None = Field(default=None, description="Docker error when logs could not be read.")


class LokiStatus(BaseModel):
    """Response payload for /api/loki/status."""

    reachable: bool = Field(default=False, description="Whether Loki is reachable.")
    url: str | None = Field(default=None, description="Resolved Loki base URL if reachable (best-effort).")
    status: str = Field(default="unreachable", description="Human-readable status label (best-effort).")


class MCPRagSearchResult(BaseModel):
    """Compact result shape for legacy /api/mcp/rag_search (debug UI)."""

    file_path: str = Field(description="Matched file path.")
    start_line: int = Field(description="Start line for the matched span.")
    end_line: int = Field(description="End line for the matched span.")
    rerank_score: float = Field(description="Legacy field: score for the match (post-fusion).")


class MCPRagSearchResponse(BaseModel):
    """Response payload for legacy /api/mcp/rag_search (debug UI)."""

    results: list[MCPRagSearchResult] = Field(default_factory=list, description="Compact match list.")
    error: str | None = Field(default=None, description="Error message when the search fails.")


class MCPHTTPTransportStatus(BaseModel):
    """Status of an MCP HTTP transport (Python/Node) when enabled."""

    host: str = Field(description="Host for the MCP HTTP transport.")
    port: int = Field(ge=1, le=65535, description="Port for the MCP HTTP transport.")
    path: str | None = Field(default=None, description="HTTP path prefix (if applicable).")
    running: bool = Field(description="Whether the transport is reachable/responding.")


class MCPStatusResponse(BaseModel):
    """Status of MCP transports built into TriBridRAG."""

    # Future-facing: expose HTTP transports when implemented.
    python_http: MCPHTTPTransportStatus | None = Field(
        default=None,
        description="Python MCP over HTTP transport status (if implemented/enabled).",
    )
    node_http: MCPHTTPTransportStatus | None = Field(
        default=None,
        description="Node MCP over HTTP transport status (if implemented/enabled).",
    )

    # Current: stdio is typically client-spawned (no daemon).
    python_stdio_available: bool = Field(
        default=False,
        description="Whether the Python stdio MCP transport is available (client-spawned).",
    )
    details: list[str] = Field(
        default_factory=list,
        description="Human-readable diagnostic details (best-effort).",
    )


class MCPConfig(BaseModel):
    """Inbound MCP (Model Context Protocol) server configuration.

    This config controls TriBridRAG's embedded MCP Streamable HTTP endpoint.
    """

    enabled: bool = Field(
        default=True,
        description="Enable the embedded MCP Streamable HTTP server.",
    )
    mount_path: str = Field(
        default="/mcp",
        description="Mount path for the MCP Streamable HTTP endpoint (e.g. /mcp).",
    )
    stateless_http: bool = Field(
        default=True,
        description="Run MCP Streamable HTTP in stateless mode (recommended).",
    )
    json_response: bool = Field(
        default=True,
        description="Prefer JSON responses for MCP Streamable HTTP (recommended).",
    )
    enable_dns_rebinding_protection: bool = Field(
        default=True,
        description="Enable DNS rebinding protection for MCP HTTP (recommended).",
    )
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost:*", "127.0.0.1:*"],
        description="Allowed Host header values for MCP HTTP (supports wildcard ':*').",
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"],
        description="Allowed Origin header values for MCP HTTP (supports wildcard ':*').",
    )
    require_api_key: bool = Field(
        default=False,
        description="Require `Authorization: Bearer $MCP_API_KEY` for MCP HTTP access.",
    )
    default_top_k: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Default top_k for MCP search/answer tools when not provided.",
    )
    default_mode: Literal["tribrid", "dense_only", "sparse_only", "graph_only"] = Field(
        default="tribrid",
        description="Default retrieval mode for MCP search/answer tools when not provided.",
    )

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _parse_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.replace("\n", ",").split(",") if item.strip()]
        if isinstance(v, (list, tuple, set)):
            cleaned: list[str] = []
            for item in v:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            return cleaned
        text = str(v).strip()
        return [text] if text else []


class Corpus(BaseModel):
    """User-managed corpus (formerly "repo" in earlier versions).

    A corpus is the unit of isolation for:
    - indexing storage (Postgres)
    - graph storage (Neo4j)
    - configuration (per-corpus TriBridConfig)
    """

    repo_id: str = Field(
        description="Corpus identifier (stable slug)",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    name: str = Field(description="Display name")
    path: str = Field(description="Root path on disk")
    slug: str | None = Field(default=None, description="Legacy alias for repo_id (UI compatibility)")
    branch: str | None = Field(default=None, description="Optional branch name (if corpus is a git repo)")
    default: bool | None = Field(default=None, description="Whether this corpus is the default selection")
    exclude_paths: list[str] | None = Field(default=None, description="Paths to exclude during indexing")
    keywords: list[str] | None = Field(default=None, description="Corpus-specific keyword boosts")
    path_boosts: list[str] | None = Field(default=None, description="Path boost prefixes for scoring")
    layer_bonuses: dict[str, dict[str, float]] | None = Field(
        default=None,
        description="Optional layer bonus overrides (intent->layer->multiplier)",
    )
    description: str | None = Field(default=None, description="Optional description")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the corpus was created",
    )
    last_indexed: datetime | None = Field(default=None, description="When the corpus was last indexed")


class CorpusStats(BaseModel):
    """High-level corpus stats for UI dashboards."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    file_count: int = Field(description="Number of files in corpus")
    total_size_bytes: int = Field(description="Total size of corpus files (bytes)")
    language_breakdown: dict[str, int] = Field(description="Language->file count breakdown")
    index_stats: IndexStats | None = Field(default=None, description="Index stats (if indexed)")
    graph_stats: GraphStats | None = Field(default=None, description="Graph stats (if built)")


class CorpusCreateRequest(BaseModel):
    """Request to create a new corpus."""

    repo_id: str | None = Field(
        default=None,
        description="Optional corpus ID; generated from name if omitted",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    name: str = Field(description="Display name")
    path: str = Field(description="Root path on disk")
    description: str | None = Field(default=None, description="Optional description")


class CorpusUpdateRequest(BaseModel):
    """Request to update an existing corpus. All fields optional."""

    name: str | None = Field(default=None, description="Display name")
    path: str | None = Field(default=None, description="Root path on disk")
    branch: str | None = Field(default=None, description="Git branch (if applicable)")
    exclude_paths: list[str] | None = Field(default=None, description="Paths to exclude during indexing")
    keywords: list[str] | None = Field(default=None, description="Corpus-specific keyword boosts")
    path_boosts: list[str] | None = Field(default=None, description="Path patterns for scoring boosts")
    layer_bonuses: dict[str, dict[str, float]] | None = Field(
        default=None, description="Nested map for layer bonus scoring"
    )


class CorpusScope(BaseModel):
    """Standard corpus scoping helper for query params and request bodies.

    Accepts either `corpus_id` (preferred) or `repo_id` (legacy).
    Also supports older `repo` query parameters used in parts of the UI.
    """

    corpus_id: str | None = Field(
        default=None,
        description="Corpus identifier (preferred)",
    )

    repo_id: str | None = Field(
        default=None,
        description="Corpus identifier (legacy repo_id)",
    )

    repo: str | None = Field(
        default=None,
        description="Corpus identifier (legacy repo alias)",
    )

    @property
    def resolved_repo_id(self) -> str | None:
        return self.corpus_id or self.repo_id or self.repo

    @field_validator("corpus_id", "repo_id", "repo")
    @classmethod
    def _strip_repo_id(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class DependencyUnavailableDetail(BaseModel):
    """Public error detail returned when a required runtime dependency is unavailable."""

    code: Literal["dependency_unavailable"] = "dependency_unavailable"
    dependency: Literal["postgres", "neo4j"] = Field(description="Unavailable required dependency")
    operation: str = Field(description="API operation that could not complete")
    message: str = Field(description="Stable, non-sensitive failure summary")
    retryable: bool = Field(default=True, description="Whether the caller may retry after operator remediation")
    operator_hint: str = Field(description="High-signal next step for the operator")


class DependencyUnavailableResponse(BaseModel):
    """FastAPI response envelope for a dependency-unavailable detail."""

    detail: DependencyUnavailableDetail


class VocabPreviewTerm(BaseModel):
    """A single term in the Postgres FTS vocabulary preview."""

    term: str = Field(description="Tokenized lexeme")
    doc_count: int = Field(ge=0, description="Number of chunks containing this term")


class VocabPreviewResponse(BaseModel):
    """Response payload for the vocab preview endpoint."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    top_n: int = Field(ge=10, le=500, description="Number of top terms requested")
    tokenizer: str = Field(description="BM25 tokenizer setting (indexing.bm25_tokenizer)")
    stemmer_lang: str | None = Field(default=None, description="Stemmer language (indexing.bm25_stemmer_lang)")
    ts_config: str = Field(description="Postgres text search configuration used for tsv + query parsing")
    total_terms: int = Field(ge=0, description="Total unique terms in the corpus vocabulary")
    terms: list[VocabPreviewTerm] = Field(default_factory=list, description="Top terms by document frequency")


class ChunkSummary(BaseModel):
    """A short summary of an indexed chunk (chunk_summary)."""

    chunk_id: str = Field(description="Unique identifier of the source chunk")
    file_path: str = Field(description="Path to the source file")
    start_line: int | None = Field(default=None, description="Starting line number")
    end_line: int | None = Field(default=None, description="Ending line number")
    purpose: str | None = Field(default=None, description="High-level purpose summary")
    symbols: list[str] = Field(default_factory=list, description="Symbols mentioned in this chunk")
    technical_details: str | None = Field(default=None, description="Technical details summary")
    domain_concepts: list[str] = Field(default_factory=list, description="Domain concepts mentioned in this chunk")
    routes: list[str] = Field(default_factory=list, description="Detected route/path signals")
    dependencies: list[str] = Field(default_factory=list, description="Key dependencies/imports")
    patterns: list[str] = Field(default_factory=list, description="Implementation patterns")
    card_source: Literal["deterministic", "llm"] = Field(
        default="deterministic",
        description="How this summary was produced",
    )
    card_score: float | None = Field(
        default=None,
        ge=0.0,
        le=10.0,
        description="Optional quality score for llm-enriched summaries",
    )


class ChunkSummariesLastBuild(BaseModel):
    """Metadata about the most recent chunk_summaries build."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the build completed",
    )
    total: int = Field(ge=0, description="Number of chunk_summaries generated")
    enriched: int = Field(default=0, ge=0, description="Number of chunk_summaries enriched (if enabled)")


class ChunkSummariesResponse(BaseModel):
    """Response payload for chunk_summaries list/build endpoints."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    chunk_summaries: list[ChunkSummary] = Field(description="Chunk summaries for this repo")
    last_build: ChunkSummariesLastBuild | None = Field(
        default=None, description="Metadata about the last build, if any"
    )


class ChunkSummariesBuildRequest(BaseModel):
    """Request to build chunk_summaries for a repository."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "repo", "corpus_id"),
        serialization_alias="corpus_id",
    )
    # Optional overrides (otherwise use TriBridConfig fields)
    max: int | None = Field(default=None, ge=1, le=10000, description="Override max summaries to build")
    enrich: bool | None = Field(default=None, description="Override enrichment toggle for this build")


class KeywordsGenerateRequest(BaseModel):
    """Request to generate discriminative keywords for a repository."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "repo", "corpus_id"),
        serialization_alias="corpus_id",
    )


class KeywordsGenerateResponse(BaseModel):
    """Response payload for keywords generation."""

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    keywords: list[str] = Field(description="Generated keywords")
    count: int = Field(ge=0, description="Number of keywords returned")


class ChunkMatch(BaseModel):
    """Unified result shape for vector/sparse/graph retrieval."""
    chunk_id: str = Field(description="Unique identifier for matched chunk")
    content: str = Field(description="The matched code/text content")
    file_path: str = Field(description="Path to the source file")
    start_line: int = Field(description="Starting line number")
    end_line: int = Field(description="Ending line number")
    language: str | None = Field(default=None, description="Programming language")
    score: float = Field(description="Relevance score from retrieval")
    source: Literal["vector", "sparse", "graph"] = Field(
        description="Which retrieval leg found this"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional match metadata")


class SearchRequest(BaseModel):
    """Request payload for tri-brid search."""
    query: str = Field(description="The search query")
    repo_id: str = Field(
        description="Corpus identifier to search",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    top_k: int = Field(default=20, ge=1, le=100, description="Number of results to return")
    include_vector: bool = Field(default=True, description="Include vector search results")
    include_sparse: bool = Field(default=True, description="Include sparse/BM25 results")
    include_graph: bool = Field(default=True, description="Include graph search results")
    cache_mode: Literal["default", "bypass", "refresh"] = Field(
        default="default",
        description="Per-request cache mode override.",
    )


class SearchResponse(BaseModel):
    """Response from tri-brid search."""
    query: str = Field(description="The original query")
    matches: list[ChunkMatch] = Field(description="Ranked list of matching chunks")
    fusion_method: str = Field(description="Fusion method used (rrf or weighted)")
    reranker_mode: str = Field(description="Reranker mode used")
    latency_ms: float = Field(description="Search latency in milliseconds")
    debug: dict[str, Any] | None = Field(default=None, description="Debug information if requested")


class AnswerRequest(BaseModel):
    """Request payload for AI answer generation."""
    query: str = Field(description="The question to answer")
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    top_k: int = Field(default=10, ge=1, le=50, description="Number of chunks to use as context")
    include_vector: bool = Field(default=True, description="Include vector retrieval results")
    include_sparse: bool = Field(default=True, description="Include sparse/BM25 retrieval results")
    include_graph: bool = Field(
        default=True,
        description="Include graph retrieval results (Neo4j), when enabled for the corpus",
    )
    stream: bool = Field(default=False, description="Stream the response")
    system_prompt: str | None = Field(default=None, description="Override system prompt")
    model_override: str = Field(default="", description="Override chat model for this request (empty=default)")
    cache_mode: Literal["default", "bypass", "refresh"] = Field(
        default="default",
        description="Per-request cache mode override.",
    )


class AnswerResponse(BaseModel):
    """Response from AI answer generation."""
    query: str = Field(description="The original question")
    answer: str = Field(description="Generated answer")
    sources: list[ChunkMatch] = Field(description="Chunks used to generate answer")
    model: str = Field(description="Model used for generation")
    tokens_used: int = Field(description="Total tokens consumed")
    latency_ms: float = Field(description="Generation latency in milliseconds")
    debug: ChatDebugInfo | None = Field(default=None, description="Developer debug metadata (best-effort)")


class Message(BaseModel):
    """Chat message in a conversation."""
    role: Literal["user", "assistant", "system"] = Field(description="Message role")
    content: str = Field(description="Message content")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When message was created"
    )


class ActiveSources(BaseModel):
    """What the user has checked in the data sources dropdown.

    This is what the frontend sends. The backend passes corpus_ids straight into fusion.
    """

    corpus_ids: list[str] = Field(
        default_factory=list,
        description="Checked corpus IDs (include recall_default when Recall is checked). Empty = no retrieval.",
    )


class RecallIntensity(str, Enum):
    """How aggressively to query Recall (chat memory) for a single message.

    NOTE:
    - This is an optimization hint decided per-message (or overridden by the user).
    - It only applies to the Recall corpus. Non-Recall RAG corpora are always queried when checked.
    """

    skip = "skip"
    light = "light"
    standard = "standard"
    deep = "deep"


class RecallSignals(BaseModel):
    """Signals extracted from the user's message + conversation context.

    Used by the Recall gate to decide Recall intensity. Exposed in debug metadata.
    All fields are cheap to compute (no LLM calls, no embeddings).
    """

    token_count: int = Field(description="Approximate token count of message")
    is_question: bool = Field(description="Contains ? or interrogative pattern")
    is_greeting: bool = Field(description="Matches greeting/farewell patterns")
    is_acknowledgment: bool = Field(description="'ok', 'thanks', 'got it', etc.")
    is_follow_up: bool = Field(
        description="Continuation of prior topic — short message after retrieval-backed reply"
    )
    is_recall_trigger: bool = Field(
        description=(
            "Explicit past reference: 'we discussed', 'you mentioned', 'last time', "
            "'remember when', 'as I said before'"
        )
    )
    has_definite_article: bool = Field(
        description="'the function', 'the bug', 'the config' — assumes shared context"
    )
    is_standalone_question: bool = Field(
        description=(
            "Question that makes sense without conversation history "
            "(code/concept questions vs 'what did we decide?')"
        )
    )
    conversation_turn: int = Field(description="0-indexed user turn number in current conversation")
    last_recall_had_results: bool = Field(
        default=True,
        description="Did the previous message's Recall query return >0 chunks?",
    )
    rag_corpora_active: bool = Field(description="Are any non-Recall corpora checked?")


class RecallFusionOverrides(BaseModel):
    """Per-message overrides applied when querying Recall.

    The gate generates these. They do not permanently change config.
    They are applied only for this single Recall query.
    """

    include_vector: bool | None = Field(
        default=None,
        description="Override vector leg. None=use request/default.",
    )
    include_sparse: bool | None = Field(
        default=None,
        description="Override sparse leg. None=use request/default.",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description=(
            "Override final_k for the Recall query. Lower than RAG since "
            "chat chunks are smaller."
        ),
    )
    enable_rerank: bool | None = Field(
        default=None,
        description="Override reranker for Recall. None=use config default.",
    )
    recency_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="How much to weight recent messages over relevance (0=relevance, 1=recency).",
    )


class RecallPlan(BaseModel):
    """The gate's decision for whether/how to query Recall for a single message."""

    intensity: RecallIntensity = Field(description="How aggressively to query Recall.")
    fusion_overrides: RecallFusionOverrides = Field(
        default_factory=RecallFusionOverrides,
        description="Per-message parameter patches for Recall query.",
    )
    signals: RecallSignals = Field(description="Signals that drove this decision.")
    reason: str = Field(
        description=(
            "Human-readable explanation for the decision. "
            "E.g., 'Greeting — skipping Recall' or 'Past reference — querying Recall'"
        )
    )
    user_override: bool = Field(
        default=False,
        description="True if the user manually overrode intensity for this message.",
    )


class RecallGateConfig(BaseModel):
    """Configuration for the Recall gate. Lives at ChatConfig.recall_gate.

    Controls the heuristic that decides per-message Recall behavior.
    NOTE: This only affects Recall (chat memory). RAG corpora are always queried when checked.
    """

    enabled: bool = Field(
        default=True,
        description="Enable smart gating. False=always query Recall when checked.",
    )

    default_intensity: RecallIntensity = Field(
        default=RecallIntensity.standard,
        description="Fallback when classifier is uncertain.",
    )

    # Skip thresholds
    skip_greetings: bool = Field(
        default=True,
        description="Skip Recall for greetings, farewells, acknowledgments.",
    )
    skip_standalone_questions: bool = Field(
        default=True,
        description=(
            "Skip Recall for questions that don't reference past context. "
            "'How does auth work?' doesn't need chat history."
        ),
    )
    skip_when_rag_active: bool = Field(
        default=False,
        description=(
            "Skip Recall when RAG corpora are checked. Assumes user wants code context, not chat history. "
            "Default False — let both contribute."
        ),
    )
    skip_max_tokens: int = Field(
        default=4,
        ge=1,
        le=20,
        description="Messages with ≤ this many tokens are skip candidates (only if they match a skip pattern).",
    )

    # Light triggers
    light_for_short_questions: bool = Field(
        default=True,
        description="Use sparse-only for short questions (< 10 tokens) without explicit recall triggers.",
    )
    light_top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="top_k when intensity=light.",
    )

    # Standard defaults
    standard_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="top_k for standard Recall queries.",
    )
    standard_recency_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Default recency weight for Recall (recent messages often more relevant).",
    )

    # Deep triggers
    deep_on_explicit_reference: bool = Field(
        default=True,
        description="Trigger deep when message explicitly references past conversation.",
    )
    deep_top_k: int = Field(
        default=10,
        ge=3,
        le=30,
        description="top_k when intensity=deep.",
    )
    deep_recency_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="recency_weight for deep (higher when user explicitly asks about the past).",
    )

    # Transparency
    show_gate_decision: bool = Field(
        default=True,
        description="Show gate decision (intensity, reason) in status bar.",
    )
    show_signals: bool = Field(
        default=False,
        description="Show raw RecallSignals in debug footer (dev mode).",
    )


class ImageAttachment(BaseModel):
    """Single image attached to a chat message.

    Exactly ONE of `url` or `base64` must be provided.
    """

    url: str | None = Field(default=None, description="Remote URL")
    base64: str | None = Field(
        default=None,
        description="Base64 data URI (no data: prefix required)",
    )
    mime_type: str = Field(default="image/png", description="MIME type (e.g., image/png)")

    @model_validator(mode="after")
    def _check_source(self) -> Self:
        if not self.url and not self.base64:
            raise ValueError("Must provide either url or base64")
        if self.url and self.base64:
            raise ValueError("Provide only one of url or base64")
        return self


class ChatRequest(BaseModel):
    """Chat request — composable data sources, not modes."""

    message: str = Field(description="User's message")

    repo_id: str = Field(
        default="",
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )

    sources: ActiveSources = Field(
        default_factory=ActiveSources,
        description=(
            "Checked sources. Empty corpus_ids = no retrieval. If recall_default is not present, "
            "Recall is OFF for both retrieval and indexing."
        ),
    )

    recall_intensity: RecallIntensity | None = Field(
        default=None,
        description=(
            "User override for Recall (chat memory) query intensity. None=auto (gate decides). "
            "Does not affect RAG corpus queries."
        ),
    )

    conversation_id: str | None = Field(default=None, description="Continue existing conversation")
    stream: bool = Field(default=False, description="Stream the response")
    images: list[ImageAttachment] = Field(
        default_factory=list,
        max_length=10,
        description=(
            "Optional images for vision. Max 10 by schema; server further limits by "
            "config.chat.multimodal.max_images_per_message."
        ),
    )
    model_override: str = Field(default="", description="Override chat model for this request (empty=default)")
    include_vector: bool = Field(default=True, description="Include vector retrieval results")
    include_sparse: bool = Field(default=True, description="Include sparse/BM25 retrieval results")
    include_graph: bool = Field(
        default=False,
        description="Advanced. Graph leg runs per-corpus; Recall only if ChatConfig.recall.graph_enabled.",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Override retrieval.final_k for this message (leave null to use config default)",
    )
    cache_mode: Literal["default", "bypass", "refresh"] = Field(
        default="default",
        description="Per-request cache mode override.",
    )


class RerankDebugInfo(BaseModel):
    """Reranker status for a single retrieval run (best-effort)."""

    enabled: bool = Field(description="Whether reranking was enabled for this run.")
    mode: str = Field(description="Reranker mode used (cloud/local/learning/none).")
    ok: bool = Field(description="Whether reranking completed without error.")
    applied: bool = Field(description="Whether reranking was actually applied to the results.")
    candidates_reranked: int = Field(default=0, ge=0, description="Number of candidates reranked.")
    skipped_reason: str | None = Field(default=None, description="Reason reranking was skipped (if any).")
    error: str | None = Field(default=None, description="Raw reranker error (if any).")
    error_message: str | None = Field(default=None, description="Short user-facing error message (if available).")
    debug_trace_id: str | None = Field(
        default=None,
        description="Provider debug trace id when available (e.g., x-debug-trace-id).",
    )
    config_corpus_id: str | None = Field(
        default=None,
        description="Corpus id whose config was used for reranking (for mixed-corpus queries).",
    )


class ChatDebugInfo(BaseModel):
    """Developer-facing debug metadata for a single chat answer."""

    llm_used: bool = Field(
        default=True,
        description="Whether an LLM/provider response was successfully used for the answer.",
    )
    llm_error: str | None = Field(
        default=None,
        description="Short best-effort reason generation failed or was unavailable (never includes secrets).",
    )

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Heuristic confidence score for this answer (0-1).",
    )

    provider: ChatProviderInfo | None = Field(
        default=None,
        description="Provider route selected for this answer.",
    )

    recall_plan: RecallPlan | None = Field(
        default=None,
        description=(
            "Recall gate decision for this message (Recall only; RAG corpora are always queried when checked)."
        ),
    )

    # Per-message leg toggles (what user requested)
    include_vector: bool = Field(default=True, description="Vector leg requested for this message")
    include_sparse: bool = Field(default=True, description="Sparse/BM25 leg requested for this message")
    include_graph: bool = Field(default=True, description="Graph leg requested for this message")

    # Config enablement (what actually ran is include_* AND *_enabled)
    vector_enabled: bool | None = Field(default=None, description="Vector leg enabled in config")
    sparse_enabled: bool | None = Field(default=None, description="Sparse leg enabled in config")
    graph_enabled: bool | None = Field(default=None, description="Graph leg enabled in config")

    # Fusion parameters
    fusion_method: Literal["rrf", "weighted"] | None = Field(
        default=None, description="Fusion method used for retrieval results"
    )
    rrf_k: int | None = Field(default=None, ge=1, le=200, description="RRF k (if fusion_method is rrf)")
    vector_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Vector weight (if fusion_method is weighted)"
    )
    sparse_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Sparse weight (if fusion_method is weighted)"
    )
    graph_weight: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Graph weight (if fusion_method is weighted)"
    )
    normalize_scores: bool | None = Field(default=None, description="Whether leg score normalization was enabled")

    # Counts + summary statistics
    final_k_used: int | None = Field(default=None, ge=1, le=500, description="Final K used for retrieval context")
    vector_results: int | None = Field(default=None, ge=0, description="Vector leg results returned")
    sparse_results: int | None = Field(default=None, ge=0, description="Sparse leg results returned")
    graph_entity_hits: int | None = Field(default=None, ge=0, description="Graph entity hits (pre-hydration)")
    graph_hydrated_chunks: int | None = Field(default=None, ge=0, description="Graph hydrated chunks returned")
    final_results: int | None = Field(default=None, ge=0, description="Final fused results returned")
    top1_score: float | None = Field(default=None, description="Top-1 fused score (raw)")
    avg5_score: float | None = Field(default=None, description="Average fused score for top-5 (raw)")
    conf_top1_thresh: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Configured top-1 confidence threshold"
    )
    conf_avg5_thresh: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Configured avg-5 confidence threshold"
    )

    rerank: RerankDebugInfo | None = Field(
        default=None,
        description="Reranker status for the non-Recall (RAG) retrieval stage, when available.",
    )

    fusion_debug: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw fusion debug payload (for developers).",
    )


class TraceExternalLink(BaseModel):
    """External observability link associated with a trace."""

    label: str = Field(description="Human-readable link label.")
    kind: Literal["grafana", "tempo", "langfuse", "custom"] = Field(
        default="custom",
        description="Link target type.",
    )
    url: str = Field(description="Absolute URL for the external observability surface.")
    detail: str | None = Field(default=None, description="Short operator-facing note about the link.")


class TraceCostSummary(BaseModel):
    """Cost attribution summary for one online request."""

    provider: str | None = Field(default=None, description="Provider/gateway used for the generation call.")
    model: str | None = Field(default=None, description="Model identifier used for the generation call.")
    currency: str = Field(default="USD", description="Currency for the attributed cost.")
    input_tokens: int | None = Field(default=None, ge=0, description="Prompt/input tokens when available.")
    output_tokens: int | None = Field(default=None, ge=0, description="Completion/output tokens when available.")
    total_tokens: int | None = Field(default=None, ge=0, description="Total tokens when available.")
    estimated_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Best-effort USD cost for this request when available.",
    )
    cost_source: Literal["provider", "catalog", "unavailable"] = Field(
        default="unavailable",
        description="Whether cost came from provider/gateway truth, catalog fallback, or was unavailable.",
    )
    authoritative: bool = Field(
        default=False,
        description="Whether the cost value came directly from provider/gateway response data.",
    )
    detail: str | None = Field(default=None, description="Short note about how the cost was derived.")


class TraceRouteSummary(BaseModel):
    """Operator-facing route summary for one online request."""

    route_name: str = Field(description="Logical route name, such as chat or search.")
    path: str = Field(description="HTTP path for the request.")
    method: str = Field(description="HTTP method for the request.")
    provider: ChatProviderInfo | None = Field(default=None, description="Selected provider route when applicable.")
    corpus_ids: list[str] = Field(default_factory=list, description="Corpus ids involved in the request.")
    include_vector: bool | None = Field(default=None, description="Whether vector retrieval was requested.")
    include_sparse: bool | None = Field(default=None, description="Whether sparse retrieval was requested.")
    include_graph: bool | None = Field(default=None, description="Whether graph retrieval was requested.")
    vector_results: int | None = Field(default=None, ge=0, description="Vector leg results returned.")
    sparse_results: int | None = Field(default=None, ge=0, description="Sparse leg results returned.")
    graph_results: int | None = Field(default=None, ge=0, description="Graph leg hydrated chunks returned.")
    final_results: int | None = Field(default=None, ge=0, description="Final results returned to the caller.")
    llm_used: bool | None = Field(default=None, description="Whether an LLM/provider response was used.")
    llm_error: str | None = Field(default=None, description="Short reason generation failed or was unavailable.")


class TraceEvent(BaseModel):
    """Single trace event (local tracing)."""

    kind: str = Field(description="Event kind identifier (e.g., retrieval.vector, fusion.rrf)")
    ts: int = Field(ge=0, description="Event timestamp (epoch milliseconds)")
    msg: str | None = Field(default=None, description="Human-readable event message")
    data: dict[str, Any] = Field(default_factory=dict, description="Structured event payload")


class Trace(BaseModel):
    """Trace payload for a single run."""

    run_id: str = Field(description="Run identifier for correlation")
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    started_at_ms: int = Field(ge=0, description="Run start time (epoch milliseconds)")
    ended_at_ms: int | None = Field(default=None, ge=0, description="Run end time (epoch milliseconds)")
    trace_id: str | None = Field(default=None, description="Canonical trace id for the request when available.")
    root_span_id: str | None = Field(default=None, description="Root span id for the request when available.")
    correlation_id: str | None = Field(default=None, description="Stable correlation id propagated across the request.")
    route_summary: TraceRouteSummary | None = Field(
        default=None,
        description="Operator-facing route summary for the request.",
    )
    external_links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="External observability links associated with this trace.",
    )
    cost_summary: TraceCostSummary | None = Field(
        default=None,
        description="Best-effort cost attribution for the request.",
    )
    events: list[TraceEvent] = Field(default_factory=list, description="Ordered trace events")


class TracesLatestResponse(BaseModel):
    """Response payload for /api/traces/latest."""

    repo: str | None = Field(default=None, description="Corpus identifier for the returned trace (if any)")
    run_id: str | None = Field(default=None, description="Run identifier for the returned trace (if any)")
    trace: Trace | None = Field(default=None, description="Trace payload (null if none available)")


class ObservabilityComponentStatus(BaseModel):
    """Status for one observability component or backend."""

    id: str = Field(description="Stable component identifier.")
    label: str = Field(description="Human-readable component label.")
    group: str = Field(default="observability", description="Operator grouping for this component.")
    enabled: bool = Field(description="Whether the component is enabled by config.")
    configured: bool = Field(description="Whether the component has the minimum config required to operate.")
    reachable: bool | None = Field(default=None, description="Whether the component endpoint was reachable, when checked.")
    detail: str | None = Field(default=None, description="Short operator-facing detail or error message.")
    url: str | None = Field(default=None, description="Configured URL for the component when applicable.")
    severity: Literal["healthy", "info", "warning", "critical"] = Field(
        default="info",
        description="Computed incident/severity state for the component.",
    )
    slo_state: Literal["healthy", "at_risk", "breached", "unknown"] = Field(
        default="unknown",
        description="Service-level state inferred for this component.",
    )
    operator_hint: str | None = Field(default=None, description="Component-local operator hint.")
    links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Curated deep links relevant to this component.",
    )


class ObservabilityWorkbenchLink(BaseModel):
    """Workbench deep link for an observability workflow."""

    label: str = Field(description="Short user-facing label.")
    path: str = Field(description="Application path or URL for this destination.")
    kind: Literal["route", "external"] = Field(default="route", description="Whether this is in-product or external.")
    subtab: str | None = Field(default=None, description="Optional workbench subtab identifier.")
    description: str | None = Field(default=None, description="Operator-facing explanation for the destination.")


class ObservabilityDashboardVariable(BaseModel):
    """Declared Grafana/dashboard variable surfaced in the catalog."""

    id: str = Field(description="Stable variable identifier.")
    label: str = Field(description="Human-readable variable label.")
    kind: Literal["textbox", "custom", "time_range"] = Field(default="textbox", description="Grafana variable kind.")
    default_value: str = Field(default="*", description="Default value used for the variable.")
    description: str | None = Field(default=None, description="Operator hint for the variable.")
    values: list[str] = Field(default_factory=list, description="Explicit choices for custom variables.")


class ObservabilityDashboardFamily(BaseModel):
    """Catalog entry for one Grafana dashboard family."""

    id: str = Field(description="Stable dashboard family identifier.")
    title: str = Field(description="Dashboard title shown to operators.")
    description: str = Field(description="Short explanation of what this dashboard is for.")
    uid: str = Field(description="Provisioned Grafana dashboard UID.")
    slug: str = Field(description="Provisioned Grafana dashboard slug.")
    category: str = Field(description="High-level grouping such as oncall, quality, or cost.")
    default: bool = Field(default=False, description="Whether this is the default landing dashboard.")
    tags: list[str] = Field(default_factory=list, description="Dashboard tags from provisioning metadata.")
    variables: list[ObservabilityDashboardVariable] = Field(
        default_factory=list,
        description="Declared dashboard variables expected to be available in Grafana.",
    )
    links: list[TraceExternalLink] = Field(default_factory=list, description="External links for this dashboard.")
    workbench_links: list[ObservabilityWorkbenchLink] = Field(
        default_factory=list,
        description="Related in-product workbench destinations.",
    )


class ObservabilityCatalogResponse(BaseModel):
    """Catalog of dashboard and workbench observability surfaces."""

    ok: bool = Field(default=True)
    generated_at: datetime | None = Field(default=None, description="When the catalog payload was generated.")
    dashboards: list[ObservabilityDashboardFamily] = Field(
        default_factory=list,
        description="Curated Grafana dashboard families available to operators.",
    )
    workbench_links: list[ObservabilityWorkbenchLink] = Field(
        default_factory=list,
        description="Primary in-product destinations tied to observability workflows.",
    )
    external_links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Cross-stack external links surfaced alongside the catalog.",
    )


class ObservabilityIncidentChange(BaseModel):
    """Correlated change item attached to an incident."""

    kind: str = Field(description="Change kind such as prompt_set, config, model_route, or dataset.")
    label: str = Field(description="Human-readable change label.")
    previous_value: str | None = Field(default=None, description="Prior value when known.")
    current_value: str | None = Field(default=None, description="Current value when known.")
    detail: str | None = Field(default=None, description="Operator-facing context for the change.")


class ObservabilityIncident(BaseModel):
    """Unified observability incident entry."""

    id: str = Field(description="Stable incident identifier.")
    title: str = Field(description="Short incident title.")
    summary: str = Field(description="High-signal incident summary.")
    source: str = Field(description="Incident source family such as infrastructure, workflow, or eval.")
    severity: Literal["healthy", "info", "warning", "critical"] = Field(
        default="warning",
        description="Severity used for wake-up and prioritization.",
    )
    status: Literal["firing", "warning", "resolved"] = Field(
        default="firing",
        description="Current lifecycle state for the incident.",
    )
    started_at: datetime | None = Field(default=None, description="When the incident started or was detected.")
    owner: str | None = Field(default=None, description="Suggested on-call owner or team.")
    component_ids: list[str] = Field(default_factory=list, description="Affected component ids.")
    dashboard_ids: list[str] = Field(default_factory=list, description="Relevant dashboard family ids.")
    links: list[TraceExternalLink] = Field(default_factory=list, description="External links for triage.")
    workbench_links: list[ObservabilityWorkbenchLink] = Field(
        default_factory=list,
        description="In-product destinations for the incident.",
    )
    muted: bool = Field(default=False, description="Whether the incident is muted/silenced.")
    slo_state: Literal["healthy", "at_risk", "breached", "unknown"] = Field(
        default="unknown",
        description="Associated SLO state for the incident.",
    )
    operator_hint: str | None = Field(default=None, description="Recommended next operator action.")
    change_correlation: list[ObservabilityIncidentChange] = Field(
        default_factory=list,
        description="Changes correlated against the incident.",
    )


class ObservabilityIncidentsResponse(BaseModel):
    """Unified incident feed for the observability workspace."""

    ok: bool = Field(default=True)
    generated_at: datetime | None = Field(default=None, description="When the incidents payload was generated.")
    incidents: list[ObservabilityIncident] = Field(default_factory=list, description="Active or recent incidents.")
    total_count: int = Field(default=0, ge=0, description="Total incident count in this payload.")
    critical_count: int = Field(default=0, ge=0, description="Critical incident count in this payload.")


class ObservabilityMetricDelta(BaseModel):
    """Current/previous metric values and their delta."""

    current_value: float | None = Field(default=None, description="Latest metric value.")
    previous_value: float | None = Field(default=None, description="Previous metric value when available.")
    absolute_delta: float | None = Field(default=None, description="Current minus previous.")
    percent_delta: float | None = Field(default=None, description="Percentage delta vs previous when available.")


class BenchmarkBreakdownDelta(BaseModel):
    """Per-phase benchmark timing delta."""

    phase: str = Field(description="Benchmark breakdown phase.")
    current_ms: float | None = Field(default=None, ge=0.0, description="Latest average phase duration in ms.")
    previous_ms: float | None = Field(default=None, ge=0.0, description="Previous average phase duration in ms.")
    delta_ms: float | None = Field(default=None, description="Current minus previous duration in ms.")


class EvalObservabilitySummaryResponse(BaseModel):
    """Corpus-scoped eval observability summary."""

    ok: bool = Field(default=True)
    repo_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
        description="Optional corpus identifier for the summary.",
    )
    latest_run_id: str | None = Field(default=None, description="Most recent eval run id.")
    previous_run_id: str | None = Field(default=None, description="Previous eval run id when available.")
    latest_completed_at: datetime | None = Field(default=None, description="Completion time for the latest eval run.")
    freshness_minutes: float | None = Field(default=None, ge=0.0, description="How old the latest eval run is.")
    total_questions: int = Field(default=0, ge=0, description="Question count for the latest eval run.")
    ai_comparison_ready: bool = Field(
        default=False,
        description="Whether a comparison-ready pair of runs exists for AI analysis.",
    )
    top1_accuracy: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    topk_accuracy: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    mrr: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    ndcg_at_10: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    map_at_5: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    recall_at_5: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    recall_at_10: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    improved_count: int = Field(default=0, ge=0, description="Question count that improved vs previous run.")
    regressed_count: int = Field(default=0, ge=0, description="Question count that regressed vs previous run.")
    stable_count: int = Field(default=0, ge=0, description="Question count with no top-k state change.")
    latest_bundle_id: str | None = Field(default=None, description="Latest bundle id tied to the eval run.")
    latest_prompt_set_ref: LineageRef | None = Field(default=None, description="Prompt set used by the latest eval run.")
    previous_prompt_set_ref: LineageRef | None = Field(default=None, description="Prompt set used by the previous eval run.")
    operator_hint: str | None = Field(default=None, description="Suggested next step for eval triage.")


class BenchmarkObservabilitySummaryResponse(BaseModel):
    """Corpus-scoped benchmark observability summary."""

    ok: bool = Field(default=True)
    repo_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
        description="Optional corpus identifier for the summary.",
    )
    latest_run_id: str | None = Field(default=None, description="Most recent benchmark run id.")
    previous_run_id: str | None = Field(default=None, description="Previous benchmark run id when available.")
    latest_started_at: datetime | None = Field(default=None, description="Start time for the latest benchmark run.")
    latest_model_count: int = Field(default=0, ge=0, description="Model count in the latest benchmark run.")
    latest_error_count: int = Field(default=0, ge=0, description="Error count in the latest benchmark run.")
    previous_error_count: int = Field(default=0, ge=0, description="Error count in the previous benchmark run.")
    provider_routes: list[str] = Field(default_factory=list, description="Provider/model routes used in the latest run.")
    average_latency_ms: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    p95_latency_ms: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    response_length_mean: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    success_rate: ObservabilityMetricDelta = Field(default_factory=ObservabilityMetricDelta)
    breakdown_deltas: list[BenchmarkBreakdownDelta] = Field(
        default_factory=list,
        description="Timing shifts by benchmark breakdown phase.",
    )
    latest_bundle_id: str | None = Field(default=None, description="Latest bundle id tied to the benchmark run.")
    latest_prompt_set_ref: LineageRef | None = Field(default=None, description="Prompt set used by the latest benchmark run.")
    previous_prompt_set_ref: LineageRef | None = Field(default=None, description="Prompt set used by the previous benchmark run.")
    operator_hint: str | None = Field(default=None, description="Suggested next step for benchmark triage.")


class PromptObservabilitySummaryResponse(BaseModel):
    """Prompt-set observability and change-correlation summary."""

    ok: bool = Field(default=True)
    repo_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
        description="Optional corpus identifier for the summary.",
    )
    current_prompt_set_ref: LineageRef | None = Field(default=None, description="Current prompt-set lineage ref.")
    previous_prompt_set_ref: LineageRef | None = Field(default=None, description="Previous prompt-set lineage ref.")
    latest_eval_run_id: str | None = Field(default=None, description="Latest eval run id used for prompt correlation.")
    latest_eval_prompt_set_ref: LineageRef | None = Field(default=None, description="Prompt set pinned to the latest eval run.")
    latest_benchmark_run_id: str | None = Field(
        default=None,
        description="Latest benchmark run id used for prompt correlation.",
    )
    latest_benchmark_prompt_set_ref: LineageRef | None = Field(
        default=None,
        description="Prompt set pinned to the latest benchmark run.",
    )
    changed_since_latest_eval: bool = Field(default=False, description="Whether prompts changed since the latest eval.")
    changed_since_latest_benchmark: bool = Field(
        default=False,
        description="Whether prompts changed since the latest benchmark.",
    )
    eval_regression_suspected: bool = Field(default=False, description="Whether prompt changes correlate with eval regression.")
    benchmark_regression_suspected: bool = Field(
        default=False,
        description="Whether prompt changes correlate with benchmark regression.",
    )
    pending_verification: bool = Field(
        default=False,
        description="Whether the current prompt set has not yet been re-verified by eval/benchmark runs.",
    )
    recent_prompt_set_count: int = Field(default=0, ge=0, description="Unique prompt-set versions seen in recent bundles.")
    operator_hint: str | None = Field(default=None, description="Suggested next step for prompt-regression triage.")


class ObservabilityStatusResponse(BaseModel):
    """Operator-facing readiness summary for the observability stack."""

    ok: bool = Field(default=True)
    generated_at: datetime | None = Field(default=None, description="When this status snapshot was generated.")
    mode: Literal["local", "otel", "otel_langfuse", "off"] = Field(
        default="local",
        description="Normalized observability mode for the current config.",
    )
    severity: Literal["healthy", "info", "warning", "critical"] = Field(
        default="info",
        description="Overall observability severity for the current stack.",
    )
    slo_state: Literal["healthy", "at_risk", "breached", "unknown"] = Field(
        default="unknown",
        description="Overall SLO state for the current stack.",
    )
    components: list[ObservabilityComponentStatus] = Field(
        default_factory=list,
        description="Observability components/backends and their readiness state.",
    )
    links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Useful external links for the current observability config.",
    )
    catalog_path: str = Field(default="/api/observability/catalog", description="Catalog endpoint for dashboard/workbench surfaces.")
    incidents_path: str = Field(default="/api/observability/incidents", description="Incident-feed endpoint for operators.")
    incident_count: int = Field(default=0, ge=0, description="Incident count surfaced alongside this status snapshot.")
    critical_incident_count: int = Field(default=0, ge=0, description="Critical incident count for the current snapshot.")
    operator_hint: str | None = Field(default=None, description="High-signal next-step guidance for operators.")


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    run_id: str = Field(description="Unique identifier for this chat run (trace/log correlation)")
    started_at_ms: int = Field(ge=0, description="Chat run start time (epoch milliseconds)")
    ended_at_ms: int | None = Field(default=None, ge=0, description="Chat run end time (epoch milliseconds)")
    debug: ChatDebugInfo | None = Field(default=None, description="Developer debug metadata for this answer")
    conversation_id: str = Field(description="Conversation identifier")
    message: Message = Field(description="Assistant's response message")
    sources: list[ChunkMatch] = Field(description="Sources used for response")
    tokens_used: int = Field(description="Tokens consumed")


class ModelCatalogEntry(BaseModel):
    """Single model catalog entry served by /api/models."""

    provider: str = Field(description="Provider identifier (for example: openai, anthropic, ragweld)")
    family: str = Field(description="Model family")
    model: str = Field(description="Model identifier")
    components: list[Literal["GEN", "EMB", "RERANK"]] = Field(
        default_factory=list,
        description="Capabilities supported by this model",
    )
    context: int | None = Field(default=None, ge=0, description="Maximum context tokens when known")
    dimensions: int | None = Field(default=None, ge=0, description="Embedding dimensions when applicable")
    unit: Literal["1k_tokens", "request"] | str | None = Field(
        default=None,
        description="Pricing unit (if priced)",
    )
    input_per_1k: float | None = Field(default=None, ge=0.0, description="GEN input cost per 1k tokens")
    output_per_1k: float | None = Field(default=None, ge=0.0, description="GEN output cost per 1k tokens")
    embed_per_1k: float | None = Field(default=None, ge=0.0, description="EMB cost per 1k tokens")
    rerank_per_1k: float | None = Field(default=None, ge=0.0, description="RERANK cost per 1k tokens")
    per_request: float | None = Field(default=None, ge=0.0, description="Cost per request")
    base_url: str | None = Field(default=None, description="Optional provider base URL")
    notes: str | None = Field(default=None, description="Freeform notes")
    selection_roles: list[Literal["generation", "embedding_provider", "reranker_cloud"]] = Field(
        default_factory=list,
        description="Runtime selection surfaces that should expose this row.",
    )
    selection_status: Literal["runtime_selectable", "catalog_only"] = Field(
        default="catalog_only",
        description="Whether this row is currently selectable in the runtime product surface.",
    )
    selection_reason: str | None = Field(
        default=None,
        description="Why the row is catalog-only when not runtime selectable.",
    )


class ModelCatalogResponse(BaseModel):
    """Response payload for GET /api/models."""

    currency: str | None = Field(default="USD")
    last_updated: str | None = Field(default=None)
    sources: list[str] = Field(default_factory=list)
    models: list[ModelCatalogEntry] = Field(default_factory=list)


class ModelCatalogUpsertRequest(BaseModel):
    """Request payload for POST /api/models/upsert."""

    provider: str = Field(min_length=1, description="Provider identifier")
    model: str = Field(min_length=1, description="Model identifier")
    family: Literal["gen", "embed", "rerank", "misc"] = Field(default="gen")
    base_url: str | None = Field(default=None, description="Provider base URL (optional)")
    unit: Literal["1k_tokens", "request"] = Field(default="1k_tokens")
    input_per_1k: float | None = Field(default=None, ge=0.0)
    output_per_1k: float | None = Field(default=None, ge=0.0)
    embed_per_1k: float | None = Field(default=None, ge=0.0)
    rerank_per_1k: float | None = Field(default=None, ge=0.0)
    per_request: float | None = Field(default=None, ge=0.0)
    context: int | None = Field(default=None, ge=0)
    dimensions: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None)


class ModelCatalogUpsertResponse(BaseModel):
    """Response payload for POST /api/models/upsert."""

    ok: bool = Field(default=True)
    action: Literal["created", "updated"] = Field(description="Whether an entry was created or updated")
    model: ModelCatalogEntry = Field(description="Upserted catalog model entry")


class RuntimeOption(BaseModel):
    """Generic runtime capability option."""

    id: str = Field(description="Stable identifier for the capability")
    label: str = Field(description="Human-readable label")
    description: str = Field(description="Short explanation of what the runtime supports")


class EmbeddingRuntimeProviderCapability(BaseModel):
    """Embedding provider capability exposed by the runtime."""

    provider: str = Field(description="Embedding provider identifier")
    label: str = Field(description="Human-readable provider label")
    description: str = Field(description="Short explanation of the provider runtime path")
    badge: Literal["local", "cloud"] = Field(description="UI badge hint for the provider")
    model_config_field: str = Field(description="Config field that stores the effective model id for this provider")
    tokenizer_strategies: list[str] = Field(
        default_factory=list,
        description="Tokenizer strategies required or supported for this provider runtime path.",
    )


class EmbeddingRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for embeddings."""

    backends: list[RuntimeOption] = Field(default_factory=list, description="Dense embedding backends supported today.")
    providers: list[EmbeddingRuntimeProviderCapability] = Field(
        default_factory=list,
        description="Embedding providers supported for embedding_backend='provider'.",
    )


class RerankerRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for reranking."""

    modes: list[RuntimeOption] = Field(default_factory=list, description="Reranker modes exposed by the product.")
    cloud_providers: list[RuntimeOption] = Field(
        default_factory=list,
        description="Cloud reranker providers that execute in the current runtime.",
    )
    learning_backends: list[RuntimeOption] = Field(
        default_factory=list,
        description="Learning reranker backends supported by the runtime.",
    )


class ChunkingRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for chunking."""

    strategies: list[RuntimeOption] = Field(default_factory=list, description="Chunking strategies implemented today.")


class IndexingRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for indexing backends."""

    dense_backends: list[RuntimeOption] = Field(
        default_factory=list,
        description="Dense indexing execution paths used during indexing.",
    )
    storage_backends: list[RuntimeOption] = Field(
        default_factory=list,
        description="Storage/index backends populated during indexing.",
    )


class SearchRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for retrieval/search backends."""

    vector_backends: list[RuntimeOption] = Field(default_factory=list, description="Vector search backends.")
    sparse_backends: list[RuntimeOption] = Field(default_factory=list, description="Sparse search backends.")
    graph_backends: list[RuntimeOption] = Field(default_factory=list, description="Graph search backends.")


class GenerationRuntimeCapabilities(BaseModel):
    """Runtime capability matrix for generation routing and serving."""

    routing_backends: list[RuntimeOption] = Field(
        default_factory=list,
        description="Gateway/routing backends that can dispatch generation requests.",
    )
    serving_backends: list[RuntimeOption] = Field(
        default_factory=list,
        description="Serving runtimes that can execute generation models today.",
    )
    default_route: ChatProviderInfo | None = Field(
        default=None,
        description="Provider route selected by the current config/env for a default chat request.",
    )


class RuntimeCapabilitiesResponse(BaseModel):
    """Response payload for GET /api/runtime-capabilities."""

    generation: GenerationRuntimeCapabilities = Field(default_factory=GenerationRuntimeCapabilities)
    embedding: EmbeddingRuntimeCapabilities = Field(default_factory=EmbeddingRuntimeCapabilities)
    reranker: RerankerRuntimeCapabilities = Field(default_factory=RerankerRuntimeCapabilities)
    chunking: ChunkingRuntimeCapabilities = Field(default_factory=ChunkingRuntimeCapabilities)
    indexing: IndexingRuntimeCapabilities = Field(default_factory=IndexingRuntimeCapabilities)
    search: SearchRuntimeCapabilities = Field(default_factory=SearchRuntimeCapabilities)


class SecretRequirement(BaseModel):
    """Env-only secret or credential required by one or more operator surfaces."""

    id: str = Field(description="Stable secret identifier used by field descriptors and readiness responses.")
    env_var: str = Field(description="Backing environment variable name.")
    label: str = Field(description="Human-readable label for operators.")
    description: str = Field(description="Short explanation of where the secret is used.")
    integrations: list[str] = Field(
        default_factory=list,
        description="Integration contracts that may depend on this secret.",
    )
    optional: bool = Field(
        default=False,
        description="Whether the secret is optional and therefore not always a readiness blocker.",
    )
    ui_surface: str | None = Field(
        default=None,
        description="Primary operator surface where this secret is configured or inspected.",
    )


class SecretRequirementStatus(BaseModel):
    """Current status for one env-only secret requirement."""

    requirement: SecretRequirement = Field(description="Static requirement metadata.")
    configured: bool = Field(description="Whether the env var is present and non-empty in the current process.")
    blocker_for_integrations: list[str] = Field(
        default_factory=list,
        description="Integrations currently blocked by this missing secret.",
    )


class ConfigFieldDescriptor(BaseModel):
    """Registry entry for one leaf config field in TriBridConfig."""

    path: str = Field(description="Dotted leaf path inside TriBridConfig.")
    section: str = Field(description="Top-level TriBridConfig section.")
    label: str = Field(description="Human-readable field label.")
    type: str = Field(description="Normalized UI type for the field (string, integer, number, boolean, enum, array, object).")
    default: Any | None = Field(default=None, description="Default value from the Pydantic model, when serializable.")
    description: str | None = Field(default=None, description="Field description pulled from the source-of-truth model.")
    scope: Literal["global", "corpus"] = Field(description="Primary operator scope for the field.")
    integration: str = Field(description="Integration contract responsible for this field.")
    exposure_level: Literal["basic", "advanced", "expert"] = Field(
        description="Layered operator exposure tier for the field.",
    )
    impact: Literal["live", "restart", "reindex", "redeploy"] = Field(
        description="Primary operator impact when the field changes.",
    )
    secret_dependency_ids: list[str] = Field(
        default_factory=list,
        description="Env-only secrets that may be required for this field to take effect.",
    )
    ui_surface: str = Field(description="Workbench configuration surface that owns this field.")
    enum_values: list[str] = Field(
        default_factory=list,
        description="Allowed enum values when the field is a closed choice.",
    )
    read_only: bool = Field(
        default=False,
        description="Whether the field is exposed for inspection only in the configuration center.",
    )


class ConfigIntegrationContract(BaseModel):
    """Registry contract for one OSS integration or protected operator surface."""

    id: str = Field(description="Stable integration identifier.")
    label: str = Field(description="Human-readable integration label.")
    summary: str = Field(description="Short explanation of the subsystem boundary.")
    ui_surface: str = Field(description="Primary workbench surface that owns this contract.")
    required_config_paths: list[str] = Field(
        default_factory=list,
        description="High-signal config fields required to operate this integration.",
    )
    required_secret_ids: list[str] = Field(
        default_factory=list,
        description="Env-only secret requirements that block this integration when missing.",
    )
    readiness_checks: list[str] = Field(
        default_factory=list,
        description="Deterministic checks performed by /api/config/readiness for this integration.",
    )
    blocked_surfaces: list[str] = Field(
        default_factory=list,
        description="Operator surfaces that are misleading or blocked when this contract is not ready.",
    )


class IntegrationReadiness(BaseModel):
    """Current readiness state for one integration contract."""

    id: str = Field(description="Integration identifier.")
    label: str = Field(description="Human-readable integration label.")
    ui_surface: str = Field(description="Primary workbench surface for the integration.")
    state: Literal["ready", "degraded", "unconfigured", "disabled"] = Field(
        description="Current readiness state.",
    )
    enabled: bool = Field(description="Whether the integration is selected or expected by the current config.")
    configured: bool = Field(description="Whether the required config is present.")
    reachable: bool | None = Field(default=None, description="Whether runtime reachability checks passed, when applicable.")
    missing_config_paths: list[str] = Field(
        default_factory=list,
        description="Required config paths that are currently empty or unset.",
    )
    missing_secret_ids: list[str] = Field(
        default_factory=list,
        description="Required env-only secrets that are currently missing.",
    )
    failing_checks: list[str] = Field(
        default_factory=list,
        description="Named readiness checks that are currently failing.",
    )
    blocked_surfaces: list[str] = Field(
        default_factory=list,
        description="Protected surfaces blocked or degraded by this readiness state.",
    )
    operator_hint: str | None = Field(default=None, description="High-signal next-step guidance for operators.")
    links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Useful deep links for debugging or operating the integration.",
    )


class ConfigRegistryResponse(BaseModel):
    """Response payload for GET /api/config/registry."""

    fields: list[ConfigFieldDescriptor] = Field(
        default_factory=list,
        description="Leaf config descriptors derived from TriBridConfig plus manual operator metadata.",
    )
    integrations: list[ConfigIntegrationContract] = Field(
        default_factory=list,
        description="Integration contracts required by the OSS composition branch.",
    )
    secrets: list[SecretRequirement] = Field(
        default_factory=list,
        description="Env-only secret requirements surfaced by the control plane.",
    )


class ConfigReadinessResponse(BaseModel):
    """Response payload for GET /api/config/readiness."""

    ok: bool = Field(default=False, description="Whether the current configuration control plane is ready enough for the protected surfaces.")
    integrations: list[IntegrationReadiness] = Field(
        default_factory=list,
        description="Integration readiness states for the current config and environment.",
    )
    secrets: list[SecretRequirementStatus] = Field(
        default_factory=list,
        description="Configured/missing env-only secrets relevant to the current control plane.",
    )
    operator_hint: str | None = Field(default=None, description="Top-level next-step guidance for operators.")


class FeedbackRequest(BaseModel):
    """Request payload for POST /api/feedback.

    Supports:
    - Learning reranker feedback correlation: event_id + signal (+ optional doc_id/note)
    - UI meta feedback: rating (+ optional comment/timestamp/context)
    """

    # Learning reranker feedback
    event_id: str | None = Field(default=None, description="Event id returned by chat/search for correlation")
    signal: str | None = Field(
        default=None,
        description="Feedback signal (thumbsup|thumbsdown|click|noclick|note|star1..star5)",
    )
    doc_id: str | None = Field(default=None, description="Document id/path (for click-based signals)")
    note: str | None = Field(default=None, description="Optional freeform note")

    # UI/meta feedback (not used for triplet mining)
    rating: int | None = Field(default=None, ge=1, le=5, description="1-5 star rating")
    comment: str | None = Field(default=None, description="Optional comment")
    timestamp: str | None = Field(default=None, description="Client timestamp (ISO string)")
    context: str | None = Field(default=None, description="Feedback context (e.g., chat, evaluation)")

    @model_validator(mode="after")
    def _validate_shape(self) -> Self:
        # Meta feedback: rating-only shape (plus optional comment/timestamp/context).
        if self.rating is not None:
            if self.event_id is not None or self.signal is not None or self.doc_id is not None or self.note is not None:
                raise ValueError("rating feedback must not include event_id/signal/doc_id/note")
            return self

        # Otherwise require event-correlated signal feedback.
        if not self.event_id or not self.signal:
            raise ValueError("Must provide either rating or (event_id and signal)")
        return self


class FeedbackResponse(BaseModel):
    """Response payload for POST /api/feedback."""

    ok: bool = Field(description="Whether feedback was accepted")


class RerankerClickRequest(BaseModel):
    """Request payload for POST /api/reranker/click."""

    event_id: str = Field(description="Event id returned by chat/search for correlation")
    doc_id: str = Field(description="Clicked document id/path")


# =============================================================================
# DOMAIN MODELS - Learning reranker legacy workflow (/api/reranker/*)
# =============================================================================

RerankerLegacyTask = Literal["mining", "training", "evaluating", ""]


class RerankerLegacyTaskResult(BaseModel):
    """Best-effort result payload embedded in /api/reranker/status."""

    ok: bool = Field(description="Whether the task succeeded")
    output: str | None = Field(default=None, description="Human-readable output (if any)")
    error: str | None = Field(default=None, description="Error message (if any)")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")
    metrics: dict[str, float] | None = Field(default=None, description="Evaluation metrics (if any)")
    run_id: str | None = Field(default=None, description="Training run id (if applicable)")


class RerankerLegacyStatus(BaseModel):
    """Status payload for GET /api/reranker/status (legacy polling + inference runtime)."""

    running: bool = Field(description="Whether a task is currently running")
    progress: int = Field(default=0, ge=0, le=100, description="0-100 progress percent")
    task: RerankerLegacyTask = Field(default="", description="Active task (mining|training|evaluating|empty)")
    message: str = Field(default="", description="Status message suitable for UI display")
    result: RerankerLegacyTaskResult | None = Field(default=None, description="Task result (if available)")
    live_output: list[str] = Field(default_factory=list, description="Best-effort streaming output lines")
    run_id: str | None = Field(default=None, description="Training run id (if applicable)")


class RerankerMineResponse(BaseModel):
    """Response payload for POST /api/reranker/mine."""

    ok: bool = Field(description="Whether mining succeeded")
    output: str | None = Field(default=None, description="Human-readable output")
    error: str | None = Field(default=None, description="Error message (if any)")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")


class RerankerTrainLegacyRequest(BaseModel):
    """Request payload for POST /api/reranker/train (legacy UI)."""

    epochs: int | None = Field(default=None, ge=1, le=50)
    batch_size: int | None = Field(default=None, ge=1, le=256)
    max_length: int | None = Field(default=None, ge=32, le=2048)
    lr: float | None = Field(default=None, gt=0.0)
    warmup_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class RerankerTrainLegacyResponse(BaseModel):
    """Response payload for POST /api/reranker/train (legacy UI)."""

    ok: bool = Field(description="Whether training was started")
    output: str | None = Field(default=None, description="Human-readable output")
    error: str | None = Field(default=None, description="Error message (if any)")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")
    run_id: str | None = Field(default=None, description="Training run id")


class RerankerEvaluateResponse(BaseModel):
    """Response payload for POST /api/reranker/evaluate (proxy metrics)."""

    ok: bool = Field(description="Whether evaluation succeeded")
    output: str | None = Field(default=None, description="Human-readable output")
    error: str | None = Field(default=None, description="Error message (if any)")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")
    metrics: dict[str, float] | None = Field(default=None, description="Proxy metrics dict (if ok)")


class CountResponse(BaseModel):
    """Generic count response used by several endpoints."""

    count: int = Field(default=0, ge=0, description="Non-negative count")


class OkResponse(BaseModel):
    """Generic ok response used by several endpoints."""

    ok: bool = Field(description="Whether the operation succeeded")


LineageAliasName = Literal["current", "promoted", "baseline", "canary"]
LineageAssetKind = Literal[
    "prompt_set",
    "config_snapshot",
    "spec_snapshot",
    "model_catalog_snapshot",
    "runtime_model_set",
    "eval_dataset",
    "benchmark_run",
    "eval_run",
    "synthetic_run",
    "synthetic_artifact",
    "published_artifact",
    "reranker_train_run",
    "reranker_model_artifact",
    "agent_train_run",
    "agent_model_artifact",
]
LineageCaptureSource = Literal["runtime", "git", "generated", "published"]


class GitTrackedFile(BaseModel):
    """Digest snapshot for a dirty tracked or untracked worktree file."""

    path: str = Field(description="Repo-relative path when known.")
    status: str = Field(description="Git porcelain status code or synthetic status label.")
    exists: bool = Field(default=True, description="Whether the path existed when the snapshot was taken.")
    sha256: str | None = Field(default=None, description="Best-effort SHA-256 digest of file bytes.")
    bytes: int | None = Field(default=None, ge=0, description="Best-effort file size in bytes.")


class GitSnapshot(BaseModel):
    """Best-effort git context captured when minting lineage versions."""

    commit_sha: str | None = Field(default=None, description="Resolved HEAD commit SHA when available.")
    dirty: bool = Field(default=False, description="Whether the worktree had tracked or untracked changes.")
    dirty_paths: list[str] = Field(default_factory=list, description="Dirty file paths from git status --porcelain.")
    tracked_files: list[GitTrackedFile] = Field(
        default_factory=list,
        description="Per-file digests for dirty paths so dirty worktrees remain reproducible.",
    )


class LineageRef(BaseModel):
    """Compact immutable reference to a lineage version."""

    kind: LineageAssetKind = Field(description="Kind of immutable version being referenced.")
    version_id: str = Field(description="Immutable version identifier.")
    label: str | None = Field(default=None, description="Optional human-readable label for UI display.")


class LineageAssetVersion(BaseModel):
    """Immutable version record for one quality-loop asset."""

    version_id: str = Field(description="Immutable version identifier.")
    kind: LineageAssetKind = Field(description="Asset kind.")
    repo_id: str | None = Field(
        default=None,
        description="Optional corpus identifier when the version is corpus-scoped.",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    created_at: datetime = Field(description="When this version record was created.")
    digest: str = Field(description="Canonical SHA-256 digest used to dedupe identical content.")
    source: LineageCaptureSource = Field(description="How this version was captured.")
    source_paths: list[str] = Field(default_factory=list, description="Underlying file or directory paths.")
    git: GitSnapshot | None = Field(default=None, description="Git context captured when the version was minted.")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Small searchable metadata for lists and UI.")
    payload: dict[str, Any] = Field(default_factory=dict, description="Canonical asset payload snapshot.")
    upstream_refs: list[LineageRef] = Field(
        default_factory=list,
        description="Other immutable versions this asset was derived from.",
    )


class LineageBundle(BaseModel):
    """Top-level immutable bundle pinning the exact versions used together."""

    bundle_id: str = Field(description="Immutable bundle identifier.")
    repo_id: str = Field(
        description="Corpus identifier for this quality-loop bundle.",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    created_at: datetime = Field(description="When this bundle was created.")
    prompt_set: LineageRef | None = Field(default=None, description="Pinned prompt-set version.")
    config_snapshot: LineageRef | None = Field(default=None, description="Pinned config snapshot version.")
    spec_snapshot: LineageRef | None = Field(default=None, description="Pinned spec snapshot version.")
    model_catalog_snapshot: LineageRef | None = Field(default=None, description="Pinned model catalog snapshot version.")
    runtime_model_set: LineageRef | None = Field(default=None, description="Pinned resolved runtime model-set version.")
    eval_dataset: LineageRef | None = Field(default=None, description="Pinned eval dataset version when available.")
    benchmark_runs: list[LineageRef] = Field(default_factory=list, description="Attached benchmark run versions.")
    eval_runs: list[LineageRef] = Field(default_factory=list, description="Attached eval run versions.")
    synthetic_runs: list[LineageRef] = Field(default_factory=list, description="Attached synthetic run versions.")
    synthetic_artifacts: list[LineageRef] = Field(default_factory=list, description="Attached synthetic artifact versions.")
    published_artifacts: list[LineageRef] = Field(default_factory=list, description="Attached published artifact versions.")
    reranker_train_runs: list[LineageRef] = Field(default_factory=list, description="Attached reranker training run versions.")
    reranker_model_artifacts: list[LineageRef] = Field(
        default_factory=list,
        description="Attached reranker model artifact versions.",
    )
    agent_train_runs: list[LineageRef] = Field(default_factory=list, description="Attached agent training run versions.")
    agent_model_artifacts: list[LineageRef] = Field(
        default_factory=list,
        description="Attached agent model artifact versions.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Bundle metadata for UI and audit notes.")


class LineageAlias(BaseModel):
    """Mutable operator alias that points to an immutable bundle."""

    alias: LineageAliasName = Field(description="Operator alias name.")
    repo_id: str = Field(
        description="Corpus identifier for the alias.",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    bundle_id: str = Field(description="Target immutable bundle identifier.")
    updated_at: datetime = Field(description="When the alias was last updated.")


class LineageAssetListResponse(BaseModel):
    """List response for immutable asset versions."""

    ok: bool = Field(default=True, description="Whether the request succeeded.")
    assets: list[LineageAssetVersion] = Field(default_factory=list, description="Immutable asset versions.")


class LineageBundleListResponse(BaseModel):
    """List response for immutable bundles."""

    ok: bool = Field(default=True, description="Whether the request succeeded.")
    bundles: list[LineageBundle] = Field(default_factory=list, description="Immutable lineage bundles.")


class LineageAliasesResponse(BaseModel):
    """List response for corpus-scoped lineage aliases."""

    ok: bool = Field(default=True, description="Whether the request succeeded.")
    aliases: list[LineageAlias] = Field(default_factory=list, description="Mutable alias pointers for this corpus.")


class LineageAliasUpdateRequest(BaseModel):
    """Request payload for setting a bundle alias."""

    bundle_id: str = Field(description="Existing immutable bundle identifier to target.")


class LineageBundleSnapshotRequest(BaseModel):
    """Request payload for explicitly snapshotting the current quality-loop state."""

    set_aliases: list[LineageAliasName] = Field(
        default_factory=list,
        description="Optional aliases to move to the new bundle after the snapshot is created.",
    )


class LineageBundleSnapshotResponse(BaseModel):
    """Response payload for creating or fetching a current-state bundle snapshot."""

    ok: bool = Field(default=True, description="Whether the request succeeded.")
    bundle: LineageBundle = Field(description="Created or reused immutable bundle.")
    aliases: list[LineageAlias] = Field(default_factory=list, description="Aliases updated by this request.")


class BenchmarkRunRequest(BaseModel):
    """Request payload for POST /api/benchmark/run."""

    prompt: str = Field(min_length=1, description="Prompt to run against multiple models.")
    models: list[str] = Field(min_length=2, description="Two to four model overrides to compare.")


class BenchmarkResult(BaseModel):
    """Per-model result from a benchmark run."""

    model: str = Field(description="Model override used for this result row.")
    response: str = Field(default="", description="Best-effort generated response.")
    latency_ms: float = Field(default=0.0, ge=0.0, description="End-to-end latency for this model in milliseconds.")
    breakdown_ms: dict[str, float] = Field(default_factory=dict, description="Timing breakdown by phase.")
    error: str | None = Field(default=None, description="Error string when the model call failed.")
    model_id: str | None = Field(default=None, description="Optional resolved model id.")
    model_name: str | None = Field(default=None, description="Optional human-readable model name.")


class BenchmarkRun(BaseModel):
    """Persisted benchmark run record."""

    run_id: str = Field(description="Unique benchmark run identifier.")
    repo_id: str | None = Field(
        default=None,
        description="Optional corpus identifier when benchmarking within a corpus scope.",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    prompt: str = Field(description="Prompt benchmarked across models.")
    models: list[str] = Field(default_factory=list, description="Requested model overrides.")
    started_at_ms: int = Field(default=0, ge=0, description="Run start timestamp in milliseconds since epoch.")
    ended_at_ms: int = Field(default=0, ge=0, description="Run completion timestamp in milliseconds since epoch.")
    results: list[BenchmarkResult] = Field(default_factory=list, description="Per-model benchmark results.")
    input_bundle_id: str | None = Field(default=None, description="Current bundle id captured before the run started.")
    bundle_id: str | None = Field(default=None, description="Bundle id after attaching this run to lineage.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable benchmark run version reference.")


class BenchmarkRunsResponse(BaseModel):
    """Response payload for listing benchmark runs."""

    ok: bool = Field(default=True, description="Whether the request succeeded.")
    runs: list[BenchmarkRun] = Field(default_factory=list, description="Recent benchmark run records.")


class ModelValidationWarning(BaseModel):
    """A single soft warning about a model assignment in the config."""

    field: str = Field(description="Dotted config field path (e.g. generation.gen_model)")
    model_value: str = Field(description="The model string that triggered the warning")
    message: str = Field(description="Human-readable warning message")


class ModelValidationResult(BaseModel):
    """Result of validating current config model assignments against the catalog."""

    valid: bool = Field(description="True when no hard errors found (warnings are soft)")
    warnings: list[ModelValidationWarning] = Field(
        default_factory=list,
        description="Soft warnings about model assignments",
    )


class RerankerCostsResponse(BaseModel):
    """Response payload for GET /api/reranker/costs."""

    total_24h: float = Field(default=0.0, ge=0.0)
    avg_per_query: float = Field(default=0.0, ge=0.0)


class RerankerNoHitsResponse(BaseModel):
    """Response payload for GET /api/reranker/nohits."""

    queries: list[dict[str, Any]] = Field(default_factory=list, description="Placeholder list of no-hit queries")


class RerankerLogsResponse(BaseModel):
    """Response payload for GET /api/reranker/logs."""

    logs: list[Any] = Field(default_factory=list, description="Parsed JSONL log entries (best-effort)")


class RerankerInfoResponse(BaseModel):
    """Response payload for GET /api/reranker/info (no secrets)."""

    enabled: bool
    reranker_mode: str = Field(default="none", description="Resolved reranker mode")
    reranker_cloud_provider: str | None = Field(default=None)
    reranker_cloud_model: str | None = Field(default=None)
    path: str = Field(default="", description="Selected model path (may be empty)")
    resolved_path: str = Field(default="", description="Resolved model path (best-effort)")
    device: str = Field(default="cpu", description="Compute device (best-effort)")
    alpha: float | None = Field(default=None, description="Reranker alpha (if applicable)")
    topn: int | None = Field(default=None, description="Rerank topn (if applicable)")
    batch: int | None = Field(default=None, description="Rerank batch size (if applicable)")
    maxlen: int | None = Field(default=None, description="Rerank max length (if applicable)")
    snippet_chars: int | None = Field(default=None, description="Snippet chars used for rerank input")


class RerankerScoreRequest(BaseModel):
    """Request payload for POST /api/reranker/score."""

    repo_id: str = Field(
        description="Corpus identifier to score against",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    query: str = Field(description="Query string")
    document: str = Field(description="Document/passage text to score")
    mode: Literal["learning"] | None = Field(
        default=None,
        description="Scoring mode override. Only 'learning' is supported; legacy values normalize to 'learning'.",
    )
    include_logits: bool = Field(
        default=False,
        description="Include backend-specific raw logits when available (best-effort)",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def normalize_mode(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {"local", "hf"}:
                return "learning"
            return val
        return v


class RerankerScoreResponse(BaseModel):
    """Response payload for POST /api/reranker/score."""

    ok: bool = Field(description="Whether scoring succeeded")
    backend: str = Field(default="", description="Resolved backend used to score (mlx_qwen3|transformers|...)")
    score: float = Field(default=0.0, description="Normalized score in [0,1] (best-effort)")
    yes_logit: float | None = Field(default=None, description="Raw yes logit (if include_logits and supported)")
    no_logit: float | None = Field(default=None, description="Raw no logit (if include_logits and supported)")
    error: str | None = Field(default=None, description="Error message (if any)")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")


class RecallIndexRequest(BaseModel):
    """Request payload for POST /api/recall/index."""

    conversation_id: str = Field(description="Conversation identifier to index into Recall")


class RecallIndexResponse(BaseModel):
    """Response payload for POST /api/recall/index."""

    ok: bool = Field(description="Whether indexing was triggered")
    conversation_id: str = Field(description="Conversation identifier")
    chunks_indexed: int = Field(default=0, ge=0, description="Number of chunks indexed into Recall")


class RecallStatusResponse(BaseModel):
    """Response payload for GET /api/recall/status."""

    enabled: bool = Field(description="Whether Recall is enabled")
    corpus_id: str = Field(description="Recall corpus id (default recall_default)")
    exists: bool = Field(description="Whether the Recall corpus exists in Postgres")
    chunk_count: int = Field(default=0, ge=0, description="Approximate number of chunks stored for Recall")


class Entity(BaseModel):
    """Knowledge graph node representing a code entity."""
    entity_id: str = Field(description="Unique identifier")
    name: str = Field(description="Entity name (function name, class name, etc)")
    entity_type: Literal["function", "class", "module", "variable", "concept", "person", "org", "location", "event"] = Field(
        description="Type of entity"
    )
    file_path: str | None = Field(default=None, description="File where entity is defined")
    description: str | None = Field(default=None, description="AI-generated description")
    properties: dict[str, Any] = Field(default_factory=dict, description="Additional properties")


class Relationship(BaseModel):
    """Knowledge graph edge connecting two entities."""
    source_id: str = Field(description="Source entity ID")
    target_id: str = Field(description="Target entity ID")
    relation_type: Literal[
        "calls",
        "imports",
        "inherits",
        "contains",
        "associated_with",
        "met_with",
        "communicated_with",
        "works_for",
        "member_of",
        "founded",
        "owns",
        "funded",
        "participated_in",
        "located_in",
        "references",
        "related_to",
    ] = Field(
        description="Type of relationship"
    )
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Relationship strength")
    properties: dict[str, Any] = Field(default_factory=dict, description="Additional properties")


class Community(BaseModel):
    """Knowledge graph community/cluster of related entities."""
    community_id: str = Field(description="Unique identifier")
    name: str = Field(description="Community name")
    summary: str = Field(description="AI-generated summary of what this community represents")
    member_ids: list[str] = Field(description="Entity IDs that belong to this community")
    level: int = Field(ge=0, description="Hierarchy level (0 = top level)")


class GraphStats(BaseModel):
    """Statistics about a repository's knowledge graph."""
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    total_entities: int = Field(description="Number of entities in graph")
    total_relationships: int = Field(description="Number of relationships")
    total_communities: int = Field(description="Number of detected communities")
    total_documents: int = Field(default=0, description="Number of Document nodes in Neo4j for this corpus")
    total_chunks: int = Field(default=0, description="Number of Chunk nodes in Neo4j for this corpus")
    entity_breakdown: dict[str, int] = Field(default_factory=dict, description="Count by entity type")
    relationship_breakdown: dict[str, int] = Field(default_factory=dict, description="Count by relation type")


class GraphNeighborsResponse(BaseModel):
    """Neighbor subgraph centered on a single entity."""

    entities: list[Entity] = Field(description="Entities in the neighborhood (includes the center entity)")
    relationships: list[Relationship] = Field(description="Relationships between returned entities")


class EvalDatasetItem(BaseModel):
    """Single evaluation dataset entry (formerly DatasetEntry)."""
    entry_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this entry",
    )
    question: str = Field(description="The test question")
    expected_paths: list[str] = Field(
        description="File paths that should be retrieved (relative or absolute)",
        validation_alias=AliasChoices("expected_paths", "expected_chunks"),
    )
    expected_answer: str | None = Field(default=None, description="Expected answer if testing generation")
    tags: list[str] = Field(default_factory=list, description="Tags for filtering/grouping")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this entry was created",
    )


class EvalRequest(BaseModel):
    """Request payload for evaluation run."""
    repo_id: str = Field(
        description="Corpus identifier to evaluate",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    dataset_id: str | None = Field(default=None, description="Dataset to use (None = default)")
    sample_size: int | None = Field(default=None, ge=1, description="Number of entries to sample (None = all)")


class EvalTestRequest(BaseModel):
    """Request payload for testing a single eval_dataset entry."""

    repo_id: str = Field(
        description="Corpus identifier to evaluate",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    question: str = Field(description="The test question")
    expected_paths: list[str] = Field(
        description="Expected file paths to retrieve",
        validation_alias=AliasChoices("expected_paths", "expected_chunks"),
    )
    use_multi: bool | None = Field(default=None, description="Optional override for multi-query")
    final_k: int | None = Field(default=None, ge=1, le=50, description="Optional override for final-k")


class EvalMetrics(BaseModel):
    """Aggregated retrieval metrics from an evaluation run."""
    mrr: float = Field(ge=0.0, le=1.0, description="Mean Reciprocal Rank")
    recall_at_5: float = Field(ge=0.0, le=1.0, description="Recall at top 5")
    recall_at_10: float = Field(ge=0.0, le=1.0, description="Recall at top 10")
    recall_at_20: float = Field(ge=0.0, le=1.0, description="Recall at top 20")
    precision_at_5: float = Field(ge=0.0, le=1.0, description="Precision at top 5")
    ndcg_at_10: float = Field(ge=0.0, le=1.0, description="NDCG at top 10")
    latency_p50_ms: float = Field(ge=0.0, description="50th percentile latency in ms")
    latency_p95_ms: float = Field(ge=0.0, description="95th percentile latency in ms")


class EvalDoc(BaseModel):
    """Lightweight scored retrieval doc for eval drill-down."""

    file_path: str = Field(description="Retrieved file path")
    start_line: int | None = Field(default=None, description="Optional start line for the retrieved span")
    score: float = Field(description="Retrieval score (post-fusion)")
    source: str | None = Field(default=None, description="Retrieval source (vector/sparse/graph)")


class EvalResult(BaseModel):
    """Per-entry evaluation result."""
    entry_id: str = Field(description="Dataset entry ID")
    question: str = Field(description="The test question")
    retrieved_paths: list[str] = Field(
        description="File paths that were actually retrieved (ranked)",
        validation_alias=AliasChoices("retrieved_paths", "retrieved_chunks"),
    )
    expected_paths: list[str] = Field(
        description="File paths that should have been retrieved",
        validation_alias=AliasChoices("expected_paths", "expected_chunks"),
    )
    top_paths: list[str] = Field(
        default_factory=list,
        description="Top retrieved file paths (ranked, truncated for UI)",
    )
    top1_path: list[str] = Field(default_factory=list, description="Top-1 retrieved file path (0 or 1 items)")
    top1_hit: bool = Field(default=False, description="Whether top-1 contained any expected path")
    topk_hit: bool = Field(default=False, description="Whether top-k contained any expected path")
    reciprocal_rank: float = Field(ge=0.0, le=1.0, description="Reciprocal rank for this entry")
    recall: float = Field(ge=0.0, le=1.0, description="Recall for this entry")
    latency_ms: float = Field(ge=0.0, description="Latency for this query")
    duration_secs: float = Field(default=0.0, ge=0.0, description="Duration for this query (seconds)")
    docs: list[EvalDoc] = Field(default_factory=list, description="Top docs with scores for drill-down")
    debug: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-query retrieval debug (best-effort, for explaining empty results).",
    )


class EvalRun(BaseModel):
    """Complete evaluation run record."""
    run_id: str = Field(description="Unique identifier for this run")
    repo_id: str = Field(
        description="Corpus identifier evaluated",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    dataset_id: str = Field(description="Dataset used")
    config_snapshot: dict[str, Any] = Field(description="Nested config state during evaluation")
    config: dict[str, Any] = Field(default_factory=dict, description="Flat env-style config snapshot (for UI)")
    total: int = Field(default=0, ge=0, description="Total questions evaluated")
    top1_hits: int = Field(default=0, ge=0, description="Count of top-1 hits")
    topk_hits: int = Field(default=0, ge=0, description="Count of top-k hits")
    top1_accuracy: float = Field(default=0.0, ge=0.0, le=1.0, description="Top-1 accuracy")
    topk_accuracy: float = Field(default=0.0, ge=0.0, le=1.0, description="Top-k accuracy")
    duration_secs: float = Field(default=0.0, ge=0.0, description="Total run duration (seconds)")
    use_multi: bool = Field(default=False, description="Whether multi-query was enabled for this run")
    final_k: int = Field(default=0, ge=0, description="Final-k used for this run")
    metrics: EvalMetrics = Field(description="Aggregated metrics")
    results: list[EvalResult] = Field(description="Per-entry results")
    started_at: datetime = Field(description="When evaluation started")
    completed_at: datetime = Field(description="When evaluation completed")
    dataset_version_ref: LineageRef | None = Field(default=None, description="Immutable eval dataset version used for this run.")
    input_bundle_id: str | None = Field(default=None, description="Current bundle id captured before evaluation started.")
    bundle_id: str | None = Field(default=None, description="Bundle id after this run was attached to lineage.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable eval run version reference.")


class EvalRunMeta(BaseModel):
    """Summary metadata for listing eval runs."""

    run_id: str = Field(description="Eval run ID")
    top1_accuracy: float = Field(ge=0.0, le=1.0, description="Top-1 accuracy")
    topk_accuracy: float = Field(ge=0.0, le=1.0, description="Top-k accuracy")
    mrr: float | None = Field(default=None, ge=0.0, le=1.0, description="Mean reciprocal rank")
    total: int = Field(ge=0, description="Total questions evaluated")
    duration_secs: float = Field(ge=0.0, description="Total run duration (seconds)")
    has_config: bool = Field(default=True, description="Whether config snapshot is present")
    bundle_id: str | None = Field(default=None, description="Bundle id associated with this eval run.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable eval run version reference.")


class EvalRunsResponse(BaseModel):
    """Response for listing eval runs."""

    ok: bool = Field(default=True, description="Whether the request succeeded")
    runs: list[EvalRunMeta] = Field(default_factory=list, description="Run summaries (newest first)")


class EvalAnalyzeComparisonRun(BaseModel):
    """Lightweight eval-run summary (used by /eval/analyze_comparison)."""

    run_id: str = Field(description="Eval run ID")
    top1_accuracy: float = Field(default=0.0, ge=0.0, le=1.0, description="Top-1 accuracy")
    topk_accuracy: float = Field(default=0.0, ge=0.0, le=1.0, description="Top-k accuracy")
    total: int = Field(default=0, ge=0, description="Total questions evaluated")
    duration_secs: float = Field(default=0.0, ge=0.0, description="Total run duration (seconds)")


class EvalAnalyzeQuestionItem(BaseModel):
    question: str = Field(description="Evaluation question text")


class EvalAnalyzeComparisonRequest(BaseModel):
    """Request payload for /eval/analyze_comparison."""

    current_run: EvalAnalyzeComparisonRun = Field(description="Current (after) run")
    compare_run: EvalAnalyzeComparisonRun = Field(
        description="Baseline (before) run",
        validation_alias=AliasChoices("compare_run", "baseline_run"),
    )
    config_diffs: list[dict[str, Any]] = Field(default_factory=list, description="Config diffs (best-effort)")
    topk_regressions: list[EvalAnalyzeQuestionItem] = Field(
        default_factory=list,
        description="Top-k regressions (question-level)",
        validation_alias=AliasChoices("topk_regressions", "regressions"),
    )
    topk_improvements: list[EvalAnalyzeQuestionItem] = Field(
        default_factory=list,
        description="Top-k improvements (question-level)",
        validation_alias=AliasChoices("topk_improvements", "improvements"),
    )
    top1_regressions_count: int = Field(default=0, ge=0, description="Top-1 regressions count")
    top1_improvements_count: int = Field(default=0, ge=0, description="Top-1 improvements count")


class EvalAnalyzeComparisonResponse(BaseModel):
    """Response for /eval/analyze_comparison."""

    ok: bool = Field(default=False, description="Whether analysis succeeded")
    analysis: str | None = Field(default=None, description="Markdown analysis")
    model_used: str | None = Field(default=None, description="Model identifier (if any)")
    error: str | None = Field(default=None, description="Error message (if any)")


class EvalComparisonResult(BaseModel):
    """Comparison between two evaluation runs."""
    baseline_run_id: str = Field(description="Baseline run ID")
    current_run_id: str = Field(description="Current run ID being compared")
    baseline_metrics: EvalMetrics = Field(description="Baseline run metrics")
    current_metrics: EvalMetrics = Field(description="Current run metrics")
    delta_mrr: float = Field(description="Change in MRR (positive = improvement)")
    delta_recall_at_10: float = Field(description="Change in recall@10")
    improved_entries: list[str] = Field(default_factory=list, description="Entry IDs that improved")
    degraded_entries: list[str] = Field(default_factory=list, description="Entry IDs that degraded")


# =============================================================================
# DOMAIN MODELS - Training evaluation (reranker training runs)
# =============================================================================

MetricKey = Literal["mrr", "ndcg", "map"]
LabelKind = Literal["pairwise", "binary", "graded", "unknown"]


class CorpusEvalProfile(BaseModel):
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    label_kind: LabelKind = Field(default="unknown", description="Label structure for relevance data")
    avg_relevant_per_query: float = Field(default=0.0, ge=0.0)
    p95_relevant_per_query: float = Field(default=0.0, ge=0.0)
    recommended_metric: MetricKey = Field(description="Auto-selected headline metric for this corpus")
    recommended_k: int = Field(default=10, ge=1, le=200, description="Recommended k for @k metrics")
    rationale: str = Field(default="", description="Short UI-safe explanation for metric choice")


RerankerTrainRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class RerankerTrainStartRequest(BaseModel):
    repo_id: str = Field(
        description="Corpus identifier to train against",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    # Optional overrides (Advanced UI)
    primary_metric: MetricKey | None = Field(default=None, description="Override metric (else use profile)")
    primary_k: int | None = Field(default=None, ge=1, le=200, description="Override k (else use profile)")
    # Training overrides (optional, defaults come from config)
    epochs: int | None = Field(default=None, ge=1, le=50)
    batch_size: int | None = Field(default=None, ge=1, le=256)
    lr: float | None = Field(default=None, gt=0.0)
    warmup_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    max_length: int | None = Field(default=None, ge=32, le=2048)


class RerankerTrainRunSummary(BaseModel):
    # Computed at end; keep lightweight so run listing is cheap.
    primary_metric_best: float | None = Field(default=None, ge=0.0)
    primary_metric_final: float | None = Field(default=None, ge=0.0)
    best_step: int | None = Field(default=None, ge=0)
    time_to_best_secs: float | None = Field(default=None, ge=0.0)
    stability_stddev: float | None = Field(
        default=None,
        ge=0.0,
        description="Late-training stddev of primary metric",
    )


class RerankerTrainRun(BaseModel):
    run_id: str = Field(description="Unique identifier for this training run")
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: RerankerTrainRunStatus = Field(default="queued")
    started_at: datetime = Field(description="UTC start time")
    completed_at: datetime | None = Field(default=None, description="UTC completion time")

    # Snapshots for reproducibility
    config_snapshot: dict[str, Any] = Field(description="Nested TriBridConfig snapshot (mode='json')")
    config: dict[str, Any] = Field(default_factory=dict, description="Flat env-style config snapshot")

    # Stable “North Star”
    primary_metric: MetricKey = Field(description="Run-locked headline metric")
    primary_k: int = Field(ge=1, le=200, description="Run-locked k for @k metrics")
    metrics_available: list[str] = Field(default_factory=list, description="e.g. ['mrr@10','ndcg@10','map']")

    # Store the *profile snapshot used at start* so rationale never changes later
    metric_profile: CorpusEvalProfile = Field(description="Profile snapshot used to choose primary_metric/primary_k")

    # Hyperparameters captured (resolved defaults + overrides)
    epochs: int = Field(ge=1, le=50)
    batch_size: int = Field(ge=1, le=256)
    lr: float = Field(gt=0.0)
    warmup_ratio: float = Field(ge=0.0, le=1.0)
    max_length: int = Field(ge=32, le=2048)

    summary: RerankerTrainRunSummary = Field(default_factory=RerankerTrainRunSummary)
    input_bundle_id: str | None = Field(default=None, description="Current bundle id captured before training started.")
    bundle_id: str | None = Field(default=None, description="Bundle id after this run was attached to lineage.")
    promoted_bundle_id: str | None = Field(default=None, description="Bundle id created when this run was promoted.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable reranker training run version reference.")
    model_artifact_ref: LineageRef | None = Field(
        default=None,
        description="Immutable reranker model artifact version produced by this run.",
    )


class RerankerTrainRunMeta(BaseModel):
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: RerankerTrainRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    primary_metric: MetricKey
    primary_k: int
    primary_metric_best: float | None = None
    primary_metric_final: float | None = None
    bundle_id: str | None = None
    lineage_ref: LineageRef | None = None


class RerankerTrainRunsResponse(BaseModel):
    ok: bool = Field(default=True)
    runs: list[RerankerTrainRunMeta] = Field(default_factory=list)


# --- Metrics event stream schema (stored in metrics.jsonl and used by SSE/UI) ---

RerankerTrainEventType = Literal["log", "progress", "metrics", "state", "error", "complete", "telemetry"]


class RerankerTrainMetricEvent(BaseModel):
    type: RerankerTrainEventType
    ts: datetime = Field(description="UTC timestamp")
    run_id: str
    step: int | None = Field(default=None, ge=0)
    epoch: float | None = Field(default=None, ge=0.0)

    message: str | None = None  # for log/error
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")
    percent: float | None = Field(default=None, ge=0.0, le=100.0)  # for progress
    metrics: dict[str, float] | None = None  # for metrics: {'mrr@10':0.33,'ndcg@10':0.41,'map':0.22}
    status: RerankerTrainRunStatus | None = None  # for state/complete
    proj_x: float | None = None
    proj_y: float | None = None
    loss: float | None = None
    lr: float | None = None
    grad_norm: float | None = None
    step_time_ms: float | None = None
    sample_count: int | None = Field(default=None, ge=0)


RerankerDiagnosticLevel = Literal["debug", "info", "warning", "error"]


class RerankerTrainDiagnosticRecord(BaseModel):
    ts: datetime = Field(description="UTC timestamp")
    run_id: str = Field(description="Training run identifier")
    level: RerankerDiagnosticLevel = Field(description="Structured diagnostic level")
    event: str = Field(description="Stable low-cardinality diagnostic event name")
    message: str = Field(description="Human-readable summary")
    operator_hint: str | None = Field(default=None, description="High-signal implementation hint for the next debugger.")
    fields: dict[str, Any] = Field(default_factory=dict, description="Additional low-cardinality diagnostic fields")


class RerankerTrainDiagnosticsResponse(BaseModel):
    ok: bool = Field(default=True)
    records: list[RerankerTrainDiagnosticRecord] = Field(default_factory=list)


class RerankerTrainStartResponse(BaseModel):
    ok: bool = Field(default=True)
    run_id: str
    run: RerankerTrainRun


class RerankerTrainMetricsResponse(BaseModel):
    ok: bool = Field(default=True)
    events: list[RerankerTrainMetricEvent] = Field(default_factory=list)


class RerankerTrainDiffRequest(BaseModel):
    baseline_run_id: str
    current_run_id: str


class RerankerTrainDiffResponse(BaseModel):
    ok: bool = Field(default=True)
    compatible: bool = Field(default=True, description="False if primary metric/k differ")
    reason: str | None = None

    primary_metric: MetricKey | None = None
    primary_k: int | None = None

    baseline_primary_best: float | None = None
    current_primary_best: float | None = None
    delta_primary_best: float | None = None

    baseline_time_to_best_secs: float | None = None
    current_time_to_best_secs: float | None = None
    delta_time_to_best_secs: float | None = None

    baseline_stability_stddev: float | None = None
    current_stability_stddev: float | None = None
    delta_stability_stddev: float | None = None


# =============================================================================
# DOMAIN MODELS - Agent training (ragweld agent runs)
# =============================================================================

AgentTrainRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class AgentTrainStartRequest(BaseModel):
    repo_id: str = Field(
        description="Corpus identifier to train against",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )

    # Optional overrides (use config defaults when omitted)
    epochs: int | None = Field(default=None, ge=1, le=50)
    batch_size: int | None = Field(default=None, ge=1, le=256)
    lr: float | None = Field(default=None, gt=0.0)
    warmup_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    max_length: int | None = Field(default=None, ge=32, le=8192)

    dataset_path: str | None = Field(
        default=None,
        description=(
            "Optional dataset path override. If empty/omitted, uses training.ragweld_agent_train_dataset_path; "
            "then evaluation.eval_dataset_path; then corpus eval dataset under data/eval_datasets/<corpus>.json."
        ),
    )


class AgentTrainRunSummary(BaseModel):
    primary_metric_best: float | None = Field(default=None, ge=0.0)
    primary_metric_final: float | None = Field(default=None, ge=0.0)
    best_step: int | None = Field(default=None, ge=0)
    time_to_best_secs: float | None = Field(default=None, ge=0.0)
    stability_stddev: float | None = Field(default=None, ge=0.0)
    primary_goal: Literal["minimize", "maximize"] = Field(
        default="minimize",
        description="Whether lower/higher values of primary_metric are better.",
    )


class AgentTrainRun(BaseModel):
    run_id: str = Field(description="Unique identifier for this agent training run")
    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: AgentTrainRunStatus = Field(default="queued")
    started_at: datetime = Field(description="UTC start time")
    completed_at: datetime | None = Field(default=None, description="UTC completion time")

    # Snapshots for reproducibility
    config_snapshot: dict[str, Any] = Field(description="Nested TriBridConfig snapshot (mode='json')")
    config: dict[str, Any] = Field(default_factory=dict, description="Flat env-style config snapshot")

    primary_metric: str = Field(default="eval_loss", description="Primary metric name (default eval_loss)")
    primary_goal: Literal["minimize", "maximize"] = Field(default="minimize", description="Goal direction for primary_metric")
    metrics_available: list[str] = Field(default_factory=list, description="e.g. ['train_loss','eval_loss']")

    # Hyperparameters captured (resolved defaults + overrides)
    epochs: int = Field(ge=1, le=50)
    batch_size: int = Field(ge=1, le=256)
    lr: float = Field(gt=0.0)
    warmup_ratio: float = Field(ge=0.0, le=1.0)
    max_length: int = Field(ge=32, le=8192)
    workflow_backend: str = Field(
        default="local",
        description="Workflow state backend used for this run (for example local or flyte).",
    )
    tracking_backend: str = Field(
        default="local",
        description="Run/artifact truth backend used for this run (for example local or mlflow).",
    )
    execution_backend: str = Field(
        default="mlx_qwen3",
        description="Execution backend used for this run (for example mlx_qwen3 or unsloth).",
    )
    workflow_run_id: str | None = Field(
        default=None,
        description="External workflow execution identifier when orchestration is delegated.",
    )
    tracking_run_id: str | None = Field(
        default=None,
        description="External run identifier in the tracking system when available.",
    )
    artifacts_uri: str | None = Field(
        default=None,
        description="Artifact URI or storage path for the run outputs when available.",
    )
    external_links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Direct operator links for workflow, tracking, or artifact surfaces.",
    )
    operator_hint: str | None = Field(
        default=None,
        description="High-signal next-step guidance for operators inspecting this run.",
    )

    summary: AgentTrainRunSummary = Field(default_factory=AgentTrainRunSummary)
    input_bundle_id: str | None = Field(default=None, description="Current bundle id captured before training started.")
    bundle_id: str | None = Field(default=None, description="Bundle id after this run was attached to lineage.")
    promoted_bundle_id: str | None = Field(default=None, description="Bundle id created when this run was promoted.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable agent training run version reference.")
    model_artifact_ref: LineageRef | None = Field(
        default=None,
        description="Immutable agent model artifact version produced by this run.",
    )


class AgentTrainRunMeta(BaseModel):
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: AgentTrainRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    primary_metric_best: float | None = None
    primary_metric_final: float | None = None
    workflow_backend: str = "local"
    tracking_backend: str = "local"
    execution_backend: str = "mlx_qwen3"
    workflow_run_id: str | None = None
    tracking_run_id: str | None = None
    bundle_id: str | None = None
    lineage_ref: LineageRef | None = None


class AgentTrainRunsResponse(BaseModel):
    ok: bool = Field(default=True)
    runs: list[AgentTrainRunMeta] = Field(default_factory=list)


AgentTrainEventType = Literal["log", "progress", "metrics", "state", "error", "complete", "telemetry"]


class AgentTrainMetricEvent(BaseModel):
    type: AgentTrainEventType
    ts: datetime = Field(description="UTC timestamp")
    run_id: str
    step: int | None = Field(default=None, ge=0)
    epoch: float | None = Field(default=None, ge=0.0)

    message: str | None = None
    percent: float | None = Field(default=None, ge=0.0, le=100.0)
    metrics: dict[str, float] | None = None
    status: AgentTrainRunStatus | None = None

    proj_x: float | None = None
    proj_y: float | None = None
    loss: float | None = None
    lr: float | None = None
    grad_norm: float | None = None
    param_norm: float | None = None
    update_norm: float | None = None
    step_time_ms: float | None = None
    sample_count: int | None = Field(default=None, ge=0)


class AgentTrainStartResponse(BaseModel):
    ok: bool = Field(default=True)
    run_id: str


class AgentTrainMetricsResponse(BaseModel):
    ok: bool = Field(default=True)
    events: list[AgentTrainMetricEvent] = Field(default_factory=list)


TrainingControlPlaneComponentKind = Literal["flyte", "mlflow", "unsloth"]
TrainingControlPlaneComponentState = Literal["disabled", "unconfigured", "ready", "degraded"]


class TrainingControlPlaneComponentStatus(BaseModel):
    kind: TrainingControlPlaneComponentKind = Field(description="Control-plane component kind.")
    label: str = Field(description="Human-readable component label.")
    enabled: bool = Field(default=False, description="Whether this component is intended for the active target lane.")
    configured: bool = Field(default=False, description="Whether required config values are present.")
    state: TrainingControlPlaneComponentState = Field(
        default="disabled",
        description="Operator-facing component state.",
    )
    detail: str | None = Field(default=None, description="Short status note for operators.")
    links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Relevant control-plane links for this component.",
    )


class AgentTrainControlPlaneStatusResponse(BaseModel):
    ok: bool = Field(default=True)
    lane: Literal["legacy_local", "flyte_mlflow_unsloth"] = Field(
        default="legacy_local",
        description="Resolved target lane for the Learning Agent Training Center surface.",
    )
    ready: bool = Field(
        default=False,
        description="Whether the Flyte + MLflow + Unsloth control plane is fully configured and reachable.",
    )
    workflow_backend: str = Field(default="local", description="Configured workflow backend target.")
    tracking_backend: str = Field(default="local", description="Configured tracking backend target.")
    execution_backend: str = Field(default="mlx_qwen3", description="Configured execution backend target.")
    components: list[TrainingControlPlaneComponentStatus] = Field(
        default_factory=list,
        description="Per-component readiness details for the target control plane.",
    )
    links: list[TraceExternalLink] = Field(
        default_factory=list,
        description="Top-level Learning Agent control-plane links.",
    )
    operator_hint: str | None = Field(default=None, description="High-signal next-step guidance for operators.")


class AgentTrainDiffRequest(BaseModel):
    baseline_run_id: str
    current_run_id: str


class AgentTrainDiffResponse(BaseModel):
    ok: bool = Field(default=True)
    compatible: bool = Field(default=True)
    reason: str | None = None

    primary_metric: str | None = None
    primary_goal: Literal["minimize", "maximize"] | None = None

    baseline_primary_best: float | None = None
    current_primary_best: float | None = None
    delta_primary_best: float | None = None

    baseline_time_to_best_secs: float | None = None
    current_time_to_best_secs: float | None = None
    delta_time_to_best_secs: float | None = None

    baseline_stability_stddev: float | None = None
    current_stability_stddev: float | None = None
    delta_stability_stddev: float | None = None

    improved: bool | None = Field(
        default=None,
        description="Whether the current run improved vs baseline (respects primary_goal).",
    )


# =============================================================================
# DOMAIN MODELS - Synthetic run orchestration
# =============================================================================

SyntheticProvider = Literal["synthetic_data_kit"]

SyntheticRunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

SyntheticArtifactKind = Literal[
    "eval_dataset_json",
    "semantic_cards_jsonl",
    "keywords_json",
    "triplets_jsonl",
    "config_patch_json",
    "quality_eval_json",
    "report_md",
]

SyntheticRecipeKind = Literal[
    "eval_dataset",
    "semantic_cards",
    "keywords",
    "triplets",
    "autotune_retrieval",
    "full_stack",
]


class SyntheticRunStartRequest(BaseModel):
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    provider: SyntheticProvider = Field(default="synthetic_data_kit")
    recipe: SyntheticRecipeKind = Field(default="eval_dataset")

    max_source_chunks: int | None = Field(default=300, ge=10, le=20000)
    max_pairs: int | None = Field(default=200, ge=10, le=50000)
    pairs_per_source: int | None = Field(default=2, ge=1, le=20)

    curate_enabled: bool = Field(default=True)
    curate_threshold: float = Field(default=7.0, ge=0.0, le=10.0)
    include_expected_answer: bool = Field(default=True)
    include_tags: bool = Field(default=True)

    seed: int | None = Field(default=1337)
    generator_model: str = Field(
        validation_alias=AliasChoices("generator_model", "generator_model_override"),
        serialization_alias="generator_model",
        min_length=1,
    )
    judge_model: str = Field(
        validation_alias=AliasChoices("judge_model", "judge_model_override"),
        serialization_alias="judge_model",
        min_length=1,
    )

    @field_validator("generator_model", "judge_model")
    @classmethod
    def _validate_non_blank_models(cls, value: str) -> str:
        model_name = str(value or "").strip()
        if not model_name:
            raise ValueError("must not be empty")
        return model_name

    @field_validator("repo_id")
    @classmethod
    def _validate_repo_id_slug(cls, value: str) -> str:
        repo_id = str(value or "").strip()
        if not repo_id:
            raise ValueError("must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", repo_id):
            raise ValueError("must contain only letters, numbers, dot, underscore, and hyphen")
        if repo_id in {".", ".."} or ".." in repo_id:
            raise ValueError("must not contain path traversal segments")
        return repo_id


class SyntheticArtifactRef(BaseModel):
    kind: SyntheticArtifactKind
    path: str
    bytes: int | None = Field(default=None, ge=0)
    created_at: datetime


class SyntheticRunSummary(BaseModel):
    sources_used: int = Field(default=0, ge=0)
    items_generated: int = Field(default=0, ge=0)
    items_curated_in: int = Field(default=0, ge=0)
    items_curated_out: int = Field(default=0, ge=0)
    avg_judge_score: float | None = Field(default=None, ge=0.0, le=10.0)
    quality_top1_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_topk_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_mrr: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_sample_size: int | None = Field(default=None, ge=0)
    quality_gate_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_gate_passed: bool | None = Field(default=None)
    quality_failure_reason: str | None = Field(default=None)

    degradation: SyntheticRunDegradation = Field(
        default_factory=SyntheticRunDegradation,
        description="Degradation flags -- honest about what actually happened during the run",
    )


class SyntheticRun(BaseModel):
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: SyntheticRunStatus = Field(default="queued")
    started_at: datetime
    completed_at: datetime | None = Field(default=None)

    provider: SyntheticProvider
    recipe: SyntheticRecipeKind

    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)

    request: SyntheticRunStartRequest
    artifacts: list[SyntheticArtifactRef] = Field(default_factory=list)
    summary: SyntheticRunSummary = Field(default_factory=SyntheticRunSummary)
    error: str | None = Field(default=None)
    input_bundle_id: str | None = Field(default=None, description="Current bundle id captured before the run started.")
    bundle_id: str | None = Field(default=None, description="Bundle id after this run was attached to lineage.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable synthetic run version reference.")
    artifact_lineage_refs: dict[str, LineageRef] = Field(
        default_factory=dict,
        description="Synthetic artifact kind -> immutable version reference.",
    )


class SyntheticRunMeta(BaseModel):
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    status: SyntheticRunStatus
    started_at: datetime
    completed_at: datetime | None = Field(default=None)
    recipe: SyntheticRecipeKind
    provider: SyntheticProvider
    items_generated: int | None = Field(default=None)
    bundle_id: str | None = Field(default=None)
    lineage_ref: LineageRef | None = Field(default=None)


class SyntheticRunsResponse(BaseModel):
    ok: bool = Field(default=True)
    runs: list[SyntheticRunMeta] = Field(default_factory=list)


SyntheticEventType = Literal["log", "progress", "state", "error", "complete", "artifact"]


class SyntheticRunEvent(BaseModel):
    type: SyntheticEventType
    ts: datetime
    run_id: str
    message: str | None = Field(default=None)
    percent: float | None = Field(default=None, ge=0.0, le=100.0)
    status: SyntheticRunStatus | None = Field(default=None)
    artifact: SyntheticArtifactRef | None = Field(default=None)


class SyntheticPublishResponse(BaseModel):
    ok: bool = Field(default=True)
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    kind: SyntheticArtifactKind
    target_path: str | None = Field(default=None)
    message: str | None = Field(default=None)
    bundle_id: str | None = Field(default=None, description="Bundle id after attaching the published artifact.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable published artifact version reference.")


class SyntheticConfigPatchResponse(BaseModel):
    ok: bool = Field(default=True)
    run_id: str
    repo_id: str = Field(
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    patch: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str | None = Field(default=None)
    bundle_id: str | None = Field(default=None, description="Bundle id after attaching the config patch artifact.")
    lineage_ref: LineageRef | None = Field(default=None, description="Immutable published artifact version reference.")


class SyntheticArtifactPreviewResponse(BaseModel):
    ok: bool = Field(default=True)
    run_id: str
    kind: SyntheticArtifactKind
    rows: list[dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# CONFIGURATION MODELS - Tunable parameters for the tribrid RAG system
# =============================================================================


class RetrievalConfig(BaseModel):
    """Configuration for retrieval and search parameters."""

    rrf_k_div: int = Field(
        default=60,
        ge=1,
        le=200,
        description="RRF rank smoothing constant (higher = more weight to top ranks)"
    )

    langgraph_final_k: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Number of final results to return in LangGraph pipeline"
    )

    max_query_rewrites: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum number of query rewrites for multi-query expansion"
    )

    langgraph_max_query_rewrites: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum number of query rewrites for LangGraph pipeline"
    )

    fallback_confidence: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for fallback retrieval strategies"
    )

    final_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Default top-k for search results"
    )

    eval_final_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Top-k for evaluation runs"
    )

    conf_top1: float = Field(
        default=0.62,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for top-1"
    )

    conf_avg5: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Confidence threshold for avg top-5"
    )

    conf_any: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold"
    )

    eval_multi: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable multi-query in eval"
    )

    query_expansion_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable synonym expansion"
    )

    bm25_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for BM25 in hybrid search"
    )

    bm25_k1: float = Field(
        default=1.2,
        ge=0.5,
        le=3.0,
        description="BM25 term frequency saturation parameter (higher = more weight to term frequency)"
    )

    bm25_b: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="BM25 length normalization (0=no penalty, 1=full penalty, 0.3-0.5 recommended for code)"
    )

    vector_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight for vector search"
    )

    chunk_summary_search_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable chunk_summary-based retrieval"
    )

    max_chunks_per_file: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Max chunks to return per file_path (document-aware result shaping).",
    )
    dedup_by: Literal["chunk_id", "file_path"] = Field(
        default="chunk_id",
        description="Dedup key for final results.",
    )
    neighbor_window: int = Field(
        default=1,
        ge=0,
        le=10,
        description="Include adjacent chunks by ordinal for coherence (requires chunk_ordinal metadata).",
    )
    min_score_vector: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum score threshold for vector leg results (0 disables).",
    )
    min_score_sparse: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Minimum score threshold for sparse leg results (0 disables). Note: sparse scores are engine-dependent (FTS vs BM25).",
    )
    min_score_graph: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Minimum score threshold for graph leg results (0 disables).",
    )
    enable_mmr: bool = Field(
        default=False,
        description="Enable MMR diversification when embeddings are available.",
    )
    mmr_lambda: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="MMR lambda (1=query relevance only, 0=diversity only).",
    )

    multi_query_m: int = Field(
        default=4,
        ge=1,
        le=10,
        description="Query variants for multi-query"
    )

    use_semantic_synonyms: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable semantic synonym expansion"
    )

    tribrid_synonyms_path: str = Field(
        default="",
        description="Custom path to semantic_synonyms.json (default: data/semantic_synonyms.json)"
    )

    topk_dense: int = Field(
        default=75,
        ge=10,
        le=200,
        description="Top-K for dense vector search"
    )

    topk_sparse: int = Field(
        default=75,
        ge=10,
        le=200,
        description="Top-K for sparse BM25 search"
    )

    hydration_mode: str = Field(
        default="lazy",
        pattern="^(lazy|eager|none|off)$",
        description="Result hydration mode"
    )

    hydration_max_chars: int = Field(
        default=2000,
        ge=500,
        le=10000,
        description="Max characters for result hydration"
    )

    # REMOVED: disable_rerank - use RERANKER_MODE='none' instead

    @field_validator('rrf_k_div')
    @classmethod
    def validate_rrf_k_div(cls, v: int) -> int:
        """Ensure RRF k_div is reasonable."""
        if v < 10:
            raise ValueError('rrf_k_div should be at least 10 for meaningful rank smoothing')
        return v

    @field_validator('hydration_mode', mode='before')
    @classmethod
    def normalize_hydration(cls, v: str) -> str:
        """Normalize hydration aliases to canonical values."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val == 'off':
                return 'none'
            return val
        return v

    @model_validator(mode='after')
    def validate_weights_sum_to_one(self) -> Self:
        """Normalize BM25/vector weights to sum to 1.0 instead of hard failing."""
        total = self.bm25_weight + self.vector_weight
        if total <= 0:
            # Reset to safe defaults
            self.bm25_weight = 0.3
            self.vector_weight = 0.7
            return self
        if not (0.99 <= total <= 1.01):
            norm_bm25 = self.bm25_weight / total
            norm_vector = self.vector_weight / total
            # Clamp to [0,1] after normalization
            self.bm25_weight = max(0.0, min(1.0, norm_bm25))
            self.vector_weight = max(0.0, min(1.0, norm_vector))
        return self


class SemanticCacheConfig(BaseModel):
    """Configuration for semantic caching across search/answer/chat endpoints."""

    enabled: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Enable semantic cache reads/writes (0=off, 1=on).",
    )
    mode: Literal["read_write", "read_only", "write_only"] = Field(
        default="read_write",
        description="Cache mode when enabled.",
    )
    max_entries: int = Field(
        default=5000,
        ge=100,
        le=500000,
        description="Maximum cache rows to retain per scope/endpoint.",
    )
    min_query_chars: int = Field(
        default=3,
        ge=1,
        le=200,
        description="Minimum query length before cache is eligible.",
    )
    similarity_threshold_search: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for semantic search cache hits.",
    )
    similarity_threshold_answer: float = Field(
        default=0.93,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for semantic answer cache hits.",
    )
    similarity_threshold_chat: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity for semantic chat cache hits.",
    )
    ttl_seconds_search: int = Field(
        default=900,
        ge=10,
        le=86_400,
        description="TTL in seconds for search cache entries.",
    )
    ttl_seconds_answer: int = Field(
        default=1800,
        ge=10,
        le=86_400,
        description="TTL in seconds for answer cache entries.",
    )
    ttl_seconds_chat: int = Field(
        default=600,
        ge=10,
        le=86_400,
        description="TTL in seconds for chat cache entries.",
    )
    chat_history_window: int = Field(
        default=6,
        ge=0,
        le=50,
        description="Number of prior conversation turns included in chat cache fingerprint.",
    )
    bypass_if_images: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Bypass chat generation cache when images are attached.",
    )
    max_temperature_for_write: float = Field(
        default=0.5,
        ge=0.0,
        le=2.0,
        description="Skip generation-cache writes when temperature exceeds this value.",
    )


class ScoringConfig(BaseModel):
    """Configuration for result scoring and boosting."""

    chunk_summary_bonus: float = Field(
        default=0.08,
        ge=0.0,
        le=1.0,
        description="Bonus score for chunks matched via chunk_summary-based retrieval"
    )

    filename_boost_exact: float = Field(
        default=1.5,
        ge=1.0,
        le=5.0,
        description="Score multiplier when filename exactly matches query terms"
    )

    filename_boost_partial: float = Field(
        default=1.2,
        ge=1.0,
        le=3.0,
        description="Score multiplier when path components match query terms"
    )

    vendor_mode: str = Field(
        default="prefer_first_party",
        pattern="^(prefer_first_party|prefer_vendor|neutral)$",
        description="Vendor code preference"
    )

    path_boosts: str = Field(
        default="/gui,/server,/indexer,/retrieval",
        description="Comma-separated path prefixes to boost"
    )

    @model_validator(mode='after')
    def validate_exact_boost_greater_than_partial(self) -> Self:
        """Ensure exact boost is greater than partial boost."""
        if self.filename_boost_exact <= self.filename_boost_partial:
            raise ValueError('filename_boost_exact should be greater than filename_boost_partial')
        return self


class LayerBonusConfig(BaseModel):
    """Layer-specific scoring bonuses with intent-aware matrix.

    The base bonuses are additive percentages (e.g., 0.15 = +15%).
    They are converted downstream to multiplicative factors.
    """

    gui: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description="Bonus for GUI/front-end layers"
    )

    retrieval: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description="Bonus for retrieval/API layers"
    )

    indexer: float = Field(
        default=0.15,
        ge=0.0,
        le=0.5,
        description="Bonus for indexing/ingestion layers"
    )

    vendor_penalty: float = Field(
        default=-0.1,
        ge=-0.5,
        le=0.0,
        description="Penalty for vendor/third-party code (negative values apply a penalty)"
    )

    freshness_bonus: float = Field(
        default=0.05,
        ge=0.0,
        le=0.3,
        description="Bonus for recently modified files"
    )

    intent_matrix: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "gui": {"gui": 1.2, "web": 1.2, "server": 0.9, "retrieval": 0.8, "indexer": 0.8},
            "retrieval": {"retrieval": 1.3, "server": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6},
            "indexer": {"indexer": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6},
            "eval": {"eval": 1.3, "retrieval": 1.15, "server": 1.1, "web": 0.8, "gui": 0.7},
            "infra": {"infra": 1.3, "scripts": 1.15, "server": 1.1, "web": 0.9},
            "server": {"server": 1.3, "retrieval": 1.15, "common": 1.1, "web": 0.7, "gui": 0.6},
        },
        description="Intent-to-layer bonus matrix. Keys are query intents, values are layer->multiplier maps."
    )


class EmbeddingConfig(BaseModel):
    """Embedding generation and caching configuration."""

    embedding_backend: Literal["deterministic", "provider"] = Field(
        default="deterministic",
        description="Embedding execution backend. 'deterministic' is offline/test-friendly; 'provider' calls real providers.",
    )
    embedding_type: str = Field(
        default="openai",
        description="Embedding provider (dynamic - validated against models.json at runtime)"
    )
    embedding_model: str = Field(
        default="text-embedding-3-large",
        description="OpenAI embedding model"
    )
    embedding_dim: int = Field(
        default=3072,
        ge=128,
        le=4096,
        description="Embedding dimensions"
    )
    auto_set_dimensions: bool = Field(
        default=True,
        description="When true, the UI auto-syncs embedding_dim from data/models.json when model changes.",
    )
    input_truncation: Literal["error", "truncate_end", "truncate_middle"] = Field(
        default="truncate_end",
        description="What to do when text exceeds embedding/token limits.",
    )
    embed_text_prefix: str = Field(
        default="",
        description="Prefix added before chunk text prior to embedding (stable document context).",
    )
    embed_text_suffix: str = Field(
        default="",
        description="Suffix added after chunk text prior to embedding.",
    )
    contextual_chunk_embeddings: Literal["off", "prepend_context", "late_chunking_local_only"] = Field(
        default="off",
        description="Contextual chunk embedding mode. 'late_chunking_local_only' requires local/HF provider backend.",
    )
    late_chunking_max_doc_tokens: int = Field(
        default=8192,
        ge=256,
        le=65536,
        description="Max tokens per document segment for local late chunking.",
    )

    @field_validator('embedding_type', mode='before')
    @classmethod
    def normalize_embedding_type(cls, v: str) -> str:
        """Normalize embedding provider aliases."""
        if isinstance(v, str):
            val = v.strip().lower()
            # Map common aliases
            if val in {'mlx', 'mlx-embeddings', 'metal', 'metal_gpu', 'apple_mlx'}:
                return 'mlx'
            if val in {'hf', 'hugging_face', 'hugging-face'}:
                return 'huggingface'
            if val in {'sentence_transformers', 'sentence-transformers', 'st'}:
                return 'local'
            if val in {'mxbai', 'mixedbread'}:
                return 'local'  # mxbai models run under local provider
            return val
        return v

    voyage_model: str = Field(
        default="voyage-code-3",
        description="Voyage embedding model"
    )
    embedding_model_local: str = Field(
        default="all-MiniLM-L6-v2",
        description="Local SentenceTransformer model"
    )
    embedding_model_mlx: str = Field(
        default="mlx-community/all-MiniLM-L6-v2-4bit",
        description="MLX-optimized embedding model (used when embedding_type=mlx)"
    )
    embedding_batch_size: int = Field(
        default=64,
        ge=1,
        le=256,
        description="Batch size for embedding generation"
    )
    embedding_max_tokens: int = Field(
        default=8000,
        ge=512,
        le=8192,
        description="Max tokens per embedding chunk"
    )
    embedding_cache_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable embedding cache"
    )
    embedding_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Embedding API timeout (seconds)"
    )
    embedding_retry_max: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Max retries for embedding API"
    )

    @property
    def effective_model(self) -> str:
        """Return the configured embedding model name actually in use for this provider."""
        t = (self.embedding_type or "").strip().lower()
        if t == "voyage":
            return self.voyage_model
        if t == "mlx":
            return self.embedding_model_mlx
        if t in {"local", "huggingface", "ollama"}:
            return self.embedding_model_local
        return self.embedding_model

    @field_validator('embedding_dim')
    @classmethod
    def validate_dim_matches_model(cls, v: int) -> int:
        """Ensure dimensions match typical model output."""
        common_dims = [128, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096]
        if v not in common_dims:
            raise ValueError(f'Uncommon embedding dimension: {v}. Expected one of {common_dims}')
        return v

    @model_validator(mode="after")
    def _validate_contextual_embedding_mode(self) -> Self:
        mode = str(self.contextual_chunk_embeddings or "off").strip().lower()
        if mode == "late_chunking_local_only":
            t = str(self.embedding_type or "").strip().lower()
            if t not in {"local", "huggingface"}:
                raise ValueError(
                    "contextual_chunk_embeddings='late_chunking_local_only' requires embedding_type=local|huggingface"
                )
            if str(self.embedding_backend or "").strip().lower() != "provider":
                raise ValueError(
                    "contextual_chunk_embeddings='late_chunking_local_only' requires embedding_backend='provider'"
                )
        return self


class TokenizationConfig(BaseModel):
    """Tokenizer configuration used for token-aware chunking and budgeting."""

    strategy: Literal["whitespace", "tiktoken", "huggingface"] = Field(
        default="tiktoken",
        description="Tokenization strategy used for chunking/budgeting.",
    )
    tiktoken_encoding: str = Field(
        default="o200k_base",
        description="tiktoken encoding name (strategy='tiktoken').",
    )
    hf_tokenizer_name: str = Field(
        default="gpt2",
        description="HuggingFace tokenizer name (strategy='huggingface').",
    )
    normalize_unicode: bool = Field(
        default=True,
        description="Normalize unicode (NFKC) before tokenization for stability.",
    )
    lowercase: bool = Field(
        default=False,
        description="Lowercase before tokenization.",
    )
    max_tokens_per_chunk_hard: int = Field(
        default=8192,
        ge=256,
        le=65536,
        description="Absolute hard limit for tokens per chunk (safety ceiling).",
    )
    estimate_only: bool = Field(
        default=False,
        description="If true, use fast approximate token counting.",
    )


class ChunkingConfig(BaseModel):
    """Chunking configuration for documents and code."""

    chunk_size: int = Field(
        default=1000,
        ge=200,
        le=5000,
        description="Target chunk size (non-whitespace chars)"
    )
    chunk_overlap: int = Field(
        default=200,
        ge=0,
        le=1000,
        description="Overlap between chunks"
    )
    ast_overlap_lines: int = Field(
        default=20,
        ge=0,
        le=100,
        description="Overlap lines for AST chunking"
    )
    max_indexable_file_size: int = Field(
        default=250_000_000,
        ge=10000,
        le=2_000_000_000,
        description="Max file size to index (bytes) - files larger than this are skipped"
    )
    max_chunk_tokens: int = Field(
        default=8000,
        ge=100,
        le=32000,
        description="Maximum tokens per chunk - chunks exceeding this are split recursively"
    )
    min_chunk_chars: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Minimum chunk size"
    )
    greedy_fallback_target: int = Field(
        default=800,
        ge=200,
        le=2000,
        description="Target size for greedy chunking"
    )
    chunking_strategy: str = Field(
        default="ast",
        pattern="^(ast|hybrid|greedy|fixed_chars|fixed_tokens|recursive|markdown|sentence|qa_blocks)$",
        description="Chunking strategy (document + code)"
    )
    preserve_imports: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Include imports in chunks"
    )
    target_tokens: int = Field(
        default=512,
        ge=64,
        le=8192,
        description="Target tokens per chunk (token-based strategies)",
    )
    overlap_tokens: int = Field(
        default=64,
        ge=0,
        le=2048,
        description="Token overlap between chunks (token-based strategies)",
    )
    separators: list[str] = Field(
        default_factory=lambda: ["\n\n", "\n", ". ", " ", ""],
        description="Separators for recursive chunking, in priority order.",
    )
    separator_keep: Literal["none", "prefix", "suffix"] = Field(
        default="suffix",
        description="Whether to keep separators when splitting (recursive strategy).",
    )
    recursive_max_depth: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Max recursion depth for recursive chunking.",
    )
    markdown_max_heading_level: int = Field(
        default=4,
        ge=1,
        le=6,
        description="Max heading level to split on for markdown chunking.",
    )
    markdown_include_code_fences: bool = Field(
        default=True,
        description="Whether to include fenced code blocks in markdown sections.",
    )
    emit_chunk_ordinal: bool = Field(
        default=True,
        description="Emit chunk ordinal metadata for neighbor-window retrieval.",
    )
    emit_parent_doc_id: bool = Field(
        default=True,
        description="Emit parent document id metadata for neighbor-window retrieval.",
    )

    @field_validator("chunking_strategy", mode="before")
    @classmethod
    def normalize_chunking_strategy(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().lower()
            if val == "semantic":
                raise ValueError(
                    "chunking_strategy='semantic' is no longer supported; use fixed_chars, fixed_tokens, recursive, markdown, sentence, qa_blocks, ast, or hybrid."
                )
            return val
        return v

    @model_validator(mode='after')
    def validate_overlap_less_than_size(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('chunk_overlap must be less than chunk_size')
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be less than target_tokens")
        return self


class IndexingConfig(BaseModel):
    """Indexing and vector storage configuration."""

    postgres_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/tribrid_rag",
        description="PostgreSQL connection string (DSN) for pgvector + FTS storage"
    )
    indexing_batch_size: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Batch size for indexing"
    )
    indexing_workers: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Parallel workers for indexing"
    )
    bm25_tokenizer: str = Field(
        default="stemmer",
        pattern="^(stemmer|lowercase|whitespace)$",
        description="BM25 tokenizer type"
    )
    bm25_stemmer_lang: str = Field(
        default="english",
        description="Stemmer language"
    )
    index_excluded_exts: str = Field(
        default=".png,.jpg,.gif,.ico,.svg,.woff,.ttf",
        description="Excluded file extensions (comma-separated)"
    )
    index_max_file_size_mb: int = Field(
        default=250,
        ge=1,
        le=1024,
        description="Max file size to index (MB)"
    )
    large_file_mode: Literal["read_all", "stream"] = Field(
        default="stream",
        description="How to ingest very large text files. 'stream' avoids loading entire files into memory.",
    )
    large_file_stream_chunk_chars: int = Field(
        default=2_000_000,
        ge=100_000,
        le=50_000_000,
        description="When large_file_mode='stream', read text files in bounded char blocks (best-effort).",
    )

    parquet_extract_max_rows: int = Field(
        default=5000,
        ge=1,
        le=200000,
        description="Max rows to extract from a single Parquet file during indexing (best-effort)",
    )
    parquet_extract_max_chars: int = Field(
        default=2_000_000,
        ge=10_000,
        le=50_000_000,
        description="Max characters to extract from a single Parquet file during indexing (best-effort)",
    )
    parquet_extract_max_cell_chars: int = Field(
        default=20_000,
        ge=100,
        le=200_000,
        description="Max characters per extracted Parquet cell (best-effort)",
    )
    parquet_extract_text_columns_only: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Extract only text/string-like columns from Parquet files when possible",
    )
    parquet_extract_include_column_names: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Include column headers when extracting Parquet text",
    )
    skip_dense: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Skip dense vector indexing"
    )
    auto_prepare_dense_retrieval: bool = Field(
        default=True,
        description=(
            "After a dense indexing run completes, automatically build the per-corpus pgvector HNSW index "
            "and warm representative query embeddings so first retrievals are not cold."
        ),
    )
    estimated_tokens_per_second_local: int | None = Field(
        default=None,
        ge=100,
        le=500_000,
        description="Optional local embedding throughput override for index-time estimates (tokens/sec).",
    )

    @property
    def postgres_ts_config(self) -> str:
        """Resolve Postgres FTS config name from TriBridConfig (LAW).

        - tokenizer=stemmer → use bm25_stemmer_lang (e.g., 'english')
        - tokenizer=lowercase/whitespace → use the built-in 'simple' config (no stemming)
        """
        tok = (self.bm25_tokenizer or "").strip().lower()
        if tok == "stemmer":
            lang = (self.bm25_stemmer_lang or "").strip()
            return lang or "english"
        return "simple"


# =============================================================================
# GRAPH STORAGE CONFIG (Neo4j)
# =============================================================================

class GraphStorageConfig(BaseModel):
    """Configuration for Neo4j graph storage and traversal."""

    neo4j_uri: str = Field(
        default="bolt://localhost:7687",
        description="Neo4j connection URI (bolt:// or neo4j://)"
    )

    neo4j_user: str = Field(
        default="neo4j",
        description="Neo4j username"
    )

    neo4j_database: str = Field(
        default="neo4j",
        description="Neo4j database name"
    )

    neo4j_database_mode: Literal["shared", "per_corpus"] = Field(
        default="shared",
        description="Database isolation mode: 'shared' uses a single Neo4j database (Community-compatible), "
        "'per_corpus' uses a separate Neo4j database per corpus (Enterprise multi-database).",
    )

    neo4j_database_prefix: str = Field(
        default="tribrid_",
        description="Prefix for per-corpus Neo4j database names when neo4j_database_mode='per_corpus'.",
    )

    neo4j_auto_create_databases: bool = Field(
        default=True,
        description="Automatically create per-corpus Neo4j databases when missing (Enterprise).",
    )

    neo4j_vector_query_mode: Literal["auto", "procedure", "search"] = Field(
        default="auto",
        description="Neo4j chunk-vector query mode. 'auto' prefers runtime-safe defaults and only uses SEARCH where supported.",
    )

    max_hops: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum traversal hops for graph search"
    )

    include_communities: bool = Field(
        default=True,
        description="Include community detection in graph analysis"
    )

    community_algorithm: Literal["louvain", "label_propagation"] = Field(
        default="louvain",
        description="Community detection algorithm"
    )

    entity_types: list[str] = Field(
        default=["function", "class", "module", "variable", "import"],
        description="Entity types to extract and store in graph"
    )

    relationship_types: list[str] = Field(
        default=["calls", "imports", "inherits", "contains", "references"],
        description="Relationship types to extract"
    )

    graph_search_top_k: int = Field(
        default=30,
        ge=5,
        le=100,
        description="Number of results from graph traversal"
    )

    def resolve_password(self) -> str:
        """Resolve the Neo4j password from env-only operator secrets."""
        return str(os.getenv("NEO4J_PASSWORD", "") or "").strip()

    def resolve_database(self, corpus_id: str | None) -> str:
        """Resolve the Neo4j database name for a corpus.

        - shared: use neo4j_database
        - per_corpus: derive from corpus_id + prefix (sanitized)
        """
        if self.neo4j_database_mode == "shared" or not corpus_id:
            return self.neo4j_database
        base = f"{self.neo4j_database_prefix}{corpus_id}"
        v = base.strip().lower()
        v = re.sub(r"[^a-z0-9_]+", "_", v)
        v = re.sub(r"_+", "_", v).strip("_")
        if not v:
            return self.neo4j_database
        if v[0].isdigit():
            v = f"db_{v}"
        return v[:63]


# =============================================================================
# FUSION CONFIG (Tri-Brid Specific)
# =============================================================================

class FusionConfig(BaseModel):
    """Configuration for tri-brid fusion of vector + sparse + graph results."""

    method: Literal["rrf", "weighted"] = Field(
        default="rrf",
        description="Fusion method: 'rrf' (Reciprocal Rank Fusion) or 'weighted' (score-based)"
    )

    vector_weight: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Weight for vector search results (pgvector)"
    )

    sparse_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for sparse BM25/FTS search results"
    )

    graph_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for graph search results (Neo4j)"
    )

    rrf_k: int = Field(
        default=60,
        ge=1,
        le=200,
        description="RRF smoothing constant (higher = more weight to top ranks)"
    )

    normalize_scores: bool = Field(
        default=True,
        description="Normalize scores to [0,1] before fusion"
    )

    @model_validator(mode='after')
    def validate_weights_sum_to_one(self) -> Self:
        """Normalize tri-brid weights to sum to 1.0."""
        total = self.vector_weight + self.sparse_weight + self.graph_weight
        if total <= 0:
            self.vector_weight = 0.4
            self.sparse_weight = 0.3
            self.graph_weight = 0.3
            return self
        if not (0.99 <= total <= 1.01):
            self.vector_weight = self.vector_weight / total
            self.sparse_weight = self.sparse_weight / total
            self.graph_weight = self.graph_weight / total
        return self


# =============================================================================
# VECTOR SEARCH CONFIG
# =============================================================================

class VectorSearchConfig(BaseModel):
    """Configuration for vector (dense) search using pgvector."""

    enabled: bool = Field(
        default=True,
        description="Enable vector search in tri-brid retrieval"
    )

    top_k: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Number of results to retrieve from vector search"
    )

    similarity_threshold: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score threshold (0 = no threshold)"
    )


# =============================================================================
# SPARSE SEARCH CONFIG
# =============================================================================

class SparseSearchConfig(BaseModel):
    """Configuration for sparse (BM25) search."""

    engine: Literal["postgres_fts", "pg_search_bm25"] = Field(
        default="postgres_fts",
        description="Sparse retrieval engine. 'postgres_fts' uses built-in FTS; 'pg_search_bm25' uses ParadeDB pg_search.",
    )
    query_mode: Literal["plain", "phrase", "boolean"] = Field(
        default="plain",
        description="How to interpret the sparse query string.",
    )
    highlight: bool = Field(
        default=False,
        description="Enable sparse highlight payloads when supported (UI later).",
    )
    relax_on_empty: bool = Field(
        default=True,
        description="If sparse retrieval returns empty, retry with a relaxed OR-style query (best-effort).",
    )
    relax_max_terms: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Max extracted query terms used for relaxed sparse fallback.",
    )
    file_path_fallback: bool = Field(
        default=True,
        description="If sparse retrieval returns empty, run a file_path-based fallback ranking (best-effort).",
    )
    file_path_max_terms: int = Field(
        default=6,
        ge=1,
        le=32,
        description="Max extracted query terms used for file_path fallback.",
    )
    enabled: bool = Field(
        default=True,
        description="Enable sparse BM25 search in tri-brid retrieval"
    )

    top_k: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Number of results to retrieve from sparse search"
    )

    bm25_k1: float = Field(
        default=1.2,
        ge=0.5,
        le=3.0,
        description="BM25 term frequency saturation (higher = more weight to term frequency)"
    )

    bm25_b: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="BM25 length normalization (0 = no penalty, 1 = full penalty)"
    )


# =============================================================================
# GRAPH SEARCH CONFIG
# =============================================================================

class GraphSearchConfig(BaseModel):
    """Configuration for graph-based search using Neo4j."""

    mode: Literal["chunk", "entity"] = Field(
        default="chunk",
        description="Graph retrieval mode. 'chunk' uses lexical chunk nodes + Neo4j vector index; "
        "'entity' uses the legacy code-entity graph.",
    )

    enabled: bool = Field(
        default=True,
        description="Enable graph search in tri-brid retrieval"
    )

    chunk_neighbor_window: int = Field(
        default=1,
        ge=0,
        le=10,
        description="When mode='chunk', include up to N adjacent chunks (NEXT_CHUNK) around each seed hit",
    )

    chunk_seed_overfetch_multiplier: int = Field(
        default=10,
        ge=1,
        le=50,
        description="When mode='chunk' and Neo4j uses a shared database, overfetch seed hits before filtering by corpus_id",
    )

    chunk_entity_expansion_enabled: bool = Field(
        default=True,
        description="When mode='chunk', expand from seed chunks via Entity graph (IN_CHUNK links) to find related chunks",
    )

    chunk_entity_expansion_weight: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Blend weight for entity-expansion scores relative to seed chunk scores (mode='chunk')",
    )

    max_hops: int = Field(
        default=2,
        ge=1,
        le=5,
        description="Maximum graph traversal hops"
    )

    include_communities: bool = Field(
        default=True,
        description="Include community-based expansion in graph search"
    )

    top_k: int = Field(
        default=30,
        ge=5,
        le=100,
        description="Number of results to retrieve from graph search"
    )


# =============================================================================
# GRAPH INDEXING CONFIG
# =============================================================================

class GraphIndexingConfig(BaseModel):
    """Configuration for building/persisting graph data during indexing."""

    enabled: bool = Field(
        default=True,
        description="Enable graph building during indexing (Neo4j)",
    )

    build_lexical_graph: bool = Field(
        default=True,
        description="Build lexical graph (Document/Chunk nodes + NEXT_CHUNK relationships)",
    )

    store_chunk_embeddings: bool = Field(
        default=True,
        description="Store chunk embeddings on Chunk nodes for Neo4j vector search (requires dense embeddings)",
    )

    semantic_kg_enabled: bool = Field(
        default=False,
        description="Build an official Neo4j GraphRAG semantic graph with typed entities and relationships linked to chunks during indexing",
    )

    ast_contains_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Edge weight for AST containment relationships (module->class/function, class->method).",
    )

    ast_inherits_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Edge weight for AST inheritance relationships (class->base).",
    )

    ast_imports_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Edge weight for AST import relationships (module->imported_module).",
    )

    ast_calls_weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Edge weight for AST call relationships (function->callee).",
    )

    semantic_kg_mode: Literal["heuristic", "llm"] = Field(
        default="llm",
        description="Semantic KG extraction mode. This branch targets the official Neo4j GraphRAG LLM path; 'heuristic' is a stale legacy setting.",
    )

    semantic_kg_typed_entities_enabled: bool = Field(
        default=True,
        description="When true, semantic KG extraction preserves typed entities (person, org, location, event, concept).",
    )

    semantic_kg_allowed_entity_types: list[Literal["person", "org", "location", "event", "concept"]] = Field(
        default=["person", "org", "location", "event", "concept"],
        description="Allowed semantic KG entity types produced by extraction.",
    )

    semantic_kg_allowed_relation_types: list[
        Literal[
            "associated_with",
            "met_with",
            "communicated_with",
            "works_for",
            "member_of",
            "founded",
            "owns",
            "funded",
            "participated_in",
            "located_in",
            "references",
            "related_to",
        ]
    ] = Field(
        default=[
            "associated_with",
            "met_with",
            "communicated_with",
            "works_for",
            "member_of",
            "founded",
            "owns",
            "funded",
            "participated_in",
            "located_in",
            "references",
            "related_to",
        ],
        description="Allowed semantic KG relationship types produced by extraction.",
    )

    semantic_kg_require_llm_success: bool = Field(
        default=False,
        description="When true, fail the indexing run if GraphRAG semantic extraction fails for a chunk.",
    )

    semantic_kg_reasoning_effort: Literal["minimal", "low", "medium", "high", "xhigh"] = Field(
        default="medium",
        description="Reasoning effort for semantic KG extraction when using OpenAI Responses-compatible models.",
    )

    semantic_kg_relation_weight_llm: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Edge weight for semantic concept relations in LLM mode.",
    )

    semantic_kg_relation_weight_heuristic: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Edge weight for semantic concept relations in heuristic fallback mode.",
    )

    semantic_kg_max_concepts_per_chunk: int = Field(
        default=8,
        ge=0,
        le=50,
        description="Maximum semantic concepts to extract per chunk",
    )

    semantic_kg_min_concept_len: int = Field(
        default=4,
        ge=3,
        le=20,
        description="Minimum length for semantic concept tokens",
    )

    semantic_kg_max_relations_per_chunk: int = Field(
        default=12,
        ge=0,
        le=200,
        description="Maximum semantic relations to retain per chunk during GraphRAG extraction",
    )

    semantic_kg_max_chunks: int = Field(
        default=40000,
        ge=0,
        le=100000,
        description="Maximum chunks to process for semantic KG extraction per indexing run (0 = disabled)",
    )

    semantic_kg_llm_model: str = Field(
        default="",
        description="Explicit runtime-selectable GEN catalog model for GraphRAG semantic extraction; required when semantic KG is enabled",
    )

    semantic_kg_llm_timeout_s: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout (seconds) for semantic KG LLM extraction per chunk",
    )

    chunk_vector_index_name: str = Field(
        default="tribrid_chunk_embeddings",
        description="Neo4j vector index name for Chunk embeddings (mode='chunk')",
    )

    chunk_embedding_property: str = Field(
        default="embedding",
        description="Chunk node property that stores the embedding vector",
    )

    vector_similarity_function: Literal["cosine", "euclidean"] = Field(
        default="cosine",
        description="Neo4j vector similarity function",
    )

    wait_vector_index_online: bool = Field(
        default=True,
        description="Wait for the Neo4j vector index to come ONLINE after (re)creating it",
    )

    vector_index_online_timeout_s: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Timeout waiting for Neo4j vector index ONLINE (seconds)",
    )


class RerankingConfig(BaseModel):
    """Reranking configuration for result refinement."""

    reranker_mode: str = Field(
        default="none",
        pattern="^(cloud|local|learning|none)$",
        description=(
            "Reranker mode: 'cloud' (Cohere/Voyage/Jina API), 'learning' (MLX Qwen3 LoRA learning reranker), "
            "'none' (disabled). Legacy values 'local'/'hf' normalize to 'learning'."
        ),
    )

    reranker_cloud_provider: str = Field(
        default="cohere",
        description="Cloud reranker provider when mode=cloud. Runtime-selectable today: cohere."
    )

    reranker_cloud_model: str = Field(
        default="rerank-v3.5",
        description="Cloud reranker model name when mode=cloud (runtime-selectable today: Cohere models)."
    )

    tribrid_reranker_alpha: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Blend weight for reranker scores"
    )

    tribrid_reranker_topn: int = Field(
        default=50,
        ge=10,
        le=200,
        description="Number of candidates to rerank (learning mode)"
    )

    reranker_cloud_top_n: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Number of candidates to rerank (cloud mode)"
    )

    tribrid_reranker_batch: int = Field(
        default=16,
        ge=1,
        le=128,
        description="Reranker batch size"
    )

    tribrid_reranker_maxlen: int = Field(
        default=512,
        ge=128,
        le=2048,
        description="Max token length for reranker"
    )

    tribrid_reranker_reload_on_change: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Hot-reload on model change"
    )

    tribrid_reranker_reload_period_sec: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Reload check period (seconds)"
    )

    reranker_timeout: int = Field(
        default=10,
        ge=5,
        le=60,
        description="Reranker API timeout (seconds)"
    )

    rerank_input_snippet_chars: int = Field(
        default=700,
        ge=200,
        le=2000,
        description="Snippet chars for reranking input"
    )

    @field_validator('reranker_mode', mode='before')
    @classmethod
    def normalize_mode(cls, v: str) -> str:
        """Normalize reranker mode aliases."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {'off', 'disabled'}:
                return 'none'
            if val in {'hf', 'local'}:
                # Back-compat: older configs used 'hf'/'local' for the legacy CrossEncoder reranker.
                # The product path is now the MLX Qwen3 learning reranker.
                return 'learning'
            # Map old 'cohere', 'voyage', 'jina' values to 'cloud'
            if val in {'cohere', 'voyage', 'jina'}:
                return 'cloud'
            return val
        return v

    @field_validator('reranker_cloud_provider', mode='before')
    @classmethod
    def normalize_cloud_provider(cls, v: str) -> str:
        """Normalize cloud provider aliases."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {'off', 'none', 'disabled', ''}:
                return ''
            return val
        return v


class EnrichmentConfig(BaseModel):
    """Code enrichment and chunk_summary generation configuration."""

    chunk_summaries_enrich_default: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable chunk_summary enrichment by default"
    )

    chunk_summaries_max: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Max chunk_summaries to generate"
    )

    enrich_code_chunks: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable chunk enrichment"
    )

    enrich_min_chars: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Min chars for enrichment"
    )

    enrich_max_chars: int = Field(
        default=1000,
        ge=100,
        le=5000,
        description="Max chars for enrichment prompt"
    )

    enrich_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Enrichment timeout (seconds)"
    )


class ChunkSummaryConfig(BaseModel):
    """Chunk summary builder filtering configuration."""

    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            "docs", "agent_docs", "website", "tests", "assets",
            "internal_docs.md", "out", "checkpoints", "models",
            "data", "telemetry", "node_mcp", "public", "examples",
            "bin", "reports", "screenshots", "web/dist", "gui"
        ],
        description="Directories to skip when building chunk_summaries"
    )

    exclude_patterns: list[str] = Field(
        default_factory=list,
        description="File patterns/extensions to skip"
    )

    exclude_keywords: list[str] = Field(
        default_factory=list,
        description="Keywords that, when present in code, skip the chunk"
    )

    code_snippet_length: int = Field(
        default=2000,
        ge=500,
        le=10000,
        description="Max code snippet length in semantic chunk_summaries"
    )

    max_symbols: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max symbols to include per chunk_summary"
    )

    max_routes: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max API routes to include per chunk_summary"
    )

    purpose_max_length: int = Field(
        default=240,
        ge=50,
        le=500,
        description="Max length for purpose field in chunk_summaries"
    )

    quick_tips: list[str] = Field(
        default_factory=list,
        description="Quick tips shown in chunk_summaries builder UI"
    )

    @field_validator('exclude_dirs', 'exclude_patterns', 'exclude_keywords', 'quick_tips', mode='before')
    @classmethod
    def _parse_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.replace('\n', ',').split(',') if item.strip()]
        if isinstance(v, (list, tuple, set)):
            cleaned = []
            for item in v:
                if item is None:
                    continue
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            return cleaned
        text = str(v).strip()
        return [text] if text else []


class KeywordsConfig(BaseModel):
    """Discriminative keywords configuration."""

    keywords_max_per_repo: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Max discriminative keywords per repo"
    )

    keywords_min_freq: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Min frequency for keyword"
    )

    keywords_boost: float = Field(
        default=1.3,
        ge=1.0,
        le=3.0,
        description="Score boost for keyword matches"
    )

    keywords_auto_generate: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Auto-generate keywords"
    )

    keywords_refresh_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Hours between keyword refresh"
    )


class TracingConfig(BaseModel):
    """Observability and tracing configuration."""

    tracing_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable distributed tracing"
    )

    trace_sampling_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling rate (0.0-1.0)"
    )

    prometheus_port: int = Field(
        default=9090,
        ge=1024,
        le=65535,
        description="Prometheus metrics port"
    )

    metrics_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable metrics collection"
    )

    alert_include_resolved: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Include resolved alerts"
    )

    alert_webhook_timeout: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Alert webhook timeout (seconds)"
    )

    log_level: str = Field(
        default="INFO",
        pattern="^(DEBUG|INFO|WARNING|ERROR)$",
        description="Logging level"
    )

    tracing_mode: str = Field(
        default="local",
        pattern="^(local|otel|otel_langfuse|off)$",
        description="Observability mode"
    )

    trace_retention: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Number of traces to retain"
    )

    tribrid_log_path: str = Field(
        default="data/logs/queries.jsonl",
        description="Query log file path"
    )

    alert_notify_severities: str = Field(
        default="critical,warning",
        description="Alert severities to notify"
    )

    otel_export_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable OTLP export for traces"
    )

    otlp_endpoint: str = Field(
        default="",
        description="OTLP HTTP endpoint for trace export"
    )

    otlp_headers: str = Field(
        default="",
        description="Comma-separated OTLP headers (k=v) for the exporter"
    )

    otel_service_name: str = Field(
        default="ragweld-api",
        description="Service name used for emitted OTel spans"
    )

    langfuse_enabled: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Enable Langfuse generation observations"
    )

    langfuse_base_url: str = Field(
        default="",
        description="Langfuse base URL"
    )

    langfuse_project: str = Field(
        default="ragweld",
        description="Langfuse project label for traces and generations"
    )

    tempo_base_url: str = Field(
        default="",
        description="Tempo or Grafana explore base URL used for trace deep links"
    )

    alloy_base_url: str = Field(
        default="",
        description="Grafana Alloy base URL used for collector status checks"
    )

    mimir_base_url: str = Field(
        default="",
        description="Grafana Mimir base URL used for metrics backend status checks"
    )

    pyroscope_base_url: str = Field(
        default="",
        description="Grafana Pyroscope base URL used for profiling status checks"
    )

    faro_base_url: str = Field(
        default="",
        description="Grafana Faro or collector base URL used for frontend telemetry status checks"
    )

    opencost_base_url: str = Field(
        default="",
        description="OpenCost base URL used for cost and capacity status checks"
    )

    alertmanager_base_url: str = Field(
        default="",
        description="Alertmanager base URL used for wake-up path status checks"
    )

    cost_tracking_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable online request cost attribution in traces"
    )

    @field_validator('tracing_mode', mode='before')
    @classmethod
    def normalize_tracing_mode(cls, v: str) -> str:
        """Normalize tracing mode aliases."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val == 'none':
                return 'off'
            if val in {'otel+langfuse', 'langfuse'}:
                return 'otel_langfuse'
            return val
        return v


class TrainingConfig(BaseModel):
    """Reranker training configuration."""

    reranker_train_epochs: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Training epochs for reranker"
    )

    reranker_train_batch: int = Field(
        default=16,
        ge=1,
        le=128,
        description="Training batch size"
    )

    reranker_train_lr: float = Field(
        default=2e-5,
        ge=1e-6,
        le=1e-3,
        description="Learning rate"
    )

    reranker_warmup_ratio: float = Field(
        default=0.1,
        ge=0.0,
        le=0.5,
        description="Warmup steps ratio"
    )

    triplets_min_count: int = Field(
        default=100,
        ge=10,
        le=10000,
        description="Min triplets for training"
    )

    triplets_mine_mode: str = Field(
        default="replace",
        pattern="^(replace|append)$",
        description="Triplet mining mode"
    )

    tribrid_reranker_model_path: str = Field(
        default="models/learning-reranker-active",
        description="Active learning reranker artifact path (MLX adapter directory)."
    )

    tribrid_reranker_mine_mode: str = Field(
        default="replace",
        pattern="^(replace|append)$",
        description="Triplet mining mode"
    )

    tribrid_reranker_mine_reset: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Reset triplets file before mining"
    )

    tribrid_triplets_path: str = Field(
        default="data/training/triplets.jsonl",
        description="Training triplets file path"
    )

    learning_reranker_backend: Literal["auto", "mlx_qwen3"] = Field(
        default="auto",
        description=(
            "Learning reranker backend: auto (prefer MLX Qwen3 on Apple Silicon), mlx_qwen3 (force). "
            "Legacy values 'transformers'/'hf' normalize to 'auto'."
        ),
    )

    @field_validator("learning_reranker_backend", mode="before")
    @classmethod
    def normalize_learning_backend(cls, v: str) -> str:
        """Normalize learning reranker backend aliases."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {"transformers", "hf"}:
                return "auto"
            if val == "mlx":
                return "mlx_qwen3"
            return val
        return v

    learning_reranker_base_model: str = Field(
        default="Qwen/Qwen3-Reranker-0.6B",
        description="Base model to fine-tune for MLX Qwen3 learning reranker",
    )

    learning_reranker_lora_rank: int = Field(
        default=16,
        ge=1,
        le=128,
        description="LoRA rank for MLX Qwen3 learning reranker",
    )

    learning_reranker_lora_alpha: float = Field(
        default=32.0,
        gt=0.0,
        le=512.0,
        description="LoRA alpha for MLX Qwen3 learning reranker",
    )

    learning_reranker_lora_dropout: float = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        description="LoRA dropout for MLX Qwen3 learning reranker",
    )

    learning_reranker_lora_target_modules: list[str] = Field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"],
        min_length=1,
        description="Module name suffixes to apply LoRA to (MLX Qwen3)",
    )

    learning_reranker_negative_ratio: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Negative pairs per positive during learning reranker training",
    )

    learning_reranker_grad_accum_steps: int = Field(
        default=8,
        ge=1,
        le=128,
        description="Gradient accumulation steps per optimizer update for MLX Qwen3 learning reranker training",
    )

    learning_reranker_promote_if_improves: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Promote trained learning artifact to active path only if primary metric improves",
    )

    learning_reranker_promote_epsilon: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum improvement required to auto-promote (primary metric delta)",
    )

    learning_reranker_unload_after_sec: int = Field(
        default=0,
        ge=0,
        le=86400,
        description="Unload MLX learning reranker model after idle seconds (0 = never)",
    )

    learning_reranker_telemetry_interval_steps: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Emit trainer telemetry every N optimizer steps (plus first/final)",
    )

    # ---------------------------------------------------------------------
    # Ragweld agent (in-process MLX chat model + LoRA adapters)
    # ---------------------------------------------------------------------

    ragweld_agent_backend: str = Field(
        default="mlx_qwen3",
        description="Ragweld agent backend (in-process chat model). Currently: mlx_qwen3",
    )

    ragweld_agent_workflow_backend: Literal["local", "flyte"] = Field(
        default="local",
        description="Workflow/orchestration backend for Learning Agent runs.",
    )

    ragweld_agent_tracking_backend: Literal["local", "mlflow"] = Field(
        default="local",
        description="Run/artifact tracking backend for Learning Agent runs.",
    )

    ragweld_agent_base_model: str = Field(
        default="mlx-community/Qwen3-1.7B-4bit",
        description="Shipped base model for the ragweld agent (MLX).",
    )

    ragweld_agent_model_path: str = Field(
        default="models/learning-agent-active",
        description="Active ragweld agent adapter artifact path (directory containing adapter.npz + adapter_config.json).",
    )

    ragweld_agent_unload_after_sec: int = Field(
        default=0,
        ge=0,
        le=86400,
        description="Unload ragweld agent model after idle seconds (0 = never).",
    )

    ragweld_agent_reload_period_sec: int = Field(
        default=60,
        ge=0,
        le=600,
        description="Adapter reload check period (seconds). 0 = check every request.",
    )

    ragweld_agent_train_dataset_path: str = Field(
        default="",
        description="Training dataset path for the ragweld agent (empty = use evaluation.eval_dataset_path).",
    )

    ragweld_agent_lora_rank: int = Field(
        default=16,
        ge=1,
        le=128,
        description="LoRA rank for ragweld agent MLX fine-tuning.",
    )

    ragweld_agent_lora_alpha: float = Field(
        default=32.0,
        gt=0.0,
        le=512.0,
        description="LoRA alpha for ragweld agent MLX fine-tuning.",
    )

    ragweld_agent_lora_dropout: float = Field(
        default=0.05,
        ge=0.0,
        le=0.5,
        description="LoRA dropout for ragweld agent MLX fine-tuning.",
    )

    ragweld_agent_lora_target_modules: list[str] = Field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"],
        min_length=1,
        description="Module name suffixes to apply LoRA to (ragweld agent; MLX Qwen3).",
    )

    ragweld_agent_grad_accum_steps: int = Field(
        default=8,
        ge=1,
        le=128,
        description="Gradient accumulation steps per optimizer update for ragweld agent training.",
    )

    ragweld_agent_telemetry_interval_steps: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Emit ragweld agent trainer telemetry every N optimizer steps (plus first/final).",
    )

    ragweld_agent_promote_if_improves: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Auto-promote trained ragweld agent adapter only if eval_loss improves.",
    )

    ragweld_agent_promote_epsilon: float = Field(
        default=0.0,
        ge=0.0,
        le=10.0,
        description="Minimum eval_loss improvement required to auto-promote (baseline_loss - new_loss >= epsilon).",
    )

    ragweld_agent_flyte_admin_base_url: str = Field(
        default="",
        description="Base URL for Flyte Admin HTTP access (used for readiness checks and operator links).",
    )

    ragweld_agent_flyte_console_base_url: str = Field(
        default="",
        description="Base URL for Flyte Console (used for operator deep links).",
    )

    ragweld_agent_flyte_project: str = Field(
        default="ragweld",
        description="Flyte project that owns Learning Agent executions.",
    )

    ragweld_agent_flyte_domain: str = Field(
        default="development",
        description="Flyte domain/environment that owns Learning Agent executions.",
    )

    ragweld_agent_flyte_launchplan: str = Field(
        default="",
        description="Flyte launch plan name for the Learning Agent workflow lane.",
    )

    ragweld_agent_mlflow_tracking_url: str = Field(
        default="",
        description="Base URL for MLflow Tracking/UI used by Learning Agent runs.",
    )

    ragweld_agent_mlflow_experiment_name: str = Field(
        default="ragweld-learning-agent",
        description="MLflow experiment name for Learning Agent runs.",
    )

    ragweld_agent_unsloth_image: str = Field(
        default="",
        description="Container image or artifact reference used by the Flyte task to run Unsloth training.",
    )


class UIConfig(BaseModel):
    """User interface configuration."""

    chat_streaming_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable streaming responses"
    )

    chat_history_max: int = Field(
        default=50,
        ge=10,
        le=500,
        description="Max chat history messages"
    )

    chat_stream_include_thinking: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Include reasoning/thinking in streamed responses when supported by model"
    )

    chat_show_confidence: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Show confidence badge on chat answers"
    )

    chat_show_citations: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Show citations list on chat answers"
    )

    chat_show_trace: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Show routing trace panel by default"
    )

    chat_show_debug_footer: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Show dev/debug footer under chat answers"
    )

    chat_default_model: str = Field(
        default="gpt-4o-mini",
        description="Default model for chat if not specified in request"
    )

    chat_stream_timeout: int = Field(
        default=120,
        ge=30,
        le=600,
        description="Streaming response timeout in seconds"
    )

    chat_thinking_budget_tokens: int = Field(
        default=10000,
        ge=1000,
        le=100000,
        description="Max thinking tokens for Anthropic extended thinking"
    )

    editor_port: int = Field(
        default=4440,
        ge=1024,
        le=65535,
        description="Embedded editor port"
    )

    grafana_dashboard_uid: str = Field(
        default="ragweld-oncall-overview",
        description="Default Grafana dashboard UID"
    )

    grafana_dashboard_slug: str = Field(
        default="on-call-overview",
        description="Grafana dashboard slug"
    )

    grafana_base_url: str = Field(
        default="http://127.0.0.1:3301",
        description="Grafana base URL"
    )

    grafana_auth_mode: str = Field(
        default="anonymous",
        description="Grafana authentication mode"
    )

    grafana_embed_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable Grafana embedding"
    )

    grafana_kiosk: str = Field(
        default="tv",
        description="Grafana kiosk mode"
    )

    grafana_org_id: int = Field(
        default=1,
        description="Grafana organization ID"
    )

    grafana_refresh: str = Field(
        default="10s",
        description="Grafana refresh interval"
    )

    editor_bind: str = Field(
        default="local",
        description="Editor bind mode"
    )

    editor_embed_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable editor embedding"
    )

    editor_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable embedded editor"
    )

    editor_image: str = Field(
        default="codercom/code-server:latest",
        description="Editor Docker image"
    )

    theme_mode: str = Field(
        default="dark",
        pattern="^(light|dark|auto)$",
        description="UI theme mode"
    )

    open_browser: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Auto-open browser on start"
    )

    runtime_mode: Literal["development", "production"] = Field(
        default="development",
        description="Runtime environment mode (development uses localhost, production uses deployed URLs)"
    )

    learning_reranker_studio_v2_enabled: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Enable Learning Reranker Studio V2 layout and controls",
    )

    learning_reranker_studio_immersive: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Use immersive full-height studio mode for Learning Reranker",
    )

    learning_reranker_layout_engine: Literal["dockview", "panels"] = Field(
        default="dockview",
        description="Learning Reranker Studio layout engine selection",
    )

    learning_reranker_default_preset: Literal["balanced", "focus_viz", "focus_logs", "focus_inspector"] = Field(
        default="balanced",
        description="Default pane layout preset applied when opening Learning Reranker Studio",
    )

    learning_reranker_show_setup_row: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Show setup summary row above studio dock layout (1=show, 0=collapsed)",
    )

    learning_reranker_logs_renderer: Literal["json", "xterm"] = Field(
        default="xterm",
        description="Preferred logs renderer for Learning Reranker Studio",
    )

    learning_reranker_dockview_layout_json: str = Field(
        default="",
        description="Serialized Dockview layout JSON for Learning Reranker Studio pane persistence",
    )

    learning_reranker_studio_left_panel_pct: int = Field(
        default=20,
        ge=15,
        le=35,
        description="Default left dock width percentage for Learning Reranker Studio",
    )

    learning_reranker_studio_right_panel_pct: int = Field(
        default=30,
        ge=20,
        le=45,
        description="Default right dock width percentage for Learning Reranker Studio",
    )

    learning_reranker_studio_bottom_panel_pct: int = Field(
        default=28,
        ge=18,
        le=45,
        description="Default bottom dock height percentage for Learning Reranker Studio",
    )

    learning_reranker_visualizer_renderer: Literal["auto", "webgpu", "webgl2", "canvas2d"] = Field(
        default="auto",
        description="Preferred renderer for Neural Visualizer",
    )

    learning_reranker_visualizer_quality: Literal["balanced", "cinematic", "ultra"] = Field(
        default="cinematic",
        description="Neural Visualizer quality tier",
    )

    learning_reranker_visualizer_color_mode: Literal["absolute", "delta"] = Field(
        default="absolute",
        description="Neural Visualizer trajectory coloring mode (absolute loss vs delta loss)",
    )

    learning_reranker_visualizer_max_points: int = Field(
        default=10000,
        ge=1000,
        le=50000,
        description="Maximum telemetry points retained for Neural Visualizer",
    )

    learning_reranker_visualizer_target_fps: int = Field(
        default=60,
        ge=30,
        le=144,
        description="Target FPS for Neural Visualizer animation loop",
    )

    learning_reranker_visualizer_tail_seconds: float = Field(
        default=8.0,
        ge=1.0,
        le=30.0,
        description="Temporal tail length in seconds for visualizer trajectory effects",
    )

    learning_reranker_visualizer_motion_intensity: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Global motion intensity multiplier for Neural Visualizer effects",
    )

    learning_reranker_visualizer_show_vector_field: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Render animated vector field accents in Neural Visualizer",
    )

    learning_reranker_visualizer_reduce_motion: int = Field(
        default=0,
        ge=0,
        le=1,
        description="Reduce Neural Visualizer motion for accessibility/performance",
    )


class HydrationConfig(BaseModel):
    """Context hydration configuration."""

    hydration_mode: str = Field(
        default="lazy",
        pattern="^(lazy|eager|none|off)$",
        description="Context hydration mode"
    )

    hydration_max_chars: int = Field(
        default=2000,
        ge=500,
        le=10000,
        description="Max characters to hydrate"
    )

    @field_validator('hydration_mode', mode='before')
    @classmethod
    def normalize_hydration_mode(cls, v: str) -> str:
        """Map aliases to canonical values."""
        if isinstance(v, str):
            val = v.strip().lower()
            if val == 'off':
                return 'none'
            return val
        return v


class EvaluationConfig(BaseModel):
    """Evaluation dataset configuration."""

    eval_dataset_path: str = Field(
        default="data/evaluation_dataset.json",
        description="Evaluation dataset path"
    )

    baseline_path: str = Field(
        default="data/evals/eval_baseline.json",
        description="Baseline results path"
    )

    recall_at_5_k: int = Field(
        default=5,
        ge=1,
        le=200,
        description="K used for recall_at_5 metric (default 5).",
    )

    recall_at_10_k: int = Field(
        default=10,
        ge=1,
        le=200,
        description="K used for recall_at_10 metric (default 10).",
    )

    recall_at_20_k: int = Field(
        default=20,
        ge=1,
        le=200,
        description="K used for recall_at_20 metric (default 20).",
    )

    precision_at_5_k: int = Field(
        default=5,
        ge=1,
        le=200,
        description="K used for precision_at_5 metric (default 5).",
    )

    ndcg_at_10_k: int = Field(
        default=10,
        ge=1,
        le=200,
        description="K used for ndcg_at_10 metric (default 10).",
    )

    eval_multi_m: int = Field(
        default=10,
        ge=1,
        le=20,
        description="Multi-query variants for evaluation"
    )


# =============================================================================
# DOMAIN MODELS - Prompt editing (Eval → System Prompts)
# =============================================================================

PromptCategory = Literal["chat", "retrieval", "indexing", "evaluation"]


class PromptMetadata(BaseModel):
    """Metadata describing how a prompt is used and edited in the UI."""

    label: str = Field(description="Human-friendly label")
    description: str = Field(description="What this prompt is used for")
    category: PromptCategory = Field(description="Prompt category")

    editable: bool = Field(
        default=True,
        description="Whether this prompt is editable in the System Prompts tab",
    )
    link_route: str | None = Field(
        default=None,
        description="Optional route to edit this prompt elsewhere (e.g. Chat → Settings)",
    )
    link_label: str | None = Field(
        default=None,
        description="Label for the link button shown when editable=false",
    )


class PromptsResponse(BaseModel):
    """Response containing prompt text and UI metadata."""

    prompts: dict[str, str] = Field(default_factory=dict, description="Prompt key -> value")
    metadata: dict[str, PromptMetadata] = Field(default_factory=dict, description="Prompt key -> metadata")


class PromptUpdateRequest(BaseModel):
    value: str = Field(description="New prompt value")


class PromptUpdateResponse(BaseModel):
    ok: bool = Field(default=True, description="Whether the update succeeded")
    prompt_key: str = Field(description="Prompt key that was updated")
    message: str = Field(description="Human-readable status message")
    prompt_set_ref: LineageRef | None = Field(default=None, description="Immutable prompt-set version after this edit.")
    bundle_id: str | None = Field(default=None, description="Current bundle id after the prompt edit was captured.")


class SystemPromptsConfig(BaseModel):
    """System prompts for LLM interactions - affects RAG pipeline behavior.

    These prompts control how LLMs behave during query processing, code analysis,
    and result generation. Changes here can significantly impact RAG accuracy.
    """

    main_rag_chat: str = Field(
        default='''You are a helpful agentic RAG database assistant.

## Your Role:
- Answer questions about the indexed database with precision and accuracy
- Offer practical, actionable insights based on the actual database information

## Guidelines:
- **Be Evidence-Based**: Ground every answer in the provided database information
- **Be Honest**: If the information doesn't contain enough information, say so, but try to provide a helpful answer based on the information you have.

## Response Format:
- Start with a direct answer to the question
- Provide a helpful answer based on the information you have

You answer strictly from the provided database information.''',
        description="Main conversational AI system prompt for answering database questions"
    )

    query_expansion: str = Field(
        default='''You are a database search query expander. Given a user's question,
generate alternative search queries that might find the same database using different terminology.

Rules:
- Output one query variant per line
- Keep variants concise (3-8 words each)
- Use technical synonyms (auth/authentication, config/configuration, etc.)
- Include both abstract and specific phrasings
- Do NOT include explanations, just the queries''',
        description="Generate query variants for better recall in hybrid search"
    )

    query_rewrite: str = Field(
        default="You rewrite developer questions into search-optimized queries without changing meaning.",
        description="Optimize user query for code search - expand CamelCase, include API nouns"
    )

    semantic_chunk_summaries: str = Field(
        default='''Analyze this database chunk and create a comprehensive JSON summary for database search. Focus on WHAT the database does (business purpose) and HOW it works (technical details). Include all important symbols, patterns, and domain concepts.

JSON format:
{
  "symbols": ["function_name", "class_name", "variable_name"],
  "purpose": "Clear business purpose - what problem this solves",
  "technical_details": "Key technical implementation details",
  "domain_concepts": ["business_term1", "business_term2"],
  "routes": ["api/endpoint", "webhook/path"],
  "dependencies": ["external_service", "library"],
  "patterns": ["design_pattern", "architectural_concept"]
}

Focus on:
- Domain-specific terminology and concepts from this database
- Technical patterns and architectural decisions
- Business logic and problem being solved
- Integration points, APIs, and external services
- Key algorithms, data structures, and workflows''',
        description="Generate JSON summaries for code chunks during indexing"
    )

    code_enrichment: str = Field(
        default='''Analyze this database and return a JSON object with: symbols (array of function/class/component names), purpose (one sentence description), keywords (array of technical terms). Be concise. Return ONLY valid JSON.''',
        description="Extract metadata from code chunks during indexing"
    )

    semantic_kg_extraction: str = Field(
        default='''You are a semantic knowledge graph extractor.

Given one corpus chunk, extract only entities and relations explicitly grounded in that text.

Rules:
- Return ONLY valid JSON (no markdown, no prose).
- Never fabricate entities, aliases, or links.
- Prefer exact surface forms for names (for example full person/organization names when present).
- Do not emit file paths or line numbers as entities.
- Keep output high-signal and deduplicated.

JSON format:
{
  "entities": [
    {"name": "Alex Rivera", "entity_type": "person"},
    {"name": "Northwind Labs", "entity_type": "org"},
    {"name": "Denver", "entity_type": "location"}
  ],
  "relations": [
    {"source": "Alex Rivera", "target": "Northwind Labs", "relation_type": "works_for", "evidence_text": "Alex Rivera works for Northwind Labs.", "confidence": 0.92},
    {"source": "Northwind Labs", "target": "Denver", "relation_type": "located_in", "evidence_text": "Northwind Labs is located in Denver.", "confidence": 0.95}
  ]
}

Allowed entity_type values: person, org, location, event, concept
Allowed relation_type values:
- associated_with
- met_with
- communicated_with
- works_for
- member_of
- founded
- owns
- funded
- participated_in
- located_in
- references
- related_to

Constraints:
- Extract only relations explicitly supported by the chunk text.
- Use canonical, grounded names for source/target (no invented aliases).
- If present, include optional "evidence_text" and "confidence" per relation.''',
        description="Prompt for LLM-assisted semantic KG extraction (typed entities + relations)"
    )

    eval_analysis: str = Field(
        default='''You are an expert RAG (Retrieval-Augmented Generation) system analyst.
Your job is to analyze evaluation comparisons and provide HONEST, SKEPTICAL insights.

CRITICAL: Do NOT force explanations that don't make sense. If the data is contradictory or confusing:
- Say so clearly: "This result is surprising and may indicate other factors at play"
- Consider: index changes, data drift, eval dataset updates, or measurement noise
- Acknowledge when correlation != causation
- It's BETTER to say "I'm not sure why this happened" than to fabricate a plausible-sounding but wrong explanation

Be rigorous:
1. Question whether the config changes ACTUALLY explain the performance delta
2. Flag when results seem counterintuitive (e.g., disabling a feature improving results)
3. Consider confounding variables: Was the index rebuilt? Did the test set change?
4. Provide actionable suggestions only when you have reasonable confidence

Format your response with clear sections using markdown headers.''',
        description="Analyze eval regressions with skeptical approach - avoid false explanations"
    )

    synthetic_judge: str = Field(
        default='''You are a strict evaluator for synthetic retrieval QA rows.

You receive:
- question
- expected_paths
- expected_answer
- source_file_path
- source_excerpt

Decide whether this row is useful for retrieval evaluation.

Scoring rubric (0-10):
- 9-10: specific, answerable from source, unambiguous grounding
- 7-8: mostly grounded, minor ambiguity
- 4-6: weak grounding, generic wording, low discriminative value
- 0-3: invalid, contradictory, or not answerable from source

Output JSON only:
{
  "score": 0.0,
  "keep": false,
  "reason": "short reason"
}

Rules:
- Keep reason concise (<200 chars)
- Set keep=true only when score >= 7.0
- Never output markdown or prose outside JSON''',
        description="Judge prompt for synthetic eval row curation and quality filtering"
    )

    lightweight_chunk_summaries: str = Field(
        default='''Extract key information from this database: symbols (function/class names), purpose (one sentence), keywords (technical terms). Return JSON only.''',
        description="Lightweight chunk_summary generation prompt for faster indexing"
    )


class DockerConfig(BaseModel):
    """Docker infrastructure configuration."""

    docker_status_timeout: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Timeout for Docker status check (seconds)"
    )

    docker_container_list_timeout: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Timeout for Docker container list (seconds)"
    )

    docker_container_action_timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Timeout for Docker container actions (start/stop/restart)"
    )

    docker_logs_tail: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Default number of log lines to tail from containers"
    )

    docker_logs_timestamps: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Include timestamps in Docker logs (1=yes, 0=no)"
    )

    dev_frontend_port: int = Field(
        default=55173,
        ge=1024,
        le=65535,
        description="Port for dev frontend (Vite)"
    )

    dev_backend_port: int = Field(
        default=58012,
        ge=1024,
        le=65535,
        description="Port for dev backend (Uvicorn)"
    )

class RecallConfig(BaseModel):
    """Persistent chat memory. ON by default.

    Indexes every conversation into a lightweight pgvector corpus.
    Self-hosted, local, zero privacy risk, negligible storage.
    """

    enabled: bool = Field(default=True, description="Enable Recall. ON by default.")
    vector_backend: str = Field(
        default="pgvector",
        pattern="^(pgvector|neo4j)$",
        description="pgvector recommended (already running).",
    )
    auto_index: bool = Field(default=True)
    index_delay_seconds: int = Field(default=5, ge=1, le=60)
    chunking_strategy: str = Field(
        default="sentence",
        pattern="^(sentence|paragraph|turn|fixed)$",
        description="'turn'=one chunk per message, 'sentence'=split by sentence.",
    )
    chunk_max_tokens: int = Field(
        default=256,
        ge=64,
        le=1024,
        description="Chat chunks should be smaller than code chunks.",
    )
    embedding_model: str = Field(
        default="",
        description="Override embedding model. Empty=use global config.",
    )
    max_history_tokens: int = Field(default=4096, ge=512, le=32768)
    default_corpus_id: str = Field(
        default="recall_default",
        description="Auto-created at first launch. Users never touch this.",
    )
    graph_enabled: bool = Field(
        default=False,
        description="Enable Recall graph indexing + retrieval (experimental).",
    )


class ChatMultimodalConfig(BaseModel):
    """Image upload + vision model configuration."""

    vision_enabled: bool = Field(default=True)
    max_image_size_mb: int = Field(default=20, ge=1, le=50)
    max_images_per_message: int = Field(default=5, ge=1, le=10)
    supported_formats: list[str] = Field(default=["png", "jpg", "jpeg", "gif", "webp"])
    image_detail: str = Field(
        default="auto",
        pattern="^(auto|low|high)$",
        description="OpenAI vision detail level.",
    )
    vision_model_override: str = Field(
        default="",
        description="Force model for vision. Empty=use chat model if it supports vision.",
    )


class ImageGenConfig(BaseModel):
    """Two tiers:
    - LOCAL: Direct CLI/subprocess (free, self-hosted)
    - CLOUD: Paid APIs (ComfyUI API, Replicate, DALL-E)

    ComfyUI is typically self-hosted. We do NOT use ComfyUI as the local P0 path; local P0 is
    direct CLI/subprocess. `comfyui_api` is a remote endpoint (self-hosted or paid).
    """

    enabled: bool = Field(default=False)
    provider: str = Field(default="local", pattern="^(local|openai|comfyui_api|replicate)$")
    # Local (free)
    local_command: str = Field(
        default="python -m qwen_image.generate",
        description="CLI command. Receives --prompt, --output, --steps, --width, --height.",
    )
    local_model_path: str = Field(default="")
    use_lightning_lora: bool = Field(default=True)
    # Cloud (paid)
    comfyui_api_endpoint: str = Field(default="")
    replicate_model: str = Field(default="")
    # Shared
    default_steps: int = Field(default=8, ge=1, le=50)
    default_resolution: str = Field(default="1024x1024")


class ChatConfig(BaseModel):
    """Top-level chat configuration. Lives at TriBridConfig.chat.

    KEY CONCEPT: There are no modes. The user checks/unchecks data sources.
    Recall is always available and ON by default. Corpora are available when indexed.
    Everything composes freely.
    """

    default_corpus_ids: list[str] = Field(
        default=["recall_default"],
        description="Default checked user-facing corpus IDs for new conversations.",
    )

    # Legacy prompt composition (kept for backwards compatibility; prefer the 4 state prompts below).
    system_prompt_base: str = Field(default="You are a helpful assistant.")
    system_prompt_recall_suffix: str = Field(
        default=" You have access to conversation history. Reference past discussions when relevant."
    )
    system_prompt_rag_suffix: str = Field(
        default=" Answer questions using the provided database information."
    )

    # Four-state prompts (selected based on whether RAG/Recall context is present).
    system_prompt_direct: str = Field(
        default="""You are a helpful agentic RAG database assistant.

The user is chatting directly without any retrieval context. No database repositories or conversation history are being queried for this message.

Answer based on your general knowledge. If the user asks about their specific database and no context is provided, let them know they can enable RAG corpora in the Data Sources panel to query their indexed repositories.

Be direct and helpful.""",
        description="State 1: No context. Nothing checked or retrieval returned empty.",
    )
    system_prompt_rag: str = Field(
        default="""You are a database assistant powered by TriBridRAG, a hybrid retrieval system that combines vector search, keyword search, and knowledge graphs to find relevant database.

The user has selected one or more database repositories to query. You will receive relevant database snippets in <rag_context>...</rag_context> tags.

Each snippet includes:
- File path and line numbers

How to use this context:
- Base your answers on the actual database shown, not assumptions
- Always cite file paths and line numbers when referencing database
- If the retrieved information doesn't fully answer the question, say what's missing
- Don't invent information that isn't in the context
- **Connect related pieces when they appear across multiple snippets** (e.g. if the user asks about a specific database table, and you have information about the table in the context, connect the information to the question)

Be helpful, friendly, and engaging, and base your answers on the actual database information you have.""",
        description="State 2: RAG only. Code corpora returned results; Recall did not.",
    )
    system_prompt_recall: str = Field(
        default="""You are an agentic RAG database assistant powered by TriBridRAG. You have access to your conversation history with this user via the Recall system.

Relevant snippets from past conversations appear in <recall_context>...</recall_context> tags.

Each snippet includes:
- Who said it (user or assistant)
- Timestamp
- The message content

How to use this context:
- Reference past discussions naturally
- Don't explicitly say "according to my recall" — incorporate it as shared context
- Past conversations may contain decisions, preferences, or context that inform the current question
- Prioritize recent conversations over older ones when relevant

Be direct and helpful. You're continuing an ongoing collaboration with this user.""",
        description="State 3: Recall only. Recall returned results; no RAG corpora active.",
    )
    system_prompt_rag_and_recall: str = Field(
        default="""You are an agentic RAG database assistant powered by TriBridRAG, a hybrid retrieval system. You have access to both:
1) The user's indexed database repositories
2) Your conversation history with this user (Recall)

database context appears in <rag_context>...</rag_context> tags.
Conversation history appears in <recall_context>...</recall_context> tags.

How to use both:
- Reference past discussions naturally
- Connect them when relevant (e.g., a past decision and the database information that implements it)
- If past context contradicts current database information, acknowledge the change
- Don't say "according to recall" — just incorporate shared knowledge naturally

Be helpful, friendly, and engaging, and base your answers on the actual database information you have.""",
        description="State 4: Both. RAG and Recall both returned results.",
    )

    recall: RecallConfig = Field(default_factory=RecallConfig)
    recall_gate: RecallGateConfig = Field(default_factory=RecallGateConfig)
    multimodal: ChatMultimodalConfig = Field(default_factory=ChatMultimodalConfig)
    image_gen: ImageGenConfig = Field(default_factory=ImageGenConfig)
    vllm: VLLMConfig = Field(default_factory=VLLMConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    local_models: LocalModelConfig = Field(default_factory=LocalModelConfig)
    openrouter: OpenRouterConfig = Field(default_factory=OpenRouterConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    openai_protocol: Literal["auto", "responses", "chat_completions"] = Field(
        default="auto",
        description="Protocol for OpenAI cloud_direct calls. 'auto' routes codex-only models to Responses.",
    )

    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    temperature_no_retrieval: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="Temperature when nothing is checked (direct chat = more creative)",
    )
    max_tokens: int = Field(default=4096, ge=100, le=16384)

    show_source_dropdown: bool = Field(default=True)
    send_shortcut: str = Field(default="ctrl+enter")


class TriBridConfig(BaseModel):
    """Root configuration model for tribrid_config.json.

    This is the top-level model that contains all configuration categories.
    The nested structure provides logical grouping and better organization.

    Note: Previously named TriBridConfig. Renamed for consistency with imports.
    """

    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    semantic_cache: SemanticCacheConfig = Field(default_factory=SemanticCacheConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    layer_bonus: LayerBonusConfig = Field(default_factory=LayerBonusConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    tokenization: TokenizationConfig = Field(default_factory=TokenizationConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    graph_storage: GraphStorageConfig = Field(default_factory=GraphStorageConfig)
    graph_indexing: GraphIndexingConfig = Field(default_factory=GraphIndexingConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    vector_search: VectorSearchConfig = Field(default_factory=VectorSearchConfig)
    sparse_search: SparseSearchConfig = Field(default_factory=SparseSearchConfig)
    graph_search: GraphSearchConfig = Field(default_factory=GraphSearchConfig)
    reranking: RerankingConfig = Field(default_factory=RerankingConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    enrichment: EnrichmentConfig = Field(default_factory=EnrichmentConfig)
    chunk_summaries: ChunkSummaryConfig = Field(default_factory=ChunkSummaryConfig)
    keywords: KeywordsConfig = Field(default_factory=KeywordsConfig)
    tracing: TracingConfig = Field(default_factory=TracingConfig)
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    hydration: HydrationConfig = Field(default_factory=HydrationConfig)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)
    system_prompts: SystemPromptsConfig = Field(default_factory=SystemPromptsConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    synthetic: SyntheticConfig = Field(default_factory=SyntheticConfig)
    docker: DockerConfig = Field(default_factory=DockerConfig)

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "description": "TRIBRID RAG Engine tunable configuration parameters",
            "title": "TRIBRID Config",
        },
    )

    def to_flat_dict(self) -> dict[str, Any]:
        """Convert nested config to flat dict with env-style keys.

        This provides backward compatibility with existing code that expects
        flat environment variable names like 'RRF_K_DIV' instead of nested
        access like config.retrieval.rrf_k_div.

        Returns:
            Flat dictionary mapping env-style keys to values:
            {
                'RRF_K_DIV': 60,
                'CHUNK_SUMMARY_BONUS': 0.08,
                ...
            }
        """
        return {
            # Retrieval params (existing + new)
            'RRF_K_DIV': self.retrieval.rrf_k_div,
            'LANGGRAPH_FINAL_K': self.retrieval.langgraph_final_k,
            'MAX_QUERY_REWRITES': self.retrieval.max_query_rewrites,
            'LANGGRAPH_MAX_QUERY_REWRITES': self.retrieval.langgraph_max_query_rewrites,
            'MQ_REWRITES': self.retrieval.max_query_rewrites,  # Legacy alias
            'FALLBACK_CONFIDENCE': self.retrieval.fallback_confidence,
            'FINAL_K': self.retrieval.final_k,
            'EVAL_FINAL_K': self.retrieval.eval_final_k,
            'CONF_TOP1': self.retrieval.conf_top1,
            'CONF_AVG5': self.retrieval.conf_avg5,
            'CONF_ANY': self.retrieval.conf_any,
            'EVAL_MULTI': self.retrieval.eval_multi,
            'QUERY_EXPANSION_ENABLED': self.retrieval.query_expansion_enabled,
            'BM25_WEIGHT': self.retrieval.bm25_weight,
            'BM25_K1': self.retrieval.bm25_k1,
            'BM25_B': self.retrieval.bm25_b,
            'VECTOR_WEIGHT': self.retrieval.vector_weight,
            'CHUNK_SUMMARY_SEARCH_ENABLED': self.retrieval.chunk_summary_search_enabled,
            'MULTI_QUERY_M': self.retrieval.multi_query_m,
            'USE_SEMANTIC_SYNONYMS': self.retrieval.use_semantic_synonyms,
            'TRIBRID_SYNONYMS_PATH': self.retrieval.tribrid_synonyms_path,
            'TOPK_DENSE': self.retrieval.topk_dense,
            'TOPK_SPARSE': self.retrieval.topk_sparse,
            # Semantic cache
            'SEMANTIC_CACHE_ENABLED': self.semantic_cache.enabled,
            'SEMANTIC_CACHE_MODE': self.semantic_cache.mode,
            'SEMANTIC_CACHE_MAX_ENTRIES': self.semantic_cache.max_entries,
            'SEMANTIC_CACHE_MIN_QUERY_CHARS': self.semantic_cache.min_query_chars,
            'SEMANTIC_CACHE_THRESHOLD_SEARCH': self.semantic_cache.similarity_threshold_search,
            'SEMANTIC_CACHE_THRESHOLD_ANSWER': self.semantic_cache.similarity_threshold_answer,
            'SEMANTIC_CACHE_THRESHOLD_CHAT': self.semantic_cache.similarity_threshold_chat,
            'SEMANTIC_CACHE_TTL_SEARCH_SEC': self.semantic_cache.ttl_seconds_search,
            'SEMANTIC_CACHE_TTL_ANSWER_SEC': self.semantic_cache.ttl_seconds_answer,
            'SEMANTIC_CACHE_TTL_CHAT_SEC': self.semantic_cache.ttl_seconds_chat,
            'SEMANTIC_CACHE_CHAT_HISTORY_WINDOW': self.semantic_cache.chat_history_window,
            'SEMANTIC_CACHE_BYPASS_IF_IMAGES': self.semantic_cache.bypass_if_images,
            'SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE': self.semantic_cache.max_temperature_for_write,
            # REMOVED: DISABLE_RERANK - use RERANKER_MODE='none' instead
            # Scoring params
            'CHUNK_SUMMARY_BONUS': self.scoring.chunk_summary_bonus,
            'FILENAME_BOOST_EXACT': self.scoring.filename_boost_exact,
            'FILENAME_BOOST_PARTIAL': self.scoring.filename_boost_partial,
            'VENDOR_MODE': self.scoring.vendor_mode,
            'PATH_BOOSTS': self.scoring.path_boosts,
            # Layer bonus params (intent-aware matrix)
            'LAYER_BONUS_GUI': self.layer_bonus.gui,
            'LAYER_BONUS_RETRIEVAL': self.layer_bonus.retrieval,
            'LAYER_BONUS_INDEXER': self.layer_bonus.indexer,
            'VENDOR_PENALTY': self.layer_bonus.vendor_penalty,
            'FRESHNESS_BONUS': self.layer_bonus.freshness_bonus,
            'LAYER_INTENT_MATRIX': self.layer_bonus.intent_matrix,
            # Embedding params (10 new)
            'EMBEDDING_TYPE': self.embedding.embedding_type,
            'EMBEDDING_MODEL': self.embedding.embedding_model,
            'EMBEDDING_DIM': self.embedding.embedding_dim,
            'VOYAGE_MODEL': self.embedding.voyage_model,
            'EMBEDDING_MODEL_LOCAL': self.embedding.embedding_model_local,
            'EMBEDDING_MODEL_MLX': self.embedding.embedding_model_mlx,
            'EMBEDDING_BATCH_SIZE': self.embedding.embedding_batch_size,
            'EMBEDDING_MAX_TOKENS': self.embedding.embedding_max_tokens,
            'EMBEDDING_CACHE_ENABLED': self.embedding.embedding_cache_enabled,
            'EMBEDDING_TIMEOUT': self.embedding.embedding_timeout,
            'EMBEDDING_RETRY_MAX': self.embedding.embedding_retry_max,
            # Chunking params (9 new)
            'CHUNK_SIZE': self.chunking.chunk_size,
            'CHUNK_OVERLAP': self.chunking.chunk_overlap,
            'AST_OVERLAP_LINES': self.chunking.ast_overlap_lines,
            'MAX_INDEXABLE_FILE_SIZE': self.chunking.max_indexable_file_size,
            'MAX_CHUNK_TOKENS': self.chunking.max_chunk_tokens,
            'MIN_CHUNK_CHARS': self.chunking.min_chunk_chars,
            'GREEDY_FALLBACK_TARGET': self.chunking.greedy_fallback_target,
            'CHUNKING_STRATEGY': self.chunking.chunking_strategy,
            'PRESERVE_IMPORTS': self.chunking.preserve_imports,
            # Indexing params (9 new)
            'POSTGRES_URL': self.indexing.postgres_url,
            'INDEXING_BATCH_SIZE': self.indexing.indexing_batch_size,
            'INDEXING_WORKERS': self.indexing.indexing_workers,
            'BM25_TOKENIZER': self.indexing.bm25_tokenizer,
            'BM25_STEMMER_LANG': self.indexing.bm25_stemmer_lang,
            'INDEX_EXCLUDED_EXTS': self.indexing.index_excluded_exts,
            'INDEX_MAX_FILE_SIZE_MB': self.indexing.index_max_file_size_mb,
            'PARQUET_EXTRACT_MAX_ROWS': self.indexing.parquet_extract_max_rows,
            'PARQUET_EXTRACT_MAX_CHARS': self.indexing.parquet_extract_max_chars,
            'PARQUET_EXTRACT_MAX_CELL_CHARS': self.indexing.parquet_extract_max_cell_chars,
            'PARQUET_EXTRACT_TEXT_COLUMNS_ONLY': self.indexing.parquet_extract_text_columns_only,
            'PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES': self.indexing.parquet_extract_include_column_names,
            'SKIP_DENSE': self.indexing.skip_dense,
            'AUTO_PREPARE_DENSE_RETRIEVAL': self.indexing.auto_prepare_dense_retrieval,
            'ESTIMATED_TOKENS_PER_SECOND_LOCAL': self.indexing.estimated_tokens_per_second_local,
            # Graph storage params (Neo4j)
            'NEO4J_URI': self.graph_storage.neo4j_uri,
            'NEO4J_USER': self.graph_storage.neo4j_user,
            'NEO4J_DATABASE': self.graph_storage.neo4j_database,
            'NEO4J_VECTOR_QUERY_MODE': self.graph_storage.neo4j_vector_query_mode,
            'GRAPH_MAX_HOPS': self.graph_storage.max_hops,
            'GRAPH_INCLUDE_COMMUNITIES': self.graph_storage.include_communities,
            'GRAPH_COMMUNITY_ALGORITHM': self.graph_storage.community_algorithm,
            'GRAPH_ENTITY_TYPES': ','.join(self.graph_storage.entity_types),
            'GRAPH_RELATIONSHIP_TYPES': ','.join(self.graph_storage.relationship_types),
            'GRAPH_SEARCH_TOP_K': self.graph_storage.graph_search_top_k,
            # Fusion params (tri-brid specific)
            'FUSION_METHOD': self.fusion.method,
            'FUSION_VECTOR_WEIGHT': self.fusion.vector_weight,
            'FUSION_SPARSE_WEIGHT': self.fusion.sparse_weight,
            'FUSION_GRAPH_WEIGHT': self.fusion.graph_weight,
            'FUSION_RRF_K': self.fusion.rrf_k,
            'FUSION_NORMALIZE_SCORES': self.fusion.normalize_scores,
    # Reranking params (14) - unified with RERANKER_MODE
            'RERANKER_MODE': self.reranking.reranker_mode,
            'RERANKER_CLOUD_PROVIDER': self.reranking.reranker_cloud_provider,
            'RERANKER_CLOUD_MODEL': self.reranking.reranker_cloud_model,
            'TRIBRID_RERANKER_ALPHA': self.reranking.tribrid_reranker_alpha,
            'TRIBRID_RERANKER_TOPN': self.reranking.tribrid_reranker_topn,
            'RERANKER_CLOUD_TOP_N': self.reranking.reranker_cloud_top_n,
            'TRIBRID_RERANKER_BATCH': self.reranking.tribrid_reranker_batch,
            'TRIBRID_RERANKER_MAXLEN': self.reranking.tribrid_reranker_maxlen,
            'TRIBRID_RERANKER_RELOAD_ON_CHANGE': self.reranking.tribrid_reranker_reload_on_change,
            'TRIBRID_RERANKER_RELOAD_PERIOD_SEC': self.reranking.tribrid_reranker_reload_period_sec,
            'RERANKER_TIMEOUT': self.reranking.reranker_timeout,
            'RERANK_INPUT_SNIPPET_CHARS': self.reranking.rerank_input_snippet_chars,
    # Generation params (12)
            'GEN_MODEL': self.generation.gen_model,
            'GEN_TEMPERATURE': self.generation.gen_temperature,
            'GEN_MAX_TOKENS': self.generation.gen_max_tokens,
            'GEN_TOP_P': self.generation.gen_top_p,
            'GEN_TIMEOUT': self.generation.gen_timeout,
            'GEN_RETRY_MAX': self.generation.gen_retry_max,
            'GEN_BACKEND': self.generation.gen_backend,
            'ENRICH_MODEL': self.generation.enrich_model,
            'ENRICH_BACKEND': self.generation.enrich_backend,
            'ENRICH_DISABLED': self.generation.enrich_disabled,
            'OLLAMA_NUM_CTX': self.generation.ollama_num_ctx,
            'OLLAMA_REQUEST_TIMEOUT': self.generation.ollama_request_timeout,
            'OLLAMA_STREAM_IDLE_TIMEOUT': self.generation.ollama_stream_idle_timeout,
            'GEN_MODEL_CLI': self.generation.gen_model_cli,
            'GEN_MODEL_OLLAMA': self.generation.gen_model_ollama,
            'GEN_MODEL_HTTP': self.generation.gen_model_http,
            'GEN_MODEL_MCP': self.generation.gen_model_mcp,
            'ENRICH_MODEL_OLLAMA': self.generation.enrich_model_ollama,
            'OLLAMA_URL': self.generation.ollama_url,
            'OPENAI_BASE_URL': self.generation.openai_base_url,
            # Enrichment params (6)
            'CHUNK_SUMMARIES_ENRICH_DEFAULT': self.enrichment.chunk_summaries_enrich_default,
            'CHUNK_SUMMARIES_MAX': self.enrichment.chunk_summaries_max,
            'ENRICH_CODE_CHUNKS': self.enrichment.enrich_code_chunks,
            'ENRICH_MIN_CHARS': self.enrichment.enrich_min_chars,
            'ENRICH_MAX_CHARS': self.enrichment.enrich_max_chars,
            'ENRICH_TIMEOUT': self.enrichment.enrich_timeout,
            # Chunk summaries filter params (8)
            'CHUNK_SUMMARIES_EXCLUDE_DIRS': ', '.join(self.chunk_summaries.exclude_dirs),
            'CHUNK_SUMMARIES_EXCLUDE_PATTERNS': ', '.join(self.chunk_summaries.exclude_patterns),
            'CHUNK_SUMMARIES_EXCLUDE_KEYWORDS': ', '.join(self.chunk_summaries.exclude_keywords),
            'CHUNK_SUMMARIES_CODE_SNIPPET_LENGTH': self.chunk_summaries.code_snippet_length,
            'CHUNK_SUMMARIES_MAX_SYMBOLS': self.chunk_summaries.max_symbols,
            'CHUNK_SUMMARIES_MAX_ROUTES': self.chunk_summaries.max_routes,
            'CHUNK_SUMMARIES_PURPOSE_MAX_LENGTH': self.chunk_summaries.purpose_max_length,
            'CHUNK_SUMMARIES_QUICK_TIPS': ', '.join(self.chunk_summaries.quick_tips),
            # Keywords params (5)
            'KEYWORDS_MAX_PER_REPO': self.keywords.keywords_max_per_repo,
            'KEYWORDS_MIN_FREQ': self.keywords.keywords_min_freq,
            'KEYWORDS_BOOST': self.keywords.keywords_boost,
            'KEYWORDS_AUTO_GENERATE': self.keywords.keywords_auto_generate,
            'KEYWORDS_REFRESH_HOURS': self.keywords.keywords_refresh_hours,
    # Tracing params
            'TRACING_ENABLED': self.tracing.tracing_enabled,
            'TRACE_SAMPLING_RATE': self.tracing.trace_sampling_rate,
            'PROMETHEUS_PORT': self.tracing.prometheus_port,
            'METRICS_ENABLED': self.tracing.metrics_enabled,
            'ALERT_INCLUDE_RESOLVED': self.tracing.alert_include_resolved,
            'ALERT_WEBHOOK_TIMEOUT': self.tracing.alert_webhook_timeout,
            'LOG_LEVEL': self.tracing.log_level,
            'TRACING_MODE': self.tracing.tracing_mode,
            'TRACE_RETENTION': self.tracing.trace_retention,
            'TRIBRID_LOG_PATH': self.tracing.tribrid_log_path,
            'ALERT_NOTIFY_SEVERITIES': self.tracing.alert_notify_severities,
            'OTEL_EXPORT_ENABLED': self.tracing.otel_export_enabled,
            'OTLP_ENDPOINT': self.tracing.otlp_endpoint,
            'OTLP_HEADERS': self.tracing.otlp_headers,
            'OTEL_SERVICE_NAME': self.tracing.otel_service_name,
            'LANGFUSE_ENABLED': self.tracing.langfuse_enabled,
            'LANGFUSE_BASE_URL': self.tracing.langfuse_base_url,
            'LANGFUSE_PROJECT': self.tracing.langfuse_project,
            'TEMPO_BASE_URL': self.tracing.tempo_base_url,
            'ALLOY_BASE_URL': self.tracing.alloy_base_url,
            'MIMIR_BASE_URL': self.tracing.mimir_base_url,
            'PYROSCOPE_BASE_URL': self.tracing.pyroscope_base_url,
            'FARO_BASE_URL': self.tracing.faro_base_url,
            'OPENCOST_BASE_URL': self.tracing.opencost_base_url,
            'ALERTMANAGER_BASE_URL': self.tracing.alertmanager_base_url,
            'COST_TRACKING_ENABLED': self.tracing.cost_tracking_enabled,
    # Training params (22)
            'RERANKER_TRAIN_EPOCHS': self.training.reranker_train_epochs,
            'RERANKER_TRAIN_BATCH': self.training.reranker_train_batch,
            'RERANKER_TRAIN_LR': self.training.reranker_train_lr,
            'RERANKER_WARMUP_RATIO': self.training.reranker_warmup_ratio,
            'TRIPLETS_MIN_COUNT': self.training.triplets_min_count,
            'TRIPLETS_MINE_MODE': self.training.triplets_mine_mode,
            'TRIBRID_RERANKER_MODEL_PATH': self.training.tribrid_reranker_model_path,
            'TRIBRID_RERANKER_MINE_MODE': self.training.tribrid_reranker_mine_mode,
            'TRIBRID_RERANKER_MINE_RESET': self.training.tribrid_reranker_mine_reset,
            'TRIBRID_TRIPLETS_PATH': self.training.tribrid_triplets_path,
            'LEARNING_RERANKER_BACKEND': self.training.learning_reranker_backend,
            'LEARNING_RERANKER_BASE_MODEL': self.training.learning_reranker_base_model,
            'LEARNING_RERANKER_LORA_RANK': self.training.learning_reranker_lora_rank,
            'LEARNING_RERANKER_LORA_ALPHA': self.training.learning_reranker_lora_alpha,
            'LEARNING_RERANKER_LORA_DROPOUT': self.training.learning_reranker_lora_dropout,
            'LEARNING_RERANKER_LORA_TARGET_MODULES': ', '.join(self.training.learning_reranker_lora_target_modules),
            'LEARNING_RERANKER_NEGATIVE_RATIO': self.training.learning_reranker_negative_ratio,
            'LEARNING_RERANKER_GRAD_ACCUM_STEPS': self.training.learning_reranker_grad_accum_steps,
            'LEARNING_RERANKER_PROMOTE_IF_IMPROVES': self.training.learning_reranker_promote_if_improves,
            'LEARNING_RERANKER_PROMOTE_EPSILON': self.training.learning_reranker_promote_epsilon,
            'LEARNING_RERANKER_UNLOAD_AFTER_SEC': self.training.learning_reranker_unload_after_sec,
            'LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS': self.training.learning_reranker_telemetry_interval_steps,
            'RAGWELD_AGENT_BACKEND': self.training.ragweld_agent_backend,
            'RAGWELD_AGENT_WORKFLOW_BACKEND': self.training.ragweld_agent_workflow_backend,
            'RAGWELD_AGENT_TRACKING_BACKEND': self.training.ragweld_agent_tracking_backend,
            'RAGWELD_AGENT_BASE_MODEL': self.training.ragweld_agent_base_model,
            'RAGWELD_AGENT_MODEL_PATH': self.training.ragweld_agent_model_path,
            'RAGWELD_AGENT_UNLOAD_AFTER_SEC': self.training.ragweld_agent_unload_after_sec,
            'RAGWELD_AGENT_RELOAD_PERIOD_SEC': self.training.ragweld_agent_reload_period_sec,
            'RAGWELD_AGENT_TRAIN_DATASET_PATH': self.training.ragweld_agent_train_dataset_path,
            'RAGWELD_AGENT_LORA_RANK': self.training.ragweld_agent_lora_rank,
            'RAGWELD_AGENT_LORA_ALPHA': self.training.ragweld_agent_lora_alpha,
            'RAGWELD_AGENT_LORA_DROPOUT': self.training.ragweld_agent_lora_dropout,
            'RAGWELD_AGENT_LORA_TARGET_MODULES': ', '.join(self.training.ragweld_agent_lora_target_modules),
            'RAGWELD_AGENT_GRAD_ACCUM_STEPS': self.training.ragweld_agent_grad_accum_steps,
            'RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS': self.training.ragweld_agent_telemetry_interval_steps,
            'RAGWELD_AGENT_PROMOTE_IF_IMPROVES': self.training.ragweld_agent_promote_if_improves,
            'RAGWELD_AGENT_PROMOTE_EPSILON': self.training.ragweld_agent_promote_epsilon,
            'RAGWELD_AGENT_FLYTE_ADMIN_BASE_URL': self.training.ragweld_agent_flyte_admin_base_url,
            'RAGWELD_AGENT_FLYTE_CONSOLE_BASE_URL': self.training.ragweld_agent_flyte_console_base_url,
            'RAGWELD_AGENT_FLYTE_PROJECT': self.training.ragweld_agent_flyte_project,
            'RAGWELD_AGENT_FLYTE_DOMAIN': self.training.ragweld_agent_flyte_domain,
            'RAGWELD_AGENT_FLYTE_LAUNCHPLAN': self.training.ragweld_agent_flyte_launchplan,
            'RAGWELD_AGENT_MLFLOW_TRACKING_URL': self.training.ragweld_agent_mlflow_tracking_url,
            'RAGWELD_AGENT_MLFLOW_EXPERIMENT_NAME': self.training.ragweld_agent_mlflow_experiment_name,
            'RAGWELD_AGENT_UNSLOTH_IMAGE': self.training.ragweld_agent_unsloth_image,
            # UI params (43)
            'CHAT_STREAMING_ENABLED': self.ui.chat_streaming_enabled,
            'CHAT_HISTORY_MAX': self.ui.chat_history_max,
            'CHAT_STREAM_INCLUDE_THINKING': self.ui.chat_stream_include_thinking,
            'CHAT_SHOW_CONFIDENCE': self.ui.chat_show_confidence,
            'CHAT_SHOW_CITATIONS': self.ui.chat_show_citations,
            'CHAT_SHOW_TRACE': self.ui.chat_show_trace,
            'CHAT_SHOW_DEBUG_FOOTER': self.ui.chat_show_debug_footer,
            'CHAT_DEFAULT_MODEL': self.ui.chat_default_model,
            'CHAT_STREAM_TIMEOUT': self.ui.chat_stream_timeout,
            'CHAT_THINKING_BUDGET_TOKENS': self.ui.chat_thinking_budget_tokens,
            'EDITOR_PORT': self.ui.editor_port,
            'GRAFANA_DASHBOARD_UID': self.ui.grafana_dashboard_uid,
            'GRAFANA_DASHBOARD_SLUG': self.ui.grafana_dashboard_slug,
            'GRAFANA_BASE_URL': self.ui.grafana_base_url,
            'GRAFANA_AUTH_MODE': self.ui.grafana_auth_mode,
            'GRAFANA_EMBED_ENABLED': self.ui.grafana_embed_enabled,
            'GRAFANA_KIOSK': self.ui.grafana_kiosk,
            'GRAFANA_ORG_ID': self.ui.grafana_org_id,
            'GRAFANA_REFRESH': self.ui.grafana_refresh,
            'EDITOR_BIND': self.ui.editor_bind,
            'EDITOR_EMBED_ENABLED': self.ui.editor_embed_enabled,
            'EDITOR_ENABLED': self.ui.editor_enabled,
            'EDITOR_IMAGE': self.ui.editor_image,
            'THEME_MODE': self.ui.theme_mode,
            'OPEN_BROWSER': self.ui.open_browser,
            'RUNTIME_MODE': self.ui.runtime_mode,
            'LEARNING_RERANKER_STUDIO_V2_ENABLED': self.ui.learning_reranker_studio_v2_enabled,
            'LEARNING_RERANKER_STUDIO_IMMERSIVE': self.ui.learning_reranker_studio_immersive,
            'LEARNING_RERANKER_LAYOUT_ENGINE': self.ui.learning_reranker_layout_engine,
            'LEARNING_RERANKER_DEFAULT_PRESET': self.ui.learning_reranker_default_preset,
            'LEARNING_RERANKER_SHOW_SETUP_ROW': self.ui.learning_reranker_show_setup_row,
            'LEARNING_RERANKER_LOGS_RENDERER': self.ui.learning_reranker_logs_renderer,
            'LEARNING_RERANKER_DOCKVIEW_LAYOUT_JSON': self.ui.learning_reranker_dockview_layout_json,
            'LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT': self.ui.learning_reranker_studio_left_panel_pct,
            'LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT': self.ui.learning_reranker_studio_right_panel_pct,
            'LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT': self.ui.learning_reranker_studio_bottom_panel_pct,
            'LEARNING_RERANKER_VISUALIZER_RENDERER': self.ui.learning_reranker_visualizer_renderer,
            'LEARNING_RERANKER_VISUALIZER_QUALITY': self.ui.learning_reranker_visualizer_quality,
            'LEARNING_RERANKER_VISUALIZER_COLOR_MODE': self.ui.learning_reranker_visualizer_color_mode,
            'LEARNING_RERANKER_VISUALIZER_MAX_POINTS': self.ui.learning_reranker_visualizer_max_points,
            'LEARNING_RERANKER_VISUALIZER_TARGET_FPS': self.ui.learning_reranker_visualizer_target_fps,
            'LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS': self.ui.learning_reranker_visualizer_tail_seconds,
            'LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY': self.ui.learning_reranker_visualizer_motion_intensity,
            'LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD': self.ui.learning_reranker_visualizer_show_vector_field,
            'LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION': self.ui.learning_reranker_visualizer_reduce_motion,
            # Hydration params (2)
            'HYDRATION_MODE': self.hydration.hydration_mode,
            'HYDRATION_MAX_CHARS': self.hydration.hydration_max_chars,
            # Evaluation params (3)
            'EVAL_DATASET_PATH': self.evaluation.eval_dataset_path,
            'BASELINE_PATH': self.evaluation.baseline_path,
            'EVAL_MULTI_M': self.evaluation.eval_multi_m,
            # System prompts (9)
            'PROMPT_MAIN_RAG_CHAT': self.system_prompts.main_rag_chat,
            'PROMPT_QUERY_EXPANSION': self.system_prompts.query_expansion,
            'PROMPT_QUERY_REWRITE': self.system_prompts.query_rewrite,
            'PROMPT_SEMANTIC_CARDS': self.system_prompts.semantic_chunk_summaries,
            'PROMPT_CODE_ENRICHMENT': self.system_prompts.code_enrichment,
            'PROMPT_SEMANTIC_KG_EXTRACTION': self.system_prompts.semantic_kg_extraction,
            'PROMPT_EVAL_ANALYSIS': self.system_prompts.eval_analysis,
            'PROMPT_LIGHTWEIGHT_CARDS': self.system_prompts.lightweight_chunk_summaries,
            'PROMPT_SYNTHETIC_JUDGE': self.system_prompts.synthetic_judge,
            # MCP (inbound) params (7)
            'MCP_HTTP_ENABLED': self.mcp.enabled,
            'MCP_HTTP_PATH': self.mcp.mount_path,
            'MCP_HTTP_STATELESS': self.mcp.stateless_http,
            'MCP_HTTP_JSON_RESPONSE': self.mcp.json_response,
            'MCP_HTTP_DNS_REBIND_PROTECTION': self.mcp.enable_dns_rebinding_protection,
            'MCP_HTTP_ALLOWED_HOSTS': ",".join(self.mcp.allowed_hosts),
            'MCP_HTTP_ALLOWED_ORIGINS': ",".join(self.mcp.allowed_origins),
            'MCP_REQUIRE_API_KEY': self.mcp.require_api_key,
            'MCP_DEFAULT_TOP_K': self.mcp.default_top_k,
            'MCP_DEFAULT_MODE': self.mcp.default_mode,
            # Local Docker diagnostics and scoped service-control params (7)
            'DOCKER_STATUS_TIMEOUT': self.docker.docker_status_timeout,
            'DOCKER_CONTAINER_LIST_TIMEOUT': self.docker.docker_container_list_timeout,
            'DOCKER_CONTAINER_ACTION_TIMEOUT': self.docker.docker_container_action_timeout,
            'DOCKER_LOGS_TAIL': self.docker.docker_logs_tail,
            'DOCKER_LOGS_TIMESTAMPS': self.docker.docker_logs_timestamps,
            'DEV_FRONTEND_PORT': self.docker.dev_frontend_port,
            'DEV_BACKEND_PORT': self.docker.dev_backend_port,
        }

    def to_env_dict(self) -> dict[str, Any]:
        """Alias for to_flat_dict() (env-style compatibility)."""
        return self.to_flat_dict()

    @classmethod
    def from_flat_dict(cls, data: dict[str, Any]) -> TriBridConfig:
        """Create config from flat env-style dict.

        This allows the API to receive updates in the traditional flat format
        and convert them to the nested structure for storage.

        Args:
            data: Flat dictionary with env-style keys

        Returns:
            TriBridConfig instance with nested structure
        """
        def _parse_csv_list(raw: Any, default: list[str]) -> list[str]:
            if isinstance(raw, list):
                out = [str(x).strip() for x in raw if str(x).strip()]
                return out or list(default)
            if isinstance(raw, str):
                out = [x.strip() for x in raw.split(",") if x.strip()]
                return out or list(default)
            return list(default)

        return cls(
            retrieval=RetrievalConfig(
                rrf_k_div=data.get('RRF_K_DIV', 60),
                langgraph_final_k=data.get('LANGGRAPH_FINAL_K', 20),
                max_query_rewrites=data.get('MAX_QUERY_REWRITES', data.get('MQ_REWRITES', 2)),
                langgraph_max_query_rewrites=data.get(
                    'LANGGRAPH_MAX_QUERY_REWRITES',
                    data.get('MAX_QUERY_REWRITES', data.get('MQ_REWRITES', 2))
                ),
                fallback_confidence=data.get('FALLBACK_CONFIDENCE', 0.55),
                final_k=data.get('FINAL_K', 10),
                eval_final_k=data.get('EVAL_FINAL_K', 5),
                conf_top1=data.get('CONF_TOP1', 0.62),
                conf_avg5=data.get('CONF_AVG5', 0.55),
                conf_any=data.get('CONF_ANY', 0.55),
                eval_multi=data.get('EVAL_MULTI', 1),
                query_expansion_enabled=data.get('QUERY_EXPANSION_ENABLED', 1),
                bm25_weight=data.get('BM25_WEIGHT', 0.3),
                bm25_k1=data.get('BM25_K1', 1.2),
                bm25_b=data.get('BM25_B', 0.4),
                vector_weight=data.get('VECTOR_WEIGHT', 0.7),
                chunk_summary_search_enabled=data.get('CHUNK_SUMMARY_SEARCH_ENABLED', 1),
                multi_query_m=data.get('MULTI_QUERY_M', 4),
                use_semantic_synonyms=data.get('USE_SEMANTIC_SYNONYMS', 1),
                tribrid_synonyms_path=data.get('TRIBRID_SYNONYMS_PATH', ''),
                topk_dense=data.get('TOPK_DENSE', 75),
                topk_sparse=data.get('TOPK_SPARSE', 75),
                hydration_mode=data.get('HYDRATION_MODE', 'lazy'),
                hydration_max_chars=data.get('HYDRATION_MAX_CHARS', 2000),
                # REMOVED: disable_rerank - use RERANKER_MODE='none' instead
            ),
            semantic_cache=SemanticCacheConfig(
                enabled=data.get('SEMANTIC_CACHE_ENABLED', 0),
                mode=data.get('SEMANTIC_CACHE_MODE', 'read_write'),
                max_entries=data.get('SEMANTIC_CACHE_MAX_ENTRIES', 5000),
                min_query_chars=data.get('SEMANTIC_CACHE_MIN_QUERY_CHARS', 3),
                similarity_threshold_search=data.get('SEMANTIC_CACHE_THRESHOLD_SEARCH', 0.90),
                similarity_threshold_answer=data.get('SEMANTIC_CACHE_THRESHOLD_ANSWER', 0.93),
                similarity_threshold_chat=data.get('SEMANTIC_CACHE_THRESHOLD_CHAT', 0.95),
                ttl_seconds_search=data.get('SEMANTIC_CACHE_TTL_SEARCH_SEC', 900),
                ttl_seconds_answer=data.get('SEMANTIC_CACHE_TTL_ANSWER_SEC', 1800),
                ttl_seconds_chat=data.get('SEMANTIC_CACHE_TTL_CHAT_SEC', 600),
                chat_history_window=data.get('SEMANTIC_CACHE_CHAT_HISTORY_WINDOW', 6),
                bypass_if_images=data.get('SEMANTIC_CACHE_BYPASS_IF_IMAGES', 1),
                max_temperature_for_write=data.get('SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE', 0.5),
            ),
            scoring=ScoringConfig(
                chunk_summary_bonus=data.get('CHUNK_SUMMARY_BONUS', 0.08),
                filename_boost_exact=data.get('FILENAME_BOOST_EXACT', 1.5),
                filename_boost_partial=data.get('FILENAME_BOOST_PARTIAL', 1.2),
                vendor_mode=data.get('VENDOR_MODE', 'prefer_first_party'),
                path_boosts=data.get('PATH_BOOSTS', '/gui,/server,/indexer,/retrieval'),
            ),
            layer_bonus=LayerBonusConfig(
                gui=data.get('LAYER_BONUS_GUI', 0.15),
                retrieval=data.get('LAYER_BONUS_RETRIEVAL', 0.15),
                indexer=data.get('LAYER_BONUS_INDEXER', 0.15),
                vendor_penalty=data.get('VENDOR_PENALTY', -0.1),
                freshness_bonus=data.get('FRESHNESS_BONUS', 0.05),
                intent_matrix=data.get('LAYER_INTENT_MATRIX', LayerBonusConfig().intent_matrix),
            ),
            embedding=EmbeddingConfig(
                embedding_type=data.get('EMBEDDING_TYPE', 'openai'),
                embedding_model=data.get('EMBEDDING_MODEL', 'text-embedding-3-large'),
                embedding_dim=data.get('EMBEDDING_DIM', 3072),
                voyage_model=data.get('VOYAGE_MODEL', 'voyage-code-3'),
                embedding_model_local=data.get('EMBEDDING_MODEL_LOCAL', 'all-MiniLM-L6-v2'),
                embedding_model_mlx=data.get('EMBEDDING_MODEL_MLX', 'mlx-community/all-MiniLM-L6-v2-4bit'),
                embedding_batch_size=data.get('EMBEDDING_BATCH_SIZE', 64),
                embedding_max_tokens=data.get('EMBEDDING_MAX_TOKENS', 8000),
                embedding_cache_enabled=data.get('EMBEDDING_CACHE_ENABLED', 1),
                embedding_timeout=data.get('EMBEDDING_TIMEOUT', 30),
                embedding_retry_max=data.get('EMBEDDING_RETRY_MAX', 3),
            ),
            chunking=ChunkingConfig(
                chunk_size=data.get('CHUNK_SIZE', 1000),
                chunk_overlap=data.get('CHUNK_OVERLAP', 200),
                ast_overlap_lines=data.get('AST_OVERLAP_LINES', 20),
                max_indexable_file_size=data.get('MAX_INDEXABLE_FILE_SIZE', 2000000),
                max_chunk_tokens=data.get('MAX_CHUNK_TOKENS', 8000),
                min_chunk_chars=data.get('MIN_CHUNK_CHARS', 50),
                greedy_fallback_target=data.get('GREEDY_FALLBACK_TARGET', 800),
                chunking_strategy=data.get('CHUNKING_STRATEGY', 'ast'),
                preserve_imports=data.get('PRESERVE_IMPORTS', 1),
            ),
            indexing=IndexingConfig(
                postgres_url=data.get('POSTGRES_URL', 'postgresql://postgres:postgres@localhost:5432/tribrid_rag'),
                indexing_batch_size=data.get('INDEXING_BATCH_SIZE', 100),
                indexing_workers=data.get('INDEXING_WORKERS', 4),
                bm25_tokenizer=data.get('BM25_TOKENIZER', 'stemmer'),
                bm25_stemmer_lang=data.get('BM25_STEMMER_LANG', 'english'),
                index_excluded_exts=data.get('INDEX_EXCLUDED_EXTS', '.png,.jpg,.gif,.ico,.svg,.woff,.ttf'),
                index_max_file_size_mb=data.get('INDEX_MAX_FILE_SIZE_MB', 250),
                parquet_extract_max_rows=data.get('PARQUET_EXTRACT_MAX_ROWS', 5000),
                parquet_extract_max_chars=data.get('PARQUET_EXTRACT_MAX_CHARS', 2_000_000),
                parquet_extract_max_cell_chars=data.get('PARQUET_EXTRACT_MAX_CELL_CHARS', 20_000),
                parquet_extract_text_columns_only=data.get('PARQUET_EXTRACT_TEXT_COLUMNS_ONLY', 1),
                parquet_extract_include_column_names=data.get('PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES', 1),
                skip_dense=data.get('SKIP_DENSE', 0),
                auto_prepare_dense_retrieval=data.get('AUTO_PREPARE_DENSE_RETRIEVAL', True),
                estimated_tokens_per_second_local=data.get('ESTIMATED_TOKENS_PER_SECOND_LOCAL', None),
            ),
            graph_storage=GraphStorageConfig(
                neo4j_uri=data.get('NEO4J_URI', 'bolt://localhost:7687'),
                neo4j_user=data.get('NEO4J_USER', 'neo4j'),
                neo4j_database=data.get('NEO4J_DATABASE', 'neo4j'),
                neo4j_vector_query_mode=data.get('NEO4J_VECTOR_QUERY_MODE', 'auto'),
                max_hops=data.get('GRAPH_MAX_HOPS', 2),
                include_communities=data.get('GRAPH_INCLUDE_COMMUNITIES', True),
                community_algorithm=data.get('GRAPH_COMMUNITY_ALGORITHM', 'louvain'),
                entity_types=data.get('GRAPH_ENTITY_TYPES', 'function,class,module,variable,import').split(','),
                relationship_types=data.get('GRAPH_RELATIONSHIP_TYPES', 'calls,imports,inherits,contains,references').split(','),
                graph_search_top_k=data.get('GRAPH_SEARCH_TOP_K', 30),
            ),
            fusion=FusionConfig(
                method=data.get('FUSION_METHOD', 'rrf'),
                vector_weight=data.get('FUSION_VECTOR_WEIGHT', 0.4),
                sparse_weight=data.get('FUSION_SPARSE_WEIGHT', 0.3),
                graph_weight=data.get('FUSION_GRAPH_WEIGHT', 0.3),
                rrf_k=data.get('FUSION_RRF_K', 60),
                normalize_scores=data.get('FUSION_NORMALIZE_SCORES', True),
            ),
            reranking=RerankingConfig(
                # Unified RERANKER_MODE with backwards compat fallback to old keys
                reranker_mode=data.get('RERANKER_MODE') or data.get('RERANKER_ACTIVE') or data.get('RERANKER_BACKEND') or 'none',
                reranker_cloud_provider=data.get('RERANKER_CLOUD_PROVIDER') or data.get('RERANKER_PROVIDER') or 'cohere',
                reranker_cloud_model=data.get('RERANKER_CLOUD_MODEL') or data.get('COHERE_RERANK_MODEL') or 'rerank-v3.5',
                tribrid_reranker_alpha=data.get('TRIBRID_RERANKER_ALPHA', 0.7),
                tribrid_reranker_topn=data.get('TRIBRID_RERANKER_TOPN', 50),
                reranker_cloud_top_n=data.get('RERANKER_CLOUD_TOP_N', 50),
                tribrid_reranker_batch=data.get('TRIBRID_RERANKER_BATCH', 16),
                tribrid_reranker_maxlen=data.get('TRIBRID_RERANKER_MAXLEN', 512),
                tribrid_reranker_reload_on_change=data.get('TRIBRID_RERANKER_RELOAD_ON_CHANGE', 0),
                tribrid_reranker_reload_period_sec=data.get('TRIBRID_RERANKER_RELOAD_PERIOD_SEC', 60),
                reranker_timeout=data.get('RERANKER_TIMEOUT', 10),
                rerank_input_snippet_chars=data.get('RERANK_INPUT_SNIPPET_CHARS', 700),
            ),
            generation=GenerationConfig(
                gen_model=data.get('GEN_MODEL', 'gpt-4o-mini'),
                gen_temperature=data.get('GEN_TEMPERATURE', 0.0),
                gen_max_tokens=data.get('GEN_MAX_TOKENS', 2048),
                gen_top_p=data.get('GEN_TOP_P', 1.0),
                gen_timeout=data.get('GEN_TIMEOUT', 60),
                gen_retry_max=data.get('GEN_RETRY_MAX', 2),
                gen_backend=data.get('GEN_BACKEND', 'openai'),
                enrich_model=data.get('ENRICH_MODEL', 'gpt-4o-mini'),
                enrich_backend=data.get('ENRICH_BACKEND', 'openai'),
                enrich_disabled=data.get('ENRICH_DISABLED', 0),
                ollama_num_ctx=data.get('OLLAMA_NUM_CTX', 8192),
                ollama_request_timeout=data.get('OLLAMA_REQUEST_TIMEOUT', 300),
                ollama_stream_idle_timeout=data.get('OLLAMA_STREAM_IDLE_TIMEOUT', 60),
                gen_model_cli=data.get('GEN_MODEL_CLI', 'qwen3-coder:14b'),
                gen_model_ollama=data.get('GEN_MODEL_OLLAMA', 'qwen3-coder:30b'),
                gen_model_http=data.get('GEN_MODEL_HTTP', ''),
                gen_model_mcp=data.get('GEN_MODEL_MCP', ''),
                enrich_model_ollama=data.get('ENRICH_MODEL_OLLAMA', ''),
                ollama_url=data.get('OLLAMA_URL', 'http://127.0.0.1:11434/api'),
                openai_base_url=data.get('OPENAI_BASE_URL', ''),
            ),
            enrichment=EnrichmentConfig(
                chunk_summaries_enrich_default=data.get('CHUNK_SUMMARIES_ENRICH_DEFAULT', 1),
                chunk_summaries_max=data.get('CHUNK_SUMMARIES_MAX', 100),
                enrich_code_chunks=data.get('ENRICH_CODE_CHUNKS', 1),
                enrich_min_chars=data.get('ENRICH_MIN_CHARS', 50),
                enrich_max_chars=data.get('ENRICH_MAX_CHARS', 1000),
                enrich_timeout=data.get('ENRICH_TIMEOUT', 30),
            ),
            chunk_summaries=ChunkSummaryConfig(
                exclude_dirs=data.get('CHUNK_SUMMARIES_EXCLUDE_DIRS', ChunkSummaryConfig().exclude_dirs),
                exclude_patterns=data.get('CHUNK_SUMMARIES_EXCLUDE_PATTERNS', []),
                exclude_keywords=data.get('CHUNK_SUMMARIES_EXCLUDE_KEYWORDS', []),
                code_snippet_length=data.get('CHUNK_SUMMARIES_CODE_SNIPPET_LENGTH', 2000),
                max_symbols=data.get('CHUNK_SUMMARIES_MAX_SYMBOLS', 5),
                max_routes=data.get('CHUNK_SUMMARIES_MAX_ROUTES', 5),
                purpose_max_length=data.get('CHUNK_SUMMARIES_PURPOSE_MAX_LENGTH', 240),
                quick_tips=data.get('CHUNK_SUMMARIES_QUICK_TIPS', []),
            ),
            keywords=KeywordsConfig(
                keywords_max_per_repo=data.get('KEYWORDS_MAX_PER_REPO', 50),
                keywords_min_freq=data.get('KEYWORDS_MIN_FREQ', 3),
                keywords_boost=data.get('KEYWORDS_BOOST', 1.3),
                keywords_auto_generate=data.get('KEYWORDS_AUTO_GENERATE', 1),
                keywords_refresh_hours=data.get('KEYWORDS_REFRESH_HOURS', 24),
            ),
            tracing=TracingConfig(
                tracing_enabled=data.get('TRACING_ENABLED', 1),
                trace_sampling_rate=data.get('TRACE_SAMPLING_RATE', 1.0),
                prometheus_port=data.get('PROMETHEUS_PORT', 9090),
                metrics_enabled=data.get('METRICS_ENABLED', 1),
                alert_include_resolved=data.get('ALERT_INCLUDE_RESOLVED', 1),
                alert_webhook_timeout=data.get('ALERT_WEBHOOK_TIMEOUT', 5),
                log_level=data.get('LOG_LEVEL', 'INFO'),
                tracing_mode=data.get('TRACING_MODE', 'local'),
                trace_retention=data.get('TRACE_RETENTION', 50),
                tribrid_log_path=data.get('TRIBRID_LOG_PATH', 'data/logs/queries.jsonl'),
                alert_notify_severities=data.get('ALERT_NOTIFY_SEVERITIES', 'critical,warning'),
                otel_export_enabled=data.get('OTEL_EXPORT_ENABLED', 1),
                otlp_endpoint=data.get('OTLP_ENDPOINT', ''),
                otlp_headers=data.get('OTLP_HEADERS', ''),
                otel_service_name=data.get('OTEL_SERVICE_NAME', 'ragweld-api'),
                langfuse_enabled=data.get('LANGFUSE_ENABLED', 0),
                langfuse_base_url=data.get('LANGFUSE_BASE_URL', ''),
                langfuse_project=data.get('LANGFUSE_PROJECT', 'ragweld'),
                tempo_base_url=data.get('TEMPO_BASE_URL', ''),
                alloy_base_url=data.get('ALLOY_BASE_URL', ''),
                mimir_base_url=data.get('MIMIR_BASE_URL', ''),
                pyroscope_base_url=data.get('PYROSCOPE_BASE_URL', ''),
                faro_base_url=data.get('FARO_BASE_URL', ''),
                opencost_base_url=data.get('OPENCOST_BASE_URL', ''),
                alertmanager_base_url=data.get('ALERTMANAGER_BASE_URL', ''),
                cost_tracking_enabled=data.get('COST_TRACKING_ENABLED', 1),
            ),
            training=TrainingConfig(
                reranker_train_epochs=data.get('RERANKER_TRAIN_EPOCHS', 2),
                reranker_train_batch=data.get('RERANKER_TRAIN_BATCH', 16),
                reranker_train_lr=data.get('RERANKER_TRAIN_LR', 2e-5),
                reranker_warmup_ratio=data.get('RERANKER_WARMUP_RATIO', 0.1),
                triplets_min_count=data.get('TRIPLETS_MIN_COUNT', 100),
                triplets_mine_mode=data.get('TRIPLETS_MINE_MODE', 'replace'),
                tribrid_reranker_model_path=data.get('TRIBRID_RERANKER_MODEL_PATH', 'models/learning-reranker-active'),
                tribrid_reranker_mine_mode=data.get('TRIBRID_RERANKER_MINE_MODE', 'replace'),
                tribrid_reranker_mine_reset=data.get('TRIBRID_RERANKER_MINE_RESET', 0),
                tribrid_triplets_path=data.get('TRIBRID_TRIPLETS_PATH', 'data/training/triplets.jsonl'),
                learning_reranker_backend=data.get('LEARNING_RERANKER_BACKEND', 'auto'),
                learning_reranker_base_model=data.get('LEARNING_RERANKER_BASE_MODEL', 'Qwen/Qwen3-Reranker-0.6B'),
                learning_reranker_lora_rank=data.get('LEARNING_RERANKER_LORA_RANK', 16),
                learning_reranker_lora_alpha=data.get('LEARNING_RERANKER_LORA_ALPHA', 32.0),
                learning_reranker_lora_dropout=data.get('LEARNING_RERANKER_LORA_DROPOUT', 0.05),
                learning_reranker_lora_target_modules=_parse_csv_list(
                    data.get('LEARNING_RERANKER_LORA_TARGET_MODULES'),
                    ["q_proj", "k_proj", "v_proj", "o_proj"],
                ),
                learning_reranker_negative_ratio=data.get('LEARNING_RERANKER_NEGATIVE_RATIO', 5),
                learning_reranker_grad_accum_steps=data.get('LEARNING_RERANKER_GRAD_ACCUM_STEPS', 8),
                learning_reranker_promote_if_improves=data.get('LEARNING_RERANKER_PROMOTE_IF_IMPROVES', 1),
                learning_reranker_promote_epsilon=data.get('LEARNING_RERANKER_PROMOTE_EPSILON', 0.0),
                learning_reranker_unload_after_sec=data.get('LEARNING_RERANKER_UNLOAD_AFTER_SEC', 0),
                learning_reranker_telemetry_interval_steps=data.get('LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS', 2),
                ragweld_agent_backend=data.get('RAGWELD_AGENT_BACKEND', 'mlx_qwen3'),
                ragweld_agent_workflow_backend=data.get('RAGWELD_AGENT_WORKFLOW_BACKEND', 'local'),
                ragweld_agent_tracking_backend=data.get('RAGWELD_AGENT_TRACKING_BACKEND', 'local'),
                ragweld_agent_base_model=data.get('RAGWELD_AGENT_BASE_MODEL', 'mlx-community/Qwen3-1.7B-4bit'),
                ragweld_agent_model_path=data.get('RAGWELD_AGENT_MODEL_PATH', 'models/learning-agent-active'),
                ragweld_agent_unload_after_sec=data.get('RAGWELD_AGENT_UNLOAD_AFTER_SEC', 0),
                ragweld_agent_reload_period_sec=data.get('RAGWELD_AGENT_RELOAD_PERIOD_SEC', 60),
                ragweld_agent_train_dataset_path=data.get('RAGWELD_AGENT_TRAIN_DATASET_PATH', ''),
                ragweld_agent_lora_rank=data.get('RAGWELD_AGENT_LORA_RANK', 16),
                ragweld_agent_lora_alpha=data.get('RAGWELD_AGENT_LORA_ALPHA', 32.0),
                ragweld_agent_lora_dropout=data.get('RAGWELD_AGENT_LORA_DROPOUT', 0.05),
                ragweld_agent_lora_target_modules=_parse_csv_list(
                    data.get('RAGWELD_AGENT_LORA_TARGET_MODULES'),
                    ["q_proj", "k_proj", "v_proj", "o_proj"],
                ),
                ragweld_agent_grad_accum_steps=data.get('RAGWELD_AGENT_GRAD_ACCUM_STEPS', 8),
                ragweld_agent_telemetry_interval_steps=data.get('RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS', 2),
                ragweld_agent_promote_if_improves=data.get('RAGWELD_AGENT_PROMOTE_IF_IMPROVES', 1),
                ragweld_agent_promote_epsilon=data.get('RAGWELD_AGENT_PROMOTE_EPSILON', 0.0),
                ragweld_agent_flyte_admin_base_url=data.get('RAGWELD_AGENT_FLYTE_ADMIN_BASE_URL', ''),
                ragweld_agent_flyte_console_base_url=data.get('RAGWELD_AGENT_FLYTE_CONSOLE_BASE_URL', ''),
                ragweld_agent_flyte_project=data.get('RAGWELD_AGENT_FLYTE_PROJECT', 'ragweld'),
                ragweld_agent_flyte_domain=data.get('RAGWELD_AGENT_FLYTE_DOMAIN', 'development'),
                ragweld_agent_flyte_launchplan=data.get('RAGWELD_AGENT_FLYTE_LAUNCHPLAN', ''),
                ragweld_agent_mlflow_tracking_url=data.get('RAGWELD_AGENT_MLFLOW_TRACKING_URL', ''),
                ragweld_agent_mlflow_experiment_name=data.get('RAGWELD_AGENT_MLFLOW_EXPERIMENT_NAME', 'ragweld-learning-agent'),
                ragweld_agent_unsloth_image=data.get('RAGWELD_AGENT_UNSLOTH_IMAGE', ''),
            ),
            ui=UIConfig(
                chat_streaming_enabled=data.get('CHAT_STREAMING_ENABLED', 1),
                chat_history_max=data.get('CHAT_HISTORY_MAX', 50),
                chat_stream_include_thinking=data.get('CHAT_STREAM_INCLUDE_THINKING', 1),
                chat_show_confidence=data.get('CHAT_SHOW_CONFIDENCE', 0),
                chat_show_citations=data.get('CHAT_SHOW_CITATIONS', 1),
                chat_show_trace=data.get('CHAT_SHOW_TRACE', 1),
                chat_show_debug_footer=data.get('CHAT_SHOW_DEBUG_FOOTER', 1),
                chat_default_model=data.get('CHAT_DEFAULT_MODEL', 'gpt-4o-mini'),
                chat_stream_timeout=data.get('CHAT_STREAM_TIMEOUT', 120),
                chat_thinking_budget_tokens=data.get('CHAT_THINKING_BUDGET_TOKENS', 10000),
                editor_port=data.get('EDITOR_PORT', 4440),
                grafana_dashboard_uid=data.get('GRAFANA_DASHBOARD_UID', 'ragweld-oncall-overview'),
                grafana_dashboard_slug=data.get('GRAFANA_DASHBOARD_SLUG', 'on-call-overview'),
                grafana_base_url=data.get('GRAFANA_BASE_URL', 'http://127.0.0.1:3301'),
                grafana_auth_mode=data.get('GRAFANA_AUTH_MODE', 'anonymous'),
                grafana_embed_enabled=data.get('GRAFANA_EMBED_ENABLED', 1),
                grafana_kiosk=data.get('GRAFANA_KIOSK', 'tv'),
                grafana_org_id=data.get('GRAFANA_ORG_ID', 1),
                grafana_refresh=data.get('GRAFANA_REFRESH', '10s'),
                editor_bind=data.get('EDITOR_BIND', 'local'),
                editor_embed_enabled=data.get('EDITOR_EMBED_ENABLED', 1),
                editor_enabled=data.get('EDITOR_ENABLED', 1),
                editor_image=data.get('EDITOR_IMAGE', 'codercom/code-server:latest'),
                theme_mode=data.get('THEME_MODE', 'dark'),
                open_browser=data.get('OPEN_BROWSER', 1),
                runtime_mode=data.get('RUNTIME_MODE', 'development'),
                learning_reranker_studio_v2_enabled=data.get('LEARNING_RERANKER_STUDIO_V2_ENABLED', 1),
                learning_reranker_studio_immersive=data.get('LEARNING_RERANKER_STUDIO_IMMERSIVE', 1),
                learning_reranker_layout_engine=data.get('LEARNING_RERANKER_LAYOUT_ENGINE', 'dockview'),
                learning_reranker_default_preset=data.get('LEARNING_RERANKER_DEFAULT_PRESET', 'balanced'),
                learning_reranker_show_setup_row=data.get('LEARNING_RERANKER_SHOW_SETUP_ROW', 0),
                learning_reranker_logs_renderer=data.get('LEARNING_RERANKER_LOGS_RENDERER', 'xterm'),
                learning_reranker_dockview_layout_json=data.get('LEARNING_RERANKER_DOCKVIEW_LAYOUT_JSON', ''),
                learning_reranker_studio_left_panel_pct=data.get('LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT', 20),
                learning_reranker_studio_right_panel_pct=data.get('LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT', 30),
                learning_reranker_studio_bottom_panel_pct=data.get('LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT', 28),
                learning_reranker_visualizer_renderer=data.get('LEARNING_RERANKER_VISUALIZER_RENDERER', 'auto'),
                learning_reranker_visualizer_quality=data.get('LEARNING_RERANKER_VISUALIZER_QUALITY', 'cinematic'),
                learning_reranker_visualizer_color_mode=data.get('LEARNING_RERANKER_VISUALIZER_COLOR_MODE', 'absolute'),
                learning_reranker_visualizer_max_points=data.get('LEARNING_RERANKER_VISUALIZER_MAX_POINTS', 10000),
                learning_reranker_visualizer_target_fps=data.get('LEARNING_RERANKER_VISUALIZER_TARGET_FPS', 60),
                learning_reranker_visualizer_tail_seconds=data.get('LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS', 8.0),
                learning_reranker_visualizer_motion_intensity=data.get(
                    'LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY', 1.0
                ),
                learning_reranker_visualizer_show_vector_field=data.get(
                    'LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD', 1
                ),
                learning_reranker_visualizer_reduce_motion=data.get(
                    'LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION', 0
                ),
            ),
            hydration=HydrationConfig(
                hydration_mode=data.get('HYDRATION_MODE', 'lazy'),
                hydration_max_chars=data.get('HYDRATION_MAX_CHARS', 2000),
            ),
            evaluation=EvaluationConfig(
                eval_dataset_path=data.get('EVAL_DATASET_PATH', 'data/evaluation_dataset.json'),
                baseline_path=data.get('BASELINE_PATH', 'data/evals/eval_baseline.json'),
                eval_multi_m=data.get('EVAL_MULTI_M', 10),
            ),
            system_prompts=SystemPromptsConfig(
                main_rag_chat=data.get('PROMPT_MAIN_RAG_CHAT', SystemPromptsConfig().main_rag_chat),
                query_expansion=data.get('PROMPT_QUERY_EXPANSION', SystemPromptsConfig().query_expansion),
                query_rewrite=data.get('PROMPT_QUERY_REWRITE', SystemPromptsConfig().query_rewrite),
                semantic_chunk_summaries=data.get('PROMPT_SEMANTIC_CARDS', SystemPromptsConfig().semantic_chunk_summaries),
                code_enrichment=data.get('PROMPT_CODE_ENRICHMENT', SystemPromptsConfig().code_enrichment),
                semantic_kg_extraction=data.get(
                    'PROMPT_SEMANTIC_KG_EXTRACTION', SystemPromptsConfig().semantic_kg_extraction
                ),
                eval_analysis=data.get('PROMPT_EVAL_ANALYSIS', SystemPromptsConfig().eval_analysis),
                lightweight_chunk_summaries=data.get('PROMPT_LIGHTWEIGHT_CARDS', SystemPromptsConfig().lightweight_chunk_summaries),
                synthetic_judge=data.get('PROMPT_SYNTHETIC_JUDGE', SystemPromptsConfig().synthetic_judge),
            ),
            mcp=MCPConfig(
                enabled=data.get('MCP_HTTP_ENABLED', MCPConfig().enabled),
                mount_path=data.get('MCP_HTTP_PATH', MCPConfig().mount_path),
                stateless_http=data.get('MCP_HTTP_STATELESS', MCPConfig().stateless_http),
                json_response=data.get('MCP_HTTP_JSON_RESPONSE', MCPConfig().json_response),
                enable_dns_rebinding_protection=data.get(
                    'MCP_HTTP_DNS_REBIND_PROTECTION', MCPConfig().enable_dns_rebinding_protection
                ),
                allowed_hosts=data.get('MCP_HTTP_ALLOWED_HOSTS', MCPConfig().allowed_hosts),
                allowed_origins=data.get('MCP_HTTP_ALLOWED_ORIGINS', MCPConfig().allowed_origins),
                require_api_key=data.get('MCP_REQUIRE_API_KEY', MCPConfig().require_api_key),
                default_top_k=data.get('MCP_DEFAULT_TOP_K', MCPConfig().default_top_k),
                default_mode=data.get('MCP_DEFAULT_MODE', MCPConfig().default_mode),
            ),
            docker=DockerConfig(
                docker_status_timeout=data.get('DOCKER_STATUS_TIMEOUT', 5),
                docker_container_list_timeout=data.get('DOCKER_CONTAINER_LIST_TIMEOUT', 10),
                docker_container_action_timeout=data.get('DOCKER_CONTAINER_ACTION_TIMEOUT', 30),
                docker_logs_tail=data.get('DOCKER_LOGS_TAIL', 100),
                docker_logs_timestamps=data.get('DOCKER_LOGS_TIMESTAMPS', 1),
                dev_frontend_port=data.get('DEV_FRONTEND_PORT', 55173),
                dev_backend_port=data.get('DEV_BACKEND_PORT', 58012),
            ),
        )

    @classmethod
    def from_env(cls) -> TriBridConfig:
        """Create config from process environment variables (best-effort)."""
        import os

        return cls.from_flat_dict(dict(os.environ))


# Default config instance for easy access
DEFAULT_CONFIG = TriBridConfig()

# Set of keys that belong in tribrid_config.json (not .env)
TRIBRID_CONFIG_KEYS = {
    # Retrieval params (22 - including MQ_REWRITES alias)
    'RRF_K_DIV',
    'LANGGRAPH_FINAL_K',
    'LANGGRAPH_MAX_QUERY_REWRITES',
    'MAX_QUERY_REWRITES',
    'MQ_REWRITES',  # Legacy alias for MAX_QUERY_REWRITES
    'FALLBACK_CONFIDENCE',
    'FINAL_K',
    'EVAL_FINAL_K',
    'CONF_TOP1',
    'CONF_AVG5',
    'CONF_ANY',
    'EVAL_MULTI',
    'QUERY_EXPANSION_ENABLED',
    'BM25_WEIGHT',
    'BM25_K1',
    'BM25_B',
    'VECTOR_WEIGHT',
    'CHUNK_SUMMARY_SEARCH_ENABLED',
    'MULTI_QUERY_M',
    'USE_SEMANTIC_SYNONYMS',
    'TRIBRID_SYNONYMS_PATH',
    'TOPK_DENSE',
    'TOPK_SPARSE',
    'HYDRATION_MODE',
    'HYDRATION_MAX_CHARS',
    # Semantic cache params (13)
    'SEMANTIC_CACHE_ENABLED',
    'SEMANTIC_CACHE_MODE',
    'SEMANTIC_CACHE_MAX_ENTRIES',
    'SEMANTIC_CACHE_MIN_QUERY_CHARS',
    'SEMANTIC_CACHE_THRESHOLD_SEARCH',
    'SEMANTIC_CACHE_THRESHOLD_ANSWER',
    'SEMANTIC_CACHE_THRESHOLD_CHAT',
    'SEMANTIC_CACHE_TTL_SEARCH_SEC',
    'SEMANTIC_CACHE_TTL_ANSWER_SEC',
    'SEMANTIC_CACHE_TTL_CHAT_SEC',
    'SEMANTIC_CACHE_CHAT_HISTORY_WINDOW',
    'SEMANTIC_CACHE_BYPASS_IF_IMAGES',
    'SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE',
    # REMOVED: DISABLE_RERANK - use RERANKER_MODE='none' instead
    # Scoring params (5 - added 2 new)
    'CHUNK_SUMMARY_BONUS',
    'FILENAME_BOOST_EXACT',
    'FILENAME_BOOST_PARTIAL',
    'VENDOR_MODE',
    'PATH_BOOSTS',
    # Layer bonus params (intent matrix + per-layer bonuses)
    'LAYER_BONUS_GUI',
    'LAYER_BONUS_RETRIEVAL',
    'LAYER_BONUS_INDEXER',
    'VENDOR_PENALTY',
    'FRESHNESS_BONUS',
    'LAYER_INTENT_MATRIX',
    # Embedding params (10)
    'EMBEDDING_TYPE',
    'EMBEDDING_MODEL',
    'EMBEDDING_DIM',
    'VOYAGE_MODEL',
    'EMBEDDING_MODEL_LOCAL',
    'EMBEDDING_BATCH_SIZE',
    'EMBEDDING_MAX_TOKENS',
    'EMBEDDING_CACHE_ENABLED',
    'EMBEDDING_TIMEOUT',
    'EMBEDDING_RETRY_MAX',
    # Chunking params (9)
    'CHUNK_SIZE',
    'CHUNK_OVERLAP',
    'AST_OVERLAP_LINES',
    'MAX_INDEXABLE_FILE_SIZE',
    'MAX_CHUNK_TOKENS',
    'MIN_CHUNK_CHARS',
    'GREEDY_FALLBACK_TARGET',
    'CHUNKING_STRATEGY',
    'PRESERVE_IMPORTS',
    # Indexing params (20)
    'POSTGRES_URL',
    'VECTOR_BACKEND',
    'INDEXING_BATCH_SIZE',
    'INDEXING_WORKERS',
    'BM25_TOKENIZER',
    'BM25_STEMMER_LANG',
    'INDEX_EXCLUDED_EXTS',
    'INDEX_MAX_FILE_SIZE_MB',
    'PARQUET_EXTRACT_MAX_ROWS',
    'PARQUET_EXTRACT_MAX_CHARS',
    'PARQUET_EXTRACT_MAX_CELL_CHARS',
    'PARQUET_EXTRACT_TEXT_COLUMNS_ONLY',
    'PARQUET_EXTRACT_INCLUDE_COLUMN_NAMES',
    'SKIP_DENSE',
    # Reranking params (14) - unified with RERANKER_MODE
    'RERANKER_MODE',
    'RERANKER_CLOUD_PROVIDER',
    'RERANKER_CLOUD_MODEL',
    'TRIBRID_RERANKER_ALPHA',
    'TRIBRID_RERANKER_TOPN',
    'RERANKER_CLOUD_TOP_N',
    'TRIBRID_RERANKER_BATCH',
    'TRIBRID_RERANKER_MAXLEN',
    'TRIBRID_RERANKER_RELOAD_ON_CHANGE',
    'TRIBRID_RERANKER_RELOAD_PERIOD_SEC',
    'RERANKER_TIMEOUT',
    'RERANK_INPUT_SNIPPET_CHARS',
    # Generation params (17)
    'GEN_MODEL',
    'GEN_TEMPERATURE',
    'GEN_MAX_TOKENS',
    'GEN_TOP_P',
    'GEN_TIMEOUT',
    'GEN_RETRY_MAX',
    'ENRICH_MODEL',
    'ENRICH_MODEL_OLLAMA',
    'ENRICH_BACKEND',
    'ENRICH_DISABLED',
    'OLLAMA_NUM_CTX',
    'OLLAMA_URL',
    'OPENAI_BASE_URL',
    'OLLAMA_REQUEST_TIMEOUT',
    'OLLAMA_STREAM_IDLE_TIMEOUT',
    'GEN_MODEL_CLI',
    'GEN_MODEL_HTTP',
    'GEN_MODEL_MCP',
    'GEN_MODEL_OLLAMA',
    # Enrichment params (6)
    'CHUNK_SUMMARIES_ENRICH_DEFAULT',
    'CHUNK_SUMMARIES_MAX',
    'ENRICH_CODE_CHUNKS',
    'ENRICH_MIN_CHARS',
    'ENRICH_MAX_CHARS',
    'ENRICH_TIMEOUT',
    # Chunk summaries filter params (8)
    'CHUNK_SUMMARIES_EXCLUDE_DIRS',
    'CHUNK_SUMMARIES_EXCLUDE_PATTERNS',
    'CHUNK_SUMMARIES_EXCLUDE_KEYWORDS',
    'CHUNK_SUMMARIES_CODE_SNIPPET_LENGTH',
    'CHUNK_SUMMARIES_MAX_SYMBOLS',
    'CHUNK_SUMMARIES_MAX_ROUTES',
    'CHUNK_SUMMARIES_PURPOSE_MAX_LENGTH',
    'CHUNK_SUMMARIES_QUICK_TIPS',
    # Keywords params (5)
    'KEYWORDS_MAX_PER_REPO',
    'KEYWORDS_MIN_FREQ',
    'KEYWORDS_BOOST',
    'KEYWORDS_AUTO_GENERATE',
    'KEYWORDS_REFRESH_HOURS',
    # Tracing params
    'TRACING_ENABLED',
    'TRACE_SAMPLING_RATE',
    'PROMETHEUS_PORT',
    'METRICS_ENABLED',
    'ALERT_INCLUDE_RESOLVED',
    'ALERT_WEBHOOK_TIMEOUT',
    'LOG_LEVEL',
    'TRACING_MODE',
    'TRACE_RETENTION',
    'TRIBRID_LOG_PATH',
    'ALERT_NOTIFY_SEVERITIES',
    'OTEL_EXPORT_ENABLED',
    'OTLP_ENDPOINT',
    'OTLP_HEADERS',
    'OTEL_SERVICE_NAME',
    'LANGFUSE_ENABLED',
    'LANGFUSE_BASE_URL',
    'LANGFUSE_PROJECT',
    'TEMPO_BASE_URL',
    'ALLOY_BASE_URL',
    'COST_TRACKING_ENABLED',
    # Training params (36)
    'RERANKER_TRAIN_EPOCHS',
    'RERANKER_TRAIN_BATCH',
    'RERANKER_TRAIN_LR',
    'RERANKER_WARMUP_RATIO',
    'TRIPLETS_MIN_COUNT',
    'TRIPLETS_MINE_MODE',
    'TRIBRID_RERANKER_MODEL_PATH',
    'TRIBRID_RERANKER_MINE_MODE',
    'TRIBRID_RERANKER_MINE_RESET',
    'TRIBRID_TRIPLETS_PATH',
    'LEARNING_RERANKER_BACKEND',
    'LEARNING_RERANKER_BASE_MODEL',
    'LEARNING_RERANKER_LORA_RANK',
    'LEARNING_RERANKER_LORA_ALPHA',
    'LEARNING_RERANKER_LORA_DROPOUT',
    'LEARNING_RERANKER_LORA_TARGET_MODULES',
    'LEARNING_RERANKER_NEGATIVE_RATIO',
    'LEARNING_RERANKER_GRAD_ACCUM_STEPS',
    'LEARNING_RERANKER_PROMOTE_IF_IMPROVES',
    'LEARNING_RERANKER_PROMOTE_EPSILON',
    'LEARNING_RERANKER_UNLOAD_AFTER_SEC',
    'LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS',
    'RAGWELD_AGENT_BACKEND',
    'RAGWELD_AGENT_BASE_MODEL',
    'RAGWELD_AGENT_MODEL_PATH',
    'RAGWELD_AGENT_UNLOAD_AFTER_SEC',
    'RAGWELD_AGENT_RELOAD_PERIOD_SEC',
    'RAGWELD_AGENT_TRAIN_DATASET_PATH',
    'RAGWELD_AGENT_LORA_RANK',
    'RAGWELD_AGENT_LORA_ALPHA',
    'RAGWELD_AGENT_LORA_DROPOUT',
    'RAGWELD_AGENT_LORA_TARGET_MODULES',
    'RAGWELD_AGENT_GRAD_ACCUM_STEPS',
    'RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS',
    'RAGWELD_AGENT_PROMOTE_IF_IMPROVES',
    'RAGWELD_AGENT_PROMOTE_EPSILON',
    # UI params (39)
    'CHAT_STREAMING_ENABLED',
    'CHAT_HISTORY_MAX',
    'CHAT_STREAM_INCLUDE_THINKING',
    'CHAT_SHOW_CONFIDENCE',
    'CHAT_SHOW_CITATIONS',
    'CHAT_SHOW_TRACE',
    'CHAT_SHOW_DEBUG_FOOTER',
    'CHAT_DEFAULT_MODEL',
    'CHAT_STREAM_TIMEOUT',
    'CHAT_THINKING_BUDGET_TOKENS',
    'EDITOR_PORT',
    'GRAFANA_DASHBOARD_UID',
    'GRAFANA_DASHBOARD_SLUG',
    'GRAFANA_BASE_URL',
    'GRAFANA_AUTH_MODE',
    'GRAFANA_EMBED_ENABLED',
    'GRAFANA_KIOSK',
    'GRAFANA_ORG_ID',
    'GRAFANA_REFRESH',
    'EDITOR_BIND',
    'EDITOR_EMBED_ENABLED',
    'EDITOR_ENABLED',
    'EDITOR_IMAGE',
    'THEME_MODE',
    'OPEN_BROWSER',
    'RUNTIME_MODE',
    'LEARNING_RERANKER_STUDIO_V2_ENABLED',
    'LEARNING_RERANKER_STUDIO_IMMERSIVE',
    'LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT',
    'LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT',
    'LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT',
    'LEARNING_RERANKER_VISUALIZER_RENDERER',
    'LEARNING_RERANKER_VISUALIZER_QUALITY',
    'LEARNING_RERANKER_VISUALIZER_COLOR_MODE',
    'LEARNING_RERANKER_VISUALIZER_MAX_POINTS',
    'LEARNING_RERANKER_VISUALIZER_TARGET_FPS',
    'LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS',
    'LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY',
    'LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD',
    'LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION',
    # Evaluation params (3)
    'EVAL_DATASET_PATH',
    'BASELINE_PATH',
    'EVAL_MULTI_M',
    # System prompts (9 active)
    'PROMPT_MAIN_RAG_CHAT',
    'PROMPT_QUERY_EXPANSION',
    'PROMPT_QUERY_REWRITE',
    'PROMPT_SEMANTIC_CARDS',
    'PROMPT_LIGHTWEIGHT_CARDS',
    'PROMPT_CODE_ENRICHMENT',
    'PROMPT_SEMANTIC_KG_EXTRACTION',
    'PROMPT_EVAL_ANALYSIS',
    'PROMPT_SYNTHETIC_JUDGE',
    # MCP (inbound) params (7)
    'MCP_HTTP_ENABLED',
    'MCP_HTTP_PATH',
    'MCP_HTTP_STATELESS',
    'MCP_HTTP_JSON_RESPONSE',
    'MCP_HTTP_DNS_REBIND_PROTECTION',
    'MCP_HTTP_ALLOWED_HOSTS',
    'MCP_HTTP_ALLOWED_ORIGINS',
    'MCP_REQUIRE_API_KEY',
    'MCP_DEFAULT_TOP_K',
    'MCP_DEFAULT_MODE',
    # Local Docker diagnostics and scoped service-control params (7)
    'DOCKER_STATUS_TIMEOUT',
    'DOCKER_CONTAINER_LIST_TIMEOUT',
    'DOCKER_CONTAINER_ACTION_TIMEOUT',
    'DOCKER_LOGS_TAIL',
    'DOCKER_LOGS_TIMESTAMPS',
    'DEV_FRONTEND_PORT',
    'DEV_BACKEND_PORT',
}


# RAG-relevant config keys for eval tracking
# Only keys that affect retrieval accuracy - NOT post-retrieval prompts, hydration, or eval paths
RAG_EVAL_CONFIG_KEYS: set[str] = {
    # BM25 Search
    'BM25_TOKENIZER', 'BM25_STEMMER_LANG',
    'BM25_K1', 'BM25_B', 'BM25_WEIGHT',
    # Embedding
    'EMBEDDING_TYPE', 'EMBEDDING_MODEL', 'EMBEDDING_DIM',
    'EMBEDDING_MODEL_LOCAL', 'EMBEDDING_MODEL_MLX', 'EMBEDDING_BATCH_SIZE', 'VOYAGE_MODEL',
    # Retrieval
    'RRF_K_DIV', 'LANGGRAPH_FINAL_K', 'FINAL_K', 'EVAL_FINAL_K',
    'TOPK_DENSE', 'TOPK_SPARSE', 'VECTOR_WEIGHT',
    'CONF_TOP1', 'CONF_AVG5', 'CONF_ANY', 'FALLBACK_CONFIDENCE',
    'CHUNK_SUMMARY_SEARCH_ENABLED', 'MULTI_QUERY_M', 'EVAL_MULTI',
    # Query Expansion (prompts that modify query BEFORE search)
    'QUERY_EXPANSION_ENABLED', 'LANGGRAPH_MAX_QUERY_REWRITES', 'MAX_QUERY_REWRITES', 'USE_SEMANTIC_SYNONYMS',
    'PROMPT_QUERY_EXPANSION', 'PROMPT_QUERY_REWRITE', 'PROMPT_SEMANTIC_CARDS',
    # Reranking
    'RERANKER_MODE', 'RERANKER_CLOUD_PROVIDER', 'RERANKER_CLOUD_MODEL',
    'TRIBRID_RERANKER_ALPHA', 'TRIBRID_RERANKER_TOPN',
    'TRIBRID_RERANKER_BATCH', 'TRIBRID_RERANKER_MAXLEN', 'RERANK_INPUT_SNIPPET_CHARS',
    # Chunking
    'CHUNK_SIZE', 'CHUNK_OVERLAP', 'AST_OVERLAP_LINES', 'MAX_INDEXABLE_FILE_SIZE',
    'MAX_CHUNK_TOKENS', 'MIN_CHUNK_CHARS', 'GREEDY_FALLBACK_TARGET',
    'CHUNKING_STRATEGY', 'PRESERVE_IMPORTS',
    # Scoring
    'CHUNK_SUMMARY_BONUS', 'FILENAME_BOOST_EXACT', 'FILENAME_BOOST_PARTIAL',
    'VENDOR_MODE', 'PATH_BOOSTS',
    # Layer Bonuses
    'LAYER_BONUS_GUI', 'LAYER_BONUS_RETRIEVAL', 'LAYER_BONUS_INDEXER',
    'VENDOR_PENALTY', 'FRESHNESS_BONUS', 'LAYER_INTENT_MATRIX',
    # Keywords
    'KEYWORDS_BOOST', 'KEYWORDS_MAX_PER_REPO', 'KEYWORDS_MIN_FREQ',
    # NOTE: Excluded (don't affect retrieval):
    # - PROMPT_MAIN_RAG_CHAT, PROMPT_CODE_ENRICHMENT, PROMPT_LIGHTWEIGHT_CARDS, PROMPT_EVAL_ANALYSIS (post-retrieval)
    # - HYDRATION_MODE, HYDRATION_MAX_CHARS (post-retrieval)
    # - EVAL_DATASET_PATH, BASELINE_PATH, EVAL_MULTI_M (eval metadata)
}


def get_eval_key_categories() -> dict[str, str]:
    """Return mapping of config keys to their category names.

    Categories are derived from the existing Pydantic model structure and
    the documented groupings in RAG_EVAL_CONFIG_KEYS.
    """
    # Define categories based on the existing comments in RAG_EVAL_CONFIG_KEYS
    # Each key maps to its display category name
    eval_key_category_map: dict[str, str] = {
        # BM25 Search
        'BM25_TOKENIZER': 'BM25 Search',
        'BM25_STEMMER_LANG': 'BM25 Search',
        'BM25_K1': 'BM25 Search',
        'BM25_B': 'BM25 Search',
        'BM25_WEIGHT': 'BM25 Search',
        # Embedding
        'EMBEDDING_TYPE': 'Embedding',
        'EMBEDDING_MODEL': 'Embedding',
        'EMBEDDING_DIM': 'Embedding',
        'EMBEDDING_MODEL_LOCAL': 'Embedding',
        'EMBEDDING_MODEL_MLX': 'Embedding',
        'EMBEDDING_BATCH_SIZE': 'Embedding',
        'VOYAGE_MODEL': 'Embedding',
        # Retrieval
        'RRF_K_DIV': 'Retrieval',
        'LANGGRAPH_FINAL_K': 'Retrieval',
        'FINAL_K': 'Retrieval',
        'EVAL_FINAL_K': 'Retrieval',
        'TOPK_DENSE': 'Retrieval',
        'TOPK_SPARSE': 'Retrieval',
        'VECTOR_WEIGHT': 'Retrieval',
        'CONF_TOP1': 'Retrieval',
        'CONF_AVG5': 'Retrieval',
        'CONF_ANY': 'Retrieval',
        'FALLBACK_CONFIDENCE': 'Retrieval',
        'CHUNK_SUMMARY_SEARCH_ENABLED': 'Retrieval',
        'MULTI_QUERY_M': 'Retrieval',
        'EVAL_MULTI': 'Retrieval',
        # Query Expansion
        'QUERY_EXPANSION_ENABLED': 'Query Expansion',
        'LANGGRAPH_MAX_QUERY_REWRITES': 'Query Expansion',
        'MAX_QUERY_REWRITES': 'Query Expansion',
        'USE_SEMANTIC_SYNONYMS': 'Query Expansion',
        'TRIBRID_SYNONYMS_PATH': 'Query Expansion',
        'PROMPT_QUERY_EXPANSION': 'Query Expansion',
        'PROMPT_QUERY_REWRITE': 'Query Expansion',
        'PROMPT_SEMANTIC_CARDS': 'Query Expansion',
        # Reranking
        'RERANKER_MODE': 'Reranking',
        'RERANKER_CLOUD_PROVIDER': 'Reranking',
        'RERANKER_CLOUD_MODEL': 'Reranking',
        'TRIBRID_RERANKER_ALPHA': 'Reranking',
        'TRIBRID_RERANKER_TOPN': 'Reranking',
        'RERANKER_CLOUD_TOP_N': 'Reranking',
        'TRIBRID_RERANKER_BATCH': 'Reranking',
        'TRIBRID_RERANKER_MAXLEN': 'Reranking',
        'RERANK_INPUT_SNIPPET_CHARS': 'Reranking',
        # Chunking
        'CHUNK_SIZE': 'Chunking',
        'CHUNK_OVERLAP': 'Chunking',
        'AST_OVERLAP_LINES': 'Chunking',
        'MAX_INDEXABLE_FILE_SIZE': 'Chunking',
        'MAX_CHUNK_TOKENS': 'Chunking',
        'MIN_CHUNK_CHARS': 'Chunking',
        'GREEDY_FALLBACK_TARGET': 'Chunking',
        'CHUNKING_STRATEGY': 'Chunking',
        'PRESERVE_IMPORTS': 'Chunking',
        # Scoring
        'CHUNK_SUMMARY_BONUS': 'Scoring',
        'FILENAME_BOOST_EXACT': 'Scoring',
        'FILENAME_BOOST_PARTIAL': 'Scoring',
        'VENDOR_MODE': 'Scoring',
        'PATH_BOOSTS': 'Scoring',
        # Layer Bonuses
        'LAYER_BONUS_GUI': 'Layer Bonuses',
        'LAYER_BONUS_RETRIEVAL': 'Layer Bonuses',
        'LAYER_BONUS_INDEXER': 'Layer Bonuses',
        'VENDOR_PENALTY': 'Layer Bonuses',
        'FRESHNESS_BONUS': 'Layer Bonuses',
        'LAYER_INTENT_MATRIX': 'Layer Bonuses',
        # Keywords
        'KEYWORDS_BOOST': 'Keywords',
        'KEYWORDS_MAX_PER_REPO': 'Keywords',
        'KEYWORDS_MIN_FREQ': 'Keywords',
    }
    return eval_key_category_map
