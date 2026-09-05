from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from tests.service_requirements import (
    postgres_dsn_from_env,
    probe_neo4j,
    probe_postgres,
)

ROOT = Path(__file__).resolve().parents[2]


def test_postgres_dsn_resolution_prefers_explicit_and_composes_escaped_components() -> None:
    assert postgres_dsn_from_env({"POSTGRES_DSN": "postgresql://explicit/db"}) == (
        "postgresql://explicit/db"
    )
    assert postgres_dsn_from_env(
        {
            "POSTGRES_HOST": "db.internal",
            "POSTGRES_PORT": "5544",
            "POSTGRES_DB": "rag weld",
            "POSTGRES_USER": "test@user",
            "POSTGRES_PASSWORD": "p:a/ss",
        }
    ) == "postgresql://test%40user:p%3Aa%2Fss@db.internal:5544/rag%20weld"
    assert postgres_dsn_from_env({}) is None


def test_require_env_resolves_postgres_components_and_preserves_named_skip() -> None:
    postgres_names = (
        "POSTGRES_DSN",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    base_env = {name: value for name, value in os.environ.items() if name not in postgres_names}
    probe = (
        "import pytest\n"
        "from tests.service_requirements import require_env\n"
        "try:\n"
        "    print(require_env('POSTGRES_DSN'))\n"
        "except pytest.skip.Exception as exc:\n"
        "    print(f'SKIP:{exc}')\n"
    )

    missing = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=base_env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert missing.stdout.strip().startswith("SKIP:POSTGRES_DSN is not set")

    configured = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env={**base_env, "POSTGRES_HOST": "db.internal", "POSTGRES_USER": "test-user"},
        check=True,
        capture_output=True,
        text=True,
    )
    assert configured.stdout.strip() == (
        "postgresql://test-user:postgres@db.internal:5432/tribrid_rag"
    )


def test_postgres_probe_requires_a_real_connection() -> None:
    capability = probe_postgres(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "POSTGRES_DB": "postgres",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
        },
        timeout_seconds=0.2,
    )

    assert capability.available is False
    assert capability.service == "PostgreSQL"
    assert "127.0.0.1:1" in capability.reason


def test_postgres_probe_reports_invalid_port_without_crashing_collection() -> None:
    capability = probe_postgres({"POSTGRES_PORT": "not-a-port"})

    assert capability.available is False
    assert "invalid postgres_port" in capability.reason.lower()


def test_service_probes_require_explicit_integration_configuration() -> None:
    postgres = probe_postgres({})
    neo4j = probe_neo4j({})

    assert postgres.available is False
    assert neo4j.available is False
    assert "not configured" in postgres.reason.lower()
    assert "not configured" in neo4j.reason.lower()


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_dotenv_loading_switch_disables_repo_env(value: str) -> None:
    from server.main import _dotenv_loading_enabled

    assert _dotenv_loading_enabled(value) is False


def test_importing_app_in_test_mode_does_not_load_repo_dotenv() -> None:
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        pytest.skip("repository .env is absent")

    values = dotenv_values(dotenv_path)
    key = next((name for name, value in values.items() if name and value), None)
    if key is None:
        pytest.skip("repository .env has no populated keys")

    env = dict(os.environ)
    env.pop(key, None)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import os; import server.main; raise SystemExit(1 if {key!r} in os.environ else 0)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("service", ["postgres", "model_gateway"])
def test_service_plugin_skips_locally_and_fails_in_strict_mode(tmp_path: Path, service: str) -> None:
    test_file = tmp_path / "test_requires_postgres.py"
    test_file.write_text(
        "import pytest\n"
        f"@pytest.mark.requires_{service}\n"
        "def test_live_postgres():\n"
        "    raise AssertionError('unreachable service test should not execute')\n",
        encoding="utf-8",
    )
    base_env = dict(os.environ)
    base_env.update(
        {
            "PYTHONPATH": str(ROOT),
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "1",
            "POSTGRES_DB": "postgres",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "RAGWELD_LOAD_DOTENV": "0",
            "LITELLM_BASE_URL": "http://127.0.0.1:1/v1",
            "LITELLM_API_KEY": "fixture-key",
        }
    )
    base_env.pop("RAGWELD_STRICT_INTEGRATION", None)
    if service == "model_gateway":
        base_env.pop("LITELLM_BASE_URL", None)

    local = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "tests.service_requirements", str(test_file)],
        cwd=ROOT,
        env=base_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert local.returncode == 0, local.stdout + local.stderr
    assert "1 skipped" in local.stdout

    if service == "model_gateway":
        configured_env = {**base_env, "LITELLM_BASE_URL": "http://127.0.0.1:1/v1"}
        configured = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "tests.service_requirements", str(test_file)],
            cwd=ROOT, env=configured_env, text=True, capture_output=True, check=False,
        )
        assert configured.returncode != 0, configured.stdout + configured.stderr
        assert "configured model gateway unavailable" in (configured.stdout + configured.stderr).lower()

    strict_env = dict(base_env)
    strict_env["RAGWELD_STRICT_INTEGRATION"] = "1"
    strict = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "tests.service_requirements", str(test_file)],
        cwd=ROOT,
        env=strict_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert strict.returncode != 0
    assert "strict integration requirements unavailable" in (strict.stdout + strict.stderr).lower()


