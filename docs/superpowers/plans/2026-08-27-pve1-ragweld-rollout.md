# pve1 Ragweld Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision LXC 100 on pve1, install the published Ragweld runtime, expose it securely at `me.ragweld.com`, seed clean public corpora, and prove the full operator experience from an external browser.

**Architecture:** Run Docker plus the existing host-mode FastAPI lifecycle inside a dedicated privileged LXC with Caddy and cloudflared in host-network containers and Authelia on a loopback port. Start with clean platform volumes, OpenRouter generation through LiteLLM, local CPU embeddings, Cloudflare Tunnel ingress, and PBS-backed recovery.

**Tech Stack:** Proxmox VE 9.2.2, Debian 13 LXC, Docker Engine/Compose, Python 3.12/uv, Node.js 22, systemd, Cloudflare Tunnel, Caddy, Authelia, LiteLLM/OpenRouter, Postgres, Qdrant, Neo4j, Flyte, MLflow, Langfuse, Grafana observability stack, Docling.

**Spec:** `docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md`

## Global Constraints

- Execute after the runtime-foundation plan is green and pushed and after LXC 4214 is accepted on `.173`.
- Re-fetch `origin/main` before provisioning and record one exact deployment commit; do not deploy uncommitted Mac source.
- Keep one local branch and one worktree on both Mac and LXC.
- Never move or delete Mac source, Mac corpora, Mac volumes, or Mac secrets.
- Create clean Docker volumes; import no Postgres, Qdrant, Neo4j, MLflow, Langfuse, lineage, synthetic-run, or test-output state.
- Use only new deployment credentials plus an explicit allowlist of copied provider API keys.
- Never print passwords, provider keys, Cloudflare credentials, OIDC secrets, private keys, or complete environment files.
- Do not expose a router port, Proxmox, SSH, or any database/control-plane port publicly.
- Do not claim vLLM or Unsloth acceleration on the Intel iGPU; `chat.vllm.enabled=false` is explicit and nonblocking.
- Use the in-app Browser for Cloudflare/DNS work and rendered acceptance. The user performs any password or OTP entry.
- Stop at the current rollback checkpoint on any backup, mount, auth, readiness, indexing, or browser blocker.

## Operator corrections (David, 2026-08-28)

From `docs/exec-plans/active/watchdog-proxmox-foundation-2026-08-28.md`. These
override the conflicting steps below until the steps themselves are rewritten.

- **W4 — bootstrap needs an empty `/etc/ragweld` (steps rewritten 2026-08-28 06:35; this note is now descriptive).** `bootstrap-secrets.sh`
  fails closed on any existing entry and replaces the directory wholesale. Task
  2 Step 5 must push `deployment-commit` to `/root/ragweld-deployment-commit`
  inside the guest (not `/etc/ragweld/`), and Task 3 Step 5 must create the
  owner password file at `/root/ragweld-owner-password` (mode `0600`). Run
  bootstrap, then move both files into `/etc/ragweld/` as `ragweld:ragweld`
  `0600`. Task 3 Step 4's equality check reads the new path.
- **W5 — tunnel credential name.** `start-runtime.sh` requires
  `/etc/ragweld/cloudflared/credentials.json`. After Task 5 Step 5, copy the
  generated `<UUID>.json` to `credentials.json` (keep the original), and in
  `config.yml` use the container path `credentials-file:
  /etc/cloudflared/credentials.json`.
- **W6 — install `lsof` (added to the Task 3 Step 1 apt line 2026-08-28 06:35).**
  `start.sh`/`stop.sh` exit without it and the unit would restart-loop.
- **W3 — API bind.** After foundation Task 6b lands, `runtime.env` carries
  `SERVER_HOST=0.0.0.0` inside the LXC and the LXC firewall is the boundary.
  Task 2 Step 6's "58000/58012 not reachable from LAN" proof becomes mandatory
  evidence, not optional.
- **W7 — link split landed (`e2a2b9da`).** The renderer sets
  `tracing.langfuse_public_base_url`, `training.ragweld_agent_mlflow_console_base_url`,
  and `tracing.faro_base_url=https://me.ragweld.com/faro/collect`; acceptance
  #12 is testable as written. Record the three rendered values (no secrets) in
  the evidence file.
- **W20 — Flyte callback evidence.** The rendered config carries
  `training.ragweld_agent_flyte_callback_base_url=http://172.17.0.1:58012` and
  `start-runtime.sh` refuses to start unless
  `docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`
  returns that host. Capture that inspect output in the evidence file before
  Task 5 Step 7; if the LXC's Docker daemon uses a custom `bip`, re-render
  with the real gateway rather than editing the daemon.
- **W17 — Cloudflare limits.** Note the 100 MB request-body and ~100 s idle
  response limits in the evidence file; corpus seeding stays rsync.

---

### Task 1: Lock source and revalidate pve1 capacity

