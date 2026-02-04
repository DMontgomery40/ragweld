from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from server.config import load_config as load_global_config
from server.models.tribrid_config_model import CorpusScope, FeedbackRequest, FeedbackResponse
from server.observability.query_log import append_feedback_log
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config

router = APIRouter(tags=["feedback"])
logger = logging.getLogger(__name__)


def _is_test_request(request: Request) -> bool:
    """Best-effort guard to avoid contaminating training logs during tests."""
    try:
        if (request.headers.get("x-tribrid-test") or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    except Exception:
        pass
    return False


@router.post("/feedback", response_model=FeedbackResponse)
async def post_feedback(
    body: FeedbackRequest,
    request: Request,
    scope: CorpusScope = Depends(),
) -> FeedbackResponse:
    """Record user feedback for a prior chat/search event.

    Supports two payload shapes:
    - Learning reranker feedback: {event_id, signal, doc_id?, note?}
    - UI meta feedback: {rating, comment?, timestamp?, context?}
    """
    # Validate allowed learning signals (UI meta feedback is gated by rating).
    if body.signal is not None:
        valid_signals = {
            "thumbsup",
            "thumbsdown",
            "click",
            "noclick",
            "note",
            "star1",
            "star2",
            "star3",
            "star4",
            "star5",
        }
        if body.signal not in valid_signals:
            raise HTTPException(status_code=400, detail="invalid signal")

    # Skip writing feedback from automated tests to protect training data
    if not _is_test_request(request):
        repo_id = scope.resolved_repo_id
        if repo_id:
            try:
                cfg = await load_scoped_config(repo_id=repo_id)
            except CorpusNotFoundError as e:
                raise HTTPException(status_code=404, detail=f"corpus_id={repo_id} not found") from e
            except Exception as e:
                logger.exception("Failed to load scoped config for feedback logging")
                raise HTTPException(status_code=500, detail="Failed to load corpus config") from e
        else:
            cfg = load_global_config()

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
            )
        except Exception as e:
            logger.exception("Failed to append feedback log")
            raise HTTPException(status_code=500, detail="Failed to record feedback") from e

    return FeedbackResponse(ok=True)
