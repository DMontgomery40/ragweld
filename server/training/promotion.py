"""Auto-promotion decision shared by the reranker and Learning Agent trainers.

Pure and artifact-free so the gate can be tested without loading a model. The
trainers measure; this module decides whether the fresh artifact may replace the
active one without an operator.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from server.lineage.registry import repo_lineage_lock, restore_aliases, snapshot_aliases
from server.models.tribrid_config_model import LineageAliasName
from server.training.artifact_store import VersionedArtifactSwap

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
    primary_text = (
        f"{float(primary_value):.6f}"
        if final_is_finite and primary_value is not None
        else ("n/a" if primary_value is None else str(primary_value))
    )
    baseline_text = (
        f"{float(baseline_primary):.6f}"
        if baseline_state == "measured" and baseline_primary is not None
        else _BASELINE_NA_TEXT[baseline_state]
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


def run_promotion_transaction(
    *,
    swap: VersionedArtifactSwap,
    repo_id: str,
    work: Callable[[], str | None],
    invalidate: Callable[[], None] | None = None,
    alias_names: tuple[str, ...] = ("current", "promoted"),
) -> Path | None:
    """The whole promotion as one synchronous unit (run it in a worker thread):

    begin (locked, recovery-first versioned publish + atomic pointer switch) -> repository
    lineage lock -> alias snapshot -> `invalidate()` (drop any in-process copy of the artifact
    being replaced) -> `work()` (lineage + run record; returns the bundle id it wrote, or None)
    -> commit (prune retired versions). On ANY failure in between, alias compensation and the
    pointer rollback are attempted independently (one failing never skips the other), both are
    reported in a `PromotionRollbackError` chained to the original failure, and every lock is
    released. Returns a retired version that could not be pruned on commit, if any.
    """
    lineage_lock = repo_lineage_lock(repo_id)  # resolved (and its root created) before anything changes
    swap.begin()
    acquired = False
    snapshot: dict[LineageAliasName, str | None] | None = None
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
