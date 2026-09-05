"""Execution ownership and exact-input identity for official extraction checkpoints.

The persisted boundary belongs to models/graph_extraction_checkpoint.py. This
adapter carries live Postgres/producer state and never stores request bodies or
billing data. Progress callbacks synchronously enqueue ordered observations;
their owner must drain persistence before successful generation completion.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from neo4j_graphrag.components.schema import GraphSchema
from neo4j_graphrag.components.types import TextChunk, TextChunks
from neo4j_graphrag.generation.prompts import PromptTemplate

from server.db.postgres import PostgresClient
from server.indexing.graphrag_schema import closed_graph_schema
from server.models.graph_extraction_checkpoint import (
    GraphExtractionCheckpoint,
    GraphExtractionCheckpointCorruptError,
    GraphExtractionCheckpointError,
    GraphExtractionCheckpointIdentity,
    GraphExtractionCheckpointRecipe,
    graph_extraction_cache_key,
    graph_extraction_recipe_hash,
)
from server.models.index import Chunk

logger = logging.getLogger(__name__)
T = TypeVar("T")
ExtractionPhase = Literal["selected", "admitted", "dispatching", "reused", "succeeded", "failed", "cancelled"]


def extraction_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extraction_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


async def await_checkpoint_task(task: asyncio.Task[T]) -> T:
    """Defer repeated caller cancellation until retained mutation/cleanup ends."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError()
    return result


@dataclass(frozen=True, slots=True)
class ExtractionProgress:
    """Ordered per-chunk domain observations, independent of native HTTP accounting.

    ``admitted`` starts inside the official semaphore; ``dispatching`` means
    entering its one fresh extraction invocation. Only native census transports
    establish HTTP attempts. ``succeeded`` follows the durable database commit.
    ``duration_s`` is fresh extractor worker time; cache hits always carry zero.
    Sequence numbers increase across all files under this corpus/run owner.
    """

    repo_id: str
    owner_run_id: str
    sequence: int
    cache_key: str
    file_path: str
    chunk_id: str
    chunk_index: int
    phase: ExtractionPhase
    duration_s: float = 0.0
    pruned_nodes: int = 0
    pruned_relationships: int = 0


ExtractionProgressCallback = Callable[[ExtractionProgress], None]


@dataclass(slots=True)
class ExtractionFileCheckpoint:
    execution: ExtractionCheckpointContext = field(repr=False)
    identities: tuple[GraphExtractionCheckpointIdentity, ...]
    keys: tuple[str, ...]
    _official_chunks: tuple[str, ...] = field(repr=False)
    _schema: str = field(repr=False)
    _examples_digest: str = field(repr=False)
    _template_digest: str = field(repr=False)
    prepared: bool = False
    extraction_started: bool = False
    written: bool = False
    outcomes: dict[str, ExtractionPhase] = field(default_factory=dict)
    pruned_nodes: int = 0
    pruned_relationships: int = 0

    def validate_inputs(
        self, chunks: TextChunks, schema: GraphSchema, examples: str,
        prompt_template: PromptTemplate,
    ) -> None:
        if not self.prepared:
            raise GraphExtractionCheckpointError("Checkpoint file preparation did not complete")
        if self.extraction_started:
            raise GraphExtractionCheckpointError("A prepared file can be extracted once per execution owner")
        if tuple(extraction_json(chunk.model_dump(mode="json")) for chunk in chunks.chunks) != self._official_chunks:
            raise GraphExtractionCheckpointError("Selected extraction chunks changed after checkpoint preparation")
        if (
            extraction_json(schema.model_dump(mode="json")) != self._schema
            or extraction_digest(examples) != self._examples_digest
            or extraction_digest(prompt_template.template) != self._template_digest
        ):
            raise GraphExtractionCheckpointError("The extraction recipe changed after checkpoint preparation")
        self.extraction_started = True

    def identity_for(self, chunk: TextChunk) -> GraphExtractionCheckpointIdentity:
        if not 0 <= chunk.index < len(self.identities):
            raise GraphExtractionCheckpointError("Extracted chunk is outside the prepared file")
        identity = self.identities[chunk.index]
        if extraction_json(chunk.model_dump(mode="json")) != self._official_chunks[chunk.index]:
            raise GraphExtractionCheckpointError("Extracted chunk does not match its prepared identity")
        return identity

    def emit(
        self, identity: GraphExtractionCheckpointIdentity, phase: ExtractionPhase,
        *, duration_s: float = 0.0, checkpoint: GraphExtractionCheckpoint | None = None,
    ) -> None:
        key = graph_extraction_cache_key(identity)
        self.outcomes[key] = phase
        nodes = checkpoint.pruned_nodes if checkpoint is not None else 0
        relationships = checkpoint.pruned_relationships if checkpoint is not None else 0
        if phase in {"reused", "succeeded"}:
            self.pruned_nodes += nodes
            self.pruned_relationships += relationships
        self.execution.emit(identity, phase, duration_s=duration_s,
                            pruned_nodes=nodes, pruned_relationships=relationships)

    def mark_written(self) -> None:
        if self.written:
            raise GraphExtractionCheckpointError("An extraction file can be marked written once")
        if not self.prepared or not self.keys or any(
            self.outcomes.get(key) not in {"reused", "succeeded"} for key in self.keys
        ):
            raise GraphExtractionCheckpointError("File writing cannot finish with incomplete extraction outcomes")
        self.written = True
        # Retain the completion flag and pruning totals needed by the writer
        # and finish_success, but no full inputs or per-chunk recipe copies.
        # This happens only after the official file writer and extractor drain.
        self._official_chunks = ()
        self.identities = ()
        self.keys = ()
        self.outcomes.clear()
        self._schema = self._examples_digest = self._template_digest = ""


