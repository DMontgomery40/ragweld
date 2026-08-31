from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from server.indexing.graph_invariants import (
    GraphInvariantReport,
    GraphPromotionRefusedError,
    authorize_sparse_graph_override,
    evaluate_graph_invariants,
)
from server.models.index import GraphExtractionTelemetry, IndexRequest


def _extraction(**updates: int) -> GraphExtractionTelemetry:
    values = {
        "selected_chunks": 2,
        "attempted_chunks": 2,
        "succeeded_chunks": 2,
        "failed_chunks": 0,
        "truncated_chunks": 0,
        "extracted_entities": 2,
        "semantic_relationships": 1,
        "from_chunk_relationships": 2,
    }
    values.update(updates)
    return GraphExtractionTelemetry(**values)


def _counts(**updates: int) -> dict[str, int]:
    values = {
        "total_chunks": 2,
        "total_entities": 2,
        "semantic_relationships": 1,
        "from_chunk_relationships": 2,
        "linked_chunks": 2,
        "duplicate_groups": 0,
        "cross_scope_nodes": 0,
        "cross_scope_relationships": 0,
    }
    values.update(updates)
    return values


@pytest.mark.parametrize(
    ("extraction", "counts", "failure_code"),
    [
        (_extraction(failed_chunks=1, succeeded_chunks=1), _counts(), "extraction_failure"),
        (
            _extraction(attempted_chunks=1, succeeded_chunks=1, truncated_chunks=1),
            _counts(),
            "silent_truncation",
        ),
        (_extraction(), _counts(total_entities=0), "zero_entities"),
        (
            _extraction(),
            _counts(semantic_relationships=0),
            "zero_semantic_relationships",
        ),
        (
            _extraction(),
            _counts(from_chunk_relationships=0, linked_chunks=0),
            "missing_from_chunk_provenance",
        ),
        (_extraction(), _counts(cross_scope_nodes=1), "cross_generation_node"),
        (
            _extraction(),
            _counts(cross_scope_relationships=1),
            "cross_generation_relationship",
        ),
        (
            _extraction(),
            _counts(duplicate_groups=1),
            "unresolved_duplicate_entity",
        ),
    ],
)
def test_semantic_invariant_matrix_has_stable_typed_failure_codes(
    extraction: GraphExtractionTelemetry,
    counts: dict[str, int],
    failure_code: str,
) -> None:
    report = evaluate_graph_invariants(
        policy="semantic",
        expected_chunks=2,
        extraction=extraction,
        schema_hash="a" * 64,
        counts=counts,
    )

    assert failure_code in report.failure_codes
    assert report.promotable is False


def test_sparse_override_is_only_available_for_complete_empty_semantic_extraction() -> None:
    report = evaluate_graph_invariants(
        policy="semantic",
        expected_chunks=2,
        extraction=_extraction(extracted_entities=0, semantic_relationships=0),
        schema_hash="a" * 64,
        counts=_counts(total_entities=0, semantic_relationships=0),
    )

    override = authorize_sparse_graph_override(
        report,
        extraction=_extraction(extracted_entities=0, semantic_relationships=0),
        actor="operator@example.test",
        reason="The reviewed corpus is intentionally entity sparse.",
        now=datetime(2026, 8, 31, tzinfo=UTC),
    )

    assert override.actor == "operator@example.test"
    assert override.failure_codes == ["zero_entities", "zero_semantic_relationships"]


@pytest.mark.parametrize(
    ("actor", "reason", "extra_failure"),
    [
        (None, "The reviewed corpus is intentionally entity sparse.", None),
        ("operator@example.test", None, None),
        (
            "operator@example.test",
            "The reviewed corpus is intentionally entity sparse.",
            "missing_from_chunk_provenance",
        ),
    ],
)
def test_sparse_override_refuses_missing_audit_identity_reason_or_nonempty_failure(
    actor: str | None,
    reason: str | None,
    extra_failure: str | None,
) -> None:
    codes = ["zero_entities", "zero_semantic_relationships"]
    if extra_failure:
        codes.append(extra_failure)
    report = GraphInvariantReport(
        policy="semantic",
        failure_codes=tuple(codes),
        total_chunks=2,
        total_entities=0,
        semantic_relationships=0,
        from_chunk_relationships=0,
        linked_chunks=0,
        duplicate_groups=0,
        cross_scope_nodes=0,
        cross_scope_relationships=0,
    )

    with pytest.raises(GraphPromotionRefusedError):
        authorize_sparse_graph_override(
            report,
            extraction=_extraction(extracted_entities=0, semantic_relationships=0),
            actor=actor,
            reason=reason,
            now=datetime(2026, 8, 31, tzinfo=UTC),
        )


def test_index_request_requires_twenty_visible_override_characters() -> None:
    with pytest.raises(ValidationError, match="visible characters"):
        IndexRequest(
            corpus_id="sparse",
            repo_path="/tmp/sparse",
            graph_empty_override_reason=" " * 20,
        )
