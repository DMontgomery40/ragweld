from __future__ import annotations

import json
import os
import re
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


def test_start_routes_vite_proxy_to_the_resolved_backend_port() -> None:
    source = (ROOT / "start.sh").read_text(encoding="utf-8")

    assert 'export VITE_API_PROXY_TARGET="${VITE_API_PROXY_TARGET:-http://127.0.0.1:${BACKEND_PORT}}"' in source


def test_acceptance_bootstrap_uses_proxied_status_with_resolved_backend_port() -> None:
    source = (ROOT / "scripts" / "automation_bootstrap.sh").read_text(encoding="utf-8")

    assert "/__dev__/" not in source
    assert '"${root}/api/dev/status"' in source
    assert source.count("BACKEND_PORT=") >= 2


def test_integration_launcher_is_disposable_strict_and_host_owned() -> None:
    source = (ROOT / "scripts" / "test_integration.sh").read_text(encoding="utf-8").lower()

    assert "colima start" not in source
    assert "colima stop" not in source
    assert "colima delete" not in source
    assert "postgres_port=0" in source
    assert "neo4j_http_port=0" in source
    assert "neo4j_bolt_port=0" in source
    assert "down --volumes --remove-orphans" in source
    assert "ragweld_strict_integration=1" in source
    assert "not requires_pg_search" in source


def test_base_compose_uses_project_scoped_names_and_named_database_volumes() -> None:
    config = _compose_config("docker-compose.yml")
    services = config["services"]

    assert all("container_name" not in service for service in services.values())
    assert config["networks"]["default"]["name"] == "ragweld_default"
    assert all(service.get("labels", {}).get("io.ragweld.managed") == "true" for service in services.values())

    for service in services.values():
        for port in service.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1"

    postgres_data = _volume_for_target(services["postgres"], "/var/lib/postgresql/data")
    neo4j_data = _volume_for_target(services["neo4j"], "/data")
    neo4j_logs = _volume_for_target(services["neo4j"], "/logs")
    assert postgres_data["type"] == "volume"
    assert neo4j_data["type"] == "volume"
    assert neo4j_logs["type"] == "volume"


def test_promtail_collects_only_ragweld_owned_container_logs() -> None:
    import yaml

    payload = yaml.safe_load((ROOT / "infra" / "promtail-config.yml").read_text(encoding="utf-8"))
    scrape_configs = payload["scrape_configs"]

    assert [config["job_name"] for config in scrape_configs] == ["docker"]
    relabel_configs = scrape_configs[0]["relabel_configs"]
    assert {
        "source_labels": [
            "__meta_docker_container_label_com_docker_compose_project",
            "__meta_docker_container_label_io_ragweld_managed",
        ],
        "separator": ";",
        "regex": "ragweld;true",
        "action": "keep",
    } in relabel_configs


def test_active_docker_config_has_no_remote_daemon_or_dead_infra_authority() -> None:
    from server.models.tribrid_config_model import DockerConfig, TriBridConfig

    removed_model_fields = {"docker_host", "docker_infra_up_timeout", "docker_infra_down_timeout"}
    removed_flat_keys = {"DOCKER_HOST", "DOCKER_INFRA_UP_TIMEOUT", "DOCKER_INFRA_DOWN_TIMEOUT"}
    schema_fields = set(DockerConfig.model_json_schema()["properties"])
    active_config = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    flat_config = TriBridConfig().to_flat_dict()

    assert schema_fields.isdisjoint(removed_model_fields)
    assert set(active_config["docker"]).isdisjoint(removed_model_fields)
    assert set(flat_config).isdisjoint(removed_flat_keys)


def test_removed_docker_controls_are_absent_from_glossary_mirrors() -> None:
    removed_keys = {"DOCKER_INFRA_UP_TIMEOUT", "DOCKER_INFRA_DOWN_TIMEOUT"}
    source = json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))
    public = json.loads((ROOT / "web" / "public" / "glossary.json").read_text(encoding="utf-8"))

    assert source == public
    assert {entry["key"] for entry in source["terms"]}.isdisjoint(removed_keys)


