from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROXMOX_PRODUCTION_COMPOSE = "deploy/proxmox/docker-compose.yml"
PROXMOX_PRODUCTION_CONTRACT_ENV = {
    "GRAFANA_ADMIN_PASSWORD": "contract-only",
    "LANGFUSE_OIDC_CLIENT_SECRET": "contract-only",
    "LANGFUSE_POSTGRES_PASSWORD": "contract-langfuse-postgres",
    "CLICKHOUSE_PASSWORD": "contract-langfuse-clickhouse",
    "REDIS_AUTH": "contract-langfuse-redis",
    "LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID": "contract-langfuse-minio-user",
    "LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY": "contract-langfuse-minio-password",
}


def _required_compose_env_keys(path: Path) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"\$\{([A-Z0-9_]+):\?set \1\}", path.read_text(encoding="utf-8"))
    }


def _run(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    run_cwd = cwd or ROOT
    if env and "RAGWELD_RUNTIME_DIR" in env:
        return subprocess.run(
            list(args),
            cwd=run_cwd,
            env=merged_env,
            text=True,
            capture_output=True,
            check=False,
        )
    with tempfile.TemporaryDirectory(prefix="ragweld-runtime-test-") as runtime_dir:
        merged_env["RAGWELD_RUNTIME_DIR"] = runtime_dir
        return subprocess.run(
            list(args),
            cwd=run_cwd,
            env=merged_env,
            text=True,
            capture_output=True,
            check=False,
        )


def _materialize_start_sh_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "start.sh").write_text((ROOT / "start.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (repo / "scripts" / "runtime_lifecycle.sh").write_text(
        (ROOT / "scripts" / "runtime_lifecycle.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return repo


def _compose_config(*files: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    version = _run("docker", "compose", "version")
    if version.returncode != 0:
        pytest.skip("docker compose plugin is unavailable")

    merged_env: dict[str, str] = {}
    if PROXMOX_PRODUCTION_COMPOSE in files:
        required_keys = _required_compose_env_keys(ROOT / PROXMOX_PRODUCTION_COMPOSE)
        assert required_keys == set(PROXMOX_PRODUCTION_CONTRACT_ENV), (
            "update PROXMOX_PRODUCTION_CONTRACT_ENV to match required deploy/proxmox/docker-compose.yml keys"
        )
        merged_env.update(PROXMOX_PRODUCTION_CONTRACT_ENV)
    if env:
        merged_env.update(env)

    args = ["docker", "compose", "--project-name", "ragweld"]
    for file_name in files:
        args.extend(["-f", file_name])
    args.extend(["config", "--format", "json"])
    result = _run(*args, env=merged_env or None)
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


def test_start_check_defaults_backend_bind_to_loopback(tmp_path: Path) -> None:
    repo = _materialize_start_sh_repo(tmp_path)
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-frontend",
        "--no-local-model",
        env={"BACKEND_PORT": "58112", "SERVER_HOST": ""},
        cwd=repo,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 0, output
    assert "--host 127.0.0.1 --port 58112" in output


@pytest.mark.parametrize("credential_source", ["inherited", "dotenv"])
def test_host_launcher_discards_gateway_provider_keys_before_app_launch(tmp_path: Path, credential_source: str) -> None:
    repo = _materialize_start_sh_repo(tmp_path)
    provider_keys = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
    env = {key: "synthetic-upstream-credential" if credential_source == "inherited" else "" for key in provider_keys}
    env["LITELLM_API_KEY"] = "synthetic-gateway-client"
    if credential_source == "dotenv":
        (repo / ".env").write_text(
            "".join(f"{key}=synthetic-upstream-credential\n" for key in provider_keys), encoding="utf-8",
        )
        # No inherited export may shadow the file values being exercised.
        prelude = "unset " + " ".join(provider_keys) + "; "
    else:
        prelude = ""
    result = _run(
        "bash", "-c",
        prelude + "source ./start.sh --check --no-docker --no-backend --no-frontend --no-local-model; "
        "for key in " + " ".join(provider_keys) + '; do [[ -z "${!key:-}" ]] || exit 91; done; '
        '[[ "$LITELLM_API_KEY" == synthetic-gateway-client ]]',
        env=env, cwd=repo,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_direct_app_import_discards_inherited_gateway_provider_keys() -> None:
    provider_keys = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
    result = _run(
        sys.executable, "-c",
        "import os; import server.main; "
        f"assert all(key not in os.environ for key in {provider_keys!r}); "
        "assert os.environ['LITELLM_API_KEY'] == 'synthetic-gateway-client'",
        env={
            **{key: "synthetic-upstream-credential" for key in provider_keys},
            "LITELLM_API_KEY": "synthetic-gateway-client",
            "RAGWELD_LOAD_DOTENV": "0", "RAGWELD_DISABLE_PROFILING": "1",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_start_check_honors_server_host_override_for_backend_bind(tmp_path: Path) -> None:
    repo = _materialize_start_sh_repo(tmp_path)
    result = _run(
        "bash",
        "start.sh",
        "--check",
        "--no-docker",
        "--no-frontend",
        "--no-local-model",
        env={"BACKEND_PORT": "58113", "SERVER_HOST": "0.0.0.0"},
        cwd=repo,
    )
    output = f"{result.stdout}\n{result.stderr}"

    assert result.returncode == 0, output
    assert "--host 0.0.0.0 --port 58113" in output


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


def test_neo4j_runtime_pins_gds_213_and_requires_functional_readiness() -> None:
    config = _compose_config("docker-compose.yml")
    neo4j = config["services"]["neo4j"]
    environment = neo4j["environment"]

    assert environment["NEO4J_PLUGINS"] == '["apoc", "graph-data-science"]'
    assert environment["NEO4J_dbms_security_procedures_unrestricted"] == "apoc.*,gds.*"
    assert environment["NEO4J_dbms_security_procedures_allowlist"] == "apoc.*,gds.*"
    healthcheck = " ".join(neo4j["healthcheck"]["test"])
    assert "gds.version()" in healthcheck
    assert "2\\.13\\." in healthcheck

    readiness_source = (ROOT / "server" / "api" / "health.py").read_text(encoding="utf-8")
    neo4j_source = (ROOT / "server" / "db" / "neo4j.py").read_text(encoding="utf-8")
    assert "gds_version" in readiness_source
    assert "CALL gds.version()" in neo4j_source


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
    removed_keys = {
        "DOCKER_INFRA_UP_TIMEOUT",
        "DOCKER_INFRA_DOWN_TIMEOUT",
        # Tooltips of the alert-thresholds form that posted to a route which never
        # existed (2026-08-25 drive finding M10); the form and its store are gone.
        "COHERE_RERANK_CALLS",
        "ENDPOINT_CALL_FREQUENCY",
        "ENDPOINT_SUSTAINED_DURATION",
        "ERROR_RATE_THRESHOLD",
        "RATE_LIMIT_ERRORS_THRESHOLD",
        "TIMEOUT_ERRORS_THRESHOLD",
    }
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

    assert set(jobs) == {"prometheus", "ragweld-api-host", "postgres", "litellm", "vllm", "laya"}
    # Laya always runs beside the platform, so it is scraped statically on the Compose
    # network (its own /metrics); the alert, not the scrape, is gated on use.
    assert jobs["laya"]["metrics_path"] == "/metrics"
    assert jobs["laya"]["static_configs"] == [{"targets": ["laya:8000"]}]
    api_targets = jobs["ragweld-api-host"]["static_configs"][0]["targets"]
    assert api_targets == ["host.docker.internal:58012"]
    assert jobs["litellm"]["metrics_path"] == "/metrics"
    assert jobs["litellm"]["static_configs"][0]["targets"] == ["litellm:4000"]
    assert jobs["vllm"]["metrics_path"] == "/metrics"
    # The local-model server is a host process that runs only when the launcher runs
    # that lane, so its target is discovered from a file the launcher writes (file_sd),
    # never listed statically: a static target is `up == 0` forever on a host without
    # the lane and keeps RagweldLocalModelDown firing.
    assert "static_configs" not in jobs["vllm"]
    assert jobs["vllm"]["file_sd_configs"] == [{"files": ["/etc/prometheus/targets/vllm.json"]}]

    compose = _compose_config("docker-compose.yml")
    prometheus = compose["services"]["prometheus"]
    assert "--web.enable-remote-write-receiver" in prometheus["command"]
    targets_mount = _volume_for_target(prometheus, "/etc/prometheus/targets")
    assert targets_mount.get("read_only") is True
    assert Path(targets_mount["source"]).resolve() == (ROOT / ".ragweld-runtime" / "prometheus-targets").resolve()
    lifecycle = (ROOT / "scripts" / "runtime_lifecycle.sh").read_text(encoding="utf-8")
    assert 'RAGWELD_PROMETHEUS_TARGETS_DIR="${ROOT_DIR}/.ragweld-runtime/prometheus-targets"' in lifecycle
    assert 'RAGWELD_LOCAL_MODEL_TARGETS_FILE="${RAGWELD_PROMETHEUS_TARGETS_DIR}/vllm.json"' in lifecycle


def _lifecycle_shell(repo: Path, script: str) -> subprocess.CompletedProcess[str]:
    return _run("bash", "-c", f'set -euo pipefail; ROOT_DIR="$PWD"; source scripts/runtime_lifecycle.sh; {script}', cwd=repo)


def test_local_model_scrape_target_exists_only_while_the_lane_is_published(tmp_path: Path) -> None:
    repo = _materialize_start_sh_repo(tmp_path)
    targets_file = repo / ".ragweld-runtime" / "prometheus-targets" / "vllm.json"

    published = _lifecycle_shell(repo, "publish_local_model_scrape_target 58080")
    assert published.returncode == 0, published.stderr
    assert json.loads(targets_file.read_text(encoding="utf-8")) == [{"targets": ["host.docker.internal:58080"]}]
    # Prometheus reads the mount as `nobody`, while the lifecycle umask is 077.
    assert stat.S_IMODE(targets_file.parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(targets_file.stat().st_mode) == 0o644

    # Idempotent in both directions: withdrawing twice, or with no file, is not an error.
    for _ in range(2):
        withdrawn = _lifecycle_shell(repo, "withdraw_local_model_scrape_target")
        assert withdrawn.returncode == 0, withdrawn.stderr
        assert not targets_file.exists()


def test_start_without_the_local_model_withdraws_a_stale_target_and_dry_run_touches_nothing(tmp_path: Path) -> None:
    repo = _materialize_start_sh_repo(tmp_path)
    targets_file = repo / ".ragweld-runtime" / "prometheus-targets" / "vllm.json"
    assert _lifecycle_shell(repo, "publish_local_model_scrape_target 58080").returncode == 0

    dry = _run("bash", "start.sh", "--check", "--no-docker", "--no-backend", "--no-frontend", "--no-local-model", cwd=repo)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "Would withdraw the stale local-model scrape target" in dry.stdout
    assert targets_file.exists(), "--check must not change the scrape target"

    dry_with_model = _run("bash", "start.sh", "--check", "--no-docker", "--no-backend", "--no-frontend", cwd=repo)
    assert dry_with_model.returncode == 0, dry_with_model.stdout + dry_with_model.stderr
    assert "Would publish the local-model scrape target" in dry_with_model.stdout

    # A real launch (nothing to start) still withdraws the stale target. The Langfuse
    # secrets file is pre-created so the launcher does not generate one here.
    (repo / "infra").mkdir()
    (repo / "infra" / "langfuse.env").write_text("# test\n", encoding="utf-8")
    real = _run("bash", "start.sh", "--no-docker", "--no-backend", "--no-frontend", "--no-local-model", cwd=repo)
    assert real.returncode == 0, real.stdout + real.stderr
    assert not targets_file.exists()


LAYA_DIR = ROOT / "infra" / "laya"


def _laya_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in (LAYA_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        assert separator and version, f"unpinned Laya requirement: {line}"
        pins[name.strip().lower()] = version.strip()
    return pins


def test_laya_image_is_pinned_cpu_only_and_runs_unprivileged() -> None:
    pins = _laya_pins()
    assert pins["laya"] == "0.3.11"
    # CPU wheels only: a CUDA torch would drag in gigabytes of GPU libraries LXC100 cannot use.
    assert pins["torch"].endswith("+cpu")
    assert not [name for name in pins if name.startswith(("nvidia-", "triton", "cuda"))]
    assert "prometheus-client" in pins and "fastapi" in pins and "uvicorn" in pins

    dockerfile = (LAYA_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert [line for line in dockerfile.splitlines() if line.startswith("FROM ")] == [
        "FROM python:3.12.14-slim-bookworm"
    ]
    assert "--extra-index-url https://download.pytorch.org/whl/cpu -r /tmp/requirements.txt" in dockerfile
    assert "HF_HOME=/var/lib/laya/hf" in dockerfile
    assert re.search(r"^USER laya$", dockerfile, re.MULTILINE)
    assert 'CMD ["python", "/opt/laya/ragweld_laya_serve.py"]' in dockerfile


def test_laya_service_is_capped_loopback_managed_and_cache_backed() -> None:
    config = _compose_config("docker-compose.yml")
    laya = config["services"]["laya"]
    environment = laya["environment"]

    assert laya["image"] == f"ragweld-laya:{_laya_pins()['laya']}"
    assert Path(laya["build"]["context"]).resolve() == LAYA_DIR.resolve()
    # A locally built image: never pulled from a registry under that name.
    assert laya["pull_policy"] == "never"
    # Loopback only, on the port system_one.laya_base_url names; promtail ships its logs.
    assert laya["labels"]["io.ragweld.managed"] == "true"
    assert laya["ports"] == [
        {"mode": "ingress", "host_ip": "127.0.0.1", "target": 8000, "published": "58180", "protocol": "tcp"}
    ]
    assert environment["LAYA_HOST"] == "0.0.0.0"
    assert environment["LAYA_PORT"] == "8000"
    assert laya["restart"] == "unless-stopped"

    # A hard memory cap with no swap headroom (swap would push the pressure onto the host),
    # and torch threads equal to the CPU limit.
    assert int(laya["mem_limit"]) == 4 * 1024**3
    assert int(laya["memswap_limit"]) == int(laya["mem_limit"])
    cpus = float(laya["cpus"])
    assert cpus == 4
    for key in ("LAYA_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        assert int(environment[key]) == int(cpus), key
    assert environment["LAYA_DEVICE"] == "cpu"

    # One resident checkpoint. The entrypoint refuses a list and never reads LAYA_PRELOAD,
    # whose upstream default builds every checkpoint.
    assert environment["LAYA_MODELS"] == "english"
    assert "LAYA_PRELOAD" not in environment
    assert "LAYA_AUTO_TASK" not in environment

    # Weights download once into a named volume at HF_HOME.
    cache = _volume_for_target(laya, environment["HF_HOME"])
    assert cache["type"] == "volume"
    assert cache["source"] == "laya_hf_cache"
    assert "laya_hf_cache" in config["volumes"]

    # Healthy means a checkpoint is loaded, not merely a listener.
    probe = " ".join(laya["healthcheck"]["test"])
    assert "http://127.0.0.1:8000/health" in probe and "loaded" in probe

    # Nothing waits on Laya: it is optional and must never gate another service's start.
    for name, service in config["services"].items():
        assert "laya" not in (service.get("depends_on") or {}), name


def test_laya_checkpoint_and_port_are_operator_env_values() -> None:
    config = _compose_config("docker-compose.yml", env={"LAYA_CHECKPOINT": "multilingual", "LAYA_HTTP_PORT": "58190"})
    laya = config["services"]["laya"]
    assert laya["environment"]["LAYA_MODELS"] == "multilingual"
    assert laya["ports"] == [
        {"mode": "ingress", "host_ip": "127.0.0.1", "target": 8000, "published": "58190", "protocol": "tcp"}
    ]


_LAYA_PIN_PROBE = r"""
import sys

sys.path.insert(0, "/opt/laya")
import ragweld_laya_serve as serve

for bad in ("", "english,multilingual", "nope"):
    try:
        serve.configured_checkpoint({"LAYA_MODELS": bad})
    except SystemExit:
        pass
    else:
        raise AssertionError(f"accepted LAYA_MODELS={bad!r}")
assert serve.configured_checkpoint({"LAYA_MODELS": " English "}) == "english"

questions = {"q": {"type": "noul", "instructions": "Is this about billing?"}}
router = serve.build_router("english", preload=False)
assert router.max_loaded == 1, router.max_loaded
for state in (
    {"text": "Mein Konto wurde zweimal belastet, bitte erstatten Sie den doppelten Betrag."},
    {"text": "私のアカウントに二重請求がありました。返金してください。"},
):
    decision = router.route(state, questions)
    assert decision["model"] == "english", decision
    assert decision["repo"] == "convaiinnovations/laya", decision
    assert decision["reason"].startswith("pinned to english (automatic routing chose multilingual"), decision
assert router.route({"text": "I was charged twice for March."}, questions)["model"] == "english"
assert router.route({"text": "I was charged twice."}, questions, model="english")["model"] == "english"
try:
    router.route({"text": "I was charged twice."}, questions, model="multilingual")
except ValueError as exc:
    assert "only the 'english' checkpoint" in str(exc), exc
else:
    raise AssertionError("an explicit request for a second checkpoint was accepted")
assert router.loaded == [], router.loaded

multilingual = serve.build_router("multilingual", preload=False)
decision = multilingual.route({"text": "I was charged twice for March."}, questions)
assert decision["model"] == "multilingual", decision
assert decision["repo"] == "convaiinnovations/laya/multilingual", decision

# The per-request question cap (a 64-question batch was OOM-killed under the 4 GiB cap).
from fastapi.testclient import TestClient

app = serve.create_app(router)
state = {"passage": "Armstrong took semi-automatic control of Eagle to avoid a boulder field."}
too_many = {f"q{i}": {"type": "noul", "instructions": f"Does the passage state fact {i}?"} for i in range(serve.MAX_QUESTIONS_PER_REQUEST + 1)}
answer = TestClient(app).post("/v1/systemone", json={"state": state, "questions": too_many})
assert answer.status_code == 413, (answer.status_code, answer.text)
import laya.serve as laya_serve
laya_serve._check_request_limits(state, dict(list(too_many.items())[: serve.MAX_QUESTIONS_PER_REQUEST]))
assert TestClient(app).get("/metrics").text.count("process_resident_memory_bytes") >= 1
print("laya-pin-ok")
"""


def test_laya_entrypoint_pins_one_checkpoint_against_the_pinned_laya(tmp_path: Path) -> None:
    """Runs the working-tree entrypoint inside the built image (real laya, no weights, no network).

    RAGWELD_LAYA_IMAGE_TESTS=1 runs it on LXC100 after `docker compose build laya`
    (RAGWELD_LAYA_IMAGE overrides the image tag).
    """
    from tests.service_requirements import _strict_mode

    if os.environ.get("RAGWELD_LAYA_IMAGE_TESTS") != "1":
        if _strict_mode():
            pytest.fail("Strict Laya acceptance requires RAGWELD_LAYA_IMAGE_TESTS=1")
        pytest.skip("Laya entrypoint acceptance requires RAGWELD_LAYA_IMAGE_TESTS=1 and the built image on LXC")
    assert sys.platform == "linux" and shutil.which("docker"), "Laya entrypoint acceptance requires LXC Docker"
    image = os.environ.get("RAGWELD_LAYA_IMAGE") or f"ragweld-laya:{_laya_pins()['laya']}"
    probe = tmp_path / "probe.py"
    probe.write_text(_LAYA_PIN_PROBE, encoding="utf-8")
    # File mounts (pytest's tmp dir is owner-only); the image runs as its `laya` user.
    probe.chmod(0o644)
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--memory", "512m", "--cpus", "1",
            "--mount", f"type=bind,src={LAYA_DIR / 'ragweld_laya_serve.py'},dst=/opt/laya/ragweld_laya_serve.py,readonly",
            "--mount", f"type=bind,src={probe},dst=/tmp/probe.py,readonly",
            image, "python", "/tmp/probe.py",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "laya-pin-ok" in result.stdout


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
    assert {
        "RagweldGatewayFailedRequestRatioHigh",
        "RagweldGatewayTtftSlow",
        "RagweldGatewayKeyBudgetLow",
        "RagweldSearchFailures",
        "RagweldSearchStageErrors",
        "RagweldRerankerErrors",
        "RagweldIndexRunFailed",
    } <= alert_names
    expressions = [str(rule["expr"]) for group in rules["groups"] for rule in group["rules"] if "alert" in rule]
    assert all("clamp_min(" not in expr and "vector(0)" not in expr for expr in expressions)
    # Every gateway-quality rule leaves out the local lane, whose health has its own rule.
    gateway_rules = [
        str(rule["expr"])
        for group in rules["groups"]
        for rule in group["rules"]
        if rule.get("alert") in {"RagweldGatewayFailedRequestRatioHigh", "RagweldGatewayTtftSlow"}
    ]
    assert gateway_rules and all('requested_model!="ragweld-local"' in expr for expr in gateway_rules)

    compose = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml")
    prometheus = compose["services"]["prometheus"]
    rules_mount = _volume_for_target(prometheus, "/etc/prometheus/prometheus-rules.yml")
    assert Path(rules_mount["source"]).resolve() == (ROOT / "infra" / "prometheus-rules.yml").resolve()


def test_every_paging_rule_links_a_provisioned_dashboard() -> None:
    import yaml

    rules = yaml.safe_load((ROOT / "infra" / "prometheus-rules.yml").read_text(encoding="utf-8"))
    dashboards_dir = ROOT / "infra" / "grafana" / "provisioning" / "dashboards"
    provisioned = {json.loads(path.read_text(encoding="utf-8"))["uid"] for path in dashboards_dir.glob("*.json")}
    paging = [rule for group in rules["groups"] for rule in group["rules"] if "alert" in rule and rule["alert"] != "RagweldWatchdog"]
    assert paging
    missing = [rule["alert"] for rule in paging if not str(rule["annotations"].get("dashboard", "")).startswith("/d/")]
    assert not missing, f"rules without a dashboard link: {missing}"
    unknown = {rule["alert"]: rule["annotations"]["dashboard"] for rule in paging if rule["annotations"]["dashboard"].removeprefix("/d/") not in provisioned}
    assert not unknown, f"dashboard links to uids Grafana does not provision: {unknown}"


def _receivers_in(route: dict[str, Any]) -> Iterator[str]:
    if route.get("receiver"):
        yield str(route["receiver"])
    for child in route.get("routes") or []:
        yield from _receivers_in(child)


def test_alertmanager_routes_to_discord_from_a_secret_file_and_parks_the_watchdog() -> None:
    import yaml

    source = (ROOT / "infra" / "alertmanager.yml").read_text(encoding="utf-8")
    # Webhook URLs are secrets: only file references may live in the repo. The one URL
    # allowed is the public Grafana root the Discord message links dashboards on, and it
    # must be the root Grafana itself is served at.
    grafana_root = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml", PROXMOX_PRODUCTION_COMPOSE)[
        "services"
    ]["grafana"]["environment"]["GF_SERVER_ROOT_URL"]
    # Whole URLs up to the template brace, so a path or query on any host fails too.
    assert set(re.findall(r"https?://[^\s'\"(){}]+", source)) == {grafana_root}
    payload = yaml.safe_load(source)
    route = payload["route"]
    assert route["receiver"] == "discord"
    assert any(
        child["receiver"] == "null" and child["matchers"] == ['alertname="RagweldWatchdog"']
        for child in route["routes"]
    )
    receivers = {receiver["name"]: receiver for receiver in payload["receivers"]}
    assert set(receivers["null"]) == {"name"}
    [discord] = receivers["discord"]["discord_configs"]
    assert discord["webhook_url_file"] == "/etc/ragweld/alertmanager-discord-webhook"
    assert discord["send_resolved"] is True
    # The message links each rule's dashboard on the public Grafana, never the
    # Prometheus generatorURL (a container hostname no reader can open).
    assert f"({grafana_root}{{{{ . }}}})" in discord["message"]
    assert "{{ with .Annotations.dashboard }}" in discord["message"]
    assert "GeneratorURL" not in discord["message"] and "GeneratorURL" not in discord["title"]
    # Slack is ready but never routed until the operator switches it on.
    assert receivers["slack"]["slack_configs"] == [
        {"api_url_file": "/etc/ragweld/alertmanager-slack-webhook", "send_resolved": True}
    ]
    assert "slack" not in set(_receivers_in(route))

    compose = _compose_config("docker-compose.yml", "infra/docker-compose.observability.yml", PROXMOX_PRODUCTION_COMPOSE)
    alertmanager = compose["services"]["alertmanager"]
    # webhook_url_file for Discord is rejected by v0.27 ("no discord webhook URL provided").
    version = re.search(r":v(\d+)\.(\d+)\.(\d+)$", alertmanager["image"])
    assert version and (int(version.group(1)), int(version.group(2))) >= (0, 28), alertmanager["image"]
    # The secret is 0600 runtime-user owned; the image's `nobody` cannot read it.
    assert alertmanager["user"] == "0:0"
    secret = _volume_for_target(alertmanager, "/etc/ragweld/alertmanager-discord-webhook")
    assert secret["source"] == "/etc/ragweld/alertmanager-discord-webhook"
    assert secret["read_only"] is True
    # Older compose-go JSON encoders omit false booleans (the CI runner's does), current ones
    # keep this opt-out: require it in the source file and reject a rendered true value.
    class ComposeFileLoader(yaml.SafeLoader):
        """The file as written; Compose merge tags (!override, !reset) keep their value."""

    def tagged(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
        if isinstance(node, yaml.MappingNode):
            return loader.construct_mapping(node, deep=True)
        if isinstance(node, yaml.SequenceNode):
            return loader.construct_sequence(node, deep=True)
        return loader.construct_scalar(node)  # type: ignore[arg-type]

    ComposeFileLoader.add_multi_constructor("!", tagged)
    declared = yaml.load((ROOT / PROXMOX_PRODUCTION_COMPOSE).read_text(encoding="utf-8"), Loader=ComposeFileLoader)  # noqa: S506 - SafeLoader subclass
    [declared_secret] = [
        volume
        for volume in declared["services"]["alertmanager"]["volumes"]
        if isinstance(volume, dict) and volume.get("target") == "/etc/ragweld/alertmanager-discord-webhook"
    ]
    assert declared_secret["bind"]["create_host_path"] is False
    assert secret.get("bind", {}).get("create_host_path", False) is False
    start_runtime = (ROOT / "deploy" / "proxmox" / "start-runtime.sh").read_text(encoding="utf-8")
    assert '  "alertmanager-discord-webhook"\n' in start_runtime.split("readonly REQUIRED_SECRET_FILES=(", 1)[1].split(")", 1)[0]


def test_alert_rules_fire_on_real_problems_and_never_on_the_disabled_local_lane(tmp_path: Path) -> None:
    """Real PromQL engine (promtool on the pinned Prometheus image), no reimplemented rules.

    RAGWELD_DASHBOARD_QUERY_TESTS=1 runs it on LXC100, which has Docker and the image.
    """
    import yaml

    from tests.service_requirements import _strict_mode

    if os.environ.get("RAGWELD_DASHBOARD_QUERY_TESTS") != "1":
        if _strict_mode():
            pytest.fail("Strict rule acceptance requires RAGWELD_DASHBOARD_QUERY_TESTS=1")
        pytest.skip("Real alert-rule acceptance requires RAGWELD_DASHBOARD_QUERY_TESTS=1 on LXC")
    assert sys.platform == "linux" and shutil.which("docker"), "Alert-rule acceptance requires LXC Docker"

    up = [
        {"series": 'up{job="ragweld-api-host"}', "values": "1x40"},
        {"series": 'up{job="litellm"}', "values": "1x40"},
        {"series": 'up{job="postgres"}', "values": "1x40"},
    ]
    watchdog = [{"exp_labels": {"severity": "none"}, "exp_annotations": {
        "summary": "Alerting pipeline watchdog",
        "description": "This alert is always firing. If it is missing from Alertmanager, Prometheus rule evaluation or alert delivery is broken.",
    }}]

    def quiet(*names: str, at: str = "30m") -> list[dict[str, Any]]:
        return [{"eval_time": at, "alertname": name, "exp_alerts": []} for name in names]

    total = "litellm_proxy_total_requests_metric_total"
    failed = "litellm_proxy_failed_requests_metric_total"
    ttft = "litellm_llm_api_time_to_first_token_metric"
    tests = [
        {
            # Local lane off: no vllm target, so no series and no alert; idle gateway is quiet.
            "interval": "1m",
            "input_series": up + [
                {"series": f'{total}{{requested_model="z-ai.glm-5.3-flash"}}', "values": "0x40"},
                # An unlimited key reports +Inf.
                {"series": 'litellm_remaining_api_key_budget_metric{hashed_api_key="k"}', "values": " ".join(["Inf"] * 41)},
            ],
            "alert_rule_test": [{"eval_time": "30m", "alertname": "RagweldWatchdog", "exp_alerts": watchdog}]
            + quiet("RagweldLocalModelDown", "RagweldGatewayFailedRequestRatioHigh", "RagweldGatewayKeyBudgetLow"),
        },
        {
            # Local lane running and down: the alert fires.
            "interval": "1m",
            "input_series": up + [{"series": 'up{job="vllm",instance="host.docker.internal:58080"}', "values": "0x40"}],
            "alert_rule_test": [
                {
                    "eval_time": "10m",
                    "alertname": "RagweldLocalModelDown",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "job": "vllm", "instance": "host.docker.internal:58080"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-oncall-overview",
                                "summary": "Local model server is not being scraped",
                                "description": "The local-model lane is running on this host but its vllm-metal server has been unreachable for 5 minutes. Local generation requests fail until it is restarted.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # Only the disabled local alias fails, and cloud traffic succeeds without a
            # failure series ever existing: no gateway alert.
            "interval": "1m",
            "input_series": up + [
                {"series": f'{total}{{requested_model="ragweld-local"}}', "values": "0+2x40"},
                {"series": f'{failed}{{requested_model="ragweld-local"}}', "values": "0+2x40"},
                {"series": f'{total}{{requested_model="openai.gpt-6-luna"}}', "values": "0+1x40"},
            ],
            "alert_rule_test": quiet("RagweldGatewayFailedRequestRatioHigh"),
        },
        {
            # Half of the cloud requests fail at volume: the ratio alert fires.
            "interval": "1m",
            "input_series": up + [
                {"series": f'{total}{{requested_model="z-ai.glm-5.3-flash"}}', "values": "0+2x40"},
                {"series": f'{failed}{{requested_model="z-ai.glm-5.3-flash"}}', "values": "0+1x40"},
            ],
            "alert_rule_test": [
                {
                    "eval_time": "30m",
                    "alertname": "RagweldGatewayFailedRequestRatioHigh",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-gateway-serving",
                                "summary": "More than 20% of gateway requests are failing",
                                "description": "Over the last 10 minutes more than 20% of LiteLLM proxy requests (at least 5 requests) returned a failure to the client. Check the Gateway & Serving dashboard (deployment failures by exception) and the provider's status.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # Streams whose first chunk lands between 30 s and 45 s fire the TTFT alert for
            # that model only; the same stall on ragweld-local does not.
            "interval": "1m",
            "input_series": up
            + [
                {"series": f'{ttft}_bucket{{requested_model="{model}",le="{le}"}}', "values": values}
                for model in ("z-ai.glm-5.3-flash", "ragweld-local")
                for le, values in (("1.0", "0x40"), ("30.0", "0x40"), ("45.0", "0+1x40"), ("+Inf", "0+1x40"))
            ]
            + [
                {"series": f'{ttft}_count{{requested_model="{model}"}}', "values": "0+1x40"}
                for model in ("z-ai.glm-5.3-flash", "ragweld-local")
            ],
            "alert_rule_test": [
                {
                    "eval_time": "30m",
                    "alertname": "RagweldGatewayTtftSlow",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "requested_model": "z-ai.glm-5.3-flash"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-gateway-serving",
                                "summary": "Gateway time to first token p95 above 30 s for z-ai.glm-5.3-flash",
                                "description": "The p95 time to the first streamed chunk for z-ai.glm-5.3-flash has been above 30 seconds over 15 minutes (at least 3 streamed requests). Users see a stalled answer. Check the provider and consider another model.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # A reranker error and an index failure each alert; flat counters stay quiet.
            "interval": "1m",
            "input_series": up + [
                {"series": 'tribrid_reranker_errors_total{mode="cloud"}', "values": "0x20 1x20"},
                {"series": 'tribrid_reranker_errors_total{mode="learning"}', "values": "0x40"},
                {"series": "tribrid_index_errors_total", "values": "0x20 1x20"},
                {"series": 'tribrid_search_stage_errors_total{stage="rerank"}', "values": "0x40"},
                {"series": "tribrid_search_errors_total", "values": "0x40"},
                {"series": 'litellm_remaining_api_key_budget_metric{hashed_api_key="k"}', "values": "3x40"},
            ],
            "alert_rule_test": [
                {
                    "eval_time": "25m",
                    "alertname": "RagweldGatewayKeyBudgetLow",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "hashed_api_key": "k"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-cost-capacity",
                                "summary": "Gateway API key budget almost spent",
                                "description": "A LiteLLM API key has less than $5 of budget left (3.00). Requests fail once it reaches zero.",
                            },
                        }
                    ],
                },
                {
                    "eval_time": "25m",
                    "alertname": "RagweldRerankerErrors",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "mode": "cloud"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-retrieval-indexing-graph",
                                "summary": "Reranker (cloud) is failing",
                                "description": "The cloud reranker raised errors in the last 15 minutes; affected searches return un-reranked results.",
                            },
                        }
                    ],
                },
                {
                    "eval_time": "25m",
                    "alertname": "RagweldIndexRunFailed",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-retrieval-indexing-graph",
                                "summary": "An indexing run failed",
                                "description": "At least one indexing run ended in error in the last 30 minutes. Open the corpus's index run history for the failing stage.",
                            },
                        }
                    ],
                },
            ]
            + quiet("RagweldSearchStageErrors", "RagweldSearchFailures", at="25m"),
        },
        {
            # Laya down while System One runs on TypeSafe: nothing is using Laya, no alert.
            "interval": "1m",
            "input_series": up + [
                {"series": 'up{job="laya",instance="laya:8000"}', "values": "0x40"},
                {"series": 'tribrid_system_one_requests_total{provider="typesafe",outcome="ok"}', "values": "0+1x40"},
            ],
            "alert_rule_test": quiet("RagweldLayaDown", at="10m") + quiet("RagweldLayaDown"),
        },
        {
            # Laya up and serving provider=laya traffic: quiet.
            "interval": "1m",
            "input_series": up + [
                {"series": 'up{job="laya",instance="laya:8000"}', "values": "1x40"},
                {"series": 'tribrid_system_one_requests_total{provider="laya",outcome="ok"}', "values": "0+3x40"},
            ],
            "alert_rule_test": quiet("RagweldLayaDown", at="10m"),
        },
        {
            # Laya down while Ragweld sends it requests (they fail): the alert fires.
            "interval": "1m",
            "input_series": up + [
                {"series": 'up{job="laya",instance="laya:8000"}', "values": "0x40"},
                {"series": 'tribrid_system_one_requests_total{provider="laya",outcome="error"}', "values": "0+2x40"},
            ],
            "alert_rule_test": [
                {
                    "eval_time": "10m",
                    "alertname": "RagweldLayaDown",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "job": "laya", "instance": "laya:8000"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-gateway-serving",
                                "summary": "Laya (local System One) is down while Ragweld is using it",
                                "description": "system_one.provider=laya requests were sent in the last 30 minutes, but the Laya container has not answered a scrape for 5 minutes. System One decisions fail until it is back.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # 2 of 10 chats fail at the gateway while half are client disconnects: 20% errors,
            # the disconnects excluded from the numerator but not the denominator. Fires.
            "interval": "1m",
            "input_series": up + [
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="ok"}', "values": "0+3x40"},
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="gateway_error"}', "values": "0+2x40"},
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="client_disconnect"}', "values": "0+5x40"},
            ],
            "alert_rule_test": [
                {
                    "eval_time": "30m",
                    "alertname": "RagweldChatErrorRatioHigh",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-chat",
                                "summary": "More than 10% of chat requests are failing",
                                "description": "Over the last 10 minutes more than 10% of chat requests (at least 5) ended in a retrieval error, gateway error or timeout. Check the Chat dashboard (requests by outcome) and the API logs.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # 70% client disconnects and no error series at all: quiet. Idle latency
            # and feedback counters stay quiet too.
            "interval": "1m",
            "input_series": up + [
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="ok"}', "values": "0+3x40"},
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="client_disconnect"}', "values": "0+7x40"},
                {"series": 'tribrid_feedback_events_total{signal="thumbsdown",surface="chat"}', "values": "0x40"},
            ],
            "alert_rule_test": quiet("RagweldChatErrorRatioHigh", "RagweldChatFirstTextSlow", "RagweldThumbsDownShareHigh"),
        },
        {
            # Every chat fails, but one per 10 minutes is under the 5-request floor: quiet.
            "interval": "1m",
            "input_series": up + [
                {"series": 'tribrid_chat_requests_total{model="m1",outcome="timeout"}', "values": "0x9 1x10 2x10 3x10"},
            ],
            "alert_rule_test": quiet("RagweldChatErrorRatioHigh"),
        },
        {
            # m1's first text lands between 60 s and 90 s, m2's under 60 s: only m1 fires.
            "interval": "1m",
            "input_series": up
            + [
                {"series": f'tribrid_chat_time_to_first_text_seconds_bucket{{model="{model}",le="{le}"}}', "values": values}
                for model, slow in (("m1", True), ("m2", False))
                for le, values in (
                    ("30.0", "0x40"),
                    ("60.0", "0x40" if slow else "0+1x40"),
                    ("90.0", "0+1x40"),
                    ("+Inf", "0+1x40"),
                )
            ]
            + [
                {"series": f'tribrid_chat_time_to_first_text_seconds_count{{model="{model}"}}', "values": "0+1x40"}
                for model in ("m1", "m2")
            ],
            "alert_rule_test": [
                {
                    "eval_time": "30m",
                    "alertname": "RagweldChatFirstTextSlow",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "model": "m1"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-chat",
                                "summary": "Chat time to first text p95 above 60 s for m1",
                                "description": "The p95 time from sending a chat to its first answer text on m1 has been above 60 seconds over 15 minutes (at least 3 answers). Users wait a minute or more before any answer appears. Check the provider and the Chat dashboard.",
                            },
                        }
                    ],
                }
            ],
        },
        {
            # Chat: a thumbs-down every minute and no thumbs-up fires for chat. Search: 3
            # thumbs-down in the hour is under the 5-vote floor, so search stays quiet.
            "interval": "1m",
            "input_series": up + [
                {"series": 'tribrid_feedback_events_total{signal="thumbsdown",surface="chat"}', "values": "0+1x70"},
                {"series": 'tribrid_feedback_events_total{signal="thumbsup",surface="chat"}', "values": "0x70"},
                {"series": 'tribrid_feedback_events_total{signal="thumbsdown",surface="search"}', "values": "0x40 1x10 2x10 3x10"},
            ],
            "alert_rule_test": [
                {
                    "eval_time": "65m",
                    "alertname": "RagweldThumbsDownShareHigh",
                    "exp_alerts": [
                        {
                            "exp_labels": {"severity": "warning", "surface": "chat"},
                            "exp_annotations": {
                                "dashboard": "/d/ragweld-chat",
                                "summary": "Most chat thumbs votes in the last hour are thumbs-down",
                                "description": "More than half of the chat thumbs votes in the last hour (at least 5 votes) were thumbs-down. Review recent answers and their feedback.",
                            },
                        }
                    ],
                }
            ],
        },
    ]
    rules_path = tmp_path / "rules.yml"
    rules_path.write_text((ROOT / "infra" / "prometheus-rules.yml").read_text(encoding="utf-8"), encoding="utf-8")
    spec = {"rule_files": ["/fixtures/rules.yml"], "evaluation_interval": "1m", "tests": tests}
    (tmp_path / "tests.yml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [
            "docker", "run", "--rm", "--network", "none", "--memory", "128m", "--cpus", "0.5",
            "--entrypoint", "/bin/promtool",
            # File mounts: pytest's tmp dir is owner-only, and promtool runs as `nobody`.
            "--mount", f"type=bind,src={rules_path},dst=/fixtures/rules.yml,readonly",
            "--mount", f"type=bind,src={tmp_path / 'tests.yml'},dst=/fixtures/tests.yml,readonly",
            "prom/prometheus:v2.45.0", "test", "rules", "/fixtures/tests.yml",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


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
    # This is a source-default contract, independent of the runner's live Loki binding.
    env = dict(os.environ)
    env.pop("LOKI_BASE_URL", None)
    env["RAGWELD_LOAD_DOTENV"] = "0"
    result = subprocess.run(
        [sys.executable, "-c", "import json; from server.api.docker import _loki_candidate_urls; print(json.dumps(_loki_candidate_urls()))"],
        cwd=ROOT, env=env, check=True, capture_output=True, text=True,
    )
    candidates = json.loads(result.stdout)
    assert "http://127.0.0.1:53100" in candidates
    assert "http://127.0.0.1:3100" not in candidates


def test_generated_wire_types_include_split_public_operator_urls_without_extra_faro_field() -> None:
    generated_source = (ROOT / "web" / "src" / "types" / "generated.ts").read_text(encoding="utf-8")

    assert "langfuse_public_base_url?: string;" in generated_source
    assert 'langfuse_public_base_url?: string; // default: "http://127.0.0.1:53000"' in generated_source
    assert "ragweld_agent_mlflow_console_base_url?: string;" in generated_source
    assert 'ragweld_agent_mlflow_console_base_url?: string; // default: "http://127.0.0.1:55500"' in generated_source
    assert "tracking_experiment_id?: string | null;" in generated_source
    assert "faro_public_base_url" not in generated_source


def test_proxmox_production_contract_env_covers_every_required_overlay_interpolation() -> None:
    assert _required_compose_env_keys(ROOT / PROXMOX_PRODUCTION_COMPOSE) == set(PROXMOX_PRODUCTION_CONTRACT_ENV)


def test_docker_service_allowlists_match_frontend_and_managed_compose_services() -> None:
    from server.api.docker import _DOCKER_SERVICES

    frontend_source = (ROOT / "web" / "src" / "api" / "docker.ts").read_text(encoding="utf-8")
    match = re.search(r"RAGWELD_DOCKER_SERVICES\s*=\s*\[(.*?)\]\s*as const", frontend_source, re.DOTALL)
    assert match is not None
    frontend_services = set(re.findall(r"'([^']+)'", match.group(1)))

    docker_subtab_source = (ROOT / "web" / "src" / "components" / "Infrastructure" / "DockerSubtab.tsx").read_text(
        encoding="utf-8"
    )
    services_subtab_source = (
        ROOT / "web" / "src" / "components" / "Infrastructure" / "ServicesSubtab.tsx"
    ).read_text(encoding="utf-8")

    config = _compose_config(
        "docker-compose.yml",
        "infra/docker-compose.observability.yml",
        "deploy/proxmox/docker-compose.yml",
    )
    managed_services_by_name = {
        name: service
        for name, service in config["services"].items()
        if service.get("labels", {}).get("io.ragweld.managed") == "true"
    }
    expected_services = {
        *managed_services_by_name,
        "caddy",
        "authelia",
        "authelia-redis",
        "cloudflared",
    }
    managed_services = set(managed_services_by_name)
    expected_labels = {
        "caddy": "Caddy Secure Ingress",
        "authelia": "Authelia Authentication",
        # Authelia's session store: added for persistent sessions, and a managed
        # compose service, so it has to appear in every allowlist like the rest.
        "authelia-redis": "Authelia Session Store",
        "cloudflared": "Cloudflare Tunnel",
    }

    for service_name, label in expected_labels.items():
        assert managed_services_by_name[service_name]["labels"]["io.ragweld.managed"] == "true"
        # A hyphenated service id has to be a quoted object key in TypeScript.
        entries = (f"{service_name}: '{label}'", f"'{service_name}': '{label}'")
        assert any(entry in docker_subtab_source for entry in entries), service_name
        assert any(entry in services_subtab_source for entry in entries), service_name

    secure_ingress_group = re.search(
        r"title:\s*'Secure Ingress'.*?services:\s*\[(.*?)\]",
        services_subtab_source,
        re.DOTALL,
    )
    assert secure_ingress_group is not None
    assert set(re.findall(r"'([^']+)'", secure_ingress_group.group(1))) == {
        "caddy",
        "authelia",
        "authelia-redis",
        "cloudflared",
    }

    assert managed_services == {
        name
        for name in expected_services
    }

    assert set(_DOCKER_SERVICES) == frontend_services == managed_services == expected_services


def test_secure_ingress_ui_contract_marks_missing_services_deployment_only() -> None:
    docker_subtab_source = (ROOT / "web" / "src" / "components" / "Infrastructure" / "DockerSubtab.tsx").read_text(
        encoding="utf-8"
    )
    services_subtab_source = (
        ROOT / "web" / "src" / "components" / "Infrastructure" / "ServicesSubtab.tsx"
    ).read_text(encoding="utf-8")

    deployment_only_set = (
        "const DEPLOYMENT_ONLY_SERVICES: ReadonlySet<RagweldDockerService> = "
        "new Set(['caddy', 'authelia', 'authelia-redis', 'cloudflared']);"
    )
    deployment_only_detail = (
        "Created by the Proxmox deployment overlay; not expected in the default local topology."
    )
    services_subtab_detail = (
        "Created by the Proxmox deployment overlay; not expected in default local development."
    )

    assert deployment_only_set in docker_subtab_source
    assert deployment_only_set in services_subtab_source

    assert "const deploymentOnly = DEPLOYMENT_ONLY_SERVICES.has(service);" in docker_subtab_source
    assert "const deploymentOnly = DEPLOYMENT_ONLY_SERVICES.has(service);" in services_subtab_source

    # An absent optional container must read the same on both pages: the drive
    # found it "Missing" on Docker and "Not deployed (expected)" on Services,
    # and "Missing" reads as a fault while "expected" reads as fine.
    optional_ladder = (
        r"deploymentOnly\s*\?\s*'— Deployment-only'\s*:\s*optional\s*\?\s*"
        r"'— Optional, not deployed'\s*:\s*'— Missing'"
    )
    assert "const optional = OPTIONAL_SERVICES.has(service);" in docker_subtab_source
    assert "const optional = OPTIONAL_SERVICES.has(service);" in services_subtab_source
    assert re.search(optional_ladder, docker_subtab_source)
    assert re.search(optional_ladder, services_subtab_source)
    assert "'— Not deployed (optional)'" not in services_subtab_source

    assert docker_subtab_source.count(deployment_only_detail) == 1
    assert services_subtab_detail in services_subtab_source

    assert "!container && deploymentOnly && (" not in docker_subtab_source
    # An optional container is not created by a start.sh flag the operator needs.
    assert "!container && !deploymentOnly && !optional && (" in docker_subtab_source
    assert "container ? '○ Stopped' : '— Missing'" not in docker_subtab_source
    assert (
        "optional\n                        ? 'Optional container; not part of the default development topology.'\n                        : 'No managed container exists for this service.'"
        not in services_subtab_source
    )


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
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        assert api["environment"][key] == ""

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
        "num_retries": 0,
        "max_retries": 0,
    }
    routed = [row for row in gateway["model_list"] if row["litellm_params"]["model"].startswith("openrouter/")]
    assert len(routed) >= 300
    assert all(row["litellm_params"]["model"].startswith("openrouter/") for row in routed)
    assert all(row["litellm_params"]["api_key"] == "os.environ/OPENROUTER_API_KEY" for row in routed)
    assert all("api_base" not in row["litellm_params"] for row in routed)
    embedded = [row for row in gateway["model_list"] if row.get("model_info", {}).get("mode") == "embedding"]
    assert {row["model_name"] for row in embedded} == {
        "openai.text-embedding-3-small", "openai.text-embedding-3-large",
    }
    assert all(row["litellm_params"]["api_key"] == "os.environ/OPENAI_API_KEY" for row in embedded)
    assert all("api_base" not in row["litellm_params"] for row in embedded)
    assert len(gateway["model_list"]) == len(routed) + len(embedded) + 1
    assert all(
        row["litellm_params"]["num_retries"] == row["litellm_params"]["max_retries"] == 0
        for row in gateway["model_list"]
    )
    assert "ragweld-openrouter-smoke" not in {row["model_name"] for row in gateway["model_list"]}

    assert "unset OPENAI_API_KEY OPENROUTER_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY" in launcher
    assert "colima start --profile ragweld --vm-type vz --cpu 6 --memory 16" in launcher
    assert gateway["litellm_settings"]["num_retries"] == 0
    assert gateway["litellm_settings"].get("fallbacks", []) == []
    assert gateway["litellm_settings"].get("context_window_fallbacks", []) == []
    assert gateway["litellm_settings"]["callbacks"] == ["prometheus", "langfuse_otel"]
    assert gateway["litellm_settings"]["turn_off_message_logging"] is True
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
