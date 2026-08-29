# Fresh-Agent Handoff Prompt — Finish the Live Ragweld Instance on pve1

Paste everything below into a fresh Codex task. This prompt is intentionally
self-contained and current through **2026-08-28 13:50 MDT**. The receiving
agent must still verify drift before mutating anything.

Status delta for the reviewed local source candidate after that timestamp:

- The deployed baseline remains `c2a8e83b7009b661d2c2e109cea12f42cfb48ff1`.
  Every published/deployed hash in this file refers to that baseline only.
- The current dirty worktree contains a reviewed local source candidate for the
  capacity guardrails and Docling ingestion fixes, but it is not yet committed,
  published, or deployed. Do not invent its future hash.
- Treat W80/W83/W86/W87/W88/W89 as implemented-and-reviewed local source work
  awaiting final rerun, commit, push, and pve1 deployment proof; they are not
  still-open implementation tasks on the live instance.

## Execution result addendum — current through 2026-08-28 18:04 MDT

This addendum supersedes the stale-state statements below. Preserve the body as
the executed acceptance specification and historical command record. Exact
evidence is in
`docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`.

- The user explicitly superseded the original copy-only Mac rule: all Ragweld
  ignored/runtime data was preserved root-private on Linux, then removed from
  the Mac. No secret or private data was committed.
- Published/deployed milestones are `0458f505` (capacity/Docling source),
  `3004aad9` (tracked handoff/agent material), `f60c440e` (temporary
  `dtmont.com` ingress), `de6085d3` (concurrent docs-autopilot hardening), and
  `f7ba79bd` / `44a42e2b` (execution evidence), `3cedcfa5` (production chat
  output budget), and `c5989bfc` (scoped-config persistence fix).
- Mac `main` and `origin/main` matched `c5989bfc` before this evidence-only
  update; the only tracked state was these two owned evidence files. The Mac
  had one branch, one worktree, no ignored state, no Ragweld local
  services/workers, and no `colima-ragweld` profile/context.
- LXC100 checkout and `/etc/ragweld/deployment-commit` matched `c5989bfc`;
  `ragweld.service`, API readiness, Caddy, Authelia, and cloudflared were green.
- Exact source gate before teardown: `1241 passed, 98 skipped, 7 warnings`.
  The later docs-autopilot lane is `25 passed`; standard validators remain
  green. A Mac-wide rerun after teardown reports 15 dependency failures because
  local Postgres/Docker/Colima were intentionally removed; do not rebuild them
  merely to change that evidence.
- The final exact staged source candidate received GPT-5.6 verdict `ACCEPTED`
  with no actionable P1/P2. The user ordered the active paid generation/test
  and speculative review stopped; no new paid GLM rerun was performed. A
  resumed external Claude session later restarted its generator, reviewer, and
  full test; all three process groups and their owning session were stopped
  again before final cleanup.
- pve1 capacity profile/guard is live: scoped 80/1 profile, monitored thin pool,
  five-minute timer, clean normal state, and warn/dedupe/critical/recovery/probe
  synthetic paths all proved with fake delivery.
- Root-only logical backup `/srv/ragweld/backups/20260828T223712Z` passed all
  checksums with no incomplete directory or Qdrant snapshot residue; its weekly
  timer is enabled. The existing PBS VMID100 job is unchanged.
- Real Docling run `20260828T230708_90174b3bb8` completed with eight chunks and
  3,131 tokens while health stayed 1.9–2.5 ms and corpus reads 2.2–6.5 ms. Its
  temporary corpus was deleted through the real API. Exactly two user-managed
  public corpora remain; `recall_default` is the product-owned chat-memory
  corpus, not a third public corpus.
- The user's signed-in browser drive found a real GLM 5.3 Flash chat failure.
  Raw gateway proof showed reasoning tokens exhausting the effective 512-token
  corpus budget before any answer text. `3cedcfa5` renders 4096 for production,
  and `c5989bfc` stops the scoped-config loader from silently migrating 4096
  back to 512. After a full restart, the scoped value remained 4096 and exact
  live run `edf49d16-f8af-47a6-a0bc-e7882cac7554` returned a complete grounded
  answer with `llm_used=true`, zero error events, 2,923 tokens, and 13 sources.
