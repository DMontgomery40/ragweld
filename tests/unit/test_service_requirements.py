from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

from tests.service_requirements import probe_neo4j, probe_postgres

ROOT = Path(__file__).resolve().parents[2]


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


def test_service_plugin_skips_locally_and_fails_in_strict_mode(tmp_path: Path) -> None:
    test_file = tmp_path / "test_requires_postgres.py"
    test_file.write_text(
        "import pytest\n"
        "@pytest.mark.requires_postgres\n"
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
        }
    )
    base_env.pop("RAGWELD_STRICT_INTEGRATION", None)

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
