from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from server.api.eval import evaluate_dataset_entries
from server.lineage import (
    attach_refs_to_current_bundle,
    capture_synthetic_artifact_version,
    capture_synthetic_run_version,
    ensure_current_bundle,
    make_ref,
)
from server.models.tribrid_config_model import (
    EvalDatasetItem,
    SyntheticArtifactRef,
    SyntheticRun,
    SyntheticRunEvent,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.services.config_store import get_config as load_scoped_config
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
_CORPUS_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_ROOT = Path(__file__).resolve().parents[2]
_DATASET_DIR = _ROOT / "data" / "eval_datasets"
_LEGACY_DATASET_DIR = _ROOT / "data" / "eval_dataset"
_RECIPES_REQUIRING_EVAL_DATASET = frozenset({"eval_dataset", "triplets", "autotune_retrieval", "full_stack"})


def _is_openai_gpt5_synthetic_model(model: str) -> bool:
    raw = str(model or "").strip().lower()
    if not raw:
        return False
    for prefix in ("openrouter:", "litellm:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    if raw.startswith("openai/"):
        raw = raw.split("/", 1)[1]
    return raw.startswith("gpt-5")


def _reject_removed_or_banned_synthetic_inputs(request: SyntheticRunStartRequest) -> None:
    if str(request.provider or "").strip() != "synthetic_data_kit":
        raise RuntimeError(
            "internal_ragweld has been removed from this branch's live Synthetic Lab path. "
            "Use synthetic_data_kit while the Unsloth Data Recipes replacement is wired in."
        )

    for field_name in ("generator_model", "judge_model"):
        model = str(getattr(request, field_name, "") or "").strip()
        lower = model.lower()
        if "openai/" in lower or lower.startswith(("gpt-", "o1", "o3", "o4", "openrouter:openai/", "litellm:openai/")):
            if not _is_openai_gpt5_synthetic_model(model):
                raise RuntimeError(
                    f"{field_name} must use an OpenAI GPT-5 model on this branch. Got {model!r}."
                )


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


def _safe_corpus_id(corpus_id: str) -> str:
    safe = quote(str(corpus_id or "").strip(), safe="._-")
    if not safe:
        raise ValueError("Invalid corpus_id")
    return safe


def _legacy_safe_corpus_id(corpus_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(corpus_id or "").strip()).strip("._-")
    if not safe:
        raise ValueError("Invalid corpus_id")
    return safe


def _load_seed_eval_items(repo_id: str) -> tuple[list[EvalDatasetItem], Path | None]:
    canonical = _DATASET_DIR / f"{_safe_corpus_id(repo_id)}.json"
    path = canonical
    if not canonical.exists():
        legacy = _LEGACY_DATASET_DIR / f"{_legacy_safe_corpus_id(repo_id)}.json"
        if legacy.exists():
            try:
                canonical.parent.mkdir(parents=True, exist_ok=True)
                canonical.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                path = canonical
            except Exception:
                path = legacy

    if not path.exists():
        return [], None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], path
    if not isinstance(raw, list):
        return [], path

    out: list[EvalDatasetItem] = []
    for row in raw:
        try:
            out.append(EvalDatasetItem.model_validate(row))
        except Exception:
            continue
    return out, path


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


def _hydrate_eval_dataset_from_seed(
    *,
    run_id: str,
    repo_id: str,
    request: SyntheticRunStartRequest,
    artifacts_payloads: dict[Any, Any],
    summary: SyntheticRunSummary,
) -> int:
    if request.recipe not in _RECIPES_REQUIRING_EVAL_DATASET:
        return 0
    if _coerce_eval_items(artifacts_payloads.get("eval_dataset_json")):
        return 0

    seed_items, source_path = _load_seed_eval_items(repo_id)
    if not seed_items:
        return 0

    max_items = len(seed_items)
    if request.max_pairs is not None:
        max_items = max(1, min(max_items, int(request.max_pairs)))

    if len(seed_items) > max_items:
        if request.seed is not None:
            chosen = random.Random(int(request.seed)).sample(seed_items, k=max_items)
        else:
            chosen = seed_items[:max_items]
    else:
        chosen = seed_items

    artifacts_payloads["eval_dataset_json"] = [row.model_dump(mode="json") for row in chosen]
    summary.items_generated = int(summary.items_generated) + len(chosen)

    summary.degradation.seed_hydration_used = True
    summary.degradation.seed_hydration_count = len(chosen)
    summary.degradation.degraded = True
    summary.degradation.reasons.append(
        f"Eval dataset hydrated from seed ({len(chosen)} rows) instead of LLM generation."
    )

    dataset_label = str(source_path) if source_path is not None else "seed dataset"
    _append_log(
        run_id,
        f"Hydrated eval_dataset_json from {dataset_label} with {len(chosen)} seed rows "
        f"(recipe={request.recipe}, max_pairs={request.max_pairs}).",
    )
    report = str(artifacts_payloads.get("report_md") or "").rstrip()
    if report:
        report += "\n"
    artifacts_payloads["report_md"] = (
        f"{report}Seed fallback hydrated {len(chosen)} eval rows from corpus dataset."
    )
    return len(chosen)


async def _evaluate_quality_gate(
    *,
    run_id: str,
    repo_id: str,
    cfg: TriBridConfig,
    artifacts_payloads: dict[Any, Any],
    summary: SyntheticRunSummary,
) -> tuple[bool | None, str | None]:
    gate = cfg.synthetic.quality_gate
    top1_min = float(gate.top1_min)
    sample_size = int(gate.sample_size)

    eval_items = _coerce_eval_items(artifacts_payloads.get("eval_dataset_json"))
    if not eval_items:
        reason = "Quality gate evaluation failed: no eval items generated"
        summary.quality_gate_threshold = top1_min
        summary.quality_sample_size = 0
        summary.quality_gate_passed = False
        summary.quality_failure_reason = reason
        artifacts_payloads["quality_eval_json"] = {
            "run_id": run_id,
            "corpus_id": repo_id,
            "sample_size": 0,
            "threshold": top1_min,
            "passed": False,
            "error": "no eval items generated",
        }
        return False, reason

    try:
        eval_run = await evaluate_dataset_entries(
            repo_id=repo_id,
            dataset=eval_items,
            sample_size=sample_size,
            dataset_id=f"synthetic:{run_id}",
            persist_run=False,
        )
    except Exception as e:
        reason = f"Quality gate evaluation failed: {e}"
        summary.quality_gate_threshold = top1_min
        summary.quality_sample_size = int(min(len(eval_items), sample_size))
        summary.quality_gate_passed = False
        summary.quality_failure_reason = reason
        artifacts_payloads["quality_eval_json"] = {
            "run_id": run_id,
            "corpus_id": repo_id,
            "sample_size": int(min(len(eval_items), sample_size)),
            "threshold": top1_min,
            "passed": False,
            "error": str(e),
        }
        return False, reason
    quality_payload = {
        "run_id": run_id,
        "corpus_id": repo_id,
        "sample_size": int(min(len(eval_items), sample_size)),
        "top1_accuracy": float(eval_run.top1_accuracy),
        "topk_accuracy": float(eval_run.topk_accuracy),
        "mrr": float(eval_run.metrics.mrr),
        "threshold": top1_min,
        "passed": bool(float(eval_run.top1_accuracy) >= top1_min),
    }
    artifacts_payloads["quality_eval_json"] = quality_payload

    summary.quality_top1_accuracy = float(eval_run.top1_accuracy)
    summary.quality_topk_accuracy = float(eval_run.topk_accuracy)
    summary.quality_mrr = float(eval_run.metrics.mrr)
    summary.quality_sample_size = int(min(len(eval_items), sample_size))
    summary.quality_gate_threshold = top1_min
    passed = bool(float(eval_run.top1_accuracy) >= top1_min)
    summary.quality_gate_passed = passed
    if not passed:
        reason = (
            f"Quality gate failed: top1={float(eval_run.top1_accuracy):.3f} "
            f"< threshold={top1_min:.3f} "
            f"(sample={summary.quality_sample_size})"
        )
        summary.quality_failure_reason = reason
        return False, reason

    summary.quality_failure_reason = None
    return True, None


async def start_run(request: SyntheticRunStartRequest) -> SyntheticRun:
    repo_id = _validate_repo_id(request.repo_id)
    _reject_removed_or_banned_synthetic_inputs(request)

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
        input_bundle_id=ensure_current_bundle(repo_id=repo_id, cfg=cfg).bundle_id,
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
    cfg: Any | None = None
    try:
        try:
            cfg = await load_scoped_config(repo_id=repo_id)
        except Exception:
            cfg = await load_scoped_config(repo_id=None)
        _append_log(run_id, f"Provider={request.provider} recipe={request.recipe}")

        if cancel_event.is_set():
            raise asyncio.CancelledError()

        if request.provider == "synthetic_data_kit":
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

        _hydrate_eval_dataset_from_seed(
            run_id=run_id,
            repo_id=repo_id,
            request=request,
            artifacts_payloads=artifacts_payloads,
            summary=summary,
        )

        gate_passed, gate_reason = await _evaluate_quality_gate(
            run_id=run_id,
            repo_id=repo_id,
            cfg=cfg,
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
