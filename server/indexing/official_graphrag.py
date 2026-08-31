from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from neo4j_graphrag.components.entity_relation_extractor import (
    LLMEntityRelationExtractor,
    OnError,
)
from neo4j_graphrag.components.lexical_graph import LexicalGraphBuilder
from neo4j_graphrag.components.schema import GraphSchema
from neo4j_graphrag.components.types import (
    DocumentInfo,
    LexicalGraphConfig,
    Neo4jGraph,
    TextChunk,
    TextChunks,
)
from neo4j_graphrag.llm import OpenAILLM

from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig

GRAPH_RAG_CHUNK_LABEL = "Chunk"
GRAPH_RAG_DOCUMENT_LABEL = "Document"
GRAPH_RAG_CHUNK_TO_DOCUMENT = "FROM_DOCUMENT"
GRAPH_RAG_FROM_CHUNK = "IN_CHUNK"

@dataclass
class GraphRAGExtractionResult:
    graph: Neo4jGraph
    lexical_graph_config: LexicalGraphConfig
    entity_count: int
    relationship_count: int
    processed_chunks: int
    empty_chunks: int


def _normalize_relation_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized


def _normalize_entity_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {"organization": "org", "organisation": "org"}
    return aliases.get(normalized, normalized)


def _lexical_graph_config() -> LexicalGraphConfig:
    return LexicalGraphConfig(
        document_node_label=GRAPH_RAG_DOCUMENT_LABEL,
        chunk_node_label=GRAPH_RAG_CHUNK_LABEL,
        chunk_to_document_relationship_type=GRAPH_RAG_CHUNK_TO_DOCUMENT,
        next_chunk_relationship_type="NEXT_CHUNK",
        node_to_chunk_relationship_type=GRAPH_RAG_FROM_CHUNK,
        chunk_id_property="chunk_id",
        chunk_index_property="chunk_index",
        chunk_text_property="text",
        chunk_embedding_property="embedding",
    )


def _to_text_chunk(chunk: Chunk, index: int, *, repo_id: str) -> TextChunk:
    metadata: dict[str, object] = {
        "repo_id": repo_id,
        "chunk_id": chunk.chunk_id,
        "file_path": chunk.file_path,
        "start_line": int(chunk.start_line or 0),
        "end_line": int(chunk.end_line or 0),
    }
    if chunk.embedding:
        metadata["embedding"] = list(chunk.embedding)
    return TextChunk(
        text=str(chunk.content or ""),
        index=index,
        metadata=metadata,
        uid=str(chunk.chunk_id),
    )


def _annotate_graph(
    graph: Neo4jGraph,
    *,
    repo_id: str,
    run_id: str,
    lexical_graph_config: LexicalGraphConfig,
) -> Neo4jGraph:
    lexical_labels = set(lexical_graph_config.lexical_graph_node_labels)
    for node in graph.nodes:
        props = dict(node.properties or {})
        props["repo_id"] = repo_id
        props["run_id"] = run_id
        if node.label == lexical_graph_config.document_node_label:
            props["document_id"] = str(node.id)
            props["file_path"] = str(props.get("file_path") or props.get("path") or "")
        elif node.label == lexical_graph_config.chunk_node_label:
            props["chunk_id"] = str(props.get("chunk_id") or node.id)
        elif node.label not in lexical_labels:
            props["entity_id"] = str(node.id)
            props["entity_type"] = _normalize_entity_type(node.label)
        node.properties = props
    for relationship in graph.relationships:
        rel_props = dict(relationship.properties or {})
        rel_props["repo_id"] = repo_id
        rel_props["run_id"] = run_id
        relationship.properties = rel_props
    return graph

async def write_lexical_graph_with_graphrag(
    *,
    repo_id: str,
    run_id: str,
    file_path: str,
    chunks: list[Chunk],
) -> tuple[Neo4jGraph, LexicalGraphConfig]:
    lexical_graph_config = _lexical_graph_config()
    builder = LexicalGraphBuilder(config=lexical_graph_config)
    ordered_chunks = sorted(chunks, key=lambda ch: (int(ch.start_line or 0), str(ch.chunk_id)))
    text_chunks = TextChunks(
        chunks=[_to_text_chunk(chunk, idx, repo_id=repo_id) for idx, chunk in enumerate(ordered_chunks)]
    )
    document_info = DocumentInfo(
        path=file_path,
        metadata={"repo_id": repo_id, "run_id": run_id, "file_path": file_path},
        uid=f"{repo_id}:{file_path}",
    )
    graph_result = await builder.run(text_chunks=text_chunks, document_info=document_info)
    graph = _annotate_graph(
        graph_result.graph,
        repo_id=repo_id,
        run_id=run_id,
        lexical_graph_config=lexical_graph_config,
    )
    return graph, lexical_graph_config