- All Mac state is under
  `/srv/ragweld/mac-archive/2026-08-28-from-mac`, including initial/delta
  archives, the stopped Colima profile, a late 1.5G regenerated-state delta,
  the ultimate post-restart delta (35 exact ignored paths, 53,483 archive
  entries, 1,493,829,632 uncompressed bytes, SHA-256
  `0b0688462f828a0a20175173828f600ee2ab19858bccbc0cfc3cc91f2d3e2ba5`), and a
  final two-entry Python validation-cache delta (SHA-256
  `aec05f69e0db94d0dbfc8a5972f115afb608c39c06cc356edd68b9701a546f36`), plus a
  verified Git bundle for unique detached review commit `0abf6cf6`. Every
  sidecar passes `sha256sum -c` in place.
- Netlify support has the `ragweld.com` nameserver-change request. Until that
  completes, `https://ragweld.dtmont.com` is live through
  `https://ragweld-auth.dtmont.com`; Google DNS sees A+AAAA, the app redirects
  to the correct Authelia host, and the login page renders in the in-app
  Browser.
- Remaining external gates: Netlify must activate the original Cloudflare zone,
  and the user must re-enter Authelia credentials after the fix-forward restart
  so the final signed-in visual confirmation and companion-UI acceptance can
  finish. Agents never handle the password/OTP.

---

`/goal` Continue and finish the permanent, clean, full Ragweld instance on
Proxmox pve1. Work persistently until every acceptance gate below is proved or
there is a genuine security/irreversible blocker requiring the user. Use
independent GPT-5.6 subagents for bounded investigation and review. Use only
GPT-5.6 models or the current OpenRouter `ox-alpha/glm-5.3-flash` identity;
**never use GPT-5.4 for any reason**. Give long-context adversarial reviewers
the time they need, up to an hour. Do not stop a reviewer merely because it has
run for a few minutes.

## 1. Mission and scope

Your job is to finish the actual Ragweld deployment—not to redesign it, restart
completed infrastructure projects, create a demo fork, or wander into broad
cleanup. The active scope is exactly:

1. `/Users/davidmontgomery/ragweld` on the Mac;
2. LXC 100 (`ragweld`, `192.168.68.225`) on Proxmox node pve1
   (`192.168.68.171`);
3. the authenticated Ragweld surfaces under `ragweld.com`;
4. the remaining capacity, event-loop, backup, DNS, browser-acceptance, review,
   evidence, commit, and publication gates in this prompt.

Everything outside those boundaries is out of scope. Do not spend time
reconstructing older homelab history. Do not broaden the work into landing-page
redesign, dead-code cleanup, training experiments, or feature work before this
deployment is accepted.

This is a **full personal instance**, not a throwaway demo. It currently holds
only clean public corpora and no private user data. The Mac remains intact;
copy, never move or delete, Mac source, state, secrets, or corpora. Do not
import any old Mac Postgres, Qdrant, Neo4j, MLflow, Langfuse, lineage,
synthetic-run, test-output, or accumulated database state. LXC100's new clean
state is now valuable and must not be wiped.

## 2. Non-negotiable operating rules

- Work directly on local `main`; `origin/main` is the publication target.
- Keep **exactly one local branch and one worktree**. Do not create a feature
  branch, rescue branch, worktree, or agent-spawn branch.
- Direct commits and pushes to `main` are explicitly authorized.
- Preserve all unknown or user-owned dirty files. Never reset, clean, checkout,
  overwrite, stash, or delete them.
- Before changing an existing function/class/method, run GitNexus upstream
  impact analysis. Warn on HIGH/CRITICAL risk. Before every commit, run
  GitNexus `detect-changes` on the staged scope.
- No fake-green tests: no request interception for new/edited browser tests, no
  `unittest.mock`, no `monkeypatch`, no placeholder questions.
