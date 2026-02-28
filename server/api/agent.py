from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

from server.api.dataset import _dataset_path_for_corpus
from server.chat.context_formatter import format_context_for_llm
from server.chat.prompt_builder import get_system_prompt
from server.chat.ragweld_mlx import clear_cache as clear_ragweld_cache
from server.db.postgres import PostgresClient
from server.models.tribrid_config_model import (
    AgentTrainDiffRequest,
    AgentTrainDiffResponse,
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
)
from server.retrieval.mlx_qwen3 import mlx_is_available
from server.services.config_store import get_config as load_scoped_config
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
    return _maybe_reconcile_run(run)


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
        if str(run.status) == "running":
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

    try:
        cfg = await load_scoped_config(repo_id=corpus_id)
        _raise_if_cancelled()

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
        promote_if_improves = int(getattr(cfg.training, "ragweld_agent_promote_if_improves", 0) or 0) == 1
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
        _save_run(run)
        _append_event(run_id, AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status=run.status))
    except TrainingCancelledError:
        try:
            run = _load_run(run_id)
            run.status = "cancelled"
            run.completed_at = datetime.now(UTC)
            _save_run(run)
        except Exception:
            pass
        _append_event(
            run_id,
            AgentTrainMetricEvent(
                type="state",
                ts=datetime.now(UTC),
                run_id=run_id,
                status="cancelled",
                message="Training cancelled.",
            ),
        )
        _append_event(run_id, AgentTrainMetricEvent(type="complete", ts=datetime.now(UTC), run_id=run_id, status="cancelled"))
    except Exception as e:
        try:
            run = _load_run(run_id)
            run.status = "failed"
            run.completed_at = datetime.now(UTC)
            _save_run(run)
        except Exception:
            pass
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
        _train_start_guard.pop(str(corpus_id or "").strip(), None)


@router.get("/agent/train/profile", response_model=OkResponse)
async def get_train_profile() -> OkResponse:
    # Minimal endpoint for Studio parity; current Agent Studio does not need a profile object.
    return OkResponse(ok=True)


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
        metas.append(
            AgentTrainRunMeta(
                run_id=run.run_id,
                repo_id=run.repo_id,
                status=run.status,
                started_at=run.started_at,
                completed_at=run.completed_at,
                primary_metric_best=run.summary.primary_metric_best,
                primary_metric_final=run.summary.primary_metric_final,
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

    started_at = datetime.now(UTC)
    run_id = _allocate_run_id(corpus_id, started_at)
    _train_start_guard[str(corpus_id or "").strip()] = (run_id, started_at)

    # Resolved defaults mirror the reranker Studio knobs (epochs/batch/lr/warmup/max_length).
    run = AgentTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="running",
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
    )

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
    _append_event(
        run_id,
        AgentTrainMetricEvent(
            type="log",
            ts=datetime.now(UTC),
            run_id=run_id,
            message="Queued background training job.",
        ),
    )

    if run_id not in _train_tasks:
        cancel_event = asyncio.Event()
        _train_cancel_events[run_id] = cancel_event
        _train_tasks[run_id] = asyncio.create_task(_run_train_job(run_id=run_id, corpus_id=corpus_id, cancel_event=cancel_event))

    return AgentTrainStartResponse(ok=True, run_id=run_id)


@router.get("/agent/train/run/{run_id}", response_model=AgentTrainRun)
async def get_train_run(run_id: str) -> AgentTrainRun:
    return _load_run(run_id)


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
    if str(run.status) in {"completed", "failed", "cancelled"}:
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
