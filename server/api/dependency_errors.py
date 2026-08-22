from __future__ import annotations

import logging
from typing import Literal

from fastapi import HTTPException

from server.dependency_errors import (
    DependencyUnavailableError,
    exception_chain,
    is_neo4j_unavailable,
    is_postgres_unavailable,
    is_transport_unavailable,
)
from server.models.tribrid_config_model import (
    DependencyUnavailableDetail,
    DependencyUnavailableResponse,
)

logger = logging.getLogger(__name__)

DependencyName = Literal["postgres", "neo4j", "qdrant", "embedding_provider", "ragas", "promptfoo", "feedback_log", "lineage_store"]

DEPENDENCY_UNAVAILABLE_RESPONSES = {
    503: {
        "model": DependencyUnavailableResponse,
        "description": "A required runtime dependency is unavailable.",
    }
}

def dependency_unavailable_http_exception(
    dependency: DependencyName,
    *,
    boundary: str,
    exc: BaseException,
) -> HTTPException:
    if dependency == "postgres":
        message = "PostgreSQL control store is unavailable."
        operator_hint = (
            f"{boundary} could not reach the corpus control store before validating the request; "
            "verify the scoped Ragweld Postgres service and DSN, then retry."
        )
    elif dependency == "neo4j":
        message = "Neo4j graph store is unavailable."
        operator_hint = (
            f"{boundary} reached graph storage but could not establish the corpus database connection; "
            "verify the scoped Ragweld Neo4j service and resolved database, then retry."
        )
    elif dependency == "qdrant":
        message = "Qdrant vector store is unavailable."
        operator_hint = (
            f"{boundary} could not reach the Compose-owned Qdrant service; verify the ragweld qdrant "
            "container and the configured qdrant.url, then retry."
        )
    elif dependency == "embedding_provider":
        message = "The configured embedding provider is unavailable."
        operator_hint = (
            f"{boundary} could not produce embeddings from the configured provider; verify the embedding "
            "runtime/model and provider credentials, then retry."
        )
    elif dependency == "ragas":
        message = "Ragas evaluation substrate is unavailable."
        operator_hint = (
            f"{boundary} requires the ragas package, a local embedding model, and a reachable LiteLLM judge "
            "alias; install/configure them or disable evaluation.ragas_enabled. Ragas scores are never faked."
        )
    elif dependency == "promptfoo":
        message = "Promptfoo regression substrate is unavailable."
        operator_hint = (
            f"{boundary} requires the promptfoo CLI on a supported Node.js runtime, eval dataset entries with "
            "expected_answer, and a reachable LiteLLM gateway exposing the provider/grader aliases. Results are never fabricated."
        )
    elif dependency == "feedback_log":
        message = "Feedback log storage is unavailable."
        operator_hint = (
            f"{boundary} could not persist the feedback event; verify the configured Ragweld feedback-log "
            "path and filesystem permissions, then retry."
        )
    else:
        message = "Lineage store is unavailable."
        operator_hint = (
            f"{boundary} could not read or persist lineage state; verify the configured Ragweld lineage-store "
            "path and filesystem permissions, then retry."
        )

    reason = str(getattr(exc, "reason", "") or "").strip()
    if reason:
        operator_hint = f"{operator_hint} Reason: {reason}"
    detail = DependencyUnavailableDetail(
        dependency=dependency,
        operation=boundary,
        message=message,
        operator_hint=operator_hint,
    )
    logger.error(
        "Required dependency unavailable",
        extra={
            "dependency": dependency,
            "boundary": boundary,
            "operator_hint": operator_hint,
            "exception_type": type(exc).__name__,
        },
    )
    return HTTPException(status_code=503, detail=detail.model_dump(mode="json"))


def raise_postgres_unavailable_if_applicable(exc: BaseException, *, boundary: str) -> None:
    if is_postgres_unavailable(exc) or is_transport_unavailable(exc):
        raise dependency_unavailable_http_exception("postgres", boundary=boundary, exc=exc) from exc


def raise_neo4j_unavailable_if_applicable(exc: BaseException, *, boundary: str) -> None:
    if is_neo4j_unavailable(exc) or is_transport_unavailable(exc):
        raise dependency_unavailable_http_exception("neo4j", boundary=boundary, exc=exc) from exc


def raise_required_dependency_unavailable_if_applicable(exc: BaseException, *, boundary: str) -> None:
    # A typed DependencyUnavailableError names its dependency explicitly
    # (qdrant, embedding_provider, ...); map it as-is.
    for item in exception_chain(exc):
        if isinstance(item, DependencyUnavailableError):
            raise dependency_unavailable_http_exception(item.dependency, boundary=boundary, exc=item) from exc
    if is_neo4j_unavailable(exc) and not is_postgres_unavailable(exc):
        raise dependency_unavailable_http_exception("neo4j", boundary=boundary, exc=exc) from exc
    if is_postgres_unavailable(exc):
        raise dependency_unavailable_http_exception("postgres", boundary=boundary, exc=exc) from exc
