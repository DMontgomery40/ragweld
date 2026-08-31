from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from neo4j_graphrag.components.schema import GraphSchema, SchemaFromTextExtractor
from neo4j_graphrag.llm import OpenAILLM

from server.models.index import Chunk, GraphSchemaProposal, GraphSchemaSample


_GRAPH_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_GENERIC_NODE_LABELS = {"OBJECT"}
_GENERIC_RELATIONSHIP_LABELS = {"RELATED_TO", "ASSOCIATED_WITH"}


def select_schema_chunks(
    chunks: Sequence[Chunk], *, corpus_id: str, max_documents: int = 12
) -> list[Chunk]:
    grouped: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        if str(chunk.content or "").strip():
            grouped[str(chunk.file_path)].append(chunk)
    paths = sorted(
        grouped,
        key=lambda path: hashlib.sha256(f"{corpus_id}:{path}".encode()).hexdigest(),
    )
    if len(paths) > max_documents:
        paths = [
            paths[round(index * (len(paths) - 1) / (max_documents - 1))]
            for index in range(max_documents)
        ]
    selected: list[Chunk] = []
    for path in paths:
        ordered = sorted(grouped[path], key=lambda chunk: (chunk.start_line, chunk.chunk_id))
        for index in sorted({0, len(ordered) // 2, len(ordered) - 1}):
            selected.append(ordered[index])
    return selected


def canonical_schema_dict(schema: GraphSchema) -> dict[str, Any]:
    return GraphSchema(
        node_types=schema.node_types,
        relationship_types=schema.relationship_types,
        patterns=schema.patterns,
        constraints=schema.constraints,
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    ).model_dump(mode="json")


def graph_schema_hash(schema_dict: Mapping[str, Any]) -> str:
    encoded = json.dumps(schema_dict, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_domain_schema(schema_dict: Mapping[str, Any]) -> None:
    for raw in schema_dict.get("node_types", []):
        if isinstance(raw, Mapping):
            label = str(raw.get("label") or "").strip()
            if label.upper() in _GENERIC_NODE_LABELS:
                raise ValueError(f"generic graph label is prohibited: {label}")
    for raw in schema_dict.get("relationship_types", []):
        if isinstance(raw, Mapping):
            label = str(raw.get("label") or "").strip()
            if label.upper() in _GENERIC_RELATIONSHIP_LABELS:
                raise ValueError(f"generic graph label is prohibited: {label}")
    schema = GraphSchema.model_validate(schema_dict)
    if not schema.node_types or not schema.relationship_types or not schema.patterns:
        raise ValueError("graph schema requires node types, relationship types, and patterns")
    for node in schema.node_types:
        label = str(node.label or "").strip()
        if label.upper() in _GENERIC_NODE_LABELS:
            raise ValueError(f"generic graph label is prohibited: {label}")
        if not _GRAPH_NAME.fullmatch(label):
            raise ValueError(f"invalid Neo4j node label: {label}")
    for relationship in schema.relationship_types:
        label = str(relationship.label or "").strip()
        if label.upper() in _GENERIC_RELATIONSHIP_LABELS:
            raise ValueError(f"generic graph label is prohibited: {label}")
        if not _GRAPH_NAME.fullmatch(label):
            raise ValueError(f"invalid Neo4j relationship label: {label}")
    if schema.additional_node_types or schema.additional_relationship_types or schema.additional_patterns:
        raise ValueError("graph schema must be closed to additional nodes, relationships, and patterns")


async def derive_graph_schema_proposal(
    *,
    corpus_id: str,
    chunks: Sequence[Chunk],
    model_alias: str,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    input_fingerprint: str,
) -> GraphSchemaProposal:
    sample = select_schema_chunks(chunks, corpus_id=corpus_id)
    if not sample:
        raise ValueError("graph schema proposal requires at least one nonempty chunk")
    text = "\n\n".join(
        f"## {chunk.file_path} lines {chunk.start_line}-{chunk.end_line}\n{chunk.content[:6000]}"
        for chunk in sample
    )
    llm = OpenAILLM(
        model_name=route_model,
        model_params={"temperature": 0},
        api_key=route_api_key,
        base_url=route_base_url,
    )
    extracted = await SchemaFromTextExtractor(llm=llm, use_structured_output=True).run(text)
    schema = canonical_schema_dict(extracted)
    validate_domain_schema(schema)
    return GraphSchemaProposal(
        corpus_id=corpus_id,
        policy="semantic",
        input_fingerprint=input_fingerprint,
        schema_hash=graph_schema_hash(schema),
        schema_payload=schema,
        sample=GraphSchemaSample(
            chunk_ids=[chunk.chunk_id for chunk in sample],
            chunk_hashes=[hashlib.sha256(chunk.content.encode()).hexdigest() for chunk in sample],
        ),
        model_alias=model_alias,
        created_at=datetime.now(UTC),
    )
