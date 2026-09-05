from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from neo4j_graphrag.components.schema import (
    ConstraintType,
    GraphConstraintType,
    GraphSchema,
    NodeType,
    PropertyType,
    RelationshipType,
    SchemaFromTextExtractor,
)
from neo4j_graphrag.generation.prompts import SchemaExtractionTemplate
from neo4j_graphrag.llm import OpenAILLM

from server.gateway_reasoning import reasoning_model_params
from server.model_policy import ensure_model_allowed
from server.models.index import Chunk, GraphSchemaProposal, GraphSchemaSample

_GRAPH_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_GENERIC_NODE_LABELS = {"OBJECT"}
_GENERIC_RELATIONSHIP_LABELS = {"RELATED_TO", "ASSOCIATED_WITH"}
# Every extracted entity needs an identity: the official exact-match resolver merges on
# this property and skips nodes where it is null, and the explorer names nodes by it.
IDENTITY_PROPERTY = "name"
# Document text lives in the chunk store, never on a graph node or edge. A property that
# asks the extractor to copy the source text back makes the structured-output stream
# carry whole documents, which provider moderation cuts mid-JSON (Task 8 drive, D3).
DOCUMENT_TEXT_PROPERTIES = frozenset(
    {
        "body",
        "content",
        "text",
        "full_text",
        "fulltext",
        "raw",
        "raw_text",
        "html",
        "message",
        "message_body",
        "email_body",
        "transcript",
    }
)


def schema_proposal_prompt() -> SchemaExtractionTemplate:
    """Keep the official schema contract while preserving less frequent facts.

    The upstream minimal-schema instruction can omit whole diagnostic domains
    from mixed reports. Override that instruction through the supported template
    API; fail explicitly if a dependency upgrade changes the instruction.
    """
    minimal_rule = (
        "7. Keep your schema minimal and focused on clearly identifiable patterns in the text."
    )
    coverage_rule = (
        "7. Cover the distinct concepts and explicit relationships represented across the entire "
        "supplied sample. Preserve causal, diagnostic, and operational relationships when the "
        "text states them; do not reduce the schema to only its most common topics or "
        "participant/containment relationships. Keep types general enough to reuse across "
        "examples, but do not collapse distinct roles or omit less frequent concepts needed "
        "to express the sample's facts. Do not invent types or relationships unsupported by the text."
        "\n7.1 Use meaningful domain types. These generic labels are prohibited (case-insensitive): "
        f"node labels {', '.join(sorted(_GENERIC_NODE_LABELS))}; "
        f"relationship labels {', '.join(sorted(_GENERIC_RELATIONSHIP_LABELS))}. "
        "Omit a relationship whose meaning the text does not establish; never substitute a catch-all link."
    )
    template = SchemaExtractionTemplate.DEFAULT_TEMPLATE
    if template.count(minimal_rule) != 1:
        raise RuntimeError("GraphRAG schema template changed; review the domain-coverage override")
    return SchemaExtractionTemplate(template=template.replace(minimal_rule, coverage_rule))


def select_schema_chunks(
    chunks: Sequence[Chunk], *, corpus_id: str, max_documents: int = 12
) -> list[Chunk]:
    """Spread a fixed 36-chunk budget over documents and their full length.

    Three chunks per document undersamples a corpus made of one long report.
    Allocate that same bounded total across the available documents instead.
    Selecting an already selected sample is idempotent.
    """
    if max_documents < 1:
        raise ValueError("max_documents must be positive")
    max_documents = min(max_documents, 36)
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
            paths[round(index * (len(paths) - 1) / max(1, max_documents - 1))]
            for index in range(max_documents)
        ]
    budgets = dict.fromkeys(paths, 0)
    remaining = min(36, sum(len(grouped[path]) for path in paths))
    while remaining:
        for path in paths:
            if budgets[path] < len(grouped[path]):
                budgets[path] += 1
                remaining -= 1
                if not remaining:
                    break
    selected: list[Chunk] = []
    for path in paths:
        ordered = sorted(grouped[path], key=lambda chunk: (chunk.start_line, chunk.chunk_id))
        count = budgets[path]
        for index in sorted({round(i * (len(ordered) - 1) / max(1, count - 1)) for i in range(count)}):
            selected.append(ordered[index])
    return selected


def _is_document_text(name: str) -> bool:
    return name.strip().lower() in DOCUMENT_TEXT_PROPERTIES


def _keeps_attributes(properties: Sequence[PropertyType]) -> list[PropertyType]:
    return [prop for prop in properties if not _is_document_text(prop.name)]


def closed_graph_schema(schema: GraphSchema | Mapping[str, Any]) -> GraphSchema:
    """Validate a schema, then apply its closed-world execution contract to a copy.

    GraphRAG 1.19 reopens an empty-property RelationshipType during validation.
    Its extractor and official pruner honor a closed validated instance, including
    through Pipeline inputs. Apply the flags after validation, both when persisting
    the approved shape and after loading it for execution; never add fake attributes
    merely to suppress the upstream default.
    """
    closed = GraphSchema.model_validate(deepcopy(schema)).model_copy(
        update={
            "additional_node_types": False,
            "additional_relationship_types": False,
            "additional_patterns": False,
        },
    )
    for node in closed.node_types:
        node.additional_properties = False
    for relationship in closed.relationship_types:
        relationship.additional_properties = False
    return closed


