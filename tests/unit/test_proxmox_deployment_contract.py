from __future__ import annotations

import copy
import json
import os
import re
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