**Files:**
- Create: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: published deployment foundation and post-Plex cluster state.
- Produces: deployment commit, resource baseline, and LXC creation authorization evidence.

- [x] **Step 1: Verify Git publication and canon**

```bash
git fetch origin
git rev-parse main
git rev-parse origin/main
git status --short --branch
git branch --format='%(refname:short)'
git worktree list --porcelain
```

Expected: `main == origin/main`, one local branch, one worktree, and only the previously identified user-owned local files outside the deployment diff.

- [x] **Step 2: Run exact source gates on the deployment commit**

```bash
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/generate_litellm_config.py --check
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
```

Expected: all green. Record exact commit and test counts.

- [ ] **Step 3: Revalidate live cluster state**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pvecm status; pveversion; free -h; pvesh get /cluster/resources --type vm --output-format json; pvesm status; test ! -e /etc/pve/lxc/100.conf; ls -l /dev/dri'
```

Expected: quorate, VMID 100 free, LXC 4214 absent from pve1, VM 120 healthy, at least 24 GiB currently available or reclaimable under the approved overcommit, at least 300 GiB free on `local-lvm`, PBS active, and render devices present.

- [ ] **Step 4: Record and commit the locked baseline**

Create the evidence file with commit, tests, pve1 resources, VM 120 state, Plex destination proof reference, and rollback owner. Commit and push it before creating LXC 100.

Stage the locked commit on pve1 without a moving reference:

```bash
git rev-parse origin/main | ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'umask 077; tee /root/ragweld-deployment-commit >/dev/null'
```

### Task 2: Create the dedicated Debian 13 LXC with full pve1 compute access

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: VMID 100, Debian 13 template, pve1 local-lvm, Mac public SSH key.
- Produces: running privileged LXC 100 with 16 CPUs, 24 GiB memory, 8 GiB swap, 300 GiB disk, Docker nesting, and Intel GPU devices.

- [ ] **Step 1: Stage the management public key without private material**

```bash
scp -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519.pub root@192.168.68.171:/root/ragweld-authorized-key.pub
```

Verify the staged file contains exactly one public-key line and no private-key marker.

- [ ] **Step 2: Download the exact Debian template**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pveam download local debian-13-standard_13.6-1_amd64.tar.zst; pveam list local'
```

Expected: `local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst` exists.

- [ ] **Step 3: Create LXC 100 stopped**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct create 100 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst --hostname ragweld --unprivileged 0 --features nesting=1,keyctl=1,fuse=1 --cores 16 --cpuunits 10000 --memory 24576 --swap 8192 --rootfs local-lvm:300 --net0 name=eth0,bridge=vmbr0,ip=dhcp,firewall=1,type=veth --nameserver 192.168.68.1 --ssh-public-keys /root/ragweld-authorized-key.pub --onboot 1 --start 0'
```

Expected: exit 0 and a new stopped LXC 100 only.

- [ ] **Step 4: Pass both Intel DRM devices**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct set 100 --dev0 path=/dev/dri/renderD128,mode=0660 --dev1 path=/dev/dri/card0,mode=0660; pct config 100'
```

Expected: both exact device entries present; no Plex/media bind mount and no Proxmox socket mount.

- [ ] **Step 5: Start and validate LXC resources**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct start 100; pct exec 100 -- nproc; pct exec 100 -- free -h; pct exec 100 -- df -h /; pct exec 100 -- ls -l /dev/dri; pct exec 100 -- ip -4 addr show dev eth0'
```

Expected: 16 CPUs, roughly 24 GiB cap, 300 GiB thin root, both DRM devices, and a LAN IP. Record the IP and reserve it in the router/DHCP system if the current homelab already uses reservations; do not invent a static address inside Debian.

Keep the bootstrap target absent and push the locked commit into guest root:

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct push 100 /root/ragweld-deployment-commit /root/ragweld-deployment-commit --perms 0600; pct exec 100 -- test ! -e /etc/ragweld'
```

Expected: `/root/ragweld-deployment-commit` exists inside LXC 100 at mode
`0600`, while `/etc/ragweld` does not exist yet. Bootstrap owns the first
creation of `/etc/ragweld`; pre-populating it makes bootstrap fail closed.

- [ ] **Step 6: Enable only LAN SSH access**

Disable SSH password authentication inside the guest:

```text
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
```

Write `/etc/ssh/sshd_config.d/90-ragweld.conf` with those exact lines, validate
with `sshd -t`, and reload SSH. From the Mac, open a second key-only SSH session
to the recorded LXC address before enabling firewall policy.

On pve1, create `/etc/pve/firewall/100.fw` with:

```ini
[OPTIONS]
enable: 1
policy_in: DROP
policy_out: ACCEPT

[RULES]
IN ACCEPT -source 192.168.68.1 -p udp -sport 67 -dport 68 -log nolog
IN ACCEPT -source 192.168.68.0/24 -p icmp -log nolog
IN ACCEPT -source 192.168.68.0/24 -p tcp -dport 22 -log nolog
```

