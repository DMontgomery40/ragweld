# Proxmox Runtime Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the tested, deployment-owned runtime surface required to run the full Ragweld platform securely inside the approved pve1 LXC.

**Architecture:** Keep the existing host-mode FastAPI lifecycle so Docker control remains loopback-only, and add a Proxmox deployment overlay for Caddy, Authelia, cloudflared, and Langfuse OIDC. Generate a validated production config outside the repository, serve the built frontend through Caddy, and keep every secret under `/etc/ragweld`.

**Tech Stack:** FastAPI, Pydantic, pytest, Docker Compose, Caddy 2.11.4, Authelia 4.39.20, cloudflared 2026.7.2, Langfuse v4, systemd, React/Vite.

**Spec:** `docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md`

## Global Constraints

- Work directly on canonical local `main`; create no branch or worktree.
- Keep the Mac runtime and all Mac data intact; this plan contains no remote infrastructure mutation.
- Use `LiteLLM` as the only generation egress and configure `OpenRouter` aliases for the Proxmox deployment.
- Do not add a local-model fallback, fake vLLM endpoint, Ollama path, llama.cpp path, or dual routing contract.
- Keep every public port behind Cloudflare Tunnel and Authelia; Proxmox and database/control-plane ports remain private.
- Store no password, tunnel token, provider key, OIDC secret, or private key in Git.
- Keep `mkdocs/**` and `mkdocs.yml` generated and untouched.
- Before editing each existing function/class/method, run GitNexus upstream impact; warn before HIGH or CRITICAL changes.
- Before each commit run GitNexus `detect-changes`; use the exact file allowlist shown in the task.
- New and edited tests use real code paths and controlled local processes; no request interception, `unittest.mock`, or `monkeypatch`.

## File structure

| Path | Responsibility |
| --- | --- |
| `server/api/health.py` | Treat configured-disabled vLLM as explicit, nonblocking readiness |
| `tests/api/test_health_endpoints.py` | API regression for disabled and enabled vLLM readiness |
| `deploy/proxmox/render_config.py` | Validate and render an external production `TriBridConfig` |
| `deploy/proxmox/docker-compose.yml` | Pinned Authelia/Caddy/cloudflared services and Langfuse production overrides |
| `deploy/proxmox/Caddyfile` | Hostname routing, forward auth, static SPA, and loopback reverse proxies |
| `deploy/proxmox/authelia/configuration.yml` | One-factor owner auth, shared cookie, deny-by-default rules, Langfuse OIDC client |
| `deploy/proxmox/start-runtime.sh` | Fail-closed production launcher for ingress plus the existing host API stack |
| `deploy/proxmox/stop-runtime.sh` | Stop exactly the Proxmox Ragweld project and owned host backend |
| `deploy/proxmox/ragweld.service` | systemd ownership and restart policy |
| `deploy/proxmox/plex/*` | NFSv4 export/mount templates for the separately executed Plex migration |
| `server/api/docker.py` | Backend allowlist for the three new managed ingress services |
| `web/src/api/docker.ts` | Generated-safe frontend service literal list |
| `web/src/components/Infrastructure/DockerSubtab.tsx` | Labels for ingress/auth services |
| `web/src/components/Infrastructure/ServicesSubtab.tsx` | Secure-ingress service group |
| `tests/unit/test_proxmox_deployment_contract.py` | Static and rendered deployment invariants |

---

### Task 1: Make disabled vLLM readiness honest and nonblocking

**Files:**
- Modify: `server/api/health.py:112-238`
- Modify: `tests/api/test_health_endpoints.py`

**Interfaces:**
- Consumes: `TriBridConfig.chat.vllm.enabled: bool`.
- Produces: `/api/ready.dependencies.vllm.info == {"status": "disabled by configuration", "required": false}` and does not set overall readiness false solely for disabled vLLM.

- [ ] **Step 1: Record impact before editing**

Run:

```bash
node .gitnexus/run.cjs impact readiness_check --repo ragweld --direction upstream --depth 3 --include-tests
```

Expected: LOW graph risk; `readiness_check` participates in the readiness processes even though FastAPI route registration is not represented as a caller.

- [ ] **Step 2: Write the failing disabled-vLLM API regression**

Append a test that uses the pytest-owned config file through the real config endpoint:

```python
@pytest.mark.asyncio
async def test_ready_marks_configured_disabled_vllm_nonblocking(client: AsyncClient) -> None:
    baseline = await client.get("/api/config")
    assert baseline.status_code == 200
    config = baseline.json()
    config["chat"]["vllm"]["enabled"] = False
    saved = await client.put("/api/config", json=config)
    assert saved.status_code == 200

    old_vllm = os.environ.get("VLLM_BASE_URL")
    os.environ["VLLM_BASE_URL"] = "http://127.0.0.1:1/v1"
    try:
        response = await client.get("/api/ready")
    finally:
        if old_vllm is None:
            os.environ.pop("VLLM_BASE_URL", None)
        else:
            os.environ["VLLM_BASE_URL"] = old_vllm

    dependency = response.json()["dependencies"]["vllm"]
    assert dependency["ok"] is True
    assert dependency["error"] is None
    assert dependency["operator_hint"] is None
    assert dependency["info"] == {
        "status": "disabled by configuration",
        "required": False,
    }
```

