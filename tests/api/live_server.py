"""Serve the real app over TCP in a subprocess for disconnect tests.

httpx's ASGI transport runs the app to completion and hands back a buffered body, so it can
never show what happens when a client goes away mid-stream, and a uvicorn thread inside the
pytest process shares its lifespan resources with the session loop. A uvicorn subprocess on
a loopback port is the real thing: closing the socket cancels the response task exactly as a
client disconnect does. Its config comes from ``config_path``; its provider from the env.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

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
