"""Observability component probes must target functional readiness paths."""

from __future__ import annotations

import pytest

from server.observability.runtime import _logs_endpoint_from_traces
from server.observability.status import readiness_probe_url


@pytest.mark.parametrize(
    ("component", "base", "expected"),
    [
        ("tempo", "http://127.0.0.1:53200", "http://127.0.0.1:53200/ready"),
        ("tempo", "http://127.0.0.1:53200/", "http://127.0.0.1:53200/ready"),
        ("tempo", "http://127.0.0.1:53200/ready", "http://127.0.0.1:53200/ready"),
        ("alloy", "http://127.0.0.1:52345", "http://127.0.0.1:52345/-/ready"),
        ("grafana", "http://127.0.0.1:3301", "http://127.0.0.1:3301/api/health"),
        ("mimir", "http://127.0.0.1:59009", "http://127.0.0.1:59009/ready"),
        ("langfuse", "http://127.0.0.1:3000", "http://127.0.0.1:3000/api/public/health"),
        ("otlp_export", "http://127.0.0.1:54320/v1/traces", "http://127.0.0.1:54320/v1/traces"),
        ("tempo", "", ""),
    ],
)
def test_readiness_probe_url_targets_functional_paths(component: str, base: str, expected: str) -> None:
    assert readiness_probe_url(component, base) == expected


def test_logs_endpoint_is_derived_from_the_traces_endpoint() -> None:
    assert _logs_endpoint_from_traces("http://127.0.0.1:54320/v1/traces") == "http://127.0.0.1:54320/v1/logs"
    assert _logs_endpoint_from_traces("http://alloy:4318") == "http://alloy:4318/v1/logs"
