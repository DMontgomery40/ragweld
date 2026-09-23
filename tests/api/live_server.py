"""Serve the real app over TCP in a subprocess for disconnect tests.

httpx's ASGI transport runs the app to completion and hands back a buffered body, so it can
never show what happens when a client goes away mid-stream, and a uvicorn thread inside the
pytest process shares its lifespan resources with the session loop. A uvicorn subprocess on
a loopback port is the real thing: closing the socket cancels the response task exactly as a
client disconnect does. Its config comes from ``config_path``; its provider from the env.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def live_app_subprocess(*, config_path: Path, env: Mapping[str, str]) -> Iterator[str]:
    port = _free_port()
    child_env = {**os.environ, **dict(env), "RAGWELD_CONFIG_PATH": str(config_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=child_env,
        cwd=str(Path(__file__).resolve().parents[2]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 120
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"uvicorn exited early with {proc.returncode}")
            try:
                if httpx.get(f"{base_url}/api/health", timeout=2.0).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("uvicorn did not answer /api/health within 120 s")
            time.sleep(0.5)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


async def post_stream_then_disconnect(
    app: Any,
    path: str,
    body: Mapping[str, Any],
    *,
    disconnect_when: Callable[[bytes], bool],
    timeout_s: float = 60.0,
) -> list[bytes]:
    """POST `body` to the ASGI `app` in-process and disconnect once a response body chunk
    satisfies `disconnect_when`; returns the body chunks received.

    The ASGI client here is the protocol itself, not a transport that buffers: after the
    request body, `receive()` blocks until the chosen chunk has been sent and then reports
    `http.disconnect`, which is exactly what a server delivers when the socket closes.
    No `asgi.spec_version` is advertised, so Starlette takes the same disconnect-listening
    branch it takes under uvicorn.
    """
    payload = json.dumps(dict(body)).encode("utf-8")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode("ascii")),
        ],
        "client": ("127.0.0.1", 50123),
        "server": ("test", 80),
    }
    request_sent = False
    gone = asyncio.Event()
    chunks: list[bytes] = []

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message.get("type") == "http.response.body":
            chunk = bytes(message.get("body") or b"")
            chunks.append(chunk)
            if disconnect_when(chunk):
                gone.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=timeout_s)
    return chunks