- Use the in-app Browser visually for DNS/auth and final product acceptance.
  Do not substitute headless-only testing. The user performs passwords, OTPs,
  passkeys, and any other sensitive credential entry.
- Paid OpenRouter calls are authorized for bounded real tests and the final GLM
  review. Do not expose provider keys or complete environment files.
- Keep Proxmox, SSH, databases, and control-plane ports private. Do not expose a
  router port. Public ingress remains Cloudflare Tunnel -> Caddy -> Authelia.
- Replacement means replacement. Do not add compatibility fallbacks, legacy
  toggles, dual paths, or fake degradation behavior.
- Do not claim completion from unit tests, HTTP 200s, or written evidence alone.
  Runtime and product claims require live operator/browser proof.

## 3. Mandatory read order before any mutation

Read these files completely, in this order:

1. `/Users/davidmontgomery/ragweld/AGENTS.md`
2. `/Users/davidmontgomery/ragweld/CLAUDE.md`
3. `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
4. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`
5. `/Users/davidmontgomery/ragweld/docs/superpowers/specs/2026-08-27-pve1-personal-deployment-design.md`
6. `/Users/davidmontgomery/ragweld/docs/superpowers/plans/2026-08-27-pve1-ragweld-rollout.md`
7. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`
8. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`
9. `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
10. this handoff again.

Older docs may contain stale milestones or historical scope. For the present
deployment state, this handoff plus fresh read-only checks wins. User-authored
W80/W81 injections in the rollout plan are active requirements; do not erase
or silently reword them.

## 4. Exact verified source state

At handoff time:

- Mac path: `/Users/davidmontgomery/ragweld`
- branch: `main`
- local branches: exactly `main`
- worktrees: exactly `/Users/davidmontgomery/ragweld`
- local `HEAD`: `c2a8e83b7009b661d2c2e109cea12f42cfb48ff1`
- `origin/main`: same commit
- ahead/behind: `0/0`
- LXC `/opt/ragweld` branch: `main`
- LXC `/opt/ragweld` commit: same `c2a8e83b...`
- LXC checkout: clean and `0/0` against its fetched `origin/main`

Commit `c2a8e83b` (`fix(deploy): harden ingestion and chat accounting`) is
already pushed and deployed. It contains:

- Debian 13 container base plus `libgl1` and `libglib2.0-0t64` for Docling /
  OpenCV;
- a fail-closed `import cv2` startup preflight;
- real non-stream and stream gateway token propagation;
- one canonical token parser shared with trace-cost accounting;
- a real local LiteLLM-compatible gateway regression covering snake_case and
  camelCase usage payloads;
- updated deployment evidence through the initial public-corpus proof.

Verification run against that exact committed candidate:

- docs ownership: pass
- banned-pattern check: pass
- generated types: pass
- LiteLLM catalog lockstep: pass, 371 aliases
- focused Ruff: pass
- full backend suite: **1,225 passed / 98 skipped / 7 warnings**
- independent GPT-5.6 token-path review after its P2 correction: no actionable
  P1/P2 findings

Do not rerun old recovery work just to rediscover this commit. Verify the hashes
and continue from here. The reviewed local source candidate below is newer than
this deployed baseline but still unpublished and undeployed.

## 5. Current dirty-worktree ownership — preserve this exactly

There are **no staged changes**. The following are dirty/untracked:

User-owned or concurrent; inspect but **do not stage, revert, or overwrite**:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/exec-plans/active/watchdog-proxmox-foundation-2026-08-28.md`
- `.claude/skills/` (untracked)

Current deployment work intended for the next scoped commit, subject to your
review and completion:

- `server/api/index.py`
- `server/indexing/text_extractors.py`
- `tests/api/test_index_batch_parallelism.py`
- `tests/unit/test_text_extractors.py`
- `docs/exec-plans/active/pve1-ragweld-deployment-2026-08-27.md`
- `docs/superpowers/plans/2026-08-27-pve1-ragweld-rollout.md`
- `tests/unit/test_proxmox_deployment_contract.py`
- `deploy/proxmox/host-capacity-guard.sh` (untracked, executable)
- `deploy/proxmox/ragweld-capacity-guard.service` (untracked)
- `deploy/proxmox/ragweld-capacity-guard.timer` (untracked)
- `deploy/proxmox/ragweld-thinpool.profile` (untracked)
- this handoff file (untracked)

