from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from server.models.index import (
    IndexDeletionIncompleteResponse,
)
from server.models.tribrid_config_model import (
    AnswerRetrievalFailureDetail,
    DependencyUnavailableResponse,
    RequiredRetrievalLegFailureDetail,
    RequiredRetrievalLegFailureResponse,
    RerankerFailureDetail,
    RerankerFailureResponse,
    RetrievalContractMismatchDetail,
    RetrievalContractMismatchResponse,
)
from server.retrieval.errors import (
    AnswerRetrievalFailedError,
    RequiredRetrievalLegError,
    RerankerFailedError,
    RetrievalContractMismatchError,
)

logger = logging.getLogger(__name__)

RETRIEVAL_RUNTIME_UNAVAILABLE_RESPONSES: dict[int | str, dict[str, Any]] = {
    503: {
        "model": (
            DependencyUnavailableResponse
            | RequiredRetrievalLegFailureResponse
            | RerankerFailureResponse
            | IndexDeletionIncompleteResponse
        ),
        "description": (
            "A required storage dependency or requested retrieval leg is unavailable, the configured "
            "reranker failed, or the corpus is being de-indexed and its external cleanup has not completed."
        ),
    },
    409: {
        "model": RetrievalContractMismatchResponse,
        "description": "The stored index contract conflicts with the current runtime configuration.",
    },
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


def reranker_failed_http_exception(exc: RerankerFailedError) -> HTTPException:
    """Translate a configured-reranker failure into its validated 503 boundary shape."""

    detail = RerankerFailureDetail.model_validate(exc.to_detail())
    logger.error(
        "Configured reranker failed",
        extra={"mode": detail.mode, "reason": detail.reason, "operator_hint": detail.operator_hint},
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))


def answer_retrieval_failed_http_exception(
    exc: AnswerRetrievalFailedError, *, operation: str
) -> HTTPException:
    """Translate an untyped answer-retrieval failure into its validated 503 boundary shape."""

    detail = AnswerRetrievalFailureDetail.model_validate(exc.to_detail(operation=operation))
    logger.error(
        "Answer retrieval failed",
        extra={"operation": operation, "reason": detail.reason, "operator_hint": detail.operator_hint},
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))


def retrieval_contract_mismatch_http_exception(
    exc: RetrievalContractMismatchError,
) -> HTTPException:
    """Translate an index-contract mismatch into its validated 409 boundary shape."""

    detail = RetrievalContractMismatchDetail.model_validate(exc.to_detail())
    logger.error(
        "Retrieval contract mismatch",
        extra={
            "code": detail.code,
            "leg": detail.leg,
            "corpus_id": detail.corpus_id,
        },
    )
    return HTTPException(status_code=409, detail=detail.model_dump(mode="json"))
