from __future__ import annotations

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


@pytest.mark.parametrize("dependency", ["postgres", "neo4j"])
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
