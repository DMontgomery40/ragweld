from __future__ import annotations

import logging

from fastapi import HTTPException

from server.models.tribrid_config_model import (
    DependencyUnavailableResponse,
    RequiredRetrievalLegFailureDetail,
    RequiredRetrievalLegFailureResponse,
)
from server.retrieval.errors import RequiredRetrievalLegError

logger = logging.getLogger(__name__)

RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES = {
    503: {
        "model": DependencyUnavailableResponse | RequiredRetrievalLegFailureResponse,
        "description": "A required storage dependency or requested retrieval leg is unavailable.",
    }
}


def required_retrieval_leg_http_exception(exc: RequiredRetrievalLegError) -> HTTPException:
    """Translate an internal leg failure without exposing its raw cause."""

    detail = RequiredRetrievalLegFailureDetail.model_validate(exc.to_detail())
    logger.error(
        "Required retrieval leg failed",
        extra={
            "leg": exc.leg,
            "operation": exc.operation,
            "operator_hint": detail.operator_hint,
        },
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))
