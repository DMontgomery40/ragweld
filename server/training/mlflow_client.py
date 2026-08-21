"""Minimal MLflow Tracking REST client for Learning Agent runs.

Uses the MLflow REST API directly (no mlflow package dependency) so the
tracking boundary stays a plain serialized HTTP contract. All methods talk to
a real MLflow server; nothing here fakes success.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_API = "/api/2.0/mlflow"


class MlflowUnavailableError(RuntimeError):
    """Raised when the configured MLflow tracking server cannot be used."""


def _base(url: str) -> str:
    base = str(url or "").strip().rstrip("/")
    if not base:
        raise MlflowUnavailableError("MLflow tracking URL is empty")
    return base


@dataclass
class MlflowRunHandle:
    tracking_url: str
    experiment_id: str
    run_id: str

    @property
    def run_url(self) -> str:
        return f"{self.tracking_url}/#/experiments/{self.experiment_id}/runs/{self.run_id}"


class MlflowClient:
    """Synchronous REST client; safe to call from worker threads."""

    def __init__(self, tracking_url: str, *, timeout_s: float = 5.0) -> None:
        self.tracking_url = _base(tracking_url)
        self._timeout = timeout_s

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.tracking_url}{_API}{path}",
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise MlflowUnavailableError(
                f"MLflow tracking server unreachable at {self.tracking_url}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise MlflowUnavailableError(
                f"MLflow API {path} failed ({response.status_code}): {response.text[:300]}"
            )
        try:
            return response.json() if response.text else {}
        except Exception:
            return {}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        try:
            response = httpx.get(
                f"{self.tracking_url}{_API}{path}",
                params=params,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise MlflowUnavailableError(
                f"MLflow tracking server unreachable at {self.tracking_url}: {type(exc).__name__}"
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise MlflowUnavailableError(
                f"MLflow API {path} failed ({response.status_code}): {response.text[:300]}"
            )
        return response.json()

    def ensure_experiment(self, name: str) -> str:
        existing = self._get("/experiments/get-by-name", {"experiment_name": name})
        if existing is not None:
            experiment = existing.get("experiment") or {}
            experiment_id = str(experiment.get("experiment_id") or "").strip()
            if experiment_id:
                return experiment_id
        created = self._post("/experiments/create", {"name": name})
        experiment_id = str(created.get("experiment_id") or "").strip()
        if not experiment_id:
            raise MlflowUnavailableError(f"MLflow did not return an experiment id for {name!r}")
        return experiment_id

    def create_run(self, experiment_id: str, *, run_name: str, tags: dict[str, str]) -> MlflowRunHandle:
        payload = {
            "experiment_id": experiment_id,
            "run_name": run_name,
            "start_time": int(time.time() * 1000),
            "tags": [{"key": k, "value": str(v)} for k, v in tags.items()],
        }
        created = self._post("/runs/create", payload)
        run = created.get("run") or {}
        run_id = str(((run.get("info") or {}).get("run_id")) or "").strip()
        if not run_id:
            raise MlflowUnavailableError("MLflow did not return a run id")
        return MlflowRunHandle(tracking_url=self.tracking_url, experiment_id=experiment_id, run_id=run_id)

    def log_params(self, run_id: str, params: dict[str, Any]) -> None:
        self._post(
            "/runs/log-batch",
            {
                "run_id": run_id,
                "params": [{"key": k, "value": str(v)[:500]} for k, v in params.items()],
            },
        )

    def log_metric(self, run_id: str, key: str, value: float, *, step: int | None = None) -> None:
        self._post(
            "/runs/log-metric",
            {
                "run_id": run_id,
                "key": key,
                "value": float(value),
                "timestamp": int(time.time() * 1000),
                "step": int(step or 0),
            },
        )

    def set_terminated(self, run_id: str, *, status: str) -> None:
        """status: FINISHED | FAILED | KILLED"""
        self._post(
            "/runs/update",
            {
                "run_id": run_id,
                "status": status,
                "end_time": int(time.time() * 1000),
            },
        )

    def log_json_artifact(self, handle: MlflowRunHandle, *, name: str, payload: dict[str, Any]) -> None:
        """Upload a JSON document via the proxied artifact API (--serve-artifacts)."""
        url = (
            f"{self.tracking_url}/api/2.0/mlflow-artifacts/artifacts/"
            f"{handle.experiment_id}/{handle.run_id}/artifacts/{name}"
        )
        body = json.dumps(payload, indent=2, sort_keys=True, default=str).encode("utf-8")
        try:
            response = httpx.put(url, content=body, timeout=self._timeout)
        except Exception as exc:
            raise MlflowUnavailableError(
                f"MLflow artifact upload unreachable at {self.tracking_url}: {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise MlflowUnavailableError(
                f"MLflow artifact upload failed ({response.status_code}): {response.text[:300]}"
            )
