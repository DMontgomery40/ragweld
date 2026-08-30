# pve1 Ragweld Deployment Evidence

Date: 2026-08-28

Status: Linux runtime, capacity, logical backup, Docling responsiveness, Mac
evacuation, and temporary public ingress complete; `ragweld.com` registrar
activation and the final post-restart signed-in browser confirmation remain
pending

## Scope

This record began as the verified source baseline for the approved permanent
Ragweld deployment to `pve1` and now tracks the predecessor Plex migration
gate. Detailed Plex/PBS/NFS evidence lives in
`docs/exec-plans/active/plex-return-to-pve-2026-08-27.md`.

## Final execution addendum — 2026-08-28

This section is the current source of truth. Later user instructions explicitly
superseded the original copy-only Mac rule: all Ragweld ignored/runtime data was
to be preserved on Linux and then removed from the Mac. No private data was
published to Git.

### Published and deployed source

- W75/W80/W81 source, tests, and deployment artifacts were published in
  `0458f5058e08222f80ef07ca30eda93a625e36bf`.
- Tracked handoff/docs/agent material was published through
  `3004aad9cfb80f2c15ef37a3ed49b5c8f9632fe5`.
- The temporary `ragweld.dtmont.com` Caddy/Authelia contract was published in
  `f60c440ee0eca63387fa5bd14d82d389726322b8`.
- The concurrent docs-autopilot hardening lane was stopped, verified, and
  published in `de6085d36d25194fa089c63bdd3befd15794509f`.
- The first final execution evidence update was published in
  `f7ba79bd1ac844172141f46c917c173ad1b7305e`.
- The ultimate post-restart archive evidence was published in
  `44a42e2bdb4b4dce14d2cf87e96f495db1a1ef2f`.
- Production chat budget and persistence fixes were published in
  `3cedcfa5270a9fdf459bfe289429644c91882953` and
  `c5989bfc5952f9fe99c67888ae24d59941804981`.
- Before this evidence-only update, local `main`, `origin/main`, LXC100
  `/opt/ragweld`, and `/etc/ragweld/deployment-commit` all matched `c5989bfc`.
- The Mac then had one branch (`main`), one worktree, only the two owned
  evidence files modified, no ignored changes, no Ragweld Vite/backend/docs
  worker, and no `colima-ragweld` profile or Docker context.

### Source verification and review

- Exact pre-teardown source gate: `1241 passed, 98 skipped, 7 warnings` in
  `253.15s`; docs ownership, banned patterns, generated types, LiteLLM
  371-alias lockstep, frontend lint/build, and `git diff --check` passed.
- Exact staged synthetic source candidate
  `0557794a033f47416d32afc9dc69c5565e429d81` received an independent GPT-5.6
  verdict `ACCEPTED` with no actionable P1/P2.
- The later docs-autopilot lane passed its two focused files: `25 passed` in
  `10.90s`. Both plan-generation smokes quoted all 92 docs pages; the normal
  plan included 138 diffs and reported 262 omitted for budget, while bootstrap
  included 114 and reported 286 omitted. The repository
  `OPENROUTER_API_KEY` secret was installed before publication.
- GitNexus classified that docs-autopilot lane HIGH because 49 symbols affect
  10 docs-CI flows. It does not touch the serving runtime. Patch paths remain
  allowlisted, incomplete provider responses fail closed, bad context is
  rejected, and `git apply --recount --index` is covered by a real repository
  regression.
- After Mac runtime removal, the full suite honestly reports
  `1229 passed, 105 skipped, 15 failed`: four index-replay tests require local
  Postgres and eleven Compose/runtime-contract tests require the deliberately
  removed local Docker/Colima/env topology. The focused changed lane remains
  green; local infrastructure was not recreated to manufacture a full-suite
  green result.
