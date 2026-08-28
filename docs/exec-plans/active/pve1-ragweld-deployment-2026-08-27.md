# pve1 Ragweld Deployment Evidence

Date: 2026-08-28

Status: full source/Plex/LXC/runtime/recovery/corpus gates complete; authoritative DNS activation, external browser acceptance, and final guardrail/review closeout pending

## Scope

This record began as the verified source baseline for the approved permanent
Ragweld deployment to `pve1` and now tracks the predecessor Plex migration
gate. Detailed Plex/PBS/NFS evidence lives in
`docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`.

## Current source state

- Local branch/worktree canon: one local branch (`main`) and one worktree
  (`/Users/davidmontgomery/ragweld`)
- Verified application tip for the runtime/deployment surface:
  `dc42075a0f19a4f41dc28ea58d77f98985f4855a`
  (`fix(deploy): close final foundation review findings`)
- Published docs-autopilot sync tip before live preflight:
  `62cff6055c096e3209b7527b101038b9e2ee9259`
  (`docs(deploy): sync published rollout readiness`)
- Required W37 follow-up published:
  `b421d203` (`fix(deploy): keep plex media automount live`).
- Published verified NFS bridge checkpoint before migration:
  `809386f8` (`docs(homelab): record verified plex media bridge`).
- Published final Plex local-media and hardware acceptance tip:
  `ad67ad31` (`docs(homelab): close plex hardware acceptance`).
- Current deployed application tip:
  `da349c901e54966aec73c5cd63ac6cfc225e8043`
  (`chore(models): restore catalog lockstep`).
- Current local candidate adds the Linux Docling/OpenCV runtime dependency and
  fail-closed startup guard discovered by the real Apollo PDF proof; it remains
  uncommitted until the independent review and runtime rerun close.
- User-owned local dirt intentionally excluded from publication:
  `AGENTS.md`, `CLAUDE.md`, and untracked `.claude/skills/`

## Verified gates

Executed on 2026-08-28 from `/Users/davidmontgomery/ragweld`.

- `uv run python scripts/check_docs_ownership.py`: pass
- `uv run scripts/check_banned.py`: pass
- `uv run scripts/validate_types.py`: pass
- `uv run python scripts/generate_litellm_config.py --check`: pass
- `npm --prefix web run lint`: pass
- `npm --prefix web run build`: pass
- `git diff --check`: pass on the worktree at verification time

### Full backend test gate

- Unsandboxed `UV_CACHE_DIR=/Users/davidmontgomery/ragweld/.uv-cache uv run pytest -q`
  completed green on 2026-08-28:
  `1219 passed, 98 skipped, 7 warnings` in `255.43s`
- The current full-gate count is higher than the earlier pre-closeout run
  because the W34 observability regression and the stale-corpus config-readiness
  regression each gained a permanent test.
- The W37 tree was then reverified from scratch:
  - deployment contract: `34 passed` in `17.66s`
  - full suite: `1219 passed, 98 skipped, 7 warnings` in `256.90s`
  - docs ownership, banned patterns, generated types, LiteLLM lockstep, and
    `git diff --check`: pass

### External adversarial review of record

- Paid OpenRouter GLM review of record:
  `.superpowers/sdd/2026-08-27-proxmox-runtime-foundation/glm-review-0b106b28..9d834fcf.md`
  with verdict `REFUTED` on the pre-closeout candidate.
- Actioned outcomes now closed in committed source:
  - `6a6567a3`: W34 Langfuse public-link fix
  - `90c621d9`: stale-corpus config-readiness `500` -> truthful degraded `200`
  - `dc42075a`: W36 deployment-script/test hygiene wave plus rollout-plan rewrite
- The two one-shot `None` artifacts were renamed `*-failed.md` and are not
  cited as review evidence.
- Final-range paid GLM rerun:
  `.superpowers/sdd/2026-08-27-proxmox-runtime-foundation/glm-rereview-9d834fcf..dc42075a.md`
  with sibling `.jsonl` trace, `35` tool rounds, verdict `PASS`.
- The harness initially stopped at its own obsolete 24-round cap. Its preserved
  trace was rebuilt exactly, a regression test proved continuation at round 25,
  and the same review continued without a total-round cutoff until the model
  returned its report. The model receives up to one hour per response.
- The rerun found no P1 source defect, secret leak, auth bypass, or fake-green
  test in the final fix range. Its two P2 gate observations are closed by the
  final full-suite evidence above and by this final-range rerun itself.