@dataclass(slots=True)
class ExtractionCheckpointContext:
    """One building fence owner; recipes and files cannot change within this context.

    Callback exceptions are retained in ``progress_error`` and refuse successful
    completion. They never erase a committed result or trigger fresh extraction.
    Callbacks must enqueue quickly and must not create unowned background work;
    Task 3 owns and drains its persistence queue before ``finish_success``.
    """

    postgres: PostgresClient = field(repr=False)
    repo_id: str
    owner_run_id: str
    recipe: GraphExtractionCheckpointRecipe
    progress: ExtractionProgressCallback | None = field(default=None, repr=False)
    progress_error: Exception | None = field(default=None, init=False, repr=False)
    _files: dict[str, ExtractionFileCheckpoint] = field(default_factory=dict, init=False, repr=False)
    _writes: set[asyncio.Task[None]] = field(default_factory=set, init=False, repr=False)
    _write_error: BaseException | None = field(default=None, init=False, repr=False)
    _sequence: int = field(default=0, init=False)
    _finished: bool = field(default=False, init=False)
    _finishing: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.repo_id.startswith("__staging__") or not self.repo_id.strip():
            raise ValueError("Extraction checkpoints require the base corpus")
        if len(self.owner_run_id) != 32 or any(char not in "0123456789abcdef" for char in self.owner_run_id):
            raise ValueError("Extraction checkpoints require a server-generated owner run id")
        self.recipe = GraphExtractionCheckpointRecipe.model_validate(self.recipe.model_dump(mode="python"))

    def emit(
        self, identity: GraphExtractionCheckpointIdentity, phase: ExtractionPhase,
        *, duration_s: float = 0.0, pruned_nodes: int = 0, pruned_relationships: int = 0,
    ) -> None:
        self._sequence += 1
        event = ExtractionProgress(
            repo_id=self.repo_id, owner_run_id=self.owner_run_id, sequence=self._sequence,
            cache_key=graph_extraction_cache_key(identity), file_path=identity.file_path,
            chunk_id=identity.chunk_id, chunk_index=identity.chunk_index, phase=phase,
            duration_s=max(0.0, duration_s), pruned_nodes=pruned_nodes,
            pruned_relationships=pruned_relationships,
        )
        if self.progress is not None:
            try:
                self.progress(event)
            except Exception as exc:
                if self.progress_error is None:
                    self.progress_error = exc
                    logger.error("Extraction progress consumer failed; generation completion is refused")

    def start_write(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        async def owned_write() -> None:
            try:
                await work
            except BaseException as exc:
                if not isinstance(exc, asyncio.CancelledError) and self._write_error is None:
                    # Preserve completion order rather than iterating an unordered
                    # task set later. Cancellation cannot hide this storage error.
                    self._write_error = exc
                raise

        task = asyncio.create_task(owned_write())
        self._writes.add(task)

        def release_success(completed: asyncio.Task[None]) -> None:
            # Successful writes need no later drain. Keep failures and cancelled
            # tasks owned so cleanup observes them with the original precedence.
            if not completed.cancelled() and completed.exception() is None:
                self._writes.discard(completed)

        task.add_done_callback(release_success)
        return task

    async def drain_writes(self) -> None:
        writes = tuple(self._writes)

        async def drain() -> None:
            try:
                await asyncio.gather(*writes, return_exceptions=True)
            finally:
                self._writes.difference_update(writes)
            if self._write_error is not None:
                raise self._write_error

        await await_checkpoint_task(asyncio.create_task(drain()))

    async def prepare_file(
        self, *, file_path: str, file_sha256: str, chunks: list[Chunk],
        text_chunks: TextChunks, schema: GraphSchema,
        prompt_template: PromptTemplate, examples: str = "",
    ) -> ExtractionFileCheckpoint:
        if self._finished or self._finishing or file_path in self._files:
            raise GraphExtractionCheckpointError("An extraction file can be prepared once per building owner")
        if not chunks or not text_chunks.chunks:
            raise GraphExtractionCheckpointError("File extraction requires nonempty source and official chunks")
        schema = closed_graph_schema(schema)
        if (
            extraction_json(schema.model_dump(mode="json"))
            != extraction_json(closed_graph_schema(self.recipe.approved_schema).model_dump(mode="json"))
            or extraction_digest(prompt_template.template) != self.recipe.prompt_template_sha256
            or extraction_digest(examples) != self.recipe.examples_sha256
        ):
            raise GraphExtractionCheckpointError("File extraction does not use the approved checkpoint recipe")
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        if len(by_id) != len(chunks) or len(chunks) != len(text_chunks.chunks):
            raise GraphExtractionCheckpointError("Selected chunks must have unique identities and matching official inputs")
        identities = []
        for index, official in enumerate(text_chunks.chunks):
            source = by_id.get(official.uid)
            if (source is None or source.file_path != file_path or official.index != index
                    or source.content != official.text):
                raise GraphExtractionCheckpointError("Official extraction input does not match selected source provenance")
            rendered = prompt_template.format(text=official.text,
                schema=schema.model_dump(exclude_none=True), examples=examples)
            identities.append(GraphExtractionCheckpointIdentity(
                repo_id=self.repo_id, file_path=file_path, file_sha256=file_sha256,
                chunk_id=source.chunk_id, chunk_index=index,
                chunk_content_sha256=extraction_digest(official.text),
                chunk_metadata_sha256=extraction_digest(extraction_json({
                    "source": source.metadata, "official": official.metadata,
                })),
                start_line=source.start_line, end_line=source.end_line,
                chunk_provenance=source.provenance.model_copy(deep=True) if source.provenance is not None else None,
                rendered_prompt_sha256=extraction_digest(rendered), recipe=self.recipe.model_copy(deep=True),
            ))
        file = ExtractionFileCheckpoint(
            execution=self, identities=tuple(identities),
            keys=tuple(graph_extraction_cache_key(identity) for identity in identities),
            _official_chunks=tuple(extraction_json(chunk.model_dump(mode="json")) for chunk in text_chunks.chunks),
            _schema=extraction_json(schema.model_dump(mode="json")),
            _examples_digest=extraction_digest(examples),
            _template_digest=extraction_digest(prompt_template.template),
        )
        self._files[file_path] = file
        for identity in file.identities:
            file.emit(identity, "selected")
        try:
            await await_checkpoint_task(self.start_write(self.postgres.prepare_graph_extraction_checkpoint_file(
                self.repo_id, self.owner_run_id, graph_extraction_recipe_hash(self.recipe), file_path, list(file.keys),
            )))
        except BaseException as exc:
            # Preparation precedes the extractor's producer/batch. It therefore
            # owns terminalizing its selected identities after the retained
            # mutation has drained, without implying any native HTTP admission.
            phase: ExtractionPhase = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            for identity in file.identities:
                if file.outcomes.get(graph_extraction_cache_key(identity)) == "selected":
                    file.emit(identity, phase)
            raise
        file.prepared = True
        return file

    async def load(self, identity: GraphExtractionCheckpointIdentity) -> GraphExtractionCheckpoint | None:
        key = graph_extraction_cache_key(identity)
        checkpoint = await self.postgres.get_graph_extraction_checkpoint(self.repo_id, key)
        if checkpoint is None:
            return None
        # Recheck the exact requested identity at the consuming boundary. Never
        # convert corrupt/unreadable/mismatched rows into a fresh paid dispatch.
        if extraction_json(checkpoint.identity.model_dump(mode="json")) != extraction_json(identity.model_dump(mode="json")):
            raise GraphExtractionCheckpointCorruptError("Stored extraction does not match the requested identity")
        return checkpoint.model_copy(deep=True)

    async def finish_success(self) -> None:
        """After full file writes and invariant checks, before building -> promotion."""
        if self._finished or self._finishing:
            raise GraphExtractionCheckpointError("Checkpoint completion is one owned operation")
        if self._write_error is not None:
            raise self._write_error
        if self.progress_error is not None:
            raise GraphExtractionCheckpointError("Extraction progress did not persist successfully") from self.progress_error
        if any(not file.written for file in self._files.values()) or any(not task.done() for task in self._writes):
            raise GraphExtractionCheckpointError("Checkpoint completion requires all file writes and checkpoint drains")
        self._finishing = True
        await await_checkpoint_task(self.start_write(self.postgres.finish_graph_extraction_checkpoint_run(
            self.repo_id, self.owner_run_id, graph_extraction_recipe_hash(self.recipe), sorted(self._files),
        )))
        self._finished = True
