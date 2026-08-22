"""Minimal FlyteAdmin REST client for Learning Agent orchestration.

Talks to flyteadmin's HTTP gateway directly (no flytekit dependency in the
API process) so the workflow boundary stays a plain serialized HTTP contract.
Every method targets a real control plane; nothing here fakes orchestration.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

_API = "/api/v1"

# flyteadmin execution phases (flyteidl core.WorkflowExecution.Phase).
FLYTE_TERMINAL_PHASES = frozenset({"SUCCEEDED", "FAILED", "ABORTED", "TIMED_OUT"})
FLYTE_FAILURE_PHASES = frozenset({"FAILED", "TIMED_OUT"})
FLYTE_ABORT_PHASES = frozenset({"ABORTED", "ABORTING"})


class FlyteUnavailableError(RuntimeError):
    """Raised when the configured Flyte control plane cannot be used."""


def _base(url: str) -> str:
    base = str(url or "").strip().rstrip("/")
    if not base:
        raise FlyteUnavailableError("Flyte admin base URL is empty")
    if base.endswith(_API):
        base = base[: -len(_API)]
    return base


def new_execution_name() -> str:
    """DNS-1123-safe execution name (lowercase, starts with a letter, 20 chars)."""
    return "ra" + secrets.token_hex(9)


def _literal(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        primitive: dict[str, Any] = {"boolean": value}
    elif isinstance(value, int):
        primitive = {"integer": str(value)}
    elif isinstance(value, float):
        primitive = {"float_value": value}
    else:
        primitive = {"string_value": str(value)}
    return {"scalar": {"primitive": primitive}}


@dataclass(frozen=True)
class FlyteLaunchPlanRef:
    project: str
    domain: str
    name: str
    version: str


@dataclass(frozen=True)
class FlyteExecutionState:
    project: str
    domain: str
    name: str
    phase: str
    error_message: str | None = None
    abort_cause: str | None = None

    @property
    def terminal(self) -> bool:
        return self.phase in FLYTE_TERMINAL_PHASES


class FlyteAdminClient:
    """Synchronous REST client; safe to call from worker threads."""

    def __init__(self, admin_base_url: str, *, timeout_s: float = 5.0) -> None:
        self.admin_base_url = _base(admin_base_url)
        self._timeout = timeout_s

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.admin_base_url}{_API}{path}"
        try:
            response = httpx.request(
                method,
                url,
                params=params,
                json=payload,
                timeout=self._timeout,
                headers={"Accept": "application/json"},
            )
        except Exception as exc:
            raise FlyteUnavailableError(
                f"Flyte admin unreachable at {self.admin_base_url}: {type(exc).__name__}"
            ) from exc
        if response.status_code == 404:
            raise FlyteUnavailableError(f"Flyte admin has no {path} ({response.text[:300]})")
        if response.status_code >= 400:
            raise FlyteUnavailableError(
                f"Flyte admin {method} {path} failed ({response.status_code}): {response.text[:300]}"
            )
        try:
            return response.json() if response.text else {}
        except Exception as exc:
            raise FlyteUnavailableError(f"Flyte admin returned non-JSON for {path}") from exc

    def healthcheck(self) -> None:
        url = f"{self.admin_base_url}/healthcheck"
        try:
            response = httpx.get(url, timeout=self._timeout)
        except Exception as exc:
            raise FlyteUnavailableError(
                f"Flyte admin unreachable at {self.admin_base_url}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise FlyteUnavailableError(f"Flyte admin healthcheck failed ({response.status_code})")

    def resolve_launch_plan(self, project: str, domain: str, name: str) -> FlyteLaunchPlanRef:
        """Return the most recently registered version of a named launch plan."""
        project = str(project or "").strip()
        domain = str(domain or "").strip()
        name = str(name or "").strip()
        if not (project and domain and name):
            raise FlyteUnavailableError("Flyte project, domain, and launch plan name are required")
        payload = self._request(
            "GET",
            f"/launch_plans/{quote(project, safe='')}/{quote(domain, safe='')}/{quote(name, safe='')}",
            params={"limit": 1, "sort_by.key": "created_at", "sort_by.direction": "DESCENDING"},
        )
        plans = payload.get("launch_plans") or payload.get("launchPlans") or []
        if not plans:
            raise FlyteUnavailableError(
                f"Launch plan {name!r} is not registered in Flyte project {project}/{domain}"
            )
        identifier = plans[0].get("id") or {}
        version = str(identifier.get("version") or "").strip()
        if not version:
            raise FlyteUnavailableError(f"Flyte returned launch plan {name!r} without a version")
        return FlyteLaunchPlanRef(project=project, domain=domain, name=name, version=version)

    def create_execution(
        self,
        launch_plan: FlyteLaunchPlanRef,
        *,
        inputs: dict[str, Any],
        execution_name: str | None = None,
        principal: str = "ragweld",
    ) -> str:
        name = str(execution_name or "").strip() or new_execution_name()
        payload = {
            "project": launch_plan.project,
            "domain": launch_plan.domain,
            "name": name,
            "spec": {
                "launch_plan": {
                    "resource_type": "LAUNCH_PLAN",
                    "project": launch_plan.project,
                    "domain": launch_plan.domain,
                    "name": launch_plan.name,
                    "version": launch_plan.version,
                },
                "metadata": {"mode": "MANUAL", "principal": principal},
            },
            "inputs": {"literals": {key: _literal(value) for key, value in inputs.items()}},
        }
        created = self._request("POST", "/executions", payload=payload)
        identifier = created.get("id") or {}
        created_name = str(identifier.get("name") or "").strip()
        if not created_name:
            raise FlyteUnavailableError("Flyte admin did not return an execution name")
        return created_name

    def get_execution(self, project: str, domain: str, name: str) -> FlyteExecutionState:
        payload = self._request(
            "GET",
            f"/executions/{quote(project, safe='')}/{quote(domain, safe='')}/{quote(name, safe='')}",
        )
        closure = payload.get("closure") or {}
        phase = str(closure.get("phase") or "UNDEFINED").strip().upper()
        error = closure.get("error") or {}
        abort = closure.get("abort_metadata") or closure.get("abortMetadata") or {}
        abort_cause = str(abort.get("cause") or closure.get("abort_cause") or closure.get("abortCause") or "").strip() or None
        return FlyteExecutionState(
            project=project,
            domain=domain,
            name=name,
            phase=phase,
            error_message=str(error.get("message") or "").strip() or None,
            abort_cause=abort_cause,
        )

    def terminate_execution(self, project: str, domain: str, name: str, *, cause: str) -> None:
        self._request(
            "DELETE",
            f"/executions/{quote(project, safe='')}/{quote(domain, safe='')}/{quote(name, safe='')}",
            payload={"cause": str(cause or "terminated by ragweld")[:500]},
        )
