"""Reasoning controls travel in the protocol of the alias's upstream, and the lowest effort a
provider honours is the measured one (defect D26), never a guess from the alias name."""

from __future__ import annotations

import pytest

from server.gateway_reasoning import (
    LOWEST_REASONING_EFFORT,
    MANDATORY_REASONING_LOWEST_EFFORT,
    lowest_reasoning_effort,
    openrouter_provider,
    reasoning_body_fields,
    reasoning_model_params,
)


@pytest.mark.parametrize(
    ("upstream", "provider"),
    [
        ("openrouter/google/gemini-3.7-flash", "google"),
        ("openrouter/openai/gpt-5.6-luna", "openai"),
        ("openrouter/deepseek/deepseek-v4-flash:batch", "deepseek"),
        ("openai/ragweld-local", None),
        ("", None),
    ],
)
def test_openrouter_provider_is_the_segment_after_the_prefix(upstream: str, provider: str | None) -> None:
    assert openrouter_provider(upstream) == provider


@pytest.mark.parametrize(
    ("upstream", "effort"),
    [
        # Measured 2026-09-02 (50 real candidates each): "none" answers with zero reasoning tokens.
        ("openrouter/openai/gpt-5.6-luna", "none"),
        ("openrouter/openai/gpt-4.1-nano", "none"),
        ("openrouter/deepseek/deepseek-v4-flash", "none"),
        ("openrouter/anthropic/claude-haiku-4.5", "none"),
        ("openrouter/qwen/qwen3.7-flash", "none"),
        ("openrouter/moonshotai/kimi-k2.5", "none"),
        # Google and Z.ai reject "none" (HTTP 400 "Reasoning is mandatory for this endpoint and
        # cannot be disabled") and answer "minimal" with zero (Gemini) or ~50 (GLM) reasoning tokens.
        ("openrouter/google/gemini-3.7-flash", "minimal"),
        ("openrouter/google/gemini-3.5-flash-lite", "minimal"),
        ("openrouter/z-ai/glm-5.3-flash", "minimal"),
    ],
)
def test_lowest_reasoning_effort_is_the_measured_floor_per_provider(upstream: str, effort: str) -> None:
    assert lowest_reasoning_effort(upstream) == effort


def test_lowest_reasoning_effort_defaults_to_none_for_a_provider_not_in_the_mandatory_table() -> None:
    assert "mistralai" not in MANDATORY_REASONING_LOWEST_EFFORT
    assert lowest_reasoning_effort("openrouter/mistralai/mistral-small-3.2-24b-instruct") == LOWEST_REASONING_EFFORT


@pytest.mark.parametrize("upstream", ["openai/ragweld-local", "", "   "])
def test_lowest_reasoning_effort_is_only_defined_for_openrouter_upstreams(upstream: str) -> None:
    with pytest.raises(RuntimeError, match="OpenRouter"):
        lowest_reasoning_effort(upstream)


@pytest.mark.parametrize(
    ("effort", "upstream", "expected"),
    [
        ("minimal", "openrouter/google/gemini-3.5-flash-lite", {"reasoning": {"effort": "minimal"}}),
        ("none", "openrouter/openai/gpt-5.6-luna", {"reasoning": {"effort": "none"}}),
        ("low", "openai/ragweld-local", {"reasoning_effort": "low"}),
    ],
)
def test_reasoning_body_fields_use_the_upstreams_protocol(
    effort: str, upstream: str, expected: dict[str, object]
) -> None:
    assert reasoning_body_fields(reasoning_effort=effort, route_upstream=upstream) == expected


def test_reasoning_model_params_are_the_sdk_form_of_the_same_fields() -> None:
    """``OpenAILLM(model_params=...)`` sends keyword arguments; OpenRouter's native object
    only reaches the request body through ``extra_body``."""
    assert reasoning_model_params(reasoning_effort="medium", route_upstream="openrouter/openai/gpt-5.6-luna") == {
        "temperature": 0,
        "extra_body": {"reasoning": {"effort": "medium"}},
    }
    assert reasoning_model_params(reasoning_effort="medium", route_upstream="openai/ragweld-local") == {
        "temperature": 0,
        "reasoning_effort": "medium",
    }


@pytest.mark.parametrize(("effort", "upstream"), [("", "openrouter/openai/gpt-5.6-luna"), ("low", ""), ("  ", "  ")])
def test_reasoning_body_fields_refuse_a_missing_effort_or_upstream(effort: str, upstream: str) -> None:
    with pytest.raises(RuntimeError, match="effort|upstream"):
        reasoning_body_fields(reasoning_effort=effort, route_upstream=upstream)


@pytest.mark.parametrize(
    "upstream",
    [
        "openrouter/google",
        "openrouter/google/",
        "openrouter//gemini-3.5-flash-lite",
        "openrouter/",
    ],
)
def test_a_malformed_openrouter_upstream_is_not_read_as_a_provider(upstream: str) -> None:
    """``openrouter/<provider>/<model>`` is the whole shape: a truncated upstream names no
    provider, so the floor table must not answer for it (review finding, 2026-09-02)."""
    assert openrouter_provider(upstream) is None
    with pytest.raises(RuntimeError, match="openrouter/<provider>/<model>"):
        lowest_reasoning_effort(upstream)


def test_the_provider_floor_ignores_the_case_the_upstream_is_written_in() -> None:
    """A mandatory-reasoning provider written in any case still gets its measured floor
    rather than the "none" every other provider takes."""
    assert openrouter_provider("openrouter/Google/gemini-3.7-flash") == "google"
    assert lowest_reasoning_effort("openrouter/Google/gemini-3.7-flash") == "minimal"
    assert lowest_reasoning_effort("openrouter/Z-AI/glm-5.3-flash") == "minimal"
