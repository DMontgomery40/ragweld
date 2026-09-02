"""The dashboard storage breakdown tells "unmeasured" apart from "0 B".

Neo4j 5 Community exposes no store-size source, and the old breakdown rendered that as a
measured-looking `neo4j_store_bytes=0` ("0 B (0.0% of total)") beside a graph holding
thousands of nodes. An unmeasured store is null and says why; a measured store carries no
note; a breakdown cannot be built half-stated.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from server.models.tribrid_config_model import DashboardIndexStorageBreakdown

REASON = "Not measured: Neo4j 5 exposes no store-size procedure."


def _measurements(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "chunks_bytes": 3_000,
        "chunk_summaries_bytes": 500,
        "qdrant_points": 10,
        "qdrant_dense_vector_bytes": 10 * 1536 * 4,
        "neo4j_store_bytes": None,
        "neo4j_store_note": REASON,
        "postgres_total_bytes": 3_500,
        "total_storage_bytes": 3_500 + 10 * 1536 * 4,
    }
    fields.update(overrides)
    return fields


def test_an_unmeasured_store_is_null_with_its_reason() -> None:
    breakdown = DashboardIndexStorageBreakdown(**_measurements())
    assert breakdown.neo4j_store_bytes is None
    assert breakdown.neo4j_store_note == REASON
    # The wire shape the dashboard reads: null, not 0.
    assert breakdown.model_dump(mode="json")["neo4j_store_bytes"] is None


def test_an_unmeasured_store_must_say_why() -> None:
    with pytest.raises(ValidationError, match="neo4j_store_note"):
        DashboardIndexStorageBreakdown(**_measurements(neo4j_store_note=None))
    with pytest.raises(ValidationError, match="neo4j_store_note"):
        DashboardIndexStorageBreakdown(**_measurements(neo4j_store_note="   "))


def test_a_measured_store_carries_no_note() -> None:
    measured = DashboardIndexStorageBreakdown(**_measurements(neo4j_store_bytes=4096, neo4j_store_note=None))
    assert measured.neo4j_store_bytes == 4096
    assert measured.neo4j_store_note is None
    with pytest.raises(ValidationError, match="neo4j_store_note"):
        DashboardIndexStorageBreakdown(**_measurements(neo4j_store_bytes=4096))


def test_a_negative_measurement_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DashboardIndexStorageBreakdown(**_measurements(neo4j_store_bytes=-1, neo4j_store_note=None))


def test_a_breakdown_is_never_built_from_defaults() -> None:
    # There is no honest default measurement: a breakdown is built from real readings or not at all.
    with pytest.raises(ValidationError):
        DashboardIndexStorageBreakdown()
