"""Validated persistence boundary for reusable official semantic chunk graphs.

Only digests of source text, templates and rendered prompts are retained. The
recipe records the approved schema and sanitized provider selection; a stable
provider slug cannot prove that the provider's implementation stayed unchanged.
Explicit de-indexing is the operator's invalidation boundary for that case.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import date, time
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from neo4j_graphrag.components.schema import GraphSchema
from neo4j_graphrag.components.types import Neo4jGraph, Neo4jNode, Neo4jRelationship
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidatorFunctionWrapHandler,
    field_validator,
    model_validator,
)

from server.models.index import ChunkProvenance

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]
_Text = Annotated[str, Field(min_length=1, strict=True)]
_RESERVED_GRAPH_PROPERTIES = frozenset(
    {"repo_id", "corpus_id", "run_id", "graphJoinId", "__tmp_internal_id"}
)
_Number = StrictInt | StrictFloat
_Probability = Annotated[_Number, Field(ge=0, le=1)]
_TokenLimit = Annotated[StrictInt, Field(ge=1)]
_ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
_TokenId = Annotated[str, Field(strict=True, pattern=r"^[0-9]+$")]
_ProviderSlug = Annotated[
    str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)*$"),
]


class _SemanticParameterObject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class _ReasoningParameters(_SemanticParameterObject):
    effort: _ReasoningEffort | None = None
    max_tokens: Annotated[StrictInt, Field(ge=0)] | None = None
    enabled: StrictBool | None = None
    exclude: StrictBool | None = None


class _ProviderParameters(_SemanticParameterObject):
    order: list[_ProviderSlug] | None = None
    allow_fallbacks: StrictBool | None = None
    require_parameters: StrictBool | None = None


class _ExtraBodyParameters(_SemanticParameterObject):
    reasoning: _ReasoningParameters | None = None
    provider: _ProviderParameters | None = None
    top_k: Annotated[StrictInt, Field(ge=0)] | None = None
    repetition_penalty: Annotated[_Number, Field(ge=0, le=2)] | None = None
    min_p: _Probability | None = None


class _ResponseFormatParameters(_SemanticParameterObject):
    # The official extractor supplies its own Neo4jGraph response schema. Do
    # not admit arbitrary schema descriptions or prompt-bearing format objects.
    type: Literal["text", "json_object"]


class _SemanticModelParameters(_SemanticParameterObject):
    """Reviewed semantic SDK kwargs, never arbitrary provider payloads.

    build_graph_llm currently emits temperature plus reasoning_effort or
    extra_body.reasoning.effort. Additional controls below have explicit typed
    shapes; expanding them requires reviewing the provider contract. Transport,
    request text, tools, metadata and unknown fields have no persistence path.
    """

    temperature: Annotated[_Number, Field(ge=0, le=2)] | None = None
    top_p: _Probability | None = None
    max_tokens: _TokenLimit | None = None
    max_completion_tokens: _TokenLimit | None = None
    frequency_penalty: Annotated[_Number, Field(ge=-2, le=2)] | None = None
    presence_penalty: Annotated[_Number, Field(ge=-2, le=2)] | None = None
    seed: StrictInt | None = None
    reasoning_effort: _ReasoningEffort | None = None
    stop: str | Annotated[list[str], Field(max_length=4)] | None = None
    logprobs: StrictBool | None = None
    top_logprobs: Annotated[StrictInt, Field(ge=0, le=20)] | None = None
    logit_bias: dict[_TokenId, Annotated[_Number, Field(ge=-100, le=100)]] | None = None
    verbosity: Literal["low", "medium", "high"] | None = None
    response_format: _ResponseFormatParameters | None = None
    extra_body: _ExtraBodyParameters | None = None


class GraphExtractionCheckpointError(RuntimeError):
    """Checkpoint state is unusable; never translate this into a paid cache miss."""


class GraphExtractionCheckpointCorruptError(GraphExtractionCheckpointError):
    """A persisted checkpoint or partition fails its validated boundary."""


class GraphExtractionCheckpointConflictError(GraphExtractionCheckpointError):
    """One exact extraction identity already owns a different validated result."""


class GraphExtractionCheckpointFenceError(GraphExtractionCheckpointError):
    """The caller no longer owns the base corpus's building fence."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _require_text(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError("Checkpoint identifiers must be nonempty text without control characters")
    return value


