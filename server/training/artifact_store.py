"""Versioned active-artifact store with a reader-atomic pointer switch.

Replaces the rename-window promotion swap for the trained reranker and Learning
Agent adapters. Layout under one artifact root (the directory named by
`training.tribrid_reranker_model_path` / `training.ragweld_agent_model_path`):

    versions/<version>/    immutable, fully-fsynced artifact trees
    ACTIVE.json            fsynced pointer file naming the current version
    .promote.lock          flock serializing promotions across processes
    .promote.json          durable promotion marker (crash recovery)

Readers resolve the pointer once (`resolve_active_artifact_dir`) and then read
from an immutable version directory, so a promotion never makes the active
path disappear underneath them. Retention keeps the current version and the
one it just retired: a reader pinned to a version stays valid across one
promotion; older versions are pruned on commit (run directories keep the full
history of trained artifacts).

A promotion is a `VersionedArtifactSwap`: `begin` stages the copy, writes a
durable `switching` marker and switches the pointer atomically; the caller
then does the fallible post-switch work (lineage, run record); `commit` prunes
and drops the marker, `rollback` switches the pointer back. A crash anywhere
is repaired deterministically by `recover_artifact_store`, which runs at
process startup and at the start of every promotion: an uncommitted switch is
rolled back (an unrecorded candidate is never left active), a committed one is
finished. An unreadable marker or pointer fails closed — nothing is deleted,
the error is raised.

All functions do blocking filesystem work: call them through
`asyncio.to_thread` from async code.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

POINTER_NAME = "ACTIVE.json"
VERSIONS_DIR_NAME = "versions"
_MARKER_NAME = ".promote.json"
_LOCK_NAME = ".promote.lock"
_STAGING_PREFIX = ".staging_"


class ArtifactStoreError(RuntimeError):
    """The store's pointer or marker is unreadable or inconsistent; nothing was touched."""


@dataclass(frozen=True)
class ActivePointerState:
    """What the pointer file names: the promoted run and its immutable version directory."""

    run_id: str
    version: str
    path: Path


def pointer_path(root: Path) -> Path:
    return root / POINTER_NAME


def versions_dir(root: Path) -> Path:
    return root / VERSIONS_DIR_NAME


def _marker_path(root: Path) -> Path:
    return root / _MARKER_NAME


