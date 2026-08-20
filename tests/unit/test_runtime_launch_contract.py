from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        list(args),
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def _compose_config(*files: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    version = _run("docker", "compose", "version")
    if version.returncode != 0:
        pytest.skip("docker compose plugin is unavailable")

    args = ["docker", "compose", "--project-name", "ragweld"]
    for file_name in files:
        args.extend(["-f", file_name])
    args.extend(["config", "--format", "json"])
    result = _run(*args)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _published_ports(service: dict[str, Any]) -> set[int]:
    ports = service.get("ports")
    if not isinstance(ports, list):
        return set()
    out: set[int] = set()
    for port in ports:
        if not isinstance(port, dict):
            continue
        published = port.get("published")
        if published is not None:
            out.add(int(published))
    return out


def _volume_for_target(service: dict[str, Any], target: str) -> dict[str, Any]:
    volumes = service.get("volumes")
    assert isinstance(volumes, list)
    for volume in volumes:
        if isinstance(volume, dict) and volume.get("target") == target:
            return volume
    raise AssertionError(f"missing volume target {target}")


def test_start_check_treats_docker_runtime_as_host_owned() -> None:
    result = _run("bash", "start.sh", "--check", "--no-backend", "--no-frontend")
    output = f"{result.stdout}\n{result.stderr}".lower()

    assert result.returncode == 0, output
    assert "host-owned docker runtime" in output
    assert "colima start" not in output
    assert "colima stop" not in output
    assert "colima delete" not in output


def test_vite_config_has_no_hidden_process_launcher() -> None:
    source = (ROOT / "web" / "vite.config.ts").read_text(encoding="utf-8")

    assert "child_process" not in source
    assert "devStackLauncher" not in source
    assert "/__dev__/" not in source
    assert "spawn(" not in source


def test_acceptance_bootstrap_uses_proxied_status_with_resolved_backend_port() -> None:
    source = (ROOT / "scripts" / "automation_bootstrap.sh").read_text(encoding="utf-8")

    assert "/__dev__/" not in source
    assert '"${root}/api/dev/status"' in source
    assert source.count("BACKEND_PORT=") >= 2


def test_base_compose_uses_project_scoped_names_and_named_database_volumes() -> None:
    config = _compose_config("docker-compose.yml")
    services = config["services"]

    assert all("container_name" not in service for service in services.values())
    assert config["networks"]["default"]["name"] == "ragweld_default"

    postgres_data = _volume_for_target(services["postgres"], "/var/lib/postgresql/data")
    neo4j_data = _volume_for_target(services["neo4j"], "/data")
    neo4j_logs = _volume_for_target(services["neo4j"], "/logs")
    assert postgres_data["type"] == "volume"
    assert neo4j_data["type"] == "volume"
    assert neo4j_logs["type"] == "volume"


def test_observability_overlay_resolves_repo_files_and_avoids_foreign_ports() -> None:
    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    services = config["services"]

    tempo_config = _volume_for_target(services["tempo"], "/etc/tempo/tempo.yaml")
    alloy_config = _volume_for_target(services["alloy"], "/etc/alloy/config.alloy")
    assert Path(tempo_config["source"]).resolve() == (ROOT / "infra" / "tempo.yaml").resolve()
    assert Path(alloy_config["source"]).resolve() == (ROOT / "infra" / "alloy" / "config.alloy").resolve()

    foreign_ports = {3001, 3100, 4317, 4318, 12345}
    published = set().union(
        _published_ports(services["grafana"]),
        _published_ports(services["loki"]),
        _published_ports(services["tempo"]),
        _published_ports(services["alloy"]),
    )
    assert published.isdisjoint(foreign_ports)