Reload `pve-firewall`, prove the second LAN SSH session still succeeds, and
prove TCP 58000/58012 is not reachable directly from the LAN. Cloudflared needs
outbound connectivity only.

- [ ] **Step 7: Record guest config and rollback**

Append `pct config 100`, LAN IP, GPU device major/minor values, and rollback command `pct stop 100` to evidence. Do not delete the LXC if the next task fails; leave it stopped for inspection.

### Task 3: Bootstrap Docker, language runtimes, source, and clean secrets

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: LXC 100, deployment commit, explicit provider-key allowlist.
- Produces: `/opt/ragweld`, `ragweld` service user, Docker/Compose, Python `.venv`, built frontend, and `/etc/ragweld` secrets/config.

- [ ] **Step 1: Install Debian prerequisites inside LXC 100**

Run package updates separately, then install:

```bash
apt-get update
apt-get install -y ca-certificates curl git gnupg jq lsof openssl rsync sudo uidmap fuse-overlayfs python3 python3-venv build-essential pciutils vainfo
```

Install Docker Engine and the Compose plugin from Docker's official Debian
repository:

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker info
docker compose version
```

Require cgroup v2 and the local Unix socket.

- [ ] **Step 2: Install Node.js 22 and uv**

Install Node.js 22 from NodeSource and install `uv` into `/usr/local/bin` with
the official installer:

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x -o /tmp/nodesource_setup.sh
bash /tmp/nodesource_setup.sh
apt-get install -y nodejs
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-installer.sh
env UV_INSTALL_DIR=/usr/local/bin sh /tmp/uv-installer.sh
rm /tmp/nodesource_setup.sh /tmp/uv-installer.sh
```

Verify:

```bash
node --version
npm --version
uv --version
```

Expected: Node major 22 and working uv.

- [ ] **Step 3: Create the service account and clone exact main**

```bash
groupadd --force docker
id ragweld >/dev/null 2>&1 || useradd --create-home --shell /bin/bash ragweld
usermod -aG docker,render,video ragweld
install -d -o ragweld -g ragweld -m 0755 /opt/ragweld /srv/ragweld/corpora
sudo -u ragweld git clone --branch main --single-branch https://github.com/DMontgomery40/ragweld.git /opt/ragweld
DEPLOY_COMMIT="$(git -C /opt/ragweld rev-parse origin/main)"
test "$DEPLOY_COMMIT" = "$(cat /root/ragweld-deployment-commit)"
test "$(git -C /opt/ragweld rev-parse main)" = "$DEPLOY_COMMIT"
test "$(git -C /opt/ragweld branch --show-current)" = main
```

Before cloning, Task 1 writes its full 40-character commit to
`/root/ragweld-deployment-commit` mode `0600`. The equality check prevents a
moving branch from changing the selected deployment source.

- [ ] **Step 4: Install dependencies and build the production frontend**

```bash
sudo -u ragweld sh -lc 'cd /opt/ragweld && uv sync --frozen'
sudo -u ragweld npm --prefix /opt/ragweld/web ci
sudo -u ragweld npm --prefix /opt/ragweld/web run build
test -f /opt/ragweld/web/dist/index.html
```

- [ ] **Step 5: Generate new platform secrets on the LXC**

Create `/root/ragweld-owner-password` mode `0600` containing a new high-entropy
bootstrap passphrase without printing it. Confirm `/etc/ragweld` still does not
exist, then run:

```bash
test ! -e /etc/ragweld
/opt/ragweld/deploy/proxmox/bootstrap-secrets.sh david /root/ragweld-owner-password
mv /root/ragweld-deployment-commit /etc/ragweld/deployment-commit
mv /root/ragweld-owner-password /etc/ragweld/owner-password
chown ragweld:ragweld /etc/ragweld/deployment-commit /etc/ragweld/owner-password
chmod 0600 /etc/ragweld/deployment-commit /etc/ragweld/owner-password
```

The script creates new Postgres, Neo4j, LiteLLM, Langfuse, Authelia, and OIDC material. It must not reuse Mac database/auth secrets.
Only after bootstrap succeeds do the deployment-commit and owner-password files
move into the initialized secret root.

Keep the bootstrap passphrase out of tool output and evidence. Immediately
before Task 6, disclose it once to the owner in the private task response, then
rotate it through Task 6 Step 5 after the first successful external login.

- [ ] **Step 6: Copy only approved provider keys from the Mac**

Create and transfer a mode-`0600` allowlist without printing values:

```bash
PROVIDER_TRANSFER="$(mktemp)"
chmod 600 "$PROVIDER_TRANSFER"
for PROVIDER_KEY in OPENROUTER_API_KEY OPENAI_API_KEY VOYAGE_API_KEY COHERE_API_KEY JINA_API_KEY; do
  PROVIDER_VALUE="$(awk -v key="$PROVIDER_KEY" 'index($0, key "=") == 1 {print substr($0, length(key) + 2)}' .env infra/litellm.env 2>/dev/null | tail -n 1)"
  if [ -n "$PROVIDER_VALUE" ]; then
    printf '%s=%s\n' "$PROVIDER_KEY" "$PROVIDER_VALUE" >> "$PROVIDER_TRANSFER"
  fi
done
test -s "$PROVIDER_TRANSFER"
scp -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes "$PROVIDER_TRANSFER" root@192.168.68.171:/root/ragweld-provider-keys.env
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct push 100 /root/ragweld-provider-keys.env /etc/ragweld/provider-keys.env --perms 0600; rm /root/ragweld-provider-keys.env'
rm "$PROVIDER_TRANSFER"
```

Inside LXC 100, append the exact nonempty allowlist to both
`/etc/ragweld/runtime.env` and `/etc/ragweld/litellm.env`, reject duplicate key
names, set ownership `ragweld:ragweld`, set mode `0600`, and delete only
`/etc/ragweld/provider-keys.env` after comparing the installed key names.

Do not copy `CONFIG_FILE`, data paths, database credentials, Langfuse keys, tracing endpoints, or runtime ports from the Mac.

- [ ] **Step 7: Render the deployment config outside Git**

```bash
sudo -u ragweld /opt/ragweld/.venv/bin/python /opt/ragweld/deploy/proxmox/render_config.py --source /opt/ragweld/tribrid_config.json --output /etc/ragweld/tribrid_config.json
```

Verify the source file hash is unchanged and the rendered file is mode `0600`, cloud-first, production-mode, and vLLM-disabled.

- [ ] **Step 8: Install but do not enable systemd ownership**

```bash
install -m 0644 /opt/ragweld/deploy/proxmox/ragweld.service /etc/systemd/system/ragweld.service
systemctl daemon-reload
systemctl cat ragweld.service
```

Do not start the unit until Cloudflare credentials exist or the start script has an explicit tunnel-disabled preflight mode for internal acceptance.

### Task 4: Prove the complete stack on loopback before changing DNS

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: bootstrapped LXC runtime and deployment config.
- Produces: full internal service health, real OpenRouter smoke, and no public exposure.

- [ ] **Step 1: Start all non-tunnel services in the exact deployment topology**

Create the exact preflight drop-in and start the ordinary service path:

```bash
install -d -m 0755 /etc/systemd/system/ragweld.service.d
install -m 0644 /dev/stdin /etc/systemd/system/ragweld.service.d/10-preflight.conf <<'EOF'
[Service]
Environment=RAGWELD_SKIP_TUNNEL=1
EOF
systemctl daemon-reload
systemctl start ragweld.service
```

This starts Authelia/Caddy plus the full base, observability, Langfuse, Flyte,
and host-mode API while omitting only cloudflared.

- [ ] **Step 2: Verify Docker service inventory and resource use**

```bash
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml -f /opt/ragweld/deploy/proxmox/docker-compose.yml ps
docker stats --no-stream
```

Expected: every required service running/healthy, including Flyte and the full Langfuse dependency group; no vLLM container; total memory remains below the LXC cap with headroom.

- [ ] **Step 3: Verify API liveness and readiness**

```bash
curl -fsS http://127.0.0.1:58012/api/health
curl -fsS http://127.0.0.1:58012/api/ready
```

Expected: HTTP 200; Postgres, Neo4j, LiteLLM, and index manifests ready; vLLM `ok=true` with `info.status="disabled by configuration"` and `info.required=false`.

- [ ] **Step 4: Verify every companion UI through Caddy using Host headers**

Unauthenticated requests to `me`, `grafana`, `langfuse`, `mlflow`, and `flyte` hostnames through `127.0.0.1:58000` must redirect to Authelia. `auth.ragweld.com` must return the Authelia portal. Direct public ports must not exist in `ss -lntp`; only loopback listeners are permitted for origin UIs.

- [ ] **Step 5: Send one paid gateway smoke request**

Use LiteLLM at `127.0.0.1:54000/v1`, model `openai.gpt-5.4-mini`, prompt `Reply with OK only.`, `temperature=0`, `max_tokens=8`, retry zero, and no fallback. Record response ID, resolved model, token usage, and cost only. Do not record the key or headers.

```bash
set -a
. /etc/ragweld/runtime.env
set +a
curl -fsS --retry 0 http://127.0.0.1:54000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"openai.gpt-5.4-mini","messages":[{"role":"user","content":"Reply with OK only."}],"temperature":0,"max_tokens":8}' \
  | jq '{id, model, usage, answer: .choices[0].message.content}'
```

- [ ] **Step 6: Inspect real observability state**

Query Grafana health, Prometheus targets, Tempo readiness, Loki readiness, Mimir readiness, Pyroscope readiness, Langfuse health, MLflow health, and Flyte health. Record failures honestly; do not proceed to DNS while a protected UI or core telemetry backend is unavailable.

