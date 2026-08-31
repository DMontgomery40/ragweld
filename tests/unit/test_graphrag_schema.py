from datetime import UTC, datetime

import pytest
from neo4j_graphrag.components.schema import GraphSchema, NodeType, Pattern, PropertyType, RelationshipType
from pydantic import ValidationError

from server.indexing.graphrag_schema import (
    canonical_schema_dict,
    graph_schema_hash,
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
