"""Auto-promotion decision shared by the reranker and Learning Agent trainers.

Pure and artifact-free so the gate can be tested without loading a model. The
trainers measure; this module decides whether the fresh artifact may replace the
active one without an operator.
"""

from __future__ import annotations

import asyncio
import fcntl
import math
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from server.lineage.registry import repo_lineage_lock, restore_aliases, snapshot_aliases

BaselineState = Literal["absent", "incompatible", "measured", "failed"]
"""Why the active artifact's held-out score is or is not available.

`absent`: no active artifact (or no manifest) -> nothing to beat, the first artifact is promoted.
`incompatible`: an active artifact exists but cannot serve under the resolved backend/base
model -> replacing it is the point of the run.
`measured`: the active artifact was scored on the same held-out split.
`failed`: an active artifact exists and its evaluation raised or returned a non-finite value
-> its quality is unknown (not absent), so an improvement-gated run must not overwrite it.
"""

Goal = Literal["maximize", "minimize"]

_BASELINE_NA_TEXT: dict[str, str] = {
    "absent": "n/a (no active artifact)",
    "incompatible": "n/a (active artifact incompatible with the resolved backend)",
    "failed": "n/a (baseline evaluation failed)",
}


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    message: str
    notice: str | None = None


def decide_auto_promotion(
    *,
    primary_value: float | None,
    baseline_primary: float | None,
    baseline_state: BaselineState,
    dev_examples: int,
    promote_if_improves: bool,
    epsilon: float,
    backend: str,
    artifact_dir: str,
    goal: Goal = "maximize",
    metric_label: str = "primary",
) -> PromotionDecision:
    """Decide whether a trained artifact is promoted automatically.

    Without a held-out split the final metric is not a measurement, so the run
    completes unpromoted (the operator promotes explicitly). With a split and
    `promote_if_improves`: a missing final measurement refuses; a `measured`
    baseline must be beaten by `epsilon` in the direction of `goal`; a `failed`
    baseline refuses (unknown quality is not absence); only `absent` and
    `incompatible` baselines let the new artifact through unmeasured. With the
    gate disabled the artifact is promoted whenever a held-out split exists, except
    when the final measurement is NaN/inf (a broken artifact is never promoted
    automatically; a *missing* measurement with the gate off still is).
    """
    if baseline_state == "measured" and (baseline_primary is None or not math.isfinite(float(baseline_primary))):
        # A NaN/inf baseline is an evaluation that produced no number: unknown quality, not a measurement.
        baseline_state = "failed"
        baseline_primary = None
    final_is_finite = primary_value is not None and math.isfinite(float(primary_value))
    primary_text = f"{float(primary_value):.6f}" if final_is_finite else ("n/a" if primary_value is None else str(primary_value))
    baseline_text = (
        f"{float(baseline_primary):.6f}" if baseline_state == "measured" else _BASELINE_NA_TEXT[baseline_state]
    )
    tail = f"eps={float(epsilon):.6f} (backend={backend}). Run artifact preserved at {artifact_dir}."
    if dev_examples <= 0:
        return PromotionDecision(
            promote=False,
            notice="Not promoting automatically: no held-out dev split (fewer than two distinct examples).",
            message=f"Did not promote: {metric_label}={primary_text} baseline=n/a (no held-out dev split) {tail}",
        )
    promote = True
    notice: str | None = None
    if primary_value is not None and not final_is_finite:
        # The evaluation ran and produced NaN/inf: the artifact or its scorer is broken. Unlike a
        # missing measurement this refuses even when the improvement gate is off.
        return PromotionDecision(
            promote=False,
            notice=(
                f"Not promoting: the final held-out {metric_label} is {primary_value}, which is not a number; "
                "the artifact or its evaluation is broken. Inspect the run before promoting."
            ),
            message=f"Did not promote: {metric_label}={primary_text} baseline={baseline_text} {tail}",
        )
    if promote_if_improves:
        if primary_value is None:
            promote = False
            notice = (
                "Not promoting automatically: the final held-out evaluation produced no measurement, "
                "so the improvement gate cannot be applied. Inspect the run and promote explicitly."
            )
        elif baseline_state == "measured":
            base = float(baseline_primary)  # type: ignore[arg-type]
            promote = (
                bool(float(primary_value) > base + float(epsilon))
                if goal == "maximize"
                else bool(float(primary_value) < base - float(epsilon))
            )
        elif baseline_state == "failed":
            promote = False
            notice = (
                "Not promoting automatically: the active artifact exists but its baseline evaluation failed, "
                "so the improvement gate cannot be applied. Inspect the run and promote explicitly."
            )
    return PromotionDecision(
        promote=promote,
        notice=notice,
        message=f"Did not promote: {metric_label}={primary_text} baseline={baseline_text} {tail}",
    )


