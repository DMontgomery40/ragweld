# Watchdog: Proxmox runtime foundation (running list)

Date opened: 2026-08-28
Owner: David (independent review of the SDD run for
`docs/superpowers/plans/2026-08-27-proxmox-runtime-foundation.md`)
Scope: problems the doer either claimed as fixed/verified or did not notice.
Not a list of the doer's open work. Items are appended as found; status is
updated in place. IDs are stable.

Status legend: `OPEN` (needs a fix), `DECIDE` (needs my call, then a fix),
`NOTE` (record only), `FIXED <commit>`.

**ID allocation (added 2026-08-28 08:20 after a collision).** The doer and I
both appended `W44`/`W45` within the same ten minutes, for different findings;
the doer's are committed at `809386f8` and keep those numbers. Mine were
renumbered to `W51`/`W52`. From here: **the doer mints W44-W49, I mint W51+**.
Numbers are never reused or reassigned once written down, even when that leaves
gaps — a stale reference in a plan or ledger must always resolve to the same
finding.

Sweep 2026-08-28 03:15: W1, W2, W3, W6, W9, W10, W20, W21, W22 are implemented
in the doer's uncommitted Task 6b working tree and match the directives
(reviewed diff-by-diff); they flip to `FIXED <commit>` when committed. Task 6
closed at `23080334` (reviewer caught the independently-installable `.mount`
unit; good catch, I had skipped it as harmless).

## Closeout (2026-08-28 07:00)

Foundation published: `main == origin/main == 40c11299` (non-force push of
the reviewed series `0b106b28..40c11299`). Final gate on the `dc42075a` tree:
`1219 passed, 98 skipped`; validators, lint, build green; external review of
record `glm-review-0b106b28..9d834fcf.md` (REFUTED-narrow, every finding
since closed); failed one-shot reports renamed `*-failed.md`. Every W item is
`FIXED <commit>`, `FIXED IN PLAN` (W4/W5/W6-rollout — verified live at rollout
Tasks 3/5), or an accepted `NOTE` (W11, W12, W16, W17, W30, W32, plus the
deferred GLM P3-2/P3-4/P3-5). This list stays open for the rollout and Plex
plans; new items continue the numbering.

