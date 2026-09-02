from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from server.chat.generation_failure import generation_unavailable_detail
from server.chat.prompt_budget import PromptBudgetError, prompt_budget_exceeded_detail
from server.models.index import (
    IndexDeletionIncompleteResponse,
)
from server.models.tribrid_config_model import (
    DependencyUnavailableResponse,
    GenerationUnavailableResponse,
    PromptBudgetExceededResponse,
    RequiredRetrievalLegFailureResponse,
    RerankerFailureResponse,
)

logger = logging.getLogger(__name__)

CHAT_RUNTIME_UNAVAILABLE_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {
        "model": PromptBudgetExceededResponse,
        "description": "The request cannot fit the selected model alias's context window.",
    },
    503: {
        "model": (
            DependencyUnavailableResponse
            | RequiredRetrievalLegFailureResponse
            | RerankerFailureResponse
            | GenerationUnavailableResponse
            | IndexDeletionIncompleteResponse
        ),
        "description": (
            "Chat storage, retrieval, the configured reranker, or generation is unavailable, or the "
            "corpus is being de-indexed and its external cleanup has not completed."
        ),
    },
}

# /api/answer: everything the chat lane can fail on except the prompt-budget 413, which the
# answer lane reports as a generation failure.
ANSWER_RUNTIME_UNAVAILABLE_RESPONSES: dict[int | str, dict[str, Any]] = {
    503: CHAT_RUNTIME_UNAVAILABLE_RESPONSES[503],
}


def prompt_budget_http_exception(exc: PromptBudgetError, *, operation: str) -> HTTPException:
    detail = prompt_budget_exceeded_detail(exc, operation=operation)
    logger.warning(
        "Generation request exceeds the alias context window",
        extra={"operation": operation, "alias": exc.alias, "context_window": exc.context_window},
    )
    return HTTPException(status_code=413, detail=detail.model_dump(mode="json"))


def generation_unavailable_http_exception(exc: BaseException, *, operation: str) -> HTTPException:
    # Same classifier as the chat stream's in-band error event, so the non-stream chat
    # and eval paths carry the same sanitised reason and the same operator hint.
    detail = generation_unavailable_detail(exc, operation=operation)
    logger.error(
        "Generation gateway unavailable",
        extra={
            "operation": operation,
            "failure_kind": detail.failure_kind,
            "gateway_reason": detail.gateway_reason,
            "operator_hint": detail.operator_hint,
            "exception_type": type(exc).__name__,
        },
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))
