"""Index-domain boundary models (owned here; registered for TypeScript generation through the aggregate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

ExtractionMethod = Literal["docling", "direct"]
DocumentKind = Literal["text", "pdf", "rich"]


class PageRegion(BaseModel):
    """One cited region on a page: top-left origin, normalized to the page size (0..1)."""

    page: int = Field(ge=1, description="1-based page number")
    left: float = Field(ge=0.0, le=1.0, description="Left edge as a fraction of page width")
    top: float = Field(ge=0.0, le=1.0, description="Top edge as a fraction of page height")
    right: float = Field(ge=0.0, le=1.0, description="Right edge as a fraction of page width")
    bottom: float = Field(ge=0.0, le=1.0, description="Bottom edge as a fraction of page height")

    @model_validator(mode="after")
    def _ordered(self) -> PageRegion:
        if self.left > self.right or self.top > self.bottom:
            raise ValueError("PageRegion requires left <= right and top <= bottom")
        return self


class ChunkProvenance(BaseModel):
    """Where a chunk came from in its source document: extraction method plus page regions.

    Direct text/code extraction has line spans only (``regions`` empty, pages ``None``).
    Docling extraction carries one region per contributing layout item.
    """

    extraction: ExtractionMethod = Field(description="How the source text was extracted")
    page_start: int | None = Field(default=None, ge=1, description="First cited page (1-based)")
    page_end: int | None = Field(default=None, ge=1, description="Last cited page (1-based)")
    regions: list[PageRegion] = Field(
        default_factory=list, description="Layout regions the chunk text was taken from"
    )

    @model_validator(mode="after")
    def _consistent(self) -> ChunkProvenance:
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start and page_end must both be set or both be None")
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("page_start must be <= page_end")
        if bool(self.regions) != (self.page_start is not None):
            raise ValueError("regions must be non-empty exactly when page_start is set")
        return self


FigureKind = Literal["diagram", "chart", "schematic", "photo", "table", "drawing", "other"]


class FigureAnnotation(BaseModel):
    """Structured description of one figure, produced by the vision alias at index time.

    Persisted in ``Chunk.metadata["figure"]`` so callouts and part numbers are searchable
    verbatim and a later schematic graph can consume ``components``/``connections``.
    """

    kind: FigureKind = Field(default="other", description="Figure kind as judged by the vision model")
    summary: str = Field(default="", description="Dense prose description; this is what gets embedded")
    labels: list[str] = Field(default_factory=list, description="Legible callouts, axis labels, legend entries, part numbers")
    components: list[str] = Field(default_factory=list, description="Named parts or entities depicted")
    connections: list[str] = Field(default_factory=list, description="'A -> B' relations stated or drawn")
    values: list[str] = Field(default_factory=list, description="Numbers with units as printed")
    references: list[str] = Field(default_factory=list, description="Sheet/figure/table/section cross-references printed on the figure")


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
    provenance: ChunkProvenance | None = Field(
        default=None,
        description="Extraction and page provenance; None only for rows indexed before provenance capture",
    )


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
    status: Literal["idle", "indexing", "complete", "error", "cancelled"] = Field(
        description="Current indexing state"
    )
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
    status: Literal["indexing", "complete", "error", "cancelled"] = Field(
        description="Final or current run state"
    )
    started_at: datetime = Field(description="When indexing run started")
    completed_at: datetime | None = Field(default=None, description="When indexing run completed")
    progress: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Best-effort progress for this run"
    )
    error: str | None = Field(default=None, description="Error message when status='error'")
    total_files: int = Field(default=0, ge=0, description="Indexed file count for this run")
    total_chunks: int = Field(default=0, ge=0, description="Indexed chunk count for this run")
    total_tokens: int = Field(default=0, ge=0, description="Indexed token count for this run")
    embedding_provider: str | None = Field(
        default=None, description="Embedding provider used by this run"
    )
    embedding_model: str | None = Field(
        default=None, description="Embedding model used by this run"
    )
    embedding_dimensions: int | None = Field(
        default=None, ge=0, description="Embedding dimensions used by this run"
    )
    figures_described: int = Field(
        default=0, ge=0, description="Figures this run described with the vision alias"
    )
    figures_failed: int = Field(
        default=0,
        ge=0,
        description="Figures this run sent for description that came back empty or errored",
    )
    figures_undescribed: int = Field(
        default=0,
        ge=0,
        description="Figures this run left undescribed (filtered by class, area, or describe=false)",
    )
    figure_description_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Ceiling on the vision-call cost (USD) of this run's figure descriptions, from catalog "
            "pricing for the run's indexing.figures.vision_model charged over the full "
            "max_completion_tokens budget; null when nothing was described or the alias is unpriced"
        ),
    )


class IndexRunEvent(BaseModel):
    """Persisted index terminal event for replay."""

    run_id: str = Field(description="Run identifier")
    ts: datetime = Field(description="Event timestamp (UTC)")
    type: str = Field(description="Event type (log/progress/warning/error/complete/cancelled)")
    message: str | None = Field(default=None, description="Human-readable message")
    percent: int | None = Field(
        default=None, ge=0, le=100, description="Progress percentage when present"
    )
    current_file: str | None = Field(default=None, description="Current file when present")
    meta: dict[str, Any] = Field(default_factory=dict, description="Additional event payload")


class IndexRunEventPage(BaseModel):
    """One page of a run's event log, carrying the total so a cap is never shown as a fact.

    The run header used to print `len(events)` as "500 replayed events" for a corpus whose log
    held far more -- 500 being the limit the UI itself asked for. The page states how many
    events the run actually recorded and where this slice starts, so the reader can tell a
    complete log from a truncated one.
    """

    repo_id: str = Field(
        description="Corpus identifier",
        validation_alias=AliasChoices("repo_id", "corpus_id"),
        serialization_alias="corpus_id",
    )
    run_id: str = Field(description="Run identifier")
    events: list[IndexRunEvent] = Field(
        default_factory=list, description="The most recent events, oldest first"
    )
    total: int = Field(ge=0, description="Events this run recorded in total")
    first_index: int = Field(
        ge=0, description="0-based position of events[0] within the run's full log"
    )


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
    file_breakdown: dict[str, int] = Field(
        default_factory=dict, description="Count by file extension"
    )


class IndexEstimate(BaseModel):
    """Best-effort estimate for indexing cost/time before running the indexer.

    Notes:
    - Tokens and chunks are measured: a sample of the corpus is extracted and run through the
      configured chunker, then scaled by byte share. ``sampled_files``/``sampled_bytes`` say
      how much was measured and the ``*_low``/``*_high`` bounds carry the error band.
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
    estimated_total_tokens: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Estimated total tokens. None whenever status is not 'ready': nothing was measured, "
            "and a consumer that would have rendered a zero fails to compile instead."
        ),
    )
    estimated_total_chunks: int | None = Field(
        default=None, ge=0, description="Estimated chunks; None unless status is 'ready'."
    )
    estimated_tokens_low: int | None = Field(
        default=None, ge=0, description="Low end of the token band; None unless status is 'ready'."
    )
    estimated_tokens_high: int | None = Field(
        default=None, ge=0, description="High end of the token band; None unless status is 'ready'."
    )
    estimated_chunks_low: int | None = Field(
        default=None, ge=0, description="Low end of the chunk band; None unless status is 'ready'."
    )
    estimated_chunks_high: int | None = Field(
        default=None, ge=0, description="High end of the chunk band; None unless status is 'ready'."
    )
    estimate_relative_error: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Half-width of the token/chunk error band as a fraction of the point estimate "
            "(model error plus a sampling term). None unless status is 'ready'."
        ),
    )
    sampled_files: int | None = Field(
        default=None, ge=0, description="Files measured; None unless status is 'ready'."
    )
    sampled_bytes: int | None = Field(
        default=None, ge=0, description="Bytes measured; None unless status is 'ready'."
    )
    status: Literal["ready", "warming", "insufficient_sample"] = Field(
        default="ready",
        description=(
            "Only 'ready' carries numbers. 'warming' means the estimator's tokenizer is still "
            "loading; 'insufficient_sample' means it measured too little of the corpus to "
            "extrapolate honestly. In BOTH non-ready states every count below is zero -- not a "
            "small estimate, no estimate -- and the client must ask again rather than show them "
            "or open a confirmation on them."
        ),
    )
    warmup_seconds_remaining: float | None = Field(
        default=None,
        ge=0.0,
        description="Rough seconds until the estimator is ready, when status is 'warming'.",
    )
    elapsed_seconds: float = Field(
        ge=0.0,
        description=(
            "Wall-clock seconds this estimate spent sampling. The first call in a fresh process "
            "pays for loading the tokenizer, so the UI can say how long the measurement took."
        ),
    )
    embedding_backend: Literal["deterministic", "provider"] = Field(
        description="Embedding backend used for indexing (deterministic has no external cost)"
    )
    embedding_provider: str = Field(
        description="Embedding provider used for indexing (embedding.embedding_type)"
    )
    embedding_model: str = Field(description="Embedding model used for indexing (effective model)")
    skip_dense: bool = Field(
        description="Whether dense embeddings are skipped (indexing.skip_dense)"
    )
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
    estimated_figures: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Figures expected to be described (heuristic: PDF pages x 0.4, rounded; "
            "omitted entirely when it rounds to zero), when indexing.figures is enabled"
        ),
    )
    figure_description_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated vision-call cost (USD) to describe figures, from catalog pricing for indexing.figures.vision_model",
    )
    total_cost_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated total indexing cost (USD): embedding + semantic KG + figure description (each when applicable).",
    )
    estimated_seconds: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Point estimate for total indexing time (seconds). The phase fields below plus "
            "estimated_seconds_overhead sum to exactly this; low/high are it scaled."
        ),
    )
    estimated_seconds_embedding: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated embedding phase time (seconds), stated rather than derived by subtraction.",
    )
    estimated_seconds_overhead: float | None = Field(
        default=None,
        ge=0.0,
        description="Fixed startup/teardown time (seconds) included in the point estimate.",
    )
    estimated_seconds_low: float | None = Field(
        default=None,
        ge=0.0,
        description="Very rough low-end estimate for total indexing time (seconds)",
    )
    estimated_seconds_high: float | None = Field(
        default=None,
        ge=0.0,
        description="Very rough high-end estimate for total indexing time (seconds)",
    )
    estimated_seconds_semantic_kg: float | None = Field(
        default=None,
        ge=0.0,
        description="Estimated GraphRAG semantic phase time (seconds) when enabled.",
    )
    estimated_seconds_figures: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Estimated figure-description phase time (seconds) when indexing.figures is enabled: "
            "the estimated figure count at ~20 s per vision call, divided by "
            "indexing.figures.concurrency."
        ),
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Human-readable assumptions used for the estimate"
    )


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
    phase: Literal["building", "retiring"] = Field(
        default="building",
        description="Fence phase of the holding run: building the index, or retiring the previous generation",
    )
    stage: str | None = Field(
        default=None,
        max_length=200,
        description="What the holding run last reported doing (its most recent log/progress run event), when it has logged one",
    )
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
    qdrant_collections: list[str] = Field(
        default_factory=list, description="Collections still to drop"
    )
    graph_repo_ids: list[str] = Field(
        default_factory=list, description="Neo4j graphs still to drop"
    )
    created_at: datetime = Field(description="When the deletion tombstone was written")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class FigureRouteConflictDetail(BaseModel):
    """Public error detail (HTTP 409) when indexing.figures.vision_model cannot be used."""

    code: Literal["figure_vision_alias"] = "figure_vision_alias"
    alias: str = Field(description="The configured indexing.figures.vision_model alias")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class PersistedStateCorruptDetail(BaseModel):
    """Public error detail (HTTP 409) when a corpus's persisted index state does not validate."""

    code: Literal["persisted_state_corrupt"] = "persisted_state_corrupt"
    corpus_id: str = Field(description="Corpus whose persisted state is malformed")
    key: str = Field(
        description=(
            "Which persisted key is malformed (generation, index_tombstone, index_run, reclaim_backlog)"
        )
    )
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="The repair action (de-index the corpus, then re-index)")