Reason for the unsandboxed rerun: the managed sandbox blocked localhost test
servers, local database sockets, and Chromium launch/cleanup paths needed by
several real tests. The repo-local result above is the authoritative source
gate.

### Post-push GitNexus scope refresh

- Forced re-index completed on 2026-08-28:
  `node .gitnexus/run.cjs analyze --force`
- Fresh compare against `origin/main` after the push:
  `node .gitnexus/run.cjs detect-changes --scope compare --base-ref origin/main --repo ragweld --limit 300`
  -> `2 files, 14 symbols, 0 affected execution flows, risk low`
- The remaining diff is only the intentionally local `AGENTS.md` / `CLAUDE.md`
  GitNexus instruction block. No product/runtime source remains unpublished.

## Browser evidence

### Verified

- Real Playwright pass on
  `web/tests/e2e/exhaustive/public_link_fields.spec.ts` against the live local
  app (`PLAYWRIGHT_WEB_BASE_URL=http://127.0.0.1:55173/web`): `1 passed`
- Real Playwright pass on
  `web/tests/e2e/exhaustive/admin_config_center_mobile.spec.ts` against the
  isolated current-code lane (`PLAYWRIGHT_WEB_BASE_URL=http://127.0.0.1:55174/web`,
  frontend `55174` -> backend `58013`): `1 passed` in `5.7s`
- The same real browser spec verifies both dedicated public-link hints:
  - Retrieval hint text:
    `Browser links use this; ingestion/tracking uses the local URL.`
  - Training hint text:
    `Browser links use this; ingestion/tracking uses the local URL.`
  - Computed font size for both hints: `12px`

### Runtime drift note

- The long-lived live host lane (`55173` -> `58012`) is not the current source
  tip. Its backend is a manually launched non-reloading uvicorn process
  (`server.main:app --host 127.0.0.1 --port 58012`) that still serves the
  pre-`90c621d9` stale-corpus bug.
- On that stale lane, a browser session scoped to
  `pytest_resume_mlflow_0f3d3c67` reproduces:
  - `GET /api/config/readiness?corpus_id=pytest_resume_mlflow_0f3d3c67` -> `500`
  - `GET /api/index/pytest_resume_mlflow_0f3d3c67/stats` -> `503`
- On the isolated current-code lane, the same scoped readiness request returns a
  truthful degraded `200` and the Admin mobile spec passes. The browser failure
  on `58012` is therefore runtime drift, not current source truth.

### Admin/Basic browser note

- The earlier Admin/Basic failure is no longer treated as an unexplained UI
  residual. Watchdog `W33` was traced to the stale live lane's scoped
  config-readiness `500`, and `90c621d9` fixes the current source tree to
  return a truthful degraded `200` instead.
- The passing isolated-lane mobile spec above is the current-source proof.
  Any future update-loop report on a healthy readiness response is a new
  product bug, not an unresolved Proxmox foundation blocker.

## Deployment-shape facts now verified in source

- The guest runtime uses `SERVER_HOST=0.0.0.0`; the LXC firewall is the
  boundary.
- `deploy/proxmox/render_config.py` sets
  `training.ragweld_agent_flyte_callback_base_url=http://172.17.0.1:58012`.
- `deploy/proxmox/start-runtime.sh` fails closed unless Docker's default bridge
  gateway matches that rendered callback host.
- `deploy/proxmox/docker-compose.yml` runs Authelia, Caddy, and cloudflared as
  deployment-owned Compose services, not ad hoc host daemons.
- The rollout plan corrections for `W4`, `W5`, `W6`, `W7`, `W17`, and `W20`
  are recorded in the active rollout plan and watchdog before any remote step.

## Task 1 Step 3 — live pve1 preflight

Read-only verification on 2026-08-28 established:

- cluster `homelabz` has three votes, three members, and quorum `Yes`;
- pve1 runs PVE `9.2.2` on kernel `7.0.2-6-pve`;
- pve1 has 31 GiB RAM total and 25 GiB available before LXC creation;
- HAOS VM 120 is `running` on pve1 and uses approximately 4.2 GiB;
- Plex LXC 4214 is `running` on node `pve` (`.173`), not pve1;
- VMID 100 has no cluster config and is free;
- pve1 `local-lvm` is active with `824476654 KiB` available;
- `pbs-beelink` is active with `1729551840 KiB` available;
- `/dev/dri/card0` and `/dev/dri/renderD128` are present;
- `/srv/media` is not mounted on pve1; `nfs-server` is inactive; and
- the pve1 resource check therefore satisfies the approved 24 GiB LXC
  allocation and 300 GiB thin-root preconditions.

