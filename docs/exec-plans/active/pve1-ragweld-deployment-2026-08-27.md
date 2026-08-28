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
  `dc42075a0f19a4f41dc28ea58d77f98985f4855a`
  (`fix(deploy): close final foundation review findings`)
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
  `1219 passed, 98 skipped, 7 warnings` in `255.43s`
- The current full-gate count is higher than the earlier pre-closeout run
  because the W34 observability regression and the stale-corpus config-readiness
  regression each gained a permanent test.

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

Reason for the unsandboxed rerun: the managed sandbox blocked localhost test
servers, local database sockets, and Chromium launch/cleanup paths needed by
several real tests. The repo-local result above is the authoritative source
gate.

## Browser evidence

### Verified

- Real Playwright pass on
  `web/tests/e2e/exhaustive/public_link_fields.spec.ts` against the live local
  app (`PLAYWRIGHT_WEB_BASE_URL=http://127.0.0.1:55173/web`): `1 passed`
- Real Playwright pass on
  `web/tests/e2e/exhaustive/admin_config_center_mobile.spec.ts` against the
  isolated current-code lane (`PLAYWRIGHT_WEB_BASE_URL=http://127.0.0.1:55174/web`,
  frontend `55174` -> backend `58013`): `1 passed` in `5.7s`
- Live in-app browser verification confirmed both dedicated public-link hints:
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
- external adversarial review of record, with its actionable findings closed in
  committed source
- rollout planning from the corrected pve1 design

Not yet done:

- final docs closeout commit and push to `origin/main`
- any Proxmox, DNS, Cloudflare, Plex, or pve1 mutation