def _fsync_dir(directory: Path) -> None:
    dir_fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _fsync_tree(top: Path) -> None:
    """Make a freshly copied tree durable before anything references it."""
    for current, _dirs, files in os.walk(top, topdown=False):
        for name in files:
            fd = os.open(Path(current) / name, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _fsync_dir(Path(current))


def _safe_name(value: object, *, field: str) -> str:
    """A version/run identifier that is exactly one directory name (fail closed otherwise)."""
    text = str(value or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text or text.startswith("."):
        raise ArtifactStoreError(f"{field} is not a safe artifact identifier: {text!r}")
    return text


def _write_json_durable(path: Path, payload: dict[str, object]) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _legacy_flat_entries(root: Path) -> list[str]:
    """Entries in the root that belong to the retired flat adapter layout, not the store."""
    if not root.is_dir():
        return []
    ours = {VERSIONS_DIR_NAME, POINTER_NAME}
    out: list[str] = []
    for entry in root.iterdir():
        name = entry.name
        if name in ours or name.startswith(".") or name.startswith(POINTER_NAME):
            continue
        out.append(name)
    return sorted(out)


def _read_pointer(root: Path) -> ActivePointerState | None:
    path = pointer_path(root)
    if not path.exists():
        legacy = _legacy_flat_entries(root)
        if legacy:
            # Replacement-only: the retired flat layout is refused loudly, never read.
            raise ArtifactStoreError(
                f"{root}: no {POINTER_NAME} pointer, but the directory holds a retired flat artifact "
                f"layout ({', '.join(legacy[:5])}); migrate it into versions/<run_id>/ with an "
                f"{POINTER_NAME} pointer before using this store"
            )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactStoreError(f"{path}: unreadable active-artifact pointer ({exc})") from exc
    if not isinstance(payload, dict):
        raise ArtifactStoreError(f"{path}: unrecognised active-artifact pointer payload")
    version = _safe_name(payload.get("version"), field=f"{path}: version")
    run_id = _safe_name(payload.get("run_id"), field=f"{path}: run_id")
    return ActivePointerState(run_id=run_id, version=version, path=versions_dir(root) / version)


def active_pointer_state(root: Path) -> ActivePointerState | None:
    """The pointer's content, verified against the version directory it names."""
    state = _read_pointer(root)
    if state is None:
        return None
    if not state.path.is_dir():
        raise ArtifactStoreError(
            f"{pointer_path(root)}: pointer names version {state.version!r} but {state.path} is missing; "
            "the store needs recovery or the operator removed files by hand"
        )
    return state


def resolve_active_artifact_dir(root: Path) -> Path | None:
    """The immutable directory of the active artifact, or None when nothing is promoted.

    Read-only. Pin it once per operation: the returned path stays valid until a later
    successful commit prunes it (retention keeps the current version and the one it just
    retired, and a rolled-back candidate survives until the next commit).
    """
    state = active_pointer_state(root)
    return None if state is None else state.path


def _read_marker(root: Path) -> dict[str, object] | None:
    path = _marker_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactStoreError(f"{path}: unreadable promotion marker ({exc})") from exc
    if not isinstance(payload, dict) or payload.get("phase") not in {"switching", "committed"}:
        raise ArtifactStoreError(f"{path}: unrecognised promotion marker payload")
    return payload


def _sweep_staging(root: Path) -> bool:
    swept = False
    directory = versions_dir(root)
    if not directory.is_dir():
        return False
    for entry in directory.iterdir():
        if entry.name.startswith(_STAGING_PREFIX):
            shutil.rmtree(entry, ignore_errors=True)
            swept = True
    return swept


def _prune_versions(root: Path, keep: set[str]) -> list[Path]:
    """Remove versions (and staging debris) not in `keep`; report what could not go."""
    leftovers: list[Path] = []
    directory = versions_dir(root)
    if not directory.is_dir():
        return leftovers
    for entry in directory.iterdir():
        if entry.name in keep:
            continue
        try:
            shutil.rmtree(entry)
        except OSError:
            leftovers.append(entry)
    return leftovers


def _restore_pointer(root: Path, *, previous_run_id: str | None, previous_version: str | None) -> None:
    if previous_version is None:
        pointer_path(root).unlink(missing_ok=True)
        _fsync_dir(root)
        return
    _write_json_durable(
        pointer_path(root),
        {"run_id": previous_run_id or previous_version, "version": previous_version},
    )


def _recover_locked(root: Path, *, promotion_recorded: Callable[[str], bool] | None = None) -> str | None:
    marker = _read_marker(root)
    if marker is None:
        return "swept_staging" if _sweep_staging(root) else None
    phase = str(marker.get("phase"))
    version = _safe_name(marker.get("version"), field=f"{_marker_path(root)}: version")
    run_id = str(marker.get("run_id") or "") or None
    previous_version_raw = marker.get("previous_version")
    previous_version = (
        _safe_name(previous_version_raw, field=f"{_marker_path(root)}: previous_version")
        if previous_version_raw
        else None
    )
    previous_run_id = str(marker.get("previous_run_id") or "") or None
    if phase == "committed":
        keep = {version} | ({previous_version} if previous_version else set())
        _prune_versions(root, keep)
        _marker_path(root).unlink(missing_ok=True)
        _fsync_dir(root)
        return "finished_commit"
    # switching: the crash happened between the pointer switch and the committed marker. The
    # caller's `promotion_recorded` predicate (the trainer's run record) decides which side of
    # the post-switch work the crash fell on: recorded work finishes the commit, unrecorded
    # work rolls the pointer back — an unrecorded candidate never stays active.
    pointer = _read_pointer(root)
    candidate = versions_dir(root) / version
    if pointer is not None and pointer.version == version:
        recorded = False
        if promotion_recorded is not None and run_id:
            try:
                recorded = bool(promotion_recorded(run_id))
            except Exception:  # noqa: BLE001 - an unreadable run record means unrecorded (conservative)
                recorded = False
        if recorded:
            keep = {version} | ({previous_version} if previous_version else set())
            _prune_versions(root, keep)
            _marker_path(root).unlink(missing_ok=True)
            _fsync_dir(root)
            return "finished_commit_of_recorded_promotion"
        if previous_version is not None and not (versions_dir(root) / previous_version).is_dir():
            # The previous version is gone (operator interference): better the complete
            # candidate than a pointer at nothing.
            _marker_path(root).unlink(missing_ok=True)
            _fsync_dir(root)
            _sweep_staging(root)
            return "kept_candidate_previous_missing"
        _restore_pointer(root, previous_run_id=previous_run_id, previous_version=previous_version)
        # The candidate stays as an unreferenced version (pruned by the next commit): an
        # in-process reader that pinned it while it was active keeps its files readable.
        _marker_path(root).unlink(missing_ok=True)
        _fsync_dir(root)
        _sweep_staging(root)
        return "rolled_back_unrecorded_promotion"
    # the crash happened before the pointer switch: the pointer is already the truth; the
    # candidate stays unreferenced until the next commit prunes it
    _marker_path(root).unlink(missing_ok=True)
    _fsync_dir(root)
    _sweep_staging(root)
    return "dropped_marker"


def recover_artifact_store(root: Path, *, promotion_recorded: Callable[[str], bool] | None = None) -> str | None:
    """Repair a promotion that crashed mid-flight; returns what was done (None when nothing).

    Runs under the store's promotion lock. `promotion_recorded(run_id)` is the caller's truth
    for whether the crashed promotion's post-switch work (run record, lineage) committed: True
    finishes the commit, False/None/raising rolls the pointer back. Raises
    `ArtifactStoreError` on an unreadable marker or pointer instead of guessing.
    """
    if not root.is_dir():
        return None
    lock_path = root / _LOCK_NAME
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return _recover_locked(root, promotion_recorded=promotion_recorded)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _allocate_version(root: Path, run_id: str) -> str:
    """A fresh version directory name for `run_id` (a re-promotion gets a suffixed one:
    an existing version directory — the live one included — is never touched)."""
    base = _safe_name(run_id, field="run_id")
    candidate = base
    n = 1
    while (versions_dir(root) / candidate).exists():
        n += 1
        candidate = f"{base}__r{n}"
    return candidate


class VersionedArtifactSwap:
    """A promotion of `artifact_dir` into the store at `root`, as three phases.

    `begin` (under the store's flock, after recovery): stage a fully-fsynced copy as a new
    immutable version — `prepare(staged_dir)`, when given, mutates the staged copy before it
    becomes visible — write the durable `switching` marker, and switch the pointer atomically.
    Readers see the previous or the new version at every instant, never a missing path. The
    caller then does the fallible post-switch work (lineage, run record). `commit` prunes all
    versions but the new one and the one it retired, then drops the marker; `rollback` switches
    the pointer back to the previous version (or removes it for a first promotion) and leaves
    the candidate as an unreferenced version for the next commit to prune, so a reader that
    pinned it keeps its files. The flock is held from `begin` to `commit`/`rollback`, so
    overlapping promotions serialize instead of undoing each other.

    All methods do blocking filesystem work: call them through `asyncio.to_thread`.
    """

    def __init__(
        self,
        artifact_dir: Path,
        root: Path,
        *,
        run_id: str,
        prepare: Callable[[Path], None] | None = None,
        promotion_recorded: Callable[[str], bool] | None = None,
    ) -> None:
        self.artifact_dir = artifact_dir
        self.root = root
        self.run_id = _safe_name(run_id, field="run_id")
        self.prepare = prepare
        self.promotion_recorded = promotion_recorded
        self.version: str | None = None
        self.previous: ActivePointerState | None = None
        self._lock_handle = None
        self._open = False

    # -- locking -------------------------------------------------------------------------
    def _acquire(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        handle = (self.root / _LOCK_NAME).open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        self._lock_handle = handle

    def _release(self) -> None:
        handle, self._lock_handle = self._lock_handle, None
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    # -- phases --------------------------------------------------------------------------
    def begin(self) -> VersionedArtifactSwap:
        self._acquire()
        staged: Path | None = None
        renamed: Path | None = None
        marker_written = False
        pointer_attempted = False
        try:
            _recover_locked(self.root, promotion_recorded=self.promotion_recorded)
            directory = versions_dir(self.root)
            directory.mkdir(parents=True, exist_ok=True)
            self.previous = active_pointer_state(self.root)
            version = _allocate_version(self.root, self.run_id)
            staged = directory / f"{_STAGING_PREFIX}{version}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
            shutil.copytree(self.artifact_dir, staged)
            if self.prepare is not None:
                self.prepare(staged)
            _fsync_tree(staged)
            renamed = directory / version
            staged.rename(renamed)
            _fsync_dir(directory)
            staged = None
            _write_json_durable(
                _marker_path(self.root),
                {
                    "phase": "switching",
                    "version": version,
                    "run_id": self.run_id,
                    "previous_version": self.previous.version if self.previous is not None else None,
                    "previous_run_id": self.previous.run_id if self.previous is not None else None,
                },
            )
            marker_written = True
            pointer_attempted = True
            _write_json_durable(pointer_path(self.root), {"run_id": self.run_id, "version": version})
            self.version = version
            self._open = True
        except BaseException:
            # Put things back exactly. A pointer write that was attempted may have landed even
            # though it raised (e.g. the rename applied and only the directory fsync failed), so
            # the previous pointer is restored before the candidate goes away — the pointer must
            # never name a removed directory. Staging debris and the marker (only ever written
            # here before the pointer switch completed) go away too.
            pointer_restore_failed = False
            try:
                if pointer_attempted:
                    try:
                        _restore_pointer(
                            self.root,
                            previous_run_id=self.previous.run_id if self.previous is not None else None,
                            previous_version=self.previous.version if self.previous is not None else None,
                        )
                    except OSError:
                        # Pointer state unknown: keep the candidate (never a dangling pointer)
                        # and keep the marker so the next recovery repairs the store.
                        renamed = None
                        pointer_restore_failed = True
                if staged is not None:
                    shutil.rmtree(staged, ignore_errors=True)
                if renamed is not None:
                    shutil.rmtree(renamed, ignore_errors=True)
                if marker_written and not pointer_restore_failed:
                    _marker_path(self.root).unlink(missing_ok=True)
                    _fsync_dir(self.root)
            finally:
                self._open = False
                self._release()
            raise
        return self

    def commit(self) -> Path | None:
        """Prune retired versions and drop the marker. Returns a path only when something
        could not be removed (reported, not hidden).

        The caller's post-switch work (run record, lineage) has already committed durably by
        the time this runs, so the promotion must stand: if writing the `committed` marker
        fails, the `switching` marker is removed instead (the switch becomes permanent and the
        prune is skipped) rather than left for recovery to roll a recorded promotion back.
        """
        if not self._open or self.version is None:
            return None
        leftover: Path | None = None
        try:
            previous_version = self.previous.version if self.previous is not None else None
            try:
                _write_json_durable(
                    _marker_path(self.root),
                    {
                        "phase": "committed",
                        "version": self.version,
                        "run_id": self.run_id,
                        "previous_version": previous_version,
                        "previous_run_id": self.previous.run_id if self.previous is not None else None,
                    },
                )
            except OSError as marker_failure:
                _marker_path(self.root).unlink(missing_ok=True)  # raising here is the truly stuck case
                _fsync_dir(self.root)
                raise ArtifactStoreError(
                    f"promotion committed (the pointer stands) but the retired versions were not pruned: "
                    f"the committed marker could not be written ({marker_failure})"
                ) from marker_failure
            keep = {self.version} | ({previous_version} if previous_version else set())
            leftovers = _prune_versions(self.root, keep)
            leftover = leftovers[0] if leftovers else None
            _marker_path(self.root).unlink(missing_ok=True)
            _fsync_dir(self.root)
        finally:
            self._open = False
            self._release()
        return leftover

    def rollback(self) -> None:
        """Switch the pointer back to the previous version (or remove it when this was the
        first promotion) and discard the candidate. Readers never see a missing path: the
        pointer always names a complete version directory."""
        if not self._open or self.version is None:
            return
        errors: list[str] = []
        try:
            if self.previous is not None and not self.previous.path.is_dir():
                # The previous version vanished mid-transaction (operator interference): better
                # the candidate than a pointer at nothing. The marker goes away so recovery does
                # not later "restore" the missing previous either. Reported, never hidden.
                errors.append(
                    f"previous version missing at {self.previous.path}; the candidate was left active at "
                    f"{versions_dir(self.root) / self.version}"
                )
                try:
                    _marker_path(self.root).unlink(missing_ok=True)
                    _fsync_dir(self.root)
                except OSError as exc:
                    errors.append(f"could not drop the promotion marker: {exc}")
                raise ArtifactStoreError("; ".join(errors))
            try:
                _restore_pointer(
                    self.root,
                    previous_run_id=self.previous.run_id if self.previous is not None else None,
                    previous_version=self.previous.version if self.previous is not None else None,
                )
            except OSError as exc:
                errors.append(f"could not restore the previous pointer at {pointer_path(self.root)}: {exc}")
            else:
                # The candidate stays as an unreferenced version until the next commit prunes
                # it: a reader that pinned it while it was active keeps its files readable.
                try:
                    _marker_path(self.root).unlink(missing_ok=True)
                    _fsync_dir(self.root)
                except OSError as exc:
                    errors.append(f"could not drop the promotion marker: {exc}")
        finally:
            self._open = False
            self._release()
        if errors:
            raise ArtifactStoreError("; ".join(errors))

    # -- crash simulation (tests only) ---------------------------------------------------
    def abandon_for_crash_simulation(self) -> None:
        """Release the lock without commit/rollback, the way a killed process would."""
        self._open = False
        self._release()

    def crash_during_commit_for_simulation(self) -> None:
        """Write the committed marker, then die before the prune and marker removal."""
        if not self._open or self.version is None:
            raise ArtifactStoreError("no open promotion to crash")
        previous_version = self.previous.version if self.previous is not None else None
        _write_json_durable(
            _marker_path(self.root),
            {
                "phase": "committed",
                "version": self.version,
                "run_id": self.run_id,
                "previous_version": previous_version,
                "previous_run_id": self.previous.run_id if self.previous is not None else None,
            },
        )
        self.abandon_for_crash_simulation()
