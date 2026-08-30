from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.api.eval import evaluate_dataset_entries
from server.config_redaction import redact_run_record, redacted_config_snapshot
from server.db.postgres import PostgresClient
from server.lineage import (
    attach_refs_to_current_bundle,
    capture_synthetic_artifact_version,
    capture_synthetic_run_version,
    ensure_current_bundle,
    make_ref,
)
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    EvalRun,
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunEvent,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.services.config_store import get_config as load_scoped_config
from server.synthetic.providers.grounded_qa_provider import run_grounded_qa_provider
from server.synthetic.storage import (
    active_run_id_for_corpus,
    allocate_run_id,
    append_event,
    list_runs,
    load_run,
    save_run,
    write_artifact,
)
from server.training.triplet_miner import mine_triplets_from_eval_results

_run_tasks: dict[str, asyncio.Task[None]] = {}
_run_cancel_events: dict[str, asyncio.Event] = {}
_start_lock = asyncio.Lock()
_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_RECIPES_REQUIRING_EVAL_DATASET = frozenset({"eval_dataset", "triplets", "autotune_retrieval", "full_stack"})
_RECIPES_PRODUCING_TRIPLETS = frozenset({"triplets", "full_stack"})


def _append_log(run_id: str, message: str) -> None:
    append_event(
        run_id,
        SyntheticRunEvent(
            type="log",
            ts=datetime.now(UTC),
            run_id=run_id,
            message=str(message),
        ),
    )


def _append_progress(run_id: str, message: str, percent: float | None) -> None:
    append_event(
        run_id,
        SyntheticRunEvent(
            type="progress",
            ts=datetime.now(UTC),
            run_id=run_id,
            message=str(message),
            percent=None if percent is None else max(0.0, min(100.0, float(percent))),
        ),
    )


def _append_state(run_id: str, status: str, message: str | None = None) -> None:
    append_event(
        run_id,
        SyntheticRunEvent(
            type="state",
            ts=datetime.now(UTC),
            run_id=run_id,
            status=status,  # type: ignore[arg-type]
            message=message,
        ),
    )


def _append_complete(run_id: str, status: str, message: str | None = None) -> None:
    append_event(
        run_id,
        SyntheticRunEvent(
            type="complete",
            ts=datetime.now(UTC),
            run_id=run_id,
            status=status,  # type: ignore[arg-type]
            message=message,
        ),
    )


def _append_artifact(run_id: str, artifact: SyntheticArtifactRef) -> None:
    append_event(
        run_id,
        SyntheticRunEvent(
            type="artifact",
            ts=datetime.now(UTC),
            run_id=run_id,
            artifact=artifact,
            message=f"artifact ready: {artifact.kind}",
        ),
    )


def get_run(run_id: str) -> SyntheticRun:
    # Read boundary: records written before the redaction existed still carry the
    # credential on disk, so it is withheld on the way out as well as on the way in.
    return redact_run_record(load_run(run_id))


def get_runs(*, corpus_id: str | None, limit: int) -> tuple[list[Any], list[Any]]:
    runs, artifacts = list_runs(corpus_id=corpus_id, limit=limit)
    return [redact_run_record(run) for run in runs], artifacts


def _coerce_eval_items(payload: Any) -> list[EvalDatasetItem]:
    if not isinstance(payload, list):
        return []
    out: list[EvalDatasetItem] = []
    for row in payload:
        if isinstance(row, EvalDatasetItem):
            out.append(row)
            continue
        try:
            out.append(EvalDatasetItem.model_validate(row))
        except Exception:
            continue
    return out


def _validate_repo_id(repo_id: str) -> str:
    rid = str(repo_id or "").strip()
    if not rid:
        raise ValueError("Missing corpus_id")
    if not _CORPUS_ID_RE.fullmatch(rid):
        raise ValueError(
            "Invalid corpus_id: only letters, numbers, dot, underscore, and hyphen are allowed"
        )
    if rid in {".", ".."} or ".." in rid:
        raise ValueError("Invalid corpus_id: path traversal segments are not allowed")
    return rid