def _validate_model_parameters(value: JsonValue) -> None:
    # Validation only: preserve original key presence, nulls, and JSON numeric
    # types for identity. Never dump defaults or silently drop unknown controls.
    _SemanticModelParameters.model_validate(value)


class GraphExtractionCheckpointRecipe(BaseModel):
    """Typed, inspectable extraction recipe; source and prompt text stay outside this table."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    approved_schema: GraphSchema
    prompt_template_sha256: Sha256
    examples_sha256: Sha256
    model_alias: _Text
    model_upstream: _Text
    model_endpoint: _Text
    model_parameters: dict[str, JsonValue]
    neo4j_graphrag_version: _Text
    extractor_version: _Text
    pruner_version: _Text

    @field_validator("approved_schema", mode="wrap")
    @classmethod
    def _exact_approved_schema(cls, value: Any, handler: ValidatorFunctionWrapHandler) -> GraphSchema:
        # Official instances contain mutable children. Validate their actual
        # fields too, without allowing SDK validators to mutate the caller.
        source = value.model_dump(mode="python") if isinstance(value, GraphSchema) else value
        source = deepcopy(source)
        schema: GraphSchema = handler(deepcopy(source))
        # GraphRAG 1.19 reopens an explicitly closed, property-free relationship.
        # Ragweld's approved schema intentionally closes it after SDK validation;
        # retain that exact permission through recipe hashes and JSONB reloads.
        # Do not extend this exception to nodes: the SDK forbids empty node
        # properties, and their normalizer supplies the required name property.
        if isinstance(source, dict):
            for raw, relationship in zip(source.get("relationship_types", ()), schema.relationship_types, strict=True):
                if (
                    isinstance(raw, dict)
                    and raw.get("properties") == []
                    and raw.get("additional_properties") is False
                ):
                    relationship.additional_properties = False
        return schema

    @field_validator(
        "model_alias", "model_upstream", "neo4j_graphrag_version", "extractor_version", "pruner_version",
    )
    @classmethod
    def _plain_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("model_endpoint")
    @classmethod
    def _sanitized_endpoint(cls, value: str) -> str:
        _require_text(value)
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or "?" in value or "#" in value or value != value.strip()
        ):
            raise ValueError("Checkpoint model endpoint must omit credentials, query and fragment")
        # Invalid ports must not become a second, apparently valid endpoint identity.
        _ = parts.port
        return value

    @field_validator("model_parameters", mode="before")
    @classmethod
    def _semantic_parameters(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _validate_model_parameters(value)
        return value


class GraphExtractionCheckpointIdentity(BaseModel):
    """Exact extraction inputs, excluding execution ownership, credentials and budgets.

    Chunk index is the official extractor's file-local order, and metadata's
    digest covers the complete metadata handed to that extractor. Provenance
    remains the existing typed source mapping. Rendered prompt digest covers
    the final template/schema/examples/text combination, never its raw text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity_version: Literal[1] = 1
    repo_id: _Text
    file_path: _Text
    file_sha256: Sha256
    chunk_id: _Text
    chunk_index: int = Field(ge=0, strict=True)
    chunk_content_sha256: Sha256
    chunk_metadata_sha256: Sha256
    start_line: int = Field(ge=0, strict=True)
    end_line: int = Field(ge=0, strict=True)
    chunk_provenance: ChunkProvenance | None
    rendered_prompt_sha256: Sha256
    recipe: GraphExtractionCheckpointRecipe

    @field_validator("identity_version", mode="before")
    @classmethod
    def _integer_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("Checkpoint identity version must be an integer")
        return value

    @field_validator("repo_id", "file_path", "chunk_id")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        return _require_text(value)

    @model_validator(mode="after")
    def _base_corpus_and_ordered_lines(self) -> GraphExtractionCheckpointIdentity:
        if self.repo_id.startswith("__staging__"):
            raise ValueError("Extraction checkpoints belong to the base corpus, never staging")
        if self.end_line < self.start_line:
            raise ValueError("Checkpoint end_line must be at least start_line")
        return self


