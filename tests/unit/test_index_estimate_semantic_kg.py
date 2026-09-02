"""The semantic KG time estimate is per gateway round-trip, calibrated from the last run.

Task 8 drive finding D13: the Start-indexing dialog quoted "~12 min" for the Epstein rebuild
(3,126 chunks, 4 workers) whose previous execution took 2 h 07 min. The estimator modelled one
extraction call per second per worker; Luna at medium effort answers one chunk in roughly ten
seconds through the gateway. Two things fix that for good: a measured rate carried on the run
record (worker-seconds spent inside the extraction calls, divided by the chunks they covered)
that the next estimate for the same alias reuses, and a default that reflects a reasoning
model's real round-trip when no measurement exists.
"""

from __future__ import annotations

from datetime import UTC, datetime

from server.api.index import (
    _SEMANTIC_KG_SECONDS_PER_CHUNK_DEFAULT,
    _estimate_semantic_kg_seconds,
    _measured_semantic_kg_seconds_per_chunk,
    _semantic_kg_seconds_assumption,
)
from server.models.index import (
    GraphExtractionTelemetry,
    GraphGenerationMetadata,
    GraphResolutionTelemetry,
    IndexRunSummary,
)

EPSTEIN_CHUNKS = 3126
EPSTEIN_WORKERS = 4
EPSTEIN_WALL_SECONDS = 7654.0  # run ca5b8d92: 21:46:27 -> 23:54:01 UTC
LUNA = "openai.gpt-5.6-luna"


def _run(
    *,
    policy: str = "semantic",
    alias: str = LUNA,
    worker_seconds: float = 31_260.0,
    succeeded: int = EPSTEIN_CHUNKS,
    status: str = "complete",
) -> IndexRunSummary:
    extraction = GraphExtractionTelemetry(
        selected_chunks=succeeded,
        attempted_chunks=succeeded,
        succeeded_chunks=succeeded,
        failed_chunks=0,
        truncated_chunks=0,
        extracted_entities=10,
        semantic_relationships=5,
        from_chunk_relationships=10,
        llm_model_alias=alias,
        workers=EPSTEIN_WORKERS,
        worker_seconds=worker_seconds,
    )
    return IndexRunSummary(
        run_id="ca5b8d92938f4f00a9e0b5ff8f63ce22",
        repo_id="epstein-files-public",
        status=status,  # type: ignore[arg-type]
        started_at=datetime(2026, 9, 1, 21, 46, 27, tzinfo=UTC),
        completed_at=datetime(2026, 9, 1, 23, 54, 1, tzinfo=UTC),
        progress=1.0,
        total_chunks=succeeded,
        graph_metadata=GraphGenerationMetadata(
            policy=policy,  # type: ignore[arg-type]
            extraction=extraction,
            resolution=GraphResolutionTelemetry(
                candidate_nodes=10, resolved_nodes=10, merged_nodes=0, unresolved_duplicate_groups=0
            ),
        ),
    )


def test_telemetry_carries_the_measurement_and_defaults_to_unmeasured() -> None:
    bare = GraphExtractionTelemetry(
        selected_chunks=0,
        attempted_chunks=0,
        succeeded_chunks=0,
        failed_chunks=0,
        truncated_chunks=0,
        extracted_entities=0,
        semantic_relationships=0,
        from_chunk_relationships=0,
    )
    assert bare.llm_model_alias == ""
    assert bare.workers == 0
    assert bare.worker_seconds == 0.0


def test_default_rate_reflects_a_reasoning_models_round_trip_not_one_call_per_second() -> None:
    seconds = _estimate_semantic_kg_seconds(
        chunks_in_scope=EPSTEIN_CHUNKS,
        indexing_workers=EPSTEIN_WORKERS,
        seconds_per_chunk=_SEMANTIC_KG_SECONDS_PER_CHUNK_DEFAULT,
    )
    # Within a factor of 1.5 of the measured 2 h 07 min run, not the 12 minutes it quoted.
    assert EPSTEIN_WALL_SECONDS / 1.5 <= seconds <= EPSTEIN_WALL_SECONDS * 1.5
    assert seconds > 60 * 60


def test_estimate_divides_by_the_workers_that_run_in_parallel() -> None:
    one = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=1, seconds_per_chunk=10.0)
    four = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=4, seconds_per_chunk=10.0)
    sixteen = _estimate_semantic_kg_seconds(chunks_in_scope=100, indexing_workers=16, seconds_per_chunk=10.0)
    assert one == 1000.0
    assert four == 250.0
    # The runtime never fans out beyond eight concurrent extraction calls.
    assert sixteen == 125.0
    assert _estimate_semantic_kg_seconds(chunks_in_scope=0, indexing_workers=4, seconds_per_chunk=10.0) == 0.0


def test_measured_rate_comes_from_the_last_complete_semantic_run_for_the_same_alias() -> None:
    measured = _measured_semantic_kg_seconds_per_chunk(_run(), alias=LUNA)
    assert measured == 31_260.0 / EPSTEIN_CHUNKS  # 10 s per chunk per worker
    seconds = _estimate_semantic_kg_seconds(
        chunks_in_scope=EPSTEIN_CHUNKS, indexing_workers=EPSTEIN_WORKERS, seconds_per_chunk=measured
    )
    assert abs(seconds - 7815.0) < 1e-6


def test_measurement_is_ignored_when_it_cannot_speak_for_this_run() -> None:
    assert _measured_semantic_kg_seconds_per_chunk(None, alias=LUNA) is None
    # A different model: its latency says nothing about this alias.
    assert _measured_semantic_kg_seconds_per_chunk(_run(alias="deepseek.deepseek-v4-flash"), alias=LUNA) is None
    # A code-policy run never called the extraction LLM.
    assert _measured_semantic_kg_seconds_per_chunk(_run(policy="code"), alias=LUNA) is None
    # A run recorded before the measurement existed carries zero worker-seconds.
    assert _measured_semantic_kg_seconds_per_chunk(_run(worker_seconds=0.0), alias=LUNA) is None
    # No succeeded chunks: nothing to divide by.
    assert _measured_semantic_kg_seconds_per_chunk(_run(succeeded=0), alias=LUNA) is None


def test_assumption_names_the_source_of_the_rate() -> None:
    measured = _semantic_kg_seconds_assumption(
        chunks=EPSTEIN_CHUNKS,
        workers=EPSTEIN_WORKERS,
        seconds_per_chunk=10.0,
        measured_run=_run(),
    )
    assert "3,126 chunks" in measured
    assert "10.0s per chunk per worker" in measured
    assert "measured on run ca5b8d92" in measured
    assert "4 in parallel" in measured
    default = _semantic_kg_seconds_assumption(
        chunks=EPSTEIN_CHUNKS, workers=EPSTEIN_WORKERS, seconds_per_chunk=10.0, measured_run=None
    )
    assert "default" in default and "no completed run" in default
