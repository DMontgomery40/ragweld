from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from string import Formatter
from typing import Any, TypeVar

import httpx
from neo4j import Driver
from neo4j_graphrag.components.entity_relation_extractor import (
    LLMEntityRelationExtractor,
    OnError,
)
from neo4j_graphrag.components.graph_pruning import GraphPruning
from neo4j_graphrag.components.kg_writer import KGWriterModel, Neo4jWriter
from neo4j_graphrag.components.lexical_graph import LexicalGraphBuilder
from neo4j_graphrag.components.resolver import SinglePropertyExactMatchResolver
from neo4j_graphrag.components.schema import GraphSchema
from neo4j_graphrag.components.types import (
    DocumentInfo,
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
    TextChunk,
    TextChunks,
)
from neo4j_graphrag.exceptions import PromptMissingPlaceholderError
from neo4j_graphrag.experimental.pipeline import Pipeline
from neo4j_graphrag.generation.prompts import ERExtractionTemplate
from neo4j_graphrag.llm import OpenAILLM
from neo4j_graphrag.utils.rate_limit import NoOpRateLimitHandler

from server.gateway_reasoning import reasoning_model_params
from server.indexing.code_graph import CODE_GRAPH_LANGUAGES, extract_code_graph
from server.indexing.extraction_checkpoint import (
    ExtractionCheckpointContext,
    ExtractionFileCheckpoint,
    await_checkpoint_task,
    extraction_digest,
    extraction_json,
)
from server.indexing.graph_policy import GraphPolicy
from server.indexing.graphrag_schema import closed_graph_schema
from server.model_policy import ensure_model_allowed
from server.models.graph_extraction_checkpoint import (
    GraphExtractionCheckpoint,
    GraphExtractionCheckpointCorruptError,
    GraphExtractionCheckpointError,
    GraphExtractionCheckpointIdentity,
    GraphExtractionCheckpointRecipe,
    graph_extraction_cache_key,
    graph_extraction_recipe_hash,
)
from server.models.index import Chunk, GraphResolutionTelemetry
from server.models.tribrid_config_model import TriBridConfig
from server.observability.run_census import CensusAsyncTransport, CensusTransport, RunCensusScope

ResultT = TypeVar("ResultT")

logger = logging.getLogger(__name__)

RESERVED_SCOPE_KEYS = frozenset({"repo_id", "run_id", "graphJoinId", "__tmp_internal_id"})
_WRITER_TEMP_PREFIX: ContextVar[str | None] = ContextVar("graphrag_writer_temp_prefix", default=None)
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STAGING_GRAPH_RE = re.compile(
    r"^__staging__[A-Za-z0-9][A-Za-z0-9._-]*__[0-9a-f]{32}$"
)


class GraphScopeCollisionError(ValueError):
    """An extracted graph tried to supply a property owned by the server scope."""


@dataclass(frozen=True, slots=True)
class GraphFileTelemetry:
    selected_chunks: int
    attempted_chunks: int
    succeeded_chunks: int
    failed_chunks: int
    extracted_entities: int
    semantic_relationships: int
    from_chunk_relationships: int
    pruned_nodes: int
    pruned_relationships: int


def require_run_id(value: str) -> str:
    run_id = str(value or "").strip()
    if not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("graph writer run_id must be exactly 32 lowercase hexadecimal characters")
    return run_id


def require_staging_graph_id(value: str) -> str:
    repo_id = str(value or "").strip()
    if not _STAGING_GRAPH_RE.fullmatch(repo_id):
        raise ValueError(
            "graph writer repo_id must be a server-generated __staging__<corpus>__<32-hex-run> id"
        )
    require_run_id(repo_id.rsplit("__", 1)[-1])
    return repo_id


def validate_no_reserved_scope_keys(
    graph: Neo4jGraph, keys: frozenset[str] = RESERVED_SCOPE_KEYS
) -> None:
    for node in graph.nodes:
        collision = keys & set(node.properties or {})
        if collision:
            key = sorted(collision)[0]
            raise GraphScopeCollisionError(
                f"node {node.id!r} contains reserved scope key {key!r}"
            )
    for relationship in graph.relationships:
        collision = keys & set(relationship.properties or {})
        if collision:
            key = sorted(collision)[0]
            raise GraphScopeCollisionError(
                "relationship "
                f"{relationship.start_node_id!r}-[{relationship.type}]->{relationship.end_node_id!r} "
                f"contains reserved scope key {key!r}"
            )


def stamp_graph_scope(
    graph: Neo4jGraph,
    *,
    repo_id: str,
    run_id: str,
    lexical: LexicalGraphConfig,
) -> None:
    scoped_repo_id = require_staging_graph_id(repo_id)
    scoped_run_id = require_run_id(run_id)
    lexical_labels = set(lexical.lexical_graph_node_labels)
    for node in graph.nodes:
        properties = dict(node.properties or {})
        properties["repo_id"] = scoped_repo_id
        properties["run_id"] = scoped_run_id
        if node.label == lexical.document_node_label:
            properties["document_id"] = str(node.id)
            properties["file_path"] = str(
                properties.get("file_path") or properties.get("path") or ""
            )
        elif node.label == lexical.chunk_node_label:
            chunk_id = str(
                properties.get("chunk_id")
                or properties.get(lexical.chunk_id_property)
                or node.id
            )
            properties["chunk_id"] = chunk_id
            properties["graphJoinId"] = f"{scoped_repo_id}:{chunk_id}"
            properties.pop("embedding", None)
            properties.pop(str(lexical.chunk_embedding_property or "embedding"), None)
        elif node.label not in lexical_labels:
            properties["entity_id"] = str(node.id)
            properties["entity_type"] = str(node.label)
        node.properties = properties
    for relationship in graph.relationships:
        relationship.properties = {
            **dict(relationship.properties or {}),
            "repo_id": scoped_repo_id,
            "run_id": scoped_run_id,
        }


