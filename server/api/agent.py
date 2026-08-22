from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.api.dataset import _dataset_path_for_corpus, _load_dataset
from server.chat.context_formatter import format_context_for_llm
from server.chat.prompt_builder import get_system_prompt
from server.chat.ragweld_mlx import clear_cache as clear_ragweld_cache
from server.db.postgres import PostgresClient
from server.lineage import (
    attach_refs_to_current_bundle,
    capture_path_version,
    capture_training_run_version,
    ensure_current_bundle,
    make_ref,
)
from server.models.tribrid_config_model import (
    AgentTrainControlPlaneStatusResponse,
    AgentTrainDiffRequest,
    AgentTrainDiffResponse,
    AgentTrainExecuteRequest,
    AgentTrainExecuteResponse,
    AgentTrainMetricEvent,
    AgentTrainMetricsResponse,
    AgentTrainRun,
    AgentTrainRunMeta,
    AgentTrainRunsResponse,
    AgentTrainStartRequest,
    AgentTrainStartResponse,
    ChunkMatch,
    EvalDatasetItem,
    OkResponse,
    TriBridConfig,
)
from server.retrieval.mlx_qwen3 import mlx_is_available
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.training.control_plane import (
    build_agent_control_plane_status,
    build_agent_run_links,
    build_agent_run_operator_hint,
)
from server.training.flyte_client import (
    FLYTE_ABORT_PHASES,
    FLYTE_FAILURE_PHASES,
    FLYTE_TERMINAL_PHASES,
    FlyteAdminClient,
    FlyteLaunchPlanRef,
    FlyteUnavailableError,
    new_execution_name,
)
from server.training.mlflow_client import MlflowClient, MlflowRunHandle, MlflowUnavailableError
from server.training.mlx_qwen3_agent_trainer import (
    deterministic_split,
    evaluate_mlx_qwen3_agent_loss,
    train_mlx_qwen3_agent,
)
from server.training.mlx_qwen3_trainer import TrainingCancelledError

router = APIRouter(tags=["agent"])

_ROOT = Path(__file__).resolve().parents[2]
_RUNS_DIR = _ROOT / "data" / "agent_train_runs"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TMP_ROOT = Path(tempfile.gettempdir()).resolve()


