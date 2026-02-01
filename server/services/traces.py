"""Local trace collection service (dev tooling).

This module intentionally implements **local** tracing independent of external
providers (LangSmith/LangTrace). It is used by the UI to render a full
per-request trace and to correlate to Loki logs.

Design goals:
- Cheap to record (in-memory ring buffer)
- Safe defaults: local trace should work out-of-the-box in dev
- No truncation in the backend; the UI can paginate if needed
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from typing import Any

from server.models.tribrid_config_model import Trace, TraceEvent, TracesLatestResponse, TriBridConfig


def _now_ms() -> int:
    return int(time.time() * 1000)


def _should_capture_local(config: TriBridConfig) -> bool:
    """Return True if we should store local traces for this request."""
    try:
        if int(getattr(config.tracing, "tracing_enabled", 1) or 0) != 1:
            return False
    except Exception:
        return False

    mode = str(getattr(config.tracing, "tracing_mode", "off") or "off").strip().lower()
    if mode == "off":
        return False

    # Local trace default rule:
    # If external tracing is not enabled/configured, fall back to local even
    # when tracing_mode is set to langsmith.
    langchain_v2 = int(getattr(config.tracing, "langchain_tracing_v2", 0) or 0)
    langtrace_host = str(getattr(config.tracing, "langtrace_api_host", "") or "").strip()
    langtrace_project = str(getattr(config.tracing, "langtrace_project_id", "") or "").strip()
    external_off = (langchain_v2 == 0) and (not langtrace_host) and (not langtrace_project)

    if mode in {"local"}:
        return True

    if external_off:
        return True

    # If the user explicitly configured an external mode, we still keep local
    # traces for dev UX unless they set tracing_mode=off.
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

        async with self._lock:
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

    async def end(self, run_id: str, *, ended_at_ms: int | None = None) -> None:
        async with self._lock:
            trace = self._traces.get(run_id)
            if trace is None:
                return
            trace.ended_at_ms = int(ended_at_ms or _now_ms())

    async def get_trace(self, run_id: str) -> Trace | None:
        async with self._lock:
            return self._traces.get(run_id)

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
                return TracesLatestResponse(repo=repo, run_id=rid, trace=self._traces.get(rid))

            if not self._order:
                return TracesLatestResponse(repo=None, run_id=None, trace=None)
            rid = self._order[-1]
            tr = self._traces.get(rid)
            return TracesLatestResponse(repo=(tr.repo_id if tr else None), run_id=rid, trace=tr)

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

