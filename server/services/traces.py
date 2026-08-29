"""Local trace collection service (workbench trace cache).

This module stores the workbench-facing trace payload used by the UI. It is now
fed by the canonical observability metadata when available, while still keeping
an in-memory event list for fast local drilldown and fallback rendering.

Design goals:
- Cheap to record (in-memory ring buffer)
- Safe defaults: local trace should work out-of-the-box in dev
- No truncation in the backend; the UI can paginate if needed
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import (
    Trace,
    TraceCostSummary,
    TraceEvent,
    TraceExternalLink,
    TraceRouteSummary,
    TracesLatestResponse,
    TriBridConfig,
)

logger = logging.getLogger(__name__)
_TRACE_STORE_VERSION = 1


def _now_ms() -> int:
    return int(time.time() * 1000)


def _should_capture_local(config: TriBridConfig) -> bool:
    """Return True if we should store local traces for this request."""
    try:
        if not getattr(config.tracing, "tracing_enabled", True):
            return False
    except Exception:
        return False

    mode = str(getattr(config.tracing, "tracing_mode", "off") or "off").strip().lower()
    if mode == "off":
        return False

    if mode in {"local"}:
        return True
    return True


def _passes_sample_rate(config: TriBridConfig) -> bool:
    try:
        rate = float(getattr(config.tracing, "trace_sampling_rate", 1.0) or 0.0)
    except Exception:
        rate = 1.0
    rate = max(0.0, min(1.0, rate))
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() <= rate


class TraceStore:
    """In-memory trace ring buffer keyed by run_id."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._traces: dict[str, Trace] = {}
        self._order: deque[str] = deque()
        self._order_by_repo: dict[str, deque[str]] = {}
        self._persist_path: Path | None = None
        self._initialized = False

    @staticmethod
    def _configured_path(config: TriBridConfig) -> Path | None:
        raw = str(getattr(config.tracing, "trace_store_path", "") or "").strip()
        return Path(raw).expanduser().resolve(strict=False) if raw else None

    def _reset_locked(self) -> None:
        self._traces.clear()
        self._order.clear()
        self._order_by_repo.clear()

    async def initialize(self, config: TriBridConfig) -> None:
        """Load persisted traces once and rebuild every retention index."""
        path = self._configured_path(config)
        async with self._lock:
            # Persistence ownership is process-global. Corpus-scoped configs may
            # predate this field and therefore carry an empty default; they must
            # never reset or disable the path established during API startup.
            if self._initialized:
                return
            self._initialized = True
            self._persist_path = path
            if path is None:
                return

            self._reset_locked()
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("trace-store root must be an object")
                if payload.get("version") != _TRACE_STORE_VERSION:
                    raise ValueError("unsupported trace-store version")
                rows = payload.get("traces")
                if not isinstance(rows, list):
                    raise ValueError("trace-store traces must be a list")
                for row in rows:
                    trace = Trace.model_validate(row)
                    self._drop_run_id_indexes_locked(trace.run_id)
                    self._traces[trace.run_id] = trace
                    self._order.append(trace.run_id)
                    self._order_by_repo.setdefault(trace.repo_id, deque()).append(trace.run_id)
                for repo_id in list(self._order_by_repo):
                    await self._enforce_retention_locked(repo_id=repo_id, config=config)
            except FileNotFoundError:
                return
            except (OSError, TypeError, ValueError) as exc:
                self._reset_locked()
                logger.warning("persistent trace store ignored at %s: %s", path, exc)

    def _persist_locked(self) -> None:
        path = self._persist_path
        if path is None:
            return
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": _TRACE_STORE_VERSION,
                "traces": [
                    self._traces[run_id].model_dump(mode="json")
                    for run_id in self._order
                    if run_id in self._traces
                ],
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                os.fchmod(handle.fileno(), 0o600)
                temp_path = Path(handle.name)
            os.replace(temp_path, path)
        except OSError as exc:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            logger.error("persistent trace store write failed at %s: %s", path, exc)

    def _drop_run_id_indexes_locked(self, run_id: str) -> None:
        """Remove all index references to run_id before replacing its trace entry."""
        while True:
            try:
                self._order.remove(run_id)
            except ValueError:
                break
        for dq in self._order_by_repo.values():
            while True:
                try:
                    dq.remove(run_id)
                except ValueError:
                    break

    async def start(
        self,
        *,
        run_id: str,
        repo_id: str,
        started_at_ms: int,
        config: TriBridConfig,
    ) -> bool:
        """Start a trace for a run_id. Returns False if tracing is disabled."""
        if not _should_capture_local(config):
            return False
        if not _passes_sample_rate(config):
            return False

        await self.initialize(config)

        async with self._lock:
            # If a caller reuses run_id (for retries/restarts), purge stale index
            # entries so retention cannot evict the newly started trace.
            if run_id in self._traces:
                self._drop_run_id_indexes_locked(run_id)
            trace = Trace(run_id=run_id, repo_id=repo_id, started_at_ms=int(started_at_ms), ended_at_ms=None, events=[])
            self._traces[run_id] = trace
            self._order.append(run_id)
            dq = self._order_by_repo.setdefault(repo_id, deque())
            dq.append(run_id)
            await self._enforce_retention_locked(repo_id=repo_id, config=config)
            return True

    async def add_event(
        self,
        run_id: str,
        *,
        kind: str,
        msg: str | None = None,
        data: dict[str, Any] | None = None,
        ts_ms: int | None = None,
    ) -> None:
        """Append a trace event (no-op if run_id not found)."""
        async with self._lock:
            trace = self._traces.get(run_id)
            if trace is None:
                return
            ev = TraceEvent(kind=str(kind), ts=int(ts_ms or _now_ms()), msg=msg, data=data or {})
            trace.events.append(ev)

    async def annotate(
        self,
        run_id: str,
        *,
        trace_id: str | None = None,
        root_span_id: str | None = None,
        correlation_id: str | None = None,
        route_summary: TraceRouteSummary | None = None,
        external_links: list[TraceExternalLink] | None = None,
        cost_summary: TraceCostSummary | None = None,
    ) -> None:
        async with self._lock:
            trace = self._traces.get(run_id)
            if trace is None:
                return
            update: dict[str, Any] = {}
            if trace_id is not None:
                update["trace_id"] = trace_id
            if root_span_id is not None:
                update["root_span_id"] = root_span_id
            if correlation_id is not None:
                update["correlation_id"] = correlation_id
            if route_summary is not None:
                update["route_summary"] = route_summary
            if external_links is not None:
                update["external_links"] = external_links
            if cost_summary is not None:
                update["cost_summary"] = cost_summary
            if update:
                self._traces[run_id] = trace.model_copy(update=update)

    async def end(self, run_id: str, *, ended_at_ms: int | None = None) -> None:
        async with self._lock:
            trace = self._traces.get(run_id)
            if trace is None:
                return
            trace.ended_at_ms = int(ended_at_ms or _now_ms())
            self._persist_locked()

    async def get_trace(self, run_id: str) -> Trace | None:
        async with self._lock:
            trace = self._traces.get(run_id)
            if trace is None:
                return None
            return trace.model_copy(deep=True)

    async def latest(self, *, repo: str | None = None, run_id: str | None = None) -> TracesLatestResponse:
        """Return the latest trace (optionally for a repo or specific run_id)."""
        if run_id:
            tr = await self.get_trace(run_id)
            return TracesLatestResponse(repo=(repo or (tr.repo_id if tr else None)), run_id=run_id, trace=tr)

        async with self._lock:
            if repo:
                dq = self._order_by_repo.get(repo)
                if not dq:
                    return TracesLatestResponse(repo=repo, run_id=None, trace=None)
                rid = dq[-1]
                trace = self._traces.get(rid)
                return TracesLatestResponse(
                    repo=repo,
                    run_id=rid,
                    trace=(trace.model_copy(deep=True) if trace is not None else None),
                )

            if not self._order:
                return TracesLatestResponse(repo=None, run_id=None, trace=None)
            rid = self._order[-1]
            tr = self._traces.get(rid)
            return TracesLatestResponse(
                repo=(tr.repo_id if tr else None),
                run_id=rid,
                trace=(tr.model_copy(deep=True) if tr is not None else None),
            )

    async def _enforce_retention_locked(self, *, repo_id: str, config: TriBridConfig) -> None:
        """Evict old traces for repo_id to satisfy config.tracing.trace_retention."""
        try:
            retention = int(getattr(config.tracing, "trace_retention", 50) or 50)
        except Exception:
            retention = 50
        retention = max(10, min(500, retention))

        dq = self._order_by_repo.get(repo_id)
        if dq is None:
            return

        while len(dq) > retention:
            old = dq.popleft()
            self._traces.pop(old, None)
            # Also remove from global order (linear, but small retention sizes).
            try:
                self._order.remove(old)
            except ValueError:
                pass


_TRACE_STORE = TraceStore()


def get_trace_store() -> TraceStore:
    return _TRACE_STORE
