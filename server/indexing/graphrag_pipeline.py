from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
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
from neo4j_graphrag.experimental.pipeline import Pipeline
from neo4j_graphrag.generation.prompts import ERExtractionTemplate
from neo4j_graphrag.llm import OpenAILLM

from server.gateway_reasoning import reasoning_model_params
from server.indexing.code_graph import CODE_GRAPH_LANGUAGES, extract_code_graph
from server.indexing.graph_policy import GraphPolicy
from server.indexing.graphrag_schema import closed_graph_schema
from server.model_policy import ensure_model_allowed
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
    missing = [
        placeholder
        for placeholder in EXTRACTION_TEMPLATE_REQUIRED_PLACEHOLDERS
        if placeholder not in template
    ]
    if missing:
        raise ValueError(
            "GraphRAG extraction prompt is missing the placeholder(s) the official extractor "
            f"formats: {', '.join(missing)}"
        )
    return ERExtractionTemplate(template=template)



@dataclass
class _ExtractionBatch:
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    closing: bool = False


_EXTRACTION_BATCH: ContextVar[_ExtractionBatch | None] = ContextVar(
    "graphrag_extraction_batch", default=None,
)


class _DrainingExtractor(LLMEntityRelationExtractor):
    """Keep official extraction, but drain gather siblings before releasing its producer."""

    def __init__(self, *, census_scope: RunCensusScope | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.census_scope = census_scope
        self.active_runs: set[asyncio.Task[Any]] = set()
        self.drains: set[asyncio.Task[None]] = set()
        self.closed = False

    async def run(
        self, chunks: TextChunks, document_info: DocumentInfo | None = None,
        lexical_graph_config: LexicalGraphConfig | None = None,
        schema: GraphSchema | None = None, examples: str = "", **kwargs: Any,
    ) -> Neo4jGraph:
        if self.closed:
            raise RuntimeError("semantic pipeline is closed")
        lease = self.census_scope.producer_started() if self.census_scope else None
        owner = asyncio.current_task()
        assert owner is not None
        self.active_runs.add(owner)
        batch = _ExtractionBatch()
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
                try:
                    for task in batch.tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*batch.tasks, return_exceptions=True)
                finally:
                    if lease is not None:
                        lease.close()

            cleanup = asyncio.create_task(drain())
            self.drains.add(cleanup)
            try:
                # A second cancellation must not release the producer while siblings
                # still own HTTP requests. Pipeline close also waits for this task.
                await asyncio.shield(cleanup)
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
        await asyncio.gather(*owners, return_exceptions=True)
        await asyncio.gather(*self.drains)
        self.drains.clear()


class SemanticPipeline(Pipeline):
    """Official pipeline with explicit ownership of extractor work and SDK clients."""

    def __init__(self, llm: OpenAILLM, extractor: _DrainingExtractor) -> None:
        super().__init__()
        self._owned_llm = llm
        self._owned_extractor = extractor

    async def aclose(self) -> None:
        await self._owned_extractor.cancel_and_drain()
        await self._owned_llm.aclose()


async def close_semantic_pipeline(pipeline: Pipeline) -> None:
    if isinstance(pipeline, SemanticPipeline):
        await pipeline.aclose()


def semantic_entity_relation_extractor(
    *,
    llm: OpenAILLM,
    prompt_template: str,
    max_concurrency: int,
    census_scope: RunCensusScope | None = None,
) -> _DrainingExtractor:
    """The official extractor over the operator's template, strict structured output, fail closed."""
    return _DrainingExtractor(
        census_scope=census_scope,
        llm=llm,
        prompt_template=extraction_prompt_template(prompt_template),
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
) -> SemanticPipeline:
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
    )
    writer = ScopedNeo4jWriter(
        driver=driver,
        neo4j_database=neo4j_database,
        repo_id=repo_id,
        run_id=run_id,
    )
    pipeline = SemanticPipeline(llm, extractor)
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
) -> GraphFileTelemetry:
    lexical = lexical_graph_config()
    schema = closed_graph_schema(schema)
    result = await pipeline.run(
        data={
            "extractor": {
                "chunks": chunks_to_text_chunks(chunks),
                "document_info": document_info(file_path),
                "lexical_graph_config": lexical,
                "schema": schema,
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
    return GraphFileTelemetry(
        selected_chunks=len(chunks),
        attempted_chunks=len(chunks),
        succeeded_chunks=len(chunks),
        failed_chunks=0,
        extracted_entities=entity_count,
        semantic_relationships=semantic_relationships,
        from_chunk_relationships=from_chunk_relationships,
        pruned_nodes=max(0, len(extracted.nodes) - len(pruned.nodes)),
        pruned_relationships=max(
            0, len(extracted.relationships) - len(pruned.relationships)
        ),
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