class FigureRouteConflictResponse(BaseModel):
    """FastAPI response envelope for an unusable figure vision alias (HTTP 409)."""

    detail: FigureRouteConflictDetail


class PersistedStateCorruptResponse(BaseModel):
    """FastAPI response envelope for a persisted-state corruption detail."""

    detail: PersistedStateCorruptDetail


class IndexDeletionIncompleteResponse(BaseModel):
    """FastAPI response envelope for an incomplete-deletion detail."""

    detail: IndexDeletionIncompleteDetail


# =============================================================================
# SOURCE DOCUMENT VIEWER - document view + provenance record
# =============================================================================


class PageSize(BaseModel):
    """PDF page size in points (72 per inch)."""

    width: float = Field(gt=0.0, description="Page width in points")
    height: float = Field(gt=0.0, description="Page height in points")


class DocumentTextView(BaseModel):
    """Plain text/code document content for the viewer."""

    kind: Literal["text"] = "text"
    text: str = Field(description="Full file text decoded exactly as the indexer decoded it")
    line_count: int = Field(ge=0, description="Number of lines in text")


class DocumentPdfView(BaseModel):
    """PDF document: pages are rendered on demand through the page endpoint."""

    kind: Literal["pdf"] = "pdf"
    page_count: int = Field(ge=1, description="Number of pages")
    page_sizes: list[PageSize] = Field(description="Page sizes in points, index 0 = page 1")