- [ ] **Step 3: Run the regression and confirm the old behavior fails**

Run:

```bash
uv run pytest -q tests/api/test_health_endpoints.py::test_ready_marks_configured_disabled_vllm_nonblocking
```

Expected: FAIL because the current endpoint probes the unreachable vLLM URL unconditionally.

- [ ] **Step 4: Implement the minimal branch around the real vLLM probe**

Initialize `vllm_status` as today. Replace only the local-serving probe section with the following shape, retaining the existing enabled-path body unchanged inside `else`:

```python
if not cfg.chat.vllm.enabled:
    vllm_status.ok = True
    vllm_status.info = {
        "status": "disabled by configuration",
        "required": False,
    }
else:
    serving_mismatch: str | None = None
    # Indent the existing identity/context probe and its existing exception
    # handler under this branch without changing their enabled-path logic.
```

Do not change LiteLLM, Postgres, Neo4j, manifest, or enabled-vLLM failure semantics.

- [ ] **Step 5: Run the whole health family**

Run:

```bash
uv run pytest -q tests/api/test_health_endpoints.py tests/api/test_config_control_plane_endpoints.py tests/unit/test_observability_readiness_probes.py
```

Expected: PASS, including stale-model mismatch rejection when vLLM is enabled.

- [ ] **Step 6: Check change scope and commit**

Run:

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 100
git add server/api/health.py tests/api/test_health_endpoints.py
git commit -m "fix(runtime): allow explicitly disabled vllm readiness"
```

Expected: only the readiness endpoint and its tests are changed.

### Task 2: Add a validated Proxmox production-config renderer

**Files:**
- Create: `deploy/proxmox/render_config.py`
- Create: `tests/unit/test_proxmox_deployment_contract.py`

**Interfaces:**
- Consumes: `--source PATH`, `--output PATH`, and canonical `TriBridConfig` JSON.
- Produces: mode `0600` JSON with cloud gateway defaults, production UI URLs, and `chat.vllm.enabled=false`.

- [ ] **Step 1: Write failing renderer tests**

Create a test module with a real subprocess call:

```python
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from server.models.tribrid_config_model import TriBridConfig

ROOT = Path(__file__).resolve().parents[2]