Stop the preflight unit, remove only the named drop-in, and reload systemd:

```bash
systemctl stop ragweld.service
rm /etc/systemd/system/ragweld.service.d/10-preflight.conf
systemctl daemon-reload
```

### Task 5: Move DNS to Cloudflare and establish the outbound-only tunnel

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: healthy loopback Caddy origin and Cloudflare/registrar access.
- Produces: authoritative Cloudflare zone, six CNAME routes, local tunnel credential JSON/config, and external HTTPS access.

- [ ] **Step 1: Inventory current DNS and landing records**

Record without mutation:

```bash
dig +short NS ragweld.com
dig +short A ragweld.com
dig +short CNAME www.ragweld.com
dig +short MX ragweld.com
dig +short TXT ragweld.com
```

Save the exact Netlify apex/`www` records and current nameservers in evidence.

- [ ] **Step 2: Add `ragweld.com` to Cloudflare in the in-app Browser**

Use the browser visually. Recreate all discovered DNS records before changing nameservers. The user enters any account password or OTP. Confirm Cloudflare reports the zone pending and supplies two authoritative nameservers.

- [ ] **Step 3: Change registrar nameservers and wait for delegation**

Use the signed-in registrar UI visually. Replace only the authoritative nameservers with Cloudflare's assigned pair. Temporary landing interruption is accepted. Poll `dig +short NS ragweld.com` until both assigned nameservers answer, then verify the landing apex/`www` records again.

- [ ] **Step 4: Authorize a locally managed tunnel without sharing credentials**

Run pinned cloudflared interactively inside LXC 100:

```bash
install -d -o ragweld -g ragweld -m 0700 /etc/ragweld/cloudflared
docker run --rm -it --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel login
```

Open the authorization URL in the in-app Browser and approve the `ragweld.com` zone. Do not copy the certificate through chat or command output.

- [ ] **Step 5: Create the tunnel and six DNS routes**

```bash
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel create ragweld-pve1
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 me.ragweld.com
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 auth.ragweld.com
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 grafana.ragweld.com
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 langfuse.ragweld.com
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 mlflow.ragweld.com
docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel route dns ragweld-pve1 flyte.ragweld.com
TUNNEL_ID="$(docker run --rm --user 0:0 --network host -v /etc/ragweld/cloudflared:/root/.cloudflared cloudflare/cloudflared:2026.7.2 tunnel list --name ragweld-pve1 --output json | jq -r '.[0].id')"
test -n "$TUNNEL_ID" && test "$TUNNEL_ID" != null
cp "/etc/ragweld/cloudflared/${TUNNEL_ID}.json" /etc/ragweld/cloudflared/credentials.json
chown -R ragweld:ragweld /etc/ragweld/cloudflared
chmod 0700 /etc/ragweld/cloudflared
chmod 0600 /etc/ragweld/cloudflared/*
```

- [ ] **Step 6: Write the exact local tunnel configuration**

Create `/etc/ragweld/cloudflared/config.yml` mode `0600` with the generated
tunnel UUID and the exact container-visible line
`credentials-file: /etc/cloudflared/credentials.json`, six hostname entries
each targeting `http://127.0.0.1:58000`, and a final `http_status:404` catchall.
No wildcard route is allowed. Keep the original `<UUID>.json`; the owned runtime
preflight consumes the normalized host file `credentials.json` mounted at the
container path above.

- [ ] **Step 7: Enable systemd and prove external auth denial**

```bash
systemctl enable --now ragweld.service
systemctl status ragweld.service --no-pager
```

From outside the LAN, each protected hostname must return the Authelia redirect/portal rather than its backend. Proxmox and database hostnames must not resolve.

### Task 6: Prove password login and Langfuse single sign-on

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: external tunnel and owner credential.
- Produces: one-password owner session across all protected hostnames.

- [ ] **Step 1: Perform a clean unauthenticated browser pass**

Use a clean browser context or private window. Visit every protected hostname directly. Confirm none reveals application content before authentication and every redirect target remains under `auth.ragweld.com`.

- [ ] **Step 2: Log in at Authelia**

The user enters the bootstrap password; the agent never requests, reads, or types it. Confirm the browser receives the secure `ragweld.com` session cookie and returns to `me.ragweld.com/web/`.

- [ ] **Step 3: Verify sibling-hostname SSO**

Open Grafana, MLflow, and Flyte in new tabs. They must open without another Authelia password prompt. Confirm Grafana dashboards render rather than an empty shell.

- [ ] **Step 4: Verify Langfuse OIDC**

Open Langfuse, choose `Ragweld` SSO, and confirm Authelia authorizes the same owner without a second password. Direct Langfuse username/password signup must be disabled. Confirm the initialized owner can reach the Langfuse project but no public signup path remains.

- [ ] **Step 5: Rotate the bootstrap password through a password-file workflow**

If the bootstrap plaintext was exposed in terminal output, generate a replacement password file, regenerate only the owner Argon2 hash, restart Authelia, verify the new login in a clean context, and securely remove only the old plaintext password file. Never rotate OIDC, database, or provider secrets as a side effect.

