"""API tests for MCP endpoints (status + Streamable HTTP).

Every real-transport proof shares the ONE app lifespan entered below:
`StreamableHTTPSessionManager.run()` may be called only once per instance, so a second
`app.router.lifespan_context(app)` entry anywhere in the same pytest process raises
".run() can only be called once per instance" instead of testing anything. The
DNS-rebinding / advertised-host agreement proof that used to enter its own lifespan in
`tests/api/test_config_redaction.py` therefore lives here, after the tool-list proof.
"""

from urllib.parse import urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app


@pytest.mark.asyncio
async def test_mcp_streamable_http_tools_and_advertised_host_agreement() -> None:
    # Keep MCP lifespan inside this test coroutine so AnyIO cancel scopes are entered/exited
    # in the same task (required by the MCP SDK internals).
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
            resp = await client.get("/api/mcp/status")
            assert resp.status_code == 200
            data = resp.json()

            assert data["python_stdio_available"] is True
            # Required, not skippable: everything below drives the real mounted transport,
            # so its absence is a broken deployment contract, not an environment to shrug at.
            assert data["python_http"] is not None, (
                "the MCP streamable-HTTP transport is absent; this suite requires it"
            )
            assert data["python_http"]["running"] is True
            assert data["python_http"]["path"] == "/mcp/"
            # The status boundary advertises the registered tools so the MCP subtab
            # can show them without a start/stop daemon that never existed (M12).
            advertised_tools = {tool["name"] for tool in data["tools"]}
            assert {"search", "answer", "list_corpora"}.issubset(advertised_tools)
            assert all(str(tool["description"]).strip() for tool in data["tools"])

            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            async with streamable_http_client("http://localhost:8000/mcp/", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert {"search", "answer", "list_corpora"}.issubset(names)

            # M-91's second half: advertising a host the transport refuses is not a fix.
            #
            # `/api/mcp/status` reports `host_allowed` by asking the transport's own
            # validator. This drives the REAL mounted transport and asserts the two agree,
            # so if the library's rule ever changes this fails instead of the workbench
            # quietly advertising a URL that answers 421.
            #
            # Asked on loopback on purpose: that is the branch where `host_allowed` is
            # about the advertised URL's own host, which is what this compares. The proxied
            # branch -- where it is deliberately about a DIFFERENT host -- is covered by
            # `test_an_unset_public_base_url_is_reported_against_the_host_a_client_would_use`
            # in tests/api/test_config_redaction.py.
            status = (
                await client.get("/api/mcp/status", headers={"Host": "127.0.0.1:58012"})
            ).json()
            http = status["python_http"]
            assert http, (
                "the MCP streamable-HTTP transport is absent; the advertised-host "
                "agreement proof requires it"
            )

            async def probe(host: str) -> int:
                response = await client.post(
                    http["path"],
                    headers={
                        "Host": host,
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )
                return response.status_code

            # The premise. Without this the agreement check below could pass on a
            # transport that happily accepts every Host, which would make `host_allowed`
            # meaningless.
            assert await probe("mcp-host-that-is-not-allowed.example") == 421, (
                "DNS rebinding protection is not refusing an unknown Host"
            )

            assert http["public_base_url_configured"] is True, (
                "this proof needs the branch where host_allowed describes the advertised URL"
            )
            advertised = urlsplit(http["url"]).netloc
            assert advertised, http["url"]
            refused = await probe(advertised) == 421
            assert http["host_allowed"] is not refused, (
                f"status says host_allowed={http['host_allowed']} for {advertised!r}, "
                f"but the transport refused it"
            )
