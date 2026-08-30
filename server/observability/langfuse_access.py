"""Decide whether a Langfuse deep link is worth offering for a trace.

Two different questions get confused here, so they are answered separately:

* **Does Langfuse hold the trace?** This process can answer that with its
  server keys against the *ingestion* base URL (the loopback listener), and
  that is what this module does.
* **May the operator's browser open it?** Langfuse enforces project membership
  on the signed-in identity. Nothing the API knows can answer that, which is
  why every result carries a sign-in hint naming the project instead of
  pretending the link will work.

The check is a read endpoint, never part of recording: `langfuse_trace_url()`
is on the streamed-generation path and must stay free of network lookups.
"""

from __future__ import annotations

import os

import httpx

from server.models.observability import LangfuseTraceAccess
from server.models.tribrid_config_model import TracingConfig
from server.observability.runtime import (
    langfuse_client_blockers,
    langfuse_sign_in_hint,
    langfuse_trace_url,
)

_ACCESS_TIMEOUT_SECONDS = 5.0

# Langfuse v4 runs in `events_only` mode here: `/api/public/traces` answers
# "not available on deployments running in Langfuse v4 events_only mode", while
# the v2 observations route serves. One observation for the trace id is proof
# the trace landed.
_OBSERVATIONS_PATH = "/api/public/v2/observations"


async def check_langfuse_trace_access(tracing: TracingConfig, trace_id: str) -> LangfuseTraceAccess:
    """Ask Langfuse whether it holds `trace_id`, and build the deep link if it does."""

    project = str(tracing.langfuse_project or "").strip()
    hint = langfuse_sign_in_hint(tracing)
    trace_id = str(trace_id or "").strip()
    if not trace_id:
        return LangfuseTraceAccess(
            trace_id="",
            exists=False,
            checked=False,
            project=project,
            detail="No trace id to look up.",
            sign_in_hint=hint,
        )

    blockers = langfuse_client_blockers(tracing)
    if blockers:
        return LangfuseTraceAccess(
            trace_id=trace_id,
            exists=False,
            checked=False,
            project=project,
            detail=f"Langfuse cannot be queried from the API: {'; '.join(blockers)}.",
            sign_in_hint=hint,
        )

    # The ingestion base URL is the loopback listener the API can actually
    # reach; the public base URL is the operator's browser route through the
    # auth proxy and would answer the API with a redirect to sign in.
    base = str(tracing.langfuse_base_url or "").strip().rstrip("/")
    auth = (
        str(os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip(),
        str(os.getenv("LANGFUSE_SECRET_KEY") or "").strip(),
    )
    try:
        async with httpx.AsyncClient(timeout=_ACCESS_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}{_OBSERVATIONS_PATH}",
                params={"traceId": trace_id, "limit": 1},
                auth=auth,
            )
    except Exception as exc:
        return LangfuseTraceAccess(
            trace_id=trace_id,
            exists=False,
            checked=False,
            project=project,
            detail=f"Langfuse at {base} did not answer ({type(exc).__name__}: {exc}).",
            sign_in_hint=hint,
        )

    if response.status_code != 200:
        return LangfuseTraceAccess(
            trace_id=trace_id,
            exists=False,
            checked=False,
            project=project,
            detail=f"Langfuse at {base} answered HTTP {response.status_code} for the trace lookup.",
            sign_in_hint=hint,
        )

    try:
        rows = response.json().get("data")
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        return LangfuseTraceAccess(
            trace_id=trace_id,
            exists=False,
            checked=False,
            project=project,
            detail=f"Langfuse at {base} answered the trace lookup without an observation list.",
            sign_in_hint=hint,
        )

    exists = len(rows) > 0
    return LangfuseTraceAccess(
        trace_id=trace_id,
        exists=exists,
        checked=True,
        url=langfuse_trace_url(tracing, trace_id) if exists else None,
        project=project,
        detail=(
            f"Langfuse holds {len(rows)} observation(s) for this trace."
            if exists
            else "Langfuse has no observation for this trace, so there is nothing to open."
        ),
        sign_in_hint=hint,
    )