def run_writer_coroutine_in_worker(
    run: Callable[
        [Neo4jGraph, LexicalGraphConfig], Coroutine[Any, Any, KGWriterModel]
    ],
    graph: Neo4jGraph,
    lexical_graph_config: LexicalGraphConfig,
) -> KGWriterModel:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("GraphRAG writer helper must run on a worker thread")
    return asyncio.run(run(graph, lexical_graph_config))


def run_component_coroutine_in_worker(
    run: Callable[[], Coroutine[Any, Any, ResultT]],
) -> ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("GraphRAG component helper must run on a worker thread")
    return asyncio.run(run())


async def run_async_component_off_event_loop(
    run: Callable[[], Coroutine[Any, Any, ResultT]],
) -> ResultT:
    return await asyncio.to_thread(run_component_coroutine_in_worker, run)


def cypher_literal(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _execute_query_rows(
    driver: Driver,
    query: str,
    parameters: dict[str, Any],
    database: str,
) -> list[dict[str, Any]]:
    records, _, _ = driver.execute_query(query, parameters_=parameters, database_=database)
    return [dict(record) for record in records]


def resolution_property_for_policy(policy: GraphPolicy | str) -> str:
    """The identity exact-match resolution merges on, per graph policy.

    A semantic entity is what the approved schema extracted under a name, so equal
    names within one generation are the same thing. A code entity is identified by
    its qualified id (``path::Qualified.symbol``); merging on the bare name collapsed
    every ``__init__`` and ``main`` of the corpus into one node (Task 8 drive defect D7).
    """
    if policy == "semantic":
        return "name"
    if policy == "code":
        return "entity_id"
    raise ValueError(f"graph policy {policy!r} does not build a resolvable graph")


async def resolve_staged_entities(
    *,
    driver: Driver,
    neo4j_database: str,
    repo_id: str,
    policy: GraphPolicy | str,
) -> GraphResolutionTelemetry:
    scoped_repo_id = require_staging_graph_id(repo_id)
    resolve_property = resolution_property_for_policy(policy)
    resolver = SinglePropertyExactMatchResolver(
        driver=driver,
        filter_query=f"WHERE entity.repo_id = {cypher_literal(scoped_repo_id)} ",
        resolve_property=resolve_property,
        neo4j_database=neo4j_database,
    )
    stats = await run_async_component_off_event_loop(resolver.run)
    rows = await asyncio.to_thread(
        _execute_query_rows,
        driver,
        """
        MATCH (entity:__Entity__ {repo_id: $repo_id})
        WITH count(entity) AS resolved_nodes
        CALL () {
            MATCH (entity:__Entity__ {repo_id: $repo_id})
            WHERE entity[$resolve_property] IS NOT NULL
            WITH entity[$resolve_property] AS identity,
                 apoc.coll.sort([label IN labels(entity)
                    WHERE NOT label IN ['__Entity__', '__KGBuilder__']]) AS domain_labels,
                 count(*) AS n
            WHERE n > 1
            RETURN count(*) AS duplicate_groups
        }
        RETURN resolved_nodes, duplicate_groups
        """,
        {"repo_id": scoped_repo_id, "resolve_property": resolve_property},
        neo4j_database,
    )
    row = rows[0] if rows else {}
    candidates = int(stats.number_of_nodes_to_resolve or 0)
    resolved = int(row.get("resolved_nodes") or 0)
    return GraphResolutionTelemetry(
        candidate_nodes=candidates,
        resolved_nodes=resolved,
        merged_nodes=max(0, candidates - resolved),
        unresolved_duplicate_groups=int(row.get("duplicate_groups") or 0),
    )


def fold_duplicate_node_ids(graph: Neo4jGraph) -> tuple[Neo4jGraph, dict[str, int]]:
    """Make extracted node ids unique before the official writer sees them.

    The 1.19 writer ``CREATE``s one node per row, so a model response that repeats a
    node id inside one chunk yields duplicate writer rows. Rows identifying the same
    named entity fold into the first occurrence. Conflicting names or labels are
    ambiguous: relationships cannot identify which entity they meant, and renaming
    one node would silently remove its provenance. Refuse the graph before writing.
    """
    kept: list[Neo4jNode] = []
    position: dict[str, int] = {}
    folded = 0
    for node in graph.nodes:
        index = position.get(node.id)
        if index is None:
            position[node.id] = len(kept)
            kept.append(node)
            continue
        first = kept[index]
        if first.label == node.label and (first.properties or {}).get("name") == (
            node.properties or {}
        ).get("name"):
            merged = dict(node.properties or {})
            merged.update(first.properties or {})
            kept[index] = first.model_copy(update={"properties": merged})
            folded += 1
            continue
        raise ValueError(
            f"GraphRAG node id {node.id!r} has conflicting identity; "
            "the extraction must use a distinct id for each named entity."
        )
    if not folded:
        return graph, {"folded_same_label": 0}
    return (
        Neo4jGraph(nodes=kept, relationships=list(graph.relationships)),
        {"folded_same_label": folded},
    )



class ScopedNeo4jWriter(Neo4jWriter):
    def __init__(self, *args: Any, repo_id: str, run_id: str, **kwargs: Any) -> None:
        self.repo_id = require_staging_graph_id(repo_id)
        self.run_id = require_run_id(run_id)
        if self.repo_id.rsplit("__", 1)[-1] != self.run_id:
            raise ValueError("graph writer run_id must match the staging graph generation")
        super().__init__(*args, **kwargs)

    def _db_cleaning(self) -> None:
        """Clean only this writer's temporary endpoint IDs, in its configured database.

        The pinned writer's default cleanup is database-wide. Complete semantic writes
        need invocation scope because another file write may still be using its IDs;
        deferred code writes keep their generation namespace until finalize().
        """
        if self._clean_db:
            prefix = _WRITER_TEMP_PREFIX.get()
            if prefix is None or not prefix.startswith(f"{self.repo_id}:write:"):
                raise RuntimeError("GraphRAG writer cleanup requires its invocation scope")
        else:
            prefix = f"{self.repo_id}:deferred:"
        query = f"""
            MATCH (n:__KGBuilder__ {{repo_id: $repo_id}})
            WHERE n.__tmp_internal_id STARTS WITH $writer_prefix
            CALL (n) {{ REMOVE n.__tmp_internal_id }}
            IN TRANSACTIONS OF {int(self.batch_size)} ROWS
        """
        with self.driver.session(database=self.neo4j_database) as session:
            session.run(query, repo_id=self.repo_id, writer_prefix=prefix).consume()

    async def run(
        self,
        graph: Neo4jGraph,
        lexical_graph_config: LexicalGraphConfig | None = None,
    ) -> KGWriterModel:
        # Pipeline edges persist component results through ``model_dump`` and
        # therefore hand downstream components plain dictionaries. The parent
        # method's validate_call normally restores the model; this override owns
        # the boundary and must do so before inspecting or stamping properties.
        graph = Neo4jGraph.model_validate(graph).model_copy(deep=True)
        graph, duplicate_ids = fold_duplicate_node_ids(graph)
        if duplicate_ids["folded_same_label"]:
            logger.warning(
                "GraphRAG extraction repeated identical entity ids for %s: folded=%d",
                self.repo_id,
                duplicate_ids["folded_same_label"],
            )
        lexical_graph_config = lexical_graph_config or LexicalGraphConfig()
        validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)
        stamp_graph_scope(
            graph,
            repo_id=self.repo_id,
            run_id=self.run_id,
            lexical=lexical_graph_config,
        )
        # The official writer resolves endpoints using a database-wide temporary id.
        # Qualify that id without changing the canonical IDs stamped into properties.
        writer_prefix = (
            f"{self.repo_id}:write:{uuid.uuid4().hex}:"
            if self._clean_db else f"{self.repo_id}:deferred:"
        )
        for node in graph.nodes:
            node.id = f"{writer_prefix}{node.id}"
        for relationship in graph.relationships:
            relationship.start_node_id = f"{writer_prefix}{relationship.start_node_id}"
            relationship.end_node_id = f"{writer_prefix}{relationship.end_node_id}"
        base_run = super().run
        token = _WRITER_TEMP_PREFIX.set(writer_prefix)
        try:
            result = await asyncio.to_thread(
                run_writer_coroutine_in_worker,
                base_run,
                graph,
                lexical_graph_config,
            )
        finally:
            _WRITER_TEMP_PREFIX.reset(token)
        if result.status != "SUCCESS":
            raise RuntimeError(f"Neo4j GraphRAG writer failed: {result.metadata}")
        return result

    async def finalize(self) -> None:
        if not self._clean_db:
            await asyncio.to_thread(self._db_cleaning)


