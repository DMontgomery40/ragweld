from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from server.db.neo4j import Neo4jClient
from server.indexing.graph_policy import GraphPolicy
from server.indexing.graphrag_pipeline import (
    require_staging_graph_id,
    resolution_property_for_policy,
)
from server.models.index import GraphExtractionTelemetry, GraphPromotionOverride

GraphInvariantFailureCode = Literal[
    "chunk_count_mismatch",
    "extraction_failure",
    "silent_truncation",
    "zero_entities",
    "zero_semantic_relationships",
    "missing_from_chunk_provenance",
    "cross_generation_node",
    "cross_generation_relationship",
    "unresolved_duplicate_entity",
    "missing_approved_schema",
]

_SPARSE_OVERRIDE_CODES = frozenset(
    {"zero_entities", "zero_semantic_relationships"}
)


@dataclass(frozen=True, slots=True)
class GraphInvariantReport:
    policy: GraphPolicy
    failure_codes: tuple[str, ...]
    total_chunks: int
    total_entities: int
    semantic_relationships: int
    from_chunk_relationships: int
    linked_chunks: int
    duplicate_groups: int
    cross_scope_nodes: int
    cross_scope_relationships: int

    @property
    def promotable(self) -> bool:
        return not self.failure_codes


class GraphPromotionRefusedError(RuntimeError):
    def __init__(self, report: GraphInvariantReport, *, detail: str | None = None) -> None:
        self.report = report
        self.operator_hint = (
            "Inspect the graph extraction and isolation telemetry, correct the source or "
            "configuration, then start a new index run; the previous generation remains active."
        )
        codes = ", ".join(report.failure_codes) or "override_not_authorized"
        message = detail or f"Graph promotion refused ({codes}). {self.operator_hint}"
        super().__init__(message)


def evaluate_graph_invariants(
    *,
    policy: GraphPolicy,
    expected_chunks: int,
    extraction: GraphExtractionTelemetry,
    schema_hash: str | None,
    counts: Mapping[str, int],
) -> GraphInvariantReport:
    total_chunks = int(counts.get("total_chunks", 0) or 0)
    total_entities = int(counts.get("total_entities", 0) or 0)
    semantic_relationships = int(counts.get("semantic_relationships", 0) or 0)
    from_chunk_relationships = int(counts.get("from_chunk_relationships", 0) or 0)
    linked_chunks = int(counts.get("linked_chunks", 0) or 0)
    duplicate_groups = int(counts.get("duplicate_groups", 0) or 0)
    cross_scope_nodes = int(counts.get("cross_scope_nodes", 0) or 0)
    cross_scope_relationships = int(counts.get("cross_scope_relationships", 0) or 0)
    failures: list[str] = []

    if total_chunks != int(expected_chunks):
        failures.append("chunk_count_mismatch")
    if policy == "semantic":
        if (
            extraction.failed_chunks > 0
            or extraction.succeeded_chunks != extraction.attempted_chunks
        ):
            failures.append("extraction_failure")
        if (
            extraction.truncated_chunks > 0
            or extraction.attempted_chunks != extraction.selected_chunks
        ):
            failures.append("silent_truncation")
    if total_entities == 0:
        failures.append("zero_entities")
    if semantic_relationships == 0:
        failures.append("zero_semantic_relationships")
    # An intentionally empty semantic graph can be audited through the sparse
    # override. Once any entity exists, every accepted graph must carry real
    # chunk provenance and touch at least one staged chunk.
    if total_entities > 0 and (from_chunk_relationships == 0 or linked_chunks == 0):
        failures.append("missing_from_chunk_provenance")
    if cross_scope_nodes > 0:
        failures.append("cross_generation_node")
    if cross_scope_relationships > 0:
        failures.append("cross_generation_relationship")
    if duplicate_groups > 0:
        failures.append("unresolved_duplicate_entity")
    if policy == "semantic" and not str(schema_hash or "").strip():
        failures.append("missing_approved_schema")

    return GraphInvariantReport(
        policy=policy,
        failure_codes=tuple(dict.fromkeys(failures)),
        total_chunks=total_chunks,
        total_entities=total_entities,
        semantic_relationships=semantic_relationships,
        from_chunk_relationships=from_chunk_relationships,
        linked_chunks=linked_chunks,
        duplicate_groups=duplicate_groups,
        cross_scope_nodes=cross_scope_nodes,
        cross_scope_relationships=cross_scope_relationships,
    )


async def verify_graph_promotion(
    *,
    neo4j: Neo4jClient,
    repo_id: str,
    policy: GraphPolicy,
    expected_chunks: int,
    extraction: GraphExtractionTelemetry,
    schema_hash: str | None,
) -> GraphInvariantReport:
    scoped_repo_id = require_staging_graph_id(repo_id)
    run_id = scoped_repo_id.rsplit("__", 1)[-1]
    counts = await neo4j.get_graph_invariant_counts(
        scoped_repo_id, run_id, identity_property=resolution_property_for_policy(policy)
    )
    report = evaluate_graph_invariants(
        policy=policy,
        expected_chunks=expected_chunks,
        extraction=extraction,
        schema_hash=schema_hash,
        counts=counts,
    )
    if not report.promotable:
        raise GraphPromotionRefusedError(report)
    return report


def authorize_sparse_graph_override(
    report: GraphInvariantReport,
    *,
    extraction: GraphExtractionTelemetry,
    actor: str | None,
    reason: str | None,
    now: datetime | None = None,
) -> GraphPromotionOverride:
    codes = frozenset(report.failure_codes)
    full_success = (
        extraction.selected_chunks > 0
        and extraction.attempted_chunks == extraction.selected_chunks
        and extraction.succeeded_chunks == extraction.selected_chunks
        and extraction.failed_chunks == 0
        and extraction.truncated_chunks == 0
    )
    if (
        report.policy != "semantic"
        or not codes
        or not codes.issubset(_SPARSE_OVERRIDE_CODES)
        or not full_success
        or not str(actor or "").strip()
        or not str(reason or "").strip()
    ):
        raise GraphPromotionRefusedError(
            report,
            detail=(
                "Graph promotion override is unavailable: it requires an authenticated "
                "Remote-User, a visible reason, a fully successful approved extraction, and "
                "only zero_entities/zero_semantic_relationships failures."
            ),
        )
    return GraphPromotionOverride(
        actor=str(actor).strip(),
        reason=str(reason).strip(),
        created_at=now or datetime.now(UTC),
        failure_codes=cast(
            list[Literal["zero_entities", "zero_semantic_relationships"]], sorted(codes)
        ),
    )


__all__ = [
    "GraphInvariantFailureCode",
    "GraphInvariantReport",
    "GraphPromotionRefusedError",
    "authorize_sparse_graph_override",
    "evaluate_graph_invariants",
    "verify_graph_promotion",
]