class DocumentRichView(BaseModel):
    """Rich document (docx/pptx/xlsx/html) shown as the Docling markdown the chunks were cut from."""

    kind: Literal["rich"] = "rich"
    markdown: str = Field(description="Docling markdown export captured at index time")


class DocumentProvenanceCaptured(BaseModel):
    """The file has a provenance record from indexing."""

    state: Literal["captured"] = "captured"
    extraction: ExtractionMethod = Field(description="How the file was extracted at index time")
    sha256: str = Field(min_length=64, max_length=64, description="SHA-256 of the file at index time")
    byte_size: int = Field(ge=0, description="File size at index time")
    indexed_at: datetime = Field(description="When the provenance record was written")
    stale: bool = Field(description="True when the file on disk no longer matches sha256")


class DocumentProvenanceNotCaptured(BaseModel):
    """The file was indexed before provenance capture existed; re-index to enable it."""

    state: Literal["not_captured"] = "not_captured"
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class DocumentView(BaseModel):
    """Source document as served to the evidence viewer."""

    corpus_id: str = Field(description="Corpus the file belongs to")
    file_path: str = Field(description="Corpus-root-relative POSIX path")
    byte_size: int = Field(ge=0, description="Current file size on disk")
    content: DocumentTextView | DocumentPdfView | DocumentRichView = Field(discriminator="kind")
    provenance: DocumentProvenanceCaptured | DocumentProvenanceNotCaptured = Field(
        discriminator="state"
    )


