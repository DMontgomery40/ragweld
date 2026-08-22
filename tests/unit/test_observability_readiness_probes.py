"""Observability component probes must target functional readiness paths."""

from __future__ import annotations

import pytest

from server.observability.runtime import _logs_endpoint_from_traces
from server.observability.status import readiness_probe_url, vllm_serving_mismatch


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


_VLLM_MODEL_CARD = {
    "object": "list",
    "data": [{"id": "ragweld-local", "object": "model", "owned_by": "vllm", "root": "Qwen/Qwen3-4B-Instruct-2507", "max_model_len": 8192}],
}


def test_vllm_readiness_accepts_the_configured_model_at_the_catalog_context() -> None:
    assert vllm_serving_mismatch(_VLLM_MODEL_CARD, expected_model="Qwen/Qwen3-4B-Instruct-2507", expected_context=8192) is None
    # Unknown catalog context only relaxes the context check, never the identity check.
    assert vllm_serving_mismatch(_VLLM_MODEL_CARD, expected_model="Qwen/Qwen3-4B-Instruct-2507", expected_context=None) is None


@pytest.mark.parametrize(
    ("payload", "expected_model", "expected_context", "fragment"),
    [
        (_VLLM_MODEL_CARD, "Qwen/Qwen3-8B", 8192, "serving Qwen/Qwen3-4B-Instruct-2507 but chat.vllm.default_model expects Qwen/Qwen3-8B"),
        (_VLLM_MODEL_CARD, "Qwen/Qwen3-4B-Instruct-2507", 2048, "max_model_len is 8192 but the catalog ragweld-local row expects 2048"),
        ({"object": "list", "data": []}, "Qwen/Qwen3-4B-Instruct-2507", 8192, "reports no served model"),
        ({"detail": "Unauthorized"}, "Qwen/Qwen3-4B-Instruct-2507", 8192, "reports no served model"),
    ],
    ids=["model-drift", "context-drift", "empty-list", "not-a-model-list"],
)
def test_vllm_readiness_fails_closed_on_served_model_drift(
    payload: dict[str, object], expected_model: str, expected_context: int, fragment: str
) -> None:
    mismatch = vllm_serving_mismatch(payload, expected_model=expected_model, expected_context=expected_context)
    assert mismatch is not None
    assert fragment in mismatch


def test_vllm_readiness_reports_every_drift_at_once() -> None:
    mismatch = vllm_serving_mismatch(_VLLM_MODEL_CARD, expected_model="Qwen/Qwen3-8B", expected_context=2048)
    assert mismatch is not None
    assert mismatch.count(";") == 1