### Task 7: Seed clean public text and PDF corpora from source

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: public Hugging Face dataset and NASA public-domain PDF.
- Produces: freshly indexed `epstein-files-public` and `nasa-apollo-11` corpora with provenance manifests.

- [ ] **Step 1: Materialize 2,000 public Epstein email rows**

Run inside `/opt/ragweld` as the `ragweld` user:

```bash
uv run python -c 'from pathlib import Path; from server.synthetic.hf_epstein_emails import materialize_epstein_email_dataset; materialize_epstein_email_dataset(output_dir=Path("/srv/ragweld/corpora/epstein-files-public"), eval_output_path=Path("/srv/ragweld/corpora-metadata/epstein-files-public-eval.json"), manifest_output_path=Path("/srv/ragweld/corpora-metadata/epstein-files-public-manifest.json"), batch_size=100, limit=2000, max_eval_rows=200, replace=True)'
```

Expected: exactly 2,000 text files, one out-of-corpus manifest, and 200 or fewer evidence-graded eval rows. Record dataset ID `to-be/epstein-emails`, config `default`, split `train`, timestamp, and manifest SHA-256.

- [ ] **Step 2: Download one public-domain multimodal PDF**

```bash
install -d -o ragweld -g ragweld -m 0755 /srv/ragweld/corpora/nasa-apollo-11 /srv/ragweld/corpora-metadata
sudo -u ragweld curl -fL --retry 2 --output /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf https://ntrs.nasa.gov/archive/nasa/casi.ntrs.nasa.gov/19700008096.pdf
sha256sum /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf
```

Record NASA NTRS document ID `19700008096`, distribution `Public`, and copyright `Work of the US Gov. Public Use Permitted` in the provenance metadata.

- [ ] **Step 3: Register both corpora through the real API**

POST `/api/corpora` with exact IDs, names, and paths:

```json
{"corpus_id":"epstein-files-public","name":"Epstein Files - Public Email Sample","path":"/srv/ragweld/corpora/epstein-files-public","description":"2,000 public Hugging Face email rows, freshly materialized on pve1"}
```

```json
{"corpus_id":"nasa-apollo-11","name":"NASA Apollo 11 Mission Report","path":"/srv/ragweld/corpora/nasa-apollo-11","description":"Public-domain NASA PDF for Docling and multimodal ingestion proof"}
```

Confirm GET `/api/corpora` returns exactly the new clean corpora and no Mac/test corpus residue.

Use the real loopback API:

```bash
curl -fsS -X POST http://127.0.0.1:58012/api/corpora -H 'Content-Type: application/json' -d '{"corpus_id":"epstein-files-public","name":"Epstein Files - Public Email Sample","path":"/srv/ragweld/corpora/epstein-files-public","description":"2,000 public Hugging Face email rows, freshly materialized on pve1"}'
curl -fsS -X POST http://127.0.0.1:58012/api/corpora -H 'Content-Type: application/json' -d '{"corpus_id":"nasa-apollo-11","name":"NASA Apollo 11 Mission Report","path":"/srv/ragweld/corpora/nasa-apollo-11","description":"Public-domain NASA PDF for Docling and multimodal ingestion proof"}'
curl -fsS http://127.0.0.1:58012/api/corpora | jq
```

- [ ] **Step 4: Estimate before indexing**

POST `/api/index/estimate` for each corpus. Record file/chunk/token/cost estimates. Stop if the system proposes unexpected per-chunk cloud enrichment spend; keep local Hugging Face embeddings and use OpenRouter only for the bounded semantic/enrichment calls explicitly shown by the estimate.

```bash
curl -fsS -X POST http://127.0.0.1:58012/api/index/estimate -H 'Content-Type: application/json' -d '{"corpus_id":"epstein-files-public","repo_path":"/srv/ragweld/corpora/epstein-files-public","force_reindex":false}' | jq
curl -fsS -X POST http://127.0.0.1:58012/api/index/estimate -H 'Content-Type: application/json' -d '{"corpus_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11","force_reindex":false}' | jq
```

- [ ] **Step 5: Index the text corpus, then the PDF corpus**

POST `/api/index` with `force_reindex=false`, monitor the real stream/status endpoint until terminal completion, and require new Postgres/Qdrant/Neo4j generations. Do not start both indexes concurrently.

```bash
curl -fsS -X POST http://127.0.0.1:58012/api/index -H 'Content-Type: application/json' -d '{"corpus_id":"epstein-files-public","repo_path":"/srv/ragweld/corpora/epstein-files-public","force_reindex":false}' | jq
watch -n 5 'curl -fsS http://127.0.0.1:58012/api/index/epstein-files-public/status | jq'
curl -fsS -X POST http://127.0.0.1:58012/api/index -H 'Content-Type: application/json' -d '{"corpus_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11","force_reindex":false}' | jq
watch -n 5 'curl -fsS http://127.0.0.1:58012/api/index/nasa-apollo-11/status | jq'
```

