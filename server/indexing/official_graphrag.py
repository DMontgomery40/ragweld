from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from neo4j_graphrag.experimental.components.entity_relation_extractor import (
    LLMEntityRelationExtractor,
    OnError,
)
from neo4j_graphrag.experimental.components.schema import (
    GraphSchema,
    NodeType,
    Pattern,
    PropertyType,
    RelationshipType,
)
from neo4j_graphrag.experimental.components.types import (
    DocumentInfo,
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
    TextChunk,
    TextChunks,
)
from neo4j_graphrag.llm import OpenAILLM

from server.models.graph import Entity, Relationship
from server.models.index import Chunk
from server.models.tribrid_config_model import GraphIndexingConfig, TriBridConfig

GRAPH_RAG_CHUNK_LABEL = "GraphRAGChunk"
GRAPH_RAG_DOCUMENT_LABEL = "GraphRAGDocument"
GRAPH_RAG_FROM_CHUNK = "FROM_CHUNK"

DEFAULT_GRAPH_ENTITY_TYPES: tuple[str, ...] = tuple(GraphIndexingConfig().semantic_kg_allowed_entity_types)
DEFAULT_GRAPH_RELATION_TYPES: tuple[str, ...] = tuple(GraphIndexingConfig().semantic_kg_allowed_relation_types)


@dataclass
class GraphRAGExtractionResult:
    entities: list[Entity]
    relationships: list[Relationship]
    chunk_links: list[dict[str, str]]
    processed_chunks: int
    empty_chunks: int


def _strip_openai_prefix(model: str) -> str:
    raw = str(model or "").strip()
    lower = raw.lower()
    for prefix in ("openai/", "litellm:openai/", "openrouter:openai/"):
        if lower.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def _normalize_relation_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized


