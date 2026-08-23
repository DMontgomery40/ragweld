"""The triplets JSONL is a validated persisted boundary: corruption fails loudly, rows round-trip."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.training.triplet_rows import (
    TripletRow,
    TripletRowsCorruptError,
    load_triplet_rows,
    write_triplet_rows,
)

QUESTION = "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?"


def test_rows_round_trip_with_source_and_count(tmp_path: Path) -> None:
    path = tmp_path / "triplets.jsonl"
    rows = [
        TripletRow(query=QUESTION, positive="pos.txt", negative="neg1.txt", source="eval_run:r1"),
        TripletRow(query=QUESTION, positive="pos.txt", negative="neg2.txt", source="feedback"),
    ]
    write_triplet_rows(path, rows)
    write_triplet_rows(path, [*rows, TripletRow(query=QUESTION, positive="pos.txt", negative="neg3.txt")])
    loaded = load_triplet_rows(path)
    assert [r.negative for r in loaded] == ["neg1.txt", "neg2.txt", "neg3.txt"]
    assert loaded[2].source is None


def test_blank_fields_and_absolute_or_traversal_paths_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TripletRow(query="", positive="a.txt", negative="b.txt")
    with pytest.raises(ValidationError):
        TripletRow(query=QUESTION, positive="/etc/passwd", negative="b.txt")
    with pytest.raises(ValidationError):
        TripletRow(query=QUESTION, positive="a.txt", negative="../b.txt")
    with pytest.raises(ValidationError):
        TripletRow(query=QUESTION, positive="a.txt", negative="a.txt")


def test_corrupt_lines_fail_loading_instead_of_being_skipped(tmp_path: Path) -> None:
    path = tmp_path / "triplets.jsonl"
    path.write_text(
        json.dumps({"query": QUESTION, "positive": "a.txt", "negative": "b.txt"}) + "\n" + '{"query": "broken\n',
        encoding="utf-8",
    )
    with pytest.raises(TripletRowsCorruptError):
        load_triplet_rows(path)


def test_byte_corrupt_file_is_reported_as_corrupt_not_as_a_decode_crash(tmp_path: Path) -> None:
    # Codex pass 6: UTF-8 failures surfaced while iterating, outside the per-line handler,
    # so mining answered 500 and publish 400 instead of the 409 corruption boundary.
    path = tmp_path / "triplets.jsonl"
    path.write_bytes(b'{"query": "Which buoy drifted?", "positive": "a.txt", "negative": "b.txt"}\n\xff\xfe broken\n')
    with pytest.raises(TripletRowsCorruptError, match="UTF-8"):
        load_triplet_rows(path)


def test_missing_file_loads_as_empty(tmp_path: Path) -> None:
    assert load_triplet_rows(tmp_path / "absent.jsonl") == []


def test_rows_canonicalize_paths_and_reject_the_same_document_in_both_roles() -> None:
    row = TripletRow(query=QUESTION, positive="./emails\\a.txt", negative="emails/b.txt")
    assert row.positive == "emails/a.txt"
    with pytest.raises(ValidationError):
        TripletRow(query=QUESTION, positive="a.txt", negative="./a.txt")
    with pytest.raises(ValidationError):
        TripletRow(query=QUESTION, positive="C:\\docs\\a.txt", negative="b.txt")


def test_rows_reject_placeholder_queries() -> None:
    with pytest.raises(ValidationError):
        TripletRow(query="test", positive="a.txt", negative="b.txt")


def test_writes_are_atomic_and_leave_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "triplets.jsonl"
    first = TripletRow(query=QUESTION, positive="pos.txt", negative="neg1.txt")
    write_triplet_rows(path, [first])
    write_triplet_rows(path, [first, TripletRow(query=QUESTION, positive="pos.txt", negative="neg2.txt")])
    assert [r.negative for r in load_triplet_rows(path)] == ["neg1.txt", "neg2.txt"]
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_rewrite_preserves_the_existing_artifact_mode(tmp_path: Path) -> None:
    # Codex pass 5: mkstemp created a 0600 inode, so every rewrite silently tightened a
    # shared 0644 artifact. New files take the process umask; rewrites keep the mode.
    path = tmp_path / "triplets.jsonl"
    row = TripletRow(query=QUESTION, positive="pos.txt", negative="neg1.txt")
    write_triplet_rows(path, [row])
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(path.stat().st_mode) == (0o666 & ~umask)
    os.chmod(path, 0o640)
    write_triplet_rows(path, [row, TripletRow(query=QUESTION, positive="pos.txt", negative="neg2.txt")])
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_failed_write_keeps_the_previous_artifact_and_cleans_the_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "triplets.jsonl"
    good = TripletRow(query=QUESTION, positive="pos.txt", negative="neg1.txt")
    write_triplet_rows(path, [good])

    class Exploding(TripletRow):
        def model_dump(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        write_triplet_rows(path, [good, Exploding(query=QUESTION, positive="pos.txt", negative="neg2.txt")])
    assert [r.negative for r in load_triplet_rows(path)] == ["neg1.txt"]
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_triplets_lock_serializes_read_modify_write_across_processes(tmp_path: Path) -> None:
    # Two processes each append their own rows under the lock; nothing is lost.
    path = tmp_path / "triplets.jsonl"
    write_triplet_rows(path, [TripletRow(query=QUESTION, positive="pos.txt", negative="seed.txt")])
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from server.training.triplet_rows import TripletRow, load_triplet_rows, triplets_lock, write_triplet_rows
        path = Path({str(path)!r})
        tag = sys.argv[1]
        with triplets_lock(path):
            existing = load_triplet_rows(path)
            time.sleep(0.3)  # widen the race window: without the lock the other process reads the stale file
            write_triplet_rows(path, [*existing, TripletRow(query={QUESTION!r}, positive="pos.txt", negative=f"{{tag}}.txt")])
        """
    )
    procs = [subprocess.Popen([sys.executable, "-c", script, tag]) for tag in ("alpha", "beta", "gamma")]
    for proc in procs:
        assert proc.wait(timeout=60) == 0
    assert sorted(r.negative for r in load_triplet_rows(path)) == ["alpha.txt", "beta.txt", "gamma.txt", "seed.txt"]