def normalize_domain_schema(schema: GraphSchema) -> GraphSchema:
    """Apply the domain rules the proposer cannot be trusted to follow.

    1. Every node type carries the ``name`` identity property, and a mandatory
       (EXISTENCE or KEY) constraint on it, so the official pruner drops an extraction
       that omits the name instead of writing an anonymous node.
    2. No node or relationship type carries a document-text property, and no
       constraint references one.
    Deterministic and idempotent: normalizing a normalized schema is a no-op, so the
    schema hash the operator approves is the hash of exactly this shape.
    """
    node_types: list[NodeType] = []
    for node in schema.node_types:
        properties = _keeps_attributes(node.properties)
        if not any(prop.name == IDENTITY_PROPERTY for prop in properties):
            properties.insert(
                0,
                PropertyType(
                    name=IDENTITY_PROPERTY,
                    type="STRING",
                    description="Canonical entity name; identity for exact-match resolution and display",
                ),
            )
        node_types.append(node.model_copy(update={"properties": properties}))
    relationship_types: list[RelationshipType] = [
        relationship.model_copy(update={"properties": _keeps_attributes(relationship.properties)})
        for relationship in schema.relationship_types
    ]
    constraints: list[ConstraintType] = [
        constraint
        for constraint in schema.constraints
        if not any(_is_document_text(name) for name in constraint.property_names)
    ]
    mandatory_on_name = {
        constraint.node_type
        for constraint in constraints
        if constraint.node_type
        and constraint.type in (GraphConstraintType.EXISTENCE, GraphConstraintType.KEY)
        and tuple(constraint.property_names) == (IDENTITY_PROPERTY,)
    }
    for node in node_types:
        if node.label not in mandatory_on_name:
            constraints.append(
                ConstraintType(
                    type=GraphConstraintType.EXISTENCE,
                    node_type=node.label,
                    property_names=(IDENTITY_PROPERTY,),
                )
            )
    return closed_graph_schema(GraphSchema(
        node_types=tuple(node_types),
        relationship_types=tuple(relationship_types),
        patterns=schema.patterns,
        constraints=tuple(constraints),
        additional_node_types=False,
        additional_relationship_types=False,
        additional_patterns=False,
    ))


def canonical_schema_dict(schema: GraphSchema) -> dict[str, Any]:
    return closed_graph_schema(schema).model_dump(mode="json")


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
    schema = GraphSchema.model_validate(deepcopy(schema_dict))
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
    # Inspect the serialized flags: validating an empty-property RelationshipType
    # reopens its instance in 1.19, but the reviewed/persisted contract must be closed.
    for kind in ("node_types", "relationship_types"):
        for raw in schema_dict.get(kind, []):
            if isinstance(raw, Mapping) and raw.get("additional_properties") is not False:
                raise ValueError("graph schema must be closed to additional properties")
    for node in schema.node_types:
        identity = [prop for prop in node.properties if prop.name == IDENTITY_PROPERTY]
        if not identity or identity[0].type != "STRING":
            raise ValueError(
                f"node type {node.label} lacks the STRING identity property '{IDENTITY_PROPERTY}'"
            )
        if not (
            schema.mandatory_property_names_for_node(node.label) & {IDENTITY_PROPERTY}
        ):
            raise ValueError(
                f"node type {node.label} has no mandatory constraint on its identity property '{IDENTITY_PROPERTY}'"
            )
        for prop in node.properties:
            if _is_document_text(prop.name):
                raise ValueError(
                    f"node type {node.label} carries document text property '{prop.name}'; the chunk store owns text"
                )
    for relationship in schema.relationship_types:
        for prop in relationship.properties:
            if _is_document_text(prop.name):
                raise ValueError(
                    f"relationship type {relationship.label} carries document text property '{prop.name}'; the chunk store owns text"
                )


async def derive_graph_schema_proposal(
    *,
    corpus_id: str,
    chunks: Sequence[Chunk],
    model_alias: str,
    route_model: str,
    route_base_url: str,
    route_api_key: str,
    route_upstream: str,
    reasoning_effort: str,
    input_fingerprint: str,
) -> GraphSchemaProposal:
    for identifier in (model_alias, route_model, route_upstream):
        ensure_model_allowed(identifier)
    sample = select_schema_chunks(chunks, corpus_id=corpus_id)
    if not sample:
        raise ValueError("graph schema proposal requires at least one nonempty chunk")
    text = "\n\n".join(
        f"## {chunk.file_path} lines {chunk.start_line}-{chunk.end_line}\n{chunk.content[:6000]}"
        for chunk in sample
    )
    # The proposal deliberately carries the effort but no per-chunk timeout (D9); the
    # effort travels in the upstream's protocol like every extraction call (D25).
    llm = OpenAILLM(
        model_name=route_model,
        model_params=reasoning_model_params(
            reasoning_effort=reasoning_effort, route_upstream=route_upstream
        ),
        api_key=route_api_key,
        base_url=route_base_url,
    )
    extracted = await SchemaFromTextExtractor(
        llm=llm,
        prompt_template=schema_proposal_prompt(),
        use_structured_output=True,
    ).run(text)
    schema = canonical_schema_dict(normalize_domain_schema(extracted))
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
