# pve1 Ragweld Deployment Evidence

Date: 2026-08-28

Status: source gate verified locally; Proxmox mutation not started

## Scope

This record captures the verified source baseline for the approved permanent
Ragweld deployment to `pve1` before any remote provisioning or data copy. It is
not a deployment log yet; it is the pre-deployment source-gate record the
rollout plan expects to exist before the first Proxmox mutation.

## Current source state

- Local branch/worktree canon: one local branch (`main`) and one worktree
  (`/Users/davidmontgomery/ragweld`)
- Verified application tip before the docs closeout publication:
  `9d834fcf76d5f3de354b66470393323e170e9b85`
  (`fix(web): keep public link controls readable and reachable`)
- Remote baseline before publication: `origin/main`
  `0b106b28825a4a9bb88c171660330557c2432ee3`
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
  `1217 passed, 97 skipped, 7 warnings` in `238.47s`
- Focused unsandboxed rerun of the families that failed inside the managed
  sandbox proved the earlier reds were harness-induced, not product regressions:
  `80 passed, 1 skipped` in `101.05s`

Reason for the unsandboxed rerun: the managed sandbox blocked localhost test
servers and Chromium launch/cleanup paths needed by several real tests. The
repo-local result above is the authoritative source gate.

## Browser evidence

### Verified

- Real Playwright pass on
  `web/tests/e2e/exhaustive/public_link_fields.spec.ts` against the live local
  app (`PLAYWRIGHT_WEB_BASE_URL=http://127.0.0.1:55173/web`): `1 passed`
- Live in-app browser verification confirmed both dedicated public-link hints:
  - Retrieval hint text:
    `Browser links use this; ingestion/tracking uses the local URL.`
  - Training hint text:
    `Browser links use this; ingestion/tracking uses the local URL.`
  - Computed font size for both hints: `12px`

### Residual frontend note

- Watchdog `W33` records an intermittent Admin/Basic browser issue observed
  during the same review window: repeated `Maximum update depth exceeded`
  console errors and one transient config-control-plane load failure.
- Fresh manual mobile re-open of `/web/admin?subtab=basic` rendered
  `Configuration Center` successfully, and the backend log showed repeated
  `200 OK` responses for `/api/config/registry` and `/api/config/readiness`
  during the later checks.
- Because the issue was not yet reduced to a proved root cause, it was logged
  instead of being folded into the Proxmox foundation closeout.

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

## Ready / not ready

Ready:

- local source verification
- direct-main publication prep
- paid adversarial review on the final local publication candidate
- rollout planning from the corrected pve1 design

Not yet done:

- final docs closeout commit and push to `origin/main`
- paid GLM adversarial report for the final published diff
- any Proxmox, DNS, Cloudflare, Plex, or pve1 mutation