The first location formatter attempted to use `jq`, which is not installed on
pve1. No mutation depended on it. A Python-only rerun asserted VM 120 on
`pve1` and LXC 4214 on `pve`, both `running`.

Rollback owner for LXC creation: the controller executing this plan. If later
bootstrap fails, leave LXC 100 stopped for inspection; do not delete it or
change HAOS/Plex as an attempted recovery.

## Task 2 — LXC 100 provisioning evidence

- Cached and checksum-verified the exact template
  `debian-13-standard_13.6-1_amd64.tar.zst` on pve1.
- Created privileged LXC 100 stopped, then attached only
  `/dev/dri/renderD128` and `/dev/dri/card0`. Its config has no Plex media,
  Proxmox filesystem, or host-control socket mount.
- Running guest proof:
  - 16 CPUs;
  - 24 GiB RAM and 8 GiB swap;
  - 295 GiB usable root with 279 GiB initially available;
  - both DRM devices at major `226`, minors `0` and `128`;
  - DHCP address `192.168.68.225/24`, default route `192.168.68.1`; and
  - locked deployment commit
    `3abb80dfe65bb1eb21ccfd68fba664c7bb5f5b25` at
    `/root/ragweld-deployment-commit` mode `0600`, while `/etc/ragweld`
    remains absent for bootstrap ownership.

### SSH and firewall acceptance

- Installed the exact key-only SSH policy. Effective values are
  `passwordauthentication no`, `kbdinteractiveauthentication no`,
  `pubkeyauthentication yes`, and `permitrootlogin without-password`.
- Debian's socket-activated SSH failed on SIGHUP reload because systemd still
  owned port 22 and sshd could not re-bind it. A controlled service restart
  recreated `/run/sshd`, re-adopted the socket, and left key-only direct SSH
  green from the Mac.
- pve1's cluster firewall is globally `disabled/running`. Enabling it for this
  guest would create unnecessary cluster-wide blast radius, so the verified
  `/etc/pve/firewall/100.fw` is dormant defense-in-depth, not the claimed
  boundary.
- LXC 100 therefore runs its own nftables input/forward guard at priority
  `-200`, before Docker filter chains. It allows loopback,
  established/related, router DHCP, LAN ICMP, LAN SSH, and IPv6
  neighbor/router discovery; it drops other new `eth0` input and forward
  traffic.
- Two temporary Python HTTP services listened on `0.0.0.0:58000` and
  `0.0.0.0:58012`. Each returned `200` through guest loopback; direct Mac
  requests timed out with curl exit `28`, while direct key-only SSH still
  succeeded. Both transient services were stopped and the final listener list
  contained only SSH and local loopback SMTP.

Task 2 rollback is `pct stop 100`. Do not delete the LXC on a later bootstrap
failure; leave it stopped with this evidence for inspection.

## Task 3 — runtime bootstrap evidence

### Base runtime and immutable source

- Installed the approved Debian prerequisites, including `lsof`, VAAPI
  drivers/tools, build tooling, and `fuse-overlayfs`.
- Installed Docker Engine `29.7.2` and Compose `5.5.0` from Docker's official
  Debian repository. The guest uses cgroup v2, a local Unix socket, and the
  `overlayfs` storage driver.
- Re-ran the live firewall proof after Docker installed its own rules. A
  Docker-published listener on 58000 and host listener on 58012 were both
  reachable internally and timed out from the Mac, while SSH remained green.
  Both probes were removed.
- Installed Node `22.23.2`, npm `10.9.8`, and uv `0.12.7`.
- Refreshed the immutable lock at the final pre-clone checkpoint, then cloned
  one `main` branch at
  `2f1274762602e7c0bb5e780e177dbc7ae216d84e`. The service-owned checkout is
  clean and matches its root-only lock. No Git safe-directory exception was
  added.

### Persistent GPU ownership

- The initial Proxmox `dev0`/`dev1` entries created `root:root` devices despite
  mode `0660`; render/video group membership alone did not grant access.
- Resolved guest GIDs render `992` and video `44`, added them to the persistent
  Proxmox device entries, and rebooted LXC 100.
- After reboot, the devices were `root:render` and `root:video`; SSH,
  nftables, Docker, and `.225` all returned. The `ragweld` user can read/write
  both DRM devices and access Docker without root.

### Dependencies, build, and clean secrets

- `uv sync --frozen` selected managed CPython `3.12.14` and installed the
  locked 246-package environment. The current lock includes CUDA/PyTorch
  wheels even though this Intel runtime does not use CUDA; the immutable lock
  was not altered during deployment. The venv occupies about 8.0 GiB.