def _artifact_lineage_ref_map(
    *,
    repo_id: str,
    run_id: str,
    artifacts: list[SyntheticArtifactRef],
) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for artifact in artifacts:
        version = capture_synthetic_artifact_version(
            repo_id=repo_id,
            artifact_kind=str(artifact.kind),
            path=str(artifact.path),
            run_id=run_id,
        )
        refs[str(artifact.kind)] = make_ref("synthetic_artifact", version.version_id)
    return refs


def _attach_lineage(run: SyntheticRun, cfg: Any) -> SyntheticRun:
    run_version = capture_synthetic_run_version(
        run_payload=run.model_dump(mode="json", by_alias=True),
        repo_id=str(run.repo_id),
    )
    artifact_refs = [
        ref
        for ref in (run.artifact_lineage_refs or {}).values()
        if hasattr(ref, "kind") and hasattr(ref, "version_id")
    ]
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=str(run.repo_id),
        cfg=cfg,
        synthetic_runs=[make_ref("synthetic_run", run_version.version_id)],
        synthetic_artifacts=list(artifact_refs),
        preserve_attached_refs=True,
    )
    run.lineage_ref = make_ref("synthetic_run", run_version.version_id)
    run.bundle_id = bundle.bundle_id
    return run


def _record_gate_failure(
    *,
    run_id: str,
    repo_id: str,
    summary: SyntheticRunSummary,
    artifacts_payloads: dict[Any, Any],
    top1_min: float,
    sample_size: int,
    reason: str,
    error: str,
) -> tuple[bool, str, None]:
    summary.quality_gate_threshold = top1_min
    summary.quality_sample_size = sample_size
    summary.quality_gate_passed = False
    summary.quality_failure_reason = reason
    artifacts_payloads["quality_eval_json"] = {
        "run_id": run_id,
        "corpus_id": repo_id,
        "sample_size": sample_size,
        "threshold": top1_min,
        "passed": False,
        "error": error,
    }
    return False, reason, None


