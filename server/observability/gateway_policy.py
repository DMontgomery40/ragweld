"""Sanitized observations of native LiteLLM policy, never inferred attempt proof.

LiteLLM 1.94 management endpoints do not expose the effective retry defaults of
provider SDK clients. Identical snapshots can produce different embedding retry
counts. This reader deliberately cannot certify a one-provider-attempt policy.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, TypeVar

import httpx
from pydantic import BaseModel, Field, SecretStr, StrictBool, ValidationError

Count = Annotated[int, Field(ge=0, strict=True)]
Routes = list[dict[str, list[str]] | str]
_RESPONSE_BYTES = 4 * 1024 * 1024
_RETRY_ERRORS = frozenset({
    "BadRequestErrorRetries", "AuthenticationErrorRetries", "TimeoutErrorRetries",
    "RateLimitErrorRetries", "ContentPolicyViolationErrorRetries", "InternalServerErrorRetries",
})
_LIMITATIONS = (
    "provider_sdk_retry_policy_unobservable",
    "effective_content_policy_fallbacks_unobservable",
    "per_request_policy_overrides_unobservable",
    "management_snapshot_not_atomic",
)


class NativeInvocationPolicy(BaseModel):
    num_retries: Count | None = None
    max_retries: Count | None = None
    silent_model: str | None = None
    fallbacks: Routes | None = None
    default_fallbacks: Routes | None = None
    context_window_fallbacks: Routes | None = None
    content_policy_fallbacks: Routes | None = None


class NativeRouterPolicy(NativeInvocationPolicy):
    retry_policy: dict[str, Count | None] | None = None
    model_group_retry_policy: dict[str, dict[str, Count | None]] | None = None
    enable_weighted_failover: StrictBool | None = None
    default_litellm_params: NativeInvocationPolicy | None = None


class NativeRouterSettings(BaseModel):
    current_values: NativeRouterPolicy


class NativeRouterMemory(BaseModel):
    # The rest of this authenticated endpoint can contain callback secrets.
    # Pydantic ignores it; never log, retain or hash the unvalidated response.
    router_settings: NativeRouterPolicy


class NativeDeploymentPolicy(NativeInvocationPolicy):
    model: str
    order: Count | None = None


class NativeDeployment(BaseModel):
    model_name: str
    litellm_params: NativeDeploymentPolicy


class NativeModelPolicies(BaseModel):
    data: list[NativeDeployment]


@dataclass(frozen=True)
class GatewayPolicySnapshot:
    """Compatible means only that the observed fields contain no detected risk.

    Neither compatibility nor equal start/end hashes removes the listed native
    observability gaps. Consumers must never promote either to verified=True.
    """

    models: tuple[str, ...]
    captured_at: datetime
    observed_compatible: bool
    evidence_sha256: str
    reasons: tuple[str, ...]

    @property
    def verified(self) -> Literal[False]:
        return False


class NativePolicyReadError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _routes_apply(routes: Routes | None, models: frozenset[str]) -> bool:
    return any(
        bool(route) if isinstance(route, str)
        else any(targets and (name in models or name == "*") for name, targets in route.items())
        for route in routes or []
    )


def _invocation_issues(policy: NativeInvocationPolicy, models: frozenset[str], prefix: str) -> set[str]:
    issues = set()
    for field in ("num_retries", "max_retries"):
        if getattr(policy, field) not in (None, 0):
            issues.add(f"{prefix}_retries_enabled")
    if policy.silent_model:
        issues.add(f"{prefix}_silent_model_enabled")
    for field in ("fallbacks", "default_fallbacks", "context_window_fallbacks", "content_policy_fallbacks"):
        if _routes_apply(getattr(policy, field), models):
            issues.add(f"{prefix}_{field}_enabled")
    return issues


def _router_issues(policy: NativeRouterPolicy, models: frozenset[str], prefix: str) -> set[str]:
    issues = _invocation_issues(policy, models, prefix)
    required = {"num_retries", "retry_policy", "model_group_retry_policy", "fallbacks", "context_window_fallbacks"}
    if prefix == "reported":
        required.add("content_policy_fallbacks")
    else:
        required.add("enable_weighted_failover")
    if not required.issubset(policy.model_fields_set) or policy.num_retries is None:
        issues.add(f"{prefix}_policy_fields_missing")
    policies = [policy.retry_policy or {}]
    policies.extend(value for name, value in (policy.model_group_retry_policy or {}).items() if name in models or name == "*")
    if any(key not in _RETRY_ERRORS or value not in (None, 0) for retry_policy in policies for key, value in retry_policy.items()):
        issues.add(f"{prefix}_retry_policy_enabled_or_unsupported")
    if policy.enable_weighted_failover:
        issues.add(f"{prefix}_weighted_failover_enabled")
    if policy.default_litellm_params is not None:
        issues.update(_invocation_issues(policy.default_litellm_params, models, f"{prefix}_defaults"))
    return issues


def assess_native_policy(
    *, models: frozenset[str], reported: NativeRouterPolicy,
    memory: NativeRouterPolicy, deployments: NativeModelPolicies,
) -> GatewayPolicySnapshot:
    if not models or any(not isinstance(model, str) or not model.strip() for model in models):
        raise ValueError("Explicit nonempty model aliases are required")
    issues = _router_issues(reported, models, "reported") | _router_issues(memory, models, "memory")
    selected = [row for row in deployments.data if row.model_name in models]
    if models != {row.model_name for row in selected}:
        issues.add("selected_model_deployments_missing")
    for row in selected:
        params = row.litellm_params
        issues.update(_invocation_issues(params, frozenset({row.model_name}), "deployment"))
        if not {"num_retries", "max_retries"}.issubset(params.model_fields_set) or params.num_retries is None or params.max_retries is None:
            issues.add("deployment_retry_fields_missing")
        if params.order not in (None, 0):
            issues.add("deployment_priority_failover_present")
    # Preserve missing vs explicit null. DTO dumps whitelist fields and discard
    # callback secrets, deployment keys/base URLs and unrelated native metadata.
    evidence = {
        "models": sorted(models),
        "reported": reported.model_dump(exclude_unset=True),
        "memory": memory.model_dump(exclude_unset=True),
        "deployments": sorted(
            (row.model_dump(exclude_unset=True) for row in selected),
            key=lambda row: json.dumps(row, sort_keys=True),
        ),
    }
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return GatewayPolicySnapshot(tuple(sorted(models)), datetime.now(UTC), not issues, digest, tuple(sorted(issues | set(_LIMITATIONS))))


_Boundary = TypeVar("_Boundary", bound=BaseModel)


async def _read_boundary(client: httpx.AsyncClient, path: str, schema: type[_Boundary]) -> _Boundary:
    async with client.stream("GET", path) as response:
        if response.status_code != 200:
            raise NativePolicyReadError("native_policy_http_error", status_code=response.status_code)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > _RESPONSE_BYTES:
                raise NativePolicyReadError("native_policy_response_too_large")
            body.extend(chunk)
    return schema.model_validate_json(body)


class NativeGatewayPolicyReader:
    def __init__(self, *, base_url: str, api_key: SecretStr, request_timeout_s: float, total_timeout_s: float):
        url = httpx.URL(base_url)
        if url.scheme not in {"http", "https"} or not url.host or url.userinfo or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError("An explicit trusted gateway management root without credentials/query is required")
        if not api_key.get_secret_value() or any(not math.isfinite(value) or value <= 0 for value in (request_timeout_s, total_timeout_s)):
            raise ValueError("An explicit key and positive timeouts are required")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._request_timeout_s = request_timeout_s
        self._total_timeout_s = total_timeout_s

    async def snapshot(self, *, models: frozenset[str]) -> GatewayPolicySnapshot:
        if not models or any(not isinstance(model, str) or not model.strip() for model in models):
            raise ValueError("Explicit nonempty model aliases are required")
        try:
            async with asyncio.timeout(self._total_timeout_s):
                async with httpx.AsyncClient(
                    base_url=self._base_url, headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    timeout=self._request_timeout_s, follow_redirects=False, trust_env=False,
                ) as client:
                    reported = await _read_boundary(client, "/router/settings", NativeRouterSettings)
                    memory = await _read_boundary(client, "/get/config/callbacks", NativeRouterMemory)
                    deployments = await _read_boundary(client, "/model/info", NativeModelPolicies)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise NativePolicyReadError("native_policy_read_timeout") from exc
        except httpx.HTTPError as exc:
            raise NativePolicyReadError("native_policy_connection_error") from exc
        except ValidationError:
            raise NativePolicyReadError("invalid_native_policy_payload") from None
        return assess_native_policy(models=models, reported=reported.current_values, memory=memory.router_settings, deployments=deployments)
