"""Measured chunk outcomes, durable summary ordering, and immutable source bytes."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.api.index import _measured_semantic_kg_seconds_per_chunk
from server.indexing.extraction_checkpoint import ExtractionProgress
from server.indexing.graph_progress import GraphProgressOwner, GraphProgressState
from server.indexing.run_records import (
    initialize_run_accounting,
    persist_graph_progress,
    update_run_accounting,
    write_run_summary,
)
from server.indexing.source_snapshot import SourceSnapshot
from server.models.index import (
    GraphExtractionTelemetry,
    GraphGenerationMetadata,
    GraphResolutionTelemetry,
    IndexRunSummary,
)
from server.models.run_accounting import IndexRunAccounting

RUN = "a" * 32
CORPUS = "apollo-progress"


def telemetry(**updates: object) -> GraphExtractionTelemetry:
    return GraphExtractionTelemetry.model_validate({
        "selected_chunks": 0, "attempted_chunks": 0, "succeeded_chunks": 0,
        "failed_chunks": 0, "truncated_chunks": 0, "extracted_entities": 0,
        "semantic_relationships": 0, "from_chunk_relationships": 0,
        "outcome_version": "checkpoint_v1", "progress_owner_run_id": RUN,
        "progress_sequence": 0, "reused_chunks": 0, "cancelled_chunks": 0,
        "unfinished_chunks": 0, "llm_model_alias": "openai.gpt-5.6-sol",
        **updates,
    })


def summary(extraction: GraphExtractionTelemetry | None = None) -> IndexRunSummary:
    return IndexRunSummary(
        run_id=RUN, repo_id=CORPUS, status="indexing", started_at=datetime.now(UTC),
        graph_metadata=GraphGenerationMetadata(
            policy="semantic", extraction=extraction or telemetry(),
            resolution=GraphResolutionTelemetry(candidate_nodes=0, resolved_nodes=0,
                                                merged_nodes=0, unresolved_duplicate_groups=0),
        ),
    )


def event(sequence: int, chunk: int, phase: str, duration: float = 0) -> ExtractionProgress:
    return ExtractionProgress(
        repo_id=CORPUS, owner_run_id=RUN, sequence=sequence,
        cache_key=f"{chunk:064x}", file_path="A11_MissionReport.pdf",
        chunk_id=f"apollo-section-{chunk}", chunk_index=chunk,
        phase=phase, duration_s=duration,  # type: ignore[arg-type]
    )


def test_selected_work_does_not_become_attempted_until_admitted_and_success_is_durable() -> None:
    current = telemetry()
    state = GraphProgressState(CORPUS, RUN, current)
    for chunk in range(4):
        state.apply(event(chunk + 1, chunk, "selected"))
    assert (current.selected_chunks, current.attempted_chunks, current.unfinished_chunks) == (4, 0, 4)
    state.apply(event(5, 0, "admitted"))
    state.apply(event(6, 0, "dispatching"))
    assert current.succeeded_chunks == 0
    state.apply(event(7, 0, "succeeded", 12))
    state.apply(event(8, 1, "admitted"))
    state.apply(event(9, 1, "reused"))
    state.apply(event(10, 2, "failed"))  # preparation failed before admission
    state.apply(event(11, 3, "cancelled"))  # still queued at cancellation
    assert (current.attempted_chunks, current.succeeded_chunks, current.reused_chunks) == (2, 2, 1)
    assert (current.failed_chunks, current.cancelled_chunks, current.unfinished_chunks) == (1, 1, 0)
    assert current.worker_seconds == 12
    assert GraphExtractionTelemetry.model_validate_json(current.model_dump_json()) == current


@pytest.mark.parametrize("terminal", ["succeeded", "failed", "cancelled"])
def test_fresh_duration_counts_once_and_stale_events_cannot_move_progress_back(terminal: str) -> None:
    current = telemetry()
    state = GraphProgressState(CORPUS, RUN, current)
    for seq, phase in enumerate(("selected", "admitted", "dispatching", terminal), 1):
        state.apply(event(seq, 0, phase, 7 if seq == 4 else 0))
    before = current.model_dump()
    state.apply(event(4, 0, terminal, 7))
    state.apply(event(1, 0, "selected"))
    assert current.model_dump() == before
    assert current.worker_seconds == 7
    assert current.unfinished_chunks == 0


@pytest.mark.parametrize("invalid", ["owner", "corpus", "sequence", "unknown_chunk", "transition", "duration"])
def test_invalid_events_fail_closed(invalid: str) -> None:
    state = GraphProgressState(CORPUS, RUN, telemetry())
    state.apply(event(1, 0, "selected"))
    bad = event(2, 0, "admitted")
    if invalid == "owner":
        bad = replace(bad, owner_run_id="b" * 32)
    elif invalid == "corpus":
        bad = replace(bad, repo_id="other-corpus")
    elif invalid == "sequence":
        bad = replace(bad, sequence=3)
    elif invalid == "unknown_chunk":
        bad = replace(bad, cache_key="f" * 64)
    elif invalid == "transition":
        bad = replace(bad, phase="succeeded")
    else:
        bad = replace(bad, duration_s=float("nan"))
    with pytest.raises(ValueError):
        state.apply(bad)


def test_historical_whole_file_aggregate_is_preserved_without_inventing_outcomes() -> None:
    old = telemetry().model_dump(exclude={
        "outcome_version", "progress_owner_run_id", "progress_sequence", "reused_chunks",
        "cancelled_chunks", "unfinished_chunks",
    })
    old.update(selected_chunks=1002, attempted_chunks=1002, failed_chunks=1002)
    restored = GraphExtractionTelemetry.model_validate(old)
    assert restored.outcome_version == "whole_file_v0"
    assert restored.selected_chunks == restored.attempted_chunks == restored.failed_chunks == 1002
    assert restored.reused_chunks is restored.cancelled_chunks is restored.unfinished_chunks is None


def test_run_boundary_rejects_extraction_from_another_owner() -> None:
    with pytest.raises(ValidationError, match="Graph progress"):
        summary(telemetry(progress_owner_run_id="b" * 32))


@pytest.mark.parametrize("changes", [
    {"unfinished_chunks": 1, "succeeded_chunks": 3},
    {"cancelled_chunks": 1, "succeeded_chunks": 3},
    {"failed_chunks": 1, "succeeded_chunks": 3},
    {"reused_chunks": None}, {"reused_chunks": -1},
])
def test_latency_refuses_incomplete_or_invalid_internal_v1_measurements(changes: dict[str, object]) -> None:
    extraction = telemetry(selected_chunks=4, attempted_chunks=4, succeeded_chunks=4, worker_seconds=48)
    run = summary(extraction).model_copy(update={"status": "complete"})
    assert run.graph_metadata is not None
    run.graph_metadata.extraction = extraction.model_copy(update=changes)
    assert _measured_semantic_kg_seconds_per_chunk(run, alias="openai.gpt-5.6-sol") is None


@pytest.mark.parametrize("updates", [
    {"reused_chunks": None}, {"cancelled_chunks": None}, {"unfinished_chunks": None},
    {"progress_owner_run_id": None}, {"attempted_chunks": 1}, {"reused_chunks": 1},
    {"failed_chunks": 1}, {"selected_chunks": 1},
])
def test_v1_public_boundary_refuses_missing_or_inconsistent_outcomes(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        telemetry(**updates)


@pytest.mark.parametrize("first", ["progress", "accounting"])
def test_delayed_summary_updates_preserve_both_progress_and_accounting(tmp_path: Path, first: str) -> None:
    path = tmp_path / "summary.json"
    stale = summary()
    write_run_summary(path, stale)
    initialize_run_accounting(path, IndexRunAccounting(
        session_id=RUN, corpus_id=CORPUS, started_at=stale.started_at,
        config_fingerprint="f" * 64, models={},
    ))
    progress = telemetry(selected_chunks=2, unfinished_chunks=2, progress_sequence=2)
    waiting, release = threading.Event(), threading.Event()

    def persist_progress() -> None:
        persist_graph_progress(path, repo_id=CORPUS, run_id=RUN, extraction=progress)

    def persist_accounting() -> None:
        update_run_accounting(path, lambda previous: previous.model_copy(update={"processed_chunks": 17}))

    def delayed() -> None:
        waiting.set()
        assert release.wait(5)
        (persist_progress if first == "accounting" else persist_accounting)()

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(delayed)
        assert waiting.wait(5)
        (persist_progress if first == "progress" else persist_accounting)()
        release.set()
        pending.result(5)
    write_run_summary(path, stale.model_copy(update={"status": "error", "graph_promotable": False}))
    persist_graph_progress(path, repo_id=CORPUS, run_id=RUN, extraction=telemetry())
    result = IndexRunSummary.model_validate_json(path.read_text())
    assert result.accounting is not None and result.accounting.processed_chunks == 17
    assert result.graph_metadata is not None
    assert result.graph_metadata.extraction == progress
    assert result.status == "error" and result.graph_promotable is False
    with pytest.raises(ValueError, match="owner|run"):
        persist_graph_progress(path, repo_id=CORPUS, run_id="b" * 32, extraction=progress)


@pytest.mark.asyncio
async def test_owned_queue_persists_final_outcomes_and_refuses_missing_summary(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    initial = summary()
    write_run_summary(path, initial)
    assert initial.graph_metadata is not None
    owner = GraphProgressOwner(path, CORPUS, RUN, initial.graph_metadata.extraction)
    for seq, phase in enumerate(("selected", "admitted", "dispatching", "succeeded"), 1):
        owner(event(seq, 0, phase, 3 if phase == "succeeded" else 0))
    await owner.close()
    result = IndexRunSummary.model_validate_json(path.read_text())
    assert result.graph_metadata is not None and result.graph_metadata.extraction.succeeded_chunks == 1
    assert result.graph_metadata.extraction.worker_seconds == 3
    missing = GraphProgressOwner(tmp_path / "absent.json", CORPUS, RUN, telemetry())
    missing(event(1, 0, "selected"))
    with pytest.raises(OSError):
        await missing.close()


@pytest.mark.asyncio
async def test_progress_close_retains_persistence_through_repeated_cancellation(tmp_path: Path) -> None:
    import fcntl

    path = tmp_path / "summary.json"
    initial = summary()
    write_run_summary(path, initial)
    assert initial.graph_metadata is not None
    owner = GraphProgressOwner(path, CORPUS, RUN, initial.graph_metadata.extraction)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        owner(event(1, 0, "selected"))
        closing = asyncio.create_task(owner.close())
        await asyncio.sleep(0.05)
        closing.cancel()
        await asyncio.sleep(0.05)
        closing.cancel()
        assert not closing.done()
        fcntl.flock(lock, fcntl.LOCK_UN)
        with pytest.raises(asyncio.CancelledError):
            await closing
    restored = IndexRunSummary.model_validate_json(path.read_text())
    assert restored.graph_metadata is not None and restored.graph_metadata.extraction.selected_chunks == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "failed", "cancelled"])
@pytest.mark.parametrize("persistence_fails", [False, True])
async def test_progress_context_preserves_primary_outcome_and_independent_failure_codes(
    tmp_path: Path, outcome: str, persistence_fails: bool,
) -> None:
    path = tmp_path / "summary.json"
    if not persistence_fails:
        write_run_summary(path, summary())
    owner = GraphProgressOwner(path, CORPUS, RUN, telemetry())
    primary = RuntimeError("source extraction failed") if outcome == "failed" else (
        asyncio.CancelledError("operator stopped indexing") if outcome == "cancelled" else None
    )
    caught: BaseException | None = None
    try:
        async with owner:
            owner(event(1, 0, "selected"))
            if primary is not None:
                raise primary
    except BaseException as error:
        caught = error
    assert caught is (primary if primary is not None else owner.error)
    assert owner.writer.done() and owner.queue.empty()
    assert (owner.error is not None) is persistence_fails
    expected = ["progress_persistence_failure"] if persistence_fails else []
    if outcome == "failed":
        expected.append("graph_build_or_promotion_failure")
    assert owner.failure_codes(caught) == expected
    if primary is not None and persistence_fails:
        assert any("Graph progress" in note for note in primary.__notes__)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["complete", "failed", "cancelled"])
@pytest.mark.parametrize("persistence_fails", [False, True])
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_progress_close_retains_late_cancellation_and_a_blocked_writer_failure(
    tmp_path: Path, outcome: str, persistence_fails: bool, cancel_count: int,
) -> None:
    import fcntl

    path = tmp_path / "summary.json"
    if not persistence_fails:
        write_run_summary(path, summary())
    owner = GraphProgressOwner(path, CORPUS, RUN, telemetry())
    primary = RuntimeError("source extraction failed") if outcome == "failed" else (
        asyncio.CancelledError("body cancelled") if outcome == "cancelled" else None
    )

    async def run_with_progress() -> None:
        async with owner:
            owner(event(1, 0, "selected"))
            if primary is not None:
                raise primary

    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        running = asyncio.create_task(run_with_progress())
        caught: BaseException | None = None
        try:
            async with asyncio.timeout(5):
                while not owner.closed:
                    await asyncio.sleep(0)
            assert not owner.writer.done() and owner.error is None
            for _ in range(cancel_count):
                running.cancel("late operator stop")
                await asyncio.sleep(0)
                assert not running.done(), "Cancellation cannot detach the blocked writer"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            try:
                await running
            except BaseException as error:
                caught = error
    if primary is not None:
        assert caught is primary
    else:
        assert isinstance(caught, asyncio.CancelledError)
    assert owner.writer.done() and owner.queue.empty()
    assert (owner.error is not None) is persistence_fails
    expected = ["progress_persistence_failure"] if persistence_fails else []
    if outcome == "failed":
        expected.append("graph_build_or_promotion_failure")
    assert owner.failure_codes(caught) == expected
    if persistence_fails:
        assert any("Graph progress" in note for note in caught.__notes__)


@pytest.mark.parametrize("reused", [0, 2, 4])
def test_measured_worker_latency_excludes_checkpoint_hits(reused: int) -> None:
    extraction = telemetry(selected_chunks=4, attempted_chunks=4, succeeded_chunks=4,
                           reused_chunks=reused, worker_seconds=12 * (4 - reused))
    run = summary(extraction).model_copy(update={"status": "complete"})
    measured = _measured_semantic_kg_seconds_per_chunk(run, alias="openai.gpt-5.6-sol")
    assert measured == (12 if reused < 4 else None)
    assert _measured_semantic_kg_seconds_per_chunk(run, alias="openai.gpt-5.6-luna") is None
    assert _measured_semantic_kg_seconds_per_chunk(run.model_copy(update={"status": "error"}), alias="openai.gpt-5.6-sol") is None


@pytest.mark.parametrize("suffix", [".txt", ".md", ".pdf", ".parquet"])
def test_source_snapshot_digest_and_consumed_bytes_survive_source_replacement(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / f"mission{suffix}"
    original = b"Apollo 11 used the Eagle lunar module.\n" * 100
    source.write_bytes(original)
    with SourceSnapshot.capture(source, max_bytes=len(original)) as snapshot:
        assert snapshot.path.suffix == suffix
        assert snapshot.path != source and snapshot.path.stat().st_mode & 0o077 == 0
        source.write_bytes(b"Apollo 12 used Intrepid.\n")
        assert snapshot.path.read_bytes() == original
        assert snapshot.sha256 == hashlib.sha256(original).hexdigest()
        assert snapshot.byte_size == len(original)
        frozen_path = snapshot.path
    assert not frozen_path.exists()


def test_failed_snapshot_target_creation_cleans_its_owned_directory(tmp_path: Path) -> None:
    before = set(Path(tempfile.gettempdir()).glob("ragweld-source-*"))
    try:
        with pytest.raises(OSError):
            SourceSnapshot.capture(tmp_path / ("a" * 300 + ".pdf"), max_bytes=1024)
        assert set(Path(tempfile.gettempdir()).glob("ragweld-source-*")) == before
    finally:
        for directory in set(Path(tempfile.gettempdir()).glob("ragweld-source-*")) - before:
            directory.rmdir()


@pytest.mark.parametrize("limit,delta", [(0, 0), (0, 1), (1, 0), (1, 1), (1024 * 1024, 0), (1024 * 1024, 1)])
def test_source_snapshot_enforces_stream_ceiling_and_cleans_rejected_copy(
    tmp_path: Path, limit: int, delta: int,
) -> None:
    source = tmp_path / "mission.txt"
    content = b"a" * (limit + delta)
    source.write_bytes(content)
    before = set(Path(tempfile.gettempdir()).glob("ragweld-source-*"))
    if delta:
        with pytest.raises(ValueError, match="file size limit"):
            SourceSnapshot.capture(source, max_bytes=limit)
    else:
        with SourceSnapshot.capture(source, max_bytes=limit) as snapshot:
            assert snapshot.byte_size == limit
            assert snapshot.path.read_bytes() == content
            assert snapshot.sha256 == hashlib.sha256(content).hexdigest()
    assert set(Path(tempfile.gettempdir()).glob("ragweld-source-*")) == before


def test_source_snapshot_stops_a_stream_at_the_limit_without_waiting_for_eof(tmp_path: Path) -> None:
    source = tmp_path / "growing.txt"
    os.mkfifo(source)
    descriptor = os.open(source, os.O_RDWR)
    os.write(descriptor, b"a" * 1025)
    before = set(Path(tempfile.gettempdir()).glob("ragweld-source-*"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        copying = pool.submit(SourceSnapshot.capture, source, max_bytes=1024)
        try:
            # The real writer remains open: an EOF-based or stat-only ceiling
            # would wait forever. A bounded read must reject the extra byte now.
            with pytest.raises(ValueError, match="file size limit"):
                copying.result(timeout=2)
        finally:
            os.close(descriptor)
    assert set(Path(tempfile.gettempdir()).glob("ragweld-source-*")) == before