def test_write_accepts_an_explicit_mode_for_a_parked_predecessor(tmp_path: Path) -> None:
    # Codex pass 17: publishing parks the previous file by rename, so the writer no longer sees it;
    # the caller passes the predecessor's mode and the replacement keeps it.
    path = tmp_path / "triplets.jsonl"
    row = TripletRow(query=QUESTION, positive="pos.txt", negative="neg1.txt")
    write_triplet_rows(path, [row])
    os.chmod(path, 0o600)
    parked = path.with_name(".triplets.jsonl.prev")
    path.rename(parked)
    write_triplet_rows(path, [row], mode=0o600)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_parked_replacement_recovers_every_phase_and_never_deletes_unproven_data(tmp_path: Path) -> None:
    # Codex pass 18/19: every crash window of the publish transaction is recoverable, and recovery
    # never removes a target whose predecessor identity is unproven; an unreadable marker fails closed.
    import json

    import pytest

    from server.training.triplet_rows import (
        PublishMarkerError,
        _marker_path,
        abort_parked_replacement,
        begin_parked_replacement,
        commit_parked_replacement,
        mark_candidate_written,
        recover_parked_replacement,
    )

    path = tmp_path / "triplets.jsonl"
    old = TripletRow(query=QUESTION, positive="pos.txt", negative="old.txt")
    new = TripletRow(query=QUESTION, positive="pos.txt", negative="new.txt")
    write_triplet_rows(path, [old])

    def rows() -> list[str]:
        return [r.negative for r in load_triplet_rows(path)]

    # phase "prepared": marker written, rename never happened -> the target is untouched
    _marker_path(path).write_text(json.dumps({"phase": "prepared", "parked": ".x.prev", "mode": None}), encoding="utf-8")
    assert recover_parked_replacement(path) == "dropped_marker_target_untouched"
    assert rows() == ["old.txt"]

    # phase "parked": crash right after parking -> predecessor comes back
    parked, mode = begin_parked_replacement(path)
    assert parked is not None and not path.exists()
    assert recover_parked_replacement(path) == "restored_predecessor"
    assert rows() == ["old.txt"] and not parked.exists()

    # phase "written": candidate live, lineage not committed -> predecessor comes back
    parked, mode = begin_parked_replacement(path)
    write_triplet_rows(path, [new], mode=mode)
    mark_candidate_written(path, parked, mode)
    assert recover_parked_replacement(path) == "restored_predecessor"
    assert rows() == ["old.txt"]

    # abort restored the predecessor but died before removing the marker -> target kept
    parked, mode = begin_parked_replacement(path)
    write_triplet_rows(path, [new], mode=mode)
    mark_candidate_written(path, parked, mode)
    path.unlink()
    parked.rename(path)  # what abort does, minus the marker removal
    assert recover_parked_replacement(path) == "dropped_marker_target_untouched"
    assert rows() == ["old.txt"]

    # committed but the parked predecessor was not removed -> recovery drops it
    parked, mode = begin_parked_replacement(path)
    write_triplet_rows(path, [new], mode=mode)
    mark_candidate_written(path, parked, mode)
    _marker_path(path).write_text(json.dumps({"phase": "committed", "parked": parked.name, "mode": None}), encoding="utf-8")
    assert recover_parked_replacement(path) == "removed_parked_after_commit"
    assert rows() == ["new.txt"] and not parked.exists()

    # an unreadable marker fails closed: nothing is deleted
    _marker_path(path).write_text("{not json", encoding="utf-8")
    with pytest.raises(PublishMarkerError):
        recover_parked_replacement(path)
    assert rows() == ["new.txt"]
    _marker_path(path).unlink()

    # explicit abort puts the predecessor back and leaves nothing behind
    parked, mode = begin_parked_replacement(path)
    write_triplet_rows(path, [old], mode=mode)
    abort_parked_replacement(path, parked)
    assert rows() == ["new.txt"]
    assert not [p for p in tmp_path.iterdir() if p.name.endswith((".prev", ".publish.json"))]

    # a full commit leaves exactly the new file
    parked, mode = begin_parked_replacement(path)
    write_triplet_rows(path, [old], mode=mode)
    mark_candidate_written(path, parked, mode)
    commit_parked_replacement(path, parked)
    assert rows() == ["old.txt"]
    assert not [p for p in tmp_path.iterdir() if p.name.endswith((".prev", ".publish.json"))]

    # first publish ever (no predecessor) that crashed after writing: the candidate is removed
    fresh = tmp_path / "fresh.jsonl"
    parked, mode = begin_parked_replacement(fresh)
    assert parked is None and mode is None
    write_triplet_rows(fresh, [new])
    mark_candidate_written(fresh, None, None)
    assert recover_parked_replacement(fresh) == "removed_uncommitted_candidate"
    assert not fresh.exists()