def test_observability_overlay_resolves_repo_files_and_avoids_foreign_ports() -> None:
    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    services = config["services"]

    tempo_config = _volume_for_target(services["tempo"], "/etc/tempo/tempo.yaml")
    alloy_config = _volume_for_target(services["alloy"], "/etc/alloy/config.alloy")
    assert Path(tempo_config["source"]).resolve() == (ROOT / "infra" / "tempo.yaml").resolve()
    assert Path(alloy_config["source"]).resolve() == (ROOT / "infra" / "alloy" / "config.alloy").resolve()

    tempo_data = _volume_for_target(services["tempo"], "/var/tempo")
    assert tempo_data["type"] == "volume"
    import yaml

    tempo_payload = yaml.safe_load((ROOT / "infra" / "tempo.yaml").read_text(encoding="utf-8"))
    assert tempo_payload["server"]["grpc_listen_port"] == 9095
    otlp_protocols = tempo_payload["distributor"]["receivers"]["otlp"]["protocols"]
    assert otlp_protocols["grpc"]["endpoint"] == "0.0.0.0:4317"
    assert otlp_protocols["http"]["endpoint"] == "0.0.0.0:4318"
    assert tempo_payload["storage"]["trace"]["wal"]["path"] == "/var/tempo/wal"
    assert tempo_payload["storage"]["trace"]["local"]["path"] == "/var/tempo/blocks"
    metrics_storage = tempo_payload["metrics_generator"]["storage"]
    assert metrics_storage["path"] == "/var/tempo/generator/wal"
    assert metrics_storage["remote_write"] == [
        {"url": "http://prometheus:9090/api/v1/write", "send_exemplars": True}
    ]

    for service_name in ("tempo", "alloy"):
        service = services[service_name]
        assert service["labels"]["io.ragweld.managed"] == "true"
        assert all(port.get("host_ip") == "127.0.0.1" for port in service.get("ports", []))

    foreign_ports = {3001, 3100, 4317, 4318, 12345}
    published = set().union(
        _published_ports(services["grafana"]),
        _published_ports(services["loki"]),
        _published_ports(services["tempo"]),
        _published_ports(services["alloy"]),
    )
    assert published.isdisjoint(foreign_ports)


def test_prometheus_scrapes_only_clean_start_targets_and_accepts_tempo_metrics() -> None:
    import yaml

    payload = yaml.safe_load((ROOT / "infra" / "prometheus.yml").read_text(encoding="utf-8"))
    scrape_configs = payload["scrape_configs"]
    jobs = {config["job_name"]: config for config in scrape_configs}

    assert set(jobs) == {"prometheus", "ragweld-api-host", "postgres"}
    api_targets = jobs["ragweld-api-host"]["static_configs"][0]["targets"]
    assert api_targets == ["host.docker.internal:58012"]

    compose = _compose_config("docker-compose.yml")
    assert "--web.enable-remote-write-receiver" in compose["services"]["prometheus"]["command"]


def test_active_observability_urls_match_namespaced_loopback_ports() -> None:
    from server.api.docker import _loki_candidate_urls
    from server.models.tribrid_config_model import TriBridConfig

    active = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    assert active["tracing"]["tracing_mode"] == "otel"
    assert active["ui"]["grafana_base_url"] == "http://127.0.0.1:3301"
    assert active["tracing"]["tempo_base_url"] == "http://127.0.0.1:53200"
    assert active["tracing"]["alloy_base_url"] == "http://127.0.0.1:52345"
    assert active["tracing"]["otlp_endpoint"] == "http://127.0.0.1:54320/v1/traces"
    assert TriBridConfig().ui.grafana_base_url == "http://127.0.0.1:3301"
    assert "http://127.0.0.1:53100" in _loki_candidate_urls()
    assert "http://127.0.0.1:3100" not in _loki_candidate_urls()


def test_docker_service_allowlists_match_frontend_and_managed_compose_services() -> None:
    from server.api.docker import _DOCKER_SERVICES

    frontend_source = (ROOT / "web" / "src" / "api" / "docker.ts").read_text(encoding="utf-8")
    match = re.search(r"RAGWELD_DOCKER_SERVICES\s*=\s*\[(.*?)\]\s*as const", frontend_source, re.DOTALL)
    assert match is not None
    frontend_services = set(re.findall(r"'([^']+)'", match.group(1)))

    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    managed_services = {
        name
        for name, service in config["services"].items()
        if service.get("labels", {}).get("io.ragweld.managed") == "true"
    }

    assert set(_DOCKER_SERVICES) == frontend_services == managed_services
