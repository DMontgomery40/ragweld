"""API tests for MCP endpoints (status + Streamable HTTP)."""

import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app


@pytest.mark.asyncio
async def test_mcp_status_and_streamable_http_tools() -> None:
    # Keep MCP lifespan inside this test coroutine so AnyIO cancel scopes are entered/exited
    # in the same task (required by the MCP SDK internals).
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:
            resp = await client.get("/api/mcp/status")
            assert resp.status_code == 200
            data = resp.json()

            assert data["python_stdio_available"] is True
            assert data["python_http"] is not None
            assert data["python_http"]["running"] is True
            assert data["python_http"]["path"] == "/mcp/"

            from mcp import ClientSession
            from mcp.client.streamable_http import streamable_http_client

            async with streamable_http_client("http://localhost:8000/mcp/", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}
                    assert {"search", "answer", "list_corpora"}.issubset(names)

