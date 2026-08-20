from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_pytest_uses_a_private_runtime_config_copy() -> None:
    from server.config import DEFAULT_CONFIG_PATH

    assert DEFAULT_CONFIG_PATH.is_absolute()
    assert DEFAULT_CONFIG_PATH != ROOT / "tribrid_config.json"
    assert DEFAULT_CONFIG_PATH.exists()


def test_explicit_runtime_config_path_controls_app_config(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    payload["indexing"]["postgres_url"] = "postgresql://isolated:secret@127.0.0.1:65431/integration"
    payload["graph_storage"]["neo4j_uri"] = "bolt://127.0.0.1:65432"
    runtime_config = tmp_path / "integration-config.json"
    runtime_config.write_text(json.dumps(payload), encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    env["RAGWELD_CONFIG_PATH"] = str(runtime_config)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from server.config import DEFAULT_CONFIG_PATH, load_config; "
                "cfg = load_config(); "
                "print(json.dumps({'path': str(DEFAULT_CONFIG_PATH), "
                "'postgres_url': cfg.indexing.postgres_url, "
                "'neo4j_uri': cfg.graph_storage.neo4j_uri}))"
            ),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    observed = json.loads(result.stdout.strip())
    assert observed == {
        "path": str(runtime_config),
        "postgres_url": "postgresql://isolated:secret@127.0.0.1:65431/integration",
        "neo4j_uri": "bolt://127.0.0.1:65432",
    }


def test_integration_launcher_rejects_foreign_project_name_before_docker(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "docker-invoked"
    fake_docker = fake_bin / "docker"
    fake_docker.write_text(f"#!/usr/bin/env bash\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["COMPOSE_PROJECT_NAME"] = "ragweld"
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "test_integration.sh")],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert not marker.exists()
    assert "COMPOSE_PROJECT_NAME" in result.stderr


def test_strict_integration_rejects_repo_owned_config_path() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["RAGWELD_STRICT_INTEGRATION"] = "1"
    env["RAGWELD_CONFIG_PATH"] = str(ROOT / "tribrid_config.json")
    env["RAGWELD_INTEGRATION_RUNTIME_DIR"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )

    assert result.returncode != 0
    assert "refuses config paths inside the repository" in result.stderr