def lexical_graph_config() -> LexicalGraphConfig:
    return LexicalGraphConfig()


def chunks_to_text_chunks(chunks: list[Chunk]) -> TextChunks:
    ordered = sorted(chunks, key=lambda chunk: (int(chunk.start_line or 0), chunk.chunk_id))
    rows: list[TextChunk] = []
    for index, chunk in enumerate(ordered):
        rows.append(
            TextChunk(
                text=str(chunk.content or ""),
                index=index,
                metadata={
                    "chunk_id": str(chunk.chunk_id),
                    "file_path": str(chunk.file_path),
                    "start_line": int(chunk.start_line or 0),
                    "end_line": int(chunk.end_line or 0),
                },
                uid=str(chunk.chunk_id),
            )
        )
    return TextChunks(chunks=rows)


DOCUMENT_NODE_ID_PREFIX = "document::"


def document_node_id(file_path: str) -> str:
    """Writer id of a file's lexical ``Document`` node.

    The id is namespaced so it can never equal a code ``module`` entity id, which
    is the bare file path. The official writer matches relationship endpoints by
    writer id regardless of label, so a shared id copied every module edge onto
    the Document node and pointed the chunks' FROM_DOCUMENT edges at the module
    entity (Task 8 drive defect D18).
    """
    path = str(file_path or "").strip()
    if not path:
        raise ValueError("document_node_id needs a file path")
    return f"{DOCUMENT_NODE_ID_PREFIX}{path}"


def document_info(file_path: str) -> DocumentInfo:
    return DocumentInfo(
        path=file_path,
        metadata={"file_path": file_path},
        uid=document_node_id(file_path),
    )


def assemble_code_file_graph(lexical_graph: Neo4jGraph, code_graph: Neo4jGraph) -> Neo4jGraph:
    """One file's lexical and code graphs as the single graph the writer receives.

    Writer ids must be unique across both halves: the official writer creates one
    node per id and resolves relationship endpoints by id, so a collision would
    silently mis-wire the graph instead of failing.
    """
    nodes = [*lexical_graph.nodes, *code_graph.nodes]
    owners: dict[str, str] = {}
    for node in nodes:
        previous = owners.get(node.id)
        if previous is not None:
            raise ValueError(
                f"writer id {node.id!r} is shared by a {previous} node and a {node.label} node"
            )
        owners[node.id] = str(node.label)
    return Neo4jGraph(
        nodes=nodes,
        relationships=[*lexical_graph.relationships, *code_graph.relationships],
    )


