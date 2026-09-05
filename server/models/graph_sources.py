"""Public source-navigation boundaries for entity mentions, not relationship evidence."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from server.models.index import ChunkProvenance


class GraphEntitySource(BaseModel):
    chunk_id: str = Field(min_length=1, description="Chunk directly linked to the entity by FROM_CHUNK")
    file_path: str = Field(min_length=1, description="Stored corpus-relative source path")
    start_line: int = Field(ge=1, description="First line of the source chunk")
    end_line: int = Field(ge=1, description="Last line of the source chunk")
    content: str = Field(description="Source text stored in the graph generation")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Matching indexed chunk location metadata, when present")
    provenance: ChunkProvenance | None = Field(default=None, description="Matching indexed chunk page provenance, when present")


class GraphEntitySourcesResponse(BaseModel):
    entity_id: str
    run_id: str = Field(description="Active manifest token; pass it when requesting another source page")
    sources: list[GraphEntitySource]
    next_offset: int | None = Field(default=None, ge=0)


class GraphSourceGenerationChangedDetail(BaseModel):
    code: Literal["graph_generation_changed"] = "graph_generation_changed"
    message: str = "The graph generation changed. Reload this entity's sources."


class GraphSourceGenerationChangedResponse(BaseModel):
    detail: GraphSourceGenerationChangedDetail


class GraphSourceReindexRequiredDetail(BaseModel):
    code: Literal["graph_source_reindex_required"] = "graph_source_reindex_required"
    message: str = "Source navigation requires a graph rebuilt with generation-scoped source links."
    operator_hint: str = "Open Indexing, review the graph schema if prompted, and rebuild this corpus."


class GraphSourceReindexRequiredResponse(BaseModel):
    detail: GraphSourceReindexRequiredDetail
