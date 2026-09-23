from __future__ import annotations

import logging
from typing import Any, cast, get_args

from fastapi import APIRouter, Depends, HTTPException, Request

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    dependency_unavailable_http_exception,
    raise_postgres_unavailable_if_applicable,
)
from server.config import load_config as load_global_config
from server.dependency_errors import DependencyUnavailableError
from server.models.tribrid_config_model import (
    CorpusScope,
    FeedbackEventNotAnsweredDetail,
    FeedbackEventNotAnsweredResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackSurface,
    RunOutcome,
    TriBridConfig,
)
from server.observability.metrics import FEEDBACK_EVENTS_TOTAL, FEEDBACK_SIGNALS
from server.observability.query_log import append_feedback_log, find_query_record
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.traces import get_trace_store

router = APIRouter(tags=["feedback"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)
logger = logging.getLogger(__name__)

# Ruff B008: avoid function calls in argument defaults (FastAPI Depends()).
_CORPUS_SCOPE_DEP = Depends()

_OUTCOMES: frozenset[str] = frozenset(get_args(RunOutcome))
_SURFACES: frozenset[str] = frozenset(get_args(FeedbackSurface))


def _is_test_request(request: Request) -> bool:
    """Best-effort guard to avoid contaminating training logs during tests."""
    try:
        if (request.headers.get("x-tribrid-test") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    except Exception:
        pass
    return False


async def _feedback_config(scope: CorpusScope) -> TriBridConfig:
    """The config whose query log holds the scoped corpus's records (global when unscoped)."""
    repo_id = scope.resolved_repo_id
    if not repo_id:
        return load_global_config()
    try:
        return await load_scoped_config(repo_id=repo_id)
    except CorpusNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"corpus_id={repo_id} not found") from e
    except Exception as e:
        raise_postgres_unavailable_if_applicable(e, boundary="Feedback API")
        logger.exception("Failed to load scoped config for feedback logging")
        raise HTTPException(status_code=500, detail="Failed to load corpus config") from e


async def _event_facts(cfg: TriBridConfig, event_id: str) -> tuple[RunOutcome | None, FeedbackSurface | None]:
    """How the rated event ended and on which surface, from its trace and its query record.

    The trace carries every chat run's outcome, including an aborted stream (which writes
    no query record); the query record carries the outcome durably. Either may be absent
    (tracing off, trace evicted, record outside the lookback), and then that fact is unknown.
    """
    outcome: RunOutcome | None = None
    surface: FeedbackSurface | None = None

    trace = await get_trace_store().get_trace(event_id)
    if trace is not None:
        for event in trace.events:
            if event.kind == "chat.outcome" and str(event.data.get("outcome")) in _OUTCOMES:
                outcome = cast(RunOutcome, event.data["outcome"])
            if event.kind.startswith("chat."):
                surface = "chat"
            elif event.kind.startswith("search."):
                surface = "search"

    record: dict[str, Any] | None = await find_query_record(cfg, event_id)
    if record is not None:
        kind = str(record.get("kind") or "")
        if kind in _SURFACES:
            surface = cast(FeedbackSurface, kind)
        recorded = str(record.get("outcome") or "")
        if outcome is None and recorded in _OUTCOMES:
            outcome = cast(RunOutcome, recorded)
    return outcome, surface


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses={
        409: {
            "model": FeedbackEventNotAnsweredResponse,
            "description": "The rated event failed or was aborted, so it has no answer to rate.",
        },
    },
)
async def post_feedback(
    body: FeedbackRequest,
    request: Request,
    scope: CorpusScope = _CORPUS_SCOPE_DEP,
) -> FeedbackResponse:
    """Record user feedback for a prior chat/search event, or UI meta feedback.

    Supports two payload shapes:
    - Event feedback: {event_id, signal, doc_id?, note?, chunk_ids?, surface?}. Refused (409)
      when the event failed or was aborted; `surface` defaults to the event's own kind.
    - UI meta feedback: {rating, comment?, timestamp?, context?}
    """
    if body.signal is not None and body.signal not in FEEDBACK_SIGNALS:
        raise HTTPException(status_code=400, detail="invalid signal")

    cfg = await _feedback_config(scope)

    surface: FeedbackSurface | None = None
    if body.event_id is not None:
        outcome, event_surface = await _event_facts(cfg, body.event_id)
        if outcome is not None and outcome != "ok":
            raise HTTPException(
                status_code=409,
                detail=FeedbackEventNotAnsweredDetail(
                    event_id=body.event_id,
                    outcome=outcome,
                    message="The rated event failed or was aborted; there is no answer to rate.",
                ).model_dump(mode="json"),
            )
        if body.surface is not None and event_surface is not None and body.surface != event_surface:
            raise HTTPException(
                status_code=422,
                detail=f"surface={body.surface} does not match the rated event, which is a {event_surface} event",
            )
        surface = body.surface or event_surface
        if surface is None:
            raise HTTPException(
                status_code=422,
                detail="surface is required: the rated event is not known to this server",
            )

    # Skip writing feedback from automated tests to protect training data
    if _is_test_request(request):
        return FeedbackResponse(ok=True)

    try:
        await append_feedback_log(
            cfg,
            event_id=body.event_id,
            signal=body.signal,
            doc_id=body.doc_id,
            note=body.note,
            rating=body.rating,
            comment=body.comment,
            timestamp=body.timestamp,
            context=body.context,
            chunk_ids=body.chunk_ids,
            surface=surface,
        )
    except DependencyUnavailableError as e:
        if e.dependency == "feedback_log":
            raise dependency_unavailable_http_exception("feedback_log", boundary="Feedback API", exc=e) from e
        raise
    except Exception as e:
        logger.exception("Failed to append feedback log")
        raise HTTPException(status_code=500, detail="Failed to record feedback") from e

    if body.signal is not None and surface is not None:
        FEEDBACK_EVENTS_TOTAL.labels(signal=body.signal, surface=surface).inc()
    return FeedbackResponse(ok=True)
