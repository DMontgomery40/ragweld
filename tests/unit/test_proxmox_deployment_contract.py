from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from server.models.tribrid_config_model import TriBridConfig

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "proxmox" / "render_config.py"
SOURCE_CONFIG = ROOT / "tribrid_config.json"
PROXMOX_DIR = ROOT / "deploy" / "proxmox"
PROXMOX_COMPOSE = PROXMOX_DIR / "docker-compose.yml"
PROXMOX_CADDYFILE = PROXMOX_DIR / "Caddyfile"
PROXMOX_AUTHELIA_CONFIG = PROXMOX_DIR / "authelia" / "configuration.yml"
PROXMOX_CONTRACT_ENV = {
    "GRAFANA_ADMIN_PASSWORD": "contract-only",
    "LANGFUSE_OIDC_CLIENT_SECRET": "contract-only",
}
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
        if volume["target"] in {"/config/configuration.yml", "/config/users_database.yml", "/config/oidc-rsa.pem", "/state"}
    } == {
        "/config/configuration.yml": str(PROXMOX_AUTHELIA_CONFIG),
        "/config/users_database.yml": "/etc/ragweld/authelia/users_database.yml",
        "/config/oidc-rsa.pem": "/etc/ragweld/authelia/oidc-rsa.pem",
        "/state": "/etc/ragweld/authelia/state",
    }
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


def test_proxmox_caddyfile_limits_public_routes_to_the_allowlist() -> None:
    source = PROXMOX_CADDYFILE.read_text(encoding="utf-8")

    assert "admin off" in source
    assert "auto_https off" in source
    assert "default_bind 127.0.0.1" in source
    assert "uri /api/authz/forward-auth" in source
    assert "copy_headers Remote-User Remote-Groups Remote-Email Remote-Name" in source
    assert "handle_path /web/*" in source
    assert "root * /srv/web" in source
    assert "try_files {path} /index.html" in source
    assert "redir /web /web/" in source
    assert "redir / /web/" in source

    hostnames = {
        "auth.ragweld.com",
        "me.ragweld.com",
        "grafana.ragweld.com",
        "langfuse.ragweld.com",
        "mlflow.ragweld.com",
        "flyte.ragweld.com",
    }
    assert {f"http://{hostname}:58000" for hostname in hostnames} <= set(source.split())

    protected_blocks = {
        "me.ragweld.com": "127.0.0.1:58012",
        "grafana.ragweld.com": "127.0.0.1:3301",
        "langfuse.ragweld.com": "127.0.0.1:53000",
        "mlflow.ragweld.com": "127.0.0.1:55500",
        "flyte.ragweld.com": "127.0.0.1:30080",
    }
    for hostname, upstream in protected_blocks.items():
        block = source.split(f"http://{hostname}:58000", 1)[1]
        block = block.split("\n}\n", 1)[0]
        assert "import require_owner" in block
        assert upstream in block

    auth_block = source.split("http://auth.ragweld.com:58000", 1)[1].split("\n}\n", 1)[0]
    assert "import require_owner" not in auth_block
    assert "127.0.0.1:59091" in auth_block

    forbidden_tokens = {
        "proxmox",
        "neo4j",
        "qdrant",
        "prometheus",
        "loki",
        "tempo",
        "mimir",
        "pyroscope",
        "alertmanager",
        "clickhouse",
        "redis",
        "minio",
        "5432",
        "7687",
        "59090",
        "53100",
        "53200",
        "59009",
        "54040",
        "59093",
        "8123",
        "6379",
        "9000",
    }
    assert forbidden_tokens.isdisjoint(source.lower().split())


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
