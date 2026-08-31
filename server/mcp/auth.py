"""Bearer authentication in front of the embedded MCP Streamable HTTP mount.

`mcp.require_api_key` and the `MCP_API_KEY` secret both existed and neither was read by
anything: the model described an `Authorization: Bearer $MCP_API_KEY` check, the docs called
it the thing to use in production, and `server/main.py` mounted the transport with no
wrapper at all. A configuration knob that silently does nothing is worse than no knob --
this one sat in the single sentence that would talk an operator into removing the only
authentication actually in front of the route.

The guard is a plain ASGI wrapper rather than a FastAPI dependency because the transport is
mounted as its own ASGI app; a dependency on the outer router never runs for requests the
mount handles.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from server.models.tribrid_config_model import MCPUnauthorizedResponse


class MCPApiKeyMissingError(RuntimeError):
    """`mcp.require_api_key` is on and `MCP_API_KEY` is not set in the environment."""


def _presented_bearer(scope: Scope) -> bytes:
    """The token from an `Authorization: Bearer` header, as raw bytes.

    Bytes end to end, deliberately. Decoding first (latin-1 maps every byte, so it never
    raises) produced a `str` that could hold code points above U+007F, and
    `secrets.compare_digest` rejects a non-ASCII `str` with `TypeError` -- so a token with
    one high byte in it crashed out of the ASGI app instead of being refused. A credential
    check must answer 401 to garbage, not 500.

    Split on RFC 7235 OWS rather than a single space: `split(maxsplit=1)` treats any run of
    ASCII whitespace as one separator, so `Bearer\ttoken` and `Bearer  token` are accepted
    as the grammar allows.
    """
    for raw_name, raw_value in scope.get("headers") or []:
        if bytes(raw_name).lower() != b"authorization":
            continue
        parts = bytes(raw_value).strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != b"bearer":
            return b""
        return parts[1].strip()
    return b""


class RequireMCPApiKey:
    """Refuse any request to the mount that does not present the configured bearer."""

    def __init__(self, app: Callable[..., Awaitable[None]], api_key: str) -> None:
        self._app = app
        # Held as bytes so the comparison below can never be handed a non-ASCII `str`.
        self._api_key = api_key.encode("utf-8")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # `lifespan` must reach the transport or its session manager never starts, and the
        # transport is HTTP-only, so anything that is not an HTTP request passes through.
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        presented = _presented_bearer(scope)
        # Constant-time, and byte-wise: the comparison is against a secret, and a length- or
        # prefix-sensitive `==` leaks it one byte at a time to anyone who can time it.
        if not presented or not secrets.compare_digest(presented, self._api_key):
            body = MCPUnauthorizedResponse(
                detail=(
                    "This MCP endpoint requires a bearer token. Send "
                    "`Authorization: Bearer <MCP_API_KEY>`; the value is the MCP_API_KEY "
                    "in the server's environment."
                )
            )
            response = JSONResponse(
                status_code=401,
                content=body.model_dump(mode="json"),
                headers={"WWW-Authenticate": 'Bearer realm="ragweld-mcp"'},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)


def guarded_mcp_app(
    app: Callable[..., Awaitable[None]],
    *,
    require_api_key: bool,
    api_key: str | None,
) -> Callable[..., Awaitable[None]]:
    """Return the MCP app, wrapped when the config asks for a bearer check.

    Fails closed: `require_api_key` with no `MCP_API_KEY` in the environment raises rather
    than mounting an unauthenticated transport. An operator who turns the flag on has said
    the endpoint is exposed; starting anyway and serving `search`, `answer` and
    `list_corpora` to anyone would be the worst of the three outcomes.

    The key is read from the process environment by the caller and never from config JSON,
    like every other secret in this repo -- `MCP_API_KEY` is a registered
    `SecretRequirement`, and config is served to the browser.
    """
    if not require_api_key:
        return app
    key = (api_key or "").strip()
    if not key:
        raise MCPApiKeyMissingError(
            "config.mcp.require_api_key is true but MCP_API_KEY is not set in the server "
            "environment. Set it, or turn the flag off -- refusing to mount an "
            "unauthenticated MCP transport."
        )
    return RequireMCPApiKey(app, key)