def test_proxmox_renderer_writes_valid_cloud_first_config(tmp_path: Path) -> None:
    output = tmp_path / "tribrid_config.json"
    result = subprocess.run(
        [
            sys.executable,
            "deploy/proxmox/render_config.py",
            "--source",
            "tribrid_config.json",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    validated = TriBridConfig.model_validate(payload)
    assert validated.generation.gen_model == "openai.gpt-5.4-mini"
    assert validated.generation.enrich_model == "openai.gpt-5.4-mini"
    assert validated.chat.litellm.default_model == "openai.gpt-5.4-mini"
    assert validated.chat.vllm.enabled is False
    assert validated.embedding.embedding_type == "huggingface"
    assert validated.embedding.embedding_model == "BAAI/bge-small-en-v1.5"
    assert validated.embedding.embedding_dim == 384
    assert validated.ui.chat_default_model == "openai.gpt-5.4-mini"
    assert validated.ui.runtime_mode == "production"
    assert validated.ui.open_browser is False
    assert validated.ui.grafana_base_url == "https://grafana.ragweld.com"
    assert output.stat().st_mode & 0o777 == 0o600


def test_proxmox_renderer_does_not_modify_source(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes((ROOT / "tribrid_config.json").read_bytes())
    before = source.read_bytes()
    output = tmp_path / "rendered.json"
    subprocess.run(
        [sys.executable, str(ROOT / "deploy/proxmox/render_config.py"), "--source", str(source), "--output", str(output)],
        cwd=ROOT,
        check=True,
    )
    assert source.read_bytes() == before
```

- [ ] **Step 2: Run tests and confirm the script is absent**

Run:

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py
```

Expected: FAIL because `render_config.py` does not exist.

- [ ] **Step 3: Implement the renderer**

Implement `main(argv: list[str] | None = None) -> int` with `argparse`, load JSON, mutate only these validated fields, and write atomically through a sibling temporary file:

```python
config.generation.gen_model = "openai.gpt-5.4-mini"
config.generation.enrich_model = "openai.gpt-5.4-mini"
config.chat.litellm.default_model = "openai.gpt-5.4-mini"
config.chat.vllm.enabled = False
config.embedding.embedding_backend = "provider"
config.embedding.embedding_type = "huggingface"
config.embedding.embedding_model = "BAAI/bge-small-en-v1.5"
config.embedding.embedding_dim = 384
config.ui.chat_default_model = "openai.gpt-5.4-mini"
config.ui.runtime_mode = "production"
config.ui.open_browser = False
config.ui.grafana_base_url = "https://grafana.ragweld.com"
config.training.ragweld_agent_flyte_admin_base_url = "http://127.0.0.1:30080"
config.training.ragweld_agent_flyte_console_base_url = "https://flyte.ragweld.com"
config.training.ragweld_agent_mlflow_tracking_url = "http://127.0.0.1:55500"
```

Validate again with `TriBridConfig.model_validate`, write
`json.dumps(config.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"`,
call `os.chmod(temp, 0o600)`, then `os.replace(temp, output)`.

- [ ] **Step 4: Run renderer and config tests**

Run:

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py tests/unit/test_config.py tests/unit/test_config_runtime_path.py
```

Expected: PASS.

- [ ] **Step 5: Check scope and commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 100
git add deploy/proxmox/render_config.py tests/unit/test_proxmox_deployment_contract.py
git commit -m "feat(deploy): render validated proxmox config"
```

### Task 3: Add pinned ingress, authentication, and Langfuse SSO configuration

**Files:**
- Create: `deploy/proxmox/docker-compose.yml`
- Create: `deploy/proxmox/Caddyfile`
- Create: `deploy/proxmox/authelia/configuration.yml`
- Modify: `tests/unit/test_proxmox_deployment_contract.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `/etc/ragweld/authelia/*`, `/etc/ragweld/cloudflared-token`, `/etc/ragweld/langfuse-oidc-client-secret`, and built `web/dist`.
- Produces: loopback Caddy origin `127.0.0.1:58000`, Authelia `127.0.0.1:59091`, and protected sibling-hostname routing.

- [ ] **Step 1: Write failing deployment topology tests**

Extend the deployment contract test to render all three Compose files and assert:

```python
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
        {"mode": "ingress", "target": 9091, "published": "59091", "protocol": "tcp", "host_ip": "127.0.0.1"}
    ]
    assert all(
        service["labels"]["io.ragweld.managed"] == "true"
        for service in (services["authelia"], services["caddy"], services["cloudflared"])
    )
    rendered = json.dumps(config)
    assert "OPENROUTER_API_KEY" not in rendered
    assert "/etc/ragweld/cloudflared" in rendered
```

The local `_compose_config` helper must add only dummy values
`LANGFUSE_OIDC_CLIENT_SECRET=contract-only` and
`GRAFANA_ADMIN_PASSWORD=contract-only` to its subprocess environment so the
required production substitutions render without reading `/etc/ragweld`.

Add textual checks that the Caddyfile contains `default_bind 127.0.0.1`, all six hostnames, uses `/api/authz/forward-auth`, copies the four Authelia identity headers, serves `/web/`, and contains no route for Proxmox, Neo4j, Qdrant, Prometheus, Loki, Tempo, Mimir, Pyroscope, Alertmanager, ClickHouse, Redis, or MinIO.

Add YAML checks that Authelia uses `default_policy: deny`, a one-factor `owners` rule, modern `session.cookies`, file authentication, SQLite storage, and the exact Langfuse callback `https://langfuse.ragweld.com/api/auth/callback/custom`.

- [ ] **Step 2: Confirm tests fail before files exist**

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py
```

Expected: FAIL on missing deployment files.

- [ ] **Step 3: Create the Compose overlay**

Define exactly three new services:

```yaml
services:
  grafana:
    environment:
      GF_SECURITY_ADMIN_PASSWORD: "${GRAFANA_ADMIN_PASSWORD:?set GRAFANA_ADMIN_PASSWORD}"

  authelia:
    image: authelia/authelia:4.39.20
    labels:
      io.ragweld.managed: "true"
    restart: unless-stopped
    environment:
      X_AUTHELIA_CONFIG_FILTERS: template
      AUTHELIA_SESSION_SECRET_FILE: /run/secrets/authelia_session
      AUTHELIA_STORAGE_ENCRYPTION_KEY_FILE: /run/secrets/authelia_storage
      AUTHELIA_IDENTITY_PROVIDERS_OIDC_HMAC_SECRET_FILE: /run/secrets/authelia_oidc_hmac
    ports:
      - "127.0.0.1:59091:9091"
    volumes:
      - ./deploy/proxmox/authelia/configuration.yml:/config/configuration.yml:ro
      - /etc/ragweld/authelia/users_database.yml:/config/users_database.yml:ro
      - /etc/ragweld/authelia/oidc-rsa.pem:/config/oidc-rsa.pem:ro
      - /etc/ragweld/authelia/state:/state
    secrets:
      - authelia_session
      - authelia_storage
      - authelia_oidc_hmac

  caddy:
    image: caddy:2.11.4-alpine
    labels:
      io.ragweld.managed: "true"
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./deploy/proxmox/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./web/dist:/srv/web:ro
    depends_on:
      authelia:
        condition: service_started

  cloudflared:
    image: cloudflare/cloudflared:2026.7.2
    labels:
      io.ragweld.managed: "true"
    restart: unless-stopped
    user: "0:0"
    network_mode: host
    command: ["tunnel", "--no-autoupdate", "--config", "/etc/cloudflared/config.yml", "run"]
    volumes:
      - /etc/ragweld/cloudflared:/etc/cloudflared:ro
    depends_on:
      caddy:
        condition: service_started
```

Define every Authelia secret as an external file under `/etc/ragweld`. Mount
the locally managed Cloudflare tunnel config and credential JSON read-only from
`/etc/ragweld/cloudflared`. Do not put secret values in the Compose file.

- [ ] **Step 4: Create Caddy routing with preferred forward auth**

Use Caddy's standard `forward_auth` directive. `auth.ragweld.com` proxies directly to Authelia. The other five hosts import a shared snippet:

```caddyfile
{
    admin off
    auto_https off
    default_bind 127.0.0.1
}

(require_owner) {
    forward_auth 127.0.0.1:59091 {
        uri /api/authz/forward-auth
        copy_headers Remote-User Remote-Groups Remote-Email Remote-Name
    }
}

http://auth.ragweld.com:58000 {
    reverse_proxy 127.0.0.1:59091
}

http://me.ragweld.com:58000 {
    import require_owner
    handle /api/* {
        reverse_proxy 127.0.0.1:58012
    }
    handle_path /web/* {
        root * /srv/web
        try_files {path} /index.html
        file_server
    }
    redir /web /web/
    redir / /web/
}
```

Add equivalent protected reverse proxies to Grafana `3301`, Langfuse `53000`, MLflow `55500`, and Flyte `30080`. Disable Caddy's admin endpoint and automatic HTTPS because Cloudflare terminates public TLS and the origin listener is loopback-only HTTP.

- [ ] **Step 5: Create deny-by-default Authelia configuration**

Use file auth, Argon2, local SQLite, a `ragweld.com` session cookie, one-factor rules restricted to `group:owners`, and the modern ForwardAuth endpoint. Configure an OIDC client named `langfuse` with scopes `openid`, `profile`, `email`, and `groups`; authorization code response; `client_secret_basic`; RS256; and the exact public callback URL. Read the RSA private key through the Authelia template secret filter and read the pre-hashed OIDC client secret from `/etc/ragweld/authelia/langfuse-client-secret-digest`.

- [ ] **Step 6: Override Langfuse for the public URL and custom OIDC**

In `deploy/proxmox/docker-compose.yml`, add a `langfuse` service override with
these environment values so the Mac/local observability file remains unchanged:

```yaml
NEXTAUTH_URL: "https://langfuse.ragweld.com"
AUTH_CUSTOM_CLIENT_ID: "langfuse"
AUTH_CUSTOM_CLIENT_SECRET: "${LANGFUSE_OIDC_CLIENT_SECRET:?set LANGFUSE_OIDC_CLIENT_SECRET}"
AUTH_CUSTOM_ISSUER: "https://auth.ragweld.com"
AUTH_CUSTOM_NAME: "Ragweld"
AUTH_CUSTOM_SCOPE: "openid email profile groups"
AUTH_CUSTOM_FETCH_USERINFO: "true"
AUTH_DISABLE_USERNAME_PASSWORD: "true"
AUTH_DISABLE_SIGNUP: "true"
```

Load `LANGFUSE_OIDC_CLIENT_SECRET` from the mode-`0600`
`/etc/ragweld/runtime.env` immediately before Compose execution. It is never
written into Compose YAML or Git. Do not capture a production `docker compose
config` rendering because that command expands environment values.

- [ ] **Step 7: Ignore only deployment-secret material**

Add these exact patterns:

```gitignore
deploy/proxmox/runtime/
deploy/proxmox/authelia/users_database.yml
deploy/proxmox/authelia/*.pem
```

- [ ] **Step 8: Render and validate configuration**

Run:

```bash
docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml -f deploy/proxmox/docker-compose.yml config --format json
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py tests/unit/test_runtime_launch_contract.py
```

Expected: Compose renders without secrets printed, all routes/ports satisfy the allowlist, and existing runtime contracts remain green.

- [ ] **Step 9: Check scope and commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 200
git add .gitignore deploy/proxmox/docker-compose.yml deploy/proxmox/Caddyfile deploy/proxmox/authelia/configuration.yml tests/unit/test_proxmox_deployment_contract.py
git commit -m "feat(deploy): add authenticated proxmox ingress"
```

### Task 4: Surface ingress services in the operator workbench

**Files:**
- Modify: `server/api/docker.py:30-57`
- Modify: `web/src/api/docker.ts:9-33`
- Modify: `web/src/components/Infrastructure/DockerSubtab.tsx`
- Modify: `web/src/components/Infrastructure/ServicesSubtab.tsx`
- Modify: `tests/unit/test_runtime_launch_contract.py`

**Interfaces:**
- Consumes: Compose service labels `caddy`, `authelia`, and `cloudflared`.
- Produces: exact backend/frontend allowlist parity and a Secure Ingress UI group.

- [ ] **Step 1: Run impact for each edited symbol**

```bash
node .gitnexus/run.cjs impact _DOCKER_SERVICES --repo ragweld --direction upstream --depth 3 --include-tests
node .gitnexus/run.cjs impact RAGWELD_DOCKER_SERVICES --repo ragweld --direction upstream --depth 3 --include-tests
```

Expected: LOW graph risk; all operational risk is bounded by the exact service allowlist tests.

- [ ] **Step 2: Write failing parity assertions**

Extend the existing exact-service-set test so its expected set includes:

```python
{"caddy", "authelia", "cloudflared"}
```

Assert each has `io.ragweld.managed=true` in the rendered production overlay and that backend, frontend, and UI label maps contain all three exact literals.

- [ ] **Step 3: Confirm the parity test fails**

```bash
uv run pytest -q tests/unit/test_runtime_launch_contract.py -k service
```

Expected: FAIL because the new services are not registered.

- [ ] **Step 4: Add the three exact literals everywhere**

Add `caddy`, `authelia`, and `cloudflared` to backend and frontend service tuples. Add labels `Caddy Secure Ingress`, `Authelia Authentication`, and `Cloudflare Tunnel`. Add a `Secure Ingress` group containing exactly those three services.

- [ ] **Step 5: Run backend and frontend gates**

```bash
uv run pytest -q tests/unit/test_runtime_launch_contract.py tests/api/test_docker_endpoints.py
npm --prefix web run lint
npm --prefix web run build
```

Expected: PASS.

- [ ] **Step 6: Check scope and commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 200
git add server/api/docker.py web/src/api/docker.ts web/src/components/Infrastructure/DockerSubtab.tsx web/src/components/Infrastructure/ServicesSubtab.tsx tests/unit/test_runtime_launch_contract.py
git commit -m "feat(web): show secure ingress services"
```

### Task 5: Add fail-closed production lifecycle ownership

**Files:**
- Create: `deploy/proxmox/start-runtime.sh`
- Create: `deploy/proxmox/stop-runtime.sh`
- Create: `deploy/proxmox/ragweld.service`
- Create: `deploy/proxmox/bootstrap-secrets.sh`
- Modify: `tests/unit/test_proxmox_deployment_contract.py`

**Interfaces:**
- Consumes: `/etc/ragweld` secret/config files, built `web/dist`, Docker, `.venv`, and the deployment Compose overlay.
- Produces: one foreground systemd-owned Ragweld process and exact stop semantics.

- [ ] **Step 1: Write failing lifecycle contract tests**

Assert scripts use `set -euo pipefail`, never use `rm -rf`, require the exact `/etc/ragweld` files, and launch the full exact service list through all three Compose files. Assert the host launcher receives `--no-docker --no-local-model --no-frontend`, so it owns FastAPI without recreating the production container topology or starting Vite/local inference. Assert `RAGWELD_SKIP_TUNNEL=1` omits only the cloudflared credential preflight/service and the installed systemd unit sets it to `0` by default. Assert the unit uses `After=network-online.target docker.service`, `Restart=on-failure`, `WorkingDirectory=/opt/ragweld`, and the two deployment scripts.

- [ ] **Step 2: Confirm the lifecycle test fails**

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py -k lifecycle
```

Expected: FAIL on missing scripts/unit.

- [ ] **Step 3: Implement the start script**

The script must:

1. verify `/etc/ragweld/tribrid_config.json`, `/etc/ragweld/runtime.env`, `/etc/ragweld/litellm.env`, `/etc/ragweld/langfuse.env`, Authelia secrets/user DB/RSA key, and the Langfuse OIDC raw secret exist and are not group/world readable; unless `RAGWELD_SKIP_TUNNEL=1`, also require the local Cloudflare config/credential JSON;
2. verify `web/dist/index.html`, `.venv/bin/uvicorn`, Docker, and Compose exist;
3. symlink repo `.env` to `/etc/ragweld/runtime.env`, `infra/litellm.env` to `/etc/ragweld/litellm.env`, and `infra/langfuse.env` to `/etc/ragweld/langfuse.env` only when each repo path is absent or already points to its exact `/etc/ragweld` source;
4. run `docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml -f deploy/proxmox/docker-compose.yml up -d --wait` with this exact service list:

```text
postgres neo4j qdrant mlflow litellm postgres-exporter prometheus grafana
loki promtail tempo alloy mimir pyroscope alertmanager langfuse
langfuse-worker langfuse-postgres langfuse-clickhouse langfuse-redis
langfuse-minio flyte authelia caddy
```

Add `cloudflared` unless `RAGWELD_SKIP_TUNNEL=1`. Omit the Compose `api`
service because FastAPI remains host-owned.
5. `exec ./start.sh --no-docker --no-local-model --no-frontend` with `RAGWELD_CONFIG_PATH=/etc/ragweld/tribrid_config.json`.

- [ ] **Step 4: Implement exact stop semantics**

Run `./stop.sh --no-docker`, then run:

```bash
docker compose --project-name ragweld \
  -f docker-compose.yml \
  -f infra/docker-compose.observability.yml \
  -f deploy/proxmox/docker-compose.yml \
  stop
```

Never delete volumes, containers, source, corpora, or secrets.

- [ ] **Step 5: Implement secret bootstrap with password-file input**

`bootstrap-secrets.sh` accepts exactly two arguments: owner username and a path to a mode-`0600` password file. It creates `/etc/ragweld/authelia/state` and generates random 64-byte session/storage/OIDC secrets, an RSA-3072 PKCS#8 key, a random Langfuse OIDC client secret, the Authelia PBKDF2 digest of that client secret, and the Argon2id owner password hash. It also creates new Postgres, Neo4j, LiteLLM, Grafana, and Langfuse machine credentials and writes the complete non-provider runtime material to `/etc/ragweld/runtime.env`, `/etc/ragweld/litellm.env`, and `/etc/ragweld/langfuse.env`. It writes the raw OIDC secret only to `/etc/ragweld/langfuse-oidc-client-secret`, writes the owner database only to `/etc/ragweld/authelia/users_database.yml`, sets `/etc/ragweld` ownership to the `ragweld` service user with directory mode `0700` and file mode `0600`, and never echoes any secret.

- [ ] **Step 6: Implement systemd ownership**

Use:

```ini
[Unit]
Description=Ragweld personal MLOps platform
Wants=network-online.target
After=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User=ragweld
Group=ragweld
SupplementaryGroups=docker
WorkingDirectory=/opt/ragweld
Environment=RAGWELD_SKIP_TUNNEL=0
ExecStart=/opt/ragweld/deploy/proxmox/start-runtime.sh
ExecStop=/opt/ragweld/deploy/proxmox/stop-runtime.sh
Restart=on-failure
RestartSec=10
TimeoutStartSec=900
TimeoutStopSec=180
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 7: Run shell and unit contract tests**

```bash
bash -n deploy/proxmox/start-runtime.sh deploy/proxmox/stop-runtime.sh deploy/proxmox/bootstrap-secrets.sh
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py tests/unit/test_runtime_lifecycle.py
```

Expected: PASS.

- [ ] **Step 8: Check scope and commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 200
git add deploy/proxmox/start-runtime.sh deploy/proxmox/stop-runtime.sh deploy/proxmox/bootstrap-secrets.sh deploy/proxmox/ragweld.service tests/unit/test_proxmox_deployment_contract.py
git commit -m "feat(deploy): add proxmox lifecycle ownership"
```

### Task 6: Add the reviewed Plex NFS bridge templates

**Files:**
- Create: `deploy/proxmox/plex/exports.ragweld`
- Create: `deploy/proxmox/plex/nfs.conf`
- Create: `deploy/proxmox/plex/srv-media.mount`
- Create: `deploy/proxmox/plex/srv-media.automount`
- Modify: `tests/unit/test_proxmox_deployment_contract.py`

**Interfaces:**
- Consumes: `pve1:/srv/media` and exact client `192.168.68.173`.
- Produces: NFSv4-only export and a hard, automounted `/srv/media` path on `.173`.

- [ ] **Step 1: Write failing NFS scope tests**

Assert the export contains exactly one client, `192.168.68.173`, uses `rw,sync,root_squash,no_subtree_check`, and contains no wildcard or `/24`. Assert `nfs.conf` disables v3 and enables v4. Assert the mount unit uses `What=192.168.68.171:/srv/media`, `Where=/srv/media`, `Type=nfs4`, `_netdev`, `hard`, `noatime`, and `x-systemd.automount` behavior.

- [ ] **Step 2: Confirm tests fail before templates exist**

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py -k nfs
```

- [ ] **Step 3: Add exact templates**

`exports.ragweld`:

```text
/srv/media 192.168.68.173(rw,sync,root_squash,no_subtree_check)
```

`nfs.conf`:

```ini
[nfsd]
vers3=n
vers4=y
```

The mount and automount units use the values from the interface contract and set `TimeoutIdleSec=60`.

- [ ] **Step 4: Run deployment contract tests**

```bash
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py
```

Expected: PASS.

- [ ] **Step 5: Check scope and commit**

```bash
node .gitnexus/run.cjs detect-changes --scope all --repo ragweld --limit 200
git add deploy/proxmox/plex tests/unit/test_proxmox_deployment_contract.py
git commit -m "feat(deploy): add scoped plex media bridge"
```

### Task 6b: Operator watchdog fixes (injected by David, 2026-08-28)

I reviewed Tasks 1-5 against the real repo contracts and the sibling rollout
plan. The running list with evidence is
`docs/exec-plans/active/watchdog-proxmox-foundation-2026-08-28.md`; update the
status of each `W` item there as you close it. This task must complete before
Task 7. Same rules as every other task: red test first, real code paths, exact
staging, no fallbacks.

**Files:**
- Modify: `deploy/proxmox/Caddyfile`
- Modify: `deploy/proxmox/docker-compose.yml`
- Modify: `deploy/proxmox/render_config.py`
- Modify: `deploy/proxmox/start-runtime.sh`
- Modify: `start.sh` (honor `SERVER_HOST` for the uvicorn bind; run GitNexus impact first)
- Modify: `tests/unit/test_proxmox_deployment_contract.py`
- Modify: `tests/unit/test_runtime_launch_contract.py` (bind contract)

- [ ] **Step 1 (W1): Force the https scheme toward Authelia**

Caddy rewrites untrusted `X-Forwarded-Proto` to the scheme it received, which is
`http` from cloudflared. Authelia's `IssuerURL()` rejects anything but `https`,
so OIDC discovery and the ForwardAuth redirect break. In `require_owner` add
`header_up X-Forwarded-Proto https` inside `forward_auth`, and add the same
`header_up` to the `auth.ragweld.com` `reverse_proxy`. Extend the brace-balanced
Caddy parser test so every block that reaches `127.0.0.1:59091` carries it.

- [ ] **Step 2 (W2): Let the seeded Langfuse owner log in over OIDC**

Bootstrap seeds a credentials user with the same email Authelia asserts, signup
is disabled, and account linking is not enabled, so Auth.js returns
`OAuthAccountNotLinked`. Add `AUTH_CUSTOM_ALLOW_ACCOUNT_LINKING: "true"` to the
`langfuse` overlay environment and assert it in the compose contract test.

- [ ] **Step 3 (W3): Make the host API reachable from Linux containers**

On Linux Docker `host-gateway` is the bridge IP, not loopback, so
`infra/prometheus.yml` scraping `host.docker.internal:58012` and the Flyte
execute-callback both fail against `--host 127.0.0.1`. Decision: `start.sh`
binds uvicorn to `${SERVER_HOST:-127.0.0.1}` (bootstrap already writes
`SERVER_HOST` to `runtime.env`; change that value to `0.0.0.0` for the LXC),
the renderer sets
`training.ragweld_agent_flyte_callback_base_url = "http://172.17.0.1:58012"`
(correction 2026-08-28, W20: Flyte task pods resolve through the sandbox's k3s
CoreDNS and cannot see `host.docker.internal`; the Docker default-bridge
gateway is what they can reach — the 2026-08-22 Flyte slice hit exactly this on
Colima), `start-runtime.sh` preflight asserts
`docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'` equals
that host and dies otherwise, and the LXC firewall remains the boundary. Run
`node .gitnexus/run.cjs impact` on the touched `start.sh` function first. Tests:
`start.sh --check` echoes the `SERVER_HOST` bind; renderer test asserts the
callback URL; a start-runtime test with a fake `docker network inspect`
returning a different gateway proves the fail-closed path; keep the Mac default
at `127.0.0.1`.

Also in this step (W21, W22): while the MLflow link builder is open, persist
`tracking_experiment_id` on `AgentTrainRun` from `MlflowRunHandle.experiment_id`
and build the console link from it instead of parsing `artifacts_uri`; and set
`alloy.environment.ALLOY_FARO_CORS_ORIGIN: https://me.ragweld.com` in the
overlay so the Faro receiver's allowlist matches the real origin.

- [ ] **Step 4 (W9, W10): Grafana public root URL and Caddy catch-all**

Overlay: `GF_SERVER_ROOT_URL: "https://grafana.ragweld.com"` on `grafana`.
Caddyfile: final `handle { respond 404 }` in the `me.ragweld.com` block so
unmatched paths do not return an empty `200`. Cover both in the contract tests.

- [ ] **Step 5 (W6, W5): Preflight the lifecycle prerequisites honestly**

`start-runtime.sh` must fail with a clear message when `lsof` is missing
(`start.sh`/`stop.sh` hard-require it) instead of restart-looping under
systemd. Keep `credentials.json` as the required tunnel file name; the rollout
plan now renames the generated `<UUID>.json` to it.

- [ ] **Step 6 (W7, ruled): Split browser-facing URLs from server-side endpoints**

Decided 2026-08-28: take the full fix, not the blanking shortcut.
`tracing.langfuse_base_url` and `training.ragweld_agent_mlflow_tracking_url`
are emitted to the browser as links but are also the server-side endpoints;
`tracing.faro_base_url` is loaded by every remote page. Pydantic-first:
1. Add `tracing.langfuse_public_base_url` and
   `training.ragweld_agent_mlflow_console_base_url` to the domain configs
   (default `""`; when empty the link builders fall back to nothing, never to
   the server-side URL), add glossary entries, run
   `uv run scripts/generate_types.py`, and route `langfuse_trace_url`
   (`server/observability/runtime.py`) and the MLflow `TraceExternalLink`
   (`server/training/control_plane.py`) through the new fields. Run GitNexus
   impact on both functions first.
2. Add a Caddy route on `me.ragweld.com`: `handle /faro/collect` →
   `reverse_proxy 127.0.0.1:52347` (behind `require_owner`), and cover it in
   the parser test's allowlist.
3. Renderer sets `tracing.langfuse_public_base_url = "https://langfuse.ragweld.com"`,
   `training.ragweld_agent_mlflow_console_base_url = "https://mlflow.ragweld.com"`,
   and `tracing.faro_base_url = "https://me.ragweld.com/faro/collect"`; extend
   the whole-model renderer invariant test accordingly.
4. Contract tests: a trace-link test that proves the public field is used for
   the browser link while ingestion still targets the loopback field.

- [ ] **Step 7 (W12): Repair the GitNexus index before the final scope check**

Run `node .gitnexus/run.cjs analyze --force` once, then re-run
`detect-changes --scope staged` for this task. Do not carry the "graph noise"
ruling into Task 7.

- [ ] **Step 7b (W8, W24 — added 2026-08-28 03:15): Truthful probes and local link values**

1. `server/observability/status.py` `_check_url`: stop following redirects; a
   3xx whose `Location` host differs from the probed host returns
   `(None, "redirected to <host>; protected ingress cannot be probed from the API")`
   so Grafana/Faro show *unverified* on pve1 instead of false-green via the
   Authelia portal. Real local-HTTP-server test (302 to another host → `ok is
   None`); keep the 405/415 POST-only rule. Run GitNexus impact on
   `_check_url` first.
2. Checked-in `tribrid_config.json`: add
   `tracing.langfuse_public_base_url = "http://127.0.0.1:53000"` and
   `training.ragweld_agent_mlflow_console_base_url = "http://127.0.0.1:55500"`
   so the Mac workbench keeps its links under the no-fallback rule; pin both
   in `tests/unit/test_clean_start_defaults.py`. Record in the handoff that
   the Mac's stored global config needs the same two values set once through
   the Config UI.

- [ ] **Step 8: Verify and commit**

```bash
bash -n deploy/proxmox/start-runtime.sh deploy/proxmox/stop-runtime.sh deploy/proxmox/bootstrap-secrets.sh
uv run pytest -q tests/unit/test_proxmox_deployment_contract.py tests/unit/test_runtime_launch_contract.py tests/unit/test_runtime_lifecycle.py
LANGFUSE_OIDC_CLIENT_SECRET=contract-only GRAFANA_ADMIN_PASSWORD=contract-only LANGFUSE_POSTGRES_PASSWORD=contract-only CLICKHOUSE_PASSWORD=contract-only REDIS_AUTH=contract-only LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID=contract-only LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=contract-only docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml -f deploy/proxmox/docker-compose.yml config --format json >/dev/null
node .gitnexus/run.cjs detect-changes --scope staged --repo ragweld --limit 200
git add deploy/proxmox/Caddyfile deploy/proxmox/docker-compose.yml deploy/proxmox/render_config.py deploy/proxmox/start-runtime.sh deploy/proxmox/bootstrap-secrets.sh start.sh tests/unit/test_proxmox_deployment_contract.py tests/unit/test_runtime_launch_contract.py
git commit -m "fix(deploy): close watchdog findings before publication"
```

Then mark each closed `W` item `FIXED <commit>` in the watchdog file. Task 7
Step 1 must run the full `pytest -q` on this tree (W13); do not cite the Task 5
count.

### Task 7: Final foundation verification and direct publication

**Files:**
- Modify: `docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md` only if verified implementation facts differ
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md` with source-gate evidence

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: one published `main` commit suitable for the live migration plans.

- [ ] **Step 1: Run all required validators**

```bash
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/generate_litellm_config.py --check
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
git diff --check
```

Expected: all green; record exact counts and hashes without secrets.

- [ ] **Step 2: Render deployment configuration without starting it**

Use dummy environment substitutions only for Compose rendering. Run:

```bash
LANGFUSE_OIDC_CLIENT_SECRET=contract-only GRAFANA_ADMIN_PASSWORD=contract-only docker compose --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml -f deploy/proxmox/docker-compose.yml config --format json
```

Expected: exit 0; only the two literal `contract-only` dummy values appear;
only the three approved public-origin services are added. Never run this
rendering with production environment values loaded.

- [ ] **Step 3: Run independent adversarial review once**

Run one high-reasoning review against the complete source diff. The prompt must ask for concrete P1/P2 correctness, security, secret-handling, auth-bypass, rollback, and fake-green findings. Do not start an unbounded review loop. Fix actionable findings, rerun only the affected tests, and record dispositions.

Operator additions (David, 2026-08-28; see watchdog W18/W19):
- Seed the reviewer with `docs/exec-plans/active/watchdog-proxmox-foundation-2026-08-28.md` as an extra `=====` block and require an explicit disposition per `W` item (confirmed / refuted with evidence / already fixed at `<commit>`), in addition to its own findings.
- Write the report and trace to `.superpowers/sdd/2026-08-27-proxmox-runtime-foundation/glm-review-<base>..<head>.md` and `.jsonl`; record both paths and the verdict in the ledger.
- "Rerun only the affected tests" means every test module that references any staged path: `git diff --cached --name-only | xargs -I{} grep -rl -- "{}" tests | sort -u | xargs uv run pytest -q`. The same rule applies to every fix round in this plan from now on.

- [ ] **Step 4: Verify final Git scope**

```bash
node .gitnexus/run.cjs detect-changes --scope compare --base-ref origin/main --repo ragweld --limit 300
git status --short --branch
git branch --format='%(refname:short)'
git worktree list --porcelain
```

Expected: only the deployment foundation, its tests, the approved spec, and evidence; exactly one local branch and one worktree.

- [ ] **Step 5: Commit evidence and push directly to main**

```bash
git add docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md
git commit -m "docs(deploy): record proxmox foundation evidence"
git push origin main
```

Expected: a non-force push; local `main` and `origin/main` resolve to the same commit afterward.
