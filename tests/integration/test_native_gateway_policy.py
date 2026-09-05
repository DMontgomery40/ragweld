"""Actual pinned LiteLLM policy and provider dispatch counts, no paid calls/DB.

RAGWELD_NATIVE_POLICY_TESTS=1 explicitly enables owned loopback containers on the
Linux test runtime. The pinned image must already be installed. This fixture
never discovers production credentials, changes existing gateways or pulls images.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from server.observability.gateway_policy import NativeGatewayPolicyReader, NativePolicyReadError
from tests.service_requirements import _strict_mode

_IMAGE = "ghcr.io/berriai/litellm:v1.94.0"


@dataclass
class _ProviderState:
    mode: str = "success"
    calls: list[str] = field(default_factory=list)
    payloads: list[dict[str, object]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=30)


@dataclass
class _Gateway:
    base_url: str
    key: SecretStr
    state: _ProviderState
    sdk_retries: int
    container: str

    def reader(self, *, key: SecretStr | None = None, timeout: float = 5) -> NativeGatewayPolicyReader:
        return NativeGatewayPolicyReader(base_url=self.base_url, api_key=key or self.key, request_timeout_s=timeout, total_timeout_s=timeout)

    def probe(self, alias: str, mode: str, **controls: object) -> tuple[int, int]:
        with self.state.lock:
            self.state.mode = mode
            self.state.calls.clear()
        body: dict[str, object] = {"model": alias, "num_retries": 0, "max_retries": 0, "disable_fallbacks": True, **controls}
        path = "/v1/embeddings" if alias == "embedding" else "/v1/chat/completions"
        body.update({"input": ["Sensor calibration measurements"]} if alias == "embedding" else {
            "messages": [{"role": "user", "content": "Which calibration measurements establish sensor linearity?"}],
        })
        with httpx.Client(base_url=self.base_url, headers={"Authorization": f"Bearer {self.key.get_secret_value()}"}, timeout=30, trust_env=False) as client:
            status = client.post(path, json=body).status_code
        # Mirrored calls are background tasks; observe their true dispatch.
        if alias == "shadow-source":
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                with self.state.lock:
                    if len(self.state.calls) >= 2:
                        break
                time.sleep(0.02)
        with self.state.lock:
            return status, len(self.state.calls)


@pytest.fixture(scope="module", params=[2, 0])
def native_policy_gateway(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Gateway]:
    if os.environ.get("RAGWELD_NATIVE_POLICY_TESTS") != "1":
        if _strict_mode():
            pytest.fail("Strict native policy acceptance requires RAGWELD_NATIVE_POLICY_TESTS=1")
        pytest.skip("Native policy acceptance requires explicit RAGWELD_NATIVE_POLICY_TESTS=1")
    if sys.platform != "linux" or shutil.which("docker") is None:
        pytest.fail("Native policy acceptance requires Linux Docker on the authorized runtime")
    _docker("image", "inspect", _IMAGE)
    state = _ProviderState()

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP method
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with state.lock:
                mode = state.mode
                state.calls.append(self.path)
                state.payloads.append(body)
            secondary = self.path.startswith("/secondary/")
            if mode == "disconnect" and not secondary:
                self.close_connection = True
                return
            status = 200 if secondary or mode == "success" else 429 if mode == "rate_limit" else 503
            if status != 200:
                payload = {"error": {"message": "Synthetic calibration provider failure", "type": "rate_limit_error" if status == 429 else "server_error"}}
            elif self.path.endswith("embeddings"):
                dimensions = body.get("dimensions")
                vector = [0.1] * dimensions if dimensions is not None else [0.1, 0.2, 0.3]
                payload = {"object": "list", "model": body["model"], "data": [
                    {"object": "embedding", "index": index, "embedding": vector}
                    for index, _ in enumerate(body["input"])
                ], "usage": {"prompt_tokens": 5, "total_tokens": 5}}
            else:
                payload = {"id": "chatcmpl-" + uuid4().hex, "object": "chat.completion", "created": 1, "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": "Calibration completed."}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("retry-after", "0")
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(encoded)

    sdk_retries = int(request.param)
    name = "ragweld-native-policy-test-" + uuid4().hex[:12]
    key = SecretStr("sk-policy-synthetic-" + uuid4().hex)
    directory = tmp_path_factory.mktemp("native-policy")
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    models = []
    for alias, model, suffix, extra in [
        ("primary", "gpt-5-mini", "", {}),
        ("embedding", "text-embedding-3-small", "", {}),
        ("deployment-retries", "gpt-5-mini", "", {"num_retries": 2}),
        ("policy-retries", "gpt-5-mini", "", {}),
        ("fallback-source", "gpt-5-mini", "", {}),
        ("secondary", "gpt-5-mini", "/secondary", {}),
        ("shadow-source", "gpt-5-mini", "", {"silent_model": "secondary"}),
    ]:
        models.append({"model_name": alias, "litellm_params": {
            "model": "openai/" + model, "api_base": f"http://127.0.0.1:{provider.server_port}{suffix}/v1",
            "api_key": "synthetic-provider-only", "num_retries": 0, "max_retries": 0, **extra,
        }})
    config = {
        "model_list": models,
        "litellm_settings": {"DEFAULT_MAX_RETRIES": sdk_retries, "num_retries": 0},
        "router_settings": {"num_retries": 0, "retry_after": 0, "allowed_fails": 100,
            "fallbacks": [{"fallback-source": ["secondary"]}], "context_window_fallbacks": [],
            "content_policy_fallbacks": [], "retry_policy": None,
            "model_group_retry_policy": {"policy-retries": {"RateLimitErrorRetries": 2}},
        },
        "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
    }
    config_file = directory / "config.json"
    config_file.write_text(json.dumps(config))
    try:
        _docker("run", "--detach", "--name", name, "--network", "host", "--memory", "1536m", "--cpus", "1.5",
            "--env", f"LITELLM_MASTER_KEY={key.get_secret_value()}", "--env", f"DEFAULT_MAX_RETRIES={sdk_retries}",
            "--env", "LITELLM_LOCAL_MODEL_COST_MAP=True", "--env", "LITELLM_TELEMETRY=False",
            "--mount", f"type=bind,src={config_file},dst=/app/policy.json,readonly", _IMAGE,
            "--config", "/app/policy.json", "--host", "127.0.0.1", "--port", str(port), "--num_workers", "1")
        gateway = _Gateway(f"http://127.0.0.1:{port}", key, state, sdk_retries, name)
        deadline = time.monotonic() + 90
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    if client.get(gateway.base_url + "/health/readiness").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                pytest.fail(f"Owned native gateway did not become ready; inspect {directory / 'gateway.log'}")
        yield gateway
    finally:
        logs = _docker("logs", name, check=False)
        (directory / "gateway.log").write_text(logs.stdout + logs.stderr)
        _docker("rm", "--force", name, check=False)
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=3)


def test_real_native_management_snapshot_cannot_observe_sdk_retry_default(native_policy_gateway: _Gateway):
    snapshot = asyncio.run(native_policy_gateway.reader().snapshot(models=frozenset({"primary", "embedding"})))
    assert snapshot.observed_compatible, snapshot.reasons
    assert snapshot.verified is False
    assert "provider_sdk_retry_policy_unobservable" in snapshot.reasons
    repeated = asyncio.run(native_policy_gateway.reader().snapshot(models=frozenset({"primary", "embedding"})))
    assert repeated.evidence_sha256 == snapshot.evidence_sha256


@pytest.mark.parametrize("alias", ["primary", "embedding"])
@pytest.mark.parametrize("mode,status", [("success", 200), ("failure", 503), ("rate_limit", 429), ("disconnect", 500)])
def test_sdk_default_controls_actual_provider_http_attempts(native_policy_gateway: _Gateway, alias: str, mode: str, status: int):
    actual_status, calls = native_policy_gateway.probe(alias, mode)
    assert actual_status == status
    expected = 3 if native_policy_gateway.sdk_retries == 2 and alias == "embedding" and mode != "success" else 1
    assert calls == expected


def test_deployment_policy_and_mirroring_override_request_zero(native_policy_gateway: _Gateway):
    # These independent routing paths can add calls even when SDK retries are0.
    for alias, mode, expected_status, expected_calls in [
        ("deployment-retries", "failure", 503, 9),
        ("policy-retries", "rate_limit", 429, 3),
        ("shadow-source", "success", 200, 2),
        ("fallback-source", "failure", 503, 1),
    ]:
        snapshot = asyncio.run(native_policy_gateway.reader().snapshot(models=frozenset({alias})))
        assert not snapshot.observed_compatible, alias
        assert native_policy_gateway.probe(alias, mode) == (expected_status, expected_calls)
    assert native_policy_gateway.probe("fallback-source", "failure", disable_fallbacks=False) == (200, 2)
    assert native_policy_gateway.probe("policy-retries", "rate_limit", model_group_retry_policy={"policy-retries": {"RateLimitErrorRetries": 0}}) == (429, 1)


def test_real_native_auth_and_deadline_errors_are_sanitized(native_policy_gateway: _Gateway):
    with pytest.raises(NativePolicyReadError) as denied:
        asyncio.run(native_policy_gateway.reader(key=SecretStr("sk-deliberately-invalid-synthetic-key")).snapshot(models=frozenset({"primary"})))
    assert denied.value.code == "native_policy_http_error"
    # This DB-free native gateway rejects unknown virtual keys with400
    # ("No connected db"); the master key still authenticates every real read.
    assert denied.value.status_code == 400
    assert "synthetic-key" not in str(denied.value)
    _docker("pause", native_policy_gateway.container)
    try:
        started = time.monotonic()
        with pytest.raises(NativePolicyReadError, match="native_policy_read_timeout"):
            asyncio.run(native_policy_gateway.reader(timeout=0.15).snapshot(models=frozenset({"primary"})))
        assert time.monotonic() - started < 2
    finally:
        _docker("unpause", native_policy_gateway.container)