class PromotionRollbackError(RuntimeError):
    """Rolling a promotion back failed; the original failure is chained as __cause__/__context__."""


class PromotionSwap:
    """A two-phase, interprocess-locked swap of the active artifact directory.

    `begin` takes an exclusive `flock` on a sibling lock file of the active directory (held
    until commit/rollback, so overlapping promotions — other jobs, other workers, manual
    promotes — serialize instead of undoing each other), copies the run artifact next to the
    active directory and swaps it in while keeping the previous active tree as a retained
    rollback directory. The caller then does the fallible post-swap work (cache clear,
    lineage, run record). `commit` discards the retained tree; `rollback` puts the previous
    active tree back (or removes the new one when there was none). Every step is
    exception-safe: a failure inside `begin` leaves the active directory as it was, and
    cleanup errors are raised (never ignored) so nothing is silently stranded.

    All methods do blocking filesystem work: call them through `asyncio.to_thread` from
    async code (the flock is bound to the descriptor, not the thread).
    """

    def __init__(self, artifact_dir: Path, active_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.active_dir = active_dir
        self.previous: Path | None = None
        self._lock_handle = None
        self._open = False

    # -- locking -------------------------------------------------------------------------
    def _acquire(self) -> None:
        self.active_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.active_dir.parent / f".{self.active_dir.name}.promote.lock"
        handle = lock_path.open("a+", encoding="utf-8")
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
    def begin(self) -> PromotionSwap:
        self._acquire()
        stamp = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        staged = self.active_dir.parent / f".tmp_{self.active_dir.name}_{stamp}"
        retained = self.active_dir.parent / f".bak_{self.active_dir.name}_{stamp}"
        try:
            shutil.copytree(self.artifact_dir, staged)
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)  # the staging copy is ours alone
            self._release()
            raise
        self._open = True
        try:
            if self.active_dir.exists():
                self.active_dir.rename(retained)
                self.previous = retained
            staged.rename(self.active_dir)
        except BaseException as failure:
            # Put things back exactly: the staged copy goes away, the previous tree returns. The
            # lock and state are always released; a failed restore is reported, never swallowed.
            try:
                shutil.rmtree(staged, ignore_errors=True)
                if self.previous is not None and self.previous.exists() and not self.active_dir.exists():
                    try:
                        self.previous.rename(self.active_dir)
                    except OSError as restore_failure:
                        raise PromotionRollbackError(
                            f"begin failed and the previous artifact could not be restored from {self.previous}: {restore_failure}"
                        ) from failure
            finally:
                self.previous = None
                self._open = False
                self._release()
            raise
        return self

    def commit(self) -> Path | None:
        """Discard the retained tree. Returns a path only when it could not be removed (reported, not hidden)."""
        if not self._open:
            return None
        leftover: Path | None = None
        try:
            if self.previous is not None and self.previous.exists():
                try:
                    shutil.rmtree(self.previous)
                except OSError:
                    leftover = self.previous
        finally:
            self.previous = None
            self._open = False
            self._release()
        return leftover

    def rollback(self) -> None:
        """Put the previous artifact back. The candidate is parked (renamed aside), the previous
        tree restored, and only then is the candidate deleted — a failed restore therefore never
        leaves the active path empty: the candidate returns and both trees are reported."""
        if not self._open:
            return
        errors: list[str] = []
        try:
            if self.previous is None:
                # first promotion ever: nothing to restore, the candidate simply goes away
                if self.active_dir.exists():
                    try:
                        shutil.rmtree(self.active_dir)
                    except OSError as exc:
                        errors.append(f"could not remove the candidate at {self.active_dir}: {exc}")
            elif not self.previous.exists():
                errors.append(
                    f"retained previous artifact missing at {self.previous}; the candidate was left in place at {self.active_dir}"
                )
            else:
                parked = self.active_dir.parent / f".rollback_{self.active_dir.name}_{os.getpid()}_{uuid.uuid4().hex[:8]}"
                try:
                    if self.active_dir.exists():
                        self.active_dir.rename(parked)
                    self.previous.rename(self.active_dir)
                except OSError as exc:
                    errors.append(f"could not restore {self.previous} to {self.active_dir}: {exc}")
                    if parked.exists() and not self.active_dir.exists():
                        try:
                            parked.rename(self.active_dir)  # better the candidate than nothing
                        except OSError as back:
                            errors.append(f"candidate parked at {parked} could not be put back either: {back}")
                else:
                    try:
                        if parked.exists():
                            shutil.rmtree(parked)
                    except OSError as exc:
                        errors.append(f"previous artifact restored; the candidate is left at {parked}: {exc}")
        finally:
            self.previous = None
            self._open = False
            self._release()
        if errors:
            raise PromotionRollbackError("; ".join(errors))


