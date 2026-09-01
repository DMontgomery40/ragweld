from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j_graphrag.components.schema import (
    GraphSchema,
    NodeType,
    Pattern,
    PropertyType,
    RelationshipType,
)
from pydantic import ValidationError

from server.indexing.graphrag_schema import (
    canonical_schema_dict,
    graph_schema_hash,
    normalize_domain_schema,
    select_schema_chunks,
    validate_domain_schema,
)
from server.models.index import Chunk, GraphSchemaProposal, GraphSchemaSample


def _chunk(path: str, index: int) -> Chunk:
    return Chunk(
        chunk_id=f"{path}:{index}",
        content=f"{path} content {index}",
        file_path=path,
        start_line=index * 10 + 1,
        end_line=index * 10 + 9,
        token_count=4,
    )


def _schema() -> GraphSchema:
    return GraphSchema(
        node_types=[
            NodeType(
                label="Person",
                description="A named person",
                properties=[PropertyType(name="name", type="STRING", required=True)],
                additional_properties=True,
            )
        ],
        relationship_types=[
            RelationshipType(label="WORKS_FOR", description="Employment", additional_properties=True)
        ],
        patterns=[Pattern(source="Person", relationship="WORKS_FOR", target="Person")],
        additional_node_types=True,
        additional_relationship_types=True,
        additional_patterns=True,
    )


def test_schema_sample_is_stable_and_spans_first_middle_last_per_document() -> None:
    chunks = [_chunk(path, index) for path in ("a.md", "b.md", "c.md") for index in range(5)]
    first = select_schema_chunks(chunks, corpus_id="apollo")
    second = select_schema_chunks(list(reversed(chunks)), corpus_id="apollo")

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len(first) == 9
    for path in ("a.md", "b.md", "c.md"):
        assert {chunk.chunk_id for chunk in first if chunk.file_path == path} == {
            f"{path}:0",
            f"{path}:2",
            f"{path}:4",
        }


def test_schema_normalization_closes_all_open_world_flags_and_hashes_canonical_json() -> None:
    normalized = canonical_schema_dict(_schema())
    assert normalized["additional_node_types"] is False
    assert normalized["additional_relationship_types"] is False
    assert normalized["additional_patterns"] is False
    assert graph_schema_hash(normalized) == graph_schema_hash(dict(reversed(list(normalized.items()))))


@pytest.mark.parametrize(
    ("node_label", "relationship_label"),
    [("Object", "WORKS_FOR"), ("Person", "RELATED_TO"), ("Person", "ASSOCIATED_WITH")],
)
def test_domain_schema_rejects_generic_catch_all_labels(
    node_label: str, relationship_label: str
) -> None:
    schema = canonical_schema_dict(_schema())
    schema["node_types"][0]["label"] = node_label
    schema["relationship_types"][0]["label"] = relationship_label
    with pytest.raises(ValueError, match="generic graph label"):
        validate_domain_schema(schema)


def test_proposal_validation_rejects_schema_hash_mismatch() -> None:
    schema = canonical_schema_dict(_schema())
    with pytest.raises(ValidationError, match="schema_hash"):
        GraphSchemaProposal(
            corpus_id="apollo",
            policy="semantic",
            input_fingerprint="a" * 64,
            schema_hash="b" * 64,
            schema=schema,
            sample=GraphSchemaSample(chunk_ids=["c1"], chunk_hashes=["c" * 64]),
            model_alias="deepseek.deepseek-v4-flash",
            created_at=datetime.now(UTC),
        )


def _email_schema() -> GraphSchema:
    """The shape every 5.6-class proposer returned for the Epstein email corpus on 2026-09-01."""
    return GraphSchema(
        node_types=[
            NodeType(
                label="Person",
                description="Sender or recipient",
                properties=[PropertyType(name="name", type="STRING")],
                additional_properties=False,
            ),
            NodeType(
                label="Email",
                description="One email message",
                properties=[
                    PropertyType(name="sent_at", type="LOCAL_DATETIME"),
                    PropertyType(name="subject", type="STRING"),
                    PropertyType(name="body", type="STRING", description="Full email text"),
                ],
                additional_properties=False,
            ),
        ],
        relationship_types=[
            RelationshipType(
                label="SENT",
                description="Person sent email",
                properties=[PropertyType(name="content", type="STRING")],
                additional_properties=False,
            )
        ],
        patterns=[Pattern(source="Person", relationship="SENT", target="Email")],
        constraints=[
            {"type": "EXISTENCE", "node_type": "Email", "property_name": "body"},
            {"type": "KEY", "node_type": "Person", "property_name": "name"},
        ],
    )