class DocumentNotCapturedDetail(BaseModel):
    """Public error detail (HTTP 409): a rich document has no captured markdown to show."""

    code: Literal["document_not_captured"] = "document_not_captured"
    corpus_id: str = Field(description="Corpus the file belongs to")
    file_path: str = Field(description="Corpus-root-relative POSIX path")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class DocumentNotCapturedResponse(BaseModel):
    """FastAPI response envelope for a not-captured rich document."""

    detail: DocumentNotCapturedDetail


class DocumentTooLargeDetail(BaseModel):
    """Public error detail (HTTP 413): a text document exceeds the viewer size limit."""

    code: Literal["document_too_large"] = "document_too_large"
    corpus_id: str = Field(description="Corpus the file belongs to")
    file_path: str = Field(description="Corpus-root-relative POSIX path")
    byte_size: int = Field(ge=0, description="Current file size on disk")
    max_text_bytes: int = Field(ge=0, description="Configured document_viewer.max_text_bytes")
    message: str = Field(description="Stable, non-sensitive summary")
    operator_hint: str = Field(description="What the operator can do next")


class DocumentTooLargeResponse(BaseModel):
    """FastAPI response envelope for an over-limit text document."""

    detail: DocumentTooLargeDetail


class IndexedDocumentRecord(BaseModel):
    """Persistence boundary for the ``documents`` table (not a frontend wire type)."""

    file_path: str = Field(description="Corpus-root-relative POSIX path")
    kind: DocumentKind = Field(description="Viewer content kind")
    extraction: ExtractionMethod = Field(description="How the file was extracted")
    sha256: str = Field(min_length=64, max_length=64, description="SHA-256 of the file at index time")
    byte_size: int = Field(ge=0, description="File size at index time")
    markdown: str | None = Field(
        default=None, description="Docling markdown export; stored for rich kinds only"
    )
    indexed_at: datetime | None = Field(default=None, description="Set by the database on write")


__all__ = [
    "Chunk",
    "ChunkProvenance",
    "DocumentKind",
    "DocumentNotCapturedDetail",
    "DocumentNotCapturedResponse",
    "DocumentPdfView",
    "DocumentProvenanceCaptured",
    "DocumentProvenanceNotCaptured",
    "DocumentRichView",
    "DocumentTextView",
    "DocumentTooLargeDetail",
    "DocumentTooLargeResponse",
    "DocumentView",
    "ExtractionMethod",
    "IndexedDocumentRecord",
    "PageRegion",
    "PageSize",
    "IndexDeletionIncompleteDetail",
    "IndexDeletionIncompleteResponse",
    "IndexEstimate",
    "FigureRouteConflictDetail",
    "FigureRouteConflictResponse",
    "IndexFenceCorruptDetail",
    "IndexRequest",
    "IndexRunConflictDetail",
    "IndexRunConflictResponse",
    "IndexRunEvent",
    "IndexRunEventPage",
    "IndexRunSummary",
    "IndexStats",
    "IndexStatus",
    "PersistedStateCorruptDetail",
    "PersistedStateCorruptResponse",
]