The rollout plan contains historical W80/W81 review injections. Preserve them,
but treat the W80/W83 source slice as already implemented in the local source
candidate rather than remaining implementation work. Do not assume the entire
deployment-contract file belongs to you merely because it is modified; inspect
its diff before staging.

## 6. Exact verified live LXC100 state

Infrastructure:

- node: pve1, `192.168.68.171`, Proxmox VE 9.2.2
- guest: LXC100 `ragweld`, `192.168.68.225`
- allocation: 16 CPU, 24 GiB RAM, 8 GiB swap, 300 GiB root disk
- Intel render devices are passed through; do not claim NVIDIA/CUDA/vLLM or
  Unsloth acceleration
- SSH from Mac uses
  `/Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519`
- source: `/opt/ragweld`
- secrets/config: `/etc/ragweld` (never print complete files)
- host service: `ragweld.service`, enabled and active
- API: `http://127.0.0.1:58012/api/health` returns healthy
- correct health route is `/api/health`; `/health/live` is not a Ragweld route

All main containers were up at handoff: cloudflared, Flyte, Grafana,
Prometheus, Langfuse web/worker/dependencies, Postgres/exporter, Qdrant, Neo4j,
LiteLLM, MLflow, Caddy, Authelia, Loki, Promtail, Tempo, Alloy, Mimir,
Pyroscope, Alertmanager. Flyte outer health is healthy; its main sandbox pod,
metrics server, connector, registry, MinIO, Postgres, proxy, BuildKit, CoreDNS,
and local-path provisioner are running. The optional internal Kubernetes
dashboard pod is currently CrashLoopBackOff. Do not let that distract you from
the actual Flyte console/workflow contract, but classify it honestly if it
affects a required surface.

The service restart after `c2a8e83b` took about 78 seconds because the lifecycle
correctly waited for Flyte to become healthy before starting FastAPI. Do not
misdiagnose that warm-up as an API failure during the first minute.

Current capacity at handoff:

- LXC `/`: 295 GiB filesystem, 38 GiB used, 242 GiB free, 14%
- `pve/data`: 794.30 GiB, Data 7.15%, Meta 0.47%, `seg_monitor=monitored`
- pve VG: 930.51 GiB total, only 16.00 GiB free
- no LVM metadata profile is attached yet
- no Ragweld capacity timer is installed yet

## 7. Clean data plane and public-corpus proof already complete

The corpus registry contains exactly two corpora and no imported Mac/test
residue:

1. `epstein-files-public`
   - path `/srv/ragweld/corpora/epstein-files-public`
   - public Hugging Face dataset `to-be/epstein-emails`, config `default`, split
     `train`
   - exactly 2,000 text files and 200 eval rows
   - 3,126 promoted chunks, 346,731 tokens
   - Qdrant 3,126 points/indexed vectors
   - Neo4j 2,000 documents / 3,126 chunks
   - local `BAAI/bge-small-en-v1.5` embeddings; $0 indexing cost

2. `nasa-apollo-11`
   - path `/srv/ragweld/corpora/nasa-apollo-11`
   - official NTRS asset:
     `https://ntrs.nasa.gov/api/citations/19700008096/downloads/19700008096.pdf`
   - 15,973,944 bytes, 359 pages
   - SHA-256
     `3314d99654ebb2ac3e3ef0ab70a84be9519a5f071cf1362118b2b20a6f161dea`
   - Docling conversion: 601,387 markdown characters
   - 1,002 promoted chunks, 182,260 tokens
   - Qdrant 1,002 points
   - Neo4j one document / 1,002 chunks

Do not download or seed larger datasets before acceptance. Do not replace these
with private data. The old NASA archive URL returned HTML and was correctly
rejected; use only the API asset above.