def semantic_extraction_llm(
    *,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    route_upstream: str,
    llm_timeout_s: int,
    reasoning_effort: str,
    census_scope: RunCensusScope | None = None,
) -> OpenAILLM:
    """The official OpenAILLM for semantic extraction, carrying the operator's controls.

    ``graph_indexing.semantic_kg_llm_timeout_s`` bounds every gateway call (the OpenAI
    client's request timeout) and ``semantic_kg_reasoning_effort`` is sent with every
    request in the upstream's own protocol (:func:`reasoning_model_params`); the Indexing
    page showed both, but neither reached the pipeline before (Task 8 drive defect D9).
    """
    ensure_model_allowed(route_model)
    ensure_model_allowed(route_upstream)
    if not str(route_model or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires a resolved model id")
    if not str(route_base_url or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires a resolved base URL")
    if not str(route_api_key or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires an authenticated route")
    if int(llm_timeout_s) <= 0:
        raise RuntimeError("GraphRAG semantic extraction requires a positive per-chunk timeout")
    if census_scope is not None and census_scope.identity.lane != "semantic_kg":
        raise ValueError("semantic extraction requires the semantic_kg census lane")
    client_options: dict[str, Any] = {}
    if census_scope is not None:
        client_options["http_client"] = httpx.AsyncClient(
            transport=CensusAsyncTransport(census_scope), timeout=float(llm_timeout_s),
        )
    llm = OpenAILLM(
        model_name=str(route_model).strip(),
        model_params=reasoning_model_params(
            reasoning_effort=reasoning_effort, route_upstream=route_upstream
        ),
        api_key=str(route_api_key).strip(),
        base_url=str(route_base_url).strip(),
        timeout=float(int(llm_timeout_s)),
        # Both libraries retry independently by default. One extraction call
        # must dispatch once so a timeout cannot silently multiply paid work.
        max_retries=0,
        rate_limit_handler=NoOpRateLimitHandler(),
        **client_options,
    )
    if census_scope is not None:
        # The official wrapper accepts one HTTP client and splits it by sync/async
        # type. The public OpenAI copy API attaches the other without replacing it.
        original = llm.client
        llm.client = original.with_options(http_client=httpx.Client(
            transport=CensusTransport(census_scope), timeout=float(llm_timeout_s),
        ))
        original.close()
    return llm


# The official extractor formats the template with these keyword arguments
# (``LLMEntityRelationExtractor.extract_for_chunk``); a template missing ``{schema}`` or
# ``{text}`` would extract against no schema or no text. ``{examples}`` is optional.
EXTRACTION_TEMPLATE_REQUIRED_PLACEHOLDERS: tuple[str, ...] = ("{schema}", "{text}")


def extraction_prompt_template(text: str) -> ERExtractionTemplate:
    """The operator's Semantic KG Extraction prompt as the official extraction template.

    ``system_prompts.semantic_kg_extraction`` is shown and edited on the System Prompts page
    but never reached the official pipeline, which ran the library's default template (Task 8
    drive finding D24); that template says nothing about what a ``name`` may be, so Luna named
    email-corpus persons and emails with OCR noise (D19). The operator text is now the template the
    extractor formats, so it must carry the placeholders the extractor fills.
    """
    template = str(text or "")
    if not template.strip():
        raise ValueError(
            "GraphRAG extraction prompt is empty; it must carry the {schema} and {text} placeholders"
        )
    # Each required input needs one complete top-level occurrence. Escaping,
    # projections, nested fields and precision/width specs cannot satisfy that
    # guarantee. Extra occurrences may format/truncate once a complete one exists.
    complete_fields = {
        field_name for _literal, field_name, format_spec, conversion in Formatter().parse(template)
        if field_name is not None and not format_spec and conversion in {None, "s", "r", "a"}
    }
    missing = [
        placeholder
        for placeholder in EXTRACTION_TEMPLATE_REQUIRED_PLACEHOLDERS
        if placeholder[1:-1] not in complete_fields
    ]
    if missing:
        raise ValueError(
            f"GraphRAG extraction prompt must include complete input values for {', '.join(missing)}; "
            "use each at least once as a direct field without a format specification. "
            "The s/r/a conversions are supported."
        )
    try:
        return ERExtractionTemplate(template=template)
    except PromptMissingPlaceholderError as exc:
        # The official public constructor additionally requires literal {text}.
        # Keep its supported contract and unchanged rendering; never rewrite the
        # template or bypass the constructor to accept conversion-only forms.
        raise ValueError(
            "The official GraphRAG template requires a literal {text} placeholder "
            "in addition to any converted or formatted occurrences."
        ) from exc



_EXTRACTION_CHECKPOINT_VERSION = "official-structured-extraction-v1"
_PRUNING_CHECKPOINT_VERSION = "official-domain-pruning-and-identity-v1"


def extraction_checkpoint_recipe(
    *, schema: GraphSchema, prompt_template: str, route_model: str,
    route_upstream: str, route_base_url: str, reasoning_effort: str, examples: str = "",
) -> GraphExtractionCheckpointRecipe:
    """The exact approved semantic inputs; transport controls and credentials stay out."""
    template = extraction_prompt_template(prompt_template)
    return GraphExtractionCheckpointRecipe(
        approved_schema=closed_graph_schema(schema),
        prompt_template_sha256=extraction_digest(template.template),
        examples_sha256=extraction_digest(examples),
        model_alias=route_model.strip(), model_upstream=route_upstream.strip(),
        model_endpoint=route_base_url.strip(),
        model_parameters=reasoning_model_params(
            reasoning_effort=reasoning_effort, route_upstream=route_upstream,
        ),
        neo4j_graphrag_version=version("neo4j-graphrag"),
        extractor_version=_EXTRACTION_CHECKPOINT_VERSION,
        pruner_version=_PRUNING_CHECKPOINT_VERSION,
    )


async def _pruned_extraction_checkpoint(
    *, identity: GraphExtractionCheckpointIdentity, owner_run_id: str,
    graph: Neo4jGraph, schema: GraphSchema,
) -> GraphExtractionCheckpoint:
    # Validate scope/official shape before pruning can remove evidence of a
    # collision. Lexical entities/links are exclusively produced by the official
    # lexical postprocessor after this durable domain-only boundary.
    raw = GraphExtractionCheckpoint(
        identity=identity, cache_key=graph_extraction_cache_key(identity),
        originating_run_id=owner_run_id, created_at=datetime.now(UTC),
        graph=graph, pruned_nodes=0, pruned_relationships=0,
    )
    lexical = lexical_graph_config()
    if (any(node.label in lexical.lexical_graph_node_labels for node in raw.graph.nodes)
            or any(rel.type in lexical.lexical_graph_relationship_types for rel in raw.graph.relationships)):
        raise GraphScopeCollisionError("Raw extraction contains server-owned lexical nodes or relationships")
    folded, _ = fold_duplicate_node_ids(raw.graph.model_copy(deep=True))
    pruned = await GraphPruning().run(graph=folded, schema=schema, lexical_graph_config=lexical)
    return GraphExtractionCheckpoint(
        identity=identity, cache_key=raw.cache_key, originating_run_id=owner_run_id,
        created_at=raw.created_at, graph=pruned.graph,
        pruned_nodes=max(0, len(raw.graph.nodes) - len(pruned.graph.nodes)),
        pruned_relationships=max(0, len(raw.graph.relationships) - len(pruned.graph.relationships)),
    )


@dataclass
class _ExtractionBatch:
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    commits: set[asyncio.Task[None]] = field(default_factory=set)
    commit_error: BaseException | None = None
    checkpoint_context: ExtractionFileCheckpoint | None = None
    closing: bool = False


_EXTRACTION_BATCH: ContextVar[_ExtractionBatch | None] = ContextVar(
    "graphrag_extraction_batch", default=None,
)


class _DrainingExtractor(LLMEntityRelationExtractor):
    """Keep official extraction, but drain gather siblings before releasing its producer."""

    def __init__(
        self, *, census_scope: RunCensusScope | None,
        checkpoint_context: ExtractionCheckpointContext | None = None, **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.census_scope = census_scope
        self.checkpoint_context = checkpoint_context
        self.active_runs: set[asyncio.Task[Any]] = set()
        self.drains: set[asyncio.Task[None]] = set()
        self.closed = False

    async def run(
        self, chunks: TextChunks, document_info: DocumentInfo | None = None,
        lexical_graph_config: LexicalGraphConfig | None = None,
        schema: GraphSchema | None = None, examples: str = "",
        checkpoint_context: ExtractionFileCheckpoint | None = None, **kwargs: Any,
    ) -> Neo4jGraph:
        if self.closed:
            raise RuntimeError("semantic pipeline is closed")
        if self.checkpoint_context is not None:
            if checkpoint_context is None or checkpoint_context.execution is not self.checkpoint_context:
                raise GraphExtractionCheckpointError("Extractor requires its explicitly prepared checkpoint file")
            if schema is None:
                raise GraphExtractionCheckpointError("Checkpoint extraction requires its approved schema")
            schema = closed_graph_schema(schema)
            checkpoint_context.validate_inputs(chunks, schema, examples, self.prompt_template)
        elif checkpoint_context is not None:
            raise GraphExtractionCheckpointError("Checkpoint file does not belong to this extractor")
        lease = self.census_scope.producer_started() if self.census_scope else None
        owner = asyncio.current_task()
        assert owner is not None
        self.active_runs.add(owner)
        batch = _ExtractionBatch(checkpoint_context=checkpoint_context)
        token = _EXTRACTION_BATCH.set(batch)
        try:
            return await super().run(
                chunks=chunks, document_info=document_info,
                lexical_graph_config=lexical_graph_config, schema=schema,
                examples=examples, **kwargs,
            )
        finally:
            batch.closing = True
            _EXTRACTION_BATCH.reset(token)

            async def drain() -> None:
                cleanup_error: BaseException | None = None
                try:
                    for task in batch.tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*batch.tasks, return_exceptions=True)
                    # Once a validated graph starts its database commit, cancellation
                    # can stop extraction but cannot orphan that writer or its fence.
                    await asyncio.gather(*batch.commits, return_exceptions=True)
                    if checkpoint_context is not None:
                        for identity in checkpoint_context.identities:
                            key = graph_extraction_cache_key(identity)
                            if checkpoint_context.outcomes.get(key) == "selected":
                                checkpoint_context.emit(identity, "cancelled")
                except BaseException as exc:
                    cleanup_error = exc
                finally:
                    if lease is not None:
                        try:
                            lease.close()
                        except BaseException as exc:
                            if cleanup_error is None:
                                cleanup_error = exc
                if batch.commit_error is not None:
                    raise batch.commit_error
                if cleanup_error is not None:
                    raise cleanup_error

            cleanup = asyncio.create_task(drain())
            self.drains.add(cleanup)
            try:
                # A second cancellation must not release the producer while siblings
                # still own HTTP requests. Pipeline close also waits for this task.
                await await_checkpoint_task(cleanup)
            finally:
                self.active_runs.discard(owner)
                if cleanup.done():
                    self.drains.discard(cleanup)

    async def run_for_chunk(
        self, sem: asyncio.Semaphore, chunk: TextChunk, schema: GraphSchema,
        examples: str, lexical_graph_builder: LexicalGraphBuilder | None = None,
    ) -> Neo4jGraph:
        batch = _EXTRACTION_BATCH.get()
        if batch is not None:
            if batch.closing:
                raise asyncio.CancelledError()
            task = asyncio.current_task()
            assert task is not None
            batch.tasks.add(task)
        return await super().run_for_chunk(
            sem, chunk, schema, examples, lexical_graph_builder,
        )

    async def cancel_and_drain(self) -> None:
        self.closed = True
        owners = tuple(self.active_runs)
        for task in owners:
            task.cancel()

        async def drain_all() -> None:
            # All owners and producer drains settle before an error escapes.
            # The context retains the first storage failure even if the file
            # owner was cancelled or has already observed and removed its drain.
            owner_results = await asyncio.gather(*owners, return_exceptions=True)
            drain_results = await asyncio.gather(*self.drains, return_exceptions=True)
            self.drains.clear()
            if self.checkpoint_context is not None:
                await self.checkpoint_context.drain_writes()
            for result in (*owner_results, *drain_results):
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result

        await await_checkpoint_task(asyncio.create_task(drain_all()))

    async def extract_for_chunk(
        self, schema: GraphSchema, examples: str, chunk: TextChunk,
    ) -> Neo4jGraph:
        """Reuse only at the official pre-lexical, semaphore-admitted boundary."""
        batch = _EXTRACTION_BATCH.get()
        if self.checkpoint_context is None:
            return await super().extract_for_chunk(schema, examples, chunk)
        if batch is None or batch.checkpoint_context is None:
            raise GraphExtractionCheckpointError("Extraction checkpoint is missing its producer ownership")
        file = batch.checkpoint_context
        identity = file.identity_for(chunk)
        if batch.closing:
            file.emit(identity, "cancelled")
            raise asyncio.CancelledError()
        file.emit(identity, "admitted")
        dispatch_started: float | None = None
        commit: asyncio.Task[None] | None = None
        try:
            stored = await self.checkpoint_context.load(identity)
            if stored is not None:
                # A valid envelope also has to remain a valid domain graph under
                # its recipe. Do not repair a poisoned cache and call it a hit.
                try:
                    checked = await _pruned_extraction_checkpoint(
                        identity=identity, owner_run_id=self.checkpoint_context.owner_run_id,
                        graph=stored.graph.model_copy(deep=True), schema=schema,
                    )
                except ValueError as exc:
                    raise GraphExtractionCheckpointCorruptError("Stored extraction graph violates its domain contract") from exc
                if extraction_json(checked.graph.model_dump(mode="json")) != extraction_json(stored.graph.model_dump(mode="json")):
                    raise GraphExtractionCheckpointCorruptError("Stored extraction graph was not pruned with its exact recipe")
                file.emit(identity, "reused", checkpoint=stored)
                return stored.graph.model_copy(deep=True)
            file.emit(identity, "dispatching")
            dispatch_started = time.perf_counter()
            graph = await super().extract_for_chunk(schema, examples, chunk)
            duration_s = max(0.0, time.perf_counter() - dispatch_started)
            checkpoint = await _pruned_extraction_checkpoint(
                identity=identity, owner_run_id=self.checkpoint_context.owner_run_id,
                graph=graph, schema=schema,
            )

            async def persist() -> None:
                try:
                    await file.execution.postgres.put_graph_extraction_checkpoint(
                        file.execution.repo_id, file.execution.owner_run_id, checkpoint,
                    )
                except BaseException as exc:
                    batch.closing = True
                    if not isinstance(exc, asyncio.CancelledError) and batch.commit_error is None:
                        batch.commit_error = exc
                    file.emit(identity, "failed", duration_s=duration_s)
                    raise
                file.emit(identity, "succeeded", duration_s=duration_s, checkpoint=checkpoint)

            commit = self.checkpoint_context.start_write(persist())
            batch.commits.add(commit)
            await asyncio.shield(commit)
            return checkpoint.graph.model_copy(deep=True)
        except BaseException as exc:
            batch.closing = True
            if commit is None:
                file.emit(identity, "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                          duration_s=max(0.0, time.perf_counter() - dispatch_started) if dispatch_started is not None else 0.0)
            raise


class SemanticPipeline(Pipeline):
    """Official pipeline with explicit ownership of extractor work and SDK clients."""

    def __init__(self, llm: OpenAILLM, extractor: _DrainingExtractor, *, examples: str = "") -> None:
        super().__init__()
        self._owned_llm = llm
        self._owned_extractor = extractor
        self.checkpoint_context = extractor.checkpoint_context
        self.extraction_examples = examples
        self._close_task: asyncio.Task[None] | None = None

    async def aclose(self) -> None:
        if self._close_task is None:
            async def close() -> None:
                error: BaseException | None = None
                try:
                    await self._owned_extractor.cancel_and_drain()
                except BaseException as exc:
                    error = exc
                try:
                    await self._owned_llm.aclose()
                except BaseException as exc:
                    if error is None or isinstance(error, asyncio.CancelledError):
                        error = exc
                if error is not None:
                    raise error
            self._close_task = asyncio.create_task(close())
        await await_checkpoint_task(self._close_task)


async def close_semantic_pipeline(pipeline: Pipeline) -> None:
    if isinstance(pipeline, SemanticPipeline):
        await pipeline.aclose()


def semantic_entity_relation_extractor(
    *,
    llm: OpenAILLM,
    prompt_template: str,
    max_concurrency: int,
    census_scope: RunCensusScope | None = None,
    checkpoint_context: ExtractionCheckpointContext | None = None,
) -> _DrainingExtractor:
    """The official extractor over the operator's template, strict structured output, fail closed."""
    template = extraction_prompt_template(prompt_template)
    if checkpoint_context is not None:
        recipe = checkpoint_context.recipe
        if (
            extraction_digest(template.template) != recipe.prompt_template_sha256
            or llm.model_name != recipe.model_alias
            or extraction_json(llm.model_params) != extraction_json(recipe.model_parameters)
            or str(llm.async_client.base_url) != str(httpx.URL(recipe.model_endpoint)).rstrip("/") + "/"
            or recipe.neo4j_graphrag_version != version("neo4j-graphrag")
            or recipe.extractor_version != _EXTRACTION_CHECKPOINT_VERSION
            or recipe.pruner_version != _PRUNING_CHECKPOINT_VERSION
        ):
            raise GraphExtractionCheckpointError("Official extractor does not match the approved checkpoint recipe")
    return _DrainingExtractor(
        census_scope=census_scope,
        checkpoint_context=checkpoint_context,
        llm=llm,
        prompt_template=template,
        create_lexical_graph=True,
        on_error=OnError.RAISE,
        max_concurrency=max(1, int(max_concurrency)),
        use_structured_output=True,
    )


def build_semantic_pipeline(
    *,
    driver: Driver,
    neo4j_database: str,
    repo_id: str,
    run_id: str,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    route_upstream: str,
    max_concurrency: int,
    llm_timeout_s: int,
    reasoning_effort: str,
    prompt_template: str,
    census_scope: RunCensusScope | None = None,
    checkpoint_context: ExtractionCheckpointContext | None = None,
    examples: str = "",
) -> SemanticPipeline:
    if checkpoint_context is not None:
        staging_id = require_staging_graph_id(repo_id)
        corpus_id = staging_id[len("__staging__"):].rsplit("__", 1)[0]
        if checkpoint_context.repo_id != corpus_id or checkpoint_context.owner_run_id != run_id:
            raise GraphExtractionCheckpointError("Checkpoint owner does not match the staging generation")
        expected_recipe = extraction_checkpoint_recipe(
            schema=checkpoint_context.recipe.approved_schema, prompt_template=prompt_template,
            examples=examples, route_model=route_model, route_base_url=route_base_url,
            route_upstream=route_upstream, reasoning_effort=reasoning_effort,
        )
        if graph_extraction_recipe_hash(expected_recipe) != graph_extraction_recipe_hash(checkpoint_context.recipe):
            raise GraphExtractionCheckpointError("Pipeline inputs do not match the approved checkpoint recipe")
    if census_scope is not None:
        staging_id = require_staging_graph_id(repo_id)
        corpus_id = staging_id[len("__staging__"):].rsplit("__", 1)[0]
        if (census_scope.identity.session_id != run_id
                or census_scope.identity.corpus_id != corpus_id):
            raise ValueError("semantic census identity does not match the staging run")
    llm = semantic_extraction_llm(
        route_model=route_model,
        route_base_url=route_base_url,
        route_api_key=route_api_key,
        route_upstream=route_upstream,
        llm_timeout_s=llm_timeout_s,
        reasoning_effort=reasoning_effort,
        census_scope=census_scope,
    )
    extractor = semantic_entity_relation_extractor(
        llm=llm, prompt_template=prompt_template, max_concurrency=max_concurrency,
        census_scope=census_scope,
        checkpoint_context=checkpoint_context,
    )
    writer = ScopedNeo4jWriter(
        driver=driver,
        neo4j_database=neo4j_database,
        repo_id=repo_id,
        run_id=run_id,
    )
    pipeline = SemanticPipeline(llm, extractor, examples=examples)
    pipeline.add_component(extractor, "extractor")
    pipeline.add_component(GraphPruning(), "pruner")
    pipeline.add_component(writer, "writer")
    # This pipeline receives the already approved GraphSchema as run data; it
    # does not contain the template's separate SchemaBuilder component. Only
    # the extractor graph is connected here, while ``pruner.schema`` is the
    # exact persisted schema supplied below.
    pipeline.connect("extractor", "pruner", {"graph": "extractor"})
    pipeline.connect("pruner", "writer", {"graph": "pruner.graph"})
    return pipeline


def _graph_counts(
    graph: Neo4jGraph, lexical: LexicalGraphConfig
) -> tuple[int, int, int]:
    lexical_labels = set(lexical.lexical_graph_node_labels)
    entity_ids = {str(node.id) for node in graph.nodes if node.label not in lexical_labels}
    entity_relationships = 0
    from_chunk_relationships = 0
    for relationship in graph.relationships:
        if relationship.type == lexical.node_to_chunk_relationship_type:
            from_chunk_relationships += 1
        elif (
            str(relationship.start_node_id) in entity_ids
            and str(relationship.end_node_id) in entity_ids
        ):
            entity_relationships += 1
    return len(entity_ids), entity_relationships, from_chunk_relationships


async def write_semantic_file_graph(
    *,
    pipeline: Pipeline,
    file_path: str,
    chunks: list[Chunk],
    schema: GraphSchema,
    file_sha256: str | None = None,
) -> GraphFileTelemetry:
    lexical = lexical_graph_config()
    schema = closed_graph_schema(schema)
    text_chunks = chunks_to_text_chunks(chunks)
    checkpoint_file: ExtractionFileCheckpoint | None = None
    examples = pipeline.extraction_examples if isinstance(pipeline, SemanticPipeline) else ""
    if isinstance(pipeline, SemanticPipeline) and pipeline.checkpoint_context is not None:
        if file_sha256 is None:
            raise GraphExtractionCheckpointError("Checkpoint extraction requires the source byte digest")
        checkpoint_file = await pipeline.checkpoint_context.prepare_file(
            file_path=file_path, file_sha256=file_sha256, chunks=chunks, text_chunks=text_chunks,
            schema=schema, prompt_template=pipeline._owned_extractor.prompt_template, examples=examples,
        )
    result = await pipeline.run(
        data={
            "extractor": {
                "chunks": text_chunks,
                "document_info": document_info(file_path),
                "lexical_graph_config": lexical,
                "schema": schema,
                "examples": examples,
                "checkpoint_context": checkpoint_file,
            },
            "pruner": {"schema": schema, "lexical_graph_config": lexical},
            "writer": {"lexical_graph_config": lexical},
        }
    )
    raw_extracted = await pipeline.store.get_result_for_component(result.run_id, "extractor")
    raw_pruned = await pipeline.store.get_result_for_component(result.run_id, "pruner")
    extracted = Neo4jGraph.model_validate(raw_extracted)
    pruned = Neo4jGraph.model_validate((raw_pruned or {}).get("graph") or {})
    entity_count, semantic_relationships, from_chunk_relationships = _graph_counts(
        pruned, lexical
    )
    pipeline.store.empty()
    pipeline.final_results.empty()
    if checkpoint_file is not None:
        checkpoint_file.mark_written()
    return GraphFileTelemetry(
        selected_chunks=len(chunks),
        attempted_chunks=len(chunks),
        succeeded_chunks=len(chunks),
        failed_chunks=0,
        extracted_entities=entity_count,
        semantic_relationships=semantic_relationships,
        from_chunk_relationships=from_chunk_relationships,
        pruned_nodes=max(0, len(extracted.nodes) - len(pruned.nodes))
        + (checkpoint_file.pruned_nodes if checkpoint_file is not None else 0),
        pruned_relationships=max(
            0, len(extracted.relationships) - len(pruned.relationships)
        ) + (checkpoint_file.pruned_relationships if checkpoint_file is not None else 0),
    )


async def write_code_file_graph(
    *,
    writer: ScopedNeo4jWriter,
    cfg: TriBridConfig,
    repo_root: Path,
    file_path: str,
    source: str,
    language: str | None,
    chunks: list[Chunk],
    deferred_relationships: list[Neo4jRelationship] | None = None,
) -> GraphFileTelemetry:
    lexical = lexical_graph_config()
    lexical_result = await LexicalGraphBuilder(config=lexical).run(
        text_chunks=chunks_to_text_chunks(chunks),
        document_info=document_info(file_path),
    )
    code_nodes: list[Any] = []
    code_relationships: list[Neo4jRelationship] = []
    if str(language or "") in CODE_GRAPH_LANGUAGES:
        code = extract_code_graph(
            repo_id=writer.repo_id,
            run_id=writer.run_id,
            file_path=file_path,
            source=source,
            language=language,
            chunks=chunks,
            cfg=cfg,
            root=repo_root,
        )
        code_nodes = list(code.graph.nodes)
        code_relationships = list(code.graph.relationships)
        if deferred_relationships is not None:
            deferred_relationships.extend(code.deferred_relationships)
    combined = assemble_code_file_graph(
        lexical_result.graph,
        Neo4jGraph(nodes=code_nodes, relationships=code_relationships),
    )
    validate_no_reserved_scope_keys(combined, RESERVED_SCOPE_KEYS)
    await writer.run(combined, lexical)
    entity_count, semantic_relationships, from_chunk_relationships = _graph_counts(
        combined, lexical
    )
    return GraphFileTelemetry(
        selected_chunks=len(chunks),
        attempted_chunks=len(chunks),
        succeeded_chunks=len(chunks),
        failed_chunks=0,
        extracted_entities=entity_count,
        semantic_relationships=semantic_relationships,
        from_chunk_relationships=from_chunk_relationships,
        pruned_nodes=0,
        pruned_relationships=0,
    )


async def write_deferred_code_relationships(
    writer: ScopedNeo4jWriter, relationships: list[Neo4jRelationship]
) -> None:
    if relationships:
        await writer.run(
            Neo4jGraph(nodes=[], relationships=relationships), lexical_graph_config()
        )
    await writer.finalize()


__all__ = [
    "GraphFileTelemetry",
    "GraphScopeCollisionError",
    "RESERVED_SCOPE_KEYS",
    "ScopedNeo4jWriter",
    "build_semantic_pipeline",
    "close_semantic_pipeline",
    "SemanticPipeline",
    "chunks_to_text_chunks",
    "cypher_literal",
    "document_info",
    "extraction_checkpoint_recipe",
    "lexical_graph_config",
    "require_run_id",
    "require_staging_graph_id",
    "assemble_code_file_graph",
    "document_node_id",
    "fold_duplicate_node_ids",
    "resolution_property_for_policy",
    "resolve_staged_entities",
    "semantic_extraction_llm",
    "run_async_component_off_event_loop",
    "run_component_coroutine_in_worker",
    "run_writer_coroutine_in_worker",
    "stamp_graph_scope",
    "validate_no_reserved_scope_keys",
    "write_code_file_graph",
    "write_deferred_code_relationships",
    "write_semantic_file_graph",
]
