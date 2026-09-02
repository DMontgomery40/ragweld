"""API tests for MCP endpoints (status + Streamable HTTP).

Every real-transport proof shares the ONE app lifespan entered below:
`StreamableHTTPSessionManager.run()` may be called only once per instance, so a second
`app.router.lifespan_context(app)` entry anywhere in the same pytest process raises
".run() can only be called once per instance" instead of testing anything. The
DNS-rebinding / advertised-host agreement proof that used to enter its own lifespan in
`tests/api/test_config_redaction.py` therefore lives here, after the tool-list proof, and so
does the mounted-tool-defaults proof (P2-B), which needs a real probe through that transport.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from httpx import ASGITransport, AsyncClient

from server.main import app

_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "acceptance_corpus"
_REAL_QUESTION = "How often is the salinity sensor calibrated?"

# A child process that STARTED with `mcp.enabled: false` -- so `server.main` mounted nothing and
# never built the FastMCP singleton -- and then sees the operator turn the flag on. Asking for the
# status in that state builds the singleton (to list the tools) without mounting anything, which
# is the one state where "a server object exists" and "a transport is mounted" come apart. Run in
# a child because both facts are process-wide and the shared pytest process mounted its transport
# at import.
_UNMOUNTED_STATUS_SCRIPT = r"""
import asyncio
import json
import os
import pathlib

from httpx import ASGITransport, AsyncClient

from server.main import app  # imported with mcp.enabled false: nothing is mounted here
from server.mcp.server import mounted_state


async def main() -> None:
    assert mounted_state()[0] is False, "this process was supposed to mount no transport"
    # The operator turns the transport on. Nothing re-mounts until a restart.
    config_path = pathlib.Path(os.environ["RAGWELD_CONFIG_PATH"])
    document = json.loads(config_path.read_text())
    document["mcp"]["enabled"] = True
    config_path.write_text(json.dumps(document, indent=2))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:8000"
    ) as client:
        response = await client.get("/api/mcp/status")
        print(
            "RAGWELD_MCP_STATUS_RESULT="
            + json.dumps(
                {"status_code": response.status_code, "body": response.json()},
                separators=(",", ":"),
            )
        )


asyncio.run(main())
"""


@pytest.mark.asyncio
async def test_mcp_streamable_http_tools_advertised_host_and_mounted_tool_defaults() -> None:
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

            # P2-B: the mounted tools close over `mcp.default_mode` / `mcp.default_top_k` as
            # they were when this process built the MCP server, so an operator's edit does not
            # reach a tool call until a restart. The probe response and the status card have to
            # report what the tool ACTUALLY applies; reporting the persisted config described a
            # deployment that does not exist yet, and the two disagreed silently.
            mounted_mode = str(data["default_mode"])
            mounted_top_k = int(data["default_top_k"])
            assert mounted_top_k >= 1, data
            assert data["config_default_mode"] == mounted_mode, data
            assert data["config_default_top_k"] == mounted_top_k, data
            assert data["defaults_restart_pending"] is False, data

            corpus_id = f"pytest_mcp_defaults_{uuid.uuid4().hex[:8]}"
            created = await client.post(
                "/api/corpora",
                json={"corpus_id": corpus_id, "name": corpus_id, "path": str(_CORPUS_PATH)},
            )
            assert created.status_code == 200, created.text
            try:
                changed_top_k = mounted_top_k + 7
                patched = await client.patch(
                    "/api/config/mcp", json={"default_top_k": changed_top_k}
                )
                assert patched.status_code == 200, patched.text
                assert patched.json()["mcp"]["default_top_k"] == changed_top_k

                after = (await client.get("/api/mcp/status")).json()
                # What the mounted tools use, what a restart would mount, and the fact that the
                # two now disagree -- all three, because the card has to say both numbers.
                assert after["default_top_k"] == mounted_top_k, after
                assert after["config_default_top_k"] == changed_top_k, after
                assert after["defaults_restart_pending"] is True, after
                assert any("Restart the API" in str(line) for line in after["details"]), after[
                    "details"
                ]

                probed = await client.post(
                    "/api/mcp/probe",
                    json={"question": _REAL_QUESTION, "corpus_id": corpus_id},
                )
                assert probed.status_code == 200, probed.text
                body = probed.json()
                assert body["top_k"] == mounted_top_k, (
                    "the probe labelled its result with a top_k the mounted tool never used: "
                    f"{body['top_k']} vs mounted {mounted_top_k}"
                )
                assert body["mode"] == mounted_mode, body
            finally:
                await client.delete(f"/api/corpora/{corpus_id}")


def test_a_process_that_mounted_no_transport_reports_no_tool_defaults(tmp_path: Path) -> None:
    """Only a process that actually mounted the transport may describe what its tools default to.

    `mounted_tool_config()` is populated by building the FastMCP singleton, and `/api/mcp/status`
    builds it to list the tools -- so "a server object exists" is not "a transport is mounted".
    Reporting the defaults on that weaker condition would advertise a mode/top_k for a transport
    whose probe answers 503, which is the same class of lie P2-B closed.
    """
    from server.config import DEFAULT_CONFIG_PATH

    document = json.loads(DEFAULT_CONFIG_PATH.read_text())
    document["mcp"]["enabled"] = False
    child_config = tmp_path / "tribrid_config.json"
    child_config.write_text(json.dumps(document, indent=2))

    completed = subprocess.run(
        [sys.executable, "-c", _UNMOUNTED_STATUS_SCRIPT],
        cwd=_ROOT,
        env={**os.environ, "RAGWELD_CONFIG_PATH": str(child_config)},
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    marker = next(
        (
            line
            for line in reversed(completed.stdout.splitlines())
            if line.startswith("RAGWELD_MCP_STATUS_RESULT=")
        ),
        None,
    )
    assert completed.returncode == 0 and marker is not None, (
        "the unmounted status probe failed before returning a response\n"
        f"stdout tail: {completed.stdout[-2000:]}\n"
        f"stderr tail: {completed.stderr[-2000:]}"
    )
    payload = json.loads(marker.removeprefix("RAGWELD_MCP_STATUS_RESULT="))
    assert payload["status_code"] == 200, payload
    body = payload["body"]
    # The premise: the singleton WAS built while answering this request (its tools are listed),
    # so a check on "was a server constructed" would have reported defaults here.
    assert {"search", "answer", "list_corpora"}.issubset({tool["name"] for tool in body["tools"]}), body
    assert body["default_mode"] is None, body
    assert body["default_top_k"] is None, body
    assert body["defaults_restart_pending"] is False, body
    # What a restart WOULD mount is still honest information, and still reported.
    assert isinstance(body["config_default_top_k"], int) and body["config_default_top_k"] >= 1, body
    assert str(body["config_default_mode"]).strip(), body