def _normalize_entity_type(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {"organization": "org", "organisation": "org"}
    return aliases.get(normalized, normalized)


def _configured_entity_types(cfg: TriBridConfig | None = None) -> tuple[str, ...]:
    raw = (
        tuple(cfg.graph_indexing.semantic_kg_allowed_entity_types)
        if cfg is not None
        else DEFAULT_GRAPH_ENTITY_TYPES
    )
    normalized = tuple(
        dict.fromkeys(
            normalized
            for normalized in (_normalize_entity_type(value) for value in raw)
            if normalized
        )
    )
    return normalized or DEFAULT_GRAPH_ENTITY_TYPES


def _configured_relation_types(cfg: TriBridConfig | None = None) -> tuple[str, ...]:
    raw = (
        tuple(cfg.graph_indexing.semantic_kg_allowed_relation_types)
        if cfg is not None
        else DEFAULT_GRAPH_RELATION_TYPES
    )
    normalized = tuple(
        dict.fromkeys(
            normalized
            for normalized in (_normalize_relation_type(value) for value in raw)
            if normalized
        )
    )
    return normalized or DEFAULT_GRAPH_RELATION_TYPES


def _relation_type(value: str, *, allowed_relation_types: set[str]) -> str | None:
    normalized = _normalize_relation_type(value)
    return normalized if normalized in allowed_relation_types else None


def _entity_type(value: str, *, allowed_entity_types: set[str]) -> str | None:
    normalized = _normalize_entity_type(value)
    return normalized if normalized in allowed_entity_types else None


def _schema(
    *,
    allowed_entity_types: tuple[str, ...] | None = None,
    allowed_relation_types: tuple[str, ...] | None = None,
) -> GraphSchema:
    entity_types = allowed_entity_types or DEFAULT_GRAPH_ENTITY_TYPES
    relation_types = allowed_relation_types or DEFAULT_GRAPH_RELATION_TYPES
    node_types = tuple(
        NodeType(
            label=entity_type,
            description=f"{entity_type} entity extracted by Neo4j GraphRAG.",
            properties=[
                PropertyType(name="name", type="STRING", description="Canonical entity name", required=True),
                PropertyType(name="description", type="STRING", description="Optional entity description", required=False),
            ],
            additional_properties=True,
        )
        for entity_type in entity_types
    )
    relationship_types = tuple(
        RelationshipType(
            label=relation_type,
            description=f"{relation_type} relationship extracted by Neo4j GraphRAG.",
            additional_properties=True,
        )
        for relation_type in relation_types
    )
    patterns = tuple(
        Pattern(source=src, relationship=rel, target=tgt)
        for src in entity_types
        for rel in relation_types
        for tgt in entity_types
    )
    return GraphSchema(
        node_types=node_types,
        relationship_types=relationship_types,
        patterns=patterns,
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    )


def _lexical_graph_config() -> LexicalGraphConfig:
    return LexicalGraphConfig(
        document_node_label=GRAPH_RAG_DOCUMENT_LABEL,
        chunk_node_label=GRAPH_RAG_CHUNK_LABEL,
        chunk_to_document_relationship_type="FROM_DOCUMENT",
        next_chunk_relationship_type="NEXT_CHUNK",
        node_to_chunk_relationship_type=GRAPH_RAG_FROM_CHUNK,
        chunk_id_property="chunk_id",
        chunk_index_property="chunk_index",
        chunk_text_property="text",
        chunk_embedding_property="embedding",
    )


def _to_text_chunk(chunk: Chunk, index: int, *, repo_id: str) -> TextChunk:
    metadata: dict[str, Any] = {
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


def _graph_node_to_entity(
    node: Neo4jNode,
    *,
    run_id: str,
    allowed_entity_types: set[str],
) -> Entity | None:
    entity_type = _entity_type(node.label, allowed_entity_types=allowed_entity_types)
    if entity_type is None:
        return None
    name = str(node.properties.get("name") or "").strip() or str(node.id).split(":")[-1]
    description_raw = node.properties.get("description")
    description = str(description_raw).strip() if isinstance(description_raw, str) and description_raw.strip() else None
    props = {k: v for k, v in dict(node.properties).items() if k not in {"name", "description"}}
    props["source"] = "neo4j_graphrag"
    props["run_id"] = run_id
    props["graphrag_label"] = node.label
    return Entity(
        entity_id=str(node.id),
        name=name,
        entity_type=entity_type,  # type: ignore[arg-type]
        file_path=None,
        description=description,
        properties=props,
    )


def adapt_graphrag_graph(
    graph: Neo4jGraph,
    *,
    run_id: str,
    allowed_entity_types: tuple[str, ...] | None = None,
    allowed_relation_types: tuple[str, ...] | None = None,
) -> GraphRAGExtractionResult:
    entity_types = set(allowed_entity_types or DEFAULT_GRAPH_ENTITY_TYPES)
    relation_types = set(allowed_relation_types or DEFAULT_GRAPH_RELATION_TYPES)
    lexical_labels = {GRAPH_RAG_DOCUMENT_LABEL, GRAPH_RAG_CHUNK_LABEL}
    entities: list[Entity] = []
    entity_ids: set[str] = set()
    chunk_ids: set[str] = set()

    for node in graph.nodes:
        if node.label == GRAPH_RAG_CHUNK_LABEL:
            chunk_ids.add(str(node.id))
            continue
        if node.label in lexical_labels:
            continue
        entity = _graph_node_to_entity(
            node,
            run_id=run_id,
            allowed_entity_types=entity_types,
        )
        if entity is None:
            continue
        entities.append(entity)
        entity_ids.add(entity.entity_id)

    relationships: list[Relationship] = []
    chunk_links: list[dict[str, str]] = []
    for rel in graph.relationships:
        rel_type = _relation_type(rel.type, allowed_relation_types=relation_types)
        if rel.type == GRAPH_RAG_FROM_CHUNK:
            if rel.start_node_id in entity_ids and rel.end_node_id in chunk_ids:
                chunk_links.append({"entity_id": rel.start_node_id, "chunk_id": rel.end_node_id})
            continue
        if rel_type is None:
            continue
        if rel.start_node_id not in entity_ids or rel.end_node_id not in entity_ids:
            continue
        props = dict(rel.properties or {})
        props["source"] = "neo4j_graphrag"
        props["run_id"] = run_id
        relationships.append(
            Relationship(
                source_id=str(rel.start_node_id),
                target_id=str(rel.end_node_id),
                relation_type=rel_type,  # type: ignore[arg-type]
                weight=1.0,
                properties=props,
            )
        )

    linked_chunk_ids = {link["chunk_id"] for link in chunk_links}
    return GraphRAGExtractionResult(
        entities=entities,
        relationships=relationships,
        chunk_links=chunk_links,
        processed_chunks=len(chunk_ids),
        empty_chunks=max(0, len(chunk_ids - linked_chunk_ids)),
    )


async def extract_semantic_kg_with_graphrag(
    *,
    repo_id: str,
    run_id: str,
    cfg: TriBridConfig,
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
    extractor = LLMEntityRelationExtractor(
        llm=OpenAILLM(
            model_name=model_name,
            model_params={"temperature": 0},
            api_key=str(route_api_key or "").strip(),
            base_url=base_url,
        ),
        create_lexical_graph=True,
        on_error=OnError.RAISE if cfg.graph_indexing.semantic_kg_require_llm_success else OnError.IGNORE,
        max_concurrency=max(1, int(getattr(cfg.indexing, "indexing_workers", 1) or 1)),
        use_structured_output=True,
    )
    allowed_entity_types = _configured_entity_types(cfg)
    allowed_relation_types = _configured_relation_types(cfg)

    grouped_chunks: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        grouped_chunks[str(chunk.file_path or "")].append(chunk)

    entities: list[Entity] = []
    relationships: list[Relationship] = []
    chunk_links: list[dict[str, str]] = []
    processed_chunks = 0
    empty_chunks = 0

    for file_path, file_chunks in grouped_chunks.items():
        ordered_chunks = sorted(file_chunks, key=lambda ch: (int(ch.start_line or 0), str(ch.chunk_id)))
        text_chunks = TextChunks(
            chunks=[
                _to_text_chunk(chunk, idx, repo_id=repo_id)
                for idx, chunk in enumerate(ordered_chunks)
            ]
        )
        document_info = DocumentInfo(
            path=file_path,
            metadata={"repo_id": repo_id, "run_id": run_id},
            uid=f"{repo_id}:{file_path}",
        )
        graph = await extractor.run(
            chunks=text_chunks,
            document_info=document_info,
            lexical_graph_config=_lexical_graph_config(),
            schema=_schema(
                allowed_entity_types=allowed_entity_types,
                allowed_relation_types=allowed_relation_types,
            ),
        )
        adapted = adapt_graphrag_graph(
            graph,
            run_id=run_id,
            allowed_entity_types=allowed_entity_types,
            allowed_relation_types=allowed_relation_types,
        )
        entities.extend(adapted.entities)
        relationships.extend(adapted.relationships)
        chunk_links.extend(adapted.chunk_links)
        processed_chunks += adapted.processed_chunks
        empty_chunks += adapted.empty_chunks

    deduped_entities = {entity.entity_id: entity for entity in entities}
    deduped_relationships: dict[tuple[str, str, str], Relationship] = {}
    for relationship in relationships:
        deduped_relationships[
            (relationship.source_id, relationship.target_id, relationship.relation_type)
        ] = relationship
    deduped_links = {
        (link["entity_id"], link["chunk_id"]): link
        for link in chunk_links
    }

    return GraphRAGExtractionResult(
        entities=list(deduped_entities.values()),
        relationships=list(deduped_relationships.values()),
        chunk_links=list(deduped_links.values()),
        processed_chunks=processed_chunks,
        empty_chunks=empty_chunks,
    )
