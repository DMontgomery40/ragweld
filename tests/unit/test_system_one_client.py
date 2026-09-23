"""The System One client against a real local HTTP server scripted to answer like a backend.

No mocks: every case is a real ``POST /v1/systemone`` over a socket to a stdlib server that
replays a scripted sequence of responses and records what it received. Covers the request
contract for both backends, the retry state machine (retryable vs terminal statuses,
Retry-After, exhaustion), typed failures and the per-call metrics.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from prometheus_client import REGISTRY

from server.models.system_one import SystemOneConfig, SystemOneNoul, SystemOneNoulCriteria
from server.system_one.client import (
    BACKOFF_INITIAL_S,
    BACKOFF_MAX_S,
    TYPESAFE_API_KEY_ENV,
    SystemOneClient,
    SystemOneHTTPError,
    SystemOneResponseError,
    SystemOneTimeoutError,
    SystemOneUnavailableError,
    backoff_delay,
    retry_after_seconds,
)

pytestmark = pytest.mark.asyncio

QUERY = "Which figure shows the lunar module pitch attitude time history during powered descent?"
PASSAGE = "Figure 5-5 shows the pitch attitude time history during the powered descent phase."
QUESTION = SystemOneNoul(
    instructions="Does `candidate_passage` contain information that answers `query`?",
    criteria=SystemOneNoulCriteria(true="It answers the query.", false="It is about something else."),
)
STATE = {"query": QUERY, "candidate_passage": PASSAGE}
FAST_RETRY = {"retry-after-ms": "5"}


def _answer(noul: float = 0.9, **extra: Any) -> dict[str, Any]:
    return {
        "model": "jev-1.13.0",
        "answers": {"answers_query": {"type": "noul", "noul": noul, **extra}},
        "usage": {"input_tokens": 120, "output_tokens": 0},
    }


@dataclass
class _Script:
    responses: list[tuple[int, dict[str, str], Any]]
    received: list[dict[str, Any]] = field(default_factory=list)
    delay_s: float = 0.0


def _handler(script: _Script) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length)
            script.received.append(
                {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "json": json.loads(body)}
            )
            if script.delay_s:
                time.sleep(script.delay_s)
            status, headers, payload = script.responses.pop(0) if script.responses else (500, {}, {"error": "empty"})
            raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

    return Handler


@contextmanager
def _backend(script: _Script) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(script))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def _env(name: str, value: str | None) -> Iterator[None]:
    saved = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = saved


def _laya(base_url: str, **overrides: Any) -> SystemOneConfig:
    return SystemOneConfig(provider="laya", laya_base_url=base_url, **overrides)


def _count(provider: str, outcome: str) -> float:
    value = REGISTRY.get_sample_value("tribrid_system_one_requests_total", {"provider": provider, "outcome": outcome})
    return float(value or 0.0)


async def test_typesafe_request_carries_the_key_model_state_and_typed_question() -> None:
    script = _Script(responses=[(200, {}, _answer(0.93))])
    with _backend(script) as base, _env(TYPESAFE_API_KEY_ENV, "  ts-live-key\n"):
        cfg = SystemOneConfig(provider="typesafe", typesafe_base_url=base + "/")
        async with SystemOneClient(cfg) as client:
            nouls = await client.nouls(STATE, {"answers_query": QUESTION})
    assert nouls == {"answers_query": pytest.approx(0.93)}
    (request,) = script.received
    assert request["path"] == "/v1/systemone"
    assert request["headers"]["authorization"] == "Bearer ts-live-key"
    assert request["json"] == {
        "model": "jev-latest",
        "state": STATE,
        "questions": {
            "answers_query": {
                "type": "noul",
                "instructions": QUESTION.instructions,
                "criteria": {"true": "It answers the query.", "false": "It is about something else."},
            }
        },
    }


async def test_laya_needs_no_credential_and_its_extra_answer_fields_are_ignored() -> None:
    script = _Script(responses=[(200, {}, {**_answer(0.21, confidence=0.79, action={"act_probability": 1.0}), "routing": {"model": "english"}})])
    with _backend(script) as base, _env(TYPESAFE_API_KEY_ENV, None):
        async with SystemOneClient(_laya(base, model="english")) as client:
            response = await client.ask(STATE, {"answers_query": QUESTION})
    assert response.answers["answers_query"].noul == pytest.approx(0.21)
    assert response.usage.input_tokens == 120
    (request,) = script.received
    assert "authorization" not in request["headers"]
    assert request["json"]["model"] == "english"


async def test_typesafe_without_a_key_fails_before_any_request() -> None:
    with _env(TYPESAFE_API_KEY_ENV, None), pytest.raises(SystemOneUnavailableError, match=TYPESAFE_API_KEY_ENV):
        SystemOneClient(SystemOneConfig(provider="typesafe"))


@pytest.mark.parametrize(
    ("responses", "requests_made"),
    [
        ([(429, FAST_RETRY, {"error": "rate"}), (200, {}, _answer())], 2),
        ([(529, FAST_RETRY, {"error": "overloaded"}), (200, {}, _answer())], 2),
        ([(503, FAST_RETRY, {}), (500, FAST_RETRY, {}), (200, {}, _answer())], 3),
        ([(408, FAST_RETRY, {}), (200, {}, _answer())], 2),
    ],
)
async def test_retryable_statuses_are_retried_until_an_answer(
    responses: list[tuple[int, dict[str, str], Any]], requests_made: int
) -> None:
    script = _Script(responses=list(responses))
    with _backend(script) as base:
        async with SystemOneClient(_laya(base)) as client:
            nouls = await client.nouls(STATE, {"answers_query": QUESTION})
    assert nouls["answers_query"] == pytest.approx(0.9)
    assert len(script.received) == requests_made


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_terminal_statuses_fail_at_once_without_retrying(status: int) -> None:
    script = _Script(responses=[(status, {}, {"detail": "malformed question"}), (200, {}, _answer())])
    before = _count("laya", "http_error")
    with _backend(script) as base:
        async with SystemOneClient(_laya(base)) as client:
            with pytest.raises(SystemOneHTTPError) as caught:
                await client.nouls(STATE, {"answers_query": QUESTION})
    assert caught.value.status == status
    assert caught.value.outcome == "http_error"
    assert "malformed question" in str(caught.value)
    assert len(script.received) == 1
    assert _count("laya", "http_error") == before + 1


async def test_rate_limit_exhaustion_is_typed_and_counted_once() -> None:
    script = _Script(responses=[(429, FAST_RETRY, {"error": "rate"})] * 3)
    before = _count("laya", "rate_limited")
    with _backend(script) as base:
        async with SystemOneClient(_laya(base, max_retries=2)) as client:
            with pytest.raises(SystemOneHTTPError) as caught:
                await client.nouls(STATE, {"answers_query": QUESTION})
    assert caught.value.outcome == "rate_limited"
    assert len(script.received) == 3
    assert _count("laya", "rate_limited") == before + 1


async def test_retries_disabled_means_one_attempt() -> None:
    script = _Script(responses=[(429, FAST_RETRY, {}), (200, {}, _answer())])
    with _backend(script) as base:
        async with SystemOneClient(_laya(base, max_retries=0)) as client:
            with pytest.raises(SystemOneHTTPError):
                await client.nouls(STATE, {"answers_query": QUESTION})
    assert len(script.received) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "jev", "answers": {}, "usage": {"input_tokens": 1, "output_tokens": 0}},
        {"model": "jev", "answers": {"answers_query": {"type": "noul", "noul": 1.5}}},
        {"model": "jev", "answers": {"answers_query": {"type": "choice", "choice": "a"}}},
        "not json at all",
    ],
)
async def test_a_2xx_body_that_does_not_answer_every_question_is_a_typed_failure(payload: Any) -> None:
    script = _Script(responses=[(200, {}, payload)])
    before = _count("laya", "invalid_response")
    with _backend(script) as base:
        async with SystemOneClient(_laya(base)) as client:
            with pytest.raises(SystemOneResponseError):
                await client.nouls(STATE, {"answers_query": QUESTION})
    assert _count("laya", "invalid_response") == before + 1


async def test_the_call_budget_bounds_a_stalled_backend() -> None:
    script = _Script(responses=[(200, {}, _answer())], delay_s=2.5)
    started = time.perf_counter()
    with _backend(script) as base:
        async with SystemOneClient(_laya(base, timeout_s=1.0, max_retries=3)) as client:
            with pytest.raises(SystemOneTimeoutError):
                await client.nouls(STATE, {"answers_query": QUESTION})
    assert time.perf_counter() - started < 2.4


async def test_an_unreachable_backend_is_unavailable_not_a_default_answer() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    async with SystemOneClient(_laya(f"http://127.0.0.1:{port}", max_retries=0)) as client:
        with pytest.raises(SystemOneUnavailableError):
            await client.nouls(STATE, {"answers_query": QUESTION})


async def test_a_successful_call_is_counted_as_ok() -> None:
    script = _Script(responses=[(200, {}, _answer())])
    before = _count("laya", "ok")
    with _backend(script) as base:
        async with SystemOneClient(_laya(base)) as client:
            await client.nouls(STATE, {"answers_query": QUESTION})
    assert _count("laya", "ok") == before + 1


def test_backoff_doubles_to_the_cap_and_honours_the_servers_wait() -> None:
    for attempt in range(6):
        delay = backoff_delay(attempt, retry_after=None)
        ceiling = min(BACKOFF_MAX_S, BACKOFF_INITIAL_S * 2**attempt)
        assert 0.75 * ceiling <= delay <= ceiling
    assert backoff_delay(0, retry_after=2.0) == 2.0
    assert retry_after_seconds({"retry-after-ms": "250"}) == pytest.approx(0.25)
    assert retry_after_seconds({"retry-after": "3"}) == pytest.approx(3.0)
    assert retry_after_seconds({"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}) is None
    assert retry_after_seconds({}) is None