- The user explicitly ordered the active paid generation/test and speculative
  review stopped. Those processes were terminated. A resumed external Claude
  session later restarted its docs generator, read-only reviewer, and full
  pytest; the owning session and all three process groups were stopped again,
  their regenerated ignored state was archived on Linux, and no paid GLM rerun
  was accepted as new final evidence. Earlier paid reviews remain historical.
- Chat-budget TDD proved the production renderer contract red at 512 and green
  at 4096. The full Proxmox contract reached 31 pass / 17 skip; its sole
  remaining live-host-only failure is expected because Compose reads the real
  optional `/etc/ragweld/langfuse.env`, while the source contract assumes that
  secret file is absent. The full config-reality file is 9/9 green, including
  the 1024/4096/16384 preservation matrix; banned patterns, generated types,
  and the 371-alias LiteLLM lockstep checks pass.

### Capacity and recovery

- pve1 `pve/data` has the scoped `ragweld-thinpool` profile attached with
  `thin_pool_autoextend_threshold=80`, `thin_pool_autoextend_percent=1`, and
  `seg_monitor=monitored`.
- Final audit measured `9.50%` data, `0.55%` metadata, and LXC100 root at
  `56G/295G` (`20%`). The five-minute capacity timer is enabled/active, its
  latest service result is success, and all production state files are `ok`.
- The non-destructive fake-delivery matrix proved warn, unchanged dedupe,
  critical, recovery, guest-probe failure, dedupe, and recovery transitions;
  the final normal live run was clean.
- Logical backup `/srv/ragweld/backups/20260828T223712Z` is root-only, about
  `138M`, and contains verified Postgres, Neo4j, MLflow, Langfuse
  Postgres/ClickHouse/MinIO, and both Qdrant collection artifacts. Every entry
  in `SHA256SUMS` passed, no `.incomplete-*` directory remains, and both live
  Qdrant snapshot inventories returned zero residue.
- `ragweld-logical-backup.timer` is enabled/active for the weekly run. The
  existing enabled `backup-pbs-cluster` job still covers VMID100 on
  `pbs-beelink`; no PBS job was created or changed during logical-backup work.

### Real Docling responsiveness proof

- Temporary corpus `acceptance-docling-20260828` contained the first two real
  pages of the Apollo 11 mission report. Estimate: one file, 62,260 bytes,
  about 15,565 tokens / 35 chunks, local Hugging Face embeddings, $0 external
  cost.
- The counted force-reindex run was
  `20260828T230708_90174b3bb8`, from `23:07:08Z` to `23:07:15Z`. It completed
  with one file, eight chunks, 3,131 tokens, model
  `BAAI/bge-small-en-v1.5`, 384 dimensions, and no error.
- While Docling reported
  `current_file=A11_MissionReport_pages_1_2.pdf`, `/api/health` remained HTTP
  200 at 1.9–2.5 ms and `/api/corpora` remained HTTP 200 at 2.2–6.5 ms.
- The real corpus DELETE API returned `{"ok":true}`. The corpus now returns
  404, zero matching Qdrant collections remain, the exact temp PDF/directory
  were removed, and readiness is 200. The user-managed registry contains only
  `nasa-apollo-11` and `epstein-files-public`; `recall_default` is the separate
  product-owned chat-memory corpus. Empty per-corpus lineage locks are retained
  intentionally by the lock design to prevent inode-swap races.
- Completed manifests from the three temporary Docling proof corpora were moved
  out of active `data/index_runs` into root-private
  `/srv/ragweld/acceptance-evidence/docling-run-manifests`; archive SHA-256 is
  `428980379efd12481dbf791fd698af5ad852ff5b31370b685fed81e3f585312e`
  and its sidecar passes in place.

### Mac data evacuation and cleanup

All archives and extracted trees are root-private under
`/srv/ragweld/mac-archive/2026-08-28-from-mac`. Every archive passed format and
SHA verification; all sidecars now use the deployed basename and pass
`sha256sum -c` in place.

