"""Validated rows of the reranker triplets artifact (`training.tribrid_triplets_path`).

The JSONL file is a persisted boundary between mining and training, so every
row is a Pydantic model: paths are corpus-relative (no absolute paths, no
traversal), positive and negative differ, and a corrupt line fails loading
instead of being skipped, so the row count the UI reports is the row count the
trainer will use.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from server.evaluation.query_guard import placeholder_reason


class TripletRowsCorruptError(ValueError):
    """A line in the triplets file is not a valid triplet row."""


_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def canonical_corpus_path(value: str, *, field: str) -> str:
    """Canonical POSIX corpus-relative path: backslashes folded, `.` segments dropped, no traversal/absolute/drive."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} must not be empty")
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_RE.match(normalized) or PurePosixPath(normalized).is_absolute():
        raise ValueError(f"{field} must be corpus-relative, got an absolute or drive-qualified path")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"{field} must not contain path traversal segments")
    if not parts:
        raise ValueError(f"{field} must name a document")
    return "/".join(parts)


class TripletRow(BaseModel):
    """One (query, positive document, negative document) training row."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="Real domain question the pair was mined for.")
    positive: str = Field(description="Corpus-relative path of a document labelled relevant to the query.")
    negative: str = Field(description="Corpus-relative path of a retrieved document that is not labelled relevant.")
    source: str | None = Field(
        default=None,
        description="Provenance: `feedback`, `eval_run:<run_id>` or `synthetic_run:<run_id>`.",
    )

    @field_validator("query")
    @classmethod
    def _real_query(cls, value: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        reason = placeholder_reason(text)
        if reason is not None:
            raise ValueError(f"query is not a real domain question ({reason})")
        return text

    @field_validator("positive")
    @classmethod
    def _positive_path(cls, value: str) -> str:
        return canonical_corpus_path(value, field="positive")

    @field_validator("negative")
    @classmethod
    def _negative_path(cls, value: str) -> str:
        return canonical_corpus_path(value, field="negative")

    @model_validator(mode="after")
    def _distinct_documents(self) -> TripletRow:
        if self.positive == self.negative:
            raise ValueError("positive and negative must be different documents")
        return self

    def key(self) -> tuple[str, str, str]:
        return (self.query, self.positive, self.negative)


def load_triplet_rows(path: Path) -> list[TripletRow]:
    """Load every row; raise ``TripletRowsCorruptError`` on the first malformed line."""
    if not path.exists():
        return []
    rows: list[TripletRow] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                    rows.append(TripletRow.model_validate(payload))
                except Exception as exc:
                    raise TripletRowsCorruptError(f"{path}:{number}: {exc}") from exc
    except UnicodeDecodeError as exc:
        # Byte-level corruption surfaces while iterating, outside the per-line handler.
        raise TripletRowsCorruptError(f"{path}: not valid UTF-8 ({exc})") from exc
    return rows


@contextmanager
def triplets_lock(path: Path) -> Iterator[None]:
    """Exclusive interprocess lock for a read-modify-write of ``path``.

    Mining is load -> dedupe -> rewrite; without a cross-process lock two API
    workers mining at once would each rewrite the union they read and the last
    ``os.replace`` would drop the other's rows. The lock is ``flock`` on a sibling
    ``.<name>.lock`` file, so it also serializes against a second process on the
    same host. Do not nest: ``flock`` on a fresh descriptor blocks against the same
    process' own lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_triplet_rows(path: Path, rows: list[TripletRow], *, mode: int | None = None) -> None:
    """Atomically persist ``rows`` as the complete artifact.

    The rows go to a same-directory temp file (created with the process' normal
    umask, then given the existing artifact's mode before its fsync), which is flushed, fsynced and
    swapped in with ``os.replace``; the parent directory is fsynced afterwards so
    the rename itself survives a crash. A reader therefore sees either the previous
    complete file or the new one, never a truncated or half-appended artifact.
    Callers that merge with the current contents hold ``triplets_lock``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = mode if mode is not None else (path.stat().st_mode & 0o7777 if path.exists() else None)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row.model_dump(exclude_none=True), ensure_ascii=False) + "\n")
            handle.flush()
            if existing_mode is not None:
                os.fchmod(handle.fileno(), existing_mode)  # before the fsync so the mode is durable with the data
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


# ---------------------------------------------------------------------------------------------
# Parked replacement with a durable marker (used by synthetic publish).
#
# Phases recorded in `.<name>.publish.json` (each transition fsyncs the marker and the directory):
#   prepared   marker written, predecessor still at `target`        -> recovery: drop the marker only
#   parked     predecessor renamed to `parked`, no live file yet      -> recovery: rename it back
#   written    candidate at `target`, predecessor at `parked`         -> recovery: candidate out, predecessor back
#   committed  lineage durable; `parked` may still exist              -> recovery: drop `parked` + marker
# A marker that cannot be read fails closed: nothing is deleted, the error is raised. A target is
# only ever removed when the marker proves it is an uncommitted candidate AND the named predecessor
# (if any) is present to take its place.


class PublishMarkerError(RuntimeError):
    """The publish marker is unreadable; nothing was touched."""


def _marker_path(target: Path) -> Path:
    return target.with_name(f".{target.name}.publish.json")


def _fsync_dir(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_marker(target: Path, payload: dict[str, object]) -> None:
    marker_file = _marker_path(target)
    tmp = marker_file.with_name(marker_file.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, marker_file)
    _fsync_dir(target.parent)


def _read_marker(target: Path) -> dict[str, object] | None:
    marker_file = _marker_path(target)
    if not marker_file.exists():
        return None
    try:
        payload = json.loads(marker_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishMarkerError(f"{marker_file}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("phase") not in {"prepared", "parked", "written", "committed"}:
        raise PublishMarkerError(f"{marker_file}: unrecognised marker payload")
    return payload


def begin_parked_replacement(target: Path) -> tuple[Path | None, int | None]:
    """Park the current file (by rename) behind a durable marker. Returns (parked, mode)."""
    recover_parked_replacement(target)
    parked: Path | None = None
    mode: int | None = None
    if target.exists():
        mode = target.stat().st_mode & 0o7777
        parked = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.prev")
    parked_name = parked.name if parked is not None else None
    _write_marker(target, {"phase": "prepared", "parked": parked_name, "mode": mode})
    if parked is not None:
        target.rename(parked)
        _fsync_dir(target.parent)
    _write_marker(target, {"phase": "parked", "parked": parked_name, "mode": mode})
    return parked, mode


def mark_candidate_written(target: Path, parked: Path | None, mode: int | None) -> None:
    _write_marker(target, {"phase": "written", "parked": parked.name if parked is not None else None, "mode": mode})


def commit_parked_replacement(target: Path, parked: Path | None) -> None:
    """Record the commit durably, then drop the predecessor and the marker (recovery finishes
    either step if this process dies in between)."""
    _write_marker(target, {"phase": "committed", "parked": parked.name if parked is not None else None, "mode": None})
    if parked is not None:
        parked.unlink(missing_ok=True)
    _marker_path(target).unlink(missing_ok=True)
    _fsync_dir(target.parent)


def abort_parked_replacement(target: Path, parked: Path | None) -> None:
    """Put the predecessor back exactly (or remove the candidate when there was none)."""
    target.unlink(missing_ok=True)
    if parked is not None and parked.exists():
        os.replace(parked, target)
    _fsync_dir(target.parent)
    _marker_path(target).unlink(missing_ok=True)
    _fsync_dir(target.parent)


def recover_parked_replacement(target: Path) -> str | None:
    """Repair a publish that crashed mid-transaction; returns what was done (None when nothing).

    Raises `PublishMarkerError` on an unreadable marker instead of guessing.
    """
    marker = _read_marker(target)
    if marker is None:
        return None
    phase = str(marker.get("phase"))
    parked_name = marker.get("parked")
    parked = target.with_name(str(parked_name)) if parked_name else None
    marker_file = _marker_path(target)
    if phase == "committed":
        if parked is not None:
            parked.unlink(missing_ok=True)
        marker_file.unlink(missing_ok=True)
        _fsync_dir(target.parent)
        return "removed_parked_after_commit"
    if phase == "prepared":
        # the rename never happened (or an abort already put the predecessor back): target is the truth
        marker_file.unlink(missing_ok=True)
        _fsync_dir(target.parent)
        return "dropped_marker_target_untouched"
    # parked / written: the predecessor (if one was named) is the truth
    if parked is not None:
        if parked.exists():
            target.unlink(missing_ok=True)
            os.replace(parked, target)
            _fsync_dir(target.parent)
            marker_file.unlink(missing_ok=True)
            _fsync_dir(target.parent)
            return "restored_predecessor"
        if target.exists():
            # the predecessor was named but is gone while a target exists: an abort already
            # restored it (its marker removal raced a crash). Keep the target.
            marker_file.unlink(missing_ok=True)
            _fsync_dir(target.parent)
            return "dropped_marker_target_untouched"
        marker_file.unlink(missing_ok=True)
        _fsync_dir(target.parent)
        return "nothing_to_restore"
    # no predecessor existed: only an uncommitted candidate could be at target
    if phase == "written":
        target.unlink(missing_ok=True)
        marker_file.unlink(missing_ok=True)
        _fsync_dir(target.parent)
        return "removed_uncommitted_candidate"
    marker_file.unlink(missing_ok=True)
    _fsync_dir(target.parent)
    return "dropped_marker_target_untouched"