def run_promotion_transaction(
    *,
    swap: PromotionSwap,
    repo_id: str,
    work: Callable[[], str | None],
    invalidate: Callable[[], None] | None = None,
    alias_names: tuple[str, ...] = ("current", "promoted"),
) -> Path | None:
    """The whole promotion as one synchronous unit (run it in a worker thread):

    begin (locked swap) -> repository lineage lock -> alias snapshot -> `invalidate()` (drop any
    in-process copy of the artifact being replaced) -> `work()` (lineage + run record; returns
    the bundle id it wrote, or None) -> commit. On ANY failure in between, alias compensation
    and artifact rollback are attempted independently (one failing never skips the other), both
    are reported in a `PromotionRollbackError` chained to the original failure, and every lock
    is released. Returns the retained tree that could not be removed on commit, if any.
    """
    lineage_lock = repo_lineage_lock(repo_id)  # resolved (and its root created) before anything changes
    swap.begin()
    acquired = False
    snapshot: dict | None = None
    written_bundle: str | None = None
    try:
        lineage_lock.acquire()
        acquired = True
        snapshot = snapshot_aliases(repo_id=repo_id, names=alias_names)  # type: ignore[arg-type]
        if invalidate is not None:
            invalidate()
        written_bundle = work()
    except BaseException as failure:
        # Anything after begin — including taking the lineage lock — is compensated.
        problems: list[str] = []
        if snapshot is not None:
            try:
                restore_aliases(repo_id=repo_id, snapshot=snapshot, only_if_pointing_at=written_bundle)
            except Exception as alias_failure:  # noqa: BLE001 - reported below, never hides the rollback
                problems.append(f"alias compensation failed: {alias_failure}")
        try:
            swap.rollback()
        except Exception as rollback_failure:  # noqa: BLE001
            problems.append(str(rollback_failure))
        if invalidate is not None:
            try:
                invalidate()  # the previous artifact is back; drop anything cached meanwhile
            except Exception as invalidate_failure:  # noqa: BLE001
                problems.append(f"cache invalidation after rollback failed: {invalidate_failure}")
        if acquired:
            lineage_lock.release()
        if problems:
            raise PromotionRollbackError("; ".join(problems)) from failure
        raise
    try:
        return swap.commit()
    finally:
        lineage_lock.release()


async def await_uncancellable(func: Callable[..., object], *args: object, **kwargs: object) -> object:
    """Run `func` in a worker thread and wait for it even if this task is cancelled.

    A promotion transaction must run to its commit or rollback; a cancelled `await` would
    otherwise abandon the worker mid-swap with the lock held. Once cancelled, the task waits
    for the worker to settle and then re-raises the cancellation — chained to the worker's
    failure if it failed — so the caller never sees a bare worker exception in place of the
    cancellation it received.
    """
    future = asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError as cancelled:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue  # cancelled again while waiting: keep waiting for settlement
            except BaseException:  # noqa: BLE001 - the worker's own failure; chained below
                break
        settled_failure = None if future.cancelled() else future.exception()
        if settled_failure is not None:
            raise cancelled from settled_failure
        raise cancelled
