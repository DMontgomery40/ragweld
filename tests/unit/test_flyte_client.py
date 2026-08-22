"""FlyteAdmin REST client contract against a real local HTTP server.

The server below speaks the flyteadmin gateway routes the client depends on
(healthcheck, launch plan listing, execution create/get/terminate) with the
camelCase JSON the gateway emits. No mocking: every call crosses a socket.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from server.training.flyte_client import (
    FLYTE_ABORT_PHASES,
    FLYTE_TERMINAL_PHASES,
    FlyteAdminClient,
    FlyteUnavailableError,
    new_execution_name,
)


class _AdminState:
    def __init__(self) -> None:
        self.executions: dict[str, dict] = {}
        self.created_payloads: list[dict] = []
        self.terminations: list[tuple[str, str]] = []
        self.lock = threading.Lock()


STATE = _AdminState()


class _AdminHandler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthcheck":
            self._json(200, {})
            return
        if path == "/api/v1/launch_plans/ragweld/development/learning-agent-train":
            self._json(
                200,
                {
                    "launchPlans": [
                        {
                            "id": {
                                "resourceType": "LAUNCH_PLAN",
                                "project": "ragweld",
                                "domain": "development",
                                "name": "learning-agent-train",
                                "version": "abc123",
                            }
                        }
                    ]
                },
            )
            return
        if path == "/api/v1/launch_plans/ragweld/development/missing-plan":
            self._json(200, {"launchPlans": []})
            return
        if path.startswith("/api/v1/executions/ragweld/development/"):
            name = path.rsplit("/", 1)[-1]
            with STATE.lock:
                execution = STATE.executions.get(name)
            if execution is None:
                self._json(404, {"error": "missing"})
                return
            self._json(200, execution)
            return
        self._json(404, {"error": "unknown route"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/v1/executions":
            payload = self._read_json()
            name = payload["name"]
            with STATE.lock:
                STATE.created_payloads.append(payload)
                STATE.executions[name] = {
                    "id": {"project": payload["project"], "domain": payload["domain"], "name": name},
                    "closure": {"phase": "RUNNING"},
                }
            self._json(200, {"id": {"project": payload["project"], "domain": payload["domain"], "name": name}})
            return
        self._json(404, {"error": "unknown route"})

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path.startswith("/api/v1/executions/ragweld/development/"):
            name = self.path.rsplit("/", 1)[-1]
            payload = self._read_json()
            with STATE.lock:
                execution = STATE.executions.get(name)
                if execution is None:
                    self._json(404, {"error": "missing"})
                    return
                STATE.terminations.append((name, payload.get("cause", "")))
                execution["closure"] = {
                    "phase": "ABORTED",
                    "abortMetadata": {"cause": payload.get("cause", ""), "principal": "test"},
                }
            self._json(200, {})
            return
        self._json(404, {"error": "unknown route"})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


@pytest.fixture(scope="module")
def admin_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _AdminHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_execution_names_are_dns_safe_and_unique() -> None:
    names = {new_execution_name() for _ in range(50)}
    assert len(names) == 50
    for name in names:
        assert len(name) == 20
        assert name[0].isalpha()
        assert name == name.lower()
        assert all(ch.isalnum() for ch in name)


def test_launch_plan_resolution_reads_gateway_camel_case(admin_url: str) -> None:
    client = FlyteAdminClient(f"{admin_url}/api/v1")  # trailing /api/v1 is tolerated
    client.healthcheck()
    ref = client.resolve_launch_plan("ragweld", "development", "learning-agent-train")
    assert (ref.project, ref.domain, ref.name, ref.version) == ("ragweld", "development", "learning-agent-train", "abc123")

    with pytest.raises(FlyteUnavailableError, match="not registered"):
        client.resolve_launch_plan("ragweld", "development", "missing-plan")
    with pytest.raises(FlyteUnavailableError):
        client.resolve_launch_plan("", "development", "learning-agent-train")


def test_execution_lifecycle_create_get_terminate(admin_url: str) -> None:
    client = FlyteAdminClient(admin_url)
    ref = client.resolve_launch_plan("ragweld", "development", "learning-agent-train")
    name = client.create_execution(
        ref,
        inputs={"run_id": "corpus__20260821_000000", "retries": 2, "ratio": 0.5, "flag": True},
        execution_name="ratest0000000000001a",
    )
    assert name == "ratest0000000000001a"

    payload = STATE.created_payloads[-1]
    assert payload["spec"]["launch_plan"] == {
        "resource_type": "LAUNCH_PLAN",
        "project": "ragweld",
        "domain": "development",
        "name": "learning-agent-train",
        "version": "abc123",
    }
    assert payload["spec"]["metadata"]["mode"] == "MANUAL"
    literals = payload["inputs"]["literals"]
    assert literals["run_id"] == {"scalar": {"primitive": {"string_value": "corpus__20260821_000000"}}}
    assert literals["retries"] == {"scalar": {"primitive": {"integer": "2"}}}
    assert literals["ratio"] == {"scalar": {"primitive": {"float_value": 0.5}}}
    assert literals["flag"] == {"scalar": {"primitive": {"boolean": True}}}

    state = client.get_execution("ragweld", "development", name)
    assert state.phase == "RUNNING"
    assert state.terminal is False
    assert "RUNNING" not in FLYTE_TERMINAL_PHASES

    client.terminate_execution("ragweld", "development", name, cause="operator cancel")
    assert STATE.terminations[-1] == (name, "operator cancel")
    state = client.get_execution("ragweld", "development", name)
    assert state.phase == "ABORTED"
    assert state.phase in FLYTE_ABORT_PHASES
    assert state.terminal is True
    assert state.abort_cause == "operator cancel"

    with pytest.raises(FlyteUnavailableError):
        client.get_execution("ragweld", "development", "rdoesnotexist00000000")


def test_unreachable_admin_raises_typed_error() -> None:
    client = FlyteAdminClient("http://127.0.0.1:9", timeout_s=0.5)
    with pytest.raises(FlyteUnavailableError, match="unreachable"):
        client.healthcheck()
    with pytest.raises(FlyteUnavailableError, match="unreachable"):
        client.resolve_launch_plan("ragweld", "development", "learning-agent-train")
    with pytest.raises(FlyteUnavailableError):
        FlyteAdminClient("   ")