def graph_extraction_recipe_hash(recipe: GraphExtractionCheckpointRecipe) -> str:
    """Hash canonical validated semantic recipe fields, preserving list order."""
    validated = GraphExtractionCheckpointRecipe.model_validate(recipe.model_dump(mode="json"))
    return hashlib.sha256(_canonical_json(validated.model_dump(mode="json")).encode("utf-8")).hexdigest()


def graph_extraction_cache_key(identity: GraphExtractionCheckpointIdentity) -> str:
    """Hash canonical validated inputs; dictionary insertion order is irrelevant."""
    validated = GraphExtractionCheckpointIdentity.model_validate(identity.model_dump(mode="json"))
    return hashlib.sha256(_canonical_json(validated.model_dump(mode="json")).encode("utf-8")).hexdigest()


class GraphExtractionCheckpoint(BaseModel):
    """Official validated chunk graph before lexical processing and run identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    identity: GraphExtractionCheckpointIdentity
    cache_key: Sha256
    originating_run_id: _Text
    created_at: AwareDatetime
    graph: Neo4jGraph
    pruned_nodes: int = Field(ge=0, strict=True)
    pruned_relationships: int = Field(ge=0, strict=True)

    @field_validator("format_version", mode="before")
    @classmethod
    def _integer_version(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("Checkpoint format version must be an integer")
        return value

    @field_validator("originating_run_id")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("graph", mode="before")
    @classmethod
    def _complete_official_graph(cls, value: Any) -> Any:
        if isinstance(value, Neo4jGraph):
            value = value.model_dump(mode="python")
        if not isinstance(value, dict) or not {"nodes", "relationships"} <= value.keys():
            raise ValueError("Checkpoint graph must explicitly contain nodes and relationships")
        return value

    @model_validator(mode="after")
    def _exact_identity_and_unscoped_graph(self) -> GraphExtractionCheckpoint:
        if self.cache_key != graph_extraction_cache_key(self.identity):
            raise ValueError("Checkpoint cache key does not match its exact extraction identity")
        items: tuple[Neo4jNode | Neo4jRelationship, ...] = (*self.graph.nodes, *self.graph.relationships)
        for item in items:
            if _RESERVED_GRAPH_PROPERTIES & (item.properties.keys() | item.embedding_properties.keys()):
                raise ValueError("Checkpoint graph contains server-owned scope properties")
            # The official extractor parses provider JSON, where date-looking
            # values remain strings in PropertyValue's union. Actual Python
            # TemporalValue instances came from outside that raw boundary and
            # cannot be represented losslessly by this JSONB envelope. Refuse
            # them before serialization, preserving the official DTO unchanged.
            if any(isinstance(value, (date, time)) for value in item.properties.values()):
                raise ValueError("Checkpoint graph cannot persist Python temporal values; raw extraction requires JSON values")
        # Reject NaN/infinity instead of allowing PostgreSQL/JSON codecs to change identity.
        _canonical_json(self.graph.model_dump(mode="json"))
        return self

    @classmethod
    def from_persisted_payload(cls, payload: Any) -> GraphExtractionCheckpoint:
        """Persisted fields must survive validation without defaults, coercion or data loss."""
        # Capture before validation: official nested validators may transform
        # their input dictionaries in place while applying schema defaults.
        original = _canonical_json(payload)
        checkpoint = cls.model_validate(payload)
        if original != _canonical_json(checkpoint.model_dump(mode="json")):
            raise ValueError("Persisted checkpoint is incomplete or changes during validation")
        return checkpoint

    def semantic_payload(self) -> str:
        """Type-strict content comparison, preserving first origin/time on duplicates."""
        return _canonical_json(self.model_dump(mode="json", exclude={"created_at", "originating_run_id"}))


class GraphExtractionCheckpointPartition(BaseModel):
    """Corpus-row recipe ownership, changed only while its index fence is row-locked."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_run_id: _Text
    recipe_hash: Sha256
    complete: bool = Field(default=False, strict=True)

    @classmethod
    def from_persisted_payload(cls, payload: Any) -> GraphExtractionCheckpointPartition:
        """A missing completion flag may never default a finished partition back open."""
        original = _canonical_json(payload)
        partition = cls.model_validate(payload)
        if original != _canonical_json(partition.model_dump(mode="json")):
            raise ValueError("Persisted checkpoint partition is incomplete or changes during validation")
        return partition
