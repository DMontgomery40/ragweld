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
    final_delay_seconds: float = 0.0
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
            if type(self).final_delay_seconds > 0:
                time.sleep(type(self).final_delay_seconds)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def slow_delta_requests() -> list[dict]:
    """The chat-completions payloads the slow gateway has received since it was started."""
    return list(_SlowDeltaGateway.requests)


@contextmanager
def slow_delta_gateway(*, delay_seconds: float = 0.4, final_delay_seconds: float = 0.0) -> Iterator[str]:
    """``final_delay_seconds`` holds the terminator back after the last delta, opening the
    window in which a client has every content token but the exchange is not finished."""
    _SlowDeltaGateway.delay_seconds = delay_seconds
    _SlowDeltaGateway.final_delay_seconds = final_delay_seconds
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


class _CompletionGateway(BaseHTTPRequestHandler):
    """A non-stream OpenAI-compatible completion with fixed text (set by ``completion_gateway``)."""

    text: str = "The plane management company was Jet Aviation."

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        length = int(self.headers.get("Content-Length") or "0")
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if payload.get("stream"):
            body_lines = [
                "data: " + json.dumps({"id": "chatcmpl-fixed", "object": "chat.completion.chunk",
                                       "choices": [{"index": 0, "delta": {"content": type(self).text}, "finish_reason": None}]}),
                "data: [DONE]",
            ]
            body = ("\n\n".join(body_lines) + "\n\n").encode()
            content_type = "text/event-stream"
        else:
            body = json.dumps(
                {
                    "id": "chatcmpl-fixed",
                    "object": "chat.completion",
                    "model": payload.get("model") or "fixed",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": type(self).text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 9, "total_tokens": 29},
                }
            ).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextmanager
def completion_gateway(text: str = "The plane management company was Jet Aviation.") -> Iterator[str]:
    """A gateway that answers every request (stream or not) with ``text``."""
    _CompletionGateway.text = text
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CompletionGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _ReasoningGateway(BaseHTTPRequestHandler):
    """A reasoning model as LiteLLM relays it: reasoning chunks (``reasoning_content`` plus
    the upstream's raw ``reasoning`` copy, empty ``content``) for a while, then the answer.
    The class attributes are set by ``reasoning_gateway``."""

    reasoning: tuple[str, ...] = ("The user asks which company ", "managed Barry Cohen's plane.")
    reasoning_seconds: float = 0.0
    answer: tuple[str, ...] = ("Jet Aviation ", "managed the plane.")
    usage: dict | None = None
    requests: list[dict] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _chunk(self, delta: dict) -> bytes:
        chunk = {
            "id": "chatcmpl-reasoning",
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
        }
        return f"data: {json.dumps(chunk)}\n\n".encode()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        import time

        length = int(self.headers.get("Content-Length") or "0")
        type(self).requests.append(json.loads(self.rfile.read(length).decode("utf-8") or "{}"))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        cls = type(self)
        try:
            # Reasoning chunks spread over `reasoning_seconds`, at least one per second, the
            # way a reasoning model streams while it thinks before its first answer token.
            steps = max(len(cls.reasoning), int(cls.reasoning_seconds))
            pause = cls.reasoning_seconds / steps if steps else 0.0
            for index in range(steps):
                text = cls.reasoning[index] if index < len(cls.reasoning) else " ..."
                self.wfile.write(self._chunk({"reasoning_content": text, "reasoning": text, "content": ""}))
                self.wfile.flush()
                if pause:
                    time.sleep(pause)
            for text in cls.answer:
                self.wfile.write(self._chunk({"content": text}))
                self.wfile.flush()
            if cls.usage is not None:
                # The terminal usage chunk `stream_options.include_usage` asks for (no choices).
                final = {"id": "chatcmpl-reasoning", "object": "chat.completion.chunk", "choices": [], "usage": cls.usage}
                self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def reasoning_gateway_requests() -> list[dict]:
    """The chat-completions payloads the reasoning gateway has received since it was started."""
    return list(_ReasoningGateway.requests)


@contextmanager
def reasoning_gateway(
    *,
    reasoning_seconds: float = 0.0,
    reasoning: tuple[str, ...] = ("The user asks which company ", "managed Barry Cohen's plane."),
    answer: tuple[str, ...] = ("Jet Aviation ", "managed the plane."),
    usage: dict | None = None,
) -> Iterator[str]:
    """A gateway whose model reasons for ``reasoning_seconds`` before it answers; an empty
    ``answer`` is a model that spends everything on reasoning and answers nothing. ``usage``,
    when given, is sent as the terminal usage chunk (tokens, reasoning tokens, ``cost``)."""
    _ReasoningGateway.reasoning = reasoning
    _ReasoningGateway.reasoning_seconds = reasoning_seconds
    _ReasoningGateway.answer = answer
    _ReasoningGateway.usage = usage
    _ReasoningGateway.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ReasoningGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _StalledGateway(BaseHTTPRequestHandler):
    """Accepts the request, sends stream headers, then sends nothing for ``stall_seconds``:
    an upstream that stalls before its first byte, which the transport's read timeout ends."""

    stall_seconds: float = 5.0

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        import time

        length = int(self.headers.get("Content-Length") or "0")
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.flush()
        time.sleep(type(self).stall_seconds)
        try:
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            return


@contextmanager
def stalled_gateway(*, stall_seconds: float = 5.0) -> Iterator[str]:
    _StalledGateway.stall_seconds = stall_seconds
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StalledGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=stall_seconds + 2)
