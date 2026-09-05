from __future__ import annotations

import copy

import pytest
from pydantic import SecretStr, ValidationError

from server.observability.gateway_policy import (
    NativeGatewayPolicyReader,
    NativeModelPolicies,
    NativeRouterMemory,
    NativeRouterPolicy,
    assess_native_policy,
)


def observed_policy() -> dict:
    # Sanitized native1.94 observations from the isolated provider-count matrix.
    return {
        "num_retries": 0, "retry_policy": None, "model_group_retry_policy": {},
        "fallbacks": [], "context_window_fallbacks": [], "content_policy_fallbacks": [],
        "enable_weighted_failover": False,
    }


def deployments() -> dict:
    return {"data": [{"model_name": "calibration", "litellm_params": {
        "model": "openai/gpt-5-mini", "num_retries": 0, "max_retries": 0,
    }}]}


def assess(reported: dict | None = None, memory: dict | None = None, models: dict | None = None):
    return assess_native_policy(
        models=frozenset({"calibration"}),
        reported=NativeRouterPolicy.model_validate(reported if reported is not None else observed_policy()),
        memory=NativeRouterPolicy.model_validate(memory if memory is not None else observed_policy()),
        deployments=NativeModelPolicies.model_validate(models if models is not None else deployments()),
    )


def test_compatible_native_fields_and_stable_hash_never_certify_provider_attempts():
    first, second = assess(), assess()
    assert first.observed_compatible and second.observed_compatible
    assert first.evidence_sha256 == second.evidence_sha256
    assert first.verified is second.verified is False
    assert "provider_sdk_retry_policy_unobservable" in first.reasons
    assert "effective_content_policy_fallbacks_unobservable" in first.reasons


@pytest.mark.parametrize("side", ["reported", "memory"])
@pytest.mark.parametrize("field,value", [
    ("num_retries", 1), ("max_retries", 1), ("silent_model", "secondary"),
    ("retry_policy", {"RateLimitErrorRetries": 1}),
    ("retry_policy", {"UnknownErrorRetries": 0}),
    ("model_group_retry_policy", {"calibration": {"TimeoutErrorRetries": 1}}),
    ("fallbacks", [{"calibration": ["secondary"]}]),
    ("default_fallbacks", ["secondary"]),
    ("context_window_fallbacks", [{"*": ["secondary"]}]),
    ("content_policy_fallbacks", ["secondary"]),
    ("enable_weighted_failover", True),
    ("default_litellm_params", {"silent_model": "secondary"}),
    ("default_litellm_params", {"default_fallbacks": ["secondary"]}),
])
def test_either_reported_or_memory_unsafe_policy_blocks_compatibility(side, field, value):
    policy = observed_policy()
    policy[field] = value
    result = assess(**{side: policy})
    assert not result.observed_compatible
    assert any(reason.startswith(side) for reason in result.reasons)
    assert result.evidence_sha256 != assess().evidence_sha256


@pytest.mark.parametrize("field", ["num_retries", "retry_policy", "model_group_retry_policy", "fallbacks", "context_window_fallbacks", "content_policy_fallbacks"])
def test_missing_reported_fields_are_not_disabled_defaults(field):
    reported = observed_policy()
    del reported[field]
    result = assess(reported=reported)
    assert not result.observed_compatible
    assert "reported_policy_fields_missing" in result.reasons
    assert result.evidence_sha256 != assess().evidence_sha256


@pytest.mark.parametrize("changes", [
    {"num_retries": 2}, {"max_retries": 2}, {"silent_model": "secondary"},
    {"order": 1}, {"num_retries": None}, {"max_retries": None},
    {"fallbacks": ["secondary"]},
    {"default_fallbacks": ["secondary"]},
])
def test_every_selected_deployment_is_checked(changes):
    value = deployments()
    unsafe = copy.deepcopy(value["data"][0])
    unsafe["litellm_params"].update(changes)
    value["data"].append(unsafe)
    assert not assess(models=value).observed_compatible


def test_missing_selected_deployment_and_missing_retry_fields_are_unverified():
    assert "selected_model_deployments_missing" in assess(models={"data": []}).reasons
    value = deployments()
    del value["data"][0]["litellm_params"]["max_retries"]
    assert "deployment_retry_fields_missing" in assess(models=value).reasons


def test_unrelated_models_do_not_block_selected_alias_and_secrets_are_discarded():
    value = deployments()
    value["data"][0]["litellm_params"].update({"api_key": "synthetic-sensitive-key", "api_base": "https://private.invalid"})
    value["data"].append({"model_name": "unselected", "litellm_params": {
        "model": "openai/other", "num_retries": 9, "silent_model": "secondary",
    }})
    memory = NativeRouterMemory.model_validate({"router_settings": observed_policy(), "callbacks": {"key": "synthetic-sensitive-key"}})
    assert "synthetic-sensitive-key" not in memory.model_dump_json()
    result = assess(models=value)
    assert result.observed_compatible
    assert result.evidence_sha256 == assess().evidence_sha256
    assert "synthetic-sensitive-key" not in repr(result)
    policy = observed_policy()
    policy["fallbacks"] = [{"unselected": ["secondary"]}]
    policy["model_group_retry_policy"] = {"unselected": {"TimeoutErrorRetries": 9}}
    assert assess(reported=policy, memory=policy).observed_compatible


@pytest.mark.parametrize("bad", [True, "0", -1, 0.5])
def test_native_retry_counts_are_strict(bad):
    with pytest.raises(ValidationError):
        NativeRouterPolicy.model_validate({"num_retries": bad})


@pytest.mark.parametrize("base_url", ["https://secret@localhost", "https://localhost/v1", "https://localhost?key=secret", "https://localhost#fragment", "file:///tmp/gateway"])
def test_reader_requires_explicit_management_root(base_url):
    with pytest.raises(ValueError):
        NativeGatewayPolicyReader(base_url=base_url, api_key=SecretStr("synthetic"), request_timeout_s=1, total_timeout_s=1)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_reader_requires_finite_positive_timeouts(timeout):
    with pytest.raises(ValueError):
        NativeGatewayPolicyReader(base_url="http://127.0.0.1", api_key=SecretStr("synthetic"), request_timeout_s=timeout, total_timeout_s=1)


def test_empty_alias_selection_is_rejected_before_network():
    with pytest.raises(ValueError):
        assess_native_policy(models=frozenset(), reported=NativeRouterPolicy(), memory=NativeRouterPolicy(), deployments=NativeModelPolicies(data=[]))
