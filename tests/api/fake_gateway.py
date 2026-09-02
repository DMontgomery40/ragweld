"""A local OpenAI-compatible gateway for zero-mocked failure tests.

``empty_stream_gateway`` answers every chat-completions request with a stream that carries
no content (only the terminator), which is how a provider that produces nothing looks to
the transport. ``gateway_env`` points the process at it for the duration: the runtime reads
``LITELLM_BASE_URL`` / ``LITELLM_API_KEY`` from the environment ahead of the config.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _EmptyStreamGateway(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        body = b"data: [DONE]\n\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def empty_stream_gateway() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _EmptyStreamGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@contextmanager
def gateway_env(base_url: str, api_key: str = "pytest-fake-gateway-key") -> Iterator[None]:
    saved = {name: os.environ.get(name) for name in ("LITELLM_BASE_URL", "LITELLM_API_KEY")}
    os.environ["LITELLM_BASE_URL"] = base_url
    os.environ["LITELLM_API_KEY"] = api_key
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class _SlowDeltaGateway(BaseHTTPRequestHandler):
    """Streams a few content deltas with a pause between them, so a client can go away
    mid-answer; the class attributes are set by ``slow_delta_gateway``."""

    deltas: tuple[str, ...] = ("The plane ", "management ", "company was ", "Jet Aviation.")
    delay_seconds: float = 0.4
    requests: list[dict] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        import time

        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        try:
            type(self).requests.append(json.loads(raw.decode("utf-8")))
        except Exception:
            type(self).requests.append({"raw": raw.decode("utf-8", errors="replace")})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for delta in type(self).deltas:
                chunk = {
                    "id": "chatcmpl-slow",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(type(self).delay_seconds)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def slow_delta_requests() -> list[dict]:
    """The chat-completions payloads the slow gateway has received since it was started."""
    return list(_SlowDeltaGateway.requests)


@contextmanager
def slow_delta_gateway(*, delay_seconds: float = 0.4) -> Iterator[str]:
    _SlowDeltaGateway.delay_seconds = delay_seconds
    _SlowDeltaGateway.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowDeltaGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