- initial ignored tree: `d0d9db26fab0140e3facb5acfcf2b59a1dc8826c7ba535b71c733625fe5eb0d7`
- post-clean delta: `39aa1e245dafd85ab9b2f595261b48cc2808082b5d787926e6f680785236781d`
- final delta: `ec6f6aefcbcf9a83e23ef21b74b3016e30fc0d27bae8e71cc5d3ded8f1905aaf`
- stopped `colima-ragweld` profile:
  `d898b297548b86463bd28d3a6f81ca2a51b5cb73e935b2b035931c9ad6742729`
- late regenerated runtime/test delta (37 exact ignored paths, 53,498 archive
  entries, 1.5G extracted):
  `b8c0f4209942c34de46ca7bc2f9f9a80fd5cca0e7646404f409ebd78315f01b2`
- ultimate post-restart delta (35 exact ignored paths, 53,483 archive entries,
  1,493,829,632 uncompressed bytes, 370,555,696 compressed bytes):
  `0b0688462f828a0a20175173828f600ee2ab19858bccbc0cfc3cc91f2d3e2ba5`
- post-validation Python cache delta (one exact ignored path, two archive
  entries, 12,288 uncompressed bytes, 5,677 compressed bytes):
  `aec05f69e0db94d0dbfc8a5972f115afb608c39c06cc356edd68b9701a546f36`
- detached synthetic review worktree bundle:
  `561c8bf5948c16b911c8478d28e3d75db16b6b7c5dc202350187eca21702355c`
  preserving unique commit `0abf6cf6d9075a8b13219db16704daef7d5340f6`

The clean detached review worktree was removed only after the complete-history
bundle verified on Linux. The original owning Claude session, its OpenRouter
docs generator, its read-only Codex reviewer, and the stale Vite server were
stopped before the late archive was created. When a resumed Claude session
later restarted generator/reviewer/test groups, those were stopped too; the
ultimate delta above was verified and extracted root-private on Linux before
the exact ignored paths were removed from the Mac again.

### Live chat fix-forward

- A signed-in curious-user query, `tell me how big was the spaceship`, selected
  `z-ai.glm-5.3-flash` against `nasa-apollo-11` and returned the real
  `generation_unavailable` card. Correlation
  `10c63eb3-d5d6-4a21-805a-3fbf8690d4c5` and trace
  `77726bb7b09119194d8253aa889e2661` proved retrieval succeeded and the gateway
  returned HTTP 200, but the effective scoped budget was still 512.
- A sanitized direct gateway probe showed the model emitting standard
  `delta.reasoning` until `finish_reason=length`; 122 of a 128-token probe were
  reasoning tokens before partial answer content. The failure was not DNS,
  authentication, retrieval, a missing alias, or a missing provider key.
- `3cedcfa5` made the Proxmox production chat allowance 4096. The first retest
  still failed because `server.services.config_store._upgrade_raw_config`
  silently rewrote stored 4096 values to 512. `c5989bfc` removed only that stale
  migration and added a 1024/4096/16384 preservation matrix. GitNexus marked the
  loader CRITICAL by reachability (89 dependents / 79 flows), while staged
  detection for the literal migration change reported three symbols, zero
  affected processes, and low risk.
- The Apollo scoped config was backed up root-private, patched to 4096 through
  the real config API, and survived a full service/container restart at 4096.
  The restart first failed closed because the one-off atomic updater created a
  root-owned config; ownership was restored to required UID/GID 1000 and the
  subsequent startup/readiness gates passed.
- Exact live post-restart run `edf49d16-f8af-47a6-a0bc-e7882cac7554` used GLM
  5.3 Flash and 13 grounded sources, returned a complete Apollo answer,
  reported 2,923 tokens, `llm_used=true`, `llm_error=null`, and zero SSE error
  events.

### Public ingress

- Netlify support has the request to move `ragweld.com` from its current NS1
  nameservers to Cloudflare's `chance.ns.cloudflare.com` and
  `kenia.ns.cloudflare.com`; the Cloudflare zone remains pending until Netlify
  acts.
