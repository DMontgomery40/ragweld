from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

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
    Neo4jRelationship,
    TextChunk,
    TextChunks,
)
from neo4j_graphrag.experimental.pipeline import Pipeline
from neo4j_graphrag.llm import OpenAILLM

from server.indexing.code_graph import CODE_GRAPH_LANGUAGES, extract_code_graph
from server.indexing.graph_policy import GraphPolicy
from server.models.index import Chunk, GraphResolutionTelemetry
from server.models.tribrid_config_model import TriBridConfig

ResultT = TypeVar("ResultT")

RESERVED_SCOPE_KEYS = frozenset({"repo_id", "run_id", "graphJoinId"})
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


class ScopedNeo4jWriter(Neo4jWriter):
    def __init__(self, *args: Any, repo_id: str, run_id: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.repo_id = require_staging_graph_id(repo_id)
        self.run_id = require_run_id(run_id)

    async def run(
        self,
        graph: Neo4jGraph,
        lexical_graph_config: LexicalGraphConfig | None = None,
    ) -> KGWriterModel:
        # Pipeline edges persist component results through ``model_dump`` and
        # therefore hand downstream components plain dictionaries. The parent
        # method's validate_call normally restores the model; this override owns
        # the boundary and must do so before inspecting or stamping properties.
        graph = Neo4jGraph.model_validate(graph)
        lexical_graph_config = lexical_graph_config or LexicalGraphConfig()
        validate_no_reserved_scope_keys(graph, RESERVED_SCOPE_KEYS)
        stamp_graph_scope(
            graph,
            repo_id=self.repo_id,
            run_id=self.run_id,
            lexical=lexical_graph_config,
        )
        base_run = super().run
        result = await asyncio.to_thread(
            run_writer_coroutine_in_worker,
            base_run,
            graph,
            lexical_graph_config,
        )
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


def document_info(file_path: str) -> DocumentInfo:
    return DocumentInfo(
        path=file_path,
        metadata={"file_path": file_path},
        uid=file_path,
    )


def semantic_extraction_llm(
    *,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    llm_timeout_s: int,
    reasoning_effort: str,
) -> OpenAILLM:
    """The official OpenAILLM for semantic extraction, carrying the operator's controls.

    ``graph_indexing.semantic_kg_llm_timeout_s`` bounds every gateway call (the OpenAI
    client's request timeout) and ``semantic_kg_reasoning_effort`` is sent with every
    request; the Indexing page showed both, but neither reached the pipeline before
    (Task 8 drive defect D9).
    """
    if not str(route_model or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires a resolved model id")
    if not str(route_base_url or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires a resolved base URL")
    if not str(route_api_key or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires an authenticated route")
    if int(llm_timeout_s) <= 0:
        raise RuntimeError("GraphRAG semantic extraction requires a positive per-chunk timeout")
    effort = str(reasoning_effort or "").strip()
    if not effort:
        raise RuntimeError("GraphRAG semantic extraction requires a reasoning effort")
    return OpenAILLM(
        model_name=str(route_model).strip(),
        model_params={"temperature": 0, "reasoning_effort": effort},
        api_key=str(route_api_key).strip(),
        base_url=str(route_base_url).strip(),
        timeout=float(int(llm_timeout_s)),
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
    max_concurrency: int,
    llm_timeout_s: int,
    reasoning_effort: str,
) -> Pipeline:
    llm = semantic_extraction_llm(
        route_model=route_model,
        route_base_url=route_base_url,
        route_api_key=route_api_key,
        llm_timeout_s=llm_timeout_s,
        reasoning_effort=reasoning_effort,
    )
    extractor = LLMEntityRelationExtractor(
        llm=llm,
        create_lexical_graph=True,
        on_error=OnError.RAISE,
        max_concurrency=max(1, int(max_concurrency)),
        use_structured_output=True,
    )
    writer = ScopedNeo4jWriter(
        driver=driver,
        neo4j_database=neo4j_database,
        repo_id=repo_id,
        run_id=run_id,
    )
    pipeline = Pipeline()
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
    combined = Neo4jGraph(
        nodes=[*lexical_result.graph.nodes, *code_nodes],
        relationships=[*lexical_result.graph.relationships, *code_relationships],
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
    "chunks_to_text_chunks",
    "cypher_literal",
    "document_info",
    "lexical_graph_config",
    "require_run_id",
    "require_staging_graph_id",
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