Paid cited-chat proof is also real:

- post-deploy run: `c3008395-1a4c-4ba9-9574-44ba0db44edf`
- question: the dated Jeffrey Epstein/Ariane de Rothschild email question from
  the generated eval set
- answer: `cam you speak now?` with the expected source citation
- sources: 10
- `ChatResponse.tokens_used`: 1,110
- `chat.response` event tokens: 1,110
- authoritative trace total: 1,110
- provider cost: `$0.003154`
- model route: `openai.gpt-5.6-terra` through LiteLLM/OpenRouter

This closes the zero-token defect in the deployed runtime. Do not reopen it
without contradictory evidence.

## 8. Recovery state already proved, plus remaining backup gate

Verified PBS snapshot:

`pbs-beelink:backup/ct/100/2026-08-28T17:33:31Z`

An offline restore into temporary VMID 900 verified the deployment marker,
protected config/tunnel files, source checkout, frontend build, and Docker
state. The duplicate was never started and was removed after proof.

The enabled cluster PBS job `backup-pbs-cluster` now includes VMID100, uses
snapshot/zstd, keeps daily 7 / last 3 / weekly 4, and targets `pbs-beelink`.

Do not redo the destructive part of restore testing unless a new material
backup format/change requires it. Do verify whether Task 9's **logical data
backup service/timer** was actually installed; the current evidence proves the
PBS guest backup, not necessarily the database/application logical-backup
timer. If absent, implement and prove it from the existing rollout plan before
final acceptance. Never expose backup contents or secrets.

## 9. Remaining gate A — finish W75/W81 host capacity guardrails

The reviewed local source candidate is already written but not yet committed,
published, or deployed. It now covers the guardrail bug family, including the
probe-failure branch, metadata warning/critical/recovery transitions, the real
guest `df` parse path, the `lvs` exit-status failure mode, and the exact
timeout/threshold invocation shapes. The remaining work is publication and live
pve1 verification, not another source redesign.

Required design:

- Run on pve1, not inside LXC100, every five minutes.
- Resolve the destination from the configured `root@pam` email; do not hardcode
  a personal email in Git.
- Send through local `/usr/sbin/sendmail` and journal every transition.
- Guest `/`: warning 75%, critical 90%.
- `pve/data` Data% and Meta%: warning 70%, critical 85%.
- Deduplicate stable states and send recovery transitions.
- Alert separately when guest or pool measurement fails.
- Do not make guest measurement failure suppress the pool check.
- Use a nonblocking `flock`; overlapping timer activations should exit cleanly.

Critical arithmetic correction: do **not** install the stale 80/10 global LVM
setting. Ten percent of 794.30 GiB is about 79.4 GiB; the VG has only 16.00
GiB free, so that extension cannot succeed. Use the scoped per-LV metadata
profile in `deploy/proxmox/ragweld-thinpool.profile`:

```text
activation {
    thin_pool_autoextend_threshold=80
    thin_pool_autoextend_percent=1
}
```

One percent is about 7.9 GiB. It is an emergency seatbelt, not a rescue plan.
Any real extension means the operator must add/resize storage promptly. Attach
the profile only to `pve/data`; do not edit global `/etc/lvm/lvm.conf`.

Before committing, inspect the full script and units, run `bash -n`, the
focused capacity matrix, the entire deployment-contract file, and an
independent GPT-5.6 P1/P2 review. Then run the full repo gates because the test
file and docs changed.

After the candidate is committed and pushed, install the exact published
artifacts on pve1 and verify:

```bash
install -m 0755 deploy/proxmox/host-capacity-guard.sh /usr/local/sbin/ragweld-host-capacity-guard.sh
install -m 0644 deploy/proxmox/ragweld-capacity-guard.service /etc/systemd/system/ragweld-capacity-guard.service
install -m 0644 deploy/proxmox/ragweld-capacity-guard.timer /etc/systemd/system/ragweld-capacity-guard.timer
install -m 0644 deploy/proxmox/ragweld-thinpool.profile /etc/lvm/profile/ragweld-thinpool.profile
lvmconfig --type profilable-metadata --file /etc/lvm/profile/ragweld-thinpool.profile activation/thin_pool_autoextend_threshold activation/thin_pool_autoextend_percent
lvchange --metadataprofile ragweld-thinpool pve/data
systemd-analyze verify /etc/systemd/system/ragweld-capacity-guard.service /etc/systemd/system/ragweld-capacity-guard.timer
systemctl daemon-reload
systemctl enable --now ragweld-capacity-guard.timer
systemctl start ragweld-capacity-guard.service
lvs -o lv_name,lv_profile,seg_monitor,data_percent,metadata_percent pve/data
systemctl list-timers ragweld-capacity-guard.timer
journalctl -u ragweld-capacity-guard.service --no-pager -n 50
```

First validate the exact `lvmconfig` syntax on the installed pve1 LVM version;
do not attach a profile that does not validate. The normal live smoke must send
no warning at current values. Use the script's environment overrides, a
temporary state directory, and a fake local sendmail capture for a
non-destructive forced warn -> dedupe -> critical -> recovery -> probe-failure
test. Do not send synthetic warning mail to the real destination.

Rollback, if any verification fails:

1. `systemctl disable --now ragweld-capacity-guard.timer`
2. `lvchange --detachprofile pve/data`
3. remove only the installed guard script, two units, profile, and guard state
   directory
4. `systemctl daemon-reload`
5. verify `pve/data` remains monitored and unchanged

## 10. Remaining gate B — deploy and live-prove the reviewed W80/W83 source slice

The source change is already implemented locally and reviewed, but it is not
yet committed, published, or deployed. Treat `c2a8e83b...` as the deployed
baseline and the current dirty worktree as the reviewed local candidate.

Reviewed local candidate behavior:

- `server/api/index.py` routes non-stream extraction through
  `_extract_text_for_index(...)` and keeps direct/plain-text paths on worker
  threads;
- Docling work remains serialized even if an awaiting task is cancelled, while
  non-Docling/direct reads still bypass the private lock;
- `server/indexing/text_extractors.py` now owns the `_DOCLING_CONVERTER`
  invariant with a module-local `threading.Lock`;
- the runtime thread caps remain `DOCLING_NUM_THREADS=4` and
  `OMP_NUM_THREADS=4`;
- focused regressions cover FIFO event-loop responsiveness,
  unsupported-suffix fallback responsiveness, cancellation-safe serialization,
  and real concurrent singleton identity.

Do not re-implement W80 in a fresh agent. The remaining work is to rerun the
local gates on the reviewed candidate, commit/push the exact source slice,
fast-forward/deploy it to LXC100, update `/etc/ragweld/runtime.env` without
duplicates or secret output, and prove the live runtime stays responsive during
real Docling work.

Runtime proof after deploy:

- restart through `systemctl restart ragweld`;
- allow Flyte its normal warm-up;
- prove `/api/health` and `/api/ready`;
- run a real bounded Docling index operation sequentially;
- while Docling is converting, poll `/api/health` and one harmless read API;
- require successful responses during OCR, not only after it finishes;
- allow the index to reach a terminal state before browser acceptance;
- record timings and no-residue results.

Do not run Task 8 browser acceptance concurrently with a still-running index.

## 11. Remaining gate C — DNS delegation and authenticated public ingress

Netlify CLI is authenticated locally as the correct account/team. The repo is
not linked to a Netlify site, but account-level DNS was successfully read.
Authoritative Netlify records copied into Cloudflare are:

- apex `NETLIFY` + `NETLIFYv6` -> `ragweld.netlify.app`
- `www` `NETLIFY` + `NETLIFYv6` -> `ragweld.netlify.app`
- `deepseek-mcp` `NETLIFY` + `NETLIFYv6` -> `ragweld.netlify.app`
- `bird-data` A -> `169.197.22.5`

Cloudflare already contains equivalent apex/`www`, `deepseek-mcp`, and
`bird-data` records, plus tunnel hostnames for:

- `me.ragweld.com`
- `auth.ragweld.com`
- `grafana.ragweld.com`
- `langfuse.ragweld.com`
- `mlflow.ragweld.com`
- `flyte.ragweld.com`

Tunnel ID:

`ff9d38b6-5f51-45b5-a9ce-380ded0b886a`

The tunnel previously reported four active connections and is currently up.
Cloudflare assigned nameservers:

- `chance.ns.cloudflare.com`
- `kenia.ns.cloudflare.com`

The public delegation is **still** the old Netlify/nsone set:

- `dns1.p04.nsone.net`
- `dns2.p04.nsone.net`
- `dns3.p04.nsone.net`
- `dns4.p04.nsone.net`

The in-app browser is parked at GitHub login for the Netlify UI. The user must
sign in there and handle any password/OTP/passkey. Do not ask them to send a
credential. Once the UI returns to Netlify, use visual browser control to
change the registrar/delegation nameservers to the two Cloudflare values. Do
not delete the old Netlify zone until Cloudflare is active and all required
records are proved.

After the switch:

1. wait for Cloudflare zone state to become active;
2. verify public `dig NS ragweld.com` returns exactly the Cloudflare pair;
3. verify apex, `www`, inherited service names, and six tunnel hostnames;
4. verify HTTPS certificates and redirect behavior;
5. verify no database, SSH, Proxmox, or private control-plane port is public;
6. preserve apex/`www` landing behavior unless a factual deployment blocker
   requires change.

## 12. Remaining gate D — full visual external acceptance

Use the in-app Browser, not headless-only automation. The user handles the
Authelia password/OTP. Start outside localhost after DNS is active.

Required surfaces:

- `https://me.ragweld.com/web/`
- `https://auth.ragweld.com/`
- `https://grafana.ragweld.com/`
- `https://langfuse.ragweld.com/`
- `https://mlflow.ragweld.com/`
- `https://flyte.ragweld.com/`

Perform a true curious-user drive:

- authenticate and prove no bypass/redirect loop;
- click every top-level Ragweld tab and subtab;
- scroll each surface fully;
- change between both corpora;
- inspect index history and statuses;
- run a real search;
- ask one cited question against each corpus;
- verify citations and source opening;
- inspect graph nodes, edges, zoom, and details;
- inspect eval analysis/drilldown;
- inspect training controls without launching an unbudgeted training run;
- open Grafana, Langfuse, MLflow, and Flyte from the workbench and directly;
- inspect browser console/network errors;
- verify responsive usability at the available mobile/narrow viewport because
  the user is remote from a phone.

Fix only deployment blockers in this session: auth bypass/loop, broken API
proxy, missing static assets, wrong external URLs, unreadable persistent state,
missing required service, or failure of the required text/PDF workflows.
Record nonblocking frontend findings, with screenshot/URL/action/expected/
actual/console/network/severity, in:

`/Users/davidmontgomery/ragweld/docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`

Do not launch a broad frontend redesign. The known Admin configuration sections
need collapsible treatment, but unless they block deployment acceptance, log
them for the dedicated frontend session rather than derailing this closeout.

## 13. Remaining gate E — verification, review, publication, and evidence

For every code change, run the narrow test first, then the standard gates:

```bash
cd /Users/davidmontgomery/ragweld
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/generate_litellm_config.py --check
uv run pytest -q
```

If frontend code changed:

```bash
npm --prefix web run lint
npm --prefix web run build
```

Also run:

- focused Ruff on every touched Python test/source file;
- `bash -n` on every touched shell script;
- `git diff --check`;
- GitNexus `detect-changes --scope staged --repo ragweld`;
- relevant real-browser acceptance after deploy.

Before commit, obtain an independent GPT-5.6 Sol/xhigh adversarial review of
the exact staged diff and live deployment evidence. Ask it to refute the
storage guard, LVM arithmetic/profile attachment, probe-failure behavior,
event-loop offload, runtime env update, DNS/auth boundary, test honesty, and
rollback. Resolve every actionable P1/P2 and re-review the corrections.