async def _evaluate_quality_gate(
    *,
    run_id: str,
    repo_id: str,
    cfg: TriBridConfig,
    artifacts_payloads: dict[Any, Any],
    summary: SyntheticRunSummary,
    evaluate_all: bool = False,
    cancel_event: asyncio.Event | None = None,
) -> tuple[bool | None, str | None, EvalRun | None]:
    """Run every gate entry through the real retrieval lane and score top-1 against the threshold.

    The gate is judged on the first ``synthetic.quality_gate.sample_size`` entries. With
    ``evaluate_all`` every generated entry is retrieved so the run's results can be mined
    for reranker triplets; the gate subset is unchanged.
    """
    gate = cfg.synthetic.quality_gate
    top1_min = float(gate.top1_min)
    sample_size = int(gate.sample_size)

    eval_items = _coerce_eval_items(artifacts_payloads.get("eval_dataset_json"))
    if not eval_items:
        return _record_gate_failure(
            run_id=run_id,
            repo_id=repo_id,
            summary=summary,
            artifacts_payloads=artifacts_payloads,
            top1_min=top1_min,
            sample_size=0,
            reason="Quality gate evaluation failed: no eval items generated",
            error="no eval items generated",
        )

    gate_size = int(min(len(eval_items), sample_size))
    try:
        eval_run = await evaluate_dataset_entries(
            repo_id=repo_id,
            dataset=eval_items,
            sample_size=None if evaluate_all else sample_size,
            dataset_id=f"synthetic:{run_id}",
            persist_run=False,
            cancel_event=cancel_event,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return _record_gate_failure(
            run_id=run_id,
            repo_id=repo_id,
            summary=summary,
            artifacts_payloads=artifacts_payloads,
            top1_min=top1_min,
            sample_size=gate_size,
            reason=f"Quality gate evaluation failed: {e}",
            error=str(e),
        )

    gate_results = eval_run.results[:gate_size]
    total = max(1, len(gate_results))
    top1_accuracy = sum(1 for r in gate_results if r.top1_hit) / total
    topk_accuracy = sum(1 for r in gate_results if r.topk_hit) / total
    mrr = sum(float(r.reciprocal_rank) for r in gate_results) / total
    passed = bool(top1_accuracy >= top1_min)
    artifacts_payloads["quality_eval_json"] = {
        "run_id": run_id,
        "corpus_id": repo_id,
        "sample_size": gate_size,
        "entries_evaluated": len(eval_run.results),
        "top1_accuracy": float(top1_accuracy),
        "topk_accuracy": float(topk_accuracy),
        "mrr": float(mrr),
        "threshold": top1_min,
        "passed": passed,
    }

    summary.quality_top1_accuracy = float(top1_accuracy)
    summary.quality_topk_accuracy = float(topk_accuracy)
    summary.quality_mrr = float(mrr)
    summary.quality_sample_size = gate_size
    summary.quality_gate_threshold = top1_min
    summary.quality_gate_passed = passed
    if not passed:
        reason = (
            f"Quality gate failed: top1={float(top1_accuracy):.3f} "
            f"< threshold={top1_min:.3f} "
            f"(sample={gate_size})"
        )
        summary.quality_failure_reason = reason
        return False, reason, eval_run

    summary.quality_failure_reason = None
    return True, None, eval_run


async def _corpus_root(cfg: TriBridConfig, repo_id: str) -> Path:
    """Absolute on-disk root of the corpus (for reading candidate negatives); a missing corpus is an error."""
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(repo_id)
    finally:
        await pg.disconnect()
    if corpus is None:
        raise RuntimeError(f"Corpus not found: {repo_id}")
    root = Path(str(corpus.get("path") or "")).expanduser()
    return root if root.is_absolute() else _ROOT / root


async def start_run(request: SyntheticRunStartRequest) -> SyntheticRun:
    repo_id = _validate_repo_id(request.repo_id)
    cfg = await load_scoped_config(repo_id=repo_id)

    async with _start_lock:
        active = active_run_id_for_corpus(repo_id)
        if active:
            raise RuntimeError(
                f"A synthetic run is already active for corpus_id={repo_id}: run_id={active}. "
                "Cancel it before starting another run."
            )
        started_at = datetime.now(UTC)
        run_id = allocate_run_id(repo_id, started_at)
        run = _new_run(run_id=run_id, repo_id=repo_id, started_at=started_at, cfg=cfg, request=request)
        save_run(run)
        _append_state(run_id, "running", "Synthetic run started.")
        cancel_event = asyncio.Event()
        _run_cancel_events[run_id] = cancel_event
        _run_tasks[run_id] = asyncio.create_task(_run_job(run_id=run_id, request=request, cancel_event=cancel_event))
    return run


def _new_run(
    *, run_id: str, repo_id: str, started_at: datetime, cfg: TriBridConfig, request: SyntheticRunStartRequest
) -> SyntheticRun:
    # One helper builds both snapshot forms, already redacted, so no call site can
    # withhold the credential from one and leak it through the other (M-89).
    _snapshot = redacted_config_snapshot(cfg)
    return SyntheticRun(
        run_id=run_id,
        repo_id=repo_id,
        status="running",
        started_at=started_at,
        completed_at=None,
        provider=request.provider,
        recipe=request.recipe,
        config_snapshot=_snapshot[0],
        config=_snapshot[1],
        request=request,
        artifacts=[],
        summary=SyntheticRunSummary(),
        error=None,
        input_bundle_id=ensure_current_bundle(repo_id=repo_id, cfg=cfg).bundle_id,
    )


async def cancel_run(run_id: str) -> bool:
    run = load_run(run_id)
    if run.status in {"completed", "failed", "cancelled"}:
        return True
    ev = _run_cancel_events.get(run_id)
    if ev is not None:
        ev.set()
    if run_id not in _run_tasks:
        now = datetime.now(UTC)
        run.status = "cancelled"
        run.completed_at = now
        save_run(run)
        _append_state(run_id, "cancelled", "Cancelled by user.")
        _append_complete(run_id, "cancelled")
    return True


async def _run_job(*, run_id: str, request: SyntheticRunStartRequest, cancel_event: asyncio.Event) -> None:
    run = load_run(run_id)
    repo_id = str(run.repo_id)
    cfg: Any | None = None

    async def _progress(message: str, percent: float | None) -> None:
        await asyncio.to_thread(_append_progress, run_id, message, percent)

    try:
        cfg = await load_scoped_config(repo_id=repo_id)
        await asyncio.to_thread(_append_log, run_id, f"Provider={request.provider} recipe={request.recipe}")

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        if request.provider == "grounded_qa":
            artifacts_payloads, summary, unpublished_items = await run_grounded_qa_provider(
                run_id=run_id,
                repo_id=repo_id,
                cfg=cfg,
                request=request,
                cancel_event=cancel_event,
                on_progress=_progress,
            )
        else:
            raise RuntimeError(f"Unsupported synthetic provider: {request.provider}")

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        produces_triplets = request.recipe in _RECIPES_PRODUCING_TRIPLETS
        gate_passed: bool | None = None
        gate_reason: str | None = None
        eval_run: EvalRun | None = None
        if request.recipe in _RECIPES_REQUIRING_EVAL_DATASET:
            # The gate retrieves the unpublished rows (answers intact) so every EvalResult in
            # the run carries its own expected_answer; the artifact is published afterwards.
            gate_payloads: dict[Any, Any] = {"eval_dataset_json": unpublished_items}
            gate_passed, gate_reason, eval_run = await _evaluate_quality_gate(
                run_id=run_id,
                repo_id=repo_id,
                cfg=cfg,
                artifacts_payloads=gate_payloads,
                summary=summary,
                evaluate_all=produces_triplets,
                cancel_event=cancel_event,
            )
            if "quality_eval_json" in gate_payloads:
                artifacts_payloads["quality_eval_json"] = gate_payloads["quality_eval_json"]
        if cancel_event.is_set():
            raise asyncio.CancelledError()
        if produces_triplets:
            triplets, mining_stats = await asyncio.to_thread(
                mine_triplets_from_eval_results,
                eval_run.results if eval_run is not None else [],
                negative_ratio=int(cfg.training.learning_reranker_negative_ratio),
                source=f"synthetic_run:{run_id}",
                corpus_root=await _corpus_root(cfg, repo_id),
                with_stats=True,
            )
            if cancel_event.is_set():
                raise asyncio.CancelledError()
            artifacts_payloads["triplets_jsonl"] = triplets
            summary.triplets_mined = len(triplets)
            await asyncio.to_thread(
                _append_log,
                run_id,
                f"Mined {len(triplets)} reranker triplets from the retrieval results of "
                f"{len(eval_run.results) if eval_run is not None else 0} generated questions "
                f"({mining_stats.get('negatives_rejected_answer_leak', 0)} candidate negatives rejected for "
                "containing the expected answer).",
            )

        artifacts: list[SyntheticArtifactRef] = []
        for kind, payload in artifacts_payloads.items():
            if cancel_event.is_set():
                raise asyncio.CancelledError()
            ref = await asyncio.to_thread(write_artifact, run_id, kind, payload)
            artifacts.append(ref)
            await asyncio.to_thread(_append_artifact, run_id, ref)

        if cancel_event.is_set():
            raise asyncio.CancelledError()
        run = load_run(run_id)
        run.summary = summary
        run.artifacts = artifacts
        run.artifact_lineage_refs = _artifact_lineage_ref_map(repo_id=repo_id, run_id=run_id, artifacts=artifacts)
        if gate_passed is False:
            run.status = "failed"
            run.error = gate_reason or "Quality gate failed."
            run.completed_at = datetime.now(UTC)
            run = _attach_lineage(run, cfg)
            save_run(run)
            append_event(
                run_id,
                SyntheticRunEvent(
                    type="error",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    message=str(run.error),
                    status="failed",
                ),
            )
            _append_complete(run_id, "failed", str(run.error))
            return

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run.error = None
        run = _attach_lineage(run, cfg)
        save_run(run)
        _append_complete(run_id, "completed")
    except asyncio.CancelledError:
        run = load_run(run_id)
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        if cfg is not None:
            run = _attach_lineage(run, cfg)
        save_run(run)
        _append_complete(run_id, "cancelled", "Cancelled.")
    except Exception as e:
        run = load_run(run_id)
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = str(e)
        if cfg is not None:
            run = _attach_lineage(run, cfg)
        save_run(run)
        append_event(
            run_id,
            SyntheticRunEvent(
                type="error",
                ts=datetime.now(UTC),
                run_id=run_id,
                message=str(e),
                status="failed",
            ),
        )
        _append_complete(run_id, "failed", str(e))
    finally:
        _run_cancel_events.pop(run_id, None)
        _run_tasks.pop(run_id, None)
