# Watchdog: Proxmox runtime foundation (running list)

Date opened: 2026-08-28
Owner: David (independent review of the SDD run for
`docs/superpowers/plans/2026-08-27-proxmox-runtime-foundation.md`)
Scope: problems the doer either claimed as fixed/verified or did not notice.
Not a list of the doer's open work. Items are appended as found; status is
updated in place. IDs are stable.

Status legend: `OPEN` (needs a fix), `DECIDE` (needs my call, then a fix),
`NOTE` (record only), `FIXED <commit>`.

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

### W37 `FIXED b421d203 (publication gate pending)` — automount idle expiry + LXC bind mount = empty media at container start

- `deploy/proxmox/plex/srv-media.automount` sets `TimeoutIdleSec=60`
  (systemd's default is 0 = never expire). LXC 4214 consumes `/srv/media`
  as `mp1: /srv/media,mp=/srv/media` — a bind mount created at `pct start`
  with private propagation. If the NFS filesystem is not mounted at that
  instant (expired after 60 s idle, or never triggered since a `.173`
  reboot because `pve-guests.service` starts containers before anything
  stats `/srv/media`), the container binds the autofs stub and sees an empty
  tree; later host-side automounts do not propagate into it. Plex/arr start
  with no media — Task 3 Step 6's rollback trigger — and it recurs on every
  reboot.
- Better way (three small pieces, all reversible):
  1. Foundation follow-up commit: `TimeoutIdleSec=0` in
     `srv-media.automount` (+ update the contract test), so the mount never
     expires once triggered.
  2. `.173` drop-in `/etc/systemd/system/pve-guests.service.d/srv-media.conf`:
     `[Unit] After=srv-media.automount network-online.target` and
     `[Service] ExecStartPre=/bin/sh -c 'ls /srv/media >/dev/null && findmnt -t nfs4 /srv/media'`
     so containers cannot start before the NFS mount is live (fails closed
     if pve1 is down — the spec asked for hard failure).
  3. Plex plan Task 3 Step 5: run `findmnt -t nfs4 /srv/media` on `.173`
     immediately before `pct start 4214`, and after start prove
     `pct exec 4214 -- findmnt -t nfs4 /srv/media` (fstype must be `nfs4`,
     not `autofs`).
- Controller RED/GREEN evidence 2026-08-28: the exact contract test failed
  against `TimeoutIdleSec=60`, then passed after the template moved to
  `TimeoutIdleSec=0`. Publish this two-file change before Plex Task 2.

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