def _count_semantic_edges(
    graph: Neo4jGraph,
    *,
    lexical_graph_config: LexicalGraphConfig,
) -> tuple[int, int, int]:
    lexical_labels = set(lexical_graph_config.lexical_graph_node_labels)
    chunk_ids = {
        str(node.properties.get("chunk_id") or node.id)
        for node in graph.nodes
        if node.label == lexical_graph_config.chunk_node_label
    }
    entity_ids = {
        str(node.properties.get("entity_id") or node.id)
        for node in graph.nodes
        if node.label not in lexical_labels
    }
    entity_count = len(entity_ids)
    relationship_count = 0
    linked_chunk_ids: set[str] = set()
    for rel in graph.relationships:
        if rel.type == lexical_graph_config.node_to_chunk_relationship_type:
            if rel.start_node_id in entity_ids and rel.end_node_id in chunk_ids:
                linked_chunk_ids.add(str(rel.end_node_id))
            continue
        if rel.start_node_id in entity_ids and rel.end_node_id in entity_ids:
            relationship_count += 1
    empty_chunks = max(0, len(chunk_ids - linked_chunk_ids))
    return entity_count, relationship_count, empty_chunks


async def extract_semantic_kg_with_graphrag(
    *,
    repo_id: str,
    run_id: str,
    cfg: TriBridConfig,
    schema: GraphSchema,
    chunks: list[Chunk],
    route_model: str,
    route_base_url: str,
    route_api_key: str | None,
) -> GraphRAGExtractionResult:
    if not str(route_api_key or "").strip():
        raise RuntimeError("GraphRAG semantic extraction requires an authenticated OpenAI-compatible route.")
    model_name = str(route_model or "").strip()
    if not model_name:
        raise RuntimeError("GraphRAG semantic extraction requires a resolved model id.")
    base_url = str(route_base_url or "").strip()
    if not base_url:
        raise RuntimeError("GraphRAG semantic extraction requires a resolved base URL.")

    lexical_graph_config = _lexical_graph_config()
    extractor = LLMEntityRelationExtractor(
        llm=OpenAILLM(
            model_name=model_name,
            model_params={"temperature": 0},
            api_key=str(route_api_key or "").strip(),
            base_url=base_url,
        ),
        create_lexical_graph=True,
        on_error=OnError.RAISE,
        max_concurrency=max(1, int(getattr(cfg.indexing, "indexing_workers", 1) or 1)),
        use_structured_output=True,
    )
    grouped_chunks: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        grouped_chunks[str(chunk.file_path or "")].append(chunk)

    combined = Neo4jGraph(nodes=[], relationships=[])
    processed_chunks = 0

    for file_path, file_chunks in grouped_chunks.items():
        ordered_chunks = sorted(file_chunks, key=lambda ch: (int(ch.start_line or 0), str(ch.chunk_id)))
        text_chunks = TextChunks(
            chunks=[_to_text_chunk(chunk, idx, repo_id=repo_id) for idx, chunk in enumerate(ordered_chunks)]
        )
        document_info = DocumentInfo(
            path=file_path,
            metadata={"repo_id": repo_id, "run_id": run_id, "file_path": file_path},
            uid=f"{repo_id}:{file_path}",
        )
        graph = await extractor.run(
            chunks=text_chunks,
            document_info=document_info,
            lexical_graph_config=lexical_graph_config,
            schema=schema,
        )
        annotated = _annotate_graph(
            graph,
            repo_id=repo_id,
            run_id=run_id,
            lexical_graph_config=lexical_graph_config,
        )
        combined.nodes.extend(annotated.nodes)
        combined.relationships.extend(annotated.relationships)
        processed_chunks += len(ordered_chunks)

    entity_count, relationship_count, empty_chunks = _count_semantic_edges(
        combined,
        lexical_graph_config=lexical_graph_config,
    )
    return GraphRAGExtractionResult(
        graph=combined,
        lexical_graph_config=lexical_graph_config,
        entity_count=entity_count,
        relationship_count=relationship_count,
        processed_chunks=processed_chunks,
        empty_chunks=empty_chunks,
    )
