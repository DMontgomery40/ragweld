from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

from server.api.eval import evaluate_dataset_entries
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunEvent,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
)
from server.services.config_store import get_config as load_scoped_config
from server.synthetic.providers.internal_provider import run_internal_provider
from server.synthetic.providers.sdkit_provider import run_sdkit_provider
from server.synthetic.storage import (
    active_run_id_for_corpus,
    allocate_run_id,
    append_event,
    list_runs,
    load_run,
    save_run,
    write_artifact,
)

_run_tasks: dict[str, asyncio.Task[None]] = {}
_run_cancel_events: dict[str, asyncio.Event] = {}
_QUALITY_GATE_TOP1_MIN = 0.40
_QUALITY_GATE_SAMPLE_SIZE = 50
_CORPUS_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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
    return load_run(run_id)


def get_runs(*, corpus_id: str | None, limit: int) -> list[Any]:
    return list_runs(corpus_id=corpus_id, limit=limit)


def _coerce_eval_items(payload: Any) -> list[EvalDatasetItem]:
    if not isinstance(payload, list):
        return []
    out: list[EvalDatasetItem] = []
    for row in payload:
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


async def _evaluate_quality_gate(
    *,
    run_id: str,
    repo_id: str,
    artifacts_payloads: dict[Any, Any],
    summary: SyntheticRunSummary,
) -> tuple[bool | None, str | None]:
    eval_items = _coerce_eval_items(artifacts_payloads.get("eval_dataset_json"))
    if not eval_items:
        reason = "Quality gate evaluation failed: no eval items generated"
        summary.quality_gate_threshold = float(_QUALITY_GATE_TOP1_MIN)
        summary.quality_sample_size = 0
        summary.quality_gate_passed = False
        summary.quality_failure_reason = reason
        artifacts_payloads["quality_eval_json"] = {
            "run_id": run_id,
            "corpus_id": repo_id,
            "sample_size": 0,
            "threshold": float(_QUALITY_GATE_TOP1_MIN),
            "passed": False,
            "error": "no eval items generated",
        }
        return False, reason

    try:
        eval_run = await evaluate_dataset_entries(
            repo_id=repo_id,
            dataset=eval_items,
            sample_size=_QUALITY_GATE_SAMPLE_SIZE,
            dataset_id=f"synthetic:{run_id}",
            persist_run=False,
        )
    except Exception as e:
        reason = f"Quality gate evaluation failed: {e}"
        summary.quality_gate_threshold = float(_QUALITY_GATE_TOP1_MIN)
        summary.quality_sample_size = int(min(len(eval_items), _QUALITY_GATE_SAMPLE_SIZE))
        summary.quality_gate_passed = False
        summary.quality_failure_reason = reason
        artifacts_payloads["quality_eval_json"] = {
            "run_id": run_id,
            "corpus_id": repo_id,
            "sample_size": int(min(len(eval_items), _QUALITY_GATE_SAMPLE_SIZE)),
            "threshold": float(_QUALITY_GATE_TOP1_MIN),
            "passed": False,
            "error": str(e),
        }
        return False, reason
    quality_payload = {
        "run_id": run_id,
        "corpus_id": repo_id,
        "sample_size": int(min(len(eval_items), _QUALITY_GATE_SAMPLE_SIZE)),
        "top1_accuracy": float(eval_run.top1_accuracy),
        "topk_accuracy": float(eval_run.topk_accuracy),
        "mrr": float(eval_run.metrics.mrr),
        "threshold": float(_QUALITY_GATE_TOP1_MIN),
        "passed": bool(float(eval_run.top1_accuracy) >= float(_QUALITY_GATE_TOP1_MIN)),
    }
    artifacts_payloads["quality_eval_json"] = quality_payload

    summary.quality_top1_accuracy = float(eval_run.top1_accuracy)
    summary.quality_topk_accuracy = float(eval_run.topk_accuracy)
    summary.quality_mrr = float(eval_run.metrics.mrr)
    summary.quality_sample_size = int(min(len(eval_items), _QUALITY_GATE_SAMPLE_SIZE))
    summary.quality_gate_threshold = float(_QUALITY_GATE_TOP1_MIN)
    passed = bool(float(eval_run.top1_accuracy) >= float(_QUALITY_GATE_TOP1_MIN))
    summary.quality_gate_passed = passed
    if not passed:
        reason = (
            f"Quality gate failed: top1={float(eval_run.top1_accuracy):.3f} "
            f"< threshold={float(_QUALITY_GATE_TOP1_MIN):.3f} "
            f"(sample={summary.quality_sample_size})"
        )
        summary.quality_failure_reason = reason
        return False, reason

    summary.quality_failure_reason = None
    return True, None


async def start_run(request: SyntheticRunStartRequest) -> SyntheticRun:
    repo_id = _validate_repo_id(request.repo_id)

    active = active_run_id_for_corpus(repo_id)
    if active:
        raise RuntimeError(
            f"A synthetic run is already active for corpus_id={repo_id}: run_id={active}. "
            "Cancel it before starting another run."
        )

    try:
        cfg = await load_scoped_config(repo_id=repo_id)
    except Exception:
        cfg = await load_scoped_config(repo_id=None)
    started_at = datetime.now(UTC)
    run_id = allocate_run_id(repo_id, started_at)
    run = SyntheticRun(
        run_id=run_id,
        repo_id=repo_id,
        status="running",
        started_at=started_at,
        completed_at=None,
        provider=request.provider,
        recipe=request.recipe,
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        request=request,
        artifacts=[],
        summary=SyntheticRunSummary(),
        error=None,
    )
    save_run(run)
    _append_state(run_id, "running", "Synthetic run started.")

    cancel_event = asyncio.Event()
    _run_cancel_events[run_id] = cancel_event
    _run_tasks[run_id] = asyncio.create_task(_run_job(run_id=run_id, request=request, cancel_event=cancel_event))
    return run


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
    try:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except Exception:
            cfg = await load_scoped_config(repo_id=None)
        _append_log(run_id, f"Provider={request.provider} recipe={request.recipe}")

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        if request.provider == "internal_ragweld":
            artifacts_payloads, summary = await run_internal_provider(
                repo_id=repo_id,
                cfg=cfg,
                request=request,
            )
        elif request.provider == "synthetic_data_kit":
            artifacts_payloads, summary = await run_sdkit_provider(
                run_id=run_id,
                repo_id=repo_id,
                cfg=cfg,
                request=request,
            )
        else:
            raise RuntimeError(f"Unsupported synthetic provider: {request.provider}")

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        gate_passed, gate_reason = await _evaluate_quality_gate(
            run_id=run_id,
            repo_id=repo_id,
            artifacts_payloads=artifacts_payloads,
            summary=summary,
        )

        artifacts: list[SyntheticArtifactRef] = []
        for kind, payload in artifacts_payloads.items():
            ref = write_artifact(run_id, kind, payload)
            artifacts.append(ref)
            _append_artifact(run_id, ref)

        run = load_run(run_id)
        run.summary = summary
        run.artifacts = artifacts
        if gate_passed is False:
            run.status = "failed"
            run.error = gate_reason or "Quality gate failed."
            run.completed_at = datetime.now(UTC)
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
        save_run(run)
        _append_complete(run_id, "completed")
    except asyncio.CancelledError:
        run = load_run(run_id)
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
        save_run(run)
        _append_complete(run_id, "cancelled", "Cancelled.")
    except Exception as e:
        run = load_run(run_id)
        run.status = "failed"
        run.completed_at = datetime.now(UTC)
        run.error = str(e)
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