- Temporary records `ragweld.dtmont.com` and
  `ragweld-auth.dtmont.com` are proxied Tunnel records to `ragweld-pve1`.
  Google DNS-over-HTTPS returned both A and AAAA answers for each hostname.
- External HTTPS reaches the tunnel: the app returns 302 to the exact temporary
  Authelia host, and the auth host returns 200. The in-app Browser rendered the
  real Authelia login page. No auth bypass or loop was observed.
- Two accidental nested records created by the zone-scoped cloudflared CLI
  were immediately deleted before the correct `dtmont.com` records were added.
- The user completed sign-in once and exposed the chat failure above. The
  fix-forward restart invalidated that browser session, so final visual
  post-fix confirmation awaits user reauthentication; passwords/OTPs are never
  handled by the agent. Companion `*.ragweld.com` surfaces remain pending the
  Netlify registrar change.

### Authelia session persistence — 2026-08-30

- Authelia sessions persist in `authelia-redis` (AOF under
  `/etc/ragweld/authelia/redis`) since 2026-08-30; restarts no longer log
  operators out, and `remember_me` is 30d with a 12h expiration and 4h
  inactivity window. Before this the `session:` block declared only `cookies:`,
  so Authelia kept sessions in process memory and every
  `stop-runtime.sh`/`start-runtime.sh` cycle invalidated the operator's browser
  session — the cause of the lost session recorded under Public ingress above.
- `authelia-redis` publishes no ports and is reachable only by service name on
  the compose project network. It runs as the runtime uid/gid that owns
  `/etc/ragweld` (`RAGWELD_RUNTIME_UID`/`RAGWELD_RUNTIME_GID`, exported by the
  lifecycle scripts) because the redis entrypoint would otherwise chown the
  bind mount to uid 999 and break the owner-only preflight.
- `start-runtime.sh` now preflights `/etc/ragweld/authelia/redis` with the same
  owner-only check as `/etc/ragweld/authelia/state`, so a missing session store
  fails the whole runtime loudly before any compose action. On an already
  bootstrapped host the directory must be created once by hand:
  `install -d -o ragweld -g ragweld -m 0700 /etc/ragweld/authelia/redis`.

## Historical source state before the final execution addendum

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

### Final verification classification

- The superseding exact full source gate is `1241 passed, 98 skipped, 7
  warnings`; the later changed docs-autopilot lane is `25 passed`.
- Current standard validators are green: docs ownership, banned patterns,
  generated types, LiteLLM 371-alias lockstep, and `git diff --check`.
- The current Mac-wide suite is intentionally dependency-incomplete after the
  authorized teardown: `1229 passed, 105 skipped, 15 failed` for missing local
  Postgres/Docker/Colima. That is recorded as topology evidence, not repaired by
  recreating the retired Mac runtime.

## Ready / not ready

Ready:

- direct-main publication and exact-hash LXC deployment
- exact full source gate before Mac teardown plus focused green verification of
  the later docs-autopilot lane
- independent GPT-5.6 source review with no actionable P1/P2
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
- pve1 80/1 thin-pool profile, five-minute capacity guard, and full synthetic
  transition matrix complete
- logical backup and weekly timer complete with all checksums and zero snapshot
  residue
- real Docling conversion proved nonblocking and its temporary corpus was
  removed through the product API
- every Mac ignored/runtime state and the unique detached review commit is
  preserved root-private on Linux; Mac source/runtime state is clean
- `ragweld.dtmont.com` and `ragweld-auth.dtmont.com` resolve and reach the live
  tunnel/Caddy/Authelia chain

Not yet done:

- Netlify support must complete the `ragweld.com` registrar nameserver switch
  before the original Cloudflare zone activates
- signed-in external browser/SSO acceptance across the protected workbench and
  companion UIs
- the full Mac suite cannot be green without recreating the explicitly retired
  local Postgres/Docker/Colima topology
- no new paid GLM closeout was run after the user ordered the active generator,
  test, and speculative review stopped
