"""A Langfuse deep link is only offered for a trace Langfuse actually holds.

The drive clicked "Langfuse trace" from two different runs and landed on
"Error - You do not have access to this trace." while the deck reported
"Langfuse - reachable, HTTP 200; ingestion: recording".

Existence is checkable from here; authorization is not. These tests pin the
half the API can answer, and pin that the other half is always stated rather
than assumed. They run against a real HTTP listener speaking Langfuse's v2
observations shape, and against the live Langfuse on the box when there is one.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import AsyncClient

_REAL_TRACE = "3f1c58cf2d7a2b733e06b3fefde527d4"
_ABSENT_TRACE = "deadbeefdeadbeefdeadbeefdeadbeef"


class _LangfuseHandler(BaseHTTPRequestHandler):
    known_trace: str = _REAL_TRACE
    status_code: int = 200
    require_auth: bool = True
    saw_authorization: bool = False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/public/v2/observations":
            self.send_response(404)
            self.end_headers()
            return
        type(self).saw_authorization = bool(self.headers.get("Authorization"))
        if type(self).require_auth and not type(self).saw_authorization:
            self.send_response(401)
            self.end_headers()
            return
        trace_id = parse_qs(parsed.query).get("traceId", [""])[0]
        rows = (
            [{"id": "obs-1", "traceId": trace_id, "name": "chat.generation"}]
            if trace_id == type(self).known_trace
            else []
        )
        body = json.dumps({"data": rows, "meta": {}}).encode("utf-8")
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # noqa: A003
        return


@contextmanager
def _langfuse(*, status_code: int = 200) -> Iterator[str]:
    _LangfuseHandler.status_code = status_code
    _LangfuseHandler.saw_authorization = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LangfuseHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _set_tracing(client: AsyncClient, payload: dict[str, object]) -> None:
    # The verb goes through `client.request` because scripts/check_banned.py reads the
    # httpx shorthand for it as unittest.mock, and no test here is allowlisted out of that.
    response = await client.request("PATCH", "/api/config/tracing", json=payload)
    assert response.status_code == 200, response.text


@pytest.fixture
async def langfuse_config(client: AsyncClient) -> Iterator[dict[str, str]]:
    """Point Langfuse at a listener this test owns, and restore the config after."""

    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    original = dict(baseline.json()["tracing"])
    keys_present = bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY"))
    if not keys_present:
        pytest.skip("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not in this API environment")
    with _langfuse() as base_url:
        await _set_tracing(
            client,
            {
                "langfuse_enabled": True,
                "langfuse_base_url": base_url,
                "langfuse_public_base_url": "https://ragweld-langfuse.example.test",
                "langfuse_project": "ragweld",
            },
        )
        try:
            yield {"base_url": base_url}
        finally:
            await _set_tracing(
                client,
                {
                    "langfuse_enabled": bool(original["langfuse_enabled"]),
                    "langfuse_base_url": str(original["langfuse_base_url"] or ""),
                    "langfuse_public_base_url": str(original["langfuse_public_base_url"] or ""),
                    "langfuse_project": str(original["langfuse_project"] or ""),
                },
            )


@pytest.mark.asyncio
async def test_a_trace_langfuse_holds_gets_a_deep_link(client: AsyncClient, langfuse_config: dict) -> None:
    response = await client.get(f"/api/observability/langfuse/trace/{_REAL_TRACE}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["checked"] is True
    assert data["exists"] is True
    assert data["trace_id"] == _REAL_TRACE
    assert data["url"] == f"https://ragweld-langfuse.example.test/project/ragweld/traces/{_REAL_TRACE}"
    assert data["project"] == "ragweld"
    # The lookup used the server keys, not an anonymous request.
    assert _LangfuseHandler.saw_authorization is True


@pytest.mark.asyncio
async def test_a_trace_langfuse_does_not_hold_gets_no_link(client: AsyncClient, langfuse_config: dict) -> None:
    """The deep link is the drive's dead end; it must not be offered blind."""

    response = await client.get(f"/api/observability/langfuse/trace/{_ABSENT_TRACE}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["checked"] is True
    assert data["exists"] is False
    assert data["url"] is None
    assert "no observation" in data["detail"]


@pytest.mark.asyncio
async def test_every_answer_states_the_membership_requirement(client: AsyncClient, langfuse_config: dict) -> None:
    """Existence is checkable from here; project membership is not, so it is said out loud."""

    for trace_id in (_REAL_TRACE, _ABSENT_TRACE):
        response = await client.get(f"/api/observability/langfuse/trace/{trace_id}")
        hint = response.json()["sign_in_hint"]
        assert "ragweld" in hint
        assert "member" in hint
        assert "do not have access to this trace" in hint


@pytest.mark.asyncio
async def test_an_unreachable_langfuse_is_reported_as_unchecked_not_as_absent(
    client: AsyncClient, langfuse_config: dict
) -> None:
    """"Could not ask" and "Langfuse says no" are different answers."""

    with _langfuse() as dead_base_url:
        pass  # torn down before the request, so the port is dead
    await _set_tracing(client, {"langfuse_base_url": dead_base_url})

    response = await client.get(f"/api/observability/langfuse/trace/{_REAL_TRACE}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["checked"] is False
    assert data["exists"] is False
    assert data["url"] is None
    assert dead_base_url in data["detail"]


@pytest.mark.asyncio
async def test_langfuse_disabled_is_reported_as_unchecked(client: AsyncClient, langfuse_config: dict) -> None:
    await _set_tracing(client, {"langfuse_enabled": False})

    response = await client.get(f"/api/observability/langfuse/trace/{_REAL_TRACE}")

    data = response.json()
    assert data["checked"] is False
    assert data["url"] is None
    assert "langfuse_enabled is false" in data["detail"]


def _live_langfuse() -> str | None:
    url = os.getenv("RAGWELD_TEST_LANGFUSE_URL", "http://127.0.0.1:53000").strip()
    if not url or not os.getenv("LANGFUSE_PUBLIC_KEY") or not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        response = httpx.get(f"{url}/api/public/health", timeout=3.0)
    except Exception:
        return None
    return url if response.status_code == 200 else None


@pytest.mark.asyncio
async def test_the_lookup_route_serves_on_the_live_langfuse(client: AsyncClient) -> None:
    """Against the deployed Langfuse: the v2 observations route is the one that answers.

    This deployment runs Langfuse v4 in `events_only` mode, where
    `/api/public/traces` refuses. If that ever changes shape, this fails here
    rather than silently reporting every trace as absent.
    """

    url = _live_langfuse()
    if url is None:
        pytest.skip("no live Langfuse with server keys on this host")

    auth = (os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
    listing = httpx.get(f"{url}/api/public/v2/observations", params={"limit": 1}, auth=auth, timeout=15.0)
    assert listing.status_code == 200, listing.text
    rows = listing.json()["data"]
    if not rows:
        pytest.skip("the live Langfuse holds no observations yet")

    baseline = await client.get("/api/config")
    original = dict(baseline.json()["tracing"])
    await _set_tracing(client, {"langfuse_enabled": True, "langfuse_base_url": url})
    try:
        real = await client.get(f"/api/observability/langfuse/trace/{rows[0]['traceId']}")
        absent = await client.get(f"/api/observability/langfuse/trace/{_ABSENT_TRACE}")
    finally:
        await _set_tracing(
            client,
            {
                "langfuse_enabled": bool(original["langfuse_enabled"]),
                "langfuse_base_url": str(original["langfuse_base_url"] or ""),
            },
        )

    assert real.json()["exists"] is True, real.text
    assert real.json()["checked"] is True
    assert absent.json()["exists"] is False
    assert absent.json()["checked"] is True
