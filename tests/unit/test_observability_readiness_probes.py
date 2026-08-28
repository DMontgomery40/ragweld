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


def test_tempo_trace_link_targets_grafana_explore_not_the_bare_tempo_port() -> None:
    """Tempo has no UI; the operator link must open Grafana Explore on the
    provisioned Tempo datasource with the canonical trace id, never the dead
    ``{tempo_base}/trace/{id}`` path (which 404s)."""
    import urllib.parse

    from server.models.tribrid_config_model import TriBridConfig
    from server.observability.runtime import (
        apply_default_links,
        current_observation,
        start_request_observation,
    )

    config = TriBridConfig()
    config.tracing.tracing_enabled = True
    config.tracing.tracing_mode = "local"
    config.tracing.tempo_base_url = "http://127.0.0.1:53200"
    config.ui.grafana_base_url = "http://127.0.0.1:3301"

    with start_request_observation(
        config=config,
        route_name="unit_trace_links",
        path="/api/unit",
        method="GET",
    ) as obs:
        assert obs is not None
        apply_default_links(config)
        links = {link.label: link.url for link in current_observation().links}

    tempo_url = links["Tempo trace"]
    assert tempo_url.startswith("http://127.0.0.1:3301/explore?"), tempo_url
    assert "/trace/" not in tempo_url
    decoded = urllib.parse.unquote(tempo_url)
    assert obs.trace_id in decoded
    assert '"uid":"tempo"' in decoded
    assert '"queryType":"traceql"' in decoded


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


def test_profiling_stays_off_for_test_processes_and_without_a_server() -> None:
    """The agent gate is deterministic: no server configured -> off; test lane -> off."""
    import os

    from server.models.tribrid_config_model import TriBridConfig
    from server.observability import profiling

    assert os.environ.get("RAGWELD_DISABLE_PROFILING") == "1"  # set by conftest

    no_server = TriBridConfig()
    no_server.tracing.pyroscope_base_url = ""
    assert profiling.start_profiling(no_server) is False
    assert "no pyroscope_base_url" in profiling.profiling_state()

    configured = TriBridConfig()
    configured.tracing.pyroscope_base_url = "http://127.0.0.1:54040"
    assert profiling.start_profiling(configured) is False
    assert "RAGWELD_DISABLE_PROFILING" in profiling.profiling_state()


def test_langfuse_cost_details_maps_the_trace_summary_to_usd_totals() -> None:
    from server.models.tribrid_config_model import TraceCostSummary
    from server.observability.runtime import langfuse_cost_details

    assert langfuse_cost_details(None) == {}
    assert langfuse_cost_details(TraceCostSummary()) == {}
    summary = TraceCostSummary(estimated_cost_usd=0.000844, cost_source="provider")
    assert langfuse_cost_details(summary) == {"total": 0.000844}


def test_langfuse_client_blockers_name_every_missing_precondition() -> None:
    import os

    from server.models.tribrid_config_model import TriBridConfig
    from server.observability.runtime import langfuse_client_blockers

    disabled = TriBridConfig()
    disabled.tracing.langfuse_enabled = False
    assert any("langfuse_enabled" in blocker for blocker in langfuse_client_blockers(disabled.tracing))

    enabled = TriBridConfig()
    enabled.tracing.langfuse_enabled = True
    enabled.tracing.langfuse_base_url = ""
    assert any("langfuse_base_url" in blocker for blocker in langfuse_client_blockers(enabled.tracing))

    enabled.tracing.langfuse_base_url = "http://127.0.0.1:53000"
    saved = {key: os.environ.pop(key, None) for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}
    try:
        blockers = langfuse_client_blockers(enabled.tracing)
        assert any("LANGFUSE_PUBLIC_KEY" in blocker for blocker in blockers)
        assert any("LANGFUSE_SECRET_KEY" in blocker for blocker in blockers)
        os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-unit"
        os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-unit"
        assert langfuse_client_blockers(enabled.tracing) == []
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_langfuse_trace_url_is_built_from_config_without_network() -> None:
    from server.models.tribrid_config_model import TriBridConfig
    from server.observability.runtime import langfuse_trace_url

    cfg = TriBridConfig()
    cfg.tracing.langfuse_base_url = "http://127.0.0.1:53000/"
    cfg.tracing.langfuse_public_base_url = "https://langfuse.ragweld.com/"
    cfg.tracing.langfuse_project = "ragweld"
    assert (
        langfuse_trace_url(cfg.tracing, "a659c9939466c50f4a1158c586673388")
        == "https://langfuse.ragweld.com/project/ragweld/traces/a659c9939466c50f4a1158c586673388"
    )
    assert langfuse_trace_url(cfg.tracing, None) is None
    cfg.tracing.langfuse_public_base_url = ""
    assert langfuse_trace_url(cfg.tracing, "a659c9939466c50f4a1158c586673388") is None
    cfg.tracing.langfuse_base_url = ""
    assert langfuse_trace_url(cfg.tracing, "abc") is None
