from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from server.models.tribrid_config_model import TriBridConfig

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "proxmox" / "render_config.py"
SOURCE_CONFIG = ROOT / "tribrid_config.json"
PROXMOX_DIR = ROOT / "deploy" / "proxmox"
PROXMOX_COMPOSE = PROXMOX_DIR / "docker-compose.yml"
PROXMOX_CADDYFILE = PROXMOX_DIR / "Caddyfile"
PROXMOX_AUTHELIA_CONFIG = PROXMOX_DIR / "authelia" / "configuration.yml"
PROXMOX_START_RUNTIME = PROXMOX_DIR / "start-runtime.sh"
PROXMOX_STOP_RUNTIME = PROXMOX_DIR / "stop-runtime.sh"
PROXMOX_BOOTSTRAP_SECRETS = PROXMOX_DIR / "bootstrap-secrets.sh"
PROXMOX_SERVICE_UNIT = PROXMOX_DIR / "ragweld.service"
PROXMOX_SECRET_ROOT_ENV = "RAGWELD_ETC_ROOT"
PROXMOX_CONTRACT_ENV = {
    "GRAFANA_ADMIN_PASSWORD": "contract-only",
    "LANGFUSE_OIDC_CLIENT_SECRET": "contract-only",
}
PROXMOX_RUNTIME_SYMLINKS = {
    ".env": "runtime.env",
    "infra/litellm.env": "litellm.env",
    "infra/langfuse.env": "langfuse.env",
}
PROXMOX_REQUIRED_SECRET_FILES = (
    "tribrid_config.json",
    "runtime.env",
    "litellm.env",
    "langfuse.env",
    "langfuse-oidc-client-secret",
    "authelia/session-secret",
    "authelia/storage-encryption-key",
    "authelia/oidc-hmac-secret",
    "authelia/langfuse-client-secret-digest",
    "authelia/users_database.yml",
    "authelia/oidc-rsa.pem",
)
PROXMOX_BOOTSTRAP_OUTPUT_FILES = tuple(
    path for path in PROXMOX_REQUIRED_SECRET_FILES if path != "tribrid_config.json"
)
PROXMOX_REQUIRED_TUNNEL_FILES = (
    "cloudflared/config.yml",
    "cloudflared/credentials.json",
)
PROXMOX_PRODUCTION_SERVICES = [
    "postgres",
    "neo4j",
    "qdrant",
    "mlflow",
    "litellm",
    "postgres-exporter",
    "prometheus",
    "grafana",
    "loki",
    "promtail",
    "tempo",
    "alloy",
    "mimir",
    "pyroscope",
    "alertmanager",
    "langfuse",
    "langfuse-worker",
    "langfuse-postgres",
    "langfuse-clickhouse",
    "langfuse-redis",
    "langfuse-minio",
    "flyte",
    "authelia",
    "caddy",
]
PRODUCTION_DEFAULTS = {
    ("generation", "gen_model"): "openai.gpt-5.4-mini",
    ("generation", "enrich_model"): "openai.gpt-5.4-mini",
    ("chat", "litellm", "default_model"): "openai.gpt-5.4-mini",
    ("chat", "multimodal", "vision_model_override"): "openai.gpt-5.4-mini",
    ("chat", "vllm", "enabled"): False,
    ("embedding", "embedding_backend"): "provider",
    ("embedding", "embedding_type"): "huggingface",
    ("embedding", "embedding_model"): "BAAI/bge-small-en-v1.5",
    ("embedding", "embedding_dim"): 384,
    ("ui", "chat_default_model"): "openai.gpt-5.4-mini",
    ("ui", "runtime_mode"): "production",
    ("ui", "open_browser"): False,
    ("ui", "grafana_base_url"): "https://grafana.ragweld.com",
    ("training", "ragweld_agent_flyte_admin_base_url"): "http://127.0.0.1:30080",
    ("training", "ragweld_agent_flyte_console_base_url"): "https://flyte.ragweld.com",
    ("training", "ragweld_agent_mlflow_tracking_url"): "http://127.0.0.1:55500",
    ("evaluation", "ragas_judge_model"): "openai.gpt-5.4-mini",
    ("evaluation", "promptfoo_grader_model"): "openai.gpt-5.4-mini",
}


