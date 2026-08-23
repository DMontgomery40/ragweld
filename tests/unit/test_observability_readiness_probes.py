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
    "data": [{"id": "ragweld-local", "object": "model", "owned_by": "vllm", "root": "mlx-community/Qwen3.8-27B-4bit", "max_model_len": 32768}],
}


def test_vllm_readiness_accepts_the_configured_model_at_the_catalog_context() -> None:
    assert vllm_serving_mismatch(_VLLM_MODEL_CARD, expected_model="mlx-community/Qwen3.8-27B-4bit", expected_context=32768) is None
    # Unknown catalog context only relaxes the context check, never the identity check.
    assert vllm_serving_mismatch(_VLLM_MODEL_CARD, expected_model="mlx-community/Qwen3.8-27B-4bit", expected_context=None) is None


@pytest.mark.parametrize(
    ("payload", "expected_model", "expected_context", "fragment"),
    [
        (_VLLM_MODEL_CARD, "Qwen/Qwen3-8B", 32768, "serving mlx-community/Qwen3.8-27B-4bit but chat.vllm.default_model expects Qwen/Qwen3-8B"),
        (_VLLM_MODEL_CARD, "mlx-community/Qwen3.8-27B-4bit", 2048, "max_model_len is 32768 but the catalog ragweld-local row expects 2048"),
        ({"object": "list", "data": []}, "mlx-community/Qwen3.8-27B-4bit", 32768, "reports no served model"),
        ({"detail": "Unauthorized"}, "mlx-community/Qwen3.8-27B-4bit", 32768, "reports no served model"),
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