Score-keeping for the next plan: 36 items, 6 P1s at the start, all closed
before publication; three defects the doer caught that I missed or
under-rated (`.mount` installability, the observability-card Langfuse link,
the readiness 500 behind W33); two of mine that were wrong on a detail (W3's
`host.docker.internal`, W25's first attribution).

## P1 — will break deployment or an acceptance criterion

### W1 `FIXED e2a2b9da` — Authelia receives `X-Forwarded-Proto: http` from Caddy

- Where: `deploy/proxmox/Caddyfile` (`require_owner` snippet and the
  `auth.ragweld.com` block).
- What was claimed: Task 3 report says the Caddy/Authelia contract is
  "verified"; tests only assert directive/host presence.
- What is wrong: cloudflared connects to Caddy over plain HTTP on
  `127.0.0.1:58000`. Caddy does not trust upstream proxies by default and
  rewrites `X-Forwarded-Proto` to the scheme it actually received (`http`).
  Authelia's `IssuerURL()` (`internal/middlewares/authelia_context.go`)
  rejects any scheme other than `https` (`invalid X-Forwarded-Proto header
  value 'http'`), so `/.well-known/openid-configuration`, the authorize
  endpoint, and the ForwardAuth redirect target (`rd=http://me...`) all break.
  Langfuse SSO (acceptance #3) and the login redirect path cannot work as
  committed.
- Fix: add `header_up X-Forwarded-Proto https` inside `forward_auth` and on the
  `auth.ragweld.com` `reverse_proxy` (optionally also
  `servers { trusted_proxies static 127.0.0.1/32 }` so cloudflared's real
  client IP survives). Extend the Caddy contract parser test so every block
  that talks to Authelia carries that `header_up`.

### W2 `FIXED e2a2b9da` — Langfuse SSO login is blocked by the overlay's own settings

- Where: `deploy/proxmox/docker-compose.yml` (`langfuse.environment`),
  `deploy/proxmox/bootstrap-secrets.sh` (`LANGFUSE_INIT_USER_*`).
- What was claimed: Task 3/5 "Langfuse OIDC client with the exact callback"
  and generated init user are presented as a complete SSO path.
- What is wrong: bootstrap seeds a credentials-provider user with email
  `<owner>@ragweld.local`; Authelia asserts the same email over OIDC. The
  overlay sets `AUTH_DISABLE_SIGNUP=true` and
  `AUTH_DISABLE_USERNAME_PASSWORD=true` but not
  `AUTH_CUSTOM_ALLOW_ACCOUNT_LINKING=true`. Auth.js therefore refuses the
  OIDC sign-in (`OAuthAccountNotLinked`) and signup being disabled removes
  the only other path. First owner login to Langfuse fails.
- Fix: add `AUTH_CUSTOM_ALLOW_ACCOUNT_LINKING: "true"` to the overlay (safe
  here: single owner, emails are Authelia-controlled) and assert it in the
  compose contract test. Reference: Langfuse
  `self-hosting/security/authentication-and-sso` — "AUTH_<PROVIDER>_ALLOW_ACCOUNT_LINKING".

### W3 `FIXED e2a2b9da` (ruled: `SERVER_HOST=0.0.0.0` in the LXC, firewall is the boundary; callback detail superseded by W20) — Linux containers cannot reach the loopback-bound host API

- Where: `start.sh` (uvicorn `--host 127.0.0.1`), `infra/prometheus.yml:31`
  (`host.docker.internal:58012`), `server/api/agent.py:1623-1640` (Flyte
  callback), `server/api/docker.py:138,448`, `deploy/proxmox/render_config.py`.
- What was claimed: spec/plan state "FastAPI bound to LXC loopback" as the
  security property; nobody checked who needs to reach it.
- What is wrong: on Linux Docker `host-gateway` resolves to the bridge
  gateway (`172.17.0.1`), not loopback. Colima on the Mac forwards
  `host.docker.internal` to the Mac's loopback, which is why this never
  surfaced. On pve1: Prometheus cannot scrape the API (every API metric,
  fusion-lane/ML-quality dashboard and alert rule goes dark), the Flyte
  execute-callback cannot reach the API, and the rendered config leaves
  `training.ragweld_agent_flyte_callback_base_url=""` so `workflow=flyte`
  launches return 503 `workflow_backend_unavailable` on day one.
- Decision (mine, override if you disagree): inside the LXC bind the API to
  `0.0.0.0` via the `SERVER_HOST` value bootstrap already writes to
  `runtime.env` (make `start.sh` honor `SERVER_HOST` instead of hardcoding
  `127.0.0.1`), set the Flyte callback to `http://host.docker.internal:58012`
  in the renderer, and treat the LXC firewall (rollout Task 2 Step 6, 58012
  proven unreachable from LAN) as the boundary. Update spec §6 wording from
  "loopback" to "LXC-bound, firewall-scoped". Add a contract test that the
  renderer sets the callback URL and that `start.sh --check` echoes the
  `SERVER_HOST` bind.

### W4 `FIXED dc42075a` (rollout Task 2 Step 5 / Task 3 Steps 4-5 rewritten: `/root` staging, `test ! -e /etc/ragweld` guard, `mv` + `chown`/`chmod` after bootstrap; GLM P1-2 confirmed the corrections block alone was not enough) — Rollout plan violates bootstrap's "empty root" precondition

- Where: `deploy/proxmox/bootstrap-secrets.sh`
  (`ensure_target_root_is_uninitialized`) vs
  `docs/superpowers/plans/2026-08-27-pve1-ragweld-rollout.md` Task 2 Step 5
  (`/etc/ragweld/deployment-commit`) and Task 3 Step 5
  (`/etc/ragweld/owner-password`).
- What was claimed: Task 5 report — "fails closed if the target secret root
  already exists with content" listed as a security invariant.
- What is wrong: the rollout puts two files into `/etc/ragweld` before it
  runs bootstrap, so bootstrap dies with "target root is already
  initialized" every time. The `mv staging -> /etc/ragweld` also requires the
  directory to be empty (`rmdir`).
- Fix: rollout stages `deployment-commit` and `owner-password` under
  `/root/` until after bootstrap (then moves them in with `ragweld:ragweld`
  `0600`), or bootstrap tolerates a pre-existing root containing only an
  allowlist of non-secret files. Pick one and test it.

### W5 `FIXED dc42075a` (rollout Task 5 resolves the tunnel id via `tunnel list --output json`, copies `<UUID>.json` to `credentials.json`, container path in `config.yml`; verify live at rollout Task 5) — cloudflared credential filename mismatch

- Where: `deploy/proxmox/start-runtime.sh` (`REQUIRED_TUNNEL_FILES` =
  `cloudflared/config.yml`, `cloudflared/credentials.json`) vs rollout Task 5
  Step 5/6 (`tunnel create` writes `<UUID>.json`; no rename).
- What is wrong: the preflight will refuse to start with "Required tunnel
  file is missing: .../credentials.json". Also `config.yml` must reference
  the *container* path `/etc/cloudflared/credentials.json`, not the host path.
- Fix: rollout copies `<UUID>.json` to `credentials.json` (or the preflight
  reads the `credentials-file:` line from `config.yml`). Add the container
  path requirement to the rollout text.

### W6 `FIXED e2a2b9da + dc42075a` (`lsof` preflight plus rollout apt line; GLM P2-1) — `lsof` is required and never installed

- Where: `start.sh:357` / `stop.sh` (`require_process_inspector`), rollout
  Task 3 Step 1 apt list.
- What is wrong: both lifecycle scripts hard-exit without `lsof`; the Debian
  13 LXC template does not ship it and the rollout apt line omits it, so the
  systemd unit fails immediately and restart-loops (`Restart=on-failure`,
  each cycle re-running `compose up`).
- Fix: add `lsof` to the rollout package list; add it to
  `start-runtime.sh`'s prerequisite check so the failure is a clear preflight
  message instead of a restart loop.

## P2 — wrong or misleading on pve1, does not block boot

### W7 `FIXED e2a2b9da` (ruled: full Pydantic public-URL split; Faro through Caddy) — loopback URLs are still handed to the remote browser

- `tracing.langfuse_base_url` is dual-use: server-side ingestion endpoint
  (`server/observability/runtime.py:126`) and the deep-link base
  (`langfuse_trace_url`, `runtime.py:451`). Rendered config keeps
  `http://127.0.0.1:53000`, so every Langfuse trace link in the workbench is
  dead remotely; flipping it to `https://langfuse.ragweld.com` would send
  ingestion through Cloudflare + Authelia (302) instead.
- `training.ragweld_agent_mlflow_tracking_url` is emitted as the "MLflow
  Tracking" external link (`server/training/control_plane.py:291`); renderer
  sets it to loopback. Flyte got an admin/console split; MLflow did not.
- `tracing.faro_base_url` stays `http://127.0.0.1:52347/collect`;
  `useAppInit` initializes Faro against it on every remote page load
  (mixed-content POSTs, console errors in the curious-user pass).
- Spec acceptance #12 fails for Langfuse and MLflow as rendered.
- Decision needed: add public-URL fields (Pydantic-first:
  `tracing.langfuse_public_base_url`, `training.ragweld_agent_mlflow_console_base_url`,
  plus a Caddy route `me.ragweld.com/faro/collect -> 127.0.0.1:52347` with
  the renderer pointing `faro_base_url` at it), or blank Faro and accept
  broken Langfuse/MLflow links for the first rollout and log it in
  the evidence. I lean toward the fields; they are small.

### W8 `FIXED dd5a5fb2` (upgraded 03:15, closed 03:58) — public Grafana/Faro URLs make the server-side status probe false-green

- `server/observability/status.py:70-84` `_check_url` runs with
  `follow_redirects=True`. On pve1 `ui.grafana_base_url` and (after Task 6b)
  `tracing.faro_base_url` are public hostnames behind Authelia: the probe
  gets a 302 to `https://auth.ragweld.com/?rd=…`, follows it, the portal
  answers 200, and the observability card reports Grafana/Faro "reachable"
  without ever touching Grafana or the Faro receiver. It also depends on the
  tunnel hairpin, so a tunnel outage reads as an observability outage.
- Better way (no new fields): `_check_url(..., follow_redirects=False)`; a
  3xx whose `Location` host differs from the target host returns
  `(None, "redirected to <host>; protected ingress cannot be probed from the
  API, verify the local listener")` so the card shows *unverified*, not
  green. Cover it with a real local HTTP server test (the repo already has
  the `_StaleModelHandler` pattern in `tests/api/test_health_endpoints.py`)
  that answers 302 to another host and asserts `ok is None`. Keep the
  existing 405/415 POST-only rule.

### W24 `FIXED dd5a5fb2 + 55eff39c` — the no-fallback link rule blanks the Mac workbench's Langfuse/MLflow links

- Correct in code (controller ruling: empty public field → no browser link,
  never loopback), but the checked-in `tribrid_config.json` carries no
  `tracing.langfuse_public_base_url` or
  `training.ragweld_agent_mlflow_console_base_url`, and the Mac's live
  Postgres global config will not have them either. On merge, every
  eval-drilldown Langfuse trace link and Training Center MLflow link on the
  Mac disappears.
- Better way: explicit config, not a code fallback — set
  `tracing.langfuse_public_base_url = "http://127.0.0.1:53000"` and
  `training.ragweld_agent_mlflow_console_base_url = "http://127.0.0.1:55500"`
  in the checked-in `tribrid_config.json` (the renderer already overrides
  both for pve1), extend `tests/unit/test_clean_start_defaults.py` to pin
  them, and note in the handoff that the Mac's stored global config needs the
  same two values once (operator action through the Config UI, which the
  doer's RED test already requires to expose them).

### W9 `FIXED e2a2b9da` — Grafana has no public `root_url`

- Overlay only overrides the admin password. Set
  `GF_SERVER_ROOT_URL=https://grafana.ragweld.com` (and keep
  `GF_SECURITY_ALLOW_EMBEDDING=true`) so absolute links, alert notification
  URLs, and share links are not `http://localhost:3000`.

### W10 `FIXED e2a2b9da` — `me.ragweld.com` has no catch-all

- `redir / /web/` only matches the bare root. Any other path outside `/api/*`
  and `/web/*` (e.g. `/favicon.ico`, typos) returns Caddy's empty `200`.
  Add a final `handle { respond 404 }` (or redirect to `/web/`) and cover it
  in the parser test.

### W11 `NOTE` — Basic-auth surface on every protected host

- `authn_strategies` includes `HeaderAuthorization` (Basic) with
  `scheme_basic_cache_lifespan: 0`, so the owner password is accepted as
  HTTP Basic on `me/grafana/langfuse/mlflow/flyte` from the Internet, with an
  Argon2 verification per request. Only keep it if an API client needs it;
  otherwise drop the strategy and rely on `CookieSession`.

## Process / hygiene

### W12 `FIXED 2026-08-28 post-push refresh` — GitNexus signal was dismissed six times instead of repaired

- Tasks 2-5 each ruled CRITICAL/178-186 impact as "graph noise". My
  debugging notes record the actual cause (incremental FTS corruption) and
  the fix: `node .gitnexus/run.cjs analyze --force`. Run it once before Task
  7's `detect-changes --scope compare --base-ref origin/main` so the final
  scope check is real.
- Resolution: after publication, `analyze --force` completed and the fresh
  compare against `origin/main` dropped to the actual current state:
  `2 files, 14 symbols, 0 affected execution flows, risk low`, all in the
  intentionally local `AGENTS.md` / `CLAUDE.md` GitNexus block. The earlier
  branch-wide CRITICAL signal was stale-index noise, not a live closeout risk.

### W13 `FIXED 40c11299` — full-suite evidence was inherited, not re-run

- Task 3 and Task 4 worker runs recorded `pytest -q` aborting (Docling
  fatal, 8 failing modules) and the controller substituted its own host run.
  Task 5's "1194 passed" is the last real run. Task 7 must run the full
  gate itself on the final tree, not cite earlier counts.
- Resolution: the final local source gate was re-run for real and recorded in
  the closeout evidence: `1219 passed, 98 skipped, 7 warnings in 255.43s`,
  plus green repo validators, frontend lint/build, and the real browser proof
  for the W31 and W33 surfaces.

### W14 `NOTE` — my dirty `AGENTS.md` reverts the handoff pointer

- Working-tree `AGENTS.md` changes "Current branch handoff" from session13
  back to session12 alongside the GitNexus block. That is my file, not the
  doer's; keep it out of the publication commit. I will fix it.

### W15 `NOTE` — `.env.example` still advertises the dead `CONFIG_FILE` key

- Server reads `RAGWELD_CONFIG_PATH` (`server/config.py:6`). Bootstrap
  correctly dropped `CONFIG_FILE`; the example should follow so the next
  operator does not copy it.

### W20 `FIXED e2a2b9da` — Flyte callback must not be `host.docker.internal` (corrects W3's detail)

- Where: Task 6b RED test `PRODUCTION_DEFAULTS[("training","ragweld_agent_flyte_callback_base_url")] = "http://host.docker.internal:58012"`; my own Task 6b Step 3 text said the same.
- Evidence: the Flyte service is the sandbox bundle (privileged, embedded
  k3s). Task pods resolve through k3s CoreDNS, not the container's
  `/etc/hosts`, so `extra_hosts: host-gateway` never reaches them. The 2026-08-22
  Flyte slice recorded exactly this on the Mac: pods reach the host only at
  the VM gateway IP and "CANNOT resolve `host.docker.internal`". On pve1 the
  equivalent is the Docker default-bridge gateway (`172.17.0.1` with stock
  daemon settings), reachable from pods once the API binds `0.0.0.0` (W3).
- Better way: renderer sets
  `training.ragweld_agent_flyte_callback_base_url = "http://172.17.0.1:58012"`;
  `start-runtime.sh` preflight asserts
  `docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`
  equals the host of that URL and fails closed otherwise (so a daemon with a
  custom `bip` cannot silently strand Flyte runs); rollout evidence records
  the inspect output. Contract test: renderer value + a start-runtime test
  with a fake `docker network inspect` returning a mismatching gateway.

### W21 `FIXED e2a2b9da` (pre-existing, was load-bearing) — MLflow deep link guesses the experiment id from `artifacts_uri`

- `server/training/control_plane.py:138-141` splits `mlflow-artifacts:/<exp>/...`
  to build `/#/experiments/<exp>/runs/<run>`; the doer's new test asserts the
  public link on top of that parse. `MlflowRunHandle.experiment_id`
  (`server/training/mlflow_client.py:37`) already knows the value at
  `create_run`.
- Better way: persist `tracking_experiment_id: str | None` on `AgentTrainRun`
  from the handle, build the link from it, delete the URI parse. Small,
  Pydantic-first, and removes a lossy guess from a link the operator will now
  actually click. Do it in this slice since the builder is already open, or
  log it in the tech-debt tracker — not both silently.

### W22 `FIXED e2a2b9da` — Alloy Faro receiver's allowed origins stay the Vite ones

- `infra/alloy/config.alloy` builds `cors_allowed_origins` from
  `ALLOY_FARO_CORS_ORIGIN*`. Same-origin POSTs from `me.ragweld.com` still
  land (CORS is browser-enforced and this is same-origin via the Caddy
  `/faro/*` route), so nothing breaks; but the receiver's allowlist is now a
  lie. Overlay: `alloy.environment.ALLOY_FARO_CORS_ORIGIN: https://me.ragweld.com`
  and assert it in the compose contract test.

### W18 `FIXED 8efdd6fe` — fix rounds skip the full suite, so Task 5 shipped a broken suite while marked complete

- Evidence: Task 5 fix round `1803419c` added five `${VAR:?set VAR}`
  interpolations to `deploy/proxmox/docker-compose.yml` and updated only the
  proxmox contract test's env. The Task 4 parity test
  (`tests/unit/test_runtime_launch_contract.py::test_docker_service_allowlists_match_frontend_and_managed_compose_services`)
  renders the same overlay with only two seeded keys and now fails with a
  Compose interpolation error. Task 5's ledger line cites "1194 passed" from
  the *initial* commit; the fix round "did not rerun the full suite by
  instruction". Task 6's full run surfaced it; the doer's working-tree fix
  (derive required keys from the overlay by regex and assert parity with a
  shared `PROXMOX_PRODUCTION_CONTRACT_ENV`) is the right shape. My own full
  run on that working tree: `1202 passed, 95 skipped` (2026-08-28). Closes
  once the doer commits it.
- Better way, so this class stops recurring: a fix round that touches a
  file referenced by more than one test module must run every test module
  that references any staged path — mechanically:
  `git diff --cached --name-only | xargs -I{} grep -l -- "{}" tests -r | sort -u | xargs uv run pytest -q`
  — before the round is recorded as "addressed". Add that line to the SDD
  fix-round instruction in the plan's Global Constraints, so "no full rerun"
  stops meaning "no rerun of the tests that actually consume the file".
  Second improvement (already in the doer's fix): required-interpolation keys
  are discovered from the overlay, not hand-listed, so the next `:?` addition
  cannot desynchronize two tests.

### W19 `DELIVERED — initial and final-range report/trace pairs preserved` — the paid GLM adversarial review has no durable, findable output

- `glm_review_agent.py` writes `--report`/`--trace` wherever the caller
  points them; nothing has been written yet (the reviews so far were subagent
  passes). When Task 7 Step 3 runs it, the trace is the most valuable
  artifact I have for this watchdog and for later sessions.
- Better way: Task 7 Step 3 writes to
  `.superpowers/sdd/2026-08-27-proxmox-runtime-foundation/glm-review-<base>..<head>.md`
  and `.jsonl`, records both paths in the ledger, seeds the reviewer with this
  watchdog file, and asks for an explicit disposition per `W` item (confirm /
  refute / already fixed) in addition to its own findings. That turns one paid
  pass into a check on both the doer and me.

### W25 `FIXED 228cfb2e` (process; guard committed, worker acknowledged in its report) — an operator-owned working-tree change was silently reverted

- `.claude/hooks/verify-tribrid.sh` (operator-approved `stop_hook_active`
  guard, deliberately uncommitted) was back at HEAD between 02:55 and 03:15.
  No ledger entry, no reflog movement, no stash — so a `git checkout`/`restore`
  of a tracked path the doer did not own. The same mechanism could revert my
  `AGENTS.md`/`tribrid_config.json` edits or a teammate's in-flight work.
- Root cause (from the Codex trace, rollout `2026-08-28T03-21-29`, turn
  `01a047b6`): the Task 6b worker said "I hit one out-of-scope governance
  edit in `.claude/hooks/verify-tribrid.sh`, and I'm reverting only that added
  hunk before I continue" and removed it with `apply_patch` at 09:34:50Z and
  again at 09:35:47Z after I re-applied. Its scope-hygiene rule outranked the
  ledger note it may not have re-read.
- Resolution (03:45): the guard is committed on `main` as a hook-only commit,
  so it is canon rather than a dirty edit the worker feels obliged to clean.
  Standing rule in the ledger and the Task 6b brief: operator governance
  changes land as commits; workers never modify `.claude/` unless a task
  lists it. A monitor now flags any further change to the hook within 5s.
- Mechanical backstop still worth adding to the SDD controller: snapshot
  `git status --porcelain` before each worker and diff it after — any tracked
  path that went from `M` to clean without being in the commit is a hard
  failure of that worker's run.

### W26 `FIXED e2a2b9da` — the staged Task 6b commit omits the glossary entries it created

- At 04:00 the index holds 18 files for Task 6b but `data/glossary.json`
  and its mirror `web/public/glossary.json` (both modified, in sync) are
  unstaged. `test_removed_docker_controls_are_absent_from_glossary_mirrors`
  only asserts mirror equality, so HEAD would stay green while the two new
  config keys' tooltips exist nowhere in history — the exact "glossary
  mirror trap" from the 2026-08-23 session, in its silent form.
- Better way: the Task 6b allowlist gains both glossary files (always as a
  pair). Cheap invariant worth adding to `tests/unit/test_clean_start_defaults.py`:
  every leaf path in `TriBridConfig` whose `to_env` key exists must have a
  glossary `key` — then a missing entry is red instead of merely absent.

### W27 `FIXED 55eff39c` (typed `tracking_backend_unavailable`, real `runs/get` verification, no swallow) — a run whose MLflow tracking cannot be resumed continues untracked while still claiming `tracking_backend=mlflow`

- `server/api/agent.py:1121-1130` (`_run_train_job`): `MlflowUnavailableError`
  at job start is caught, `mlflow_client`/`mlflow_handle` are set to `None`,
  one log line is emitted, and training proceeds. The run record keeps
  `tracking_backend="mlflow"` and `tracking_run_id`, so the Training Center
  and lineage show an MLflow-tracked run whose metrics never arrive. W21's
  new `_resume_mlflow_tracking` raises exactly this error for any run
  persisted before `e2a2b9da` (no `tracking_experiment_id`), so the silent
  downgrade is now reachable deterministically, not only on outages.
- This contradicts the slice's own rule twelve hundred lines lower
  ("Fail closed on configured-but-unavailable target backends. No silent
  substitution back to the local lane." — `start_train_run`).
- Better way: at job start, treat an unresumable configured tracking backend
  the way `start_train_run` treats an unavailable one — mark the run
  `failed` with a typed `tracking_backend_unavailable` reason and stop; an
  operator who wants untracked runs sets `tracking_backend=local`
  explicitly. Cover with the existing real-`_StaleModelHandler`-style local
  HTTP server test plus one persisted run fixture lacking
  `tracking_experiment_id`. Small enough for Task 7's fix disposition;
  otherwise it goes in the tech-debt tracker with this exact wording.

### W28 `FIXED 55eff39c` (siblings + hint on both subtabs, real E2E) — the public-URL fields are editable only in the generic Config Center

- `e2a2b9da` shipped no `web/src` component change; the RED test that
  required `tracing.langfuse_public_base_url` in `RetrievalSubtab.tsx` and
  `training.ragweld_agent_mlflow_console_base_url` in `TrainingStudio.tsx`
  was dropped. The dedicated subtabs still show "Langfuse Base URL" and the
  MLflow tracking URL with no sibling, so an operator editing the Langfuse
  URL there will not understand why trace links did not change. The fields
  are reachable via the Config Center registry cards (and the worker's new
  mobile Playwright proof targets exactly those cards), so this is not a
  blocker.
- Better way (small): render the public sibling directly under each local
  field in `RetrievalSubtab` (Langfuse) and `TrainingStudio` (MLflow) with the
  one-line hint "browser links use this; ingestion/tracking use the local
  URL", reusing `useConfigField`; extend the existing exhaustive spec for
  those tabs rather than adding a new one. Also fine as the first item in
  the next product session if Task 7 is time-boxed.

### W29 `FIXED ad0a2472` (verified: all 12/13px support sizes preserved, no opacity/ellipsis; wrap + minWidth:0 only) — Config Center overflow fix must respect the legibility floor

- The worker is fixing shared `ConfigFieldEditor`/`ConfigBasicsSubtab` card
  overflow at 390×844 with `min-width: 0` and wrapping — the right shape.
  Directive injected into the brief: do not close the overflow by reducing
  font sizes below the floor (nothing under 11px, body ≥ 14px, labels ≥
  11.5px), by adding opacity to text, or by truncating the config path with
  no full-path affordance; verify at deviceScaleFactor 1.

### W30 `NOTE` (test seam, P3) — the W27 regression redirects the run store by swapping a module global

- `tests/api/test_agent_train_launch_boundaries.py` fixture
  `tmp_agent_run_store` assigns `agent_api._RUNS_DIR` and clears
  `_train_tasks`/`_train_cancel_*` by hand. It works (every use of
  `_RUNS_DIR` in `server/api/agent.py` reads the global at call time; verified
  lines 161-162, 570-571, 772, 1564-1572), but it is the same shape as
  `monkeypatch` with less protection, and the manual global clears show the
  module keeps session-wide mutable state that other API tests can see.
- Better way: an env seam mirroring the one that already exists for synthetic
  runs (`RAGWELD_SYNTHETIC_RUNS_ROOT` in `server/synthetic/storage.py:27`):
  `RAGWELD_AGENT_RUNS_ROOT`, resolved inside a `_runs_dir()` accessor, set per
  test via the process env before app import in the fixture. Same isolation,
  no private-global surgery, and it doubles as the pve1 `DATA_DIR` knob. Not
  a Task 7 blocker; fine for the next product session.

### W31 `FIXED 9d834fcf` — new hint captions render at 11px muted

- Fix-wave working tree (05:05): `RetrievalSubtab.tsx` and
  `TrainingStudio.tsx` add the public-URL hint as
  `fontSize: '11px', color: 'var(--fg-muted)'`. My floor: nothing under
  11px, labels/captions >= 11.5px, and the faintest (muted) tier only for
  >= 12px type — at 93 PPI an 11px muted caption is unreadable.
- Better way: `fontSize: 12` (what `configControlPlane.tsx` already uses for
  support text), same color. One-line change; directive injected into the
  ledger and Task 7 brief before the commit. Longer term: put the floor into
  `web/src/legibility.test.ts`-style lint (the dtmont repo has one) so 11px
  literals fail CI instead of relying on a watchdog.

- Resolution: both dedicated hints now render at 12px, and the real
  `public_link_fields.spec.ts` regression checks their computed font sizes.
  That browser run also exposed and fixed the adjacent controlled-`details`
  problem that could snap the Training target lane shut during an async
  refresh. The lane now has one React state authority while preserving
  automatic open for Flyte/MLflow/Unsloth configurations and manual toggling.

### W32 `NOTE` (verification hygiene) — the Playwright proof silently changed lanes when the isolated API was down

- Fix round 3 report: the isolated frontend `55174` was live but the
  isolated API `58013` "was absent on-host", so the spec was rerun against
  the live local API `58012`. The report says so honestly and the spec is
  read-only, so nothing was harmed — but "isolated proof" quietly became
  "proof against whatever is running", which is the same substitution shape
  the repo bans elsewhere.
- Better way: the exhaustive-suite bootstrap already owns port allocation
  and API/proxy alignment (2026-03 UI-proof notes); route every spec run
  through it so a dead isolated API lane restarts or fails the run loudly.
  Add the resolved API base URL to the Playwright report header so a lane
  swap is visible in the evidence, not only in prose.

### W33 `FIXED 90c621d9` (reproduced as scoped readiness 500, not a React loop; real de-indexing-corpus regression plus Admin mobile/browser proof) — intermittent Admin/Basic React update loop

- During the independent W31 browser review, the Admin/Basic page
  intermittently emitted repeated `Maximum update depth exceeded` console
  errors and once failed to load the config control plane. The scoped reviewer
  found no causal link to `9d834fcf`; the controller's isolated
  Retrieval/Training run was green and did not exercise Admin/Basic.
- Preserve this for the Task 7 internal and GLM reviewers. Do not fold an
  unproven fix into W31. If reproducible, route it to the existing frontend
  findings plan with the console trace and exact state transition that loops.
- David, 06:55: agreed with `90c621d9` — the degraded readiness branches omitted `configured`/`reachable`, the partial `IntegrationReadiness` 500'd the Config Center bootstrap, and the retry cycle is what surfaced as `Maximum update depth exceeded`. Keep the harness below as the regression check if the loop ever reappears with a healthy readiness endpoint.
- David, 06:05: cheap reproduction harness — run
  `admin_config_center_mobile.spec.ts` 5x with `page.on('console', ...)`
  collecting `error` entries and fail the run on `Maximum update depth
  exceeded`; the console entry seen at 11:37:49Z pointed into
  `/web/node_modules/...` (Vite dev React), so reproduce against the dev
  server, not the built bundle. First suspects: `useConfigField` per card
  inside `ConfigBasicsSubtab` re-subscribing on every registry refresh, and
  the new `useEffect` auto-open in `TrainingStudio` if `targetLaneConfigured`
  flips each render. Next product session, not this closeout.

### W34 `FIXED 6a6567a3` (probe local, publish `langfuse_public_base_url`; API test with local `:9` vs public https) — the observability status card still links to the local Langfuse URL

- `server/observability/status.py:318` `langfuse_url = config.tracing.langfuse_base_url`
  is used for the reachability probe (correct: local) and then passed as
  `url=langfuse_url` and `links=_make_links("Langfuse", langfuse_url, ...)`
  (`status.py:469-482`). On pve1 the Observability card's "Langfuse" link is
  `http://127.0.0.1:53000` for a remote browser — the exact class W7 was
  meant to close; I grepped `langfuse_trace_url` and stopped one builder short.
- Better way: probe `langfuse_base_url`, publish `langfuse_public_base_url`:
  `url=public or None`, `links=_make_links("Langfuse", public, ...)`, with
  `configured` still derived from the local URL + client blockers. Extend
  `tests/api/test_observability_endpoints.py` to assert the Langfuse component
  `url`/link equals the public field while `configured` follows the local
  one. Sweep rule for the fix: `grep -rn "langfuse_base_url\|mlflow_tracking_url" server | grep -v Field(`
  and classify every hit as probe/ingest (local) or link (public) in the
  commit message so this cannot recur one builder at a time.

### W35 `FIXED (harness) — review of record plus final-range rerun delivered` (`glm-review-0b106b28..9d834fcf.md`, 18 rounds, verdict REFUTED-narrow; `glm-rereview-9d834fcf..dc42075a.md`, 35 rounds, verdict PASS) — the tool-using GLM run discarded six minutes of paid trace and the fallback stalled

- `glm_review_agent.py` writes `--trace`/`--report` only after the loop
  returns; the 11:53-11:59 run ended in `RuntimeError("reviewer returned no
  final report")` (final message had no tool calls and empty `content`), so
  every tool round was lost. The one-shot fallback pushed the whole 275 KB
  bundle into a single prompt and was killed at ~90 s (the harness the
  controller had already rejected as "summary-only" is now the plan).
- Better way (three small harness edits, then rerun in the background):
  1. append each round to the `.jsonl` as it happens (open once, write per
     round, flush) so a failed run still leaves evidence;
  2. when the final message has empty `content`, first look for
     `message.reasoning` / `reasoning_content`, and if still empty send one
     more user turn "Emit the final bounded report now; no more tool calls"
     with a large `max_tokens`, before raising;
  3. run it in the background and poll the trace file; a 1.3 M-token reviewer
     gets up to one hour for each model response and no short total-job cutoff.
     Tool rounds continue until the reviewer emits its bounded final report or
     the provider returns a genuine terminal failure. Silence is not failure.
- 06:20 evidence for the root cause: both one-shot outputs
  (`glm-review-0b106b28..c7993372.md`, `glm-review-9d834fcf..c7993372.md`)
  contain the literal `None` — the verdict JSON shows `finish_reason:
  "length"`, `content: null`, and the whole budget spent in `reasoning`. A
  thinking model with a small `max_tokens` never reaches the answer; the
  writer then serialized `None`. Neither file is review evidence; do not cite
  them. The tool-using rerun is the one that counts.
- Publication rule (mine): do not push without either the GLM report on disk
  or an explicit ledger line from me waiving it. Do not terminate a healthy
  review because it crosses an arbitrary wall-clock budget; preserve every
  checkpoint and allow the tool-using run to finish naturally.

### W36 `FIXED dc42075a` — GLM P3 batch: five one-line hygiene fixes worth one commit, three deferred

GLM's tool-using pass (`glm-review-0b106b28..9d834fcf.md`) found no new
correctness/secret/auth defect in the committed surface; its P1-1 was W34
(already `6a6567a3`), P1-2/P2-1 were my rollout-plan text (fixed 06:35), P2-2
is W13 (final full gate on the final tree). Of its eight P3s I verified and
adopt five for the single fix wave — each is a one-liner with an existing
test to extend:

1. `tests/unit/test_proxmox_deployment_contract.py:1548,1609` —
   `rf"(?m)^\\s*{command}\\b"` in a raw f-string is a literal-backslash
   regex; verified `re.search` never matches a plain `mount -a` line, so the
   forbidden-command scans pass vacuously. Fix: single backslashes; add one
   positive control (a poisoned sample must fail).
2. `deploy/proxmox/bootstrap-secrets.sh:236` writes `SERVER_PORT=58012`, but
   `start.sh:9` binds on `BACKEND_PORT`; an operator changing it is silently
   ignored. Fix: write `BACKEND_PORT` (keep `SERVER_PORT` only if a consumer
   exists; none in `server/`).
3. `deploy/proxmox/start-runtime.sh` preflight validates the rendered config
   only for the Flyte callback host; a truncated/invalid file passes and fails
   inside uvicorn under `Restart=on-failure`. Fix: `TriBridConfig.model_validate`
   in the same preflight python, fail closed with the validation error.
4. `deploy/proxmox/bootstrap-secrets.sh:122` `shutil.rmtree(..., ignore_errors=True)`
   can leave a secret-bearing `.ragweld-bootstrap.*` staging dir in `/etc`
   silently. Fix: drop `ignore_errors`, print the path on failure.
5. `.env.example:59` still advertises the dead `CONFIG_FILE` key (W15).

Deferred with a reason: P3-2 (`RAGWELD_CONFIG_PATH` written from
`DEFAULT_ETC_ROOT` under a test-only override — harmless until the seam is
real), P3-4 (`_resume_mlflow_tracking` returns `None` when `tracking_run_id`
is empty — unreachable via `start_train_run`; hardening only), P3-5
(`_ensure_local_request` admits everything behind Caddy — consistent with the
single-owner model; document in spec §6 in the docs commit, and revisit if a
viewer identity is ever added). Note: GLM also pointed out the W23 numbering
gap; there was never a W23 — nothing lost.

### W14 `FIXED (working tree)` — my `AGENTS.md` handoff pointer regression is repaired (session13 restored; GitNexus block kept).

## Plex plan pre-read (2026-08-28 07:10, before any live step)

### W37 `FIXED AND PUBLISHED b421d203` — automount idle expiry + LXC bind mount = empty media at container start

- `deploy/proxmox/plex/srv-media.automount` sets `TimeoutIdleSec=60`
  (systemd's default is 0 = never expire). LXC 4214 consumes `/srv/media`
  as `mp1: /srv/media,mp=/srv/media` — a bind mount created at `pct start`
  with private propagation. If the NFS filesystem is not mounted at that
  instant (expired after 60 s idle, or never triggered since a `.173`
  reboot before the path is traversed), the container binds the autofs stub and sees an empty
  tree; later host-side automounts do not propagate into it. Plex/arr start
  with no media — Task 3 Step 6's rollback trigger — and it recurs on every
  reboot.
- Better way (three small pieces, all reversible):
  1. Foundation follow-up commit: `TimeoutIdleSec=0` in
     `srv-media.automount` (+ update the contract test), so the mount never
     expires once triggered.
  2. `.173` drop-in
     `/etc/systemd/system/pve-container@4214.service.d/srv-media.conf` requires
     and orders after `srv-media.automount`, then runs a fatal, bounded
     `ExecStartPre` that traverses the path and requires `nfs4`. This gates
     Plex 4214 only; global `pve-guests.service` and Scrypted 1043 remain
     independent (W43).
  3. Plex plan Task 3 Step 5: run `findmnt -t nfs4 /srv/media` on `.173`
     immediately before `pct start 4214`, and after start prove
     `pct exec 4214 -- findmnt -t nfs4 /srv/media` (fstype must be `nfs4`,
     not `autofs`).
- Controller RED/GREEN evidence 2026-08-28: the exact contract test failed
  against `TimeoutIdleSec=60`, then passed after the template moved to
  `TimeoutIdleSec=0`. The two-file fix was published as `b421d203` before
  Plex Task 2.

### W38 `SATISFIED by live preflight 2026-08-28` — `pct migrate` needs `shared=1` on the bind mount; the plan assumes it

- Task 1 Step 2 "expects" `mp1: /srv/media,mp=/srv/media,shared=1`, but the
  spec's verified state only says "bind mount". Proxmox refuses to migrate a
  container with a non-shared bind mount. Better way: Task 1 records the
  actual `mp1` line; if `shared=1` is absent, add
  `pct set 4214 -mp1 /srv/media,mp=/srv/media,shared=1` as an explicit,
  metadata-only Task 3 Step 0 with its own rollback (`shared=0`).
- Controller revalidation read the exact live line:
  `mp1: /srv/media,mp=/srv/media,shared=1`; no metadata change is required.

### W39 `SATISFIED at live preflight; recheck before export` — pve1 host firewall not checked for NFS

- Task 2 Step 2 starts `nfs-server` on pve1 but never checks
  `pve-firewall status` / the host ruleset. If the datacenter or host
  firewall is enabled with default input DROP, `.173` cannot reach tcp/2049
  and Task 2 Step 3's mount hangs (hard mount) instead of failing. Better
  way: Task 2 Step 2 adds `pve-firewall status` + `pve-firewall localnet`;
  if enabled, add a host rule `IN ACCEPT -source 192.168.68.173 -p tcp
  -dport 2049` in `/etc/pve/nodes/pve1/host.fw` before mounting, and record
  it as a bridge component to remove with the bridge.
- `pve-firewall status` on pve1 returned `disabled/running` during the
  2026-08-28 preflight, so no rule is currently required. The plan still
  rechecks immediately before installing the export.

### W40 `RESOLVED by live inventory 2026-08-28` — Task 4 probe paths are hardcoded

- Step 3 assumes `/tv`→`/srv/media/tv-sonarr`, `/movies`→`/srv/media/radarr`,
  `/downloads`→`/srv/media/downloads`. Task 1 Step 3 already inventories the
  real container mounts; derive the probe paths from that inventory (and
  the container UID) so a differently-mapped library does not read as a
  write failure.
- Live Docker mount inventory confirms Sonarr `/tv` and `/downloads`, Radarr
  `/movies` and `/downloads`, and qBittorrent `/downloads`, with host sources
  recorded in `plex-return-to-pve-2026-08-27.md`. All four media containers
  explicitly carry `PUID=1000` and `PGID=1000`; Task 4 uses those observed
  values rather than hardcoded guesses.

### W44 `FIXED LIVE; preserved for rollback` — stale `.173` fstab entry and real data occupied the NFS mountpoint

- `.173:/etc/fstab` still targeted absent ext4 UUID
  `5ddacfd6-1309-4c2c-8bb8-890bbef8546d` at `/srv/media`; systemd generated
  an inactive conflicting mount unit from it.
- The plain root-disk directory below that path held 145 files / 31.6 GB.
  Mounting NFS over it would have hidden real data.
- Live correction: preserve the exact fstab at
  `/etc/fstab.ragweld-pre-nfs-20260828`, disable only the absent-UUID line,
  rename the directory on the same filesystem to
  `/srv/media-local-pre-nfs-20260828`, and create a new empty mountpoint.
  Nothing was deleted. The quarantine remains until migration acceptance.

### W45 `FIXED LIVE AND IN PLAN` — Debian 13 omitted `/etc/exports.d`; `stat` did not trigger the direct automount

- The first server activation failed closed before writing Ragweld config
  because Debian's package did not create `/etc/exports.d`, although
  `exports(5)` supports it. The plan now creates the standard directory first.
- On `.173`, `stat /srv/media` inspected the autofs node but did not traverse
  it, leaving the NFS mount inactive. Bounded `ls /srv/media` is the verified
  trigger and is now used by installation, retrigger proof, and the
  `pve-container@4214.service` pre-start guard.

### W41 `FIXED LIVE AND IN PLAN` — prove `root_squash` before the migration commits to it

- Today LXC 4214 writes `/srv/media` as a **local** bind mount, so container
  uid 0 writes succeed. After the bridge it is NFS with `root_squash`, and
  uid 0 writes become `nobody` → `EACCES`. The container is privileged
  (`unprivileged: 0`), so uid 0 inside is uid 0 on `.173` and is squashed.
- The first proposed negative test was incorrect: pve1's export root is owned
  by `1000:1000` and mode `0777`, so the anonymous uid can create a file even
  when squashing works. Write failure is not the invariant.
- Controller proof: a root-created `.ragweld-root-squash-probe` appeared on
  both `.173` and pve1 as `65534:65534`, proving root maps to the anonymous
  identity. The exact probe was removed. Task 2 now asserts that ownership.
- Task 4 still greps Plex/Sonarr/Radarr/qBittorrent logs for permission/chown
  signatures before acceptance. Any hit is stop-and-investigate; never relax
  the whole export to `no_root_squash`.

### W42 `FIXED LIVE AND IN PLAN` — an unmounted `/srv/media` silently absorbs writes onto `.173`'s root disk

- Preflight recorded `.173:/srv/media` as "a plain root-owned directory and
  is not mounted". Task 2 Step 3 mounts over it. Whenever the NFS mount is
  absent — before the first trigger, during a pve1 outage, after a failed
  remount — writes to that path land on the **underlying local directory** on
  `.173`'s `local-lvm` root filesystem. They succeed, so nothing alerts;
  they are invisible once the mount returns; and a busy qBittorrent can fill
  the root disk of the node now hosting Plex. Same family as W37: the path
  looks right, the data goes somewhere else.
- Better way (one command, before the mount, in Task 2 Step 3):
  ```bash
  "${PVE_SSH[@]}" root@192.168.68.173 'test -z "$(ls -A /srv/media)" || { echo "UNEXPECTED: underlying /srv/media is not empty"; exit 1; }; chmod 0555 /srv/media; stat -c "%a" /srv/media'
  ```
  An empty, mode-`0555` underlying directory makes a missing mount fail loudly
  (`EACCES`) instead of writing to the wrong disk; the NFS root's own
  permissions govern once mounted, so nothing changes in the working state.
  Record the `0555` in the evidence file as a bridge component, and note that
  removing the bridge later means unmounting **and** restoring the mode.
- Live proof: the NFS units were stopped, the empty underlying directory was
  changed to mode `0555`, and an explicit UID/GID 1000 write was denied. The
  NFSv4 mount was then retriggered and returned active.

### W43 `FIXED AND ACCEPTED LIVE` — the original W37 drop-in would hold Scrypted's cameras hostage to pve1

- Correcting a directive I wrote. W37 part 2 told Task 2 Step 3 to add
  `ExecStartPre=/bin/sh -c 'ls /srv/media >/dev/null && findmnt -t nfs4 /srv/media'`
  to `pve-guests.service` on `.173`. That unit starts **every** autostarting
  guest on the node, and `.173` also runs Scrypted LXC 1043 (the camera
  workload, per spec §3 and the plan's own Task 4 Step 5). As written:
  - pve1 down at `.173` boot → `ExecStartPre` fails → `pve-guests.service`
    fails → **Scrypted never starts**, cameras stay dark, and the cause is a
    media mount for a different container;
  - worse, the mount is `hard`, so a pve1 that is reachable-but-not-serving
    makes the bare `ls` block indefinitely and hangs the boot instead of
    failing. A media bridge must not become a single point of failure for an
    unrelated guest.
- The non-fatal global workaround was also rejected: it protects Scrypted but
  permits Plex 4214 to start against an autofs stub. Proxmox has the correct
  per-guest ownership seam:
  ```ini
  # /etc/systemd/system/pve-container@4214.service.d/srv-media.conf
  [Unit]
  Requires=srv-media.automount
  After=srv-media.automount network-online.target
  [Service]
  ExecStartPre=/usr/bin/timeout 60 /bin/sh -c 'ls /srv/media >/dev/null 2>&1 && findmnt -t nfs4 /srv/media >/dev/null'
  ```
- This gate is fatal and bounded for 4214 only. Live `systemctl show` proves
  the drop-in attaches to `pve-container@4214.service`; global
  `pve-guests.service` has no drop-in; Scrypted 1043 remained running.
- Also add to Task 4 Step 5 (Scrypted health): reboot `.173` once after the
  bridge is live and confirm both 1043 and 4214 come back with media
  present — the boot-order path is the one this trap lives in, and it is
  never exercised by the migration steps themselves.
- Live acceptance: `.173` rebooted after migration. Grafana 103, Scrypted
  1043, and Plex 4214 all returned automatically; Scrypted stayed active with
  its render device; the host and 4214 guest both reported the NFS source as
  `nfs4`; all 12 media containers returned and Gluetun was healthy.

### W51 `SATISFIED by live reboot evidence 2026-08-28` (renumbered from a duplicate W44 — see the ID-collision note) — nothing checked `onboot`, so the reboot proof could have passed while Plex stayed down

- `onboot` appears nowhere in the plan, the Task 1 `pct config 4214` inventory,
  or the Task 2 evidence. Proxmox defaults `onboot` to `0`, and the Task 1
  dump recorded `cores/memory/unprivileged/features/rootfs/net0/mp1` with no
  `onboot` line — so 4214 most likely does **not** autostart.
- Why this bites precisely here: the whole boot-order apparatus we just built
  (`pve-container@4214.service.d/srv-media.conf`, `Requires=`/`After=`
  automount, the `ExecStartPre` trigger) only runs when something starts that
  unit. With `onboot: 0` nothing does at boot. The W43 reboot acceptance would
  then "pass" — Scrypted up, no errors, `findmnt` fine on the host — while
  4214 is simply *not running* and Plex is down until someone notices. A
  reboot check that does not assert the container is running proves the
  opposite of what it looks like it proves.
- Better way (one line of inventory, one decision, one assertion):
  1. Task 1 Step 2 records the actual `onboot` value alongside `mp1`.
  2. Before the W43 reboot test, set it deliberately on the destination:
     `pct set 4214 --onboot 1 --startup order=2` (order after Scrypted so the
     camera workload claims the render device first; rollback is
     `pct set 4214 --onboot 0 --delete startup`). If the operator prefers
     manual starts, record that choice explicitly instead — but record it.
  3. The W43 reboot acceptance must assert `pct status 4214` is `running`
     **and** `pct exec 4214 -- findmnt -t nfs4 /srv/media` before it counts.
     Without the running assertion the test is vacuous.
- Closed by evidence, not by argument: the Task 4 boot-order section records
  `onboot=1` on 103/1043/4214 **before** the reboot, an actual reboot of `pve`
  (boot time `2026-08-28 08:10:43`), all three LXCs back to `running`, matching
  host and guest NFSv4 views, Scrypted still holding `renderD128`, all 12
  containers back, and all nine LAN checks responding. That is exactly the
  non-vacuous form this item asked for. My premise that `onboot` would default
  to `0` was wrong for this container — the check was still worth demanding,
  since nothing in the plan or the Task 1 inventory had established it.

### W52 `WITHDRAWN — my framing was wrong (see W57)` (P3; renumbered from a duplicate W45) — restoring the fstab backup re-adds the stale absent-UUID line

- Task 2 disabled one `.173` fstab line targeting `/srv/media` for absent UUID
  `5ddacfd6-…` and saved `/etc/fstab.ragweld-pre-nfs-20260828`. The recorded
  bridge rollback says "restore the dated fstab backup", which would put that
  broken line back — an fstab entry for a device that does not exist, now
  pointed at a path that will be a live mountpoint.
- Better way: the rollback restores the backup **minus** that line (or simply
  leaves the disabled line disabled and notes the backup as reference only).
  State it in the evidence file's rollback section so a later operator does
  not faithfully restore a landmine.

### W53 `CLOSED — Plex coupling dead; my sizing push withdrawn, spec sizing stands; one post-start check retained` — the Plex bridge just made pve1's stability a Plex dependency, and the next plan deliberately loads pve1 to ~91% memory

- Neither plan owns this, because it only exists once both have run. Plex now
  reads its entire library over `hard` NFS from pve1
  (`srv-media.mount:10` `Options=_netdev,hard,noatime`). `hard` means a server
  that stops answering does not return `EIO` — client processes block in
  uninterruptible sleep, so Plex/arr hang unkillably rather than erroring.
- Onto that same node the rollout plan puts LXC 100 at `--memory 24576
  --swap 8192 --cores 16 --cpuunits 10000` (rollout plan `:149`), beside HAOS
  VM 120's 16 GB cap, on a 31 GiB node. Caps total 40 GiB on 31 GiB; the
  approved overcommit rests on HAOS's observed ~4.2 GiB, leaving roughly
  28.2 GiB committed of 31. A Ragweld indexing run, a Docling PDF pass, or the
  Flyte sandbox spiking into its cap puts pve1 under memory pressure — and the
  kernel OOM killer does not know that `nfsd` is holding up the household's
  Plex. Symptom on `.173` would be every media container wedged in D-state,
  which reads as a Plex failure with no Plex cause.
- Better way (three cheap, independent guards; none requires re-architecting):
  1. **Protect the exporter.** On pve1:
     `systemctl edit nfs-server` with `[Service]` `OOMScoreAdjust=-1000`, so
     the media bridge is the last thing the kernel reclaims. Record it as a
     bridge component alongside the export.
  2. **Make Ragweld the first victim, not the node.** Give LXC 100 a memory
     cap that leaves real headroom and mark it as the preferred OOM target:
     drop to `--memory 20480` (still ample beside HAOS's real 4.2 GiB) or add
     a `.173`-style startup order plus `pct set 100 --startup order=3`, and
     verify `free -h` headroom on pve1 **after** the stack is up, not only at
     provisioning time (rollout Task 1 Step 3 checks it before).
  3. **Document the expected freeze.** A deliberate pve1 reboot — which the
     rollout plan will cause — freezes Plex for the duration and then
     recovers, by design of `hard`. Put that in the rollout evidence so nobody
     force-reboots `.173` or force-kills wedged containers mid-window, which
     is what turns a five-minute freeze into a corrupted download client.
- Sequencing note: the cheapest moment for guards 1 and 2 is rollout Task 2
  (LXC creation), before any Ragweld data exists.

**Correction (David, 15:35Z), and then a correction to the correction.**
When the disks moved I retired this item and wrote "LXC 100 may keep its full
24 GiB". The Plex half is genuinely dead — pve1 serves no media, `nfs-server`
is disabled, nothing depends on it over a `hard` mount — so the
`OOMScoreAdjust` guard is withdrawn.

I then argued the co-tenancy half survives and pushed for `--memory 20480`,
because pve1 is 31 GiB with 25 GiB available and one co-tenant (HAOS VM 120,
16000 MB cap, ~5 GiB real), so a Ragweld peak could squeeze Home Assistant —
lights and automations, not a slow dashboard. **The doer pushed back and it is
right; I withdraw the 20 GiB push.** Spec §5 reads "24 GiB memory and 8 GiB
swap **while HAOS remains on `pve1`**; a later increase to roughly 30 GiB after
HAOS can safely return to `pve3`". So 24 GiB was already the HAOS-aware number
chosen deliberately, and 30 GiB is the post-HAOS number. My 20 GiB would have
overridden an approved sizing decision using the very consideration that
produced it. Caps are not reservations and the 24+16-on-31 overcommit is the
one the rollout plan calls "the approved overcommit".

What actually survives from this item is one line, which the doer already kept:
**re-check `free -h` on pve1 after the full stack is up**, not only at Task 1
Step 3 on an empty node. If that measurement shows HAOS genuinely squeezed, the
levers in order are moving HAOS to `pve3` (already the plan) or lowering the cap
then — with data, rather than pre-emptively against the spec.

### W54 `DOWNGRADED to P3 by live evidence, but one concrete defect survives — see the 2026-08-28 inventory below` — the DNS inventory can only find records we already know the names of

- Task 5 Step 1 inventories with five `dig` queries (`NS`, `A`, apex `CNAME`,
  `MX`, apex `TXT`) and Step 2 says "recreate all discovered DNS records".
  `dig` is a *lookup*, not an enumeration: it can only answer for names
  supplied to it, and DNS has no listing operation. Everything below is
  invisible to that method and is lost the moment the registrar delegates to
  Cloudflare:
  - **DKIM** at `<selector>._domainkey.ragweld.com` and **DMARC** at
    `_dmarc.ragweld.com` — subdomains, so apex `TXT` never sees them. Losing
    them does not bounce mail; it silently degrades deliverability, so outbound
    mail starts landing in spam days later with no obvious connection to a DNS
    change made during a Plex migration weekend.
  - **CAA** — not queried at all. Lost CAA is a quiet security regression;
    a mis-recreated one blocks certificate issuance for the new hostnames.
  - Any other subdomain record: `_acme-challenge`, provider
    domain-verification CNAMEs, `mail`/`autodiscover`, a staging host.
- Better way — one action that is exhaustive by construction, instead of five
  guesses:
  1. **Export the zone from the current provider before touching anything.**
     Whatever holds the zone today (Netlify DNS or the registrar) offers a
     full record list or BIND zone export in its UI. Save the export verbatim
     into the evidence file's appendix — it is also the rollback source.
  2. **Import that zone file into Cloudflare** (Cloudflare's zone-add flow
     accepts a BIND import) rather than hand-recreating records. Then diff:
     record count and every name/type/value must match the export before the
     nameserver change, and the plan stops if they do not.
  3. If no export exists, enumerate deliberately before delegating:
     `dig +short CAA ragweld.com`, `dig +short TXT _dmarc.ragweld.com`,
     `dig +short TXT <selector>._domainkey.ragweld.com` for each selector the
     mail provider lists, plus `dig +short CNAME` for every hostname named in
     the provider's dashboard. Record "no mail on this domain" explicitly if
     that is the answer — an explicit negative is evidence; silence is not.
  4. **Lower TTLs to 300s at the current provider before the cutover** so a
     rollback is minutes rather than hours.
- Rollback (spec §12 asks for it; the plan should carry the literal values):
  record the exact original nameserver pair beside the export, and state that
  reverting means restoring those two nameservers at the registrar — nothing
  else.

---

**Live inventory of `ragweld.com`, taken read-only 2026-08-28 17:00Z.** I
queried the zone rather than continuing to argue from principle:

| Record | Value |
| --- | --- |
| `NS` | `dns1-4.p04.nsone.net.` (NS1 — Netlify's DNS backend) |
| `A` (apex) | `13.52.188.95`, `52.52.192.191` |
| `www` | **`A` records**, same two IPs — **not** a CNAME |
| `MX` | **none** |
| apex `TXT` | **none** |
| `_dmarc` | **none** |
| `CAA` | **none** |
| DKIM (`google`, `default`, `selector1/2`, `k1`, `s1`, `mail`, `dkim`, `fm1`, `protonmail`) | **none found** |

**My headline worry does not apply.** There is no mail on this domain and no
SPF/DKIM/DMARC/CAA to lose, so the "silently broken email deliverability"
scenario — the reason I rated this P1 — is empirically absent. Downgraded to
P3. The zone is minimal: nameservers, apex A, www A.

**But one concrete defect survives, and it is the same enumeration weakness
showing up differently than I predicted.** Task 5 Step 1 inventories www with:

```bash
dig +short CNAME www.ragweld.com     # returns NOTHING — www is an A record
```

`www` is served by **A records**, not a CNAME, so that command returns empty
and the plan would record "no www record". Then Step 2 recreates "all
discovered DNS records" — and `www.ragweld.com` is silently dropped at
delegation, taking the landing site's www with it. One wrong record type in an
inventory command is enough; this is exactly why enumeration beats lookup.

**Reduced fix, proportional to what is actually there:**
1. Query `www` for `A` and `AAAA` as well as `CNAME`, or simply use
   `dig +short ANY www.ragweld.com` and `dig +short ANY ragweld.com`.
2. Record the four literal values above in the evidence file *before*
   touching nameservers — apex `13.52.188.95` / `52.52.192.191`, www the same
   pair, and the four `p04.nsone.net` nameservers as the rollback target.
3. The zone-export recommendation still stands as the cheaper, exhaustive
   option (Netlify DNS can list the full record set), but with no mail,
   hand-recreating five records is now a reasonable alternative.
4. Note that the apex points at AWS `us-west-1` addresses rather than
   Netlify's usual load-balancer IPs — confirm what actually serves the
   landing page before assuming Netlify's defaults will recreate it.

### W55 `CLOSED BY CODEX LIVE EXECUTION 2026-08-28 — DO NOT EXECUTE; record only` (P1) — the Plex disks moved to `.173`; the bridge was torn down, not repaired

**Coordination.** David moved the disks physically at ~14:30Z and asked only
that someone own it. Codex has the live-infra authority and the destructive-op
approval path, so **Codex executes this**; this watchdog session verified the
state read-only and wrote the procedure, and will not run teardown commands.
If Codex has already started, this section is reference only — do not run any
step twice.

**Verified live state (watchdog, read-only, 14:30-14:34Z).** No emergency:
nothing is running against the dead path and nothing is writing.
- `.173`: `sda` + `sdb` present; `plex-vg` complete and healthy (2 PVs,
  VSize 7.28T, VFree 0); `plex--vg-plex--lv` ext4 — **not mounted**.
- `.173`: `/srv/media` is **still the NFS mount to `192.168.68.171`**
  (`nfs4`, `hard`, vers=4.2) behind the direct automount.
- `.173`: **LXC 4214 is stopped**; Scrypted 1043 running; **no D-state
  processes**; root fs 94G, 68G used, 22G free.
- `pve1`: `plex-vg` is **gone from LVM** (`vgs` shows only `pve`), yet
  `/srv/media` is still mounted as `/dev/mapper/plex--vg-plex--lv ext4
  rw,relatime,**emergency_ro**` — a zombie mount whose block device vanished —
  and it is **still exported** to `.173`.
- Data looks intact; the media was never copied, only the enclosure moved.

**Why this is a teardown, not a repair.** Spec §10 already anticipated it:
"A later physical disk move can remove this temporary dependency… document the
later physical media-disk return to `.173` as the cleanup that removes the
bridge." That move just happened early. Repairing the export would reintroduce
a network hop between `.173` and its own local disks.

**Ordered procedure — each step is a checkpoint; stop and report on any surprise.**

1. **Confirm the safe window.** `pct status 4214` is `stopped`. Do not start it
   until step 7. (If it is running, stop it first — its media path is dead.)
2. **`.173` — remove the bridge client.**
   `systemctl stop srv-media.automount srv-media.mount`; if the unmount hangs
   because the server filesystem is dead, `umount -f /srv/media` then
   `umount -l /srv/media`. `systemctl disable srv-media.automount`; remove
   `/etc/systemd/system/srv-media.mount` and `srv-media.automount`; remove
   `/etc/systemd/system/pve-container@4214.service.d/srv-media.conf`;
   `systemctl daemon-reload`. Confirm `findmnt /srv/media` is empty.
3. **`pve1` — stop being a storage server.** `exportfs -ua`; remove
   `/etc/exports.d/ragweld-media.exports` and `/etc/nfs.conf.d/99-ragweld.conf`;
   `systemctl disable --now nfs-server`; `umount -l /srv/media` to clear the
   `emergency_ro` zombie; confirm `findmnt /srv/media` is empty. This also
   **retires W53** — pve1 is no longer in Plex's data path.
4. **`.173` — activate and CHECK the filesystem before any writable mount.**
   `vgchange -ay plex-vg`, then a **read-only dry run first**:
   `e2fsck -n /dev/mapper/plex--vg-plex--lv`. The filesystem was mounted `rw`
   when the disks were pulled and went `emergency_ro`, so it is unclean by
   definition. If the dry run shows only journal recovery, proceed with
   `e2fsck -p`. **If it reports real structural damage, stop and report before
   mounting rw** — 5.4 TB of media is worth one careful step.
5. **`.173` — mount it locally, keeping the W42 guard.** Leave the underlying
   `/srv/media` directory at mode `0555` (it still makes a missing mount fail
   loudly). Get `blkid -s UUID -o value /dev/mapper/plex--vg-plex--lv` and
   install a **local** `srv-media.mount` unit (`What=/dev/disk/by-uuid/<UUID>`,
   `Type=ext4`, `Options=defaults,noatime`) — no automount needed for a local
   device — plus `WantedBy=multi-user.target`.
6. **Keep the W37/W43 protection in the new topology.** Reinstate
   `/etc/systemd/system/pve-container@4214.service.d/srv-media.conf` with
   `Requires=srv-media.mount` and `After=srv-media.mount`. The trap is
   identical for a local mount: a bind taken before the mount exists captures
   an empty directory. Scoping stays per-container so Scrypted is unaffected.
7. **Verify, then start.** `findmnt -t ext4 /srv/media` (~7.3T, ~5.4T used),
   top-level listing matches the pre-move inventory, then `pct start 4214` and
   prove `pct exec 4214 -- findmnt /srv/media` shows the **ext4 device** — not
   `autofs`, not `nfs4`. Then the Task 4 service/write/transcode acceptance.
8. **Reboot `.173` once** and re-verify 1043 running, 4214 running, and the
   guest-side ext4 mount — the W43/W51 boot-order proof, now for local disk.
9. **Record and decide.** Update the evidence file with the new topology; mark
   W53 obsolete; decide the fate of the 31.6 GB quarantine
   `/srv/media-local-pre-nfs-20260828` now that `.173` root is at 76%.

**Rollback.** The pre-migration PBS backup of 4214 is still the container
rollback and the media was never copied. If the array will not mount cleanly on
`.173`, power down, return the disks to pve1, `vgchange -ay` there, and restore
the two saved bridge units — the teardown above is reversible precisely because
nothing is deleted.

### W56 `RESOLVED by the same event` (P1, process deadlock) — Codex is blocked on a human proof the disk move made impossible, so W55 will never start on its own

- The Plex evidence file ends: "A signed-in user must finish the remaining
  direct-play and forced lower-quality transcode interaction… **This is the
  only remaining Plex-plan acceptance item before starting Ragweld LXC
  provisioning.**" Codex has been idle ~30 minutes waiting on exactly that.
- David cannot perform it. LXC 4214 is stopped, and if started its library
  path is the dead NFS mount to a node with no disks. So Codex waits for a
  human, the human cannot act, W55 never begins — and because that proof is
  written as the gate before Ragweld provisioning, the **entire rollout is
  transitively blocked** by a circular dependency neither side can see from
  its own position. Codex will not self-diagnose this: from where it sits,
  "waiting on the operator" is a legitimate state.
- Better way (pure re-sequencing, no scope change):
  1. The visual Plex proof is **not** a precondition of W55 — it is a
     *consequence* of it. It moves to after W55 step 7 (container started on
     the local ext4 mount), where it can actually succeed.
  2. Codex proceeds with W55 **now**, without waiting for David. The steps
     that need his approval are the destructive ones inside W55, which its
     own sandbox flow already prompts for — that is the right place for a
     human gate, not an impossible UI interaction.
  3. Ragweld LXC provisioning stays gated on Plex acceptance, but that gate is
     now "W55 complete **and** the visual proof done", in that order.
- General lesson worth keeping: when an agent's only remaining item is "waiting
  on the operator", something must periodically re-validate that the operator
  can still act. A blocked-on-human state is invisible to the blocked agent and
  looks identical to progress from outside.

### W57 `VERIFIED LIVE` — what the local-media transition proved and what remains

**Executed and verified live by Codex, both nodes.** David physically moved the
two drives; Codex performed the shutdown, bridge teardown, filesystem recovery,
local mount activation, service probes, and reboot proof. Two implementation
details improve on the original sketch:

- The `pve-container@4214.service.d` drop-in was rewritten for local disk as
  `RequiresMountsFor=/srv/media` + `After=local-fs.target`, plus **two**
  `ExecStartPre` guards — one asserting the mountpoint is `ext4`, one asserting
  the source is exactly `/dev/mapper/plex--vg-plex--lv`. That is stronger than
  the `Requires=srv-media.mount` I proposed: it survives the unit being renamed
  or replaced, and it pins the device identity, not just the fact of a mount.
- Persistence is a plain `fstab` UUID entry with `nofail`. That pairing is
  right: `nofail` keeps `.173` bootable if the array ever fails, while the
  container guard still refuses to start 4214 onto an empty tree. Availability
  for the node, fail-closed for the workload.

State: `.173` `/srv/media` = local ext4 `rw`, 7.3T/5.4T, `Filesystem state:
clean`; bridge units retired; 4214 running with the guest seeing the real
device; 12 containers up. pve1: no exports, `nfs-server` inactive and disabled,
config files retired, zombie mount cleared, and the stale zero-open device map
removed.

**The filesystem gate ran in full.** `e2fsck -f -n` completed all five passes,
found no structural corruption, and reported only optional extent-tree
optimization. `e2fsck -p` then replayed the pending journal and returned the
filesystem clean before read-write mounting.

**Reboot proof is closed.** `.173` rebooted at `08:59:22 MDT`; Grafana 103,
Scrypted 1043, and Plex 4214 all autostarted. Host and guest showed the exact
local ext4 device, no NFS mount returned, all 12 media containers were healthy,
the expected app probes responded, and Scrypted Python/Node processes held
active render-device file descriptors.

**Visual acceptance is closed.** The signed-in in-app browser played an
original-quality local session, then visibly forced 720p/4 Mbps. The sanitized
Plex session changed from video `copy` to `transcode`; the actual transcoder
carried `-hwaccel`, `vaapi`, and `/dev/dri` markers while labeled VCS/VECS
engine samples were active. Playback was closed and no transcoder remained.

**Still open only as cleanup debt:** the 31.6 GB quarantine
`/srv/media-local-pre-nfs-20260828` on `.173`'s root. Reconcile it against the
live media tree before any deletion; it was deliberately left untouched and is
not a Ragweld provisioning gate.
3. **`/etc/fstab.ragweld-pre-nfs-20260828` on `.173`** — the bridge-era fstab
   backup. The live fstab has since diverged in the one way that matters: the
   UUID line is re-enabled and is now what mounts the array. Restoring this
   backup by reflex during any future rollback would **disable the array's own
   mount line**. Delete it, or rename it `*.superseded-20260828` so it cannot
   be restored without a deliberate decision.

**Independent corroboration of the reboot proof (watchdog, read-only 15:20Z).**
The claim checks out, and the timestamps show it was a real boot-order test
rather than a post-boot assembly — the configuration predates the boot:

| Event | Timestamp (MDT) |
| --- | --- |
| `/etc/fstab` and the `pve-container@4214` drop-in written | `08:54:50` |
| `.173` boot | `08:59:22` |
| `srv-media.mount` active (fstab-generated unit) | `08:59:26` |
| `pve-container@4214.service` active | `08:59:35` |
| `pve-container@1043.service` (Scrypted) active | `08:59:35` |

`journalctl -u pve-container@4214 -b` for that boot shows a clean
`Starting…`/`Started…` with no `ExecStartPre` guard failure; Scrypted still
holds `renderD128`; the guest sees `/dev/mapper/plex--vg-plex--lv`. The mount
landed 4 s into boot and the container 9 s later, in the intended order.

### W59 `OPEN` (P2 for the rollout) — the capacity that matters is the thin pool, and its safety net is switched off

**My error first.** In W53 I quoted "25 GiB available" from `free -h` — that is
RAM, in a memory-budget item — and never looked at storage at all. David called
it: the real capacity is in the LVM layer, and it is roughly a terabyte.

**What is actually there on pve1 (verified 15:50Z):**

| Thing | Value |
| --- | --- |
| `local-lvm` thin pool `pve/data` | 794.30 GiB, **Data 1.58%**, Meta 0.29% |
| `pvesm` available on `local-lvm` | ~819 GiB |
| `vm-100-disk-0` (Ragweld, thin) | 300 GiB allocated, **1.49% used** |
| `vm-120-disk-1` (HAOS, thin) | 32 GiB, 25.19% used |
| **VG free outside the pool** | **16.00 GiB** |
| `thin_pool_autoextend_*` in `lvm.conf` | **unset — autoextend disabled** |

So sizing is a non-issue: 332 GiB provisioned against a 794 GiB pool at 1.58%
used, and because it is thin, the 300 GiB costs nothing until written and can be
grown later with `pct resize 100 rootfs +NNG`. There is no reason to be stingy.

**The sharp edge is what happens if the pool ever does fill.** Ragweld is the
one workload here that grows without a natural ceiling — corpora, Qdrant
vectors, Neo4j, Langfuse ClickHouse, MLflow artifacts, and Docker images all
land inside `vm-100-disk-0`. If `pve/data` reaches 100%, **every thin volume on
the node goes read-only, including HAOS's** — Home Assistant dies alongside
Ragweld, and thin-pool-full is notoriously hard to recover from once metadata
is also stressed. Two facts make that worse here than on a default install:
autoextend is not configured, and there are only **16 GiB of unallocated VG
space** to extend into, so there is no automatic rescue and almost no manual
one either.

**Better way — cheap, and none of it blocks the rollout:**
1. **Alarm before the cliff, not at it.** Ragweld already runs Prometheus and
   Alertmanager. Add a node-level check on `pve/data` `Data%` and `Meta%` with
   a warning at 70% and a page at 85%. If a pve1-side exporter is out of scope,
   the one-line fallback is a root cron on pve1 running
   `lvs --noheadings -o data_percent,metadata_percent pve/data` and mailing on
   threshold.
2. **Turn the safety net on** in `/etc/lvm/lvm.conf`:
   `thin_pool_autoextend_threshold = 80`, `thin_pool_autoextend_percent = 10`.
   With only 16 GiB of VG free it buys one small extension rather than a
   rescue — which is precisely why the alarm in (1) matters more.
3. **Record the ceiling in the rollout evidence** so corpus seeding is a
   deliberate decision against a known budget: ~819 GiB pool-wide, shared with
   HAOS, no meaningful autoextend.

**Note on state:** LXC 100 now exists and is **running** — `cores: 16`,
`memory: 24576`, `swap: 8192`, `rootfs: local-lvm:vm-100-disk-0,size=300G`,
`onboot: 1`, and both `/dev/dri` devices passed through. That matches the
approved spec exactly, including the 24 GiB I tried and failed to argue down.

### W60 `CLOSED — operator decision 2026-08-28: Proxmox firewall stays off (Firewalla MSP Pro is the perimeter); residual carved out as W63` (was P1) — LXC 100's firewall is written but not enforced; the datacenter firewall was never enabled

`2f127476` records "lxc100 boundary acceptance". The SSH half is real and good.
The **firewall half is not in effect**, and the acceptance test the plan
specifies cannot detect that.

**Verified on pve1, 15:40Z:**

| Check | Result |
| --- | --- |
| `/etc/pve/firewall/100.fw` | present, `enable: 1`, `policy_in: DROP`, LAN-SSH/ICMP/DHCP rules |
| `net0` flag on LXC 100 | `firewall=1` ✓ |
| `/etc/pve/firewall/cluster.fw` | **does not exist — datacenter firewall never enabled** |
| `pve-firewall status` | **`disabled/running`** |
| `iptables -S \| grep -c PVEFW` | **0** |
| `iptables -S \| grep -c veth100i0` | **0** |

Proxmox gates the whole firewall stack at the datacenter level. With no
`cluster.fw` and the service reporting `disabled`, **no PVEFW chains exist at
all** — so the guest's `policy_in: DROP` and its three ACCEPT rules are inert
text. LXC 100 is currently reachable on every port from the whole LAN.

**Why the plan's own acceptance would have missed it.** Task 2 Step 6 says to
"prove TCP 58000/58012 is not reachable directly from the LAN". Nothing is
listening on those ports yet — Task 3 has not installed the stack — so that
probe passes today for the wrong reason and would be recorded as boundary
proof. It only becomes a real test *after* Caddy and the API are running, which
is exactly when a wrong answer is expensive. This is the same shape as W8
(a probe that returns the right answer for the wrong reason) and W51 (a reboot
test that passes while the thing under test is absent).

**Also note the earlier read.** W39 observed this same `disabled/running` and
correctly concluded no NFS rule was needed. That was right for NFS and wrong to
leave as the end of the story: the identical fact means the guest firewall is
decorative.

**Better way:**
1. **Enable the datacenter firewall** — create `/etc/pve/firewall/cluster.fw`
   with `[OPTIONS]` `enable: 1`. Do this deliberately and with a LAN SSH
   session already open to pve1 and to `.173`, because enabling it applies host
   policy cluster-wide; confirm `/etc/pve/nodes/*/host.fw` policy leaves node
   management reachable before committing.
2. **Prove enforcement, not configuration.** After enabling:
   `pve-firewall status` must report `enabled`, `iptables -S | grep veth100i0`
   must show the guest chains, and — the real test — from another LAN host
   `nc -vz 192.168.68.225 22` succeeds while a port that is *listening but not
   allowed* is refused. Bind something trivial in the guest for that check
   rather than testing a closed port.
3. **Re-run Task 2 Step 6's probe after Task 4**, when Caddy and the API are
   actually listening, and record both the listening state and the refusal.
   A "not reachable" result against nothing listening is not evidence.
4. If the datacenter firewall is deliberately left off as a homelab choice,
   say so explicitly in the evidence and **delete `100.fw`** rather than
   leaving a file that reads as a boundary — the spec's §5 "LXC firewall with
   SSH accepted only from the management LAN and no public inbound application
   ports" would then be knowingly unmet, and the tunnel plus loopback binding
   become the only boundary.

### W61 `NOTE` — three of my earlier corrections just proved out on the real host

Recording these because two of them were things I had initially gotten wrong,
and the live host is the only place that settles it. Verified inside LXC 100 at
15:45-15:50Z:

- **W4 (bootstrap empty-root) — honored exactly.** `/etc/ragweld` is
  `700 ragweld:ragweld` and contains `deployment-commit` and `owner-password`
  at `600 ragweld:ragweld`. That ordering is only possible if bootstrap ran
  against an empty root and the two files were moved in afterwards, which is
  precisely the rewrite. The original plan text would have failed closed here
  every time.
- **W20 (Flyte callback) — my correction is right and my first answer was
  wrong.** `docker network inspect bridge` in LXC 100 returns **`172.17.0.1`**,
  matching the renderer's
  `training.ragweld_agent_flyte_callback_base_url=http://172.17.0.1:58012`. My
  original `host.docker.internal` would have failed: Flyte task pods resolve
  through the sandbox's k3s CoreDNS and never see the container's
  `extra_hosts`. The `start-runtime.sh` gateway preflight will pass on this
  host.
- **W36 / GLM P3-3 (`BACKEND_PORT`) — live.** `runtime.env` carries
  `BACKEND_PORT`, not the dead `SERVER_PORT`, alongside `SERVER_HOST` from W3.

**Correction to my own reading in the same pass:** I first read `runtime.env`
as missing every `NEO4J_*` key and nearly filed it as a P1. My grep was
`^[A-Z_]+=`, which cannot match `NEO4J_URI` — the digit. The file is fine; the
pattern was wrong. Recording it because a regex that silently under-matches is
exactly the class of error I flagged in W36 item 1.

### W62 `OPEN` (P2, ahead of Task 3 Step 6) — the provider-key copy has one real failure mode left, and one stale-value trap

Task 3 Step 6 copies provider keys from the Mac by scanning `.env` and
`infra/litellm.env` and taking `tail -n 1` of each match. Checked on the Mac
(names and lengths only, no values read into the transcript):

| Key | Source found | Shape |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | `infra/litellm.env` | len 73, not a placeholder |
| `OPENAI_API_KEY` | `.env` | len 167, not a placeholder |
| `VOYAGE` / `COHERE` / `JINA` | `.env` | len 15 / 15 / 13 |

So the copy will find a real OpenRouter key and the historical failure recorded
in project memory — key present only in the parent shell environment while
`infra/litellm.env` held a `disabled` placeholder — **does not apply now**.
Both are present and consistent. Two things still deserve care:

1. **`VOYAGE`/`COHERE`/`JINA` at 13-15 characters are almost certainly
   truncated or placeholder-length values**, not working keys. Copying them
   installs credentials that fail at first use, and a failing reranker or
   embedder reads as a Ragweld bug rather than a bad key. Either verify them
   before copying or copy only `OPENROUTER_API_KEY` and `OPENAI_API_KEY` — the
   two the deployment actually needs — and record the others as deliberately
   not installed.
2. **`litellm.env` in LXC 100 is currently keyless** (bootstrap wrote only its
   comment line) and `/etc/ragweld/tribrid_config.json` does not exist yet, so
   `start-runtime.sh` will fail closed until Task 3 Steps 6-7 run. That is
   correct behaviour, not a defect — but it means any Task 4 loopback failure
   before those steps is a sequencing artifact and must not be diagnosed as a
   stack problem.

### W63 `CLOSED — solved better than I specified (see W70)` (was P1) — the one thing the Firewalla cannot cover, and it is my own W3 that created it

**The decision (David, 2026-08-28):** the Proxmox datacenter firewall stays
off. A Firewalla MSP Pro is the perimeter with IPS/IDS, and there is no
port-forward — public reach is Cloudflare Tunnel outbound-only plus Authelia.
That is a sound perimeter and W60 is closed on it.

**What a perimeter device structurally cannot do.** This is topology, not a
comment on the hardware. Traffic from one LAN host to another on the **same
subnet** — say a laptop at `192.168.68.x` to LXC 100 at `192.168.68.225` — is
switched directly and never traverses the router. No gateway appliance, at any
price, can filter or even see it. The Proxmox guest firewall was the only
control that sat in that path, and it is now deliberately absent.

**Why that matters here specifically, and why it is my fault.** Almost the
entire stack is already loopback-bound and therefore unreachable regardless:
32 Compose port bindings across the two files are `127.0.0.1:`, and the
Caddyfile sets `default_bind 127.0.0.1`. The exception is the Ragweld API.
**W3 was my directive** — I told the plan to bind `SERVER_HOST=0.0.0.0` so
Prometheus could scrape and Flyte could call back from containers, and
`/etc/ragweld/runtime.env` now carries exactly that with `BACKEND_PORT=58012`.

The Ragweld API has **no authentication of its own**. Authelia guards the
public path at Caddy; it does not guard the API's own socket. So once the stack
starts, any device on the LAN can reach `http://192.168.68.225:58012/api/…`
unauthenticated — config mutation, corpus deletion, chat, training control, the
whole surface — bypassing Authelia entirely. That is a bigger hole than
anything the guest firewall's SSH rules were protecting, and it exists only
because of my W3.

**Better way — no Proxmox firewall involved, which keeps David's decision
intact.** Constrain the socket inside the guest, where Docker's own rules live:

```bash
# in LXC 100, /etc/nftables.conf (Debian 13 already uses the nft backend)
table inet ragweld {
  chain input {
    type filter hook input priority 0; policy accept;
    tcp dport 58012 ip saddr 127.0.0.1 accept
    tcp dport 58012 ip saddr 172.16.0.0/12 accept   # docker bridge, incl. 172.17.0.1
    tcp dport 58012 drop
  }
}
```
`systemctl enable --now nftables`. A separate `inet` table with `policy accept`
and targeted drops coexists with Docker's chains rather than fighting them.
Loopback keeps working for Caddy, `172.17.0.1` keeps working for Prometheus and
the Flyte callback (W20 verified that gateway is exactly `172.17.0.1` on this
host), and the LAN is refused.

**Prove it, don't assume it** — after Task 4, from another LAN machine:
`curl -m 5 http://192.168.68.225:58012/api/health` must fail, while the same
call from inside LXC 100 and from a container via `172.17.0.1` succeeds. A
closed-port refusal before the stack is running is not evidence (the W60/W8
lesson).

**Housekeeping — DONE 2026-08-28 (watchdog, operator-authorized).**
`/etc/pve/firewall/100.fw` was renamed to `100.fw.disabled-20260828` on pve1,
with a copy preserved at `/root/100.fw.backup-20260828`. Proxmox parses only
`<VMID>.fw`, so the renamed file is inert *and* no longer reads as an active
boundary; the original is recoverable if the decision is ever revisited.
Verified after the change: `pve-firewall status` still `disabled/running`,
LXC 100 still `running`, SSH path unaffected.

### W64 `FIXED 8c9f171c — Authelia healthy on the node` (was P1, blocking) — Authelia cannot parse its own OIDC key: the template is wrapped in YAML quotes

**This is what is stopping the rollout right now.** `ragweld.service` runs, brings
up 22 containers, then fails: `container ragweld-authelia-1 is unhealthy` →
`compose up --wait` exits 1 → unit dies (`Result=success` is misleading;
`journalctl -u ragweld.service` shows `status=1/FAILURE`). Authelia itself is
crash-looping, `Exited (1)`, with the same fatal every restart:

```
'identity_providers.oidc.jwks[0].key' could not decode to a schema.CryptographicKey:
    illegal base64 data at input byte 0
```

**Ruled out, so the cause is narrow:**
- `X_AUTHELIA_CONFIG_FILTERS=template` **is** set in the running container, so
  the template filter is active (verified via `docker inspect`).
- `/etc/ragweld/authelia/oidc-rsa.pem` **is** a valid PKCS#8 key — it begins
  `-----BEGIN PRIVATE KEY-----\nMIIG/AIBADAN…`, exactly what bootstrap's
  `openssl genpkey … rsa_keygen_bits:3072` produces.
- The `chown: /config/…: Read-only file system` lines are entrypoint noise from
  the `:ro` mounts and are **not** the failure.

**The defect is in repo source**, `deploy/proxmox/authelia/configuration.yml:53`:

```yaml
        key: '{{ secret "/config/oidc-rsa.pem" | mindent 12 "|" | msquote }}'
```

`mindent N "|"` exists precisely to emit a YAML **block scalar** — it supplies
the `|` indicator and the indented PEM body — and `msquote` handles the
quoting. Wrapping that in single quotes collapses the whole thing into a
single-line quoted scalar, so Authelia receives literal text where it expects a
key and fails to base64-decode at byte 0. The surrounding `'…'` must go:

```yaml
        key: {{ secret "/config/oidc-rsa.pem" | mindent 8 "|" | msquote }}
```

(`key:` sits at 8 spaces, so the block body indents to 8; confirm against the
final file rather than trusting the count.)

**Why our tests did not catch it — the more important half.** The contract test
at `tests/unit/test_proxmox_deployment_contract.py:864-869` asserts the `jwks`
entry equals the exact string *including the quotes*. It pins the typo as the
contract. Every structural assertion we wrote about Authelia — deny-by-default,
the owner rule, the OIDC callback, the client id — checks **text we authored**,
never whether Authelia can load the result. This is the W8 pattern again: a
check that returns the right answer to the wrong question.

**Fix, in this order:**
1. Correct line 53 and update the test's expected string to match.
2. Add the gate that would actually have caught it, as a real test:
   `docker run --rm -v <cfg>:/config/configuration.yml:ro … authelia/authelia:4.39.20 authelia validate-config --config /config/configuration.yml`
   with the template filter enabled and a throwaway generated key. It is a real
   process against the pinned image — no mocks — and it fails on exactly this
   class of error. Mark it `requires_docker` so the default lane skips cleanly.
3. Redeploy and confirm `ragweld-authelia-1` reaches healthy and
   `ragweld.service` stays active.

### W66 `RESOLVED CORRECTLY 2026-08-28` (the trap was avoided; see the note at the end) — the corrected Authelia config is no longer parseable as YAML, and the test must not be "fixed" by reverting

The W64 fix is in the working tree and is **correct for Authelia**:

```yaml
        key: {{ secret "/config/oidc-rsa.pem" | mindent 10 "|" | msquote }}
```

It now breaks our test — `test_proxmox_authelia_configuration_is_owner_only_and_deny_by_default`
fails with `yaml.constructor.ConstructorError: while constructing a mapping`,
and `yaml.safe_load()` on the file confirms it.

**This is expected and is not a regression.** `{{` opens a flow mapping in
YAML, so `key: {{ … }}` is invalid YAML *by design*. Authelia's template filter
runs **before** the YAML parser — the file is a **template**, not a YAML
document, and it only becomes YAML after `{{ secret … }}` is substituted. The
previous quoted form parsed cleanly precisely because it was wrong.

**The trap, stated plainly: do not restore the quotes to make the test green.**
That would produce a passing suite and a crash-looping Authelia — the same
inversion that let this ship in the first place, where the test pinned the typo
as the contract. If the suite and the running service disagree, the service is
right.

**Fix the test to match what the artifact actually is:**
1. Render before parsing. Substitute the template the way Authelia does — read
   the `{{ secret "<path>" … }}` line, replace it with a block scalar holding a
   throwaway PEM, then `yaml.safe_load` the result and keep every existing
   structural assertion (deny-by-default, the `owners` one-factor rule, session
   cookies, SQLite storage, the exact Langfuse callback).
2. Assert the template line itself as **text**, and assert it is *not* quoted —
   a positive control that fails if anyone reintroduces `'…'`.
3. Keep the `authelia validate-config` gate from W64 step 2. It is the only
   check that would have caught the original defect, and now also the only one
   that proves the rendered template is loadable.

**Outcome (watchdog, 16:15Z): the trap was avoided and the test fix is better
than what I proposed.** The quotes were *not* restored —
`configuration.yml:53` still reads `key: {{ secret … | mindent 10 "|" |
msquote }}`. The test now: collects every line containing
`{{ secret … | mindent … | msquote`, asserts each value **starts** with
`{{ secret ` and **ends** with ` }}` (the positive control against
re-quoting), then builds a `yaml_surrogate` by re-adding quotes *only for
parsing*, guarded by `assert yaml_surrogate != source` so a silent no-op
substitution fails. Every structural assertion is preserved. That is cleaner
than my "block scalar with a throwaway PEM" suggestion — pure text, no fixture
key — and it encodes the real invariant: the file is a template, and the
template must stay unquoted.

### W65 `OPEN` (P3) — W62 was not applied; the placeholder-length keys were copied

`litellm.env`/`runtime.env` in LXC 100 now carry `COHERE_API_KEY`,
`JINA_API_KEY` and `VOYAGE_API_KEY` alongside the two real ones. Those are the
13-15 character values W62 flagged as placeholder-length. They are inert until
something calls those providers, at which point a bad key will present as a
reranker or embedder fault in Ragweld. Either verify them or remove the three
lines and note them as deliberately not installed.

### W63 status: **still unapplied** — no nft rule for 58012 exists in the guest.

The API is not listening yet (`ragweld.service` is down), so the LAN exposure
has not materialised. That makes now the cheap moment to add the rule, before
Task 4 brings the socket up.

### W67 `FIXED 8c9f171c — validate-config gate is in the suite` — nothing yet proves Authelia can *load* the config; the device-GID work is verified correct

**Still missing: the `validate-config` gate.** `grep validate-config` over the
contract test returns nothing. The rewritten test proves the template's
*shape* and that it stays unquoted — genuinely valuable — but no test runs
Authelia against the file. The defect that cost this deployment was precisely
a config Authelia could not load while every structural assertion passed, so
shape-checking is the layer that already failed us once. Concrete, runnable,
no mocks, real pinned image:

```python
@pytest.mark.requires_docker
def test_authelia_can_actually_load_the_rendered_configuration(tmp_path: Path) -> None:
    # throwaway key; never the real one
    subprocess.run(["openssl","genpkey","-algorithm","RSA","-pkeyopt",
                    "rsa_keygen_bits:2048","-out",str(tmp_path/"oidc-rsa.pem")], check=True)
    (tmp_path/"users_database.yml").write_text(USERS_FIXTURE, encoding="utf-8")
    for name in ("session","storage","oidc_hmac"):
        (tmp_path/name).write_text("x"*64+"\n", encoding="utf-8")
    result = subprocess.run([
        "docker","run","--rm",
        "-e","X_AUTHELIA_CONFIG_FILTERS=template",
        "-v",f"{PROXMOX_AUTHELIA_CONFIG}:/config/configuration.yml:ro",
        "-v",f"{tmp_path}/oidc-rsa.pem:/config/oidc-rsa.pem:ro",
        "-v",f"{tmp_path}/users_database.yml:/config/users_database.yml:ro",
        "authelia/authelia:4.39.20",
        "authelia","validate-config","--config","/config/configuration.yml",
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
```

Point it at the same pinned tag the overlay uses so the test and production
agree on the parser. This is the single highest-value test left in the slice:
it is the only thing that would have caught W64 before the node did.

**Device GIDs — verified correct, including the trap they avoided.** The new
`test_proxmox_rollout_passes_every_nested_runtime_device_with_persistent_ownership`
asserts `--dev0 …renderD128,mode=0660,gid=992`, `--dev1 …card0,mode=0660,gid=44`,
`--dev2 path=/dev/kmsg,mode=0660`. Checked against live reality:

| | `render` | `video` |
| --- | --- | --- |
| pve1 host | **993** | 44 |
| inside LXC 100 | **992** (contains `ragweld`) | 44 (contains `ragweld`) |

`gid=` sets ownership **as seen inside the container**, so `992` is right and
the host's `993` would have been wrong — an easy off-by-one to get backwards,
and they got it right. `ragweld` is already a member of both groups, and the
guest currently shows `crw-rw---- root render` / `root video` on both nodes.

**Two follow-through gaps, not defects:**
- `/dev/kmsg` is **absent inside LXC 100** — the plan text asserts `dev2` but
  the live container has no such device. Plan updated, node not yet.
- The Authelia fix is uncommitted working-tree only; the node still shows
  `ragweld-authelia-1  Exited (1)` and `ragweld.service inactive`. Nothing is
  wrong with that ordering — source first — but the deployment stays down
  until it is applied there.

### W68 `VERIFIED` — I ran the W67 gate myself: the W64 fix is correct, and the exercise found three things the eventual test must handle

Rather than wait for another deploy cycle to learn whether the Authelia fix
works, I ran the proposed gate against the real pinned image with the corrected
config. Final result:

```
Configuration parsed and loaded successfully without errors.
```

**So the W64 fix is confirmed good.** Un-quoting the `jwks` template is
sufficient; nothing else in `configuration.yml` is wrong. Redeploying it should
bring `ragweld-authelia-1` healthy.

**A hypothesis I formed and then disproved — worth recording so nobody
re-derives it.** My first run reported *every* section missing
(`session: option 'cookies' is required`, `storage: … must be provided`,
`identity_providers: oidc: option 'jwks' is required`, …). That pattern looks
exactly like "the template filter never ran, so the YAML failed to parse", and
I nearly filed a P1 claiming `X_AUTHELIA_CONFIG_FILTERS=template` is not the
right lever in 4.39.20 and that production was mis-configured. **It is the
right lever.** A controlled A/B — env var alone vs `--config.experimental.filters=template`
— showed both run the filter identically. The "everything missing" output was
entirely my own harness bug cascading: a failed secret read makes the whole
config load fail, which then reports every option as absent.

**Three findings the eventual `requires_docker` test must encode:**
1. **macOS bind-mount trap.** Mounting fixture files from `$TMPDIR`
   (`/var/folders/…`) silently gives the container an **empty directory** —
   Docker's VM does not share that path — producing
   `error calling secret: read /config/oidc-rsa.pem: is a directory`. Fixture
   files must live under the repo (shared) or another shared path. A test
   written with `tmp_path` will fail on macOS for a reason unrelated to the
   config; use a repo-local gitignored dir, or assert the mount is a regular
   file inside the container first.
2. **Cascading validation output is misleading.** One failed template read
   reports as a dozen unrelated "required option" errors. The test should
   assert on `returncode == 0` and surface full stdout+stderr on failure, and
   its docstring should warn that a wall of "option required" errors usually
   means one upstream load failure, not a dozen defects.
3. **Env vars the real container gets from Compose secrets must be supplied.**
   `AUTHELIA_SESSION_SECRET`, `AUTHELIA_STORAGE_ENCRYPTION_KEY`,
   `AUTHELIA_IDENTITY_PROVIDERS_OIDC_HMAC_SECRET`, and
   `AUTHELIA_IDENTITY_VALIDATION_RESET_PASSWORD_JWT_SECRET` — the last is
   required by 4.39.20 and is **not** in our overlay. Worth checking whether
   the deployed container needs it too, or whether Authelia only demands it
   when password reset is enabled; our config sets
   `password_reset.disable: true`, so it may be satisfied there. Confirm on
   the next successful start rather than assuming.

Exact reproduction (all mounts repo-local, throwaway 2048-bit key, digest and
users fixtures inline) is in the ledger entry for this item.

### W69 `WITHDRAWN — I was reading a stale diff; the doer already resolved this correctly and proved it live`

I filed an inconsistency between two `/dev/kmsg` strategies. It does not exist.
I based it on an `--dev2 path=/dev/kmsg,mode=0660` assertion I had read in an
earlier tick's diff, without re-checking the file before writing. Current
state, verified:

- `tests/unit/test_proxmox_deployment_contract.py:879-889` —
  `test_flyte_gets_a_container_scoped_kmsg_sink_without_host_kernel_exposure`
  asserts `flyte["devices"] == ["/dev/null:/dev/kmsg"]` **and** the negative
  `assert "--dev2 path=/dev/kmsg" not in source`. The contract explicitly
  forbids the thing I claimed was being added.
- Rollout plan lines 173-179 say it outright: kubelet exited with
  `open /dev/kmsg: no such file or directory`; **do not** pass pve1's real
  kernel-message device into the privileged LXC; map `/dev/null:/dev/kmsg` on
  the Flyte container only — "proven live with that mapping: its nested k3s
  node reached `Ready` while pve1's `/dev/kmsg` remained outside the LXC
  boundary."
- Line 286 requires "no `/dev/kmsg`" among the `pct create` device entries.

So the doer diagnosed a real kubelet failure, chose the narrower fix, wrote a
negative assertion against the broader one, and verified k3s reaching `Ready` —
better than the recommendation I was about to make, and already empirically
settled rather than argued.

**Process correction for me, and this is the second time:** I wrote a finding
from a diff captured in an earlier tick instead of re-reading current state.
The same shape produced the wrong `NEO4J_*` alarm in W61 (a bad regex) and the
wrong attribution in ticks 23-24. Rule I am adopting: **before filing any
finding, re-read the file as it is now** — diffs age between ticks, and this
codebase moves faster than my sampling interval.

### W70 `VERIFIED` — the deployment is up, and the host boundary they built is stronger than the one I asked for

`8c9f171c fix(proxmox): harden auth and flyte startup` is committed and pushed.
Verified live at 16:45-16:50Z:

- **`ragweld-authelia-1  Up (healthy)`** — W64 closed on the node, matching the
  `validate-config` result I predicted in W68.
- **`ragweld.service  active`**, 24 containers up, `/api/ready` returns **200**.
- **`validate-config` is now in the contract suite** — W67 closed.

**W63 closed, and the implementation is better than my prescription.** I asked
for a single-port nft rule (allow 58012 from loopback and `172.16.0.0/12`, drop
the rest). What exists is `table inet ragweld_guard` at hook priority **-200**,
i.e. evaluated before Docker's chains:

```
chain input_guard { policy accept
  iifname "lo" accept
  ct state established,related accept
  ip saddr 192.168.68.1 udp sport 67 udp dport 68 accept   # DHCP
  ip saddr 192.168.68.0/24 ip protocol icmp accept
  ip saddr 192.168.68.0/24 tcp dport 22 ct state new accept
  ip6 … nd-* accept
  iifname "eth0" drop                                       # default deny
}
chain forward_guard { … iifname "eth0" drop }
```

That is a **default-deny on the LAN interface with an explicit allowlist**,
not a port patch — it covers 58012 and every other port, including ones nobody
has thought of yet, and it re-implements the intent of the deleted `100.fw`
*inside the guest where it actually executes*. Persistent via
`/etc/nftables.conf` with `nftables` enabled.

**Proven by probe, not by reading:**

| From | Result |
| --- | --- |
| Mac (`192.168.68.123`) → `.225:58012` | filtered (HTTP 000) |
| Mac → `.225:22` | open (allowlisted) |
| **pve1 → `.225:58012`** | **HTTP 000** — and pve1 is same-bridge, so this is the guest guard, not the Firewalla |
| inside guest → `127.0.0.1:58012` | 200 |
| inside guest → `192.168.68.225:58012` | 200 |

And the paths it must *not* break are intact: Prometheus shows
`up  http://host.docker.internal:58012/metrics` — container→host through
`docker0` is unaffected by the `eth0` drop, exactly as the design requires.
(The one `down` target is `:58080`, the local vLLM that is deliberately absent
on this Intel host — expected, not a regression.)

**My grep was wrong again — third time.** I reported "nft58012=0" from
`nft list ruleset | grep -c 58012`; the guard does not name the port at all
because it denies by interface. A negative grep is not evidence of absence when
you are guessing at the implementation's shape. Same failure family as the
`NEO4J_*` regex (W61) and the stale-diff W69: **verify by behaviour — probe the
socket — not by pattern-matching config.** That is now the third data point and
I am treating it as the rule, not the exception.

**Remaining before external acceptance:** DNS/Cloudflare (W54 — export the zone
before the nameserver change, since `dig` cannot enumerate DKIM/DMARC/CAA),
thin-pool alerting before corpus seeding (W59), and the placeholder-length
provider keys (W65).

### W71 `FIXED — node re-rendered and verified; item 2 (preflight guard) still open` — the production model alias changed in source but the node was still rendered with the old one

The renderer now sets `PRODUCTION_MODEL_ALIAS = "openai.gpt-5.6-terra"`
(`deploy/proxmox/render_config.py:12`). The alias is genuine — 16 entries in
`data/models.json`, present in the generated `infra/litellm-config.yaml:1046`
routing to `openrouter/openai/gpt-5.6-terra` — so the swap itself is sound.

**But the deployed config still carries the old alias.** Read from the node:

| field | on `.225` | source now renders |
| --- | --- | --- |
| `generation.gen_model` | `openai.gpt-5.4-mini` | `openai.gpt-5.6-terra` |
| `chat.litellm.default_model` | `openai.gpt-5.4-mini` | `openai.gpt-5.6-terra` |
| `ui.chat_default_model` | `openai.gpt-5.4-mini` | `openai.gpt-5.6-terra` |
| `evaluation.ragas_judge_model` | `openai.gpt-5.4-mini` | `openai.gpt-5.6-terra` |

`/etc/ragweld/tribrid_config.json` was rendered once at Task 3 Step 7 and is
**not** regenerated by `start-runtime.sh` — the launcher only validates that it
exists, parses, and carries a matching Flyte callback host. So restarting the
service, or even redeploying the repo, leaves the old model in place. Whatever
the external acceptance run exercises would be `gpt-5.4-mini`, while the repo,
its tests, and any evidence written from source all say `gpt-5.6-terra`. That
is a silent source-versus-runtime divergence in the one value that determines
what every generation call actually costs and returns.

**Better way:**
1. Re-run the renderer on the node after this lands —
   `sudo -u ragweld /opt/ragweld/.venv/bin/python /opt/ragweld/deploy/proxmox/render_config.py --source /opt/ragweld/tribrid_config.json --output /etc/ragweld/tribrid_config.json`
   — then restart `ragweld.service` and confirm the four fields above report
   the new alias.
2. Make the drift impossible to miss rather than relying on memory: have
   `start-runtime.sh`'s preflight compare the rendered
   `generation.gen_model` against `render_config.PRODUCTION_MODEL_ALIAS` and
   fail closed on mismatch, the same shape as the existing bridge-gateway
   check it already performs. A rendered config that disagrees with the
   renderer is exactly as wrong as a callback that disagrees with the bridge.
3. Record the alias in the deployment evidence, so the acceptance run states
   which model it actually exercised.

**Retracted (David, 11:05Z).** I appended a note suggesting evaluation and
enrichment could stay on the cheaper `-mini` alias to save cost. That was wrong
and out of scope: the operator's standing rule is paid 5.6-class API aliases
for eval/judge/chat traffic, and he has since specified **5.6 models or
`z-ai/glm-5.3-flash`** explicitly. I re-opened a settled decision using the
exact consideration it was already decided on — the same error I made and
withdrew on the 24 GiB memory cap in W53. The alias change to
`openai.gpt-5.6-terra` is **compliant**, and the renderer driving every model
field from one constant is correct, not a limitation.

**This makes the drift finding above sharper, not weaker.** The node is serving
`openai.gpt-5.4-mini` — not a 5.6 model, not `glm-5.3-flash`. So the running
deployment is out of compliance with the operator's model instruction until the
config is re-rendered, and any acceptance run performed now would exercise a
model that was not specified. Items 1-3 above stand unchanged and are the fix.

### W72 `FIXED da349c90` — the daily catalog refresh left `infra/litellm-config.yaml` regenerated-but-uncommitted, so HEAD was out of lockstep

`c629717b chore(models): daily catalog refresh` came in from origin and was
merged at `07ecb5eb`. It rewrote `data/models.json` substantially
(+356/−1574). The generated gateway config was then regenerated in the working
tree but **not committed**:

| | `gpt-5.6-terra` entries | |
| --- | --- | --- |
| `HEAD:infra/litellm-config.yaml` | 8 | committed, **stale** |
| working tree | 4 | regenerated, correct |
| `generate_litellm_config.py --check` | passes (371 aliases) | against the *working* file |

So the lockstep gate is green only because the uncommitted regeneration is
present. Anyone cloning `main` — or the pve1 deployment pulling the published
commit — gets the stale config, and `--check` fails for them. That gate is in
the repo's standard verification list, so it would surface as a confusing
failure unrelated to whatever they were doing.

**Fix:** commit `infra/litellm-config.yaml` with the merge, or regenerate and
commit it as a follow-up. It is generated output that must move with
`data/models.json`; the two are a pair exactly like the glossary mirror in W26.

**Also unpushed:** `main` is at `07ecb5eb` while `origin/main` is `c629717b` —
the merge and `1eaa725e fix(proxmox): require GPT-5.6 production models` are
local only.

**Alias sanity, verified with the correct field** (`gateway_alias`, not
`id`/`name`): `openai.gpt-5.6-terra` **is** present, alongside
`openai.gpt-5.4-mini`, in 371 aliases. The refresh did not remove it, so the
new policy test and the renderer constant are both satisfiable. Note for the
model rule: **`z-ai/glm-5.3-flash` is _not_ a gateway alias in this catalog**
(the string appears in the file, but not as a routable `gateway_alias`), so if
that model is ever wanted as a production default it needs a catalog entry
first — it is currently only reachable the way the adversarial reviews call it,
directly through OpenRouter.

**Method note, fifth instance.** I nearly filed a P1 claiming the refresh had
deleted every 5.6 alias, because I queried `m.get('id') or m.get('alias') or
m.get('name')` — none of which exist. The field is `gateway_alias`. Same family
as the `NEO4J_*` regex, the stale-diff W69, the `grep -c 58012` nft miss, and
the raw-count models.json probe. The rule is no longer "be careful": before
querying any structure, print one element's keys. I did that here, which is why
this is a note instead of a false alarm.

### W73 `VERIFIED` — both model findings closed on the node; one durable guard still missing, and a timing near-miss worth naming

**W71 closed.** All six model fields on `.225` now read `openai.gpt-5.6-terra`,
verified individually rather than by spot-check:

```
gen_model / enrich_model / chat.litellm.default_model /
ui.chat_default_model / evaluation.ragas_judge_model /
evaluation.promptfoo_grader_model   -> openai.gpt-5.6-terra
```

`ragweld.service` active, 25 containers, `/api/health` 200, `/api/ready` 200.
The deployment now complies with the operator's 5.6-class model instruction.

**W72 closed** by `da349c90 chore(models): restore catalog lockstep` —
`HEAD:infra/litellm-config.yaml` and the working tree now agree (4 `terra`
entries each), the tree is clean, and `main == origin/main == da349c90`, so the
published commit is self-consistent for anyone cloning it.

**Still open: the durable half of W71.** `grep PRODUCTION_MODEL_ALIAS
deploy/proxmox/start-runtime.sh` returns nothing — the preflight still does not
compare the rendered `generation.gen_model` against the renderer's constant. The
drift it would catch just happened for real and cost a manual round trip, and
the launcher already performs exactly this shape of check for the Flyte
bridge-gateway host. One more comparison in the same preflight, failing closed
on mismatch, makes "the node is running a model nobody chose" structurally
impossible rather than something a watchdog has to notice.

**Timing near-miss, recorded because it is a different failure mode from the
previous five.** I probed `/api/ready` at 17:30:42Z with `-m 6` and got `000`,
and my first instinct was that the re-render had broken readiness. It had not:
the service log shows the API reaching ready at **17:31:07-08**, i.e. I sampled
during the restart the re-render required. A retry returns 200. The earlier
misses were structural guesses; this one is a **race against a change I had
just asked for**. Rule to add: after any restart-inducing fix, probe with a
retry window (or read the unit's own log timeline) before calling a transient a
regression — otherwise the watchdog manufactures the very alarms it exists to
prevent.

### W74 `CLOSED — paid proof recorded in the evidence file` — the running gateway really does serve the new alias; what that did *not* establish (now established)

No new commits this tick, clean tree. I checked the staleness risk I considered
most likely after the model swap: LiteLLM loading a config predating the
catalog regeneration. It does not.

- `ragweld-litellm-1` started **17:30:09Z**; `infra/litellm-config.yaml`
  mtime **17:21:48Z** — the container is newer than the config.
- `GET /v1/models` with the generated `LITELLM_API_KEY` → **HTTP 200**,
  **371 served aliases**, and `openai.gpt-5.6-terra` **present** (as is
  `openai.gpt-5.4-mini`).
- The in-container config carries 4 `gpt-5.6-terra` entries, matching the repo.

So the routing layer is consistent end to end: catalog → generated config →
mounted file → running gateway → served alias.

**What this deliberately does not prove, and must not be read as proving.**
Serving an alias means LiteLLM will *accept* the request and knows where to
send it. It says nothing about whether OpenRouter will *fulfil* it — model
access on the account, credit balance, or upstream availability are all
untested by a `/v1/models` listing. Rollout acceptance #9 ("a real paid
OpenRouter request succeeds through Ragweld → LiteLLM with no direct-provider
path, retry, or fallback") therefore remains genuinely open, and the natural
first failure would look like a working chat UI returning an upstream error.

I stopped short of making that call deliberately: it costs money and it is the
doer's Task 4/8 acceptance step, not a watchdog read. Worth doing early rather
than at external-acceptance time, since a model-access rejection is cheapest to
discover before DNS and SSO are in the path.

### W75 `IMPLEMENTED in the capacity guard (see W81)` (P2, sharpens W59 with measured growth) — the nearer wall is the 300 GB volume, not the 794 GB pool, and standing the stack up already consumed 44 GB

Measured on pve1 at 18:00Z, roughly two hours after LXC 100 was created and
**before any corpus data exists**:

| | at creation | now | delta |
| --- | --- | --- | --- |
| `pve/data` pool | 1.58% | **6.92%** | +5.3pp (~42 GB) |
| pool metadata | 0.29% | 0.46% | — |
| `vm-100-disk-0` (300 GB thin) | 1.49% | **15.64%** | +14.1pp (**~44 GB**) |
| guest `df /` | — | 38 G used / 295 G, **242 G free** | — |

**Correction to my own W59 framing.** I wrote it as a thin-pool exhaustion
risk. The arithmetic says the *volume* is the nearer wall: the guest
filesystem is capped at 300 GB with 242 GB free, while the pool still has
~739 GB free. Ragweld hits its own 300 GB ceiling long before it can exhaust
`pve/data`. Both matter, but they fail differently and the first one is
recoverable:

- **Volume full (nearer):** the guest's `/` fills. Postgres, Qdrant, Neo4j and
  ClickHouse all start erroring; Ragweld breaks, HAOS is untouched. Recovery is
  easy — `pct resize 100 rootfs +100G` against 739 GB of free pool, thin so it
  costs nothing until used.
- **Pool full (further, worse):** *every* thin volume on the node goes
  read-only, HAOS included, autoextend is still unset and there are only
  16 GiB of unallocated VG to extend into. This is the one with no cheap
  recovery.

**What 44 GB for an empty stack implies for Task 7.** That is images,
databases and observability at rest, with zero corpora. Corpus seeding adds
source documents, Qdrant dense+sparse vectors, the Neo4j graph, Langfuse
ClickHouse traces and MLflow artifacts — all inside `vm-100-disk-0`. The
budget conversation should therefore be "how much of 242 GB does seeding
consume", not "is 794 GB enough".

**Revised guidance, replacing W59's single threshold:**
1. Alert on **both** levels, since they have different blast radii: guest
   `df /` at 75% warn / 90% page (Ragweld-only impact, easy fix), and
   `pve/data` `Data%`/`Meta%` at 70% / 85% (node-wide, hard fix).
2. `thin_pool_autoextend_threshold = 80` / `..._percent = 10` remains unset —
   still worth setting, while remembering 16 GiB is one small extension, not a
   rescue.
3. Re-measure `vm-100-disk-0` immediately after the first corpus is indexed.
   That single number turns the seeding budget from an estimate into a
   measurement, and it is free to collect.

### W65 / password residue — status, unchanged and still tracked

- All five provider keys remain installed, including the three
  placeholder-length ones (`VOYAGE_API_KEY`, `COHERE_API_KEY`,
  `JINA_API_KEY`). W65 stands: they will fail at first use and read as a
  Ragweld reranker/embedder fault rather than a bad credential.
- `/etc/ragweld/owner-password` is **still present in plaintext**. That is
  expected at this stage — the rollout plan rotates it at Task 6 Step 5 after
  the first successful external login, which has not happened. Recording it so
  it does not survive to production unnoticed: it is mode `0600` in a `0700`
  root, so the exposure is small, but a bootstrap passphrase sitting on disk
  after rotation would be a real residue.

### W76 `VERIFIED (no finding)` — the Docling/OpenCV gap was found and closed completely, and the runtime `validate-config` gate is a better answer than the one I asked for

In-flight (uncommitted) work on `Dockerfile`, `deploy/proxmox/start-runtime.sh`
and the contract test. Checked all of it against the node rather than the diff:

**Docling/OpenCV on Debian 13 — closed at every layer, nothing left to inject.**
`import cv2` needs `libgl1` and `libglib2.0-0t64` on trixie. The doer:
- added `require_docling_runtime()` to `start-runtime.sh`, which runs
  `.venv/bin/python -c 'import cv2'` and dies with an actionable message;
- installed both packages on the node — verified: `cv2 OK 4.13.0`,
  `ii libgl1:amd64 1.7.0-1+b2`, `ii libglib2.0-0t64:amd64 2.84.4-3~deb13u3`;
- added both to the rollout plan's Task 3 Step 1 apt line (line 387), so a
  rebuild does not hit the same wall;
- moved the image base to `python:3.12-slim-trixie` with the two libs.

That is the `lsof`/W6 pattern executed completely and without prompting — node,
plan, preflight, and image all moved together. **Ordering verified too**, since
a fail-closed guard placed after the thing it guards is useless:
`require_docling_runtime` sits at position 31 in `main()`, before
`compose_args` is built (44) and well before `up -d --wait` (50).

**Already in HEAD and better than my W67 recommendation:**
`start-runtime.sh:234-235` runs

```
docker compose … run --rm --no-deps authelia   authelia validate-config --config /config/configuration.yml
```

immediately *before* `up -d --wait`. I asked for `validate-config` as a
`requires_docker` **test**; this is the same check as a **runtime preflight**,
against the real mounted config and the real pinned image, on every start. It
converts the W64 failure mode — a crash-looping container discovered through a
`--wait` timeout and an unhealthy status — into an immediate, readable error
before any service starts. The test-level gate and this are complementary, and
both now exist.

**Still open, and this is the moment for it:** `grep PRODUCTION_MODEL_ALIAS
deploy/proxmox/start-runtime.sh` still returns 0. The W71 drift guard —
compare rendered `generation.gen_model` against the renderer constant, fail
closed on mismatch — belongs in exactly the preflight block being edited right
now, three lines below `require_bridge_gateway_matches_rendered_callback`,
which already reads and validates that same rendered file.

### W77 `OPEN` (P1) — Docling PDF processing blocks the event loop: the whole API goes unresponsive during indexing, including dependency-free `/api/health`

**Observed live at 18:30Z**, not inferred:

| Signal | Value |
| --- | --- |
| `/api/health` (dependency-free liveness) | **`000`** — no response, 10 s timeout |
| `/api/ready` | **`000`** — no response, 30 s timeout |
| listening socket | `LISTEN` **`Recv-Q 17`** / Send-Q 2048 — 17 connections queued, unaccepted |
| uvicorn uptime | **1h00m58s** — not a restart |
| uvicorn RSS | **~4.4 GB** |
| unit log, same moment | `Accelerator device: 'cpu'` / `Processing document A11_MissionReport.pdf` / rapidocr+onnxruntime |

The process is alive and holding the listen socket, but not *accepting* — the
backlog is filling while Docling OCRs a PDF on CPU. This is CPU-bound native
work stalling the async loop, not a dependency outage: `/api/health` performs no
dependency checks at all and still times out.

**Why this matters more than it looks:**
- `start.sh`'s own readiness gate polls `/api/health`; a restart during
  indexing would fail its wait and could be read as a broken deploy.
- Behind Caddy, every workbench request times out while a corpus indexes — to a
  remote user the entire deployment looks dead, not busy.
- Prometheus scrapes `/metrics` on the same loop, so observability goes blind
  exactly when load is highest, and the gap will look like a node problem.
- **Rollout collision:** Task 7 is corpus seeding and Task 8 is external
  browser acceptance. Seeding a real corpus will make Task 8's UI pass hit a
  dead workbench, and that will present as a deployment failure rather than a
  known blocking-indexer.
- The 4.4 GB RSS is also live evidence for W75's memory line: one indexing API
  against a 24 GiB cap shared with HAOS.

**Fix, in order of value:**
1. Get the OCR/parse off the loop. Docling parsing belongs in a
   `ProcessPoolExecutor` (or a separate worker process), not in the API
   process — native OCR holding the interpreter is exactly what a subprocess
   boundary is for. A thread executor may be enough if the native calls release
   the GIL, but the evidence here says whatever is currently used does not
   keep the loop responsive.
2. Add the regression that would have caught it: start an index of a real PDF
   and assert `/api/health` answers **200 within a bounded time** throughout —
   a real request against the real running app, no mocks. That is the honest
   version of "the API stays alive under indexing load".
3. Until (1) lands, add to the rollout plan: **do not run Task 8 external
   acceptance while Task 7 seeding is in flight**, and record in the evidence
   that the API is unresponsive during indexing so a timed-out browser pass is
   not misdiagnosed.

**Quantified at 18:45Z, 15 minutes later — and the numbers change the fix.**
The backlog grew **17 → 115** queued connections and the unit log had **not
advanced at all** since `18:30:10`, still on the same document. That pattern
reads as a hang, so I measured instead of assuming:

| Measurement | Value |
| --- | --- |
| CPU delta over 5 s wall | `utime` 777678 → 781414 = **~37 s CPU in 5 s** ≈ **7.5 cores saturated** |
| threads | **152** |
| RSS / VSZ | 4.98 GB / 68.6 GB |
| guest memory | 24.5 GB total, 12.3 used, **12.2 available**, swap untouched (7 MB) |

**It is not deadlocked — it is grinding.** onnxruntime/rapidocr has fanned out
to ~152 threads and is consuming roughly half of the LXC's 16 cores on a single
scanned PDF for over fifteen minutes. The log silence is simply Docling logging
per-document while still on document one.

Two things follow that the original write-up got wrong or missed:
- **Memory is not the constraint** (12 GB free), so this does not trigger W75's
  memory line. Contention, not RSS, is starving the loop: with 152 runnable
  threads the asyncio thread does not get scheduled promptly even when native
  code releases the GIL.
- **Corpus seeding is a multi-hour, API-down operation at this rate.** One PDF
  is still going after 15 minutes. Task 7 against a scanned-document corpus is
  not a short step, and the API is unreachable throughout.

**Revised fix list:**
1. **Cap the OCR thread fan-out** — set `OMP_NUM_THREADS` and onnxruntime
   intra/inter-op threads to a small fixed number (2-4) for the indexing path.
   This is the cheapest change and directly addresses the starvation: OCR
   should not be allowed to take half the box out from under the event loop.
2. **Move parsing to a subprocess** (as before) — with the added benefit that a
   separate process can be `nice`d or cgroup-capped, which an in-process
   thread pool cannot be.
3. Keep the `/api/health`-stays-200-during-indexing regression from the
   original list; it is the check that makes either fix verifiable.
4. **Rollout planning consequence:** budget Task 7 in hours, not minutes, and
   treat the API as offline for its duration.

**Method note:** my W73 rule said to retry before calling a transient a
regression. I applied it — retried with 10 s and 30 s windows, checked process
uptime and the unit log — and that is precisely what distinguished this real
defect from the earlier restart artifact. The rule worked in both directions.
The follow-up measurement then corrected my own second reading: "log silent for
15 minutes with a growing backlog" looked like a hang, and only the CPU sample
showed it was saturation.

### W78 `VERIFIED (no finding)` — the `tokens_used` fix is complete; the two remaining zeros are correct and must not be "fixed"

**W77 incident closed, finding stands.** At 19:00Z the Apollo PDF finished:
`/api/health` 200, `Recv-Q` back to **0**, log flowing. The stall lasted
roughly 30 minutes on one document. The *design* issue in W77 is unchanged —
indexing still blocks the loop — but there is no live incident.

**W74 closed.** The evidence file now records "Paid replacement proof through
LiteLLM used `openai.gpt-5.6-terra`", which is the acceptance-#9 gap I flagged
and deliberately did not spend money to close myself.

**The paid call immediately earned its keep** — it surfaced that `tokens_used`
was hardcoded `0`, so every chat reported zero tokens and zero cost. The fix in
flight is coherent across the whole surface:
- `chat_once` refactored to return a `ChatOnceResult` dataclass carrying
  `tokens_used`, replacing a 7-tuple;
- non-streaming path propagates it into the payload, the response model, and
  the trace `data` block;
- **both** non-cache streaming terminal events (`handler.py:1003`, `:1055`)
  report `_usage_total_tokens(provider_usage)`;
- `_usage_total_tokens` defends against bools and non-int values rather than
  trusting the provider payload.

**The test is honest.** `tests/api/test_chat_usage_propagation.py` stands up a
real `ThreadingHTTPServer` gateway and drives the app through `ASGITransport` —
no `mock`, no `monkeypatch`, matching the repo's no-fake-green rule.

**Recorded so nobody "fixes" them later:** two `tokens_used=0` literals remain
in `server/chat/handler.py` at **565** and **911**, and both are **correct**.
Each sits inside a semantic-cache-hit path (`cached_text`, `cache_hit: True`) —
a cache hit consumes no gateway tokens, so zero is the truthful answer, not an
oversight. A future `grep tokens_used.*0` will flag them; changing them to
report the original response's tokens would turn a true statement into a
double-count. I nearly filed them as an incomplete fix and only avoided it by
reading the enclosing block — third tick running that the read-the-context rule
has prevented a wrong finding.

### W79 `VERIFIED (no finding)` — the usage work consolidated onto one extractor; tokens and cost can no longer disagree

Follow-up to W78, checked after `server/observability/costing.py` appeared in
the tree. The doer went further than the original fix and it is better for it:

- `costing.py` now exposes `usage_total_tokens()` wrapping the
  `_extract_usage_tokens` helper it already used for cost maths.
- `server/chat/handler.py:34` **imports** that shared function; the private
  `_usage_total_tokens` duplicate I reviewed last tick is gone. It is used at
  `623` (non-streaming) and `978` / `1030` (both non-cache streaming terminal
  events).
- So token reporting and cost accounting derive from **one** extractor. They
  cannot drift apart, which is the failure this would otherwise have invited —
  two implementations of "how many tokens was that" is exactly the duplicated-
  contract smell the repo bans elsewhere.

**Pricing data is real for the production alias**, so cost will not silently
compute zero the way tokens did. From `data/models.json`:
`openai.gpt-5.6-terra` → `model: openai/gpt-5.6-terra`, `input_per_1k 0.002`,
`output_per_1k 0.012`, `context 1050000`. My concern that the alias lookup
might miss (repeating the tokens-bug class one layer down) is unfounded.

**Cache-hit zeros re-verified after the refactor.** The two literals moved to
`handler.py:540` and `:886`, and both are still inside `cache_hit: True` /
`cached_text` blocks — so the refactor neither made cache paths double-count
nor made real paths report zero. Both remain correct; the W78 note about not
"fixing" them still applies, at the new line numbers.

Nothing to inject. Recording it because a reviewer arriving later sees two
hardcoded zeros and one shared helper, and the interesting fact — that the
zeros are deliberate and the helper is deliberately singular — is invisible
from the diff alone.

### W80 `FIXED (working tree, uncommitted)` `OPEN` (P1, W77 root cause located to a line) — Docling runs **on the event loop**; the fix is one `asyncio.to_thread`, matching a pattern already used next door

`c2a8e83b fix(deploy): harden ingestion and chat accounting` is committed and
pushed, and it is good work — but "harden ingestion" means the Docling
*runtime dependency* guard (libgl1/cv2 preflight), **not** the event-loop
blocking. W77 is untouched by it. The only lines in that commit matching
`OMP_NUM_THREADS` / `ProcessPoolExecutor` are **my own W77 text**, which it
committed into the rollout plan.

Confirmed repo-wide (and I checked the match list rather than a count — my
`ORT_` pattern over-matched on `ABORT`/`EXPORT`/`TRANSPORT`, real hits are
zero):

- No `OMP_NUM_THREADS`, no onnxruntime intra/inter-op setting, no
  `ProcessPoolExecutor` anywhere in `server/`, `start.sh`, `deploy/`,
  `docker-compose.yml`, or `infra/`.

**Root cause, exact:**

| Location | What it does |
| --- | --- |
| `server/indexing/text_extractors.py:93` | `result = _docling_converter().convert(str(path))` — plain synchronous call |
| `server/api/index.py:1784` | `content = extract_text_for_path(...)` — called **directly**, no thread hop |
| enclosing chain | `server/api/index.py:1657` **`async def _flush_pending_cross_file_chunks`** (indent 4, **nested**) inside `server/api/index.py:1452` **`async def _run_index_body`** (module level) — corrected, see W82 |

So a multi-minute, 7.5-core OCR runs **on the event loop thread** inside an
`async def`. That is precisely the live evidence from W77 — `/api/health`
timing out while `Recv-Q` climbed to 115 and the process burned 37 s of CPU per
5 s wall.

**The codebase already knows the right pattern.** `server/indexing/embedder.py`
uses `await asyncio.to_thread(...)` in five places (85, 150, 351, 392, 458) for
exactly this reason. Extraction is the outlier, not a design choice.

**Minimal fix — one line, idiomatic here:**
```python
content = await asyncio.to_thread(extract_text_for_path, ...)
```
Docling/onnxruntime release the GIL during native OCR, so a thread hop restores
loop responsiveness immediately. Then cap the fan-out (`OMP_NUM_THREADS` and
onnxruntime intra/inter-op at 2-4) so one document cannot claim half the LXC —
the two are complementary: the thread hop stops the API dying, the cap stops
indexing starving everything else on the node.

`ProcessPoolExecutor` remains the stronger option and is still worth doing if
`to_thread` proves insufficient under load, but it is no longer the *minimum*
needed to unblock Task 7/8 — and this one-line change is testable with the
`/api/health`-stays-200-during-indexing regression already specified in W77.

### W81 `VERIFIED (no finding)` — the capacity guard implements W59/W75 correctly, and its autoextend value corrects mine

New in the tree: `deploy/proxmox/host-capacity-guard.sh`, its
`.service`/`.timer`, and `ragweld-thinpool.profile`. It is a faithful and
slightly better implementation of what W59/W75 asked for:

- **Both levels monitored**, which was the whole point of the W75 correction:
  guest root via `pct exec "$VMID" -- df --output=pcent /`, and
  `lvs -o data_percent,metadata_percent pve/data`.
- **Thresholds exactly as specified** — `guest_root … 75 90`,
  `pool_data … 70 85`, `pool_meta … 70 85`.
- **Probe failure is itself an alert** (`guest_probe="failed"` →
  `send_probe_transition`). I did not ask for that, and it closes the gap where
  a broken check reads as a healthy system — the same "silence is not success"
  failure I have flagged elsewhere.
- **Transition-based alerting**, so a sustained warning does not spam every
  five minutes.
- Timer runs `OnBootSec=5m` **and `OnUnitActiveSec=5m`** with jitter — a real
  repeating check.

**My `autoextend_percent=10` recommendation was wrong; their `1` is right.**
The profile sets `thin_pool_autoextend_threshold=80` /
`thin_pool_autoextend_percent=1`. Arithmetic against this pool:

| percent | GB per extension | extensions possible in 16 GiB VG free |
| --- | --- | --- |
| **1** | 7.9 | **~2** |
| 10 (mine) | 79.4 | **0** |

At 10% a single extension exceeds the free VG, so autoextend could never fire —
my value would have installed a setting that silently does nothing. They chose
the largest value that actually works given the 16 GiB headroom **I had myself
documented** in W59. Second time a numeric recommendation of mine has been
correctly overridden against a constraint from my own notes, after the 24 GiB
memory cap in W53.

**Method note:** my first read of the timer reported only `OnBootSec`, which
would have meant a guard that runs once per boot and never again — a serious
defect had it been true. It was not: my grep pattern was
`OnCalendar|OnBootSec|Persistent` and simply could not match
`OnUnitActiveSec`. Reading the whole file, rather than trusting a pattern I
chose before knowing the answer, is what turned that into a non-event.

**Still open and unchanged:** W80 — `asyncio.to_thread` has not landed at
`server/api/index.py:1784`; the `to_thread` calls at 459/478/669 are
pre-existing and unrelated. No `OMP_NUM_THREADS` anywhere yet.

### W82 `CORRECTION to my own W80` — the root cause stands; my symbol reference was imprecise, and the doer caught it

The fresh-agent handoff (`docs/exec-plans/active/handoff-2026-08-28-pve1-fresh-agent.md`
§10) says: *"that nested function is not the actual call site; run impact on
the real enclosing symbol/call before editing. Do not blindly copy the slightly
mislocated line description from W80."*

I verified rather than simply accepting it. Walking the indentation chain from
the call at `index.py:1784` (indent 20):

| | line | indent | |
| --- | --- | --- | --- |
| innermost enclosing | 1657 | 4 | `async def _flush_pending_cross_file_chunks` — **nested** |
| module-level enclosing | 1452 | 0 | `async def _run_index_body` |

**What I got right:** the immediately enclosing function *is*
`_flush_pending_cross_file_chunks` and it *is* `async`, so the core W80 claim —
a synchronous multi-minute Docling `.convert()` executing on the event-loop
thread — is confirmed, and doubly so since both functions in the chain are
async.

**What I got wrong:** I presented a nested helper as though it were the
addressable symbol. That matters for their workflow, not the diagnosis: a
GitNexus `impact` query against a nested name returns misleading LOW risk
because the graph does not address it the way it addresses
`_run_index_body`. Anyone following my note literally would have run impact on
the wrong symbol and drawn false comfort from the result. W80's table is
corrected above to carry the full chain.

**Their proposed regression is better than mine.** I specified
"`/api/health` stays 200 during indexing", which needs the whole stack running
and is timing-sensitive. The handoff proposes: create a named pipe with a
`.txt` suffix, start a real writer thread that waits ~0.5 s, call the async
extraction helper, and assert an `asyncio.sleep(0.05)` resumes well before the
writer releases the blocking read — then assert the real text is returned.
That is deterministic, needs no services, uses no mocks, and proves the precise
property at issue: **the loop stays free while extraction blocks.** Adopt
theirs.

**Handoff quality note:** it carries the watchdog file in its mandatory read
order, names W75/W81 and W80 as explicit remaining gates, and states that the
W80/W81 rollout-plan injections "are active requirements; do not erase". My
findings survive the agent boundary, which is the thing I would otherwise have
had to check for.

### W83 `ADDRESSED DIFFERENTLY (see W88)` P2 — the W80 fix un-serialized a lazy global: the Docling converter singleton can now be built twice

**This is a defect created by a correct fix, and it only bites under exactly the
concurrency the fix was written to enable.** Not a reason to revert anything —
a five-line follow-up.

`server/indexing/text_extractors.py:21-26` is an unguarded check-then-set on a
module global:

```python
global _DOCLING_CONVERTER
if _DOCLING_CONVERTER is None:
    from docling.document_converter import DocumentConverter
    _DOCLING_CONVERTER = DocumentConverter()
```

That file imports no `threading` (verified: imports are `csv`, `pathlib`,
`typing` only). It was safe before W80 **because of the bug W80 fixed** —
`extract_text_for_path` was called directly on the event-loop thread, so every
call was serialized onto one thread and the lazy init could not race. Now the
call goes through `asyncio.to_thread`, i.e. the default `ThreadPoolExecutor`
with multiple workers.

Is concurrent entry actually reachable? Yes — the run fence is **per-corpus**,
not global: `server/api/index.py:119` is `_ACTIVE_RUNS: dict[str, str]` keyed
by `repo_id`, set at 2323 and popped at 179. Two different corpora indexing at
once is a supported, expected state, and each is a separate task landing in a
separate executor thread. Both can observe `None` and both construct a
`DocumentConverter()`.

**Consequence:** a duplicate Docling model load — layout plus OCR weights,
hundreds of MB and up — on the LXC where memory is the constrained resource
(24 GiB while HAOS remains on pve1). Torn global, wasted cold start, and a
memory spike whose trigger is "two corpora indexed at the same time", which is
about the least reproducible bug shape there is.

**Fix — double-checked locking, no behaviour change:**

```python
import threading
_DOCLING_CONVERTER_LOCK = threading.Lock()

def _docling_converter() -> Any:
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is None:
        with _DOCLING_CONVERTER_LOCK:
            if _DOCLING_CONVERTER is None:
                from docling.document_converter import DocumentConverter
                _DOCLING_CONVERTER = DocumentConverter()
    return _DOCLING_CONVERTER
```

**Red test first, in the existing suite** (`tests/api/test_index_batch_parallelism.py`,
alongside the W80 test): reset `text_extractors._DOCLING_CONVERTER = None`,
patch nothing, and instead count constructions by wrapping the real symbol —
launch two `asyncio.to_thread(_docling_converter)` calls concurrently via
`asyncio.gather` and assert both return **the same object identity**
(`a is b`). Identity is the honest assertion: it is true only if exactly one
converter was built, needs no mock, and fails today under a thread race.

**The generalisable trap, for the plan:** *offloading a synchronous function to
a thread pool silently promotes every lazy global it touches from
single-threaded to concurrent.* The event loop was providing mutual exclusion
for free, and `asyncio.to_thread` withdraws it. Whenever a call is moved to a
thread, audit the transitive callee set for `global`/module-level caches, and
give each one a lock — the offload and the lock belong in the same commit.

### W84 `NOTE` — two findings I did not file this tick, because I checked the object instead of guessing

Both would have been wrong, and both are the same failure mode I have now hit
seven times. Recording the near-misses because the discipline is the finding.

1. **"`DOCLING_NUM_THREADS=4` is a no-op."** I checked
   `docling.datamodel.settings.settings.perf`, whose fields are
   `doc_batch_size, doc_batch_concurrency, page_batch_size,
   page_batch_concurrency, elements_batch_size` — no thread control — and was
   one step from filing it. Wrong object. Thread control lives on
   `docling.datamodel.accelerator_options.AcceleratorOptions`, fields
   `num_threads, device, cuda_use_flash_attention2`, `env_prefix='DOCLING_'`.
   Executed: `DOCLING_NUM_THREADS=4` → `num_threads == 4`, and
   `OMP_NUM_THREADS=4` alone → `num_threads == 4` via Docling's fallback
   validator. **The doer's two lines are both live, and deliberately
   belt-and-braces.**
2. **"The env never reaches uvicorn."** `start-runtime.sh`'s
   `source_private_env_file()` wraps `source` in `set -a` / `set +a`, which
   auto-exports every assignment. It does reach the child.

Also verified the cap is not stranded: `_docling_converter()` builds a bare
`DocumentConverter()` with no `format_options`, so Docling constructs its
default `PdfPipelineOptions`, whose `accelerator_options` defaults to
`AcceleratorOptions()` — which is what reads the env. Bare construction is
precisely what makes an env-based cap work here.

Standing rule, restated because it paid for itself twice in one tick: **print
the object's real fields, or execute the resolution, before asserting a
setting is dead.** A grep or a single settings object is evidence about a
pattern, never about absence.

### W85 `NOTE` — I audited the blast radius of the W80 offload myself. Two positives for the doer, and W83 turns out to be applying the repo's own idiom.

Applying the W83 rule rather than just asserting it: when a sync function moves
into a thread pool, audit its transitive callee set for lazy globals, and check
that every call site of the blocking function actually got the offload.

**Positive 1 — W80's fix is complete; there is no sibling bug.**
`extract_text_for_path` has exactly **one** production caller, and it is the
offload wrapper itself (`server/api/index.py:1462` inside
`_extract_text_for_index`). Every other reference is
`tests/unit/test_text_extractors.py`, which calls it synchronously and
correctly — that is a unit test of the extractor, not an event-loop path. So
no second blocking call site was left behind. Worth stating plainly because my
own standing lesson is *"sibling subsystems share the bug"*, and here, checked,
they do not.

**Positive 2 — the scope of W83 is exactly one symbol, not a sweep.**
`_DOCLING_CONVERTER` (`text_extractors.py:13`) is the only
lazily-initialised `= None` module global in `server/`. The other module-level
containers are constant lookup tables (`_SECTION_DEFAULTS`, `_FIELD_OVERRIDES`,
`_BASELINE_NA_TEXT`, `_GROUP_DASHBOARDS`) or `@lru_cache`, which is thread-safe
in CPython — at worst it computes twice, it does not tear. None of them sit in
the extraction path. **Do not turn W83 into a codebase-wide locking sweep.**

**And the finding that makes W83 cheap — the precedent is already in the file
being fixed.** `server/api/index.py:462` guards its own lazy global with
precisely the pattern W83 asks for:

```python
def _ensure_event_writer() -> None:
    global _EVENT_WRITER
    with _EVENT_WRITER_LOCK:
        if _EVENT_WRITER is None or not _EVENT_WRITER.is_alive():
            ...
```

So this is not a new convention I am importing. The indexing subsystem already
decided that a lazy global touched off the event loop gets a module-level lock,
and implemented it for `_EVENT_WRITER`. `_DOCLING_CONVERTER` is simply the one
that predates the offload and never got the same treatment. Frame the fix as
"make the converter match `_ensure_event_writer`" — same file, same idiom,
already reviewed and shipped.

Also checked and clean: `_flush_run_events_sync`, the other offloaded callee
(`to_thread` at 478), only calls `_EVENT_WRITE_QUEUE.join()` — a queue
operation, thread-safe, no global mutation. And `_ACTIVE_RUNS` is written only
at 179 and 2323 and read at 3383, none of which are inside an offloaded
callee, so the per-corpus fence itself is not exposed to the new concurrency.

### W86 `FIXED (0458f505)` P2 — the capacity guard's *metadata* threshold is the one with no behavioural test, and it guards the worse failure

**First, credit, because it changes how this finding should be read.** The new
+149 lines in `tests/unit/test_proxmox_deployment_contract.py` are the opposite
of the fake-green pattern I have been flagging all day. They *execute*
`host-capacity-guard.sh` under `bash` with fake `sendmail`/`logger`/`timeout`/
`pveum`/`lvs` executables on `PATH` and assert behaviour: alert-once-per-state
dedup, escalation to CRITICAL, RECOVERED transitions, probe timeout that must
not suppress the sibling probe, refusal to persist state when delivery fails
plus a successful retry afterwards, the exact `timeout` argv triple, and clean
`pveum` failures with `"Traceback" not in result.stderr`. They also assert
`0 < service_timeout_seconds < timer_interval_seconds`, which is a real
overlap invariant rather than a string match. Fake executables driven through
real `subprocess` are the honest way to test shell, and they satisfy the
no-Python-mocking rule properly. `_run_shell_script` merges rather than
replaces `os.environ`, so `PATH` is intact.

**The gap.** `deploy/proxmox/host-capacity-guard.sh:231` is

```bash
send_transition pool_meta "pve/data metadata" "$pool_meta" 70 85 "$alert_email" || status=1
```

and that branch never fires in any test. Every test pins metadata below
warning: `RAGWELD_POOL_META_PERCENT: "10"` at test lines 1023 and 1153, and the
fake `lvs` prints `71.0 10.0` at line 1092. So warning/critical/recovered for
`pool_meta` are entirely unexercised.

The only thing protecting those two numbers is, at line 956:

```python
assert "70" in guard and "85" in guard
```

a **whole-file substring check**. It passes if the two thresholds are swapped,
if they appear only inside a comment, or as digits inside an unrelated number
(`170`, `285`, a `TimeoutStartSec=70`). Note the same file does this *properly*
for the timer — `re.search(r"^OnUnitActiveSec=(\d+)m$", ...)` — so the weak
idiom is the exception, not the house style.

**Why this is P2 and not a nitpick: the untested threshold guards the worse
outcome.** A data-full thin pool blocks new writes. A metadata-full thin pool
flips the pool read-only and needs offline `thin_check` / `lvconvert --repair`
to recover. Metadata exhaustion is the failure that actually loses you the
afternoon, and it is the one branch with no behavioural proof.

**Fix, using the harness that already exists** (the `lvs` fake already proves
the pattern works): drive `pool_meta` across 71 and 86 and back down, asserting
`Subject: [Ragweld][WARNING] pve1 pve/data metadata` and the CRITICAL and
RECOVERED equivalents. Then replace line 956's substring check with an anchored
match on the call itself, e.g.
`re.search(r"^\s*send_transition pool_meta .* 70 85 ", guard, re.MULTILINE)`,
and the same for `guest_root 75 90` and `pool_data 70 85`.

**Trap worth knowing before you write it:** the existing tests assert
`first_mail.count("Subject: [Ragweld][WARNING]") == 2`, and that `2` is
`guest_root` + `pool_data`. Those counts are implicitly pinned to pool_meta
*never* alerting. Raise metadata above 70 in a shared-env test and those
`== 2` assertions break in a way that looks like a regression in unrelated
cases. Give the metadata case its own state dir and its own env rather than
editing the shared `base_env`.

### W87 `FIXED (0458f505)` P3 — the successful `df` parse is the one measurement path no test executes

Asymmetric coverage between the guard's two probes.

`host-capacity-guard.sh:201`:

```bash
elif ! guest_used="$(run_with_timeout pct exec "$VMID" -- df --output=pcent / 2>/dev/null | tail -n 1 | tr -d ' %')" \
```

That pipeline is correct by inspection — `df --output=pcent` emits a `Use%`
header then a space-padded ` 76%`, and `tail -n 1 | tr -d ' %'` handles both.
But no test ever runs it successfully: the dedup/recovery/retry tests all
bypass it via `RAGWELD_GUEST_USED_PERCENT`, and the only test that reaches the
real command makes the fake `timeout` exit 124 so it takes the failure branch.

The `lvs` side, by contrast, *is* covered — the fake prints `71.0 10.0` and
that exercises both the two-column split and the decimal truncation in
`whole="${value%%.*}"`. So one measurement path is proven and its sibling is
not, which is exactly the shape that lets a future edit to the `df` pipeline
land green.

**Fix, four lines, mirroring the `lvs` fake:** add a fake `pct` that prints
realistic two-line output —

```bash
#!/usr/bin/env bash
printf 'Use%%\n 76%%\n'
```

— leave `RAGWELD_GUEST_USED_PERCENT` unset, and assert the guest_root WARNING
fires. That proves header-skipping and `%`-stripping against the real format
rather than against a pre-parsed integer.

**The general point for both items:** an env override that lets a test inject a
already-parsed value is a useful seam, but every test that uses it steps over
the parsing it was meant to exercise. When a script has both a probe and a
parse, at least one test per probe must go through the real command shape.

### W88 `FIXED (0458f505)` P2 — W83 was solved with a better outer control than I asked for; the inner invariant is still missing

The doer did not take my `threading.Lock` and did something more interesting.
`server/api/index.py:115` adds `_DOCLING_EXTRACTION_LOCK = asyncio.Lock()`, and
`_extract_text_for_index` now branches on
`extraction_method_for_path(path) == "docling"`, holding that lock across the
**entire** `to_thread` extraction for Docling formats while letting text, CSV
and parquet reads through unlocked. Ten tests pass, including
`test_unsupported_suffix_fallback_bypasses_the_docling_lock`, which holds the
lock and proves a plain read still completes — a test for the *absence* of
over-serialization, which most people would not think to write.

**On the axis I care about most, theirs is strictly better than mine.** A
`threading.Lock` around the singleton init would have stopped the double model
load and nothing else: N corpora could still run N concurrent OCR jobs, each
spawning its 4 capped threads. Their lock bounds total Docling concurrency to
one, which attacks W77's actual measured symptom — ~7.5 cores across 152
threads — not just the memory spike I identified. I asked for a safety latch;
they installed a throughput governor that happens to also be a safety latch.

**What is still missing, and why it is worth five lines.** The guard is now
remote from the thing it guards. `text_extractors.py:13` `_DOCLING_CONVERTER`
remains an unguarded check-then-set in a module that imports no `threading`.
The real invariant is now *"any caller of `extract_text_for_path` on a Docling
suffix must first hold `server.api.index._DOCLING_EXTRACTION_LOCK`"* — which is
undocumented, unenforceable by the module that owns the global, and invisible
to anyone reading `text_extractors.py`. It holds today only because there is
exactly one production caller (W85). It lapses silently the moment a second one
appears, and on this branch that is a live possibility: a Flyte ingest task, a
CLI path, or a script would all be natural second callers.

Two narrower notes on the same point. `asyncio.Lock` is bound to one event
loop, so a second loop — a worker thread calling `asyncio.run`, or any sync
entry point — gets no protection at all. And the lock lives in the API layer
while the state it protects lives in the indexing layer, which is the wrong way
round for a module that is otherwise self-contained.

**Fix — keep theirs, add mine underneath.** These are not redundant, they are
different kinds of thing: the asyncio lock is a *policy* (one OCR at a time on
this loop), the threading lock is an *invariant* (this module is safe to call
from any thread, by anyone). Belt and braces — exactly the reasoning the doer
themselves applied when they set both `DOCLING_NUM_THREADS` and
`OMP_NUM_THREADS`. Add the double-checked `threading.Lock` in
`text_extractors.py` plus a one-line comment naming the module-local
guarantee, so the safety property is readable where the global is defined.

**And state the throughput decision out loud.** Holding the lock across the
whole extraction means two corpora can never OCR concurrently — indexing
wall-clock for parallel corpora is now serialized. On a 24 GiB guest with a
4-thread cap that is very likely correct, and I would keep it. But it is a
product decision that arrived inside a concurrency fix, and it should be
recorded as deliberate rather than inherited silently, because the next person
looking at slow multi-corpus indexing will find it and be tempted to remove it
without knowing W77.

### W89 `MITIGATED — residual, see W92` P2 — the staged commit contains both the W80 implementation *and* a mandatory-read document instructing a fresh agent to implement W80

Caught at a commit boundary, which is the point of watching one. Everything is
now staged (`git status` shows `M `/`A ` across
`server/api/index.py`, the three test files, the four capacity-guard artifacts
and the 635-line handoff), HEAD still `c2a8e83b`. Nothing is committed yet.

**Secrets check on the staged diff first, since that is the irreversible
risk: clean.** The only secret-shaped matches are two git SHAs and
`3314d996…f161dea`, which context shows is the SHA-256 of the public NASA NTRS
PDF fixture — pinning a fixture hash is good practice, not a leak. Hostnames
are the operator's own domains and the IPs are RFC1918. Nothing to hold the
commit for.

**The defect.** `docs/exec-plans/active/handoff-2026-08-28-pve1-fresh-agent.md`
is staged as a new file. It is stamped *"current through 2026-08-28 13:50
MDT"*, and the W80 work landed **after** that stamp. So the single commit will
contain, simultaneously:

- `server/api/index.py:1475-1500` — the offload, plus
  `_DOCLING_EXTRACTION_LOCK` at 115;
- `DOCLING_NUM_THREADS=4` / `OMP_NUM_THREADS=4` in `bootstrap-secrets.sh`;
- four passing event-loop regression tests; and
- §10 of the handoff, titled **"Remaining gate B — implement W80 event-loop
  offload and explicit CPU cap"**, whose step 5 at line 616 reads *"Implement
  the W80 FIFO event-loop regression first, watch it fail, then add the
  offload."*

`docs/exec-plans/active/` is mandatory read order under `AGENTS.md`. A fresh
agent following line 616 writes a regression that passes on the first run — the
most confusing possible starting state — or re-implements work that is already
in the same commit it just checked out.

Two smaller staleness items in the same document: §9 says the capacity
candidate "has three focused tests passing", but there are now five test
functions (six cases, one is parametrised ×2); and §9's framing of gate A as
unfinished is only half true — the artifacts are authored and tested, what
actually remains is installing and enabling them on pve1.

**Fix — cheap, and it preserves the document's character.** Do not rewrite the
gate bodies; they are a useful historical record of the reasoning. The document
already carries a "current through" stamp, so add a short **status delta**
block immediately beneath it, listing what closed after 13:50: W80 complete
(offload, `_DOCLING_EXTRACTION_LOCK`, thread caps, four tests), gate A's
authoring half complete with five test functions and only pve1 installation
outstanding, and W83/W86/W87/W88 open. Then a fresh agent reads the stamp, reads
the delta, and knows which imperatives are spent before it reaches them.

**The generalisable trap:** *a handoff document is a snapshot, but committing it
into a mandatory-read directory turns it into a standing instruction.* The
moment a snapshot and the work it describes land in the same commit, the
snapshot has to carry a delta or it actively misdirects. Either update it in
the commit that outdates it, or keep it out of the mandatory-read path.

### W90 `OPEN` P3 — the systemd unit's most important flag is the one the test does not assert

`ragweld-capacity-guard.service` is well built, and the flag in question shows
it:

```
ExecStart=/usr/bin/flock --nonblock --conflict-exit-code 0 /run/lock/ragweld-capacity-guard.lock /usr/local/sbin/ragweld-host-capacity-guard.sh
```

`--conflict-exit-code 0` is the thoughtful part. Without it, `flock --nonblock`
exits 1 when a previous run still holds the lock, a `Type=oneshot` unit treats
that as a failure, and because the timer keeps firing you end up with a unit
that is permanently in `failed` state — which then masks the real failure you
built the guard to surface. They got this right.

But the contract test at test line ~966 asserts only:

```python
assert "flock --nonblock" in service
```

The substring `"flock --nonblock"` matches with or without
`--conflict-exit-code 0`. Delete that flag in a future edit and the test stays
green while the unit starts failing on every overlapping run. Same shape as
W86: the assertion covers the part that was never in doubt and skips the part
that carries the behaviour.

**Fix:** assert the full flag set — `"--nonblock" in service and
"--conflict-exit-code 0" in service` — or better, anchor on the whole
`ExecStart=` line with a regex so the lock path and script path are pinned too.

### W91 `OPEN` P3 — `Persistent=true` is inert on this timer, and the test pins it as if it means something

`ragweld-capacity-guard.timer` sets `OnBootSec=5m`, `OnUnitActiveSec=5m`,
`AccuracySec=30s`, `RandomizedDelaySec=30s` and `Persistent=true`.

Per `systemd.timer(5)`, `Persistent=` "only has an effect on timers configured
with `OnCalendar=`". This timer is monotonic-only, so the directive does
nothing. The test then asserts `"Persistent=true" in timer`, which promotes a
no-op to a pinned contract — and the natural reading of that assertion is
"missed runs are caught up after downtime", which is not what will happen.

Operationally this is harmless today: `OnBootSec=5m` already covers the
after-downtime case, which is the thing `Persistent=` would have bought.
So this is about the contract saying something untrue, not about a capacity
gap.

**Fix:** drop `Persistent=true` and its assertion, and if catch-up semantics
are actually wanted, say so with `OnCalendar=` instead. If it is kept as
harmless future-proofing, put a comment in the unit saying it is inert until an
`OnCalendar=` exists, so the next reader does not infer a guarantee from it.

**Credit where due on this unit,** because the ratio matters:
`--conflict-exit-code 0`, `install -d -m 0700 "$STATE_DIR"` (atomic mode, better
than `mkdir -p`), `UMask=0077`, `ConditionPathExists=/etc/pve/lxc/100.conf` so
it no-ops on a host without the guest, `After=pve-cluster.service
lvm2-monitor.service`, and `RandomizedDelaySec=30s` to avoid thundering with
other timers. Two weak assertions against that much correct detail is a good
ratio.

### W92 `FIXED (working tree)` P3 — W89 is mitigated by unstaging, but the stale handoff still sits in the mandatory-read directory

The doer unstaged it: `docs/exec-plans/active/handoff-2026-08-28-pve1-fresh-agent.md`
moved from `A ` to `??`, confirmed untracked by `git ls-files --error-unmatch`.
That resolves the sharp edge of W89 — the commit will no longer contain both
the W80 implementation and a document telling a fresh agent to build it.

The residual: the file is still on disk, 28 KB, in
`docs/exec-plans/active/`, which `AGENTS.md` puts in mandatory read order. Read
order is a filesystem path, not a git query, so any agent working in this
checkout still meets §10 "Remaining gate B — implement W80 event-loop offload
and explicit CPU cap" and step 5's "watch it fail, then add the offload" — for
work that is already done in the working tree.

The fix is now *cheaper* than when I first raised it, because an untracked file
costs nothing to edit: add the status delta under the existing "current through
2026-08-28 13:50 MDT" stamp. Same content as before — W80 closed, gate A
authoring closed with five test functions and only the pve1 install left,
W83/W86/W87/W88/W90/W91 open.

### W93 `NOTE` — a near-miss I caught by running the thing instead of trusting the grep

I searched the guard and its unit for `mkdir|StateDirectory`, got nothing, and
was ready to file a P2: "`STATE_DIR` defaults to
`/var/lib/ragweld-capacity-guard`, nothing creates it, so `write_state`'s
redirect fails under `set -e` on first run."

Instead of writing it up I executed the script against an absent state dir with
fake `sendmail`/`logger`. Result: `exit=0`, directory created, mail delivered.
The mechanism is line 190, `install -d -m 0700 "$STATE_DIR"` — which my pattern
could never have matched, and which is *better* than the `mkdir -p` I was
looking for because it sets the mode atomically rather than leaving a window at
the process umask.

That is the ninth time today a pattern-based absence check has been wrong, and
the first time the thing that caught it was execution rather than a second
grep. Promote the rule accordingly: **when a finding would be "X never
happens", run the code path and watch, rather than searching for the mechanism
you assume X would use.** A grep can only find the implementation you already
imagined.

### W94 `NOTE` — W88 is no longer a prediction; the doer's own red test measured it

They wrote the red test before the fix, as they have all day:
`tests/unit/test_text_extractors.py::test_docling_converter_singleton_is_thread_safe_under_real_concurrent_threads`.
It is red right now, and its failure output is the proof I could not produce by
reading:

```
[4560993024, 4562953008, 4549392240, 4562954448, 4562955120, 4560993024, 4562956560, 4562957328]
```

Eight concurrent threads calling `_docling_converter()`, **seven distinct
object identities** (`4560993024` recurs once). So seven `DocumentConverter`
instances — seven duplicate layout-plus-OCR model loads — were constructed from
a single unguarded check-then-set. W83 estimated "two corpora could double-load
it"; the measured answer is that it scales with thread count.

This also settles the W88 design question empirically. The test drives
`_docling_converter` directly from real threads, bypassing the API layer — i.e.
exactly the "second caller" case I argued would silently lose protection. The
`asyncio.Lock` in `server/api/index.py` does nothing here, which is the whole
reason the module-local `threading.Lock` is worth its five lines. Their own
test now demonstrates that better than my argument did.

Worth noting the test's construction: it runs the concurrency probe in a
subprocess (`.venv/bin/python -c ...`) rather than in-process, so the singleton
starts clean and the test cannot pollute module state for the rest of the
suite. That is the right call for a global-state test and not the obvious one.

**Status for anyone reading the suite:** a full `uv run pytest -q` currently
reports one failure, and it is *this* test. It is a deliberate red-first
assertion of a real defect, not a regression, and it goes green when the
`threading.Lock` lands in `text_extractors.py`. Do not "fix" it by weakening
the assertion.

### W95 `FIXED (0458f505)` P2 — one stale test double, three symptoms, and a green test that is green for the wrong reason

**Diagnosis of the current red suite.** `uv run pytest -q` reports three
failures. Two are the doer's deliberate red-first work in progress. The third
is an incomplete sweep that is easy to misread as one of the other two, which
is exactly why it is worth calling out.

The production change is correct and small — `run_with_timeout` gained a
kill escalation:

```bash
run_with_timeout() {
  "$TIMEOUT_BIN" --kill-after=10s "${COMMAND_TIMEOUT_SECONDS}s" "$@"
}
```

The `timeout` test doubles emulate that CLI by position. The doer correctly
updated **three of the four** to cope with the new leading flag — test lines
1099, 1164 and 1293 each gained

```bash
if [[ "$1" == --kill-after=* ]]; then
  shift 2
```

— and **missed the fourth**, at test line 1423, which is still a bare `shift`
followed by `exec "$@"`.

**Proven, not inferred.** I ran that exact double against both argv shapes:

```
$ double 9s echo hi                      -> hi
$ double --kill-after=10s 9s echo hi     -> exec: 9s: not found   (exit 127)
```

One `shift` removes `--kill-after=10s`, so the double tries to execute a
program literally named `9s`. Every command routed through it now fails with
127 before the real fake ever runs.

**The part that matters most: the failure half-masks itself.** That double
serves a parametrised test with two cases.

| case | fake `pveum` | expects | result |
| --- | --- | --- | --- |
| 1 | `exit 42` | `"pveum user list failed…"` | **passes** |
| 2 | `printf 'not-json'` | `"pveum returned malformed JSON…"` | **fails** |

With the double broken, *both* invocations die at 127, so both produce
"pveum user list failed". Case 1 therefore still passes — but it is no longer
testing what it claims: the fake `pveum`'s `exit 42` is never reached, and the
assertion is satisfied by the broken fixture instead. So a fully broken test
double surfaced as a single failure rather than two, which understates the
breakage and makes it look like an isolated red-first test.

**Fix — and do the structural one, not just the patch.** The immediate repair
is to give line 1423's double the same `--kill-after` handling as its three
siblings. But four hand-copied emulations of one CLI is the defect generator
here: the sweep was incomplete precisely because the knowledge "our `timeout`
invocation takes a leading flag" lives in four places. Hoist a single
`_FAKE_TIMEOUT_SOURCE` module constant (or one fixture that writes it) and have
all four call sites use it. Then the next flag added to `run_with_timeout` is a
one-line change with no sweep to get wrong.

**The generalisable trap:** *a test double that reimplements a CLI's argument
parsing is coupled to the caller's exact argv shape.* Adding a flag to the real
invocation silently changes what the double does, and because the double is
"just test scaffolding" nobody diffs it against the caller. Worse, a
positional double tends to fail in ways that produce plausible error text —
here, "pveum user list failed" — so the symptom reads as a product bug rather
than a fixture bug. Keep one copy, and make it parse flags rather than count
positions.

### W96 `NOTE` — status of the other two failures, so nobody "fixes" the wrong thing

- `tests/api/test_index_batch_parallelism.py::test_docling_cancellation_keeps_lock_until_blocking_worker_finishes`
  fails with `AttributeError: module 'server.api…'` — a red-first test for a
  symbol that does not exist yet. Work in progress, not a regression.
- `test_proxmox_capacity_guard_alerts_on_real_guest_df_output_without_override`
  is the **W87 fix landing**: a fake `pct` emitting real two-line
  `df --output=pcent` output with no percent override. It failed in the
  full-suite run and passes both in isolation and in a full-file run now
  (47 passed, 1 failed), so it was caught mid-edit.

**W87 and W88 are both now fixed in the working tree.** `text_extractors.py`
has `import threading`, `_DOCLING_CONVERTER_LOCK = threading.Lock()` at line 15
and `with _DOCLING_CONVERTER_LOCK:` at 26 — the module-local invariant I asked
for in W88, alongside the `asyncio.Lock` policy they added for W83. The
thread-safety test that measured seven duplicate converters now passes.

### W97 `FIXED (0458f505)` P2 — the new cancellation-safe lock can leak itself, and the leak is a permanent ingestion deadlock

**First: the design is good and I would not have written it as well.** The
obvious implementation of "serialize Docling" is
`async with lock: await asyncio.to_thread(...)`. That is wrong in a way most
people never notice — cancel the caller and the lock releases immediately while
the OS thread keeps running Docling, because threads are not cancellable. A
second extraction then acquires the lock and runs *concurrently with the
orphan*, which defeats the entire point of the serialization. Their
`_run_docling_extraction_locked` (`server/api/index.py:1477`) avoids that:
`asyncio.shield(worker)` so cancelling the caller does not cancel the thread
task, `worker.add_done_callback(_release_lock)` so the lock is held until the
thread actually finishes, a `released` flag to make release idempotent, and
`finally: if worker.done(): _release_lock()` to close the `call_soon` latency
window rather than leaving the lock held for an extra loop iteration. That is
careful, correct reasoning about a genuinely subtle problem.

**The gap.** The acquire and the task wiring sit *outside* the `try`:

```python
await _DOCLING_EXTRACTION_LOCK.acquire()      # line 1483
released = False
def _release_lock(...): ...
worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))   # 1493
worker.add_done_callback(_release_lock)                                   # 1494
try:                                                                      # 1495
    return await asyncio.shield(worker)
finally:
    if worker.done():
        _release_lock()
```

If anything between the `acquire()` and the `try` raises, the lock is held by
nobody and released by nothing. `_DOCLING_EXTRACTION_LOCK` is a module-level
singleton, so the consequence is not one failed request — **every subsequent
PDF, DOCX, PPTX, XLSX and HTML ingestion blocks forever on `acquire()` until
the process is restarted.**

**Why this is not as theoretical as it sounds.** `asyncio.create_task` raising
inside a running coroutine mostly means loop shutdown — rare. But it also
raises `MemoryError` under allocation pressure, and the one code path where
`MemoryError` is genuinely plausible on this deployment is the one that is
about to hand a 359-page PDF to an OCR pipeline on a 24 GiB guest. The failure
mode would also present as "indexing hangs and the API stops making progress",
which is *identical to the W77 symptom they just fixed* — so it would very
likely be misdiagnosed as a regression of the thing that was already repaired.

**Fix — move the wiring inside a guard:**

```python
await _DOCLING_EXTRACTION_LOCK.acquire()
released = False
def _release_lock(_future: object | None = None) -> None: ...
try:
    worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    worker.add_done_callback(_release_lock)
except BaseException:
    _release_lock()
    raise
try:
    return await asyncio.shield(worker)
finally:
    if worker.done():
        _release_lock()
```

`BaseException` rather than `Exception` on purpose: a cancellation delivered in
that window must not strand the lock either.

**Test it the way they tested the rest of this** — no mocking needed. Acquire
the lock is not the seam; instead assert the invariant directly: after forcing a
failure in the setup window, `_DOCLING_EXTRACTION_LOCK.locked()` must be
`False`. A small helper that raises in place of `func` does not exercise it
(the failure has to be in `create_task`), so the honest cheap test is a direct
one: call `_run_docling_extraction_locked` with a callable, cancel it, let the
worker finish, and assert `locked() is False` — plus a regression asserting the
lock is *still held* immediately after cancellation while the worker runs,
which is the property `shield` exists to provide.

### W98 `OPEN` P3 — the shielded orphan's exception is never retrieved

Same function, smaller point. When the caller is cancelled, nothing ever awaits
`worker` again. If the Docling conversion then raises, that exception is never
retrieved, and CPython logs `Task exception was never retrieved` when the task
is garbage collected — attributed to no request, at an arbitrary later moment.

The result is correctly discarded (the caller is gone), so this is not a
correctness bug. It is a diagnosability one: an operator debugging ingestion
sees a detached traceback with no context, on a system where "ingestion is
behaving strangely" is the exact thing being investigated.

**Fix:** have the done-callback consume it, since the callback already receives
the future —

```python
def _release_lock(future: object | None = None) -> None:
    ...
    if isinstance(future, asyncio.Future) and not future.cancelled():
        exc = future.exception()
        if exc is not None:
            logger.warning("docling extraction failed after caller went away", exc_info=exc)
```

That both marks the exception retrieved and puts it in the log with a sentence
saying why it has no request attached.

### W99 `NOTE` — W86 and W92 both landed better than I specified

**W86.** They did not just add metadata cases, they fixed the assertion
strength I complained about and avoided the trap I flagged:

- test line 977 is a **full-line anchored regex**,
  `r'^\s*send_transition pool_meta "pve/data metadata" "\$pool_meta" 70 85 "\$alert_email" \|\| status=1$'`
  — stronger than the partial anchor I suggested, since it pins the label and
  the `|| status=1` too;
- metadata now runs the whole cycle: `71` warning (1235), `86` critical (1251),
  `10` recovered (1261), with WARNING/CRITICAL/RECOVERED all asserted at
  1242/1256/1266;
- and line 1200 asserts `"…pve/data metadata" not in mail` for the
  below-threshold case. That is the right answer to the trap I raised: rather
  than editing the brittle `count(...) == 2` assertions, they replaced counting
  with explicit presence *and absence* assertions, which is what the counts
  were badly approximating in the first place.

**W92.** The status delta is sharper than the one I asked for. Mine said "list
what closed". Theirs additionally separates the *deployed baseline*
(`c2a8e83b…`) from the *reviewed local source candidate*, and states "Do not
invent its future hash" — which forecloses a failure I had not thought to
guard: a fresh agent citing an uncommitted change as deployment proof.

One freshness note, and it is the same shape as W89 itself: the delta lists
W80/W83/W86/W87/W88/W89 as implemented, but does not mention **W90, W91 and
W95**, which are open. A status block that is not maintained becomes the next
stale artifact. Either add the open items or give the block a rule — "items not
listed here are tracked in the watchdog file" — so it degrades honestly.

### W100 `NOTE` — W95 closed and the four doubles now agree; the structural residual is smaller than I framed it

The fourth `timeout` double at test line 1425 now carries the same prologue as
its three siblings, and — better than the sweep I asked for — all four use

```bash
if [[ "$1" == --kill-after=* ]]; then
  shift 2
else
  shift
fi
```

The `else shift` branch means each double now tolerates *both* argv shapes, so
removing `--kill-after` later would not break them either. My version of the
fix only handled the new shape. Contract file is **48 passed, 0 failed**.

The hoist was not taken and I am downgrading that ask rather than repeating it.
Three of the four are now byte-identical prologues followed by `exec "$@"`; the
fourth (line 1099) adds a `pct` special case after the same prologue. Since
they agree, the live defect is gone and what remains is only the cost of the
*next* sweep. If it is ever touched again, extract the prologue to one
constant and append the per-test body — but this is now housekeeping, not a
correctness risk, and it does not need to block the commit.

### W101 `NOTE` — W97 is no longer an argument; I reproduced the deadlock

I replicated the exact structure of `_run_docling_extraction_locked` in a
standalone script — no repo code modified — and forced a failure in the
`acquire()` → `try` window:

```
lock held before:        False
raised:                  MemoryError
lock held AFTER failure:  True
next extraction DEADLOCKED on acquire() -> all Docling ingestion blocked
```

The second caller never acquires. Because `_DOCLING_EXTRACTION_LOCK` is a
module-level singleton, that is every subsequent PDF, DOCX, PPTX, XLSX and HTML
ingestion for the life of the process. **Raising W97 from P3 to P2:** the
trigger is narrow but the blast radius is total and the recovery is a restart.

**Being precise about what is and is not proven,** because the distinction
matters for how hard to push this. *Proven:* any exception raised between
`acquire()` and the `try` strands the lock permanently, and the next caller
hangs. *Plausible but not demonstrated:* the specific triggers. `create_task`
allocates a Task (and `asyncio.to_thread(...)` allocates a coroutine object
first), so `MemoryError` under real pressure is credible on a 24 GiB guest
running OCR; `RuntimeError` during loop shutdown is the other candidate. I have
not produced either in situ, and I am not claiming to have. The structural
defect is what needs fixing, and it needs fixing regardless of which trigger
you find most likely — the fix is four lines and costs nothing.

The fix remains as filed in W97: move `create_task` and `add_done_callback`
inside a `try` with `except BaseException: _release_lock(); raise`.

### W102 `FIXED (0458f505)` P3 — W97's fix is better than what I asked for, and the leak window is now one line wide instead of closed

**What they added that I did not think of.** My prescription was just
`try: create_task; add_done_callback / except BaseException: _release_lock(); raise`.
They went further on two real points:

1. **The orphaned coroutine.** If `create_task` fails, the coroutine object
   returned by `asyncio.to_thread(...)` was created and never scheduled, which
   emits `RuntimeWarning: coroutine ... was never awaited` at GC. They call
   `worker_coroutine.close()` in that branch. I missed this entirely.
2. **Compensating when the callback registration fails.** If
   `add_done_callback` raises, `_release_lock` was never registered, so nothing
   would ever free the lock. They `await asyncio.shield(worker)` to let the
   thread finish *before* releasing — which preserves the serialization
   invariant on the error path rather than just avoiding the deadlock. That is
   the more careful of the two possible fixes.

**The residual.** The coroutine is still constructed outside the guard:

```python
worker_coroutine = asyncio.to_thread(func, *args, **kwargs)   # <- outside
worker: asyncio.Task[T] | None = None
try:
    worker = asyncio.create_task(worker_coroutine)
    ...
```

Calling `asyncio.to_thread(...)` allocates a coroutine object, and that
allocation is exactly the `MemoryError` candidate I named when arguing W97. So
the window I reproduced is narrowed from three statements to one, not
eliminated — an exception there still strands the module-level lock and
deadlocks all subsequent Docling ingestion.

**Fix is one line: move it inside the existing `try`,** and initialise
`worker_coroutine = None` alongside `worker` so the `close()` branch stays
correct.

**Where I would stop, and why.** Strictly, `released = False` and the
`def _release_lock` closure are also allocations between `acquire()` and the
`try`, so the window can only be fully closed by making the `try` the first
statement after the acquire. I am not asking for that. A `MemoryError` during
`MAKE_FUNCTION` is a process that is already dying, and restructuring around it
buys nothing real while making the function harder to read. Move the
`to_thread` call — it is the one allocation in that window large enough to
matter, since it captures the args — and leave the rest.

**One near-unreachable path, recorded but explicitly not worth changing.** In
the `except BaseException` branch where `worker is not None`, the
`await asyncio.shield(worker)` runs inside an exception handler. If the original
exception was a `CancelledError`, that await can be cancelled immediately, fall
through `except BaseException: pass`, and reach `_release_lock()` while the
worker thread is still running — releasing the lock with an orphan in flight.
Reaching it requires `add_done_callback` to raise, which happens only if the
callback is not callable. I am noting it for completeness, not asking for a
change; adding cancellation gymnastics to an unreachable branch would cost more
clarity than it buys safety.

**Still open and unchanged:** W98 (consume the orphan's exception in the
done-callback), W90 (`--conflict-exit-code 0` unasserted), W91
(`Persistent=true` inert but pinned as contract).

## Published: 0458f505 — gate green, focus moves to the host

`fix(deploy): harden pve1 capacity and indexing` is committed **and pushed**;
`HEAD == origin/main == 0458f505`, 0 ahead / 0 behind, working tree clean.
Full gate at that commit: `check_docs_ownership`, `check_banned`,
`validate_types`, `generate_litellm_config --check` all PASS, and
`uv run pytest -q` gives **1241 passed, 98 skipped**.

W102 landed, and the restructure goes past the one-line change I asked for: a
single `try` now spans `to_thread` → `create_task` → `add_done_callback` →
`await shield`, with a `callback_registered` flag and a `finally` that decides
release from `(worker is None, worker.done(), callback_registered)`. I traced
every reachable path — normal success, caller cancelled mid-await, `to_thread`
raising, `create_task` raising, `add_done_callback` raising — and they are all
correct. The one that matters most is right: **on cancellation the lock is not
released**, so the done-callback frees it only once the orphan thread actually
finishes, and nothing can race an in-flight OCR job.

Everything from W80 to W102 is now closed except W90, W91 and W98, none of
which block anything. The remaining risk has moved off the code and onto the
host, so that is where these next two live.

### W103 `OPEN` P3 — pin the locale before the guard parses numbers on a real host

`host-capacity-guard.sh` parses `lvs` output through
`is_number`, whose regex is `^[0-9]+([.][0-9]+)?$` — a hard-coded `.` decimal
separator. There is no locale pin anywhere in the script.

Under a comma-decimal locale, `lvs` emits `71,0`, `is_number` rejects it, and
the guard takes the probe-failure branch. That does not crash and does not
alert on capacity — it alerts "pve/data storage probe" **forever**, so you lose
thin-pool monitoring while believing it is running. Silent loss of the thing
the guard exists to provide.

Honest likelihood: **low.** systemd services do not inherit an interactive
user's locale, and Proxmox hosts normally run `en_US.UTF-8` or C, both of which
use `.`. But the fix is one line at the top of the script —
`export LC_ALL=C` — and it removes the entire class for a script whose whole
job is scraping numbers out of tool output. Cheap insurance, not a redesign.

### W104 `OPEN` P2 — verify `root@pam` has an email *before* enabling the timer, or the first run fails and keeps failing

`resolve_alert_email` falls back to `pveum user list --output-format json` and
extracts root@pam's address with
`str(row.get("email") or "")` — which yields an **empty string** when the field
is absent, and exits 0. The emptiness is caught later by the address regex,
which calls `die`.

So if `root@pam` has no email configured, the guard exits 1 on **every** timer
firing, every five minutes, indefinitely. The unit sits permanently failed and
no capacity alert is ever delivered — and because `--conflict-exit-code 0`
makes genuine skips exit 0, a persistently failed unit is precisely the signal
that would otherwise mean something real.

This is the most likely thing to go wrong on first install, and it is not a
code defect — the fail-closed behaviour is correct, and `die` does log to the
journal so local visibility survives. It is a **precondition to check before
enabling the timer**:

```bash
pveum user list --output-format json | python3 -c \
  "import json,sys; print([r.get('email') for r in json.load(sys.stdin) if r.get('userid')=='root@pam'])"
```

If that prints `[None]` or `['']`, either set the address in the Proxmox UI
(Datacenter → Permissions → Users → root@pam) or put
`Environment=RAGWELD_CAPACITY_ALERT_EMAIL=…` in the service unit. The PVE ISO
installer does prompt for an administrator email, so it is probably populated
on pve1 — but "probably" is worth one command when the failure mode is silent
non-monitoring.

**Add both to the install step as a preflight**, so enabling the timer is
gated on a real successful run rather than on `systemctl enable` returning 0.
That is the general point for this phase: every test so far has driven the
guard through fake `pveum`, `pct` and `lvs`. The first contact with real ones
happens on pve1, and the install step should prove one real invocation before
trusting the schedule.

## Low / rollout-time reminders

### W16 `NOTE` — NFS `root_squash` vs arr/Plex write uids

- LXC 4214 is privileged; anything running as uid 0 inside it writes as
  `nobody` on the bridge. Verify media-tree owning uids match the Plex/arr
  PUIDs during spec §10 step 5, before migration, or acceptance #14 fails
  late.

### W17 `NOTE` — Cloudflare free-plan limits

- 100 MB request body (UI corpus upload) and ~100 s idle response timeout.
  Corpus seeding is rsync, so fine; record it in the rollout evidence rather
  than discovering it in the curious-user pass.
