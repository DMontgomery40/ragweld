"""Native LiteLLM ledger contract using a real pinned gateway and local provider.

Set RAGWELD_NATIVE_LEDGER_TEST_DSN to a fresh, empty, locally hosted database
whose name starts ragweld_native_ledger_test_. Its owner creates/drops that
disposable database; these tests never infer a production DSN or drop a database.
The pinned LiteLLM image must already be present in Docker. Missing explicit
capability skips ordinary runs and fails strict native acceptance.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import httpx
import pytest
from pydantic import SecretStr

from server.observability.gateway_costs import (
    NativeLedgerReadError,
    NativeSpendReader,
    RequestCensus,
)
from tests.service_requirements import _strict_mode, require_env

_IMAGE = "ghcr.io/berriai/litellm:v1.94.0"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=30)


async def _verify_owned_empty_database(dsn: str) -> None:
    parsed = urlsplit(dsn)
    database = unquote(parsed.path.removeprefix("/"))
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or re.fullmatch(r"ragweld_native_ledger_test_[a-z0-9_]{1,35}", database) is None
        or parsed.query not in {"", "schema=public"}
        or parsed.fragment
    ):
        raise ValueError("Native ledger tests require an explicit local, owned test database DSN")
    connection = await asyncpg.connect(urlunsplit(parsed._replace(query="")), timeout=3)
    try:
        owned = await connection.fetchval(
            "SELECT current_database()=$1 AND pg_get_userbyid(datdba)=current_user "
            "FROM pg_database WHERE datname=$1", database,
        )
        if not owned:
            raise ValueError("The native ledger test connection must own its dedicated database")
        occupied = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema='public')"
        )
        if occupied:
            raise ValueError("Native ledger tests refuse an existing schema; supply a fresh owned database")
    finally:
        await connection.close()


class _SyntheticProvider(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = json.dumps({
            "id": f"chatcmpl-native-ledger-{uuid4().hex}",
            "object": "chat.completion", "created": int(time.time()), "model": request["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "synthetic response"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "cost": 0.0123},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@dataclass(frozen=True)
class _NativeGateway:
    base_url: str
    key: SecretStr
    container_name: str


@pytest.fixture(scope="module")
def native_gateway(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_NativeGateway]:
    if _strict_mode() and not os.environ.get("RAGWELD_NATIVE_LEDGER_TEST_DSN"):
        pytest.fail("Strict native ledger acceptance requires RAGWELD_NATIVE_LEDGER_TEST_DSN")
    dsn = require_env("RAGWELD_NATIVE_LEDGER_TEST_DSN")
    if sys.platform != "linux" or shutil.which("docker") is None:
        pytest.fail("Native ledger acceptance requires Linux Docker on the authorized test runtime")
    asyncio.run(_verify_owned_empty_database(dsn))
    _docker("image", "inspect", _IMAGE)
    directory = tmp_path_factory.mktemp("native-ledger-gateway")
    name = f"ragweld-native-ledger-test-{uuid4().hex[:12]}"
    key = SecretStr(f"sk-native-fixture-{uuid4().hex}")
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticProvider)
    provider_thread = threading.Thread(target=provider.serve_forever, daemon=True)
    provider_thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        gateway_port = reservation.getsockname()[1]
    configuration = {
        "model_list": [{"model_name": "fixture-provider-cost", "litellm_params": {
            "model": "openrouter/astra/provider-cost", "api_key": "synthetic-local-provider-only",
            "api_base": f"http://127.0.0.1:{provider.server_port}/v1",
        }}],
        "litellm_settings": {"num_retries": 0, "fallbacks": [], "context_window_fallbacks": []},
        "router_settings": {"num_retries": 0},
        "general_settings": {
            "master_key": "os.environ/LITELLM_MASTER_KEY", "store_model_in_db": False,
            "store_prompts_in_spend_logs": False, "disable_spend_logs": False,
        },
    }
    config_file = directory / "config.json"
    config_file.write_text(json.dumps(configuration))
    env_file = directory / "gateway.env"
    env_file.write_text(
        f"DATABASE_URL={dsn}\nLITELLM_MASTER_KEY={key.get_secret_value()}\n"
        "STORE_PROMPTS_IN_SPEND_LOGS=false\nLITELLM_LOCAL_MODEL_COST_MAP=True\nLITELLM_TELEMETRY=False\n"
    )
    env_file.chmod(0o600)
    gateway = _NativeGateway(f"http://127.0.0.1:{gateway_port}", key, name)
    try:
        _docker(
            "run", "--detach", "--name", name, "--network", "host", "--memory", "1536m", "--cpus", "1.5",
            "--env-file", str(env_file), "--mount", f"type=bind,src={config_file},dst=/app/test-config.json,readonly",
            _IMAGE, "--config", "/app/test-config.json", "--host", "127.0.0.1", "--port", str(gateway_port),
            "--num_workers", "1", "--use_v2_migration_resolver", "--enforce_prisma_migration_check",
        )
        deadline = time.monotonic() + 180
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(f"{gateway.base_url}/health/readiness")
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                pytest.fail(f"Native gateway failed readiness; inspect {directory / 'gateway.log'}")
        yield gateway
    finally:
        logs = _docker("logs", name, check=False)
        (directory / "gateway.log").write_text(logs.stdout + logs.stderr)
        _docker("rm", "--force", name, check=False)
        provider.shutdown()
        provider.server_close()
        provider_thread.join(timeout=3)
        env_file.unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("dsn", [
    "postgresql://test@127.0.0.1/tribrid_rag",
    "postgresql://test@192.0.2.1/ragweld_native_ledger_test_reader",
    "postgresql://test@127.0.0.1/ragweld_native_ledger_test_",
    "postgresql://test@127.0.0.1/ragweld_native_ledger_test_reader?schema=foreign",
    "postgresql://test@127.0.0.1/ragweld_native_ledger_test_reader#fragment",
    "sqlite:///ragweld_native_ledger_test_reader",
])
async def test_native_fixture_refuses_unowned_or_ambiguous_resources_before_connecting(dsn: str) -> None:
    with pytest.raises(ValueError, match="explicit local, owned test database"):
        await _verify_owned_empty_database(dsn)


@pytest.mark.asyncio
async def test_real_native_pagination_exact_attribution_and_durable_census(native_gateway: _NativeGateway, tmp_path: Path) -> None:
    reader = NativeSpendReader(base_url=native_gateway.base_url, api_key=native_gateway.key, request_timeout_s=2, total_timeout_s=10)
    session = "reader-" + uuid4().hex
    started = datetime.now(UTC) - timedelta(seconds=1)
    dispatches = completions = 0
    native_call_ids = []
    async with httpx.AsyncClient(base_url=native_gateway.base_url, timeout=15, trust_env=False) as client:
        for index in range(108):
            target_session = session + "-neighbor" if index == 105 else session
            corpus = "foreign-corpus" if index == 106 else "reader-corpus"
            lane = "foreign-lane" if index == 107 else "index_graph_extraction"
            if index < 105:
                dispatches += 1
            response = await client.post("/v1/chat/completions", headers={
                "Authorization": f"Bearer {native_gateway.key.get_secret_value()}",
                "x-litellm-session-id": target_session,
                "x-litellm-spend-logs-metadata": json.dumps({"run_id": target_session, "corpus_id": corpus, "lane": lane}),
            }, json={"model": "fixture-provider-cost", "messages": [{"role": "user", "content": f"synthetic reader pagination {session} {index}"}]})
            if index < 105:
                completions += 1
                native_call_ids.append(response.headers.get("x-litellm-call-id"))
            assert response.status_code == 200, response.text
    ended = datetime.now(UTC) + timedelta(seconds=1)
    census = RequestCensus("closed", dispatches, completions, 0, 0, True, True, True)
    samples = []
    for _ in range(30):
        result = await reader.read_run(session_id=session, corpus_id="reader-corpus", lanes=frozenset({"index_graph_extraction"}), started_at=started, ended_at=ended, census=census)
        samples.append(asdict(result))
        if result.state == "complete" and result.excluded_rows == 3:
            break
        await asyncio.sleep(0.5)
    assert result.state == result.coverage_state == result.pricing_state == "complete"
    assert result.matched_gateway_requests == result.provider_reported_requests == 105
    assert result.provider_reported_usd == Decimal("0.0123") * 105
    assert result.gateway_calculated_usd == 0
    assert result.excluded_rows == 3 and result.pages_read == 2 and result.missing_requests == 0
    assert None not in native_call_ids and len(set(native_call_ids)) == census.started_requests
    (tmp_path / "native-reader-evidence.json").write_text(json.dumps({"census": asdict(census), "samples": samples}, indent=2, default=str))


@pytest.mark.asyncio
async def test_real_native_auth_failure_is_not_zero_spend(native_gateway: _NativeGateway) -> None:
    reader = NativeSpendReader(base_url=native_gateway.base_url, api_key=SecretStr("wrong-fixture-key"), request_timeout_s=2, total_timeout_s=3)
    now = datetime.now(UTC)
    with pytest.raises(NativeLedgerReadError) as error:
        await reader.read_run(session_id="no-authorized-view", corpus_id="reader-corpus", lanes=frozenset({"index_graph_extraction"}), started_at=now, ended_at=now, census=RequestCensus("closed", 0, 0, 0, 0, True, True, True))
    assert error.value.code == "native_http_error" and error.value.status_code == 401
    assert "wrong-fixture-key" not in str(error.value)


@pytest.mark.asyncio
async def test_real_paused_gateway_honors_explicit_deadline(native_gateway: _NativeGateway) -> None:
    reader = NativeSpendReader(base_url=native_gateway.base_url, api_key=native_gateway.key, request_timeout_s=0.2, total_timeout_s=0.3)
    now = datetime.now(UTC)
    _docker("pause", native_gateway.container_name)
    try:
        started = asyncio.get_running_loop().time()
        with pytest.raises(NativeLedgerReadError) as error:
            await reader.read_run(session_id="paused-view", corpus_id="reader-corpus", lanes=frozenset({"index_graph_extraction"}), started_at=now, ended_at=now, census=RequestCensus("closed", 0, 0, 0, 0, True, True, True))
        assert error.value.code == "native_read_timeout"
        assert asyncio.get_running_loop().time() - started < 1
    finally:
        _docker("unpause", native_gateway.container_name)