def _run_renderer(*, source: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source",
            str(source),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _read_config(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _compose_config(*files: str) -> dict[str, Any]:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is unavailable")
    version = subprocess.run(
        ["docker", "compose", "version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if version.returncode != 0:
        pytest.skip("docker compose plugin is unavailable")

    merged_env = dict(os.environ)
    merged_env.update(PROXMOX_CONTRACT_ENV)
    args = ["docker", "compose", "--project-name", "ragweld"]
    for file_name in files:
        args.extend(["-f", file_name])
    args.extend(["config", "--format", "json"])
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _caddy_named_blocks(source: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    header: str | None = None
    current: list[str] = []
    depth = 0

    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            if header is not None:
                current.append(line)
            continue

        if header is None:
            if stripped.endswith("{"):
                header = stripped[:-1].strip()
                current = [line]
                depth = 1
            continue

        current.append(line)
        if stripped.endswith("{"):
            depth += 1
        elif stripped == "}":
            depth -= 1
            if depth == 0:
                blocks[header] = "\n".join(current)
                header = None
                current = []

    assert header is None, f"unterminated Caddy block: {header}"
    return blocks


def _assert_caddy_contract(source: str) -> None:
    blocks = _caddy_named_blocks(source)
    assert "" in blocks
    assert "(require_owner)" in blocks

    expected_sites = {
        "http://auth.ragweld.com:58000",
        "http://me.ragweld.com:58000",
        "http://grafana.ragweld.com:58000",
        "http://langfuse.ragweld.com:58000",
        "http://mlflow.ragweld.com:58000",
        "http://flyte.ragweld.com:58000",
    }
    site_headers = {header for header in blocks if header.startswith("http://")}
    assert site_headers == expected_sites

    global_block = blocks[""]
    assert "admin off" in global_block
    assert "auto_https off" in global_block
    assert "default_bind 127.0.0.1" in global_block

    require_owner = blocks["(require_owner)"]
    assert "uri /api/authz/forward-auth" in require_owner
    assert "copy_headers Remote-User Remote-Groups Remote-Email Remote-Name" in require_owner

    reverse_proxy_targets = {
        match.group(1)
        for match in re.finditer(r"^\s*reverse_proxy\s+([^\s{]+)", source, flags=re.MULTILINE)
    }
    assert reverse_proxy_targets == {
        "127.0.0.1:59091",
        "127.0.0.1:58012",
        "127.0.0.1:3301",
        "127.0.0.1:53000",
        "127.0.0.1:55500",
        "127.0.0.1:30080",
    }

    for header in expected_sites - {"http://auth.ragweld.com:58000"}:
        assert "import require_owner" in blocks[header], header

    auth_block = blocks["http://auth.ragweld.com:58000"]
    assert "import require_owner" not in auth_block
    assert "reverse_proxy 127.0.0.1:59091" in auth_block

    me_block = blocks["http://me.ragweld.com:58000"]
    assert "handle /api/* {" in me_block
    assert "reverse_proxy 127.0.0.1:58012" in me_block
    assert "handle_path /web/* {" in me_block
    assert "root * /srv/web" in me_block
    assert "try_files {path} /index.html" in me_block
    assert "file_server" in me_block
    assert "redir /web /web/" in me_block
    assert "redir / /web/" in me_block


def _compose_service_blocks(source: str) -> dict[str, str]:
    match = re.search(r"^services:\n(?P<body>.*?)(?:^\S|\Z)", source, flags=re.MULTILINE | re.DOTALL)
    assert match is not None
    body = match.group("body")
    blocks: dict[str, list[str]] = {}
    current_name: str | None = None
    current_lines: list[str] = []
    for line in body.splitlines():
        if re.match(r"^  [^:\s][^:]*:\s*$", line):
            if current_name is not None:
                blocks[current_name] = "\n".join(current_lines)
            current_name = line.strip()[:-1]
            current_lines = [line]
            continue
        if current_name is not None:
            current_lines.append(line)
    if current_name is not None:
        blocks[current_name] = "\n".join(current_lines)
    return blocks


def _nested_get(payload: dict[str, object], path: tuple[str, ...]) -> object:
    current: object = payload
    for key in path:
        assert isinstance(current, dict)
        current = current[key]
    return current


def _nested_set(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    current = payload
    for key in path[:-1]:
        current = current[key]
        assert isinstance(current, dict)
    current[path[-1]] = value


def _run_shell_script(
    script: Path,
    *args: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=cwd,
        env=merged_env,
        text=True,
        capture_output=True,
        check=False,
    )


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _write_private_file(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o600)


def _parse_env_file(path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        payload[key] = value
    return payload


def _ab64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").rstrip("=").replace("+", ".")


def _ab64_decode(data: str) -> bytes:
    padded = data.replace(".", "+")
    padded += "=" * (-len(padded) % 4)
    return base64.b64decode(padded)


def _verify_authelia_pbkdf2_sha512(secret: str, digest: str) -> bool:
    match = re.fullmatch(r"\$pbkdf2-sha512\$(\d+)\$([^$]+)\$([^$]+)", digest)
    assert match is not None, digest
    rounds = int(match.group(1))
    salt = _ab64_decode(match.group(2))
    expected = _ab64_encode(hashlib.pbkdf2_hmac("sha512", secret.encode("utf-8"), salt, rounds))
    return hmac.compare_digest(expected, match.group(3))


def _materialize_proxmox_runtime_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    for relative_path in (
        "deploy/proxmox/start-runtime.sh",
        "deploy/proxmox/stop-runtime.sh",
        "deploy/proxmox/bootstrap-secrets.sh",
    ):
        source = ROOT / relative_path
        target = repo / relative_path
        _write_executable(target, source.read_text(encoding="utf-8"))
    for relative_path in (
        "docker-compose.yml",
        "infra/docker-compose.observability.yml",
        "deploy/proxmox/docker-compose.yml",
    ):
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("services: {}\n", encoding="utf-8")
    _write_executable(
        repo / "start.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'start %s\\n' "$*" >> "$FAKE_TOOL_LOG"
printf 'config %s\\n' "${RAGWELD_CONFIG_PATH:-}" >> "$FAKE_TOOL_LOG"
exit 0
""",
    )
    _write_executable(
        repo / "stop.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'stop %s\\n' "$*" >> "$FAKE_TOOL_LOG"
exit 0
""",
    )
    _write_executable(
        repo / ".venv/bin/uvicorn",
        """#!/usr/bin/env bash
exit 0
""",
    )
    (repo / "web" / "dist").mkdir(parents=True, exist_ok=True)
    (repo / "web" / "dist" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    (repo / "infra").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "tool.log"
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\\n' "$*" >> "$FAKE_TOOL_LOG"
exit 0
""",
    )
    return repo, log_path


def _build_secret_root(tmp_path: Path, *, include_tunnel: bool) -> Path:
    secret_root = tmp_path / "ragweld-etc"
    secret_root.mkdir(parents=True, exist_ok=True)
    secret_root.chmod(0o700)
    (secret_root / "authelia").mkdir(parents=True, exist_ok=True)
    (secret_root / "authelia").chmod(0o700)
    (secret_root / "authelia" / "state").mkdir(parents=True, exist_ok=True)
    (secret_root / "authelia" / "state").chmod(0o700)

    _write_private_file(secret_root / "tribrid_config.json", "{}\n")
    _write_private_file(
        secret_root / "runtime.env",
        "\n".join(
            [
                "LITELLM_BASE_URL=http://127.0.0.1:54000/v1",
                "LITELLM_API_KEY=sk-ragweld-runtime-test",
                "POSTGRES_HOST=127.0.0.1",
                "POSTGRES_PORT=5432",
                "POSTGRES_DB=tribrid_rag",
                "POSTGRES_USER=postgres",
                "POSTGRES_PASSWORD=runtime-postgres-password",
                "NEO4J_URI=bolt://127.0.0.1:7687",
                "NEO4J_USER=neo4j",
                "NEO4J_PASSWORD=runtime-neo4j-password",
                "GRAFANA_ADMIN_PASSWORD=runtime-grafana-password",
                "LANGFUSE_PUBLIC_KEY=pk-lf-runtime",
                "LANGFUSE_SECRET_KEY=sk-lf-runtime",
                "SERVER_HOST=127.0.0.1",
                "SERVER_PORT=58012",
                "METRICS_ENABLED=true",
                "TRACING_ENABLED=true",
                "",
            ]
        ),
    )
    _write_private_file(secret_root / "litellm.env", "# provider keys installed later\n")
    _write_private_file(
        secret_root / "langfuse.env",
        "\n".join(
            [
                "DATABASE_URL=postgresql://langfuse:langfuse@langfuse-postgres:5432/langfuse",
                "SALT=langfuse-test-salt",
                "ENCRYPTION_KEY=langfuse-test-encryption-key",
                "NEXTAUTH_SECRET=langfuse-test-nextauth-secret",
                "TELEMETRY_ENABLED=false",
                "",
            ]
        ),
    )
    _write_private_file(secret_root / "langfuse-oidc-client-secret", "runtime-oidc-secret\n")
    _write_private_file(secret_root / "authelia/session-secret", "authelia-session-secret\n")
    _write_private_file(secret_root / "authelia/storage-encryption-key", "authelia-storage-secret\n")
    _write_private_file(secret_root / "authelia/oidc-hmac-secret", "authelia-oidc-hmac\n")
    _write_private_file(
        secret_root / "authelia/langfuse-client-secret-digest",
        "$pbkdf2-sha512$310000$c8p78n7pUMln0jzvd4aK4Q$JNRBzwAo0ek5qKn50cFzzvE9RXV88h1wJn5KGiHrD0YKtZaR/nCb2CJPOsKaPK0hjf.9yHxzQGZziziccp6Yng\n",
    )
    _write_private_file(
        secret_root / "authelia/users_database.yml",
        "users:\n  owner:\n    password: '$argon2id$v=19$m=65536,t=3,p=4$Hjc8e7WYcBFcJmEDUOsS9A$ozM7RyZR1EyDR8cuyVpDDfmLrGPGFgo5E2NNqRumui4'\n",
    )
    _write_private_file(secret_root / "authelia/oidc-rsa.pem", "-----BEGIN PRIVATE KEY-----\nlocal-test\n-----END PRIVATE KEY-----\n")

    if include_tunnel:
        (secret_root / "cloudflared").mkdir(parents=True, exist_ok=True)
        (secret_root / "cloudflared").chmod(0o700)
        _write_private_file(secret_root / "cloudflared/config.yml", "tunnel: local-test\n")
        _write_private_file(secret_root / "cloudflared/credentials.json", '{"AccountTag":"local"}\n')

    return secret_root


def test_proxmox_renderer_writes_validated_production_defaults_atomically(tmp_path: Path) -> None:
    source_payload = _read_config(SOURCE_CONFIG)
    source_config = TriBridConfig.model_validate(source_payload)
    output = tmp_path / "tribrid_config.production.json"

    result = _run_renderer(source=SOURCE_CONFIG, output=output)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = _read_config(output)
    validated = TriBridConfig.model_validate(payload)
    expected_payload = copy.deepcopy(source_config.model_dump(mode="json"))
    for path, expected in PRODUCTION_DEFAULTS.items():
        _nested_set(expected_payload, path, expected)
    expected = TriBridConfig.model_validate(expected_payload)
    assert output.read_text(encoding="utf-8") == json.dumps(
        expected.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    ) + "\n"
    assert validated.model_dump(mode="json") == expected.model_dump(mode="json")
    assert output.stat().st_mode & 0o777 == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name]


def test_proxmox_renderer_preserves_source_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(SOURCE_CONFIG.read_bytes())
    output = tmp_path / "rendered.json"
    before = source.read_bytes()

    result = _run_renderer(source=source, output=output)

    assert result.returncode == 0, result.stdout + result.stderr
    assert source.read_bytes() == before


def test_proxmox_renderer_rejects_same_source_and_output_file(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(SOURCE_CONFIG.read_bytes())
    before = source.read_bytes()

    result = _run_renderer(source=source, output=source)

    assert result.returncode != 0
    assert "must identify different files" in result.stderr
    assert source.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_proxmox_renderer_rejects_symlink_output_to_source(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(SOURCE_CONFIG.read_bytes())
    output = tmp_path / "rendered.json"
    output.symlink_to(source)
    before = source.read_bytes()

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert "must identify different files" in result.stderr
    assert source.read_bytes() == before
    assert output.is_symlink()
    assert output.resolve() == source.resolve()
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name, source.name]


def test_proxmox_renderer_rejects_invalid_source_without_creating_output(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    payload = _read_config(SOURCE_CONFIG)
    payload["generation"]["gen_model"] = "OpenAI.GPT-5.4-mini"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "rendered.json"

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert not output.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == [source.name]


def test_proxmox_renderer_keeps_existing_output_on_validation_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    payload = _read_config(SOURCE_CONFIG)
    payload["chat"]["litellm"]["default_model"] = "not/a-valid-alias"
    source.write_text(json.dumps(payload), encoding="utf-8")
    output = tmp_path / "rendered.json"
    output.write_text('{"keep":"me"}\n', encoding="utf-8")
    before = output.read_text(encoding="utf-8")

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == before
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name, source.name]


def test_proxmox_renderer_removes_temp_file_when_replace_fails(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(SOURCE_CONFIG.read_bytes())
    output = tmp_path / "rendered"
    output.mkdir()
    marker = output / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    result = _run_renderer(source=source, output=output)

    assert result.returncode != 0
    assert output.is_dir()
    assert marker.read_text(encoding="utf-8") == "keep"
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == [output.name, source.name]


def test_proxmox_compose_is_pinned_loopback_only_and_secret_file_backed() -> None:
    config = _compose_config(
        "docker-compose.yml",
        "infra/docker-compose.observability.yml",
        "deploy/proxmox/docker-compose.yml",
    )
    services = config["services"]

    assert services["authelia"]["image"] == "authelia/authelia:4.39.20"
    assert services["caddy"]["image"] == "caddy:2.11.4-alpine"
    assert services["cloudflared"]["image"] == "cloudflare/cloudflared:2026.7.2"
    assert services["caddy"]["network_mode"] == "host"
    assert services["cloudflared"]["network_mode"] == "host"
    assert services["authelia"]["ports"] == [
        {
            "mode": "ingress",
            "target": 9091,
            "published": "59091",
            "protocol": "tcp",
            "host_ip": "127.0.0.1",
        }
    ]
    assert services["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"] == "contract-only"
    assert services["langfuse"]["environment"]["NEXTAUTH_URL"] == "https://langfuse.ragweld.com"
    assert services["langfuse"]["environment"]["AUTH_CUSTOM_CLIENT_SECRET"] == "contract-only"
    assert all(
        service["labels"]["io.ragweld.managed"] == "true"
        for service in (services["authelia"], services["caddy"], services["cloudflared"])
    )

    rendered = json.dumps(config)
    assert "/etc/ragweld/cloudflared" in rendered
    assert "/etc/ragweld/authelia/users_database.yml" in rendered


def test_proxmox_compose_uses_only_allowlisted_secret_mounts_and_origins() -> None:
    config = _compose_config(
        "docker-compose.yml",
        "infra/docker-compose.observability.yml",
        "deploy/proxmox/docker-compose.yml",
    )
    services = config["services"]
    authelia = services["authelia"]
    langfuse = services["langfuse"]

    authelia_secret_files = {
        name: definition["file"] for name, definition in config["secrets"].items() if name.startswith("authelia_")
    }
    assert authelia_secret_files == {
        "authelia_session": "/etc/ragweld/authelia/session-secret",
        "authelia_storage": "/etc/ragweld/authelia/storage-encryption-key",
        "authelia_oidc_hmac": "/etc/ragweld/authelia/oidc-hmac-secret",
    }
    assert {secret["source"] for secret in authelia["secrets"]} == set(authelia_secret_files)
    assert authelia["environment"] == {
        "AUTHELIA_IDENTITY_PROVIDERS_OIDC_HMAC_SECRET_FILE": "/run/secrets/authelia_oidc_hmac",
        "AUTHELIA_SESSION_SECRET_FILE": "/run/secrets/authelia_session",
        "AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE": "/run/secrets/authelia_storage",
        "X_AUTHELIA_CONFIG_FILTERS": "template",
    }
    assert {
        volume["target"]: volume["source"]
        for volume in authelia["volumes"]
        if volume["target"]
        in {
            "/config/configuration.yml",
            "/config/users_database.yml",
            "/config/oidc-rsa.pem",
            "/etc/ragweld/authelia/langfuse-client-secret-digest",
            "/state",
        }
    } == {
        "/config/configuration.yml": str(PROXMOX_AUTHELIA_CONFIG),
        "/config/users_database.yml": "/etc/ragweld/authelia/users_database.yml",
        "/config/oidc-rsa.pem": "/etc/ragweld/authelia/oidc-rsa.pem",
        "/etc/ragweld/authelia/langfuse-client-secret-digest": "/etc/ragweld/authelia/langfuse-client-secret-digest",
        "/state": "/etc/ragweld/authelia/state",
    }

    mounted_targets = {volume["target"] for volume in authelia["volumes"]}
    referenced_secret_paths = {
        match.group(1)
        for match in re.finditer(
            r'{{ secret "([^"]+)"',
            PROXMOX_AUTHELIA_CONFIG.read_text(encoding="utf-8"),
        )
    }
    assert referenced_secret_paths <= mounted_targets

    langfuse_env = langfuse["environment"]
    assert langfuse_env["AUTH_CUSTOM_CLIENT_ID"] == "langfuse"
    assert langfuse_env["AUTH_CUSTOM_CLIENT_SECRET"] == "contract-only"
    assert langfuse_env["AUTH_CUSTOM_FETCH_USERINFO"] == "true"
    assert langfuse_env["AUTH_CUSTOM_ISSUER"] == "https://auth.ragweld.com"
    assert langfuse_env["AUTH_CUSTOM_NAME"] == "Ragweld"
    assert langfuse_env["AUTH_CUSTOM_SCOPE"] == "openid email profile groups"
    assert langfuse_env["AUTH_DISABLE_SIGNUP"] == "true"
    assert langfuse_env["AUTH_DISABLE_USERNAME_PASSWORD"] == "true"
    assert langfuse_env["NEXTAUTH_URL"] == "https://langfuse.ragweld.com"
    for inherited_key in (
        "DATABASE_URL",
        "NEXTAUTH_SECRET",
        "LANGFUSE_INIT_USER_EMAIL",
        "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
        "LANGFUSE_INIT_PROJECT_SECRET_KEY",
    ):
        assert inherited_key not in langfuse_env

    worker_env = services["langfuse-worker"].get("environment") or {}
    assert worker_env == {}
    overlay_source = PROXMOX_COMPOSE.read_text(encoding="utf-8")
    service_blocks = _compose_service_blocks(overlay_source)
    for service_name in ("langfuse", "langfuse-worker"):
        block = service_blocks[service_name]
        assert "env_file: !override" in block
        assert "path: /etc/ragweld/langfuse.env" in block
        assert "required: false" in block
        assert "./infra/langfuse.env.example" not in block
        assert "./infra/langfuse.env" not in block


def test_proxmox_caddyfile_limits_public_routes_to_the_allowlist() -> None:
    source = PROXMOX_CADDYFILE.read_text(encoding="utf-8")
    _assert_caddy_contract(source)


def test_caddy_contract_parser_detects_appended_unprotected_nested_route() -> None:
    malicious = PROXMOX_CADDYFILE.read_text(encoding="utf-8").replace(
        "    redir / /web/\n}",
        "    redir / /web/\n    handle /metrics/* {\n        reverse_proxy 127.0.0.1:59090\n    }\n}",
    )

    with pytest.raises(AssertionError):
        _assert_caddy_contract(malicious)


def test_caddy_contract_parser_detects_forbidden_hostname_and_proxy_target() -> None:
    malicious = PROXMOX_CADDYFILE.read_text(encoding="utf-8") + """

http://prometheus.ragweld.com:58000 {
    import require_owner
    reverse_proxy 127.0.0.1:59090
}
"""

    with pytest.raises(AssertionError):
        _assert_caddy_contract(malicious)


def test_proxmox_authelia_configuration_is_owner_only_and_deny_by_default() -> None:
    payload = yaml.safe_load(PROXMOX_AUTHELIA_CONFIG.read_text(encoding="utf-8"))

    assert payload["access_control"]["default_policy"] == "deny"
    assert payload["access_control"]["rules"] == [
        {
            "domain": [
                "me.ragweld.com",
                "grafana.ragweld.com",
                "langfuse.ragweld.com",
                "mlflow.ragweld.com",
                "flyte.ragweld.com",
            ],
            "policy": "one_factor",
            "subject": ["group:owners"],
        }
    ]
    assert payload["session"]["cookies"] == [
        {
            "domain": "ragweld.com",
            "authelia_url": "https://auth.ragweld.com",
            "default_redirection_url": "https://me.ragweld.com/web/",
        }
    ]
    assert payload["authentication_backend"]["password_reset"]["disable"] is True
    assert payload["authentication_backend"]["password_change"]["disable"] is True
    assert payload["authentication_backend"]["file"]["path"] == "/config/users_database.yml"
    assert payload["storage"]["local"]["path"] == "/state/db.sqlite3"
    assert payload["server"]["endpoints"]["authz"]["forward-auth"]["implementation"] == "ForwardAuth"

    oidc = payload["identity_providers"]["oidc"]
    assert oidc["clients"] == [
        {
            "client_id": "langfuse",
            "client_name": "Langfuse",
            "client_secret": "{{ secret \"/etc/ragweld/authelia/langfuse-client-secret-digest\" }}",
            "public": False,
            "authorization_policy": "one_factor",
            "redirect_uris": [
                "https://langfuse.ragweld.com/api/auth/callback/custom",
            ],
            "scopes": ["openid", "profile", "email", "groups"],
            "response_types": ["code"],
            "grant_types": ["authorization_code"],
            "token_endpoint_auth_method": "client_secret_basic",
            "id_token_signed_response_alg": "RS256",
        }
    ]
    assert oidc["jwks"] == [
        {
            "key_id": "langfuse-rs256",
            "algorithm": "RS256",
            "use": "sig",
            "key": "{{ secret \"/config/oidc-rsa.pem\" | mindent 12 \"|\" | msquote }}",
        }
    ]


def test_proxmox_lifecycle_artifacts_exist_and_use_strict_shell_contract() -> None:
    for path in (
        PROXMOX_START_RUNTIME,
        PROXMOX_STOP_RUNTIME,
        PROXMOX_BOOTSTRAP_SECRETS,
    ):
        assert path.is_file(), f"missing {path.relative_to(ROOT)}"
        source = path.read_text(encoding="utf-8")
        assert source.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
        assert "rm -rf" not in source

    assert PROXMOX_SERVICE_UNIT.is_file(), f"missing {PROXMOX_SERVICE_UNIT.relative_to(ROOT)}"
    stop_source = PROXMOX_STOP_RUNTIME.read_text(encoding="utf-8")
    assert " docker compose " in stop_source
    assert " down" not in stop_source
    assert "rm " not in stop_source
    assert "volume rm" not in stop_source


def test_proxmox_lifecycle_unit_owns_exact_runtime_paths_and_tunnel_default() -> None:
    source = PROXMOX_SERVICE_UNIT.read_text(encoding="utf-8")

    assert "Description=Ragweld personal MLOps platform" in source
    assert "Wants=network-online.target" in source
    assert "After=network-online.target docker.service" in source
    assert "Requires=docker.service" in source
    assert "User=ragweld" in source
    assert "Group=ragweld" in source
    assert "SupplementaryGroups=docker" in source
    assert "WorkingDirectory=/opt/ragweld" in source
    assert "Environment=RAGWELD_SKIP_TUNNEL=0" in source
    assert "ExecStart=/opt/ragweld/deploy/proxmox/start-runtime.sh" in source
    assert "ExecStop=/opt/ragweld/deploy/proxmox/stop-runtime.sh" in source
    assert "Restart=on-failure" in source
    assert "RestartSec=10" in source
    assert "TimeoutStartSec=900" in source
    assert "TimeoutStopSec=180" in source
    assert "KillMode=mixed" in source
    assert "WantedBy=multi-user.target" in source
    assert PROXMOX_SECRET_ROOT_ENV not in source


@pytest.mark.parametrize(
    ("skip_tunnel", "include_tunnel", "expected_services"),
    [
        ("1", False, PROXMOX_PRODUCTION_SERVICES),
        ("0", True, [*PROXMOX_PRODUCTION_SERVICES, "cloudflared"]),
    ],
)
def test_proxmox_lifecycle_start_runtime_runs_exact_compose_allowlist_and_host_flags(
    tmp_path: Path,
    skip_tunnel: str,
    include_tunnel: bool,
    expected_services: list[str],
) -> None:
    assert PROXMOX_START_RUNTIME.is_file()
    repo, log_path = _materialize_proxmox_runtime_repo(tmp_path)
    secret_root = _build_secret_root(tmp_path, include_tunnel=include_tunnel)

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "start-runtime.sh",
        cwd=repo,
        env={
            PROXMOX_SECRET_ROOT_ENV: str(secret_root),
            "RAGWELD_SKIP_TUNNEL": skip_tunnel,
            "FAKE_TOOL_LOG": str(log_path),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    lines = log_path.read_text(encoding="utf-8").splitlines()
    docker_lines = [line for line in lines if line.startswith("docker ")]
    assert docker_lines
    compose_up = next(line for line in docker_lines if " up " in line)
    tokens = shlex.split(compose_up)
    assert tokens[:14] == [
        "docker",
        "compose",
        "--project-name",
        "ragweld",
        "-f",
        "docker-compose.yml",
        "-f",
        "infra/docker-compose.observability.yml",
        "-f",
        "deploy/proxmox/docker-compose.yml",
        "up",
        "-d",
        "--wait",
        expected_services[0],
    ]
    assert tokens[13:] == expected_services
    assert "api" not in tokens[13:]
    assert ("cloudflared" in tokens[13:]) is include_tunnel

    assert f"start --no-docker --no-local-model --no-frontend" in lines
    assert f"config {secret_root / 'tribrid_config.json'}" in lines
    for relative_path, secret_name in PROXMOX_RUNTIME_SYMLINKS.items():
        repo_path = repo / relative_path
        assert repo_path.is_symlink(), relative_path
        assert repo_path.resolve() == secret_root / secret_name


def test_proxmox_lifecycle_start_runtime_fails_closed_on_insecure_secret_mode_before_compose(
    tmp_path: Path,
) -> None:
    assert PROXMOX_START_RUNTIME.is_file()
    repo, log_path = _materialize_proxmox_runtime_repo(tmp_path)
    secret_root = _build_secret_root(tmp_path, include_tunnel=False)
    (secret_root / "langfuse.env").chmod(0o644)

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "start-runtime.sh",
        cwd=repo,
        env={
            PROXMOX_SECRET_ROOT_ENV: str(secret_root),
            "RAGWELD_SKIP_TUNNEL": "1",
            "FAKE_TOOL_LOG": str(log_path),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert "langfuse.env" in result.stderr
    assert "0600" in result.stderr
    assert (not log_path.exists()) or all(" up " not in line for line in log_path.read_text(encoding="utf-8").splitlines())


def test_proxmox_lifecycle_start_runtime_refuses_conflicting_repo_env_paths(tmp_path: Path) -> None:
    assert PROXMOX_START_RUNTIME.is_file()
    repo, log_path = _materialize_proxmox_runtime_repo(tmp_path)
    secret_root = _build_secret_root(tmp_path, include_tunnel=False)
    (repo / ".env").write_text("conflict\n", encoding="utf-8")

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "start-runtime.sh",
        cwd=repo,
        env={
            PROXMOX_SECRET_ROOT_ENV: str(secret_root),
            "RAGWELD_SKIP_TUNNEL": "1",
            "FAKE_TOOL_LOG": str(log_path),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
    )

    assert result.returncode != 0
    assert ".env" in result.stderr
    assert "symlink" in result.stderr
    assert (not log_path.exists()) or all(" up " not in line for line in log_path.read_text(encoding="utf-8").splitlines())


def test_proxmox_lifecycle_stop_runtime_only_stops_owned_stack_without_destructive_commands(
    tmp_path: Path,
) -> None:
    assert PROXMOX_STOP_RUNTIME.is_file()
    repo, log_path = _materialize_proxmox_runtime_repo(tmp_path)

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "stop-runtime.sh",
        cwd=repo,
        env={
            "FAKE_TOOL_LOG": str(log_path),
            "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "stop --no-docker"
    assert lines[1] == (
        "docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml "
        "-f deploy/proxmox/docker-compose.yml stop"
    )


def test_proxmox_secret_bootstrap_rejects_non_private_password_file_before_initialization(
    tmp_path: Path,
) -> None:
    assert PROXMOX_BOOTSTRAP_SECRETS.is_file()
    repo, _ = _materialize_proxmox_runtime_repo(tmp_path)
    password_file = tmp_path / "owner-password"
    password_file.write_text("owner-secret\n", encoding="utf-8")
    password_file.chmod(0o644)
    secret_root = tmp_path / "ragweld-etc"

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "bootstrap-secrets.sh",
        "david",
        str(password_file),
        cwd=repo,
        env={PROXMOX_SECRET_ROOT_ENV: str(secret_root)},
    )

    assert result.returncode != 0
    assert "0600" in result.stderr
    assert not secret_root.exists()


def test_proxmox_secret_bootstrap_generates_owner_only_runtime_material_and_exact_hash_formats(
    tmp_path: Path,
) -> None:
    assert PROXMOX_BOOTSTRAP_SECRETS.is_file()
    repo, _ = _materialize_proxmox_runtime_repo(tmp_path)
    password = "owner-secret-for-bootstrap"
    password_file = tmp_path / "owner-password"
    password_file.write_text(f"{password}\n", encoding="utf-8")
    password_file.chmod(0o600)
    secret_root = tmp_path / "ragweld-etc"

    result = _run_shell_script(
        repo / "deploy" / "proxmox" / "bootstrap-secrets.sh",
        "david",
        str(password_file),
        cwd=repo,
        env={PROXMOX_SECRET_ROOT_ENV: str(secret_root)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    assert _mode(secret_root) == 0o700
    assert _mode(secret_root / "authelia") == 0o700
    assert _mode(secret_root / "authelia" / "state") == 0o700
    for relative_path in PROXMOX_BOOTSTRAP_OUTPUT_FILES:
        assert _mode(secret_root / relative_path) == 0o600

    runtime_env = _parse_env_file(secret_root / "runtime.env")
    litellm_env = (secret_root / "litellm.env").read_text(encoding="utf-8")
    langfuse_env = _parse_env_file(secret_root / "langfuse.env")
    oidc_secret = (secret_root / "langfuse-oidc-client-secret").read_text(encoding="utf-8").strip()
    oidc_digest = (secret_root / "authelia" / "langfuse-client-secret-digest").read_text(encoding="utf-8").strip()
    users_database = yaml.safe_load((secret_root / "authelia" / "users_database.yml").read_text(encoding="utf-8"))

    assert {
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "GRAFANA_ADMIN_PASSWORD",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "SERVER_HOST",
        "SERVER_PORT",
        "METRICS_ENABLED",
        "TRACING_ENABLED",
    } <= set(runtime_env)
    assert runtime_env["LANGFUSE_PUBLIC_KEY"].startswith("pk-lf-")
    assert runtime_env["LANGFUSE_SECRET_KEY"].startswith("sk-lf-")
    assert runtime_env["LITELLM_API_KEY"].startswith("sk-ragweld-")
    for forbidden_key in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "VOYAGE_API_KEY",
        "COHERE_API_KEY",
        "JINA_API_KEY",
        "LANGFUSE_OIDC_CLIENT_SECRET",
    ):
        assert forbidden_key not in runtime_env

    assert "OPENAI_API_KEY" not in litellm_env
    assert "OPENROUTER_API_KEY" not in litellm_env
    assert langfuse_env["LANGFUSE_INIT_PROJECT_PUBLIC_KEY"] == runtime_env["LANGFUSE_PUBLIC_KEY"]
    assert langfuse_env["LANGFUSE_INIT_PROJECT_SECRET_KEY"] == runtime_env["LANGFUSE_SECRET_KEY"]
    assert langfuse_env["LANGFUSE_INIT_USER_EMAIL"] == "david@ragweld.local"
    assert langfuse_env["LANGFUSE_INIT_USER_NAME"] == "david"
    assert langfuse_env["DATABASE_URL"].startswith("postgresql://langfuse:")
    assert langfuse_env["CLICKHOUSE_URL"] == "http://langfuse-clickhouse:8123"
    assert langfuse_env["LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT"] == "http://langfuse-minio:9000"

    assert oidc_secret
    assert oidc_secret not in (secret_root / "runtime.env").read_text(encoding="utf-8")
    assert oidc_secret not in (secret_root / "langfuse.env").read_text(encoding="utf-8")
    assert _verify_authelia_pbkdf2_sha512(oidc_secret, oidc_digest)

    owner_record = users_database["users"]["david"]
    assert owner_record["displayname"] == "david"
    assert owner_record["email"] == "david@ragweld.local"
    assert owner_record["groups"] == ["owners"]
    assert owner_record["password"].startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    Argon2id.verify_phc_encoded(password.encode("utf-8"), owner_record["password"])


def test_proxmox_secret_bootstrap_fails_closed_on_existing_initialized_secret_root(tmp_path: Path) -> None:
    assert PROXMOX_BOOTSTRAP_SECRETS.is_file()
    repo, _ = _materialize_proxmox_runtime_repo(tmp_path)
    password_file = tmp_path / "owner-password"
    password_file.write_text("owner-secret\n", encoding="utf-8")
    password_file.chmod(0o600)
    secret_root = tmp_path / "ragweld-etc"

    first = _run_shell_script(
        repo / "deploy" / "proxmox" / "bootstrap-secrets.sh",
        "david",
        str(password_file),
        cwd=repo,
        env={PROXMOX_SECRET_ROOT_ENV: str(secret_root)},
    )
    assert first.returncode == 0, first.stderr
    before = (secret_root / "runtime.env").read_text(encoding="utf-8")

    second = _run_shell_script(
        repo / "deploy" / "proxmox" / "bootstrap-secrets.sh",
        "david",
        str(password_file),
        cwd=repo,
        env={PROXMOX_SECRET_ROOT_ENV: str(secret_root)},
    )

    assert second.returncode != 0
    assert "already initialized" in second.stderr
    assert (secret_root / "runtime.env").read_text(encoding="utf-8") == before