Then run the paid OpenRouter `ox-alpha/glm-5.3-flash` adversarial review with
full context: staged diff, both active deployment docs, source/lifecycle
scripts, exact test output, LXC runtime facts, DNS state, browser evidence,
rollback, and acceptance criteria. Do not give it a tiny summary or a few-minute
timeout. Resolve actionable P1/P2 and rerun affected gates.

Stage only owned/in-scope files by explicit path. Never use a broad `git add .`.
Commit directly to `main`, push `origin main`, fast-forward the clean LXC
checkout, and deploy the exact hash. Then update the evidence with the deployed
commit and live proof; commit and push that evidence too.

## 14. Definition of done — do not declare success before all are true

Source and topology:

- local and LXC `main` contain the final pushed commit;
- local `main` and `origin/main` are `0/0`;
- exactly one local branch and one worktree;
- no uncommitted in-scope product/deployment changes remain;
- user-owned/concurrent dirty files are preserved untouched.

Runtime:

- `ragweld.service` survives a clean restart and reaches API ready state;
- required containers/services are healthy or any upstream optional residual is
  explicitly classified with evidence;
- Docling conversion no longer blocks API responsiveness;
- both corpora remain registered/indexed/citable;
- real paid GPT-5.6 Terra chat returns nonzero tokens matching the authoritative
  trace and cost record;
- no old/private data was imported.

Capacity/recovery:

- `pve/data` has the validated scoped 80/1 metadata profile attached;
- `seg_monitor=monitored`;
- five-minute guard timer is enabled and scheduled;
- normal live run is clean;
- synthetic warn/dedupe/critical/recovery/probe-failure paths are proved with
  fake delivery;
- rollback is recorded;
- PBS scheduled backup still includes VMID100;
- logical backup requirement is either proved installed/working or explicitly
  closed with equivalent verified recovery evidence from the approved plan.

DNS/auth/browser:

- Cloudflare zone active;
- public NS exactly the Cloudflare pair;
- all inherited and tunnel hostnames resolve correctly;
- external HTTPS and Authelia authentication work with no bypass/loop;
- full visual curious-user drive completed after indexing is idle;
- companion UIs open and function;
- nonblocking frontend bugs are logged with evidence.

Quality/closeout:

- required local validators and full backend suite green;
- frontend lint/build green if touched;
- relevant real-browser suites green;
- GitHub CI billing blocks, if any, are distinguished from actual failures;
- GPT-5.6 adversarial review has no unresolved actionable P1/P2;
- paid GLM adversarial review has no unresolved actionable P1/P2;
- final evidence/handoff states exactly what is working, what was measured,
  costs, backup/rollback, and any honest residual;
- final commits pushed to `origin/main`.

Only then mark the goal complete.

## 15. First actions for the fresh agent

1. Complete the mandatory read pass.
2. Run read-only branch/worktree/status/hash checks on Mac and LXC100.
3. Inspect the dirty diffs and re-establish file ownership; do not stage yet.
4. Review the four W75/W81 artifacts and the focused capacity tests; run
   `bash -n` and the entire Proxmox deployment-contract test file.
5. Re-run the focused W80/W83 and capacity regressions on the reviewed local
   candidate, then the full gates; do not re-implement W80.
6. Run focused tests, full gates, GitNexus staged analysis, and independent
   GPT-5.6 review.
7. Commit/push the scoped source slice to `main`.
8. Fast-forward/deploy LXC100; update its protected runtime env without
   duplicates or secret output.
9. Install/attach/enable/verify W75/W81 on pve1 with rollback ready.
10. Prove API responsiveness during real Docling work and wait for indexing to
    become idle.
11. Ask the user only for the in-browser login handoff, finish nameserver
    delegation, and verify propagation.
12. Run the full external visual acceptance and log nonblocking frontend issues.
13. Close logical backup evidence, final GPT-5.6 + GLM reviews, final gates,
    evidence commit, push, and exact topology verification.

Do not drift. Do not restart completed projects. Do not claim “enterprise
grade” from architecture diagrams or green unit tests. Finish the actual live
operator path and prove it.
