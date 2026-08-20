from __future__ import annotations

import logging

import pytest
from neo4j.exceptions import ServiceUnavailable

from server.api.dependency_errors import (
    dependency_unavailable_http_exception,
    raise_neo4j_unavailable_if_applicable,
    raise_postgres_unavailable_if_applicable,
)
from server.dependency_errors import (
    DependencyUnavailableError,
    is_neo4j_unavailable,
    is_postgres_unavailable,
    is_required_dependency_unavailable,
)
from server.models.tribrid_config_model import DependencyUnavailableDetail
from server.retrieval.fusion import _raise_neo4j_boundary_error, _raise_postgres_boundary_error


@pytest.mark.parametrize(
    "error",
    [
        OSError("model cache unavailable"),
        TimeoutError("embedding timed out"),
        FileNotFoundError("model weights missing"),
        ExceptionGroup("local failures", [PermissionError("cache is read-only")]),
    ],
)
def test_unrelated_runtime_errors_are_not_database_outages(error: BaseException) -> None:
    assert is_postgres_unavailable(error) is False
    assert is_neo4j_unavailable(error) is False


def test_neo4j_classifier_covers_driver_service_unavailable() -> None:
    error = ServiceUnavailable("Unable to retrieve routing information")
    error.__cause__ = ConnectionRefusedError(61, "connection refused")
    assert is_neo4j_unavailable(error) is True
    assert is_postgres_unavailable(error) is False


@pytest.mark.parametrize(
    ("raiser", "dependency"),
    [
        (raise_postgres_unavailable_if_applicable, "postgres"),
        (raise_neo4j_unavailable_if_applicable, "neo4j"),
    ],
)
def test_explicit_database_boundary_attributes_raw_transport_failure(raiser, dependency: str) -> None:
    with pytest.raises(Exception) as caught:
        raiser(ConnectionRefusedError(61, "connection refused"), boundary="Explicit DB boundary")

    error = caught.value
    assert getattr(error, "status_code", None) == 503
    detail = DependencyUnavailableDetail.model_validate(error.detail)
    assert detail.dependency == dependency


@pytest.mark.parametrize(
    ("raiser", "dependency"),
    [
        (
            lambda error: _raise_postgres_boundary_error(
                error,
                operation="Postgres vector search",
                leg="vector",
            ),
            "postgres",
        ),
        (
            lambda error: _raise_neo4j_boundary_error(error, operation="Neo4j graph connect"),
            "neo4j",
        ),
    ],
)
def test_fusion_database_boundaries_tag_raw_transport_provenance(raiser, dependency: str) -> None:
    with pytest.raises(DependencyUnavailableError) as caught:
        raiser(ConnectionRefusedError(61, "connection refused"))

    assert caught.value.dependency == dependency


@pytest.mark.parametrize("dependency", ["postgres", "neo4j", "feedback_log", "lineage_store"])
def test_dependency_http_exception_uses_typed_safe_detail(dependency: str) -> None:
    raw = ConnectionRefusedError(61, "127.0.0.1:1 secret-password")
    error = dependency_unavailable_http_exception(
        dependency,  # type: ignore[arg-type]
        boundary="Test boundary",
        exc=raw,
    )

    assert error.status_code == 503
    detail = DependencyUnavailableDetail.model_validate(error.detail)
    assert detail.dependency == dependency
    assert detail.operation == "Test boundary"
    assert detail.retryable is True
    assert "Test boundary" in detail.operator_hint
    assert "127.0.0.1:1" not in str(error.detail)
    assert "secret-password" not in str(error.detail)


def test_dependency_http_exception_logs_structured_event_without_traceback(caplog: pytest.LogCaptureFixture) -> None:
    raw = ConnectionRefusedError(61, "127.0.0.1:1 secret-password")

    with caplog.at_level(logging.ERROR, logger="server.api.dependency_errors"):
        dependency_unavailable_http_exception(
            "postgres",
            boundary="Test boundary",
            exc=raw,
        )

    assert caplog.records
    record = caplog.records[-1]
    assert record.getMessage() == "Required dependency unavailable"
    assert getattr(record, "dependency") == "postgres"
    assert getattr(record, "boundary") == "Test boundary"
    assert getattr(record, "exception_type") == "ConnectionRefusedError"
    assert getattr(record, "operator_hint")
    assert record.exc_info is None
    assert "Traceback" not in caplog.text
    assert "127.0.0.1:1" not in caplog.text
    assert "secret-password" not in caplog.text


@pytest.mark.parametrize("dependency", ["postgres", "neo4j", "feedback_log", "lineage_store"])
def test_explicit_dependency_errors_are_required_failures(dependency: str) -> None:
    error = DependencyUnavailableError(dependency, "Test operation")  # type: ignore[arg-type]
    assert is_required_dependency_unavailable(error) is True
