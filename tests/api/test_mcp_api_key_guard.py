"""`mcp.require_api_key` must actually require an API key.

The flag, the `MCP_API_KEY` secret and the docs all described an
`Authorization: Bearer $MCP_API_KEY` check that nothing enforced. That is worse than no
knob: it sat in the one sentence that would talk an operator into removing the Authelia
session in front of the route, leaving `search`, `answer` and `list_corpora` open.

Zero mocks. The guard is exercised as what it is -- an ASGI app -- with a real inner ASGI
app behind it and real HTTP requests through `ASGITransport`. The wiring into the real
mount is asserted separately, because `StreamableHTTPSessionManager.run()` may be called
only once per process and re-importing `server.main` per state is not available.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from server.mcp.auth import MCPApiKeyMissingError, guarded_mcp_app

REPO_ROOT = Path(__file__).resolve().parents[2]
API_KEY = "mcp-test-key-8f2c1d"


async def _inner_app(scope, receive, send) -> None:
    """A real ASGI app standing in for the transport, so 'reached it' is observable."""
    if scope["type"] != "http":  # pragma: no cover - lifespan is not driven here
        return
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"reached the transport"})


def _client(app: object) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://mcp-guard.test")


@pytest.mark.asyncio
async def test_the_flag_off_leaves_the_transport_untouched() -> None:
    """Default behaviour must not change: the guard returns the app itself, not a wrapper."""
    guarded = guarded_mcp_app(_inner_app, require_api_key=False, api_key=None)
    assert guarded is _inner_app

    async with _client(guarded) as client:
        response = await client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 200
    assert response.text == "reached the transport"


@pytest.mark.asyncio
async def test_the_flag_on_refuses_a_request_with_no_bearer() -> None:
    guarded = guarded_mcp_app(_inner_app, require_api_key=True, api_key=API_KEY)

    async with _client(guarded) as client:
        response = await client.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 401
    assert "reached the transport" not in response.text
    # Typed body, and it says how to fix it rather than just refusing.
    detail = response.json()["detail"]
    assert "Authorization: Bearer" in detail
    assert "MCP_API_KEY" in detail
    # Correct HTTP: a 401 has to name the scheme it wants.
    assert response.headers["www-authenticate"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_the_flag_on_refuses_a_wrong_or_malformed_bearer() -> None:
    guarded = guarded_mcp_app(_inner_app, require_api_key=True, api_key=API_KEY)

    async with _client(guarded) as client:
        for header in (
            {"Authorization": f"Bearer {API_KEY}-wrong"},
            {"Authorization": f"Bearer {API_KEY[:-1]}"},  # a prefix must not pass
            {"Authorization": API_KEY},  # no scheme
            {"Authorization": f"Basic {API_KEY}"},  # wrong scheme
            {"Authorization": "Bearer "},
        ):
            response = await client.post("/", headers=header, json={"jsonrpc": "2.0", "id": 1})
            assert response.status_code == 401, header
            assert "reached the transport" not in response.text


@pytest.mark.asyncio
async def test_a_non_ascii_token_is_refused_rather_than_crashing() -> None:
    """401, not a 500 out of the ASGI app.

    The header was decoded with latin-1 -- which maps every byte and never raises -- and
    the result handed to `secrets.compare_digest`, which rejects a non-ASCII `str` with
    `TypeError`. One high byte in the token therefore crashed the app instead of being
    refused. This path becomes publicly reachable the moment `/mcp` moves outside
    forward_auth, so garbage has to be answered, not propagated.
    """
    guarded = guarded_mcp_app(_inner_app, require_api_key=True, api_key=API_KEY)

    async with _client(guarded) as client:
        for token in ("kéy-with-an-accent", "ключ", "🔑", API_KEY + "é"):
            response = await client.post(
                "/",
                headers={"Authorization": f"Bearer {token}".encode()},
                json={"jsonrpc": "2.0", "id": 1},
            )
            assert response.status_code == 401, token
            assert "reached the transport" not in response.text


@pytest.mark.asyncio
async def test_the_scheme_and_token_may_be_separated_by_rfc7235_whitespace() -> None:
    """RFC 7235 allows a run of OWS between the scheme and the credential.

    A single-space `partition(" ")` refused a tab-separated header -- a correct client,
    turned away.
    """
    guarded = guarded_mcp_app(_inner_app, require_api_key=True, api_key=API_KEY)

    async with _client(guarded) as client:
        for raw in (
            f"Bearer\t{API_KEY}",
            f"Bearer  {API_KEY}",
            f"Bearer \t {API_KEY}",
            f"  Bearer {API_KEY}  ",
        ):
            response = await client.post(
                "/", headers={"Authorization": raw}, json={"jsonrpc": "2.0", "id": 1}
            )
            assert response.status_code == 200, repr(raw)
            assert response.text == "reached the transport"


@pytest.mark.asyncio
async def test_the_flag_on_admits_the_configured_bearer() -> None:
    guarded = guarded_mcp_app(_inner_app, require_api_key=True, api_key=API_KEY)

    async with _client(guarded) as client:
        # Case-insensitive scheme, per RFC 7235.
        for header in ({"Authorization": f"Bearer {API_KEY}"}, {"Authorization": f"bearer {API_KEY}"}):
            response = await client.post("/", headers=header, json={"jsonrpc": "2.0", "id": 1})
            assert response.status_code == 200, header
            assert response.text == "reached the transport"


def test_the_flag_on_without_a_key_fails_closed_rather_than_mounting() -> None:
    """The whole point: an operator who turns this on has said the endpoint is exposed.

    Mounting anyway -- because the secret was forgotten -- would serve the corpus set to
    anyone, which is the worst of the three outcomes and the one that looks like success.
    """
    for absent in (None, "", "   "):
        with pytest.raises(MCPApiKeyMissingError) as raised:
            guarded_mcp_app(_inner_app, require_api_key=True, api_key=absent)
        message = str(raised.value)
        assert "MCP_API_KEY" in message
        assert "require_api_key" in message


def test_the_real_mount_goes_through_the_guard() -> None:
    """Structure, because the behaviour above cannot be re-driven per state in-process.

    `StreamableHTTPSessionManager.run()` may be called once per process, so flipping the
    flag and re-importing `server.main` is not available. This asserts the wiring instead:
    the mount must pass through `guarded_mcp_app`, reading the key from the environment
    and never from config JSON.
    """
    source = (REPO_ROOT / "server" / "main.py").read_text(encoding="utf-8")

    mount = re.search(r"app\.mount\(\s*_global_cfg\.mcp\.mount_path,(.+?)\n    \)", source, re.S)
    assert mount, "the MCP mount is no longer recognisable in server/main.py"
    body = mount.group(1)

    assert "guarded_mcp_app(" in body, "the MCP transport is mounted without the auth guard"
    assert "require_api_key=bool(_global_cfg.mcp.require_api_key)" in body
    assert 'os.environ.get("MCP_API_KEY")' in body, (
        "the key must come from the process environment; config JSON is served to the browser"
    )


def test_the_secret_is_never_read_out_of_config() -> None:
    """A tree invariant: `MCP_API_KEY` is an env secret, not a config field.

    `mcp.public_base_url` and `mount_path` are config; the key is not, and must never be
    added there -- `GET /api/config` reaches the browser.
    """
    offenders: list[str] = []
    for source in sorted((REPO_ROOT / "server").rglob("*.py")):
        text = source.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if re.search(r"(cfg|config)\.mcp\.\w*api_key\w*", line) and "require_api_key" not in line:
                offenders.append(f"{source.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "read MCP_API_KEY from the environment, not from config:\n" + "\n".join(offenders)