@pytest.mark.parametrize("env", [{}, {"LITELLM_BASE_URL": "http://127.0.0.1:1/v1"}])
def test_model_gateway_requires_explicit_authenticated_configuration(env: dict[str, str]) -> None:
    from tests.service_requirements import probe_model_gateway

    capability = probe_model_gateway(env, timeout_seconds=0.1)
    assert not capability.available
    assert "not configured" in capability.reason.lower()


@pytest.mark.parametrize("response_status,payload,available", [
    (401, {"error": "unauthorized"}, False),
    (200, {"data": []}, False),
    (200, {"data": [{"id": "openai.gpt-4o"}]}, False),
    (200, {"data": [{"id": "openai.gpt-5.6-sol"}]}, True),
    (200, ["not a model listing"], False),
    (200, b"{invalid-json", False),
])
def test_model_gateway_probe_checks_real_authenticated_model_listing(
    response_status: int, payload: object, available: bool, tmp_path: Path,
) -> None:
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from tests.service_requirements import probe_model_gateway

    requests: list[tuple[str, str | None]] = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append((self.path, self.headers.get("Authorization")))
            self.send_response(response_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload if isinstance(payload, bytes) else json.dumps(payload).encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        capability = probe_model_gateway({
            "LITELLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "LITELLM_API_KEY": "fixture-key",
            "GRAPH_E2E_KG_MODEL": "openai.gpt-5.6-sol",
        })
        assert capability.available is available
        assert requests == [("/v1/models", "Bearer fixture-key")]
        assert "fixture-key" not in capability.reason
        test_file = tmp_path / "test_gateway.py"
        test_file.write_text("import pytest\n@pytest.mark.requires_model_gateway\ndef test_gateway(): pass\n")
        for strict in (False, True):
            env = {**os.environ, "PYTHONPATH": str(ROOT),
                   "LITELLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                   "LITELLM_API_KEY": "fixture-key", "GRAPH_E2E_KG_MODEL": "openai.gpt-5.6-sol"}
            env.pop("RAGWELD_STRICT_INTEGRATION", None)
            if strict:
                env["RAGWELD_STRICT_INTEGRATION"] = "1"
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "tests.service_requirements", str(test_file)],
                                    cwd=ROOT, env=env, capture_output=True, text=True)
            assert (result.returncode == 0) is available, result.stdout + result.stderr
            if available:
                assert "1 passed" in result.stdout
            else:
                assert "unavailable" in (result.stdout + result.stderr).lower()
            assert "fixture-key" not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("fixture_kind", ["valid", "missing", "malformed"])
def test_explicit_private_test_config_preserves_its_input_and_tracked_source(tmp_path: Path, fixture_kind: str) -> None:
    import json

    fixture = tmp_path / "isolated.json"
    source = ROOT / "tribrid_config.json"
    source_before = source.read_bytes()
    if fixture_kind == "valid":
        raw = json.loads(source_before)
        raw["qdrant"]["url"] = "http://127.0.0.1:1"
        fixture.write_text(json.dumps(raw))
    elif fixture_kind == "malformed":
        fixture.write_text('{"qdrant":')
    fixture_before = fixture.read_bytes() if fixture.exists() else None
    env = dict(os.environ)
    env.pop("RAGWELD_STRICT_INTEGRATION", None)
    env["RAGWELD_TEST_CONFIG_PATH"] = str(fixture)
    script = """
import os, shutil
from pathlib import Path
import tests.conftest
from server.config import DEFAULT_CONFIG_PATH, load_config
assert load_config().qdrant.url == 'http://127.0.0.1:1'
assert DEFAULT_CONFIG_PATH != Path(os.environ['RAGWELD_TEST_CONFIG_PATH'])
assert Path(os.environ['RAGWELD_SOURCE_CONFIG_PATH']) == Path.cwd() / 'tribrid_config.json'
DEFAULT_CONFIG_PATH.write_text('{}')
shutil.rmtree(DEFAULT_CONFIG_PATH.parent)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
    if fixture_kind == "valid":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "RAGWELD_TEST_CONFIG_PATH" in result.stderr
    assert source.read_bytes() == source_before
    assert (fixture.read_bytes() if fixture.exists() else None) == fixture_before


@pytest.mark.parametrize("strict_value", ["1", "true", "yes", "on", " TRUE "])
def test_strict_config_gate_uses_the_same_truth_values_as_service_collection(strict_value: str) -> None:
    env = dict(os.environ)
    for key in ("RAGWELD_CONFIG_PATH", "RAGWELD_INTEGRATION_RUNTIME_DIR", "RAGWELD_TEST_CONFIG_PATH"):
        env.pop(key, None)
    env["RAGWELD_STRICT_INTEGRATION"] = strict_value
    result = subprocess.run([sys.executable, "-c", "import tests.conftest"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Strict integration requires a private RAGWELD_CONFIG_PATH" in result.stderr