- `npm ci` installed 1,287 packages; the production Vite build completed from
  3,838 modules and produced `web/dist/index.html`. npm reported 17 audit
  findings (1 low, 5 moderate, 11 high) and the build reported large-chunk
  warnings. These are recorded honestly; no unreviewed dependency mutation was
  made during deployment.
- Generated a new 48-hex-character high-entropy owner passphrase and used it
  to bootstrap entirely new Postgres, Neo4j, LiteLLM, Grafana, Langfuse,
  Authelia, and OIDC secrets on-box. All secret files are mode `0600`, owned by
  `ragweld:ragweld`; no Mac database/auth secret or old platform state was
  imported.
- Installed exactly these approved provider keys by name, once in each target
  environment, without logging values: `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`, `VOYAGE_API_KEY`, `COHERE_API_KEY`, `JINA_API_KEY`.
  All provider staging files were removed.

### Production config and service ownership

- Rendered `/etc/ragweld/tribrid_config.json` mode `0600` while preserving the
  source hash
  `e75fe7e128f4f34b4205491dd47309b3edf6eecbf0e4a4b4a05f99fe785b89df`.
- Verified production mode, `openai.gpt-5.6-terra` for all seven production
  generation/judge defaults, provider embeddings,
  explicit vLLM disablement, public Grafana/Langfuse/MLflow/Flyte URLs, and
  Flyte callback `http://172.17.0.1:58012`.
- Installed `ragweld.service` but left it disabled and inactive. Task 4 owns
  the tunnel-skipped internal start.

Task 3 rollback remains `pct stop 100`; source, config, and fresh secrets stay
on the stopped LXC for inspection.

## Tasks 4-7 — full runtime, recovery, tunnel, and clean-corpus evidence

### Runtime and recovery

- The complete production service is enabled and running in LXC 100. Authelia,
  Flyte, LiteLLM, Postgres, Qdrant, Neo4j, MLflow, Langfuse, Grafana, and the
  remaining observability services passed their real readiness checks.
- Flyte's nested k3s reached `Ready` with container-only
  `/dev/null:/dev/kmsg`; pve1's real kernel log device is not exposed.
- Authelia's pinned image validates its configuration before Compose startup.
- Paid replacement proof through LiteLLM used `openai.gpt-5.6-terra`, returned
  `OK`, consumed 16 tokens, cost `$0.000082`, and used no fallback.
- PBS snapshot `pbs-beelink:backup/ct/100/2026-08-28T17:33:31Z` completed, and
  an offline restore to temporary VMID 900 verified the exact deployment
  marker, protected config/tunnel files, source checkout, frontend build, and
  Docker state. The duplicate was never started and VMID 900 was deleted after
  the proof.

### Cloudflare and authoritative-DNS state

- Cloudflare tunnel `ff9d38b6-5f51-45b5-a9ce-380ded0b886a` is healthy with
  four registered connections and exact routes for `me`, `auth`, `grafana`,
  `langfuse`, `mlflow`, and `flyte`.
- The logged-in Netlify CLI/API, not Cloudflare's incomplete quick scan,
  supplied the authoritative old-zone inventory. Cloudflare now also carries
  `deepseek-mcp` -> `ragweld.netlify.app` and `bird-data` -> `169.197.22.5`,
  both DNS-only, in addition to the apex/`www` landing records.
- Assigned Cloudflare nameservers are `chance.ns.cloudflare.com` and
  `kenia.ns.cloudflare.com`. The zone remains pending because the
  Netlify-registered domain still uses `dns1-4.p04.nsone.net`; the in-app
  browser is waiting at the user-owned GitHub sign-in handoff. No credential or
  OTP was handled by the agent.

### Clean public corpora and real cited chat

- Registry started empty and now contains exactly `epstein-files-public` and
  `nasa-apollo-11`; no Mac/test corpus or old database/index was imported.
- Public email corpus:
  - 2,000 files, 200 eval rows, 3,126 promoted chunks, 346,731 tokens;
  - local Hugging Face `BAAI/bge-small-en-v1.5` embeddings, `$0.00` index cost;
  - Qdrant points/indexed vectors `3126/3126` and Neo4j documents/chunks
    `2000/3126`.
- Apollo corpus:
  - NASA document `19700008096`, 359 pages, 15,973,944 bytes, SHA-256
    `3314d99654ebb2ac3e3ef0ab70a84be9519a5f071cf1362118b2b20a6f161dea`;
  - current NTRS API asset verified as PDF; the old archive URL returned HTML
    and was rejected;
  - Docling produced 601,387 markdown characters, then promoted 1,002 chunks /
    182,260 tokens with Qdrant 1,002 points and Neo4j one document / 1,002
    chunks.
