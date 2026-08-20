from __future__ import annotations

import logging

from fastapi import HTTPException

from server.models.tribrid_config_model import (
    DependencyUnavailableResponse,
    GenerationUnavailableDetail,
    GenerationUnavailableResponse,
    RequiredRetrievalLegFailureResponse,
)

logger = logging.getLogger(__name__)

CHAT_RUNTIME_UNAVAILABLE_RESPONSES = {
    503: {
        "model": (
            DependencyUnavailableResponse
            | RequiredRetrievalLegFailureResponse
            | GenerationUnavailableResponse
        ),
        "description": "Chat storage, retrieval, or generation is unavailable.",
    }
}


def generation_unavailable_http_exception(exc: BaseException, *, operation: str) -> HTTPException:
    detail = GenerationUnavailableDetail(
        operation=operation,
        message="The generation gateway could not complete the chat request.",
        operator_hint=(
            "Verify the scoped LiteLLM gateway, client key, and selected model alias, then retry. "
            "Ragweld did not substitute a direct provider fallback."
        ),
    )
    logger.error(
        "Generation gateway unavailable",
        extra={
            "operation": operation,
            "operator_hint": detail.operator_hint,
            "exception_type": type(exc).__name__,
        },
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))
