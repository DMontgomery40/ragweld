"""One client for ``POST /v1/systemone``, whichever backend ``system_one.provider`` names.

TypeSafe's hosted Jev and a self-hosted ``laya-serve`` share the request/answer contract,
so one httpx client serves both; only the base URL and the credential differ. A call is
bounded by ``system_one.timeout_s`` as a whole: 408, 429 and 5xx answers (529 Overloaded
included) and connection failures are retried with exponential backoff that honours
``Retry-After``/``retry-after-ms``, and the backoff never sleeps past the budget.

Failures are typed and fail closed. There is no silent switch to the other backend and
no default answer: a caller that needs a judgment it cannot get raises.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any

import httpx
from pydantic import ValidationError

from server.models.system_one import (
    SystemOneConfig,
    SystemOneNoul,
    SystemOneRequest,
    SystemOneResponse,
)
from server.observability.metrics import SYSTEM_ONE_LATENCY_SECONDS, SYSTEM_ONE_REQUESTS_TOTAL

ENDPOINT_PATH = "/v1/systemone"
TYPESAFE_API_KEY_ENV = "TYPESAFE_API_KEY"
RETRY_STATUSES = frozenset({408, 429, *range(500, 600)})
RATE_LIMIT_STATUSES = frozenset({429, 529})
BACKOFF_INITIAL_S = 0.5
BACKOFF_MAX_S = 5.0
BACKOFF_JITTER = 0.25
_ERROR_BODY_CHARS = 300


class SystemOneError(RuntimeError):
    """A System One call that did not produce every requested answer."""

    def __init__(self, message: str, *, provider: str, outcome: str, status: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.outcome = outcome
        self.status = status


class SystemOneUnavailableError(SystemOneError):
    """The backend cannot be called: missing credential, or unreachable after retries."""


class SystemOneTimeoutError(SystemOneError):
    """The call exhausted ``system_one.timeout_s`` (retries and backoff included)."""


class SystemOneHTTPError(SystemOneError):
    """The backend answered with an error status (after retries for retryable ones)."""


class SystemOneResponseError(SystemOneError):
    """A 2xx answer whose body does not answer every question with a Noul."""


def system_one_base_url(cfg: SystemOneConfig) -> str:
    raw = cfg.typesafe_base_url if cfg.provider == "typesafe" else cfg.laya_base_url
    return str(raw).strip().rstrip("/")


def system_one_headers(cfg: SystemOneConfig) -> dict[str, str]:
    """Request headers; TypeSafe needs ``TYPESAFE_API_KEY``, a self-hosted Laya needs none."""
    headers = {"Content-Type": "application/json", "User-Agent": "ragweld-system-one"}
    if cfg.provider == "typesafe":
        key = str(os.environ.get(TYPESAFE_API_KEY_ENV) or "").strip()
        if not key:
            raise SystemOneUnavailableError(
                f"system_one.provider=typesafe needs {TYPESAFE_API_KEY_ENV} in the server environment",
                provider=cfg.provider,
                outcome="unavailable",
            )
        headers["Authorization"] = f"Bearer {key}"
    return headers


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    """The server's requested wait from ``retry-after-ms`` or ``Retry-After`` (seconds), if any."""
    raw_ms = headers.get("retry-after-ms")
    if raw_ms:
        try:
            return max(0.0, float(raw_ms) / 1000.0)
        except ValueError:
            pass
    raw = headers.get("retry-after")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None
    return None


def backoff_delay(attempt: int, *, retry_after: float | None) -> float:
    """Exponential backoff for retry ``attempt`` (0-based), jittered, or the server's own wait."""
    if retry_after is not None:
        return retry_after
    base = min(BACKOFF_MAX_S, BACKOFF_INITIAL_S * (2.0**attempt))
    return base * (1.0 - BACKOFF_JITTER * random.random())


def _outcome_for_status(status: int) -> str:
    return "rate_limited" if status in RATE_LIMIT_STATUSES else "http_error"