def _resolve_path(path_str: str) -> Path:
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def _resolve_training_dataset_path(
    *,
    corpus_id: str,
    request_override: str,
    config_default: str,
    evaluation_default: str,
) -> tuple[Path | None, list[str]]:
    legacy_eval_default = "data/evaluation_dataset.json"
    corpus_dataset_path = _dataset_path_for_corpus(corpus_id)
    messages: list[str] = []

    candidates: list[tuple[str, Path, bool]] = []
    if request_override:
        candidates.append(("request override", _resolve_path(request_override), False))
    if config_default:
        candidates.append(("training.ragweld_agent_train_dataset_path", _resolve_path(config_default), False))
    if evaluation_default and evaluation_default != legacy_eval_default:
        candidates.append(("evaluation.eval_dataset_path", _resolve_path(evaluation_default), False))
    elif evaluation_default == legacy_eval_default:
        candidates.append(("evaluation.eval_dataset_path (legacy default)", _resolve_path(evaluation_default), True))
    candidates.append(("corpus eval dataset", corpus_dataset_path, False))

    deduped: list[tuple[str, Path, bool]] = []
    seen_paths: set[str] = set()
    for label, path, legacy_default_path in candidates:
        key = str(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduped.append((label, path, legacy_default_path))

    for label, candidate_path, is_legacy_default in deduped:
        if is_legacy_default and not candidate_path.exists():
            messages.append(
                f"Skipping missing legacy default dataset path: {candidate_path}. "
                "Falling back to corpus-scoped dataset."
            )
            continue
        if candidate_path.exists():
            messages.append(f"Loading agent training dataset from {label}: {candidate_path}")
            return candidate_path, messages
        messages.append(f"Dataset path not found for {label}: {candidate_path}")

    return None, messages


def _atomic_copy_dir(src: Path, dst: Path) -> None:
    """Atomically replace dst with a copied version of src."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    stamp = f"{int(datetime.now(UTC).timestamp())}_{os.getpid()}"
    tmp = dst.parent / f".tmp_{dst.name}_{stamp}"
    bak = dst.parent / f".bak_{dst.name}_{stamp}"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(bak, ignore_errors=True)
    shutil.copytree(src, tmp, dirs_exist_ok=True)
    if dst.exists():
        dst.rename(bak)
    tmp.rename(dst)
    shutil.rmtree(bak, ignore_errors=True)


def _run_dir(run_id: str) -> Path:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR / run_id


def _run_json_path(run_id: str) -> Path:
    return _run_dir(run_id) / "run.json"


def _metrics_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metrics.jsonl"


def _capture_model_artifact_ref(run_id: str, repo_id: str) -> Any | None:
    path = _run_dir(run_id) / "model"
    if not path.exists():
        return None
    version = capture_path_version(
        kind="agent_model_artifact",
        path=path,
        repo_id=repo_id,
        source="generated",
        metadata={"run_id": run_id},
    )
    return make_ref("agent_model_artifact", version.version_id)


def _cfg_from_run_snapshot(run: AgentTrainRun) -> TriBridConfig | None:
    try:
        return TriBridConfig.model_validate(run.config_snapshot)
    except Exception:
        return None


def _apply_run_control_plane_metadata(run: AgentTrainRun, cfg: TriBridConfig) -> AgentTrainRun:
    run.external_links = build_agent_run_links(run, cfg)
    run.operator_hint = build_agent_run_operator_hint(run, cfg)
    return run


_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "cancelled"})
_FLYTE_RECONCILE_INTERVAL_S = 5.0
_FLYTE_RECONCILE_TERMINAL_INTERVAL_S = 60.0
_flyte_reconcile_at: dict[str, float] = {}
# Outcome a cancel-driven job must finalize with when the orchestrator (not the
# operator) ended the run: run_id -> (status, message).
_train_cancel_outcomes: dict[str, tuple[str, str]] = {}


def _flyte_scope(cfg: TriBridConfig) -> tuple[str, str, str]:
    return (
        str(cfg.training.ragweld_agent_flyte_admin_base_url or "").strip(),
        str(cfg.training.ragweld_agent_flyte_project or "").strip(),
        str(cfg.training.ragweld_agent_flyte_domain or "").strip(),
    )


def _mlflow_terminate_for_run(run: AgentTrainRun, cfg: TriBridConfig | None, *, status: str) -> None:
    """Terminate the MLflow run of a run that has no active training job."""
    if cfg is None or str(run.tracking_backend or "") != "mlflow" or not str(run.tracking_run_id or "").strip():
        return
    try:
        MlflowClient(str(cfg.training.ragweld_agent_mlflow_tracking_url or "")).set_terminated(
            str(run.tracking_run_id), status=status
        )
    except MlflowUnavailableError as exc:
        _append_event(
            run.run_id,
            AgentTrainMetricEvent(
                type="log",
                ts=datetime.now(UTC),
                run_id=run.run_id,
                message=f"MLflow run could not be finalized ({status}): {exc}",
            ),
        )


def _finalize_run_without_job(run: AgentTrainRun, cfg: TriBridConfig | None, *, status: str, message: str) -> AgentTrainRun:
    """Terminal transition for a run that never reached (or no longer has) an in-process job."""
    now = datetime.now(UTC)
    run.status = status  # type: ignore[assignment]
    run.completed_at = now
    if cfg is not None:
        run = _attach_lineage(run, cfg)
    _save_run(run)
    _mlflow_terminate_for_run(run, cfg, status="KILLED" if status == "cancelled" else "FAILED")
    _append_event(
        run.run_id,
        AgentTrainMetricEvent(
            type="state" if status == "cancelled" else "error",
            ts=now,
            run_id=run.run_id,
            status=run.status,
            message=message,
        ),
    )
    _append_event(run.run_id, AgentTrainMetricEvent(type="complete", ts=now, run_id=run.run_id, status=run.status))
    _train_start_guard.pop(str(run.repo_id or "").strip(), None)
    return run


def _flyte_run_needs_reconcile(run: AgentTrainRun) -> bool:
    if str(run.workflow_backend or "") != "flyte" or not str(run.workflow_run_id or "").strip():
        return False
    if str(run.status) in {"queued", "running"}:
        return True
    # Terminal locally: keep mirroring the Flyte phase until Flyte is terminal too.
    return str(run.workflow_phase or "") not in FLYTE_TERMINAL_PHASES


def _fetch_flyte_state(run: AgentTrainRun):
    """Blocking flyteadmin probe for a Flyte-owned run. Call via asyncio.to_thread.

    Returns the FlyteExecutionState, or None if config is missing or the admin
    is transiently unreachable (never invents a phase).
    """
    execution_name = str(run.workflow_run_id or "").strip()
    if not execution_name:
        return None
    cfg = _cfg_from_run_snapshot(run)
    if cfg is None:
        return None
    admin_url, project, domain = _flyte_scope(cfg)
    locally_terminal = str(run.status) in _TERMINAL_RUN_STATUSES
    try:
        return FlyteAdminClient(admin_url, timeout_s=1.0 if locally_terminal else 2.0).get_execution(
            project, domain, execution_name
        )
    except FlyteUnavailableError:
        return None


async def _refresh_flyte_run(run: AgentTrainRun) -> AgentTrainRun:
    """Mirror the live Flyte phase onto a Flyte-owned run without blocking the event loop.

    The network probe runs in a worker thread; all run mutations (save, events,
    cancel-event signalling, finalization) happen back on the loop thread so
    asyncio.Event.set() stays loop-safe.
    """
    execution_name = str(run.workflow_run_id or "").strip()
    if not execution_name:
        return run
    interval = (
        _FLYTE_RECONCILE_TERMINAL_INTERVAL_S
        if str(run.status) in _TERMINAL_RUN_STATUSES
        else _FLYTE_RECONCILE_INTERVAL_S
    )
    now_mono = time.monotonic()
    if now_mono - _flyte_reconcile_at.get(run.run_id, 0.0) < interval:
        return run
    _flyte_reconcile_at[run.run_id] = now_mono

    state = await asyncio.to_thread(_fetch_flyte_state, run)
    if state is None:
        return run
    return _apply_flyte_state(run, state)


def _apply_flyte_state(run: AgentTrainRun, state) -> AgentTrainRun:
    """Apply a fetched Flyte execution phase to a run. Loop-thread only."""
    execution_name = str(run.workflow_run_id or "").strip()
    locally_terminal = str(run.status) in _TERMINAL_RUN_STATUSES

    if state.phase != str(run.workflow_phase or ""):
        run.workflow_phase = state.phase
        _save_run(run)
        if not locally_terminal:
            # The event log ends with the run's "complete" event; after that the
            # phase is mirrored on the run record only.
            _append_event(
                run.run_id,
                AgentTrainMetricEvent(
                    type="log",
                    ts=datetime.now(UTC),
                    run_id=run.run_id,
                    message=f"Flyte execution {execution_name} phase: {state.phase}",
                ),
            )
    if locally_terminal:
        return run

    cfg = _cfg_from_run_snapshot(run)
    ended_by_flyte: tuple[str, str] | None = None
    if state.phase in FLYTE_ABORT_PHASES:
        ended_by_flyte = (
            "cancelled",
            f"Flyte execution {execution_name} was aborted"
            + (f": {state.abort_cause}" if state.abort_cause else "."),
        )
    elif state.phase in FLYTE_FAILURE_PHASES:
        ended_by_flyte = (
            "failed",
            f"Flyte execution {execution_name} ended {state.phase}"
            + (f": {state.error_message}" if state.error_message else "."),
        )
    elif state.phase == "SUCCEEDED":
        # The task only succeeds after this API reported a completed run, so a
        # non-terminal local record here is an inconsistency, not a success.
        ended_by_flyte = (
            "failed",
            f"Flyte execution {execution_name} SUCCEEDED while the host run was still {run.status}; "
            "refusing to infer a completed training run.",
        )
    if ended_by_flyte is None:
        return run

    status, message = ended_by_flyte
    if run.run_id in _train_tasks:
        _train_cancel_outcomes[run.run_id] = (status, message)
        cancel_event = _train_cancel_events.get(run.run_id)
        if cancel_event is not None:
            cancel_event.set()
        return run
    return _finalize_run_without_job(run, cfg, status=status, message=message)


def _attach_lineage(run: AgentTrainRun, cfg: Any, *, promoted: bool = False) -> AgentTrainRun:
    repo_id = str(run.repo_id)
    model_ref = _capture_model_artifact_ref(run.run_id, repo_id)
    if model_ref is not None:
        run.model_artifact_ref = model_ref
    if isinstance(cfg, TriBridConfig):
        run = _apply_run_control_plane_metadata(run, cfg)
    try:
        dataset_rows = [row.model_dump(mode="json", by_alias=True) for row in _load_dataset(corpus_id=repo_id)]
    except Exception:
        dataset_rows = []
    run_version = capture_training_run_version(
        kind="agent_train_run",
        run_payload=run.model_dump(mode="json", by_alias=True),
        repo_id=repo_id,
        payload_extras={
            "model_artifact_ref": model_ref.model_dump(mode="json", by_alias=True) if model_ref is not None else None,
            "promotion": {"promoted": bool(promoted)},
        },
    )
    bundle, _aliases = attach_refs_to_current_bundle(
        repo_id=repo_id,
        cfg=cfg,
        dataset_rows=dataset_rows,
        dataset_path=str(_dataset_path_for_corpus(repo_id)),
        agent_train_runs=[make_ref("agent_train_run", run_version.version_id)],
        agent_model_artifacts=[model_ref] if model_ref is not None else [],
        extra_aliases=("promoted",) if promoted else (),
        preserve_attached_refs=True,
    )
    run.lineage_ref = make_ref("agent_train_run", run_version.version_id)
    run.bundle_id = bundle.bundle_id
    if promoted:
        run.promoted_bundle_id = bundle.bundle_id
    return run


def _tail_lines(path: Path, *, max_bytes: int = 65536, max_lines: int = 50) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size <= 0:
                return []
            start = max(0, size - int(max_bytes))
            f.seek(start)
            data = f.read()
    except Exception:
        return []

    try:
        txt = data.decode("utf-8", errors="ignore")
    except Exception:
        return []

    if start > 0:
        nl = txt.find("\n")
        if nl != -1:
            txt = txt[nl + 1 :]
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _read_last_event(run_id: str) -> AgentTrainMetricEvent | None:
    path = _metrics_path(run_id)
    for line in reversed(_tail_lines(path, max_lines=50)):
        try:
            return AgentTrainMetricEvent.model_validate(json.loads(line))
        except Exception:
            continue
    return None


_train_tasks: dict[str, asyncio.Task[None]] = {}
_train_cancel_events: dict[str, asyncio.Event] = {}
_train_start_guard: dict[str, tuple[str, datetime]] = {}
_TRAIN_START_GRACE = timedelta(seconds=2)


def _mark_train_start_guard(corpus_id: str, run_id: str, *, at: datetime | None = None) -> None:
    """Remember a just-started run long enough to block rapid duplicate starts."""
    _train_start_guard[str(corpus_id or "").strip()] = (run_id, at or datetime.now(UTC))


def _allocate_run_id(repo_id: str, started_at: datetime) -> str:
    base = f"{repo_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_id = base
    n = 0
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    while (_RUNS_DIR / run_id).exists():
        n += 1
        run_id = f"{base}__{n}"
    return run_id


def _maybe_reconcile_run(run: AgentTrainRun) -> AgentTrainRun:
    if run.status != "running":
        return run

    last = _read_last_event(run.run_id)
    now = datetime.now(UTC)

    terminal = str(getattr(last, "status", "") or "").strip().lower()
    if getattr(last, "type", None) == "complete" and terminal in {"completed", "failed", "cancelled"}:
        run.status = terminal  # type: ignore[assignment]
        if run.completed_at is None:
            run.completed_at = getattr(last, "ts", None) or now
        _save_run(run)
        return run

    # Orphaned run after backend restart: mark cancelled after long inactivity.
    if run.run_id not in _train_tasks:
        last_ts = getattr(last, "ts", None) if last is not None else None
        anchor = last_ts or run.started_at
        try:
            idle_secs = float((now - anchor).total_seconds())
        except Exception:
            idle_secs = 0.0
        if idle_secs >= 2 * 60 * 60:
            run.status = "cancelled"
            run.completed_at = now
            _save_run(run)
            _append_event(
                run.run_id,
                AgentTrainMetricEvent(
                    type="error",
                    ts=now,
                    run_id=run.run_id,
                    status=run.status,
                    message="Reconciled orphaned run (no active task; likely backend restart).",
                ),
            )
            _append_event(run.run_id, AgentTrainMetricEvent(type="complete", ts=now, run_id=run.run_id, status=run.status))
    return run


def _load_run(run_id: str) -> AgentTrainRun:
    path = _run_json_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"run_id={run_id} not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read agent train run: {e}") from e
    run = AgentTrainRun.model_validate(raw)
    run = _maybe_reconcile_run(run)
    cfg = _cfg_from_run_snapshot(run)
    if cfg is not None:
        run = _apply_run_control_plane_metadata(run, cfg)
    return run


def _save_run(run: AgentTrainRun) -> None:
    path = _run_json_path(run.run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = run.model_dump(mode="json", by_alias=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_event(run_id: str, event: AgentTrainMetricEvent) -> None:
    path = _metrics_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = event.model_dump(mode="json", by_alias=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _load_events(run_id: str, limit: int | None = None) -> list[AgentTrainMetricEvent]:
    path = _metrics_path(run_id)
    if not path.exists():
        return []
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return []
    if limit is not None and limit > 0:
        lines = lines[-limit:]
    out: list[AgentTrainMetricEvent] = []
    for line in lines:
        try:
            out.append(AgentTrainMetricEvent.model_validate(json.loads(line)))
        except Exception:
            continue
    return out


def _active_run_id_for_corpus(corpus_id: str) -> str | None:
    cid = str(corpus_id or "").strip()
    if not cid:
        return None
    guard = _train_start_guard.get(cid)
    if guard:
        run_id, started_at = guard
        try:
            run = _load_run(run_id)
            if str(run.status) == "completed":
                _train_start_guard.pop(cid, None)
            elif datetime.now(UTC) - started_at <= _TRAIN_START_GRACE:
                return run_id
        except Exception:
            if datetime.now(UTC) - started_at <= _TRAIN_START_GRACE:
                return run_id
            _train_start_guard.pop(cid, None)

    prefix = f"{cid}__"
    try:
        entries = [p for p in _RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    except Exception:
        return None
    entries.sort(key=lambda p: p.name, reverse=True)
    for entry in entries:
        try:
            run = _load_run(entry.name)
        except Exception:
            continue
        if str(run.status) in {"queued", "running"}:
            return str(run.run_id)
    return None


def _request_train_run_cancel(*, run_id: str, reason: str) -> bool:
    cancel_event = _train_cancel_events.get(run_id)
    if cancel_event is not None:
        cancel_event.set()

    if run_id in _train_tasks:
        return True

    try:
        run = _load_run(run_id)
    except HTTPException:
        return False
    if run.status != "running":
        return True

    now = datetime.now(UTC)
    run.status = "cancelled"
    run.completed_at = now
    _save_run(run)
    _append_event(
        run_id,
        AgentTrainMetricEvent(type="state", ts=now, run_id=run_id, status="cancelled", message=str(reason)),
    )
    _append_event(run_id, AgentTrainMetricEvent(type="complete", ts=now, run_id=run_id, status="cancelled"))
    return True


def _resolve_expected_path(*, corpus_root: Path, path_str: str) -> Path | None:
    p = Path(str(path_str or "").strip())
    if not str(p):
        return None
    try:
        root = corpus_root.resolve()
    except Exception:
        root = corpus_root.absolute()

    try:
        if p.is_absolute():
            resolved = p.resolve()
        else:
            resolved = (corpus_root / p).resolve()
    except Exception:
        return None

    try:
        resolved.relative_to(root)
    except Exception:
        return None
    return resolved


def _read_text(path: Path, *, max_chars: int) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if max_chars <= 0:
        return ""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"Dataset not found: {path}")
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            ln = line.strip()
            if not ln:
                continue
            try:
                obj = json.loads(ln)
            except Exception:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def _load_json_any(path: Path) -> Any:
    if not path.exists():
        raise RuntimeError(f"Dataset not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_messages(messages: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(messages, list):
        return out
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": role, "content": str(content)})
    return out


async def _load_training_messages(
    *,
    cfg: Any,
    corpus_id: str,
    dataset_path: Path,
) -> list[list[dict[str, Any]]]:
    """Load training examples from either:

    - Format A: JSONL items { "messages": [ {role, content}, ... ] }
    - Format B: EvalDatasetItem-like entries {question, expected_paths, expected_answer}
    """

    if dataset_path.suffix.lower() == ".jsonl":
        rows = _load_jsonl(dataset_path)
    else:
        raw = _load_json_any(dataset_path)
        rows = raw if isinstance(raw, list) else []

    # Detect format.
    has_messages = any(isinstance(r, dict) and isinstance(r.get("messages"), list) for r in rows)
    has_questions = any(isinstance(r, dict) and isinstance(r.get("question"), str) for r in rows)

    examples: list[list[dict[str, Any]]] = []
    if has_messages:
        for r in rows:
            if not isinstance(r, dict):
                continue
            msgs = _normalize_messages(r.get("messages"))
            if msgs:
                examples.append(msgs)
        return examples

    if not has_questions:
        return []

    # Resolve corpus root for expected_paths materialization.
    pg = PostgresClient(cfg.indexing.postgres_url)
    await pg.connect()
    try:
        corpus = await pg.get_corpus(corpus_id)
        if corpus is None:
            raise RuntimeError(f"Corpus not found: {corpus_id}")
    finally:
        await pg.disconnect()

    corpus_root = Path(str(corpus.get("path") or "")).expanduser()
    if not corpus_root.is_absolute():
        corpus_root = PROJECT_ROOT / corpus_root

    snippet_chars = int(getattr(cfg.reranking, "rerank_input_snippet_chars", 700) or 700)

    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            item = EvalDatasetItem.model_validate(r)
        except Exception:
            continue
        if not (item.expected_answer or "").strip():
            continue

        rag_chunks: list[ChunkMatch] = []
        for p in list(item.expected_paths or [])[:20]:
            resolved = _resolve_expected_path(corpus_root=corpus_root, path_str=str(p))
            if resolved is None:
                continue
            txt = _read_text(resolved, max_chars=int(snippet_chars))
            if not txt.strip():
                continue
            end_line = max(1, txt.count("\n") + 1)
            rag_chunks.append(
                ChunkMatch(
                    chunk_id=f"{resolved.name}:1-{end_line}",
                    content=txt,
                    file_path=str(Path(p).as_posix()),
                    start_line=1,
                    end_line=end_line,
                    language=None,
                    score=1.0,
                    source="vector",
                    metadata={},
                )
            )

        context_text = format_context_for_llm(rag_chunks=rag_chunks, recall_chunks=[])
        system_prompt = get_system_prompt(
            has_rag_context=True,
            has_recall_context=False,
            config=cfg.chat,
        )
        prompt = system_prompt if not context_text else f"{system_prompt}\n\n## Context\n{context_text}"

        examples.append(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(item.question or "")},
                {"role": "assistant", "content": str(item.expected_answer or "")},
            ]
        )

    return examples


def _primary_from_metrics(metrics: dict[str, float] | None) -> float | None:
    if not metrics:
        return None
    v = metrics.get("eval_loss")
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


async def _run_train_job(*, run_id: str, corpus_id: str, cancel_event: asyncio.Event | None = None) -> None:
    try:
        run = _load_run(run_id)
    except Exception:
        return

    def _emit_log(msg: str) -> None:
        _append_event(run_id, AgentTrainMetricEvent(type="log", ts=datetime.now(UTC), run_id=run_id, message=str(msg)))

    def _is_cancel_requested() -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def _raise_if_cancelled(message: str = "Training cancelled by user.") -> None:
        if _is_cancel_requested():
            raise TrainingCancelledError(message)

    baseline_primary: float | None = None
    best_primary: float | None = None
    best_step: int | None = None
    best_ts: datetime | None = None
    primary_series: list[float] = []
    final_primary: float | None = None

    cfg: Any | None = None
    mlflow_client: MlflowClient | None = None
    mlflow_handle: MlflowRunHandle | None = None
    mlflow_warned = False

    def _mlflow_log_metrics(metrics: dict[str, float] | None, *, step: int | None) -> None:
        nonlocal mlflow_warned
        if mlflow_client is None or mlflow_handle is None or not metrics:
            return
        try:
            for key, value in metrics.items():
                if key in {"train_loss", "eval_loss"} and math.isfinite(float(value)):
                    mlflow_client.log_metric(mlflow_handle.run_id, key, float(value), step=step)
        except MlflowUnavailableError as exc:
            if not mlflow_warned:
                mlflow_warned = True
                _emit_log(f"MLflow tracking degraded mid-run (metrics no longer forwarded): {exc}")

    def _mlflow_finish(status: str, *, manifest: dict[str, Any] | None = None) -> None:
        if mlflow_client is None or mlflow_handle is None:
            return
        try:
            if manifest is not None:
                mlflow_client.log_json_artifact(mlflow_handle, name="ragweld_run_manifest.json", payload=manifest)
            mlflow_client.set_terminated(mlflow_handle.run_id, status=status)
        except MlflowUnavailableError as exc:
            _emit_log(f"MLflow run could not be finalized ({status}): {exc}")

    try:
        cfg = await load_scoped_config(repo_id=corpus_id)
        _raise_if_cancelled()

        if str(run.tracking_backend or "local") == "mlflow" and str(run.tracking_run_id or "").strip():
            try:
                mlflow_client = MlflowClient(str(cfg.training.ragweld_agent_mlflow_tracking_url or ""))
                experiment_id = mlflow_client.ensure_experiment(
                    str(cfg.training.ragweld_agent_mlflow_experiment_name or "ragweld-learning-agent")
                )
                mlflow_handle = MlflowRunHandle(
                    tracking_url=mlflow_client.tracking_url,
                    experiment_id=experiment_id,
                    run_id=str(run.tracking_run_id),
                )
                _emit_log(f"MLflow tracking active: {mlflow_handle.run_url}")
            except MlflowUnavailableError as exc:
                mlflow_client = None
                mlflow_handle = None
                _emit_log(f"MLflow tracking unavailable at job start: {exc}")

        if not mlx_is_available():
            raise RuntimeError("MLX is not available on this platform (install mlx + mlx-lm)")

        # Determine dataset path precedence.
        # 1) request override (stored in run.config as RAGWELD_AGENT_TRAIN_DATASET_PATH, if present)
        # 2) training.ragweld_agent_train_dataset_path
        # 3) evaluation.eval_dataset_path (if non-default/non-empty)
        # 4) corpus-scoped dataset path (data/eval_datasets/<corpus>.json)
        # If the legacy default evaluation path is configured but missing, fall through to corpus dataset.
        req_override = ""
        try:
            req_override = str(getattr(run, "config", {}).get("RAGWELD_AGENT_TRAIN_DATASET_PATH") or "").strip()
        except Exception:
            req_override = ""
        cfg_default = str(getattr(cfg.training, "ragweld_agent_train_dataset_path", "") or "").strip()
        eval_default = str(getattr(cfg.evaluation, "eval_dataset_path", "") or "").strip()

        dataset_path, ds_messages = _resolve_training_dataset_path(
            corpus_id=corpus_id,
            request_override=req_override,
            config_default=cfg_default,
            evaluation_default=eval_default,
        )
        for msg in ds_messages:
            _emit_log(msg)

        if dataset_path is None:
            tried = ", ".join(
                str(_resolve_path(x))
                for x in [req_override, cfg_default, eval_default]
                if str(x or "").strip()
            )
            tried = ", ".join([t for t in [tried, str(_dataset_path_for_corpus(corpus_id))] if t])
            raise RuntimeError(f"No readable training dataset found. Tried: {tried}")

        examples = await _load_training_messages(cfg=cfg, corpus_id=corpus_id, dataset_path=dataset_path)
        if not examples:
            raise RuntimeError(f"No usable training examples found in dataset: {dataset_path}")

        # Deterministic split for eval_loss.
        train_examples, dev_examples = deterministic_split(examples, dev_split=0.1, seed=0)
        if len(examples) >= 2 and not dev_examples:
            dev_examples = [train_examples.pop(0)]

        model_artifact_dir = _run_dir(run_id) / "model"
        model_artifact_dir.parent.mkdir(parents=True, exist_ok=True)

        # Baseline eval (optional, used for auto-promote gating).
        active_dir_cfg = str(getattr(cfg.training, "ragweld_agent_model_path", "") or "").strip()
        active_dir = _resolve_path(active_dir_cfg) if active_dir_cfg else None
        promote_if_improves = bool(getattr(cfg.training, "ragweld_agent_promote_if_improves", False))
        if promote_if_improves and dev_examples and active_dir is not None and active_dir.exists():
            try:
                baseline_primary = await asyncio.to_thread(
                    evaluate_mlx_qwen3_agent_loss,
                    base_model=str(getattr(cfg.training, "ragweld_agent_base_model", "") or ""),
                    adapter_dir=active_dir,
                    messages=dev_examples,
                    batch_size=max(1, int(run.batch_size)),
                    max_length=int(run.max_length),
                    lora_rank=int(getattr(cfg.training, "ragweld_agent_lora_rank", 16)),
                    lora_alpha=float(getattr(cfg.training, "ragweld_agent_lora_alpha", 32.0)),
                    lora_dropout=float(getattr(cfg.training, "ragweld_agent_lora_dropout", 0.05)),
                    lora_target_modules=list(getattr(cfg.training, "ragweld_agent_lora_target_modules", []) or []),
                    should_stop=_is_cancel_requested,
                )
                if baseline_primary is not None and math.isfinite(float(baseline_primary)):
                    _emit_log(f"Baseline eval_loss={baseline_primary:.6f} on held-out dev split.")
                else:
                    baseline_primary = None
            except Exception as e:
                _emit_log(f"Baseline eval failed; treating baseline as unknown. error={e}")
                baseline_primary = None

        def _emit(event_type: str, payload: dict[str, Any]) -> None:
            nonlocal best_primary, best_step, best_ts, primary_series, final_primary
            ts = datetime.now(UTC)
            if event_type == "log":
                msg = str(payload.get("message") or "").strip()
                if msg:
                    _append_event(run_id, AgentTrainMetricEvent(type="log", ts=ts, run_id=run_id, message=msg))
                return
            if event_type == "progress":
                progress_metrics: dict[str, float] | None = None
                raw_metrics = payload.get("metrics")
                if isinstance(raw_metrics, dict):
                    parsed_progress_metrics: dict[str, float] = {}
                    for k, v in raw_metrics.items():
                        try:
                            parsed_progress_metrics[str(k)] = float(v)
                        except Exception:
                            continue
                    progress_metrics = parsed_progress_metrics or None
                _append_event(
                    run_id,
                    AgentTrainMetricEvent(
                        type="progress",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        percent=float(payload.get("percent") or 0.0) or None,
                        message=str(payload.get("message") or ""),
                        metrics=progress_metrics,
                    ),
                )
                return
            if event_type == "metrics":
                raw = payload.get("metrics") or {}
                metrics_map: dict[str, float] | None = None
                if isinstance(raw, dict):
                    parsed_metrics: dict[str, float] = {}
                    for k, v in raw.items():
                        try:
                            parsed_metrics[str(k)] = float(v)
                        except Exception:
                            continue
                    metrics_map = parsed_metrics or None

                _mlflow_log_metrics(metrics_map, step=int(payload.get("step") or 0) or None)
                pv = _primary_from_metrics(metrics_map)
                if pv is not None:
                    primary_series.append(float(pv))
                    final_primary = float(pv)
                    if best_primary is None or pv < best_primary:
                        best_primary = float(pv)
                        best_step = int(payload.get("step") or 0) or None
                        best_ts = ts

                _append_event(
                    run_id,
                    AgentTrainMetricEvent(
                        type="metrics",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        metrics=metrics_map,
                    ),
                )
                return
            if event_type == "telemetry":
                proj_x_raw = payload.get("proj_x")
                proj_y_raw = payload.get("proj_y")
                loss_raw = payload.get("loss")
                lr_raw = payload.get("lr")
                grad_norm_raw = payload.get("grad_norm")
                param_norm_raw = payload.get("param_norm")
                update_norm_raw = payload.get("update_norm")
                step_time_ms_raw = payload.get("step_time_ms")
                sample_count_raw = payload.get("sample_count")
                _append_event(
                    run_id,
                    AgentTrainMetricEvent(
                        type="telemetry",
                        ts=ts,
                        run_id=run_id,
                        step=int(payload.get("step") or 0) or None,
                        epoch=float(payload.get("epoch") or 0.0) or None,
                        proj_x=float(proj_x_raw) if proj_x_raw is not None else None,
                        proj_y=float(proj_y_raw) if proj_y_raw is not None else None,
                        loss=float(loss_raw) if loss_raw is not None else None,
                        lr=float(lr_raw) if lr_raw is not None else None,
                        grad_norm=float(grad_norm_raw) if grad_norm_raw is not None else None,
                        param_norm=float(param_norm_raw) if param_norm_raw is not None else None,
                        update_norm=float(update_norm_raw) if update_norm_raw is not None else None,
                        step_time_ms=float(step_time_ms_raw) if step_time_ms_raw is not None else None,
                        sample_count=int(sample_count_raw) if sample_count_raw is not None else None,
                    ),
                )
                return

        # Mark run as running (in case a previous partial state left it inconsistent).
        _raise_if_cancelled()
        run.status = "running"
        _save_run(run)
        _append_event(run_id, AgentTrainMetricEvent(type="state", ts=datetime.now(UTC), run_id=run_id, status=run.status))

        # Train (runs in thread; emits progress/metrics/telemetry into metrics.jsonl).
        _raise_if_cancelled()
        await asyncio.to_thread(
            train_mlx_qwen3_agent,
            run_id=run_id,
            base_model=str(getattr(cfg.training, "ragweld_agent_base_model", "") or ""),
            output_dir=model_artifact_dir,
            train_messages=train_examples,
            dev_messages=dev_examples,
            epochs=int(run.epochs),
            batch_size=int(run.batch_size),
            gradient_accumulation_steps=int(getattr(cfg.training, "ragweld_agent_grad_accum_steps", 1) or 1),
            lr=float(run.lr),
            warmup_ratio=float(run.warmup_ratio),
            max_length=int(run.max_length),
            seed=0,
            lora_rank=int(getattr(cfg.training, "ragweld_agent_lora_rank", 16)),
            lora_alpha=float(getattr(cfg.training, "ragweld_agent_lora_alpha", 32.0)),
            lora_dropout=float(getattr(cfg.training, "ragweld_agent_lora_dropout", 0.05)),
            lora_target_modules=list(getattr(cfg.training, "ragweld_agent_lora_target_modules", []) or []),
            telemetry_interval_steps=int(getattr(cfg.training, "ragweld_agent_telemetry_interval_steps", 2) or 2),
            emit=_emit,
            should_stop=_is_cancel_requested,
        )

        _raise_if_cancelled()

        # Auto-promote trained artifact to active ragweld agent path when configured.
        eps = float(getattr(cfg.training, "ragweld_agent_promote_epsilon", 0.0) or 0.0)
        should_promote = True
        if promote_if_improves and baseline_primary is not None and final_primary is not None:
            should_promote = bool(final_primary < (baseline_primary - eps))

        if active_dir is not None and should_promote:
            _atomic_copy_dir(model_artifact_dir, active_dir)
            # Ensure in-process ragweld model reloads the adapter immediately.
            await clear_ragweld_cache(adapter_dir=str(active_dir_cfg))
            _emit_log(
                f"Promoted trained artifact to {active_dir_cfg} (backend=mlx_qwen3). "
                f"Run artifact preserved at {model_artifact_dir}."
            )
        elif active_dir is not None and not should_promote:
            _emit_log(
                f"Did not promote: final_eval_loss={final_primary} baseline_eval_loss={baseline_primary} eps={eps}. "
                f"Run artifact preserved at {model_artifact_dir}."
            )

        # Populate summary (minimize).
        run.summary.primary_goal = "minimize"
        run.summary.primary_metric_best = float(best_primary) if best_primary is not None else None
        run.summary.primary_metric_final = float(final_primary) if final_primary is not None else None
        run.summary.best_step = int(best_step or 0) or None
        if best_ts is not None:
            run.summary.time_to_best_secs = float((best_ts - run.started_at).total_seconds())
        tail = primary_series[-5:]
        if tail:
            mean = sum(tail) / len(tail)
            var = sum((x - mean) ** 2 for x in tail) / len(tail)
            run.summary.stability_stddev = float(math.sqrt(var))

        run.status = "completed"
        run.completed_at = datetime.now(UTC)
        run = _attach_lineage(run, cfg, promoted=bool(active_dir is not None and should_promote))
        _save_run(run)
        _mlflow_finish(
            "FINISHED",
            manifest={
                "run_id": run.run_id,
                "corpus_id": run.repo_id,
                "status": run.status,
                "primary_metric": run.primary_metric,
                "primary_metric_best": run.summary.primary_metric_best,
                "primary_metric_final": run.summary.primary_metric_final,
                "model_artifact_ref": (
                    run.model_artifact_ref.model_dump(mode="json", by_alias=True)
                    if run.model_artifact_ref is not None
                    else None
                ),
                "input_bundle_id": run.input_bundle_id,
                "execution_backend": run.execution_backend,
                "workflow_backend": run.workflow_backend,
            },
        )
        _append_event(run_id, AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status=run.status))
    except TrainingCancelledError:
        outcome_status, outcome_message = _train_cancel_outcomes.pop(run_id, ("cancelled", "Training cancelled."))
        try:
            run = _load_run(run_id)
            run.status = outcome_status  # type: ignore[assignment]
            run.completed_at = datetime.now(UTC)
            if cfg is not None:
                run = _attach_lineage(run, cfg)
            _save_run(run)
        except Exception:
            pass
        _mlflow_finish("KILLED" if outcome_status == "cancelled" else "FAILED")
        _append_event(
            run_id,
            AgentTrainMetricEvent(
                type="state" if outcome_status == "cancelled" else "error",
                ts=datetime.now(UTC),
                run_id=run_id,
                status=outcome_status,  # type: ignore[arg-type]
                message=outcome_message,
            ),
        )
        _append_event(
            run_id,
            AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status=outcome_status),  # type: ignore[arg-type]
        )
    except Exception as e:
        try:
            run = _load_run(run_id)
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            if cfg is not None:
                run = _attach_lineage(run, cfg)
            _save_run(run)
        except Exception:
            pass
        _mlflow_finish("FAILED")
        _append_event(
            run_id,
            AgentTrainMetricEvent(
                type="error",
                ts=datetime.now(UTC),
                run_id=run_id,
                status="failed",
                message=str(e),
            ),
        )
        _append_event(run_id, AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status="failed"))
    finally:
        _train_tasks.pop(run_id, None)
        _train_cancel_events.pop(run_id, None)
        _train_cancel_outcomes.pop(run_id, None)
        _train_start_guard.pop(str(corpus_id or "").strip(), None)


def _start_train_job_task(run_id: str, corpus_id: str) -> None:
    if run_id in _train_tasks:
        return
    cancel_event = asyncio.Event()
    _train_cancel_events[run_id] = cancel_event
    _train_tasks[run_id] = asyncio.create_task(_run_train_job(run_id=run_id, corpus_id=corpus_id, cancel_event=cancel_event))


@router.get("/agent/train/profile", response_model=OkResponse)
async def get_train_profile() -> OkResponse:
    # Minimal endpoint for Studio parity; current Agent Studio does not need a profile object.
    return OkResponse(ok=True)


@router.get("/agent/train/control-plane/status", response_model=AgentTrainControlPlaneStatusResponse)
async def get_train_control_plane_status(
    repo: str | None = Query(default=None, description="Optional corpus_id to scope config"),
    corpus_id: str | None = Query(default=None, description="Alias for repo"),
    repo_id: str | None = Query(default=None, description="Alias for corpus_id"),
) -> AgentTrainControlPlaneStatusResponse:
    scope_id = (repo or corpus_id or repo_id or "").strip() or None
    try:
        cfg = await load_scoped_config(repo_id=scope_id)
    except CorpusNotFoundError:
        cfg = await load_scoped_config(repo_id=None)
    return await build_agent_control_plane_status(cfg)


@router.get("/agent/train/runs", response_model=AgentTrainRunsResponse)
async def list_train_runs(
    corpus_id: str | None = Query(default=None, description="Corpus identifier for corpus scope"),
    scope: Literal["corpus", "all"] = Query(default="corpus"),
    limit: int = Query(default=50, ge=1, le=200),
) -> AgentTrainRunsResponse:
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)

    if scope == "corpus":
        if not corpus_id:
            raise HTTPException(status_code=422, detail="Missing corpus_id")
        prefix = f"{corpus_id}__"
        candidates = [p for p in _RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith(prefix)]
    else:
        candidates = [p for p in _RUNS_DIR.iterdir() if p.is_dir()]

    metas: list[AgentTrainRunMeta] = []
    for run_dir in candidates:
        path = run_dir / "run.json"
        if not path.exists():
            continue
        try:
            run = AgentTrainRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
            run = _maybe_reconcile_run(run)
        except Exception:
            continue
        if _flyte_run_needs_reconcile(run):
            run = await _refresh_flyte_run(run)
        metas.append(
            AgentTrainRunMeta(
                run_id=run.run_id,
                repo_id=run.repo_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                primary_metric_best=run.summary.primary_metric_best,
                primary_metric_final=run.summary.primary_metric_final,
                workflow_backend=run.workflow_backend,
                tracking_backend=run.tracking_backend,
                execution_backend=run.execution_backend,
                workflow_run_id=run.workflow_run_id,
                workflow_phase=run.workflow_phase,
                tracking_run_id=run.tracking_run_id,
                bundle_id=run.bundle_id,
                lineage_ref=run.lineage_ref,
            )
        )

    metas.sort(key=lambda m: m.started_at, reverse=True)
    return AgentTrainRunsResponse(ok=True, runs=metas[: int(limit)])


@router.post("/agent/train/start", response_model=AgentTrainStartResponse)
async def start_train_run(request: AgentTrainStartRequest) -> AgentTrainStartResponse:
    corpus_id = request.repo_id
    active_run_id = _active_run_id_for_corpus(corpus_id)
    if active_run_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"An agent training run is already active for corpus_id={corpus_id}: run_id={active_run_id}. "
                "Cancel the active run before starting a new one."
            ),
        )

    cfg = await load_scoped_config(repo_id=corpus_id)

    workflow_backend = str(cfg.training.ragweld_agent_workflow_backend or "local").strip().lower()
    tracking_backend = str(cfg.training.ragweld_agent_tracking_backend or "local").strip().lower()
    execution_backend = str(cfg.training.ragweld_agent_backend or "mlx_qwen3").strip().lower()

    # Fail closed on configured-but-unavailable target backends. No silent
    # substitution back to the local lane.
    flyte_client: FlyteAdminClient | None = None
    flyte_launch_plan: FlyteLaunchPlanRef | None = None
    flyte_callback_url = ""
    if workflow_backend == "flyte":
        flyte_admin_url, flyte_project, flyte_domain = _flyte_scope(cfg)
        flyte_launchplan_name = str(cfg.training.ragweld_agent_flyte_launchplan or "").strip()
        flyte_callback_url = str(cfg.training.ragweld_agent_flyte_callback_base_url or "").strip().rstrip("/")
        flyte_missing = [
            name
            for name, value in (
                ("training.ragweld_agent_flyte_admin_base_url", flyte_admin_url),
                ("training.ragweld_agent_flyte_project", flyte_project),
                ("training.ragweld_agent_flyte_domain", flyte_domain),
                ("training.ragweld_agent_flyte_launchplan", flyte_launchplan_name),
                ("training.ragweld_agent_flyte_callback_base_url", flyte_callback_url),
            )
            if not value
        ]
        if flyte_missing:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "workflow_backend_unavailable",
                    "backend": "flyte",
                    "message": f"Flyte orchestration is selected but required config is empty: {', '.join(flyte_missing)}.",
                    "operator_hint": (
                        "Fill the Flyte fields in Training Center (the callback base URL is this API as "
                        "reachable from Flyte task pods), then retry. Ragweld does not fall back to the "
                        "local workflow lane silently."
                    ),
                },
            )

        def _resolve_flyte() -> FlyteLaunchPlanRef:
            client = FlyteAdminClient(flyte_admin_url)
            client.healthcheck()
            return client.resolve_launch_plan(flyte_project, flyte_domain, flyte_launchplan_name)

        try:
            flyte_launch_plan = await asyncio.to_thread(_resolve_flyte)
            flyte_client = FlyteAdminClient(flyte_admin_url)
        except FlyteUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "workflow_backend_unavailable",
                    "backend": "flyte",
                    "message": str(exc),
                    "operator_hint": (
                        "Start the Compose-owned flyte service (./start.sh --with-flyte) and register the "
                        "launch plan with scripts/flyte_register_learning_agent.sh, then retry. Ragweld does "
                        "not fall back to the local workflow lane silently."
                    ),
                },
            ) from exc
    elif workflow_backend != "local":
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workflow_backend_unavailable",
                "backend": workflow_backend,
                "message": f"Unknown workflow backend {workflow_backend!r}.",
                "operator_hint": "Set training.ragweld_agent_workflow_backend to 'local' or 'flyte'.",
            },
        )
    if execution_backend not in {"mlx_qwen3"}:
        import platform as _platform

        raise HTTPException(
            status_code=503,
            detail={
                "code": "execution_backend_unavailable",
                "backend": execution_backend,
                "message": (
                    "Unsloth execution requires an NVIDIA CUDA runtime; this host is "
                    f"{_platform.system().lower()}/{_platform.machine()} (no CUDA device). "
                    "Refusing to substitute the MLX lane silently."
                ),
                "operator_hint": (
                    "Provision a CUDA-capable execution environment for Unsloth, or set "
                    "training.ragweld_agent_backend back to 'mlx_qwen3'."
                ),
            },
        )

    mlflow_handle: MlflowRunHandle | None = None
    if tracking_backend == "mlflow":
        tracking_url = str(cfg.training.ragweld_agent_mlflow_tracking_url or "").strip()
        experiment_name = str(cfg.training.ragweld_agent_mlflow_experiment_name or "").strip()
        try:
            mlflow = MlflowClient(tracking_url)
            experiment_id = await asyncio.to_thread(mlflow.ensure_experiment, experiment_name)
        except MlflowUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "tracking_backend_unavailable",
                    "backend": "mlflow",
                    "message": str(exc),
                    "operator_hint": (
                        "Start the Compose-owned mlflow service (or fix "
                        "training.ragweld_agent_mlflow_tracking_url), then retry. "
                        "Ragweld does not fall back to local tracking silently."
                    ),
                },
            ) from exc

    current_bundle = ensure_current_bundle(
        repo_id=corpus_id,
        cfg=cfg,
        dataset_rows=[row.model_dump(mode="json", by_alias=True) for row in _load_dataset(corpus_id=corpus_id)],
        dataset_path=str(_dataset_path_for_corpus(corpus_id)),
    )

    started_at = datetime.now(UTC)
    run_id = _allocate_run_id(corpus_id, started_at)
    _mark_train_start_guard(corpus_id, run_id, at=started_at)

    # Resolved defaults mirror the reranker Studio knobs (epochs/batch/lr/warmup/max_length).
    run = AgentTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="queued" if workflow_backend == "flyte" else "running",
        started_at=started_at,
        completed_at=None,
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="eval_loss",
        primary_goal="minimize",
        metrics_available=["train_loss", "eval_loss"],
        epochs=int(request.epochs) if request.epochs is not None else int(cfg.training.reranker_train_epochs),
        batch_size=int(request.batch_size) if request.batch_size is not None else int(cfg.training.reranker_train_batch),
        lr=float(request.lr) if request.lr is not None else float(cfg.training.reranker_train_lr),
        warmup_ratio=float(request.warmup_ratio) if request.warmup_ratio is not None else float(cfg.training.reranker_warmup_ratio),
        max_length=int(request.max_length) if request.max_length is not None else int(getattr(cfg.reranking, "tribrid_reranker_maxlen", 512) or 512),
        workflow_backend=workflow_backend,  # type: ignore[arg-type]
        tracking_backend=tracking_backend,  # type: ignore[arg-type]
        execution_backend=execution_backend,
        input_bundle_id=current_bundle.bundle_id,
    )
    if tracking_backend == "mlflow":
        try:
            mlflow_handle = await asyncio.to_thread(
                mlflow.create_run,
                experiment_id,
                run_name=run_id,
                tags={"ragweld.run_id": run_id, "ragweld.corpus_id": corpus_id},
            )
            await asyncio.to_thread(
                mlflow.log_params,
                mlflow_handle.run_id,
                {
                    "epochs": run.epochs,
                    "batch_size": run.batch_size,
                    "lr": run.lr,
                    "warmup_ratio": run.warmup_ratio,
                    "max_length": run.max_length,
                    "execution_backend": run.execution_backend,
                    "corpus_id": corpus_id,
                },
            )
        except MlflowUnavailableError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "tracking_backend_unavailable",
                    "backend": "mlflow",
                    "message": str(exc),
                    "operator_hint": "MLflow became unavailable while opening the run; retry once it is reachable.",
                },
            ) from exc
        run.tracking_run_id = mlflow_handle.run_id
        run.artifacts_uri = f"mlflow-artifacts:/{mlflow_handle.experiment_id}/{mlflow_handle.run_id}/artifacts"

    run = _apply_run_control_plane_metadata(run, cfg)

    # Persist request-level dataset override into the run snapshot so the background
    # job can apply the correct precedence without rereading the request.
    ds_override = str(getattr(request, "dataset_path", "") or "").strip()
    if ds_override:
        run.config["RAGWELD_AGENT_TRAIN_DATASET_PATH"] = ds_override

    # Persist immediately.
    _save_run(run)

    # Create empty metrics.jsonl.
    metrics_path = _metrics_path(run_id)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_path.exists():
        metrics_path.write_text("", encoding="utf-8")

    # First event: record primary metric.
    _append_event(
        run_id,
        AgentTrainMetricEvent(
            type="state",
            ts=started_at,
            run_id=run_id,
            message="Primary metric locked: eval_loss (minimize)",
            status=run.status,
        ),
    )
    if workflow_backend == "flyte" and flyte_client is not None and flyte_launch_plan is not None:
        # Flyte owns the execution lifecycle. The workflow task hands the run
        # back to this API's execute boundary; no in-process job starts here.
        execution_name = new_execution_name()
        try:
            execution_name = await asyncio.to_thread(
                flyte_client.create_execution,
                flyte_launch_plan,
                inputs={
                    "run_id": run_id,
                    "corpus_id": corpus_id,
                    "callback_base_url": flyte_callback_url,
                    "execution_backend": execution_backend,
                },
                execution_name=execution_name,
            )
        except FlyteUnavailableError as exc:
            _finalize_run_without_job(
                run,
                cfg,
                status="failed",
                message=f"Flyte refused to create the execution: {exc}",
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "workflow_backend_unavailable",
                    "backend": "flyte",
                    "message": f"Flyte refused to create the execution: {exc}",
                    "operator_hint": "Inspect the Flyte control plane (flyteadmin logs / console) and retry the launch.",
                },
            ) from exc
        run.workflow_run_id = execution_name
        run.workflow_phase = "QUEUED"
        run = _apply_run_control_plane_metadata(run, cfg)
        _save_run(run)
        _append_event(
            run_id,
            AgentTrainMetricEvent(
                type="log",
                ts=datetime.now(UTC),
                run_id=run_id,
                message=(
                    f"Flyte execution {execution_name} created in {flyte_launch_plan.project}/{flyte_launch_plan.domain} "
                    f"(launch plan {flyte_launch_plan.name} v{flyte_launch_plan.version}); waiting for the workflow task "
                    "to hand the run to the execute boundary."
                ),
            ),
        )
        _mark_train_start_guard(corpus_id, run_id)
        return AgentTrainStartResponse(ok=True, run_id=run_id)

    _append_event(
        run_id,
        AgentTrainMetricEvent(
            type="log",
            ts=datetime.now(UTC),
            run_id=run_id,
            message="Queued background training job.",
        ),
    )

    _start_train_job_task(run_id, corpus_id)

    # Refresh the guard at queue time so rapid follow-up requests still see an
    # active run even when the background task fails immediately after start.
    _mark_train_start_guard(corpus_id, run_id)

    return AgentTrainStartResponse(ok=True, run_id=run_id)


@router.post("/agent/train/run/{run_id}/execute", response_model=AgentTrainExecuteResponse)
async def execute_train_run(run_id: str, request: AgentTrainExecuteRequest) -> AgentTrainExecuteResponse:
    """Workflow-side hand-off: the Flyte task asks this API to execute a queued run.

    Only a Flyte-owned run whose execution identifier matches may be executed
    here; the call is idempotent while the run is running.
    """
    run = _load_run(run_id)
    if str(run.workflow_backend or "") != "flyte":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workflow_backend_mismatch",
                "message": f"Run {run_id} is owned by the {run.workflow_backend} workflow lane, not Flyte.",
            },
        )
    expected = str(run.workflow_run_id or "").strip()
    if not expected or request.workflow_run_id.strip() != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workflow_run_mismatch",
                "message": f"Run {run_id} belongs to Flyte execution {expected or '<none>'}, not {request.workflow_run_id}.",
            },
        )
    if str(run.status) in _TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "run_terminal",
                "status": str(run.status),
                "message": f"Run {run_id} already ended with status={run.status}.",
            },
        )
    if str(run.status) == "running" or run_id in _train_tasks:
        return AgentTrainExecuteResponse(ok=True, run_id=run_id, status="running", workflow_run_id=expected)

    now = datetime.now(UTC)
    run.status = "running"
    _save_run(run)
    _append_event(
        run_id,
        AgentTrainMetricEvent(
            type="state",
            ts=now,
            run_id=run_id,
            status="running",
            message=f"Flyte execution {expected} handed the run to the host execute boundary; training starts now.",
        ),
    )
    _start_train_job_task(run_id, str(run.repo_id))
    _mark_train_start_guard(str(run.repo_id), run_id)
    return AgentTrainExecuteResponse(ok=True, run_id=run_id, status="running", workflow_run_id=expected)


@router.get("/agent/train/run/{run_id}", response_model=AgentTrainRun)
async def get_train_run(run_id: str) -> AgentTrainRun:
    run = _load_run(run_id)
    if _flyte_run_needs_reconcile(run):
        run = await _refresh_flyte_run(run)
        cfg = _cfg_from_run_snapshot(run)
        if cfg is not None:
            run = _apply_run_control_plane_metadata(run, cfg)
    return run


@router.get("/agent/train/run/{run_id}/metrics", response_model=AgentTrainMetricsResponse)
async def get_train_run_metrics(run_id: str, limit: int = Query(default=500, ge=1, le=5000)) -> AgentTrainMetricsResponse:
    _load_run(run_id)
    events = _load_events(run_id, limit=int(limit))
    return AgentTrainMetricsResponse(ok=True, events=events)


@router.get("/agent/train/run/{run_id}/stream")
async def stream_train_run(request: Request, run_id: str) -> StreamingResponse:
    _load_run(run_id)
    metrics_path = _metrics_path(run_id)
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if not metrics_path.exists():
        metrics_path.write_text("", encoding="utf-8")

    async def _gen() -> AsyncIterator[str]:
        try:
            lines = [ln for ln in metrics_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            lines = []
        for line in lines[-200:]:
            yield f"data: {line}\n\n"

        offset = 0
        try:
            offset = metrics_path.stat().st_size
        except Exception:
            offset = 0
        buf = b""

        while True:
            if await request.is_disconnected():
                return

            try:
                run = _load_run(run_id)
            except HTTPException:
                run = None
            # A Flyte-owned run may be terminated console-side while this stream
            # is the only observer; the read-driven reconcile does not run for a
            # queued run otherwise, so drive it here (throttled, off-loop).
            if run is not None and _flyte_run_needs_reconcile(run):
                run = await _refresh_flyte_run(run)
            if run is not None and run.status in {"completed", "failed", "cancelled"}:
                complete_event = AgentTrainMetricEvent(
                    type="complete",
                    ts=datetime.now(UTC),
                    run_id=run_id,
                    status=run.status,
                )
                yield f"data: {json.dumps(complete_event.model_dump(mode='json', by_alias=True))}\n\n"
                return

            try:
                size = metrics_path.stat().st_size
            except Exception:
                size = 0
            if size < offset:
                offset = 0
                buf = b""

            if size > offset:
                try:
                    with metrics_path.open("rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset = size
                    buf += chunk
                    while b"\n" in buf:
                        raw_line, buf = buf.split(b"\n", 1)
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line:
                            continue
                        yield f"data: {line}\n\n"
                except Exception:
                    pass

            await asyncio.sleep(1.0)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/train/run/{run_id}/cancel", response_model=OkResponse)
async def cancel_train_run(run_id: str) -> OkResponse:
    run = _load_run(run_id)
    if str(run.status) in _TERMINAL_RUN_STATUSES:
        return OkResponse(ok=True)

    if str(run.workflow_backend or "") == "flyte" and str(run.workflow_run_id or "").strip():
        cfg = _cfg_from_run_snapshot(run)
        execution_name = str(run.workflow_run_id)
        if cfg is not None:
            admin_url, project, domain = _flyte_scope(cfg)

            def _terminate() -> None:
                FlyteAdminClient(admin_url).terminate_execution(
                    project, domain, execution_name, cause="Cancellation requested by the Ragweld operator."
                )

            try:
                await asyncio.to_thread(_terminate)
                _append_event(
                    run_id,
                    AgentTrainMetricEvent(
                        type="log",
                        ts=datetime.now(UTC),
                        run_id=run_id,
                        message=f"Flyte execution {execution_name} termination requested.",
                    ),
                )
            except FlyteUnavailableError as exc:
                _append_event(
                    run_id,
                    AgentTrainMetricEvent(
                        type="log",
                        ts=datetime.now(UTC),
                        run_id=run_id,
                        message=f"Flyte execution {execution_name} could not be terminated: {exc}",
                    ),
                )
        if str(run.status) == "queued" and run_id not in _train_tasks:
            _finalize_run_without_job(
                run,
                cfg,
                status="cancelled",
                message="Cancellation requested by user before the workflow task started training.",
            )
            return OkResponse(ok=True)

    _request_train_run_cancel(run_id=run_id, reason="Cancellation requested by user.")
    return OkResponse(ok=True)


@router.post("/agent/train/run/{run_id}/promote", response_model=OkResponse)
async def promote_train_run(run_id: str) -> OkResponse:
    run = _load_run(run_id)
    if run.status != "completed":
        raise HTTPException(status_code=409, detail=f"Run is not finished (status={run.status})")

    src = _run_dir(run_id) / "model"
    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Run artifact not found at {src}")

    cfg = await load_scoped_config(repo_id=str(run.repo_id))
    dst_cfg = str(getattr(cfg.training, "ragweld_agent_model_path", "") or "").strip()
    if not dst_cfg:
        raise HTTPException(status_code=500, detail="training.ragweld_agent_model_path is empty")
    dst = _resolve_path(dst_cfg)

    _atomic_copy_dir(src, dst)
    await clear_ragweld_cache(adapter_dir=str(dst_cfg))
    run = _attach_lineage(run, cfg, promoted=True)
    _save_run(run)
    return OkResponse(ok=True)


@router.post("/agent/train/run/{run_id}/diff", response_model=AgentTrainDiffResponse)
async def diff_train_runs(run_id: str, payload: AgentTrainDiffRequest) -> AgentTrainDiffResponse:
    if payload.current_run_id != run_id:
        raise HTTPException(status_code=422, detail="current_run_id must match run_id path parameter")

    baseline = _load_run(payload.baseline_run_id)
    current = _load_run(payload.current_run_id)

    if baseline.primary_metric != current.primary_metric or baseline.primary_goal != current.primary_goal:
        return AgentTrainDiffResponse(
            ok=True,
            compatible=False,
            reason="Incompatible runs: primary_metric/primary_goal differ",
            primary_metric=None,
            primary_goal=None,
        )

    primary_metric = baseline.primary_metric
    primary_goal = baseline.primary_goal

    baseline_events = _load_events(baseline.run_id)
    current_events = _load_events(current.run_id)

    def _best(run: AgentTrainRun, events: list[AgentTrainMetricEvent]) -> float | None:
        if run.summary.primary_metric_best is not None:
            return float(run.summary.primary_metric_best)
        vals: list[float] = []
        for ev in events:
            if ev.type != "metrics" or not ev.metrics:
                continue
            pv = _primary_from_metrics(ev.metrics)
            if pv is None:
                continue
            vals.append(float(pv))
        return min(vals) if vals else None

    def _ttb(run: AgentTrainRun, events: list[AgentTrainMetricEvent], best_val: float | None) -> float | None:
        if run.summary.time_to_best_secs is not None:
            return float(run.summary.time_to_best_secs)
        if best_val is None:
            return None
        for ev in events:
            if ev.type != "metrics" or not ev.metrics:
                continue
            pv = _primary_from_metrics(ev.metrics)
            if pv is None:
                continue
            if float(pv) == float(best_val):
                return float((ev.ts - run.started_at).total_seconds())
        return None

    def _stability(run: AgentTrainRun, events: list[AgentTrainMetricEvent]) -> float | None:
        if run.summary.stability_stddev is not None:
            return float(run.summary.stability_stddev)
        vals: list[float] = []
        for ev in events:
            if ev.type != "metrics" or not ev.metrics:
                continue
            pv = _primary_from_metrics(ev.metrics)
            if pv is None:
                continue
            vals.append(float(pv))
        if not vals:
            return None
        tail = vals[-5:]
        if len(tail) == 1:
            return 0.0
        mean = sum(tail) / len(tail)
        var = sum((x - mean) ** 2 for x in tail) / len(tail)
        return float(math.sqrt(var))

    baseline_best = _best(baseline, baseline_events)
    current_best = _best(current, current_events)
    baseline_ttb = _ttb(baseline, baseline_events, baseline_best)
    current_ttb = _ttb(current, current_events, current_best)
    baseline_stability = _stability(baseline, baseline_events)
    current_stability = _stability(current, current_events)

    delta_best = (current_best - baseline_best) if (current_best is not None and baseline_best is not None) else None
    delta_ttb = (current_ttb - baseline_ttb) if (current_ttb is not None and baseline_ttb is not None) else None
    delta_stability = (
        (current_stability - baseline_stability)
        if (current_stability is not None and baseline_stability is not None)
        else None
    )

    improved: bool | None = None
    if baseline_best is not None and current_best is not None:
        improved = bool(current_best < baseline_best) if primary_goal == "minimize" else bool(current_best > baseline_best)

    return AgentTrainDiffResponse(
        ok=True,
        compatible=True,
        reason=None,
        primary_metric=primary_metric,
        primary_goal=primary_goal,
        baseline_primary_best=baseline_best,
        current_primary_best=current_best,
        delta_primary_best=delta_best,
        baseline_time_to_best_secs=baseline_ttb,
        current_time_to_best_secs=current_ttb,
        delta_time_to_best_secs=delta_ttb,
        baseline_stability_stddev=baseline_stability,
        current_stability_stddev=current_stability,
        delta_stability_stddev=delta_stability,
        improved=improved,
    )
