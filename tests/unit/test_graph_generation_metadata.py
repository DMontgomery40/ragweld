from server.indexing.generations import build_generation
from server.models.index import (
    GraphExtractionTelemetry,
    GraphGenerationMetadata,
    GraphResolutionTelemetry,
)


def test_generation_manifest_keeps_the_exact_reviewed_schema_and_run_telemetry() -> None:
    schema = {
        "node_types": [{"label": "Astronaut", "description": "A crew member", "properties": []}],
        "relationship_types": [{"label": "FLEW_ON", "description": "Mission assignment"}],
        "patterns": [{"source": "Astronaut", "relationship": "FLEW_ON", "target": "Mission"}],
        "constraints": [],
        "additional_node_types": False,
        "additional_relationship_types": False,
        "additional_patterns": False,
    }
    metadata = GraphGenerationMetadata(
        policy="semantic",
        schema_hash="a" * 64,
        schema=schema,
        extraction=GraphExtractionTelemetry(
            selected_chunks=12,
            attempted_chunks=12,
            succeeded_chunks=12,
            failed_chunks=0,
            truncated_chunks=0,
            extracted_entities=8,
            semantic_relationships=5,
            from_chunk_relationships=8,
        ),
        resolution=GraphResolutionTelemetry(
            candidate_nodes=8,
            resolved_nodes=8,
            merged_nodes=0,
            unresolved_duplicate_groups=0,
        ),
    )

    manifest = build_generation(
        run_id="schema-reviewed",
        qdrant_collection="qdrant-generation",
        graph_repo_id="graph-generation",
        graph_metadata=metadata,
    )

    assert manifest.graph_metadata == metadata
    dumped = manifest.model_dump(mode="json")
    assert dumped["graph_metadata"]["schema_hash"] == "a" * 64
    assert dumped["graph_metadata"]["schema"] == schema
    assert "schema_payload" not in dumped["graph_metadata"]
