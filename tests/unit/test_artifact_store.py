"""Versioned active-artifact store: reader-atomic pointer switch, durable marker, recovery.

The store replaces the rename-window promotion swap: versions are immutable
directories under `<root>/versions/`, the active one is named by a fsynced
pointer file, and a crash anywhere inside a promotion is repaired
deterministically by `recover_artifact_store`. A reader that resolves the
active artifact during a promotion must never observe a missing path.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from server.training.artifact_store import (
    ArtifactStoreError,
    VersionedArtifactSwap,
    active_pointer_state,
    pointer_path,
    recover_artifact_store,
    resolve_active_artifact_dir,
    versions_dir,
)

RUN_A = "epstein-files-1__20260823_090000"
RUN_B = "epstein-files-1__20260823_100000"
RUN_C = "epstein-files-1__20260823_110000"


def _make_artifact(base: Path, name: str, payload: str) -> Path:
    src = base / "runs" / name / "model"
    src.mkdir(parents=True)
    (src / "adapter.npz").write_bytes(payload.encode("utf-8") * 64)
    (src / "adapter_config.json").write_text(json.dumps({"lora_rank": 16, "tag": payload}), encoding="utf-8")
    sub = src / "extras"
    sub.mkdir()
    (sub / "projection_dirs.npz").write_bytes(payload.encode("utf-8"))
    return src


def _promote(root: Path, src: Path, run_id: str, *, prepare=None) -> VersionedArtifactSwap:
    swap = VersionedArtifactSwap(src, root, run_id=run_id, prepare=prepare)
    swap.begin()
    return swap


def _read_tag(active: Path) -> str:
    return json.loads((active / "adapter_config.json").read_text(encoding="utf-8"))["tag"]


# -- publish / resolve -----------------------------------------------------------------


def test_first_promotion_publishes_an_immutable_version_and_pointer(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    src = _make_artifact(tmp_path, RUN_A, "alpha")
    swap = _promote(root, src, RUN_A)
    # readers already see the new version between begin() and commit()
    active = resolve_active_artifact_dir(root)
    assert active is not None and active.is_dir()
    assert _read_tag(active) == "alpha"
    assert active.parent == versions_dir(root)
    assert swap.commit() is None
    state = active_pointer_state(root)
    assert state is not None
    assert state.run_id == RUN_A
    # the whole tree was copied, including subdirectories
    assert (active / "extras" / "projection_dirs.npz").read_bytes() == b"alpha"


def test_resolve_returns_none_when_nothing_was_ever_promoted(tmp_path: Path) -> None:
    root = tmp_path / "learning-agent-active"
    assert resolve_active_artifact_dir(root) is None
    assert active_pointer_state(root) is None


def test_unreadable_pointer_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    src = _make_artifact(tmp_path, RUN_A, "alpha")
    _promote(root, src, RUN_A).commit()
    pointer_path(root).write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactStoreError):
        resolve_active_artifact_dir(root)


def test_pointer_naming_a_missing_version_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    src = _make_artifact(tmp_path, RUN_A, "alpha")
    swap = _promote(root, src, RUN_A)
    swap.commit()
    active = resolve_active_artifact_dir(root)
    assert active is not None
    import shutil

    shutil.rmtree(active)
    with pytest.raises(ArtifactStoreError):
        resolve_active_artifact_dir(root)


# -- rollback --------------------------------------------------------------------------


def test_rollback_restores_the_previous_version_pointer(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    swap = _promote(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B)
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "beta"
    swap.rollback()
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "alpha"
    # no marker survives a rollback; a later promotion starts clean
    assert recover_artifact_store(root) is None


def test_rollback_of_the_first_promotion_removes_the_pointer(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    swap = _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A)
    assert resolve_active_artifact_dir(root) is not None
    swap.rollback()
    assert resolve_active_artifact_dir(root) is None


# -- retention / pruning ---------------------------------------------------------------


def test_commit_retains_current_and_the_just_retired_version_only(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    _promote(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B).commit()
    _promote(root, _make_artifact(tmp_path, RUN_C, "gamma"), RUN_C).commit()
    names = sorted(p.name for p in versions_dir(root).iterdir())
    # a reader pinned to the just-retired version stays valid across one promotion
    assert names == sorted([RUN_B, RUN_C])
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "gamma"


def test_re_promoting_the_same_run_id_never_touches_the_live_version(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    src = _make_artifact(tmp_path, RUN_A, "alpha")
    _promote(root, src, RUN_A).commit()
    live = resolve_active_artifact_dir(root)
    assert live is not None
    swap = _promote(root, src, RUN_A)
    fresh = resolve_active_artifact_dir(root)
    assert fresh is not None and fresh != live  # a new immutable version dir
    assert live.is_dir()  # the previously live version is intact until pruned
    swap.commit()
    state = active_pointer_state(root)
    assert state is not None and state.run_id == RUN_A


# -- prepare callback ------------------------------------------------------------------


def test_prepare_mutates_the_staged_copy_before_it_becomes_visible(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    src = _make_artifact(tmp_path, RUN_A, "alpha")

    def _prepare(staged: Path) -> None:
        (staged / "tribrid_reranker_manifest.json").write_text(
            json.dumps({"backend": "mlx_qwen3", "run_id": RUN_A}), encoding="utf-8"
        )

    swap = _promote(root, src, RUN_A, prepare=_prepare)
    active = resolve_active_artifact_dir(root)
    assert active is not None
    manifest = json.loads((active / "tribrid_reranker_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == RUN_A
    assert not (src / "tribrid_reranker_manifest.json").exists()  # the run artifact itself is untouched
    swap.commit()


def test_prepare_failure_leaves_the_store_exactly_as_it_was(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()

    def _prepare(staged: Path) -> None:
        raise OSError("disk full while writing the manifest")

    with pytest.raises(OSError):
        VersionedArtifactSwap(_make_artifact(tmp_path, RUN_B, "beta"), root, run_id=RUN_B, prepare=_prepare).begin()
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "alpha"
    assert recover_artifact_store(root) is None  # no marker, no staging debris that recovery reports
    leftovers = [p.name for p in versions_dir(root).iterdir() if p.name != active.name]
    assert leftovers == []


# -- crash recovery --------------------------------------------------------------------


def _crash_after_pointer_switch(root: Path, src: Path, run_id: str) -> None:
    """Drive a promotion up to the pointer switch, then abandon it (no commit/rollback),
    releasing the lock the way a killed process would."""
    swap = VersionedArtifactSwap(src, root, run_id=run_id)
    swap.begin()
    swap.abandon_for_crash_simulation()


def test_recovery_rolls_back_a_promotion_that_died_before_commit(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    _crash_after_pointer_switch(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B)
    # the stranded pointer names the unrecorded candidate until recovery runs
    assert recover_artifact_store(root) == "rolled_back_unrecorded_promotion"
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "alpha"
    assert recover_artifact_store(root) is None  # idempotent


def test_recovery_rolls_back_a_first_promotion_that_died_before_commit(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _crash_after_pointer_switch(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A)
    assert recover_artifact_store(root) == "rolled_back_unrecorded_promotion"
    assert resolve_active_artifact_dir(root) is None


def test_recovery_finishes_a_commit_that_died_mid_prune(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    _promote(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B).commit()
    swap = _promote(root, _make_artifact(tmp_path, RUN_C, "gamma"), RUN_C)
    swap.crash_during_commit_for_simulation()
    assert recover_artifact_store(root) == "finished_commit"
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "gamma"
    names = sorted(p.name for p in versions_dir(root).iterdir())
    assert names == sorted([RUN_B, RUN_C])  # current + just-retired, older pruned by recovery


def test_recovery_sweeps_staging_debris_from_a_crash_mid_copy(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    debris = versions_dir(root) / f".staging_{RUN_B}_dead"
    debris.mkdir()
    (debris / "adapter.npz").write_bytes(b"partial")
    assert recover_artifact_store(root) == "swept_staging"
    assert not debris.exists()
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "alpha"


def test_recovery_fails_closed_on_an_unreadable_marker(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    marker = root / ".promote.json"
    marker.write_text("{truncated", encoding="utf-8")
    with pytest.raises(ArtifactStoreError):
        recover_artifact_store(root)
    # nothing was deleted while the marker is unreadable
    active_versions = [p.name for p in versions_dir(root).iterdir()]
    assert active_versions == [RUN_A]


def test_begin_recovers_a_stranded_previous_promotion_first(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    _crash_after_pointer_switch(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B)
    # a new promotion begins by repairing the stranded one, then proceeds
    swap = _promote(root, _make_artifact(tmp_path, RUN_C, "gamma"), RUN_C)
    swap.commit()
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "gamma"
    state = active_pointer_state(root)
    assert state is not None and state.run_id == RUN_C


def test_recovery_finishes_a_stranded_promotion_whose_work_was_recorded(tmp_path: Path) -> None:
    """The crash window between the caller's durable run-record write and the committed
    marker: recovery must NOT roll back a promotion the run record already claims."""
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    _crash_after_pointer_switch(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B)
    recorded_runs = {RUN_B}
    outcome = recover_artifact_store(root, promotion_recorded=lambda rid: rid in recorded_runs)
    assert outcome == "finished_commit_of_recorded_promotion"
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "beta"
    # and without the record, the same stranded state still rolls back (conservative default)
    _crash_after_pointer_switch(root, _make_artifact(tmp_path, RUN_C, "gamma"), RUN_C)
    outcome = recover_artifact_store(root, promotion_recorded=lambda rid: rid in recorded_runs)
    assert outcome == "rolled_back_unrecorded_promotion"
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "beta"


def test_unmigrated_flat_layout_fails_closed_instead_of_reading_or_hiding_it(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    root.mkdir()
    (root / "adapter.npz").write_bytes(b"legacy-weights")
    (root / "adapter_config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactStoreError, match="flat artifact layout"):
        resolve_active_artifact_dir(root)
    with pytest.raises(ArtifactStoreError, match="flat artifact layout"):
        VersionedArtifactSwap(_make_artifact(tmp_path, RUN_A, "alpha"), root, run_id=RUN_A).begin()
    assert (root / "adapter.npz").read_bytes() == b"legacy-weights"  # nothing was touched


def test_rollback_keeps_a_pinned_candidate_readable_until_the_next_commit(tmp_path: Path) -> None:
    root = tmp_path / "learning-reranker-active"
    _promote(root, _make_artifact(tmp_path, RUN_A, "alpha"), RUN_A).commit()
    swap = _promote(root, _make_artifact(tmp_path, RUN_B, "beta"), RUN_B)
    pinned = resolve_active_artifact_dir(root)  # a reader pinned the candidate mid-promotion
    assert pinned is not None and _read_tag(pinned) == "beta"
    swap.rollback()
    active = resolve_active_artifact_dir(root)
    assert active is not None and _read_tag(active) == "alpha"
    assert _read_tag(pinned) == "beta"  # the pinned path still reads completely
    # the next successful commit prunes the parked candidate
    _promote(root, _make_artifact(tmp_path, RUN_C, "gamma"), RUN_C).commit()
    assert not pinned.exists()


# -- reader atomicity ------------------------------------------------------------------


def test_a_reader_inside_the_retention_window_never_sees_a_missing_or_partial_artifact(tmp_path: Path) -> None:
    """The acceptance test of the slice, stated with its honest bound: resolve + read in a
    tight loop while promotions (commits AND rollbacks) run back to back. A pinned path may
    only vanish after at least two further store mutations (retention keeps the current and
    just-retired version, and a rolled-back candidate survives until the next commit); inside
    that window every read must land on a complete, unmixed artifact tree."""
    root = tmp_path / "learning-reranker-active"
    payloads = ["alpha", "beta", "gamma", "delta", "epsilon"]
    sources = {p: _make_artifact(tmp_path, f"run_{p}", p) for p in payloads}
    _promote(root, sources["alpha"], "run_alpha").commit()

    stop = threading.Event()
    failures: list[str] = []
    mutations: list[str] = []  # append-only; len() is the store-mutation epoch a reader pins

    def _reader() -> None:
        while not stop.is_set():
            epoch = len(mutations)
            try:
                active = resolve_active_artifact_dir(root)
            except ArtifactStoreError as exc:
                failures.append(f"resolve failed: {exc}")
                return
            if active is None:
                failures.append("resolve returned None while an artifact was promoted")
                return
            try:
                tag = _read_tag(active)
                weights = (active / "adapter.npz").read_bytes()
                extra = (active / "extras" / "projection_dirs.npz").read_bytes()
            except OSError as exc:
                if len(mutations) - epoch < 2:
                    failures.append(f"pinned version vanished inside the retention window: {exc}")
                    return
                continue
            if weights != tag.encode("utf-8") * 64 or extra != tag.encode("utf-8"):
                failures.append(f"read a mixed artifact for tag {tag}")
                return

    threads = [threading.Thread(target=_reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for round_number in range(3):
            for index, p in enumerate(payloads[1:]):
                swap = _promote(root, sources[p], f"run_{p}")
                mutations.append(f"begin_{p}")
                # Every third promotion fails after the switch and rolls back: readers
                # pinned to the candidate must keep their files (it is parked, not deleted).
                if (round_number + index) % 3 == 2:
                    swap.rollback()
                    mutations.append(f"rollback_{p}")
                else:
                    swap.commit()
                    mutations.append(f"commit_{p}")
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=30)
    assert failures == []
