from __future__ import annotations

import pytest
from neo4j.exceptions import ServiceUnavailable

from server.api.dependency_errors import dependency_unavailable_http_exception
from server.dependency_errors import is_neo4j_unavailable, is_postgres_unavailable
from server.models.tribrid_config_model import DependencyUnavailableDetail


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError(61, "connection refused"),
        TimeoutError("connection timed out"),
        ExceptionGroup("connect failed", [ConnectionRefusedError(61, "connection refused")]),
    ],
)
def test_postgres_classifier_covers_transport_failure_family(error: BaseException) -> None:
    assert is_postgres_unavailable(error) is True
    assert is_neo4j_unavailable(error) is True


def test_neo4j_classifier_covers_driver_service_unavailable() -> None:
    error = ServiceUnavailable("Unable to retrieve routing information")
    assert is_neo4j_unavailable(error) is True
    assert is_postgres_unavailable(error) is False


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