- The first Apollo attempt exposed missing Linux OpenCV libraries
  (`libGL.so.1`, then `libgthread-2.0.so.0`/`libglib-2.0.so.0`). The candidate
  pins the Debian 13 container base, installs `libgl1` plus
  `libglib2.0-0t64`, and makes Proxmox startup fail closed on `import cv2`.
  The direct 359-page conversion and the second API index both completed.
- Real GPT-5.6 Terra chat proof:
  - email question returned the cited answer `cam you speak now?`, 8 vector + 8
    sparse results, authoritative 980 tokens and `$0.00234`;
  - Apollo question returned the mission purpose and Section 11 location with
    PDF line citations, 10 vector + 10 sparse + 10 graph results before fusion,
    authoritative 1,591 tokens and `$0.004584`;
  - both traces include canonical trace IDs and Grafana, Tempo, and Langfuse
    links. `ChatResponse.tokens_used` incorrectly returned zero while the trace
    held authoritative usage. The candidate now propagates the gateway usage
    through both chat transports using the canonical trace-cost parser; a real
    local LiteLLM-compatible gateway regression covers snake_case and camelCase
    usage payloads.
  - published commit `c2a8e83b7009b661d2c2e109cea12f42cfb48ff1`
    was fast-forwarded into the clean LXC checkout and restarted through the
    systemd lifecycle. A post-deploy paid email query returned the cited answer
    `cam you speak now?` with ten sources. `ChatResponse.tokens_used`, the
    `chat.response` trace event, and the authoritative trace cost summary all
    agreed on 1,110 tokens for run
    `c3008395-1a4c-4ba9-9574-44ba0db44edf`; provider cost was `$0.003154`.

### Post-corpus capacity measurement (W75)

- Guest `/`: 14% used, 242 GB free.
- `vm-100-disk-0`: 15.67% Data.
- `pve/data`: 6.94% Data / 0.46% Meta.
- The first corpus moved thin-pool Data% by only 0.02 percentage points.
  Capacity is not a blocker.
- Independent GPT-5.6 review rejected the injected 10% autoextend: it would
  request about 79.4 GiB against only 16.00 GiB of VG free space. The tested
  candidate uses a pve/data-only LVM metadata profile at 80% / 1% and a
  host-level five-minute systemd guard for deduplicated warning, critical,
  recovery, and probe-failure email/journal transitions. Host installation and
  forced non-destructive live verification remain before closeout.

### Current verification candidate

- docs ownership, banned-pattern, generated-type, LiteLLM 371-alias lockstep,
  and `git diff --check` gates: pass;
- latest proven staged-source full backend suite before the final review fix
  wave: `1235 passed, 98 skipped, 7 warnings`;
- that staged count is now superseded because the final review fix wave added
  new Docling/capacity regressions and source changes;
- final full-suite rerun and exact source hash are still required before
  commit, publish, or deploy. The controller will record the post-fix count and
  published hash after the closeout rerun.

## Ready / not ready

Ready:

- local source verification
- direct-main publication complete
- external adversarial review of record, with its actionable findings closed in
  committed source
- rollout planning from the corrected pve1 design
- Plex Tasks 1-3 complete: fresh PBS backups, verified NFSv4 bridge, offline
  root-disk migration to `.173`, guest-side NFS proof, and reboot acceptance
- W37-W45 incorporated into the executable plan and live state
- physical media returned to `.173`, full filesystem check and journal replay
  complete, local-mount reboot proof green
- signed-in original playback and forced Intel VAAPI hardware-transcode proof
  complete
- pve1 Task 1 live capacity/VMID/GPU/PBS preflight green
- LXC 100 provisioned and reachable at `192.168.68.225` with its isolated
  ingress boundary proved against live listeners
- Task 3 runtime bootstrap, immutable source/build, clean secrets, provider
  allowlist, production config, and persistent non-root GPU access complete
- Task 7 clean public-corpus materialization, sequential text/PDF indexing,
  cited paid chat, Docling runtime correction, and live token-accounting proof
  complete

Not yet done:

- Netlify registrar nameserver switch and Cloudflare zone activation
- signed-in external browser/SSO acceptance across the protected workbench and
  companion UIs
- W75 thin-pool/guest-volume alert and autoextend guardrails
- final independent GPT-5.6 plus paid GLM adversarial closeout and publication
