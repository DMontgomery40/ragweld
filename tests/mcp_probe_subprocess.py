"""Drive the mounted MCP transport in a one-lifespan child process.

The MCP SDK's process-wide StreamableHTTPSessionManager is intentionally
one-shot.  A child process lets integration tests exercise the real mounted
transport without entering a second lifespan in the shared pytest process.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_RESULT_PREFIX = "RAGWELD_MCP_PROBE_RESULT="
_SCRIPT = r"""
import asyncio
import json
import sys

from httpx import ASGITransport, AsyncClient
from server.main import app


async def main() -> None:
    corpus_id, mode, question, top_k_text = sys.argv[1:5]
    payload = {
        "question": question,
        "corpus_id": corpus_id,
        "top_k": int(top_k_text),
    }
    if mode:
        payload["mode"] = mode
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://localhost:8000",
        ) as client:
            response = await client.post(
                "/api/mcp/probe",
                json=payload,
            )
            print(
                "RAGWELD_MCP_PROBE_RESULT="
                + json.dumps(
                    {"status_code": response.status_code, "body": response.json()},
                    separators=(",", ":"),
                )
            )


asyncio.run(main())
"""


async def call_mcp_probe(
    corpus_id: str,
    mode: str | None,
    *,
    question: str = "status",
    top_k: int = 3,
) -> tuple[int, dict[str, Any]]:
    """Return one real mounted-transport probe response from an isolated lifespan."""

    completed = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", _SCRIPT, corpus_id, mode or "", question, str(top_k)],
        cwd=ROOT,
        env=dict(os.environ),
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    marker = next(
        (line for line in reversed(completed.stdout.splitlines()) if line.startswith(_RESULT_PREFIX)),
        None,
    )
    assert completed.returncode == 0 and marker is not None, (
        "isolated MCP probe failed before returning a response\n"
        f"stdout tail: {completed.stdout[-2000:]}\n"
        f"stderr tail: {completed.stderr[-2000:]}"
    )
    payload = json.loads(marker.removeprefix(_RESULT_PREFIX))
    body = payload.get("body")
    assert isinstance(body, dict), payload
    return int(payload["status_code"]), body
