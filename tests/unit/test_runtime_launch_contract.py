from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    if env and "RAGWELD_RUNTIME_DIR" in env:
        return subprocess.run(
            list(args),
            cwd=ROOT,
            env=merged_env,
            text=True,
            capture_output=True,
            check=False,
        )
    with tempfile.TemporaryDirectory(prefix="ragweld-runtime-test-") as runtime_dir:
        merged_env["RAGWELD_RUNTIME_DIR"] = runtime_dir
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
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-backend",
        "--no-frontend",
        "--no-local-model",
        env={
            "DOCKER_HOST": "tcp://127.0.0.1:1",
            "DOCKER_CONTEXT": "foreign-context",
        },
    )
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
    assert "strictPort: true" in source


def test_start_routes_vite_proxy_to_the_resolved_backend_port() -> None:
    source = (ROOT / "start.sh").read_text(encoding="utf-8")

    assert 'export VITE_API_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}"' in source


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
    assert "qdrant_port=0" in source
    assert "requires_qdrant" in source


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


def test_prometheus_scrapes_clean_start_data_and_generation_targets() -> None:
    import yaml

    payload = yaml.safe_load((ROOT / "infra" / "prometheus.yml").read_text(encoding="utf-8"))
    scrape_configs = payload["scrape_configs"]
    jobs = {config["job_name"]: config for config in scrape_configs}

    assert set(jobs) == {"prometheus", "ragweld-api-host", "postgres", "litellm", "vllm"}
    api_targets = jobs["ragweld-api-host"]["static_configs"][0]["targets"]
    assert api_targets == ["host.docker.internal:58012"]
    assert jobs["litellm"]["metrics_path"] == "/metrics"
    assert jobs["litellm"]["static_configs"][0]["targets"] == ["litellm:4000"]
    assert jobs["vllm"]["metrics_path"] == "/metrics"
    # The local-model server is a host process; Prometheus (in the VM) scrapes
    # it through the Docker host gateway.
    assert jobs["vllm"]["static_configs"][0]["targets"] == ["host.docker.internal:58080"]

    compose = _compose_config("docker-compose.yml")
    assert "--web.enable-remote-write-receiver" in compose["services"]["prometheus"]["command"]