def test_normalization_gives_every_node_type_a_name_identity_with_an_existence_constraint() -> None:
    """Task 8 drive defect D4: the NASA proposal typed Tank/PressureTransducerAssembly without a
    ``name`` property, so 2,021 of 2,112 extracted entities were anonymous - the official
    exact-match resolver skips null names and the explorer had nothing to show. Every node
    type must carry the identity property, and the official pruner must drop an extraction
    that omits it (EXISTENCE constraint), so an entity can never be written without a name.
    """
    normalized = canonical_schema_dict(normalize_domain_schema(_email_schema()))
    by_label = {node["label"]: node for node in normalized["node_types"]}
    assert [p["name"] for p in by_label["Email"]["properties"]][0] == "name"
    assert by_label["Email"]["properties"][0]["type"] == "STRING"
    assert [p["name"] for p in by_label["Person"]["properties"]] == ["name"]
    mandatory = {
        (c["type"], c["node_type"], tuple(c["property_names"]))
        for c in normalized["constraints"]
        if c["type"] in {"EXISTENCE", "KEY"}
    }
    assert ("EXISTENCE", "Email", ("name",)) in mandatory
    # A KEY on name already implies existence; no duplicate EXISTENCE is added.
    assert ("KEY", "Person", ("name",)) in mandatory
    assert ("EXISTENCE", "Person", ("name",)) not in mandatory
    # Idempotent: normalizing a normalized schema changes nothing (stable hash).
    again = canonical_schema_dict(normalize_domain_schema(GraphSchema.model_validate(normalized)))
    assert graph_schema_hash(again) == graph_schema_hash(normalized)


def test_normalization_drops_document_text_properties_and_their_constraints() -> None:
    """Task 8 drive defect D3: a ``body`` property made every OpenAI 5.6 alias copy whole emails
    into the extraction JSON, the provider's output moderation cut the stream
    (``finish_reason=content_filter``) and the run failed closed. Document text is owned by the
    chunk store; graph properties are attributes, never bodies.
    """
    normalized = canonical_schema_dict(normalize_domain_schema(_email_schema()))
    by_label = {node["label"]: node for node in normalized["node_types"]}
    assert [p["name"] for p in by_label["Email"]["properties"]] == ["name", "sent_at", "subject"]
    assert normalized["relationship_types"][0]["properties"] == []
    assert not any(
        "body" in (c.get("property_names") or []) or c.get("property_name") == "body"
        for c in normalized["constraints"]
    )


def _without_email_name_constraint(schema: dict[str, Any]) -> None:
    schema["constraints"] = [c for c in schema["constraints"] if c["node_type"] != "Email"]


def _without_email_name_property(schema: dict[str, Any]) -> None:
    _without_email_name_constraint(schema)
    schema["node_types"][1]["properties"] = [
        p for p in schema["node_types"][1]["properties"] if p["name"] != "name"
    ]


def _with_node_text_property(schema: dict[str, Any]) -> None:
    schema["node_types"][1]["properties"].append(
        {"name": "content", "type": "STRING", "description": "", "required": False}
    )


def _with_relationship_text_property(schema: dict[str, Any]) -> None:
    schema["relationship_types"][0]["properties"].append(
        {"name": "text", "type": "STRING", "description": "", "required": False}
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_without_email_name_property, "lacks the STRING identity property"),
        (_without_email_name_constraint, "no mandatory constraint on its identity property"),
        (_with_node_text_property, "document text"),
        (_with_relationship_text_property, "document text"),
    ],
)
def test_domain_schema_rejects_anonymous_node_types_and_document_text_properties(
    mutate: Callable[[dict[str, Any]], None], message: str
) -> None:
    schema = canonical_schema_dict(normalize_domain_schema(_email_schema()))
    validate_domain_schema(schema)
    mutate(schema)
    with pytest.raises(ValueError, match=message):
        validate_domain_schema(schema)