class SystemOneClient:
    """Async client for one configured System One backend; use as an async context manager."""

    def __init__(self, cfg: SystemOneConfig) -> None:
        self.cfg = cfg
        self.provider = str(cfg.provider)
        self.url = f"{system_one_base_url(cfg)}{ENDPOINT_PATH}"
        self._headers = system_one_headers(cfg)
        self._slots = asyncio.Semaphore(int(cfg.max_concurrency))
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SystemOneClient:
        self._http = httpx.AsyncClient(
            headers=self._headers,
            timeout=float(self.cfg.timeout_s),
            limits=httpx.Limits(max_connections=int(self.cfg.max_concurrency)),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def ask(self, state: Any, questions: Mapping[str, SystemOneNoul]) -> SystemOneResponse:
        """One request; every question must come back as a Noul answer under its own id."""
        if self._http is None:
            raise RuntimeError("SystemOneClient must be entered (async with) before use")
        body = SystemOneRequest(model=str(self.cfg.model), state=state, questions=dict(questions))
        payload = body.model_dump(mode="json", exclude_none=True)
        async with self._slots:
            started = time.perf_counter()
            outcome = "ok"
            try:
                response = await self._post_with_retries(payload, started=started)
                return self._validated(response, expected=list(questions))
            except SystemOneError as exc:
                outcome = exc.outcome
                raise
            finally:
                SYSTEM_ONE_REQUESTS_TOTAL.labels(provider=self.provider, outcome=outcome).inc()
                SYSTEM_ONE_LATENCY_SECONDS.labels(provider=self.provider).observe(time.perf_counter() - started)

    async def nouls(self, state: Any, questions: Mapping[str, SystemOneNoul]) -> dict[str, float]:
        response = await self.ask(state, questions)
        return {qid: float(response.answers[qid].noul) for qid in questions}

    async def _post_with_retries(self, payload: dict[str, Any], *, started: float) -> httpx.Response:
        assert self._http is not None
        deadline = started + float(self.cfg.timeout_s)
        max_retries = int(self.cfg.max_retries)
        attempt = 0
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise SystemOneTimeoutError(
                    f"System One ({self.provider}) exceeded system_one.timeout_s={self.cfg.timeout_s}",
                    provider=self.provider,
                    outcome="timeout",
                )
            retry_after: float | None = None
            try:
                response = await self._http.post(self.url, json=payload, timeout=remaining)
            except httpx.TimeoutException as exc:
                failure: SystemOneError = SystemOneTimeoutError(
                    f"System One ({self.provider}) timed out at {self.url}: {type(exc).__name__}",
                    provider=self.provider,
                    outcome="timeout",
                )
            except httpx.TransportError as exc:
                failure = SystemOneUnavailableError(
                    f"System One ({self.provider}) unreachable at {self.url}: {type(exc).__name__}: {exc}",
                    provider=self.provider,
                    outcome="unavailable",
                )
            else:
                if response.status_code < 400:
                    return response
                detail = response.text[:_ERROR_BODY_CHARS]
                failure = SystemOneHTTPError(
                    f"System One ({self.provider}) answered HTTP {response.status_code}: {detail}",
                    provider=self.provider,
                    outcome=_outcome_for_status(response.status_code),
                    status=response.status_code,
                )
                if response.status_code not in RETRY_STATUSES:
                    raise failure
                retry_after = retry_after_seconds(response.headers)
            if attempt >= max_retries:
                raise failure
            delay = backoff_delay(attempt, retry_after=retry_after)
            if time.perf_counter() + delay >= deadline:
                raise failure
            await asyncio.sleep(delay)
            attempt += 1

    def _validated(self, response: httpx.Response, *, expected: list[str]) -> SystemOneResponse:
        try:
            parsed = SystemOneResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise SystemOneResponseError(
                f"System One ({self.provider}) returned a body that is not a System One answer: {exc}",
                provider=self.provider,
                outcome="invalid_response",
            ) from exc
        missing = [qid for qid in expected if qid not in parsed.answers]
        if missing:
            raise SystemOneResponseError(
                f"System One ({self.provider}) did not answer {missing}",
                provider=self.provider,
                outcome="invalid_response",
            )
        return parsed