Exit each `watch` only after `status` is `complete`, `error`, or `cancelled`.
Treat `error` and `cancelled` as blockers and inspect the persisted run events.

- [ ] **Step 6: Ask real evidence questions**

For Epstein emails, ask one question from the generated eval dataset, such as:

```text
On 2016-11-12 at 09:35, what short question did Jeffrey Epstein email Ariane de Rothschild?
```

For Apollo 11, ask:

```text
According to the Apollo 11 Mission Report, what was the mission's primary purpose and where does the report discuss lunar surface activities?
```

Require cited source paths, nonempty retrieval legs, trace metadata, and a real paid generation through LiteLLM.

### Task 8: Run full external curious-user acceptance

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`
- Modify: `docs/exec-plans/active/frontend-browser-findings-2026-08-20.md` only for new nonblocking frontend defects

**Interfaces:**
- Consumes: authenticated full platform and two indexed public corpora.
- Produces: rendered proof for every primary operator surface and an honest blocker list.

- [ ] **Step 1: Use the frontend-testing and in-app Browser skills**

Drive `https://me.ragweld.com/web/` visually. Do not use headless-only acceptance.

- [ ] **Step 2: Exercise every primary surface**

Click every top-level tab and subtab, scroll each full surface, open drawers and pop-outs, change corpus, inspect indexing history, run search, send cited Chat questions, inspect graph nodes/edges/zoom, open evaluation drilldown, inspect training controls without launching an unbudgeted run, and open Grafana/Langfuse/MLflow/Flyte.

- [ ] **Step 3: Verify browser runtime evidence**

Record console errors, failed network requests, wrong hostnames, mixed-content/CSP/frame failures, authentication loops, and empty/placeholder states. A page shell or HTTP 200 is not acceptance.

- [ ] **Step 4: Run bounded real workflows**

Run one real Promptfoo/Ragas evaluation subset, one synthetic generation with a strict item cap, and one no-op/dry-run training eligibility check. Do not start full training or a large synthetic dataset.

- [ ] **Step 5: Classify findings**

Fix only deployment blockers: auth bypass/loop, broken API proxy, missing static assets, wrong external URLs, unreadable persistent volumes, missing service, or failure of the required text/PDF workflows. Append other frontend defects to the existing browser findings file with screenshot, URL, action, expected, actual, console/network evidence, and severity.

- [ ] **Step 6: Rerun the entire external drive after blocker fixes**

Completion requires the second pass to satisfy the spec acceptance criteria, not merely the individual repaired clicks.

### Task 9: Establish PBS recovery, logical backups, and final evidence

**Files:**
- Modify: `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`

**Interfaces:**
- Consumes: accepted LXC 100.
- Produces: verified initial backup, daily retention job, logical-backup commands, isolated restore proof, and final source/runtime hashes.

- [ ] **Step 1: Create and verify the first LXC backup**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'vzdump 100 --storage pbs-beelink --mode snapshot --compress zstd; pvesm list pbs-beelink --content backup --vmid 100 | tail -n 3'
```

Expected: `TASK OK` and a new LXC 100 backup identifier.

- [ ] **Step 2: Create the daily PBS job**

First verify no job ID `ragweld-daily` exists. Then:

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 "pvesh create /cluster/backup --id ragweld-daily --node pve1 --storage pbs-beelink --vmid 100 --mode snapshot --compress zstd --schedule '03:30' --prune-backups keep-daily=7,keep-weekly=4 --notes-template 'Ragweld {{guestname}} VMID {{vmid}} on {{node}}' --enabled 1"
```

Read the job back with `pvesh get /cluster/backup` and record it.

- [ ] **Step 3: Create logical backup commands without exporting secrets**

Create a dated mode-`0700` root and load credentials without printing them:

```bash
BACKUP_DATE="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/srv/ragweld/backups/$BACKUP_DATE"
install -d -o ragweld -g ragweld -m 0700 "$BACKUP_ROOT"/{postgres,neo4j,qdrant,mlflow,langfuse}
set -a
. /etc/ragweld/runtime.env
. /etc/ragweld/langfuse.env
set +a
```

Create logical Postgres dumps:

```bash
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP_ROOT/postgres/ragweld.dump"
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml exec -T langfuse-postgres pg_dump -U postgres -d postgres -Fc > "$BACKUP_ROOT/langfuse/langfuse-postgres.dump"
```

Take one Qdrant snapshot per real collection and copy each snapshot out of the
container using the returned snapshot name:

```bash
QDRANT_CONTAINER="$(docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml ps -q qdrant)"
for COLLECTION in $(curl -fsS http://127.0.0.1:56333/collections | jq -r '.result.collections[].name'); do
  SNAPSHOT_NAME="$(curl -fsS -X POST "http://127.0.0.1:56333/collections/$COLLECTION/snapshots" | jq -r '.result.name')"
  test -n "$SNAPSHOT_NAME"
  install -d -m 0700 "$BACKUP_ROOT/qdrant/$COLLECTION"
  docker cp "$QDRANT_CONTAINER:/qdrant/storage/collections/$COLLECTION/snapshots/$SNAPSHOT_NAME" "$BACKUP_ROOT/qdrant/$COLLECTION/$SNAPSHOT_NAME"
done
```

Stop only stateful services that cannot be copied consistently while live,
archive their named volumes, and restart the exact services immediately:

```bash
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml stop neo4j mlflow langfuse langfuse-worker langfuse-clickhouse langfuse-minio
docker run --rm -v ragweld_neo4j_data:/data:ro -v "$BACKUP_ROOT/neo4j:/backup" neo4j:5.26.20-community neo4j-admin database dump neo4j --to-path=/backup --overwrite-destination=true
docker run --rm -v ragweld_mlflow_data:/source:ro -v "$BACKUP_ROOT/mlflow:/backup" alpine:3.22 tar -C /source -czf /backup/mlflow-data.tgz .
docker run --rm -v ragweld_langfuse_clickhouse_data:/source:ro -v "$BACKUP_ROOT/langfuse:/backup" alpine:3.22 tar -C /source -czf /backup/langfuse-clickhouse.tgz .
docker run --rm -v ragweld_langfuse_minio_data:/source:ro -v "$BACKUP_ROOT/langfuse:/backup" alpine:3.22 tar -C /source -czf /backup/langfuse-minio.tgz .
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml start neo4j mlflow langfuse-clickhouse langfuse-minio langfuse-worker langfuse
chmod -R go-rwx "$BACKUP_ROOT"
find "$BACKUP_ROOT" -type f ! -name SHA256SUMS -exec sha256sum {} + > "$BACKUP_ROOT/SHA256SUMS"
```

Re-run `/api/ready` and the Langfuse/MLflow health checks after restart. Add no
backup payload to Git.

After the command block succeeds, save that exact block as
`/usr/local/sbin/ragweld-logical-backup`, add `#!/usr/bin/env bash` and
`set -euo pipefail`, make it mode `0700`, and install:

```ini
# /etc/systemd/system/ragweld-logical-backup.service
[Unit]
Description=Ragweld component-level backup
After=ragweld.service
Requires=ragweld.service

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/sbin/ragweld-logical-backup
```

```ini
# /etc/systemd/system/ragweld-logical-backup.timer
[Unit]
Description=Weekly Ragweld component-level backup

[Timer]
OnCalendar=Sun *-*-* 04:30:00
Persistent=true
RandomizedDelaySec=15m
Unit=ragweld-logical-backup.service

[Install]
WantedBy=timers.target
```

Run `systemd-analyze verify` on both units, enable the timer, and record
`systemctl list-timers ragweld-logical-backup.timer`. Component-backup pruning
is not automated until measured backup growth establishes a safe retention
window; PBS still enforces seven daily and four weekly whole-LXC restore points.

- [ ] **Step 4: Prove an isolated restore**

On pve1, resolve a free ID and newest backup, restore with networking removed,
and inspect only through `pct exec`:

```bash
RESTORE_VMID="$(pvesh get /cluster/nextid)"
BACKUP_VOLUME="$(pvesm list pbs-beelink --content backup --vmid 100 | awk 'NR > 1 {print $1}' | tail -n 1)"
test -n "$RESTORE_VMID"
test -n "$BACKUP_VOLUME"
pct restore "$RESTORE_VMID" "$BACKUP_VOLUME" --storage local-lvm
pct set "$RESTORE_VMID" --delete net0
pct start "$RESTORE_VMID"
pct exec "$RESTORE_VMID" -- test -f /opt/ragweld/deploy/proxmox/ragweld.service
pct exec "$RESTORE_VMID" -- test -f /etc/ragweld/tribrid_config.json
pct exec "$RESTORE_VMID" -- docker volume ls
pct stop "$RESTORE_VMID"
```

Record successful proof and confirm source LXC 100 remains running. Then delete
only the isolated stopped restore guest:

```bash
pct destroy "$RESTORE_VMID" --purge 1
```

- [ ] **Step 5: Final Git, public-boundary, and Mac-preservation proof**

Record:

- deployed Git commit and clean one-branch/one-worktree state;
- full service inventory and image digests;
- `/api/health` and `/api/ready` sanitized payloads;
- protected/public hostname matrix;
- external browser pass and screenshots;
- corpus manifests/index generations/questions;
- Plex migration evidence reference;
- PBS identifiers and restore proof;
- Mac source/corpus hashes showing no move/delete.

- [ ] **Step 6: Commit and push final evidence**

Run repo validators for any evidence/doc changes, GitNexus detect-changes, commit only source-owned documentation, and push non-force to `origin/main`. Local and remote main must match when the deployment is declared operational.