def test_prometheus_forwards_to_mimir_and_routes_alerts_to_alertmanager() -> None:
    import yaml

    payload = yaml.safe_load((ROOT / "infra" / "prometheus.yml").read_text(encoding="utf-8"))

    # Long-range retention: every WAL sample (scrapes + Tempo span metrics
    # received over remote write) is forwarded to Mimir.
    remote_write = payload["remote_write"]
    assert remote_write == [{"url": "http://mimir:9009/api/v1/push"}]

    alert_targets = [
        target
        for manager in payload["alerting"]["alertmanagers"]
        for static in manager["static_configs"]
        for target in static["targets"]
    ]
    assert alert_targets == ["alertmanager:9093"]
    assert payload["rule_files"] == ["/etc/prometheus/prometheus-rules.yml"]

    rules = yaml.safe_load((ROOT / "infra" / "prometheus-rules.yml").read_text(encoding="utf-8"))
    alert_names = {
        rule["alert"]
        for group in rules["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    # The watchdog proves the Prometheus -> Alertmanager delivery pipe end to
    # end; the target-down rules cover the serving/data-plane jobs.
    assert "RagweldWatchdog" in alert_names
    assert {"RagweldApiDown", "RagweldGatewayDown", "RagweldLocalModelDown", "RagweldPostgresDown"} <= alert_names

    compose = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    prometheus = compose["services"]["prometheus"]
    rules_mount = _volume_for_target(prometheus, "/etc/prometheus/prometheus-rules.yml")
    assert Path(rules_mount["source"]).resolve() == (ROOT / "infra" / "prometheus-rules.yml").resolve()


def test_a3_fabric_services_are_managed_loopback_and_volume_backed() -> None:
    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    services = config["services"]

    fabric = {
        "mimir",
        "pyroscope",
        "alertmanager",
        "langfuse",
        "langfuse-worker",
        "langfuse-postgres",
        "langfuse-clickhouse",
        "langfuse-redis",
        "langfuse-minio",
    }
    assert fabric <= set(services)

    for name in fabric:
        service = services[name]
        assert "container_name" not in service
        assert service["labels"]["io.ragweld.managed"] == "true"
        for port in service.get("ports", []):
            assert port.get("host_ip") == "127.0.0.1"

    # Only the operator-facing surfaces publish host ports; the Langfuse
    # dependency plane stays VM-internal.
    assert _published_ports(services["mimir"]) == {59009}
    assert _published_ports(services["pyroscope"]) == {54040}
    assert _published_ports(services["alertmanager"]) == {59093}
    assert _published_ports(services["langfuse"]) == {53000}
    for internal in ("langfuse-worker", "langfuse-postgres", "langfuse-clickhouse", "langfuse-redis", "langfuse-minio"):
        assert _published_ports(services[internal]) == set()

    # Durable state lives in project-scoped named volumes.
    assert _volume_for_target(services["mimir"], "/data")["type"] == "volume"
    assert _volume_for_target(services["pyroscope"], "/data")["type"] == "volume"
    assert _volume_for_target(services["alertmanager"], "/alertmanager")["type"] == "volume"
    assert _volume_for_target(services["langfuse-postgres"], "/var/lib/postgresql/data")["type"] == "volume"
    assert _volume_for_target(services["langfuse-clickhouse"], "/var/lib/clickhouse")["type"] == "volume"
    assert _volume_for_target(services["langfuse-minio"], "/data")["type"] == "volume"

    mimir_config = _volume_for_target(services["mimir"], "/etc/mimir/mimir.yaml")
    assert Path(mimir_config["source"]).resolve() == (ROOT / "infra" / "mimir.yaml").resolve()
    alertmanager_config = _volume_for_target(services["alertmanager"], "/etc/alertmanager/alertmanager.yml")
    assert Path(alertmanager_config["source"]).resolve() == (ROOT / "infra" / "alertmanager.yml").resolve()

    # Native default ports stay unpublished so foreign local listeners are
    # never mistaken for Ragweld services.
    published = set().union(*(_published_ports(services[name]) for name in fabric))
    assert published.isdisjoint({9009, 4040, 9093, 3000, 8123, 6379, 9000, 12347})

    launcher = (ROOT / "start.sh").read_text(encoding="utf-8")
    observability_line = re.search(r"services\+=\(([^)]*)\)\s*\n\s*fi\s*\n\s*if \[\[ \"\$WITH_FLYTE\"", launcher)
    assert observability_line is not None
    started = set(observability_line.group(1).split())
    assert fabric <= started


def test_alloy_faro_receiver_feeds_loki_and_tempo() -> None:
    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    alloy = config["services"]["alloy"]
    assert 52347 in _published_ports(alloy)
    # CORS follows the Vite port through Compose so a FRONTEND_PORT override
    # cannot silently reject beacons.
    assert alloy["environment"]["ALLOY_FARO_CORS_ORIGIN"] == "http://127.0.0.1:55173"
    assert alloy["environment"]["ALLOY_FARO_CORS_ORIGIN_LOCALHOST"] == "http://localhost:55173"

    source = (ROOT / "infra" / "alloy" / "config.alloy").read_text(encoding="utf-8")
    assert 'faro.receiver "web"' in source
    assert "listen_port    = 12347" in source
    assert 'sys.env("ALLOY_FARO_CORS_ORIGIN")' in source
    # Faro events join the shared streams: logs to Loki, traces to Tempo.
    faro_block = source.split('faro.receiver "web"', 1)[1]
    assert "loki.write.default.receiver" in faro_block
    assert "otelcol.exporter.otlp.tempo.input" in faro_block


def test_active_observability_urls_match_namespaced_loopback_ports() -> None:
    from server.api.docker import _loki_candidate_urls
    from server.models.tribrid_config_model import TriBridConfig

    active = json.loads((ROOT / "tribrid_config.json").read_text(encoding="utf-8"))
    assert active["tracing"]["tracing_mode"] == "otel_langfuse"
    assert active["ui"]["grafana_base_url"] == "http://127.0.0.1:3301"
    assert active["tracing"]["tempo_base_url"] == "http://127.0.0.1:53200"
    assert active["tracing"]["alloy_base_url"] == "http://127.0.0.1:52345"
    assert active["tracing"]["otlp_endpoint"] == "http://127.0.0.1:54320/v1/traces"
    # A3 fabric: every deployed component is configured at its namespaced
    # loopback port; OpenCost stays empty (needs a Kubernetes runtime).
    assert active["tracing"]["mimir_base_url"] == "http://127.0.0.1:59009"
    assert active["tracing"]["pyroscope_base_url"] == "http://127.0.0.1:54040"
    assert active["tracing"]["faro_base_url"] == "http://127.0.0.1:52347/collect"
    assert active["tracing"]["alertmanager_base_url"] == "http://127.0.0.1:59093"
    assert active["tracing"]["langfuse_enabled"] is True
    assert active["tracing"]["langfuse_base_url"] == "http://127.0.0.1:53000"
    assert active["tracing"]["opencost_base_url"] == ""
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


def test_generation_gateway_topology_is_pinned_local_and_has_no_paid_fallback() -> None:
    import yaml
    from server.models.tribrid_config_model import TriBridConfig

    config = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    services = config["services"]

    # Local generation is a HOST process (vllm-metal on Apple Silicon); the
    # in-VM vLLM service and its weight-cache volume are gone.
    assert "vllm" not in services
    assert "hf_cache" not in config.get("volumes", {})

    litellm = services["litellm"]
    api = services["api"]

    assert litellm["image"] == "ghcr.io/berriai/litellm:v1.94.0"
    assert _published_ports(litellm) == {54000}
    assert all(port.get("host_ip") == "127.0.0.1" for port in litellm["ports"])

    launcher = (ROOT / "start.sh").read_text(encoding="utf-8")
    local_model_id = "mlx-community/Qwen3.8-27B-4bit"
    assert f'LOCAL_MODEL_ID="{local_model_id}"' in launcher
    max_len_match = re.search(r"^LOCAL_MODEL_MAX_LEN=(\d+)$", launcher, re.MULTILINE)
    assert max_len_match is not None
    max_model_len = int(max_len_match.group(1))
    assert max_model_len == 32768
    # Measured on this host (M4 Pro 48 GiB, VM at 16 GiB): 0.50 of unified
    # memory fits the 15 GiB 4-bit weights plus a 32k-token KV cache.
    assert 'LOCAL_MODEL_MEMORY_FRACTION="0.50"' in launcher
    assert "--served-model-name ragweld-local" in launcher
    assert '--default-chat-template-kwargs \'{"enable_thinking": false}\'' in launcher
    assert "--no-local-model" in launcher
    assert "pip install vllm-metal" in launcher  # fail-closed missing-venv hint
    # The port is pinned: LiteLLM's generated config, the Compose api service,
    # and Prometheus all target 58080; an env override would split-brain them.
    assert re.search(r"^LOCAL_MODEL_PORT=58080$", launcher, re.MULTILINE)
    # The readiness gate verifies the served identity, not just a listener.
    assert '"\\"root\\":\\"${LOCAL_MODEL_ID}\\""' in launcher
    assert '"\\"max_model_len\\":${LOCAL_MODEL_MAX_LEN}[,}]"' in launcher
    # --docker-backend must not race the containerized API healthcheck against
    # the model load.
    assert 'BACKEND_MODE" == "docker" && "$START_LOCAL_MODEL" == "1"' in launcher
    stopper = (ROOT / "stop.sh").read_text(encoding="utf-8")
    assert 'stop_owned_process "local-model" "$ROOT_DIR"' in stopper
    lifecycle = (ROOT / "scripts" / "runtime_lifecycle.sh").read_text(encoding="utf-8")
    # Force-stopping the owned parent must sweep validated descendants (the
    # memory-heavy EngineCore child) instead of orphaning them.
    assert "descendant_pids()" in lifecycle
    assert lifecycle.count("stop_process_descendants ") >= 2

    runtime_config = TriBridConfig()
    assert runtime_config.chat.max_tokens <= max_model_len // 2
    assert runtime_config.generation.gen_max_tokens <= max_model_len // 2
    assert runtime_config.chat.vllm.default_model == local_model_id
    assert runtime_config.chat.vllm.base_url == "http://127.0.0.1:58080/v1"
    catalog = json.loads((ROOT / "data" / "models.json").read_text(encoding="utf-8"))
    local_rows = [row for row in catalog["models"] if row.get("provider") == "ragweld"]
    assert len(local_rows) == 1
    assert local_rows[0]["model"] == local_model_id
    assert local_rows[0]["context"] == max_model_len
    assert local_rows[0]["base_url"] == "http://host.docker.internal:58080/v1"

    # Containers reach the host process through the Docker host gateway.
    assert "host.docker.internal=host-gateway" in litellm["extra_hosts"]
    assert "host.docker.internal=host-gateway" in api["extra_hosts"]
    assert "depends_on" not in litellm
    assert api["depends_on"]["litellm"]["condition"] == "service_healthy"
    assert api["environment"]["LITELLM_BASE_URL"] == "http://litellm:4000/v1"
    assert api["environment"]["VLLM_BASE_URL"] == "http://host.docker.internal:58080/v1"
    assert api["environment"]["OPENROUTER_API_KEY"] == ""

    config_mount = _volume_for_target(litellm, "/app/config.yaml")
    assert config_mount["read_only"] is True
    assert Path(config_mount["source"]).resolve() == (ROOT / "infra/litellm-config.yaml").resolve()

    gateway = yaml.safe_load((ROOT / "infra/litellm-config.yaml").read_text(encoding="utf-8"))
    from server.gateway_catalog import build_model_list, load_catalog

    assert gateway["model_list"] == build_model_list(load_catalog(ROOT / "data/models.json"))
    assert gateway["model_list"][0]["model_name"] == "ragweld-local"
    assert gateway["model_list"][0]["litellm_params"] == {
        "model": "openai/ragweld-local",
        "api_base": "http://host.docker.internal:58080/v1",
        "api_key": "none",
    }
    routed = gateway["model_list"][1:]
    assert len(routed) >= 300
    assert all(row["litellm_params"]["model"].startswith("openrouter/") for row in routed)
    assert all(row["litellm_params"]["api_key"] == "os.environ/OPENROUTER_API_KEY" for row in routed)
    assert all("api_base" not in row["litellm_params"] for row in routed)
    assert "ragweld-openrouter-smoke" not in {row["model_name"] for row in gateway["model_list"]}

    assert "unset OPENROUTER_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY" in launcher
    assert "colima start --profile ragweld --vm-type vz --cpu 6 --memory 16" in launcher
    assert gateway["litellm_settings"]["num_retries"] == 0
    assert gateway["litellm_settings"].get("fallbacks", []) == []
    assert gateway["litellm_settings"].get("context_window_fallbacks", []) == []
    assert gateway["litellm_settings"]["callbacks"] == ["prometheus"]
    assert gateway["litellm_settings"]["require_auth_for_metrics_endpoint"] is False

    litellm_health = " ".join(str(part) for part in litellm["healthcheck"]["test"])
    assert "/v1/models" in litellm_health
    assert "LITELLM_MASTER_KEY" in litellm_health
    assert "Authorization" in litellm_health
    api_health = " ".join(str(part) for part in api["healthcheck"]["test"])
    assert "/api/ready" in api_health
    # /api/ready needs the host local model; the healthcheck start period must
    # cover its measured ~100 s load time.
    assert api["healthcheck"]["start_period"] == "2m30s"
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "http://localhost:8000/api/ready" in dockerfile
    assert "http://localhost:8000/health" not in dockerfile

    gateway_dashboard = json.loads(
        (ROOT / "infra/grafana/provisioning/dashboards/gateway-serving.json").read_text(encoding="utf-8")
    )
    dashboard_source = json.dumps(gateway_dashboard)
    assert "tribrid_search_" not in dashboard_source
    assert "tribrid_vector_leg_" not in dashboard_source
    assert "litellm_proxy_total_requests_metric_total" in dashboard_source
    assert "litellm_request_total_latency_metric_bucket" in dashboard_source
    assert "vllm:num_requests_running" in dashboard_source
    assert "vllm:num_requests_waiting" in dashboard_source
