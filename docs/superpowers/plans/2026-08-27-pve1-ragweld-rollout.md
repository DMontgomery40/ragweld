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

### 0458f505 is published and green — two preflight checks before the guard goes on pve1

Good commit. `HEAD == origin/main == 0458f505`, tree clean, and the full gate is
green at it: all four validators pass and `uv run pytest -q` gives 1241 passed,
98 skipped. W102's restructure went past the one-line fix I asked for — one
`try` spanning `to_thread` → `create_task` → `add_done_callback` →
`await shield`, with `callback_registered` driving the `finally`. I traced every
reachable path and they are all correct, including the one that matters: on
cancellation the lock is *not* released, so the done-callback frees it only
after the orphan thread finishes and nothing can race an in-flight OCR job.

W90, W91 and W98 are all that remain from the code phase and none of them block
anything. Sweep them whenever. The risk has moved to the host, so these two are
about the install.

**W104 (do this first) — confirm `root@pam` has an email before enabling the
timer.** `resolve_alert_email` extracts it with `str(row.get("email") or "")`,
which returns empty when the field is unset and exits 0; the empty value is
then caught by the address regex, which calls `die`. So an unset address means
the guard exits 1 on every firing, every five minutes, forever — unit
permanently failed, no capacity alert ever delivered. That is especially bad
here because `--conflict-exit-code 0` makes real skips exit 0, so a failed unit
is exactly the signal that would otherwise mean something genuine. Check it in
one command:

```bash
pveum user list --output-format json | python3 -c \
  "import json,sys; print([r.get('email') for r in json.load(sys.stdin) if r.get('userid')=='root@pam'])"
```

`[None]` or `['']` means either set it in Datacenter → Permissions → Users →
root@pam, or add `Environment=RAGWELD_CAPACITY_ALERT_EMAIL=…` to the unit. The
PVE installer does prompt for an admin email so it is probably set, but this is
the single most likely first-run failure and it costs one command to rule out.

**W103 (one line) — `export LC_ALL=C` at the top of the guard.** `is_number`
hard-codes a `.` decimal separator and nothing pins the locale. Under a
comma-decimal locale `lvs` prints `71,0`, the check fails, and the guard takes
the probe-failure branch — so it alerts "storage probe failed" forever and you
lose thin-pool monitoring while believing it is running. Likelihood is genuinely
low (systemd does not inherit an interactive locale, and PVE runs `en_US.UTF-8`
or C), but it is one line and it removes the whole class for a script whose job
is scraping numbers out of tool output.

**And the general point for this phase:** every test so far has driven the guard
through fake `pveum`, `pct` and `lvs`. First contact with the real ones happens
on pve1. Gate enabling the timer on one proven real invocation —
`systemctl start ragweld-capacity-guard.service` then check the journal and the
state files — rather than on `systemctl enable` returning 0.


### W102 — your W97 fix beat my prescription; one line still sits outside the guard

Two things you added that I had not thought of, both correct. You `close()` the
orphaned coroutine when `create_task` fails, which kills the
`coroutine ... was never awaited` warning I would have shipped. And when
`add_done_callback` is the thing that raises, you `await asyncio.shield(worker)`
before releasing, so the thread finishes before the lock frees — that preserves
the serialization invariant on the error path instead of merely avoiding the
deadlock, which is the better of the two available fixes.

The residual is one line. `worker_coroutine = asyncio.to_thread(func, *args,
**kwargs)` is still constructed *above* the `try`. That call allocates a
coroutine object, and that allocation is precisely the `MemoryError` candidate
I used to argue W97 in the first place. So the window I reproduced went from
three statements to one rather than closing. Move it inside the existing `try`
and initialise `worker_coroutine = None` next to `worker` so the `close()`
branch stays correct.

**Where to stop.** `released = False` and the `_release_lock` closure are also
allocations in that window, so only making `try` the first statement after
`acquire()` closes it completely. Don't. A `MemoryError` during `MAKE_FUNCTION`
is a process already dying, and restructuring for it costs readability and buys
nothing. Move the `to_thread` call and leave the rest.

**One thing I found and am explicitly not asking you to change.** In the
`except BaseException` branch where `worker is not None`, the shielded await
sits inside an exception handler; if the original exception was `CancelledError`
that await can be cancelled immediately, fall through `except BaseException:
pass`, and release the lock while the worker thread is still running. Getting
there requires `add_done_callback` to raise, which needs a non-callable
callback. Recording it so it is not rediscovered as a surprise later — adding
cancellation handling to an unreachable branch would cost more clarity than it
buys.

Still open from earlier: W98 (have the done-callback consume the orphan's
exception), W90 (assert `--conflict-exit-code 0`, not just `flock --nonblock`),
W91 (`Persistent=true` is inert on a monotonic-only timer but pinned as
contract).


### W97 raised to P2 — I reproduced the ingestion deadlock; and W95 is closed

W95 is done and your fix is better than the one I asked for: all four doubles
now use `if [[ "$1" == --kill-after=* ]]; then shift 2; else shift; fi`, so each
tolerates both argv shapes rather than only the new one. Contract file is 48
passed, 0 failed. I am dropping the hoist request — three prologues are now
byte-identical and the fourth only adds a `pct` case after the same prologue, so
the live defect is gone and only the cost of a future sweep remains. Housekeeping
if you touch it again; not a commit blocker.

**W97 is the one to fix before you commit.** I stopped arguing it and
reproduced it, replicating the structure of `_run_docling_extraction_locked` in
a standalone script with a forced failure in the `acquire()` → `try` window:

```
lock held before:        False
raised:                  MemoryError
lock held AFTER failure:  True
next extraction DEADLOCKED on acquire() -> all Docling ingestion blocked
```

The second caller never acquires. `_DOCLING_EXTRACTION_LOCK` is a module-level
singleton, so that is every subsequent PDF, DOCX, PPTX, XLSX and HTML ingestion
for the life of the process, recoverable only by restart. That is why I am
moving it from P3 to P2 — narrow trigger, total blast radius.

To be straight about the evidence: what I proved is that *any* exception in
that window strands the lock and hangs the next caller. I did **not** produce a
real `MemoryError` from `create_task` in situ; that trigger is credible on a
24 GiB guest running OCR (both `create_task` and the `to_thread` coroutine
allocate), and loop-shutdown `RuntimeError` is the other candidate, but neither
is demonstrated. The structural defect is the thing to fix, and it wants fixing
whichever trigger you think likeliest, because the fix is four lines:

```python
try:
    worker = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    worker.add_done_callback(_release_lock)
except BaseException:
    _release_lock()
    raise
```

`BaseException`, not `Exception` — a cancellation delivered in that window must
not strand the lock either. W98 (consume the orphan's exception in the
done-callback) still stands and is cheaper still.


### W97 / W98 — the cancellation-safe Docling lock is good work; it can still strand itself

W86 and W92 both landed better than I asked for. On W86 you replaced the weak
substring check with a full-line anchored regex that pins the label and the
`|| status=1`, ran metadata through the whole 71 → 86 → 10 cycle, and — the
part I liked — answered the count-coupling trap by swapping the brittle
`count(...) == 2` assertions for explicit presence *and absence* checks, which
is what those counts were badly approximating anyway. On W92 your status delta
separates the deployed baseline from the reviewed local candidate and says "do
not invent its future hash", which forecloses a failure I had not thought to
guard against.

`_run_docling_extraction_locked` is also the right design, and not the obvious
one. `async with lock: await asyncio.to_thread(...)` looks correct and is not:
cancel the caller and the lock drops while the OS thread keeps running Docling,
so a second extraction runs concurrently with the orphan and the serialization
is defeated. `shield` plus `add_done_callback` plus the idempotent `released`
flag plus `finally: if worker.done()` to close the `call_soon` window is
careful work.

**W97 — the acquire sits outside the try.** Lines 1483 through 1494 —
`acquire()`, `create_task`, `add_done_callback` — are all before the `try` at
1495. Anything raising in that window leaves a module-level lock held by nobody
and released by nothing, so **every subsequent PDF, DOCX, PPTX, XLSX and HTML
ingestion blocks forever on `acquire()` until the process restarts.** Not as
theoretical as it sounds: `create_task` raises `MemoryError` under allocation
pressure, and the one path where that is plausible here is the one about to
hand a 359-page PDF to an OCR pipeline on a 24 GiB guest. It would also present
as "indexing hangs, API stops progressing" — identical to the W77 symptom you
just fixed, so it would likely be misdiagnosed as that regressing.

Wrap the wiring: `try: worker = create_task(...); worker.add_done_callback(...)
except BaseException: _release_lock(); raise`. `BaseException`, not
`Exception` — a cancellation delivered in that window must not strand the lock
either.

**W98 — the orphan's exception is never retrieved.** Once the caller is
cancelled nothing awaits `worker` again, so a Docling failure surfaces as a
detached `Task exception was never retrieved` at GC time, attributed to no
request. Not a correctness bug, a diagnosability one, and it lands on exactly
the operator who is already staring at odd ingestion behaviour. Have the
done-callback consume it — it already receives the future — and log it with a
line saying the caller had gone away.

**One freshness note on the delta itself,** since it is the same shape as the
problem it fixed: it lists W80/W83/W86/W87/W88/W89 as implemented but not W90,
W91 or W95, which are open. Either add them, or give the block a standing rule
— "anything not listed here is tracked in the watchdog file" — so it degrades
honestly instead of reading as complete.


### W95 — you swept three of the four `timeout` doubles; the fourth is the failing test

W87 and W88 are both landed and good — `text_extractors.py` now has
`import threading`, `_DOCLING_CONVERTER_LOCK` and `with _DOCLING_CONVERTER_LOCK:`,
so the module-local invariant sits underneath your `asyncio.Lock` policy exactly
as I asked, and the test that measured seven duplicate converters is green.

Adding `--kill-after=10s` to `run_with_timeout` was right. The problem is that
your `timeout` doubles emulate that CLI positionally, and you updated three of
them (test lines 1099, 1164, 1293, each gaining
`if [[ "$1" == --kill-after=* ]]; then shift 2`) and missed the fourth at line
1423, which is still a bare `shift` then `exec "$@"`. I ran it both ways to be
sure:

```
double 9s echo hi                    -> hi
double --kill-after=10s 9s echo hi   -> exec: 9s: not found  (127)
```

One `shift` eats the flag, so it tries to exec a program called `9s`.

Watch the bit that hides it. That double serves a parametrised test: the
`exit 42` case expects "pveum user list failed" and the `not-json` case expects
"pveum returned malformed JSON". With the double broken *both* commands die at
127, so both emit "pveum user list failed" — the first case still passes, but
only because the broken fixture produces the string it was looking for; the
fake `pveum`'s `exit 42` is never reached. A completely broken double therefore
shows up as one failure instead of two, which is why it reads like an isolated
red-first test rather than a sweep you didn't finish.

Fix the fourth double, but do the structural fix too: hoist one
`_FAKE_TIMEOUT_SOURCE` constant (or a fixture that writes it) and point all four
call sites at it. Four hand-copied emulations of one CLI is what made an
incomplete sweep possible in the first place — with one copy, the next flag on
`run_with_timeout` is a one-line change.

**Rule to carry:** a test double that reimplements a CLI's argument parsing is
coupled to the caller's exact argv shape, and nobody diffs scaffolding against
its caller. Positional doubles also fail with plausible-looking error text, so
the symptom reads as a product bug instead of a fixture bug. Keep one copy, and
parse flags rather than count positions.

For the record, the other two current failures are not regressions:
`test_docling_cancellation_keeps_lock_until_blocking_worker_finishes` is
red-first against a symbol you have not added yet, and
`test_proxmox_capacity_guard_alerts_on_real_guest_df_output_without_override`
is the W87 landing — it passes in a full-file run now (47 passed, 1 failed).


### W90 / W91 / W92 — the capacity unit is good; two assertions cover the wrong half, and the handoff is still on disk

The service and timer are well built and I want that noted before the nitpicks:
`--conflict-exit-code 0`, `install -d -m 0700 "$STATE_DIR"` (atomic mode, better
than the `mkdir -p` I went looking for), `UMask=0077`,
`ConditionPathExists=/etc/pve/lxc/100.conf` so it no-ops on a host without the
guest, `After=pve-cluster.service lvm2-monitor.service`, and
`RandomizedDelaySec=30s`. Two weak assertions against that much correct detail
is a good ratio.

**W90 — assert the flag that carries the behaviour.** The test says
`assert "flock --nonblock" in service`, which matches whether or not
`--conflict-exit-code 0` is present. That flag is the whole point: without it a
skipped overlapping run exits 1, a `Type=oneshot` unit records a failure, and
since the timer keeps firing you get a permanently failed unit that masks the
real alerts the guard exists to raise. Assert the full flag set, or anchor a
regex on the entire `ExecStart=` line so the lock path and script path are
pinned too.

**W91 — `Persistent=true` does nothing here.** Per `systemd.timer(5)` it only
has an effect on timers configured with `OnCalendar=`, and this timer is
monotonic-only (`OnBootSec`/`OnUnitActiveSec`). The test asserts it anyway,
which pins a no-op as contract and reads as "missed runs are caught up after
downtime" — they are not. Harmless in practice, since `OnBootSec=5m` already
covers the after-downtime case, so this is about the contract claiming
something untrue. Drop the directive and its assertion, or keep it with a
comment saying it is inert until an `OnCalendar=` exists.

**W92 — finish the handoff fix you started.** Unstaging
`handoff-2026-08-28-pve1-fresh-agent.md` was the right call and it closes the
sharp edge of W89: the commit will no longer contain both the W80
implementation and a document instructing someone to write it. But the file is
still on disk in `docs/exec-plans/active/`, which AGENTS.md puts in mandatory
read order — and read order is a filesystem path, not a git query. Any agent in
this checkout still hits §10 "Remaining gate B" for work that is already done.
Now that it is untracked the edit is free: put the status delta under the
existing "current through 2026-08-28 13:50 MDT" stamp — W80 closed, gate A
authoring closed with five test functions and only the pve1 install remaining,
W83/W86/W87/W88/W90/W91 open.


### W89 — before you commit: the handoff you staged tells a fresh agent to build what is in the same commit

Everything is staged and nothing is committed yet, so this is easy to fix now
and annoying to fix later. I checked the staged diff for secrets first: clean —
the only secret-shaped strings are two git SHAs and the SHA-256 of the public
NASA NTRS fixture, which is good practice to pin. Hosts are your own domains,
IPs are RFC1918. No reason to hold the commit.

The problem is `docs/exec-plans/active/handoff-2026-08-28-pve1-fresh-agent.md`.
It is stamped "current through 2026-08-28 13:50 MDT" and the W80 work landed
after that stamp, so one commit will contain both the offload
(`server/api/index.py:1475-1500`), `_DOCLING_EXTRACTION_LOCK` at 115, the
`DOCLING_NUM_THREADS`/`OMP_NUM_THREADS` caps and four passing regressions —
*and* §10 "Remaining gate B — implement W80 event-loop offload and explicit CPU
cap", whose step 5 says "Implement the W80 FIFO event-loop regression first,
watch it fail, then add the offload." `docs/exec-plans/active/` is mandatory
read order under AGENTS.md, so a fresh agent follows that and writes a test that
passes immediately, which is the most confusing place to start.

Also stale in the same file: §9 says "three focused tests" — there are five test
functions now, six cases — and it frames gate A as unfinished when the artifacts
are authored and tested and only the pve1 install remains.

Do not rewrite the gate bodies; the reasoning in them is worth keeping. The file
already has a "current through" stamp, so put a short **status delta** right
under it: W80 closed (offload, lock, thread caps, four tests), gate A authoring
closed with five test functions and only installation outstanding, W83/W86/W87/
W88 still open. A fresh agent then hits the delta before it reaches any spent
imperative.

**Rule to carry:** a handoff is a snapshot, but committing it into a
mandatory-read directory turns it into a standing instruction. When a snapshot
and the work it describes land in the same commit, the snapshot must carry a
delta — or it should not be in the mandatory-read path at all.


### W88 — your Docling lock is better than the fix I asked for; keep it, and add the small one underneath

You ignored my `threading.Lock` suggestion and did something better, so take
the credit: `_DOCLING_EXTRACTION_LOCK` held across the whole extraction, with
non-Docling suffixes bypassing it, bounds total OCR concurrency to one. My
version would only have stopped the duplicate model load and still allowed N
corpora to run N concurrent OCR jobs at 4 threads each. Yours attacks the
symptom I actually measured in W77 — roughly 7.5 cores across 152 threads — not
just the memory spike. And
`test_unsupported_suffix_fallback_bypasses_the_docling_lock` is a good test:
proving a plain read is *not* serialized is the part most people skip.

Two things to finish.

**Add the module-local lock as well — it is not redundant.** The guard now
lives in `server/api/index.py` while the state it protects
(`_DOCLING_CONVERTER`) lives in `server/indexing/text_extractors.py:13`, still
an unguarded check-then-set in a module that imports no `threading`. The
invariant became "any caller of `extract_text_for_path` on a Docling suffix
must hold `server.api.index._DOCLING_EXTRACTION_LOCK`", which nothing states
and the owning module cannot enforce. It holds only because there is exactly
one production caller today; a Flyte ingest task, a CLI path or a script would
each break it silently. `asyncio.Lock` is also per-event-loop, so any second
loop gets nothing. Treat the two as different things — yours is the policy, the
five-liner is the invariant — the same belt-and-braces call you made with
`DOCLING_NUM_THREADS` plus `OMP_NUM_THREADS`. Add a one-line comment at the
global naming the guarantee, so it is readable where the state is defined.

**Write down that the serialization is intentional.** Holding the lock across
the full extraction means two corpora can never OCR in parallel; multi-corpus
indexing wall-clock is now serialized. On a 24 GiB guest with a 4-thread cap I
want that, so keep it — but record it as a deliberate throughput decision tied
to W77. Otherwise the next person chasing slow parallel indexing finds the lock,
sees no rationale, and removes it.


### W86 / W87 — the capacity-guard tests are good; close the two branches they step over

The new guard tests are the right shape and I want that shape kept. They run
the script under `bash` against fake `sendmail`/`logger`/`timeout`/`pveum`/`lvs`
binaries and assert real behaviour — dedup, escalation, RECOVERED, a probe
timeout that must not suppress its sibling, no state written when delivery
fails plus a clean retry, the exact `timeout` argv, and no `Traceback` on
`pveum` failure. The `0 < TimeoutStartSec < OnUnitActiveSec` overlap invariant
is a genuine invariant, not a string match. That is how shell should be tested
here.

Two branches are stepped over, both cheap to close with the harness you already
built.

**W86 (do this one) — `pool_meta` never alerts in any test.** Every case pins
metadata below warning (`RAGWELD_POOL_META_PERCENT: "10"`, and the fake `lvs`
printing `71.0 10.0`), so `send_transition pool_meta ... 70 85` at
`host-capacity-guard.sh:231` has no behavioural proof at all. The only guard on
those numbers is `assert "70" in guard and "85" in guard` — a whole-file
substring test that still passes if the thresholds are swapped or if the digits
turn up inside an unrelated number. You already do this properly for the timer
with an anchored `re.search`, so match that: assert on the call line itself for
all three pairs (`guest_root 75 90`, `pool_data 70 85`, `pool_meta 70 85`), and
add warning/critical/recovered cases for metadata.

This is the branch that matters most. A data-full thin pool blocks new writes;
a metadata-full thin pool goes read-only and needs offline `thin_check` /
`lvconvert --repair`. The least-tested threshold is guarding the worse
outcome.

Trap before you write it: the existing assertions say
`count("Subject: [Ragweld][WARNING]") == 2`, and that 2 is guest_root plus
pool_data. Push metadata over 70 inside the shared `base_env` and those counts
break in cases that have nothing to do with your change. Give the metadata case
its own state dir and its own env.

**W87 (small) — no test ever runs the `df` parse successfully.** The dedup and
retry tests inject `RAGWELD_GUEST_USED_PERCENT`, and the one test that reaches
the real command forces `timeout` to exit 124, so
`df --output=pcent / | tail -n 1 | tr -d ' %'` at line 201 is never executed
against real output. Your `lvs` side is covered properly — the fake prints
`71.0 10.0` and that exercises the column split and the `${value%%.*}`
truncation. Mirror it: a fake `pct` printing `Use%` then ` 76%`, with
`RAGWELD_GUEST_USED_PERCENT` unset, asserting the guest_root WARNING fires.

**Rule to carry:** an env seam that injects an already-parsed value is useful,
but every test that uses it skips the parsing it was meant to cover. When a
script has a probe and a parse, at least one test per probe has to go through
the real command shape.


### W83 — lock the Docling converter singleton, in the same slice as the W80 offload

The `asyncio.to_thread` offload is right and I want it kept. It has one
consequence you need to close before this ships: it removed the mutual
exclusion the event loop was giving you for free.

`server/indexing/text_extractors.py:21-26` builds `_DOCLING_CONVERTER` with an
unguarded check-then-set, and that file imports no `threading`. That was safe
only while extraction ran on the single event-loop thread. It now runs in the
default thread pool, and the run fence is per-corpus — `server/api/index.py:119`
is `_ACTIVE_RUNS: dict[str, str]` keyed by `repo_id` — so two corpora indexing
at once puts two executor threads into that function, both seeing `None`, both
loading Docling's layout and OCR weights. On a 24 GiB guest that duplicate load
is the memory spike, and its trigger ("two corpora at the same time") makes it
nearly unreproducible after the fact.

Do it as double-checked locking with a module-level `threading.Lock()` — no
behaviour change, five lines. **You already wrote this pattern in the file you
are fixing:** `server/api/index.py:462` guards `_EVENT_WRITER` with
`with _EVENT_WRITER_LOCK:` around exactly this check-then-set. So make the
converter match `_ensure_event_writer` — same idiom, already shipped and
reviewed. `_DOCLING_CONVERTER` is just the one that predates the offload.

Keep it to that one symbol. I audited the rest: it is the only lazily-created
`= None` module global in `server/`, the other module-level containers are
constant lookup tables or `@lru_cache` (thread-safe in CPython), `_ACTIVE_RUNS`
is never touched from an offloaded callee, and `_flush_run_events_sync` only
does a thread-safe `Queue.join()`. **Do not turn this into a codebase-wide
locking sweep.** And W80 itself needs nothing further — `extract_text_for_path`
has exactly one production caller and it is your offload wrapper, so no second
blocking call site was left behind. Red test first, in
`tests/api/test_index_batch_parallelism.py` next to the W80 test: set
`_DOCLING_CONVERTER = None`, run two `asyncio.to_thread(_docling_converter)`
calls under `asyncio.gather`, and assert the two returns are **the same object**
(`a is b`). Identity is the honest assertion — true only if exactly one
converter was built, no mocking required, and red today.

**Carry the rule, not just the patch:** moving a sync function into a thread
pool promotes every lazy global in its transitive callee set from
single-threaded to concurrent. Audit that set for module-level caches whenever
you offload, and land the offload and the lock together.

**Credit where it is due on W80 itself:** extracting a module-level
`async def _extract_text_for_index` is better than the inline `to_thread` I
asked for — it is an addressable symbol, so GitNexus impact works on it and it
is unit-testable on its own. And the named-pipe test is the right proof: it
asserts the loop resumes while extraction blocks, with no services and no
mocks. Both halves of the thread cap check out too — I verified
`DOCLING_NUM_THREADS` and `OMP_NUM_THREADS` each resolve to
`AcceleratorOptions.num_threads == 4`, and `set -a` in
`source_private_env_file()` does export them to uvicorn.


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
- **W54 (revised 2026-08-28 with the authoritative Netlify API inventory) —
  public `dig` and Cloudflare quick-scan both missed live records.** The logged-in
  Netlify CLI `getDnsZones` response is the source of truth for the existing
  zone. It reports seven source records: managed `NETLIFY` + `NETLIFYv6` pairs
  for the apex, `www`, and `deepseek-mcp`, plus
  `bird-data.ragweld.com A 169.197.22.5`. There is no MX, apex TXT, `_dmarc`,
  CAA, or DKIM record. Cloudflare's quick scan found only the eight concrete
  A/AAAA answers for apex and `www`; it omitted both service subdomains.
  Before delegation, preserve all logical records: retain the scanned apex/www
  A/AAAA records, add DNS-only `deepseek-mcp CNAME ragweld.netlify.app`, and add
  DNS-only `bird-data A 169.197.22.5`. The rollback nameservers are
  `dns1-4.p04.nsone.net`; the assigned Cloudflare nameservers are
  `chance.ns.cloudflare.com` and `kenia.ns.cloudflare.com`. Task 5 Step 1 must
  use the authenticated Netlify export, not a guessed list of `dig` names.
  ~~Original text below.~~
- **W54 (original) — export the zone; do not rebuild it from `dig`.** Task 5 Step 1's five
  `dig` queries cannot enumerate DNS — they only answer for names already
  known — so DKIM (`<selector>._domainkey`), DMARC (`_dmarc`), CAA, and any
  verification or service subdomain would be lost silently at delegation, and
  lost mail auth shows up days later as spam-foldering rather than as an
  outage. Before Step 2: export the full zone from the current provider
  (BIND export or the complete record list) into the evidence appendix, import
  that file into Cloudflare rather than hand-recreating records, and diff
  name/type/value and record count against the export before changing
  nameservers — stop if they differ. If no export is available, additionally
  query `CAA`, `_dmarc`, each mail-provider DKIM selector, and every hostname
  in the provider dashboard, and record an explicit "no mail on this domain"
  if that is the truth. Lower TTLs to 300s at the current provider first so
  rollback is minutes. Record the exact original nameserver pair beside the
  export; reverting means restoring those two values and nothing else.
- **W53 — obsolete after the physical media move.** Plex media is now local to
  `.173`; pve1 no longer runs NFS or participates in Plex I/O. Do not install
  the proposed NFS OOM guard and do not reduce LXC 100 to 20 GiB for that old
  coupling. Keep the approved 24 GiB LXC allocation, then re-check real pve1
  headroom after the full stack starts.
- **W64 (P1, blocking) — Authelia's OIDC key template is YAML-quoted and cannot
  parse.** `ragweld.service` fails at `compose up --wait` because
  `ragweld-authelia-1` crash-loops with `'identity_providers.oidc.jwks[0].key'
  could not decode to a schema.CryptographicKey: illegal base64 data at input
  byte 0`. The filter is enabled and the PEM is valid; the bug is in repo source
  `deploy/proxmox/authelia/configuration.yml:53`, where the template is wrapped
  in single quotes. `mindent N "|"` is meant to emit a block scalar, so the
  quotes collapse it to a one-line string. Drop them:
  `key: {{ secret "/config/oidc-rsa.pem" | mindent 10 "|" | msquote }}`, and fix
  the contract test at `tests/unit/test_proxmox_deployment_contract.py:864-869`
  which currently pins the broken string as the expected value. Then add a real
  `authelia validate-config` test against the pinned image so config that
  Authelia cannot load fails in CI rather than on the node.
- **W62 — trim the provider-key allowlist before copying.** Verified on the
  Mac: `OPENROUTER_API_KEY` (len 73, in `infra/litellm.env`) and
  `OPENAI_API_KEY` (len 167, in `.env`) are real and will copy correctly — the
  old "key only in the parent shell env" failure does not apply. But
  `VOYAGE_API_KEY` (15), `COHERE_API_KEY` (15) and `JINA_API_KEY` (13) are
  placeholder-length and would install credentials that fail at first use,
  making a bad key look like a Ragweld bug. Copy only `OPENROUTER_API_KEY` and
  `OPENAI_API_KEY`, and record the other three as deliberately not installed.
  Note also that `/etc/ragweld/litellm.env` is keyless and
  `/etc/ragweld/tribrid_config.json` absent until Steps 6-7 run, so
  `start-runtime.sh` failing closed before then is correct sequencing, not a
  stack fault.
- **W60/W63 (operator decision 2026-08-28) — Proxmox firewall stays off; close
  the API socket instead.** David runs a Firewalla MSP Pro with IPS/IDS and no
  port-forward, so the perimeter is covered and the datacenter firewall will
  not be enabled. Delete or rename `/etc/pve/firewall/100.fw` so a file reading
  `policy_in: DROP` does not masquerade as an active boundary. The residual a
  gateway device cannot cover is same-subnet LAN traffic, which never traverses
  the router: with `SERVER_HOST=0.0.0.0` (from W3) the **unauthenticated**
  Ragweld API on `192.168.68.225:58012` would be reachable by any LAN device,
  bypassing Authelia — everything else is already loopback-bound (32 Compose
  `127.0.0.1:` bindings, Caddy `default_bind 127.0.0.1`). Before Task 4, add an
  in-guest nftables table allowing 58012 from `127.0.0.1` and `172.16.0.0/12`
  and dropping the rest, then prove it after Task 4: `curl` to
  `192.168.68.225:58012/api/health` fails from another LAN host while
  succeeding from inside the guest and from a container via `172.17.0.1`.
  ~~Superseded text below.~~
- **W60 (superseded) — the LXC 100 firewall is written but not enforced.** `100.fw` has
  `enable: 1` / `policy_in: DROP` and `net0` carries `firewall=1`, but
  `/etc/pve/firewall/cluster.fw` does not exist, `pve-firewall status` is
  `disabled/running`, and `iptables -S` contains **zero** PVEFW chains — so the
  guest rules are inert and LXC 100 is open on the LAN. Task 2 Step 6's probe
  cannot catch this: nothing is listening on 58000/58012 yet, so "not
  reachable" passes for the wrong reason. Before Task 4: create
  `/etc/pve/firewall/cluster.fw` with `[OPTIONS] enable: 1` (with SSH sessions
  already open to both nodes, and after confirming `host.fw` policy keeps node
  management reachable), then prove *enforcement* — `pve-firewall status`
  reports enabled, `iptables -S | grep veth100i0` shows guest chains, and a
  LAN probe against a **listening but disallowed** port is refused. Re-run the
  58000/58012 probe after Task 4 when those ports are genuinely bound. If the
  datacenter firewall is deliberately staying off, record that decision and
  delete `100.fw` rather than leaving a file that reads as a boundary — spec §5
  is then knowingly unmet and the tunnel plus loopback binds are the only
  boundary.
- **W77 (P1, observed live) — the API is unresponsive while Docling indexes, so
  Task 7 and Task 8 must not overlap.** At 18:30Z with a PDF mid-OCR
  (`A11_MissionReport.pdf`, rapidocr/CPU), `/api/health` and `/api/ready` both
  returned `000` with 17 connections queued on the listen socket, uvicorn up
  1h and holding ~4.4 GB RSS. `/api/health` does no dependency checks, so this
  is the event loop being blocked by CPU-bound native OCR, not an outage.
  Until Docling parsing is moved off the loop (ProcessPoolExecutor or a worker
  process): run Task 8's external browser acceptance **only after** Task 7
  seeding has finished, never concurrently, and record in the evidence that the
  API does not answer during indexing so a timed-out UI pass is not
  misdiagnosed as a deployment failure. Note also that Prometheus scrapes
  `/metrics` on the same loop, so expect scrape gaps during seeding.
  **Measured 18:45Z — not a hang, saturation:** onnxruntime/rapidocr fans out
  to ~152 threads consuming ~7.5 of the LXC's 16 cores on one scanned PDF,
  still running after 15 minutes, backlog grown to 115 queued connections,
  while 12 GB of guest memory stays free. Contention starves the loop, not
  memory. Before Task 7, cap the OCR fan-out (`OMP_NUM_THREADS` plus
  onnxruntime intra/inter-op threads at 2-4) so indexing cannot take half the
  box, and **budget seeding in hours, not minutes**, treating the API as
  offline throughout.
  **Root cause located (W80):** `server/api/index.py:1784` calls
  `extract_text_for_path(...)` directly inside `async def
  _flush_pending_cross_file_chunks` (`:1657`), and
  `server/indexing/text_extractors.py:93` runs `.convert()` synchronously — so
  OCR executes on the event loop. `server/indexing/embedder.py` already uses
  `await asyncio.to_thread(...)` in five places for exactly this reason.
  Minimal fix is `content = await asyncio.to_thread(extract_text_for_path, ...)`,
  plus the thread cap so one document cannot claim half the LXC. `c2a8e83b`
  did not address this — its "harden ingestion" is the libgl1/cv2 preflight.
- **W75 (measured 2026-08-28, sharpens W59) — alert on the volume as well as
  the pool; the volume is the nearer wall.** Two hours in and with **no corpora
  yet**, `vm-100-disk-0` is already at **15.64% of 300 GB (~44 GB)** and
  `pve/data` at **6.92%**; the guest has **242 GB free** while the pool has
  ~739 GB. So Ragweld hits its own 300 GB ceiling long before it can exhaust
  the pool. Alert at both levels because they fail differently: guest `df /` at
  75% warn / 90% page (Ragweld-only, fixed by `pct resize 100 rootfs +100G`
  against ample thin headroom), and `pve/data` Data%/Meta% at 70% / 85%
  (node-wide, takes HAOS read-only with it, `thin_pool_autoextend_*` still
  unset with only 16 GiB of VG to extend into). Before Task 7, set the
  autoextend keys and both alerts; immediately after the first corpus indexes,
  re-measure `vm-100-disk-0` so the seeding budget is a measurement rather than
  an estimate.
  Follow-up at 18:36Z after the 2,000-file corpus completed and the Apollo PDF
  was mid-index: guest `/` was 14% used with 242 GB free,
  `vm-100-disk-0` Data% was 15.67%, and `pve/data` was 6.94% Data / 0.46%
  Meta. The first corpus moved the pool by only 0.02 percentage points; the
  guardrails remain required, but capacity is not a seeding blocker.
  **Independent-review correction (W81):** the original 10% autoextend is
  impossible on this host: 10% of the 794.30 GiB pool is about 79.4 GiB, while
  the VG has only 16.00 GiB free. Use the repo-owned per-LV
  `deploy/proxmox/ragweld-thinpool.profile` at threshold 80% / extension 1%
  (about 7.9 GiB), attach it only to `pve/data`, and treat every extension as
  an immediate capacity action rather than a rescue plan. Install the
  host-level five-minute capacity timer so alerts do not depend on LXC 100 or
  its observability stack. It must email the configured `root@pam` address and
  journal deduplicated warning/critical/recovery transitions for guest `/` at
  75%/90%, pool Data%/Meta% at 70%/85%, and measurement-probe failure.

  Install and verify on pve1:

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
  ```

  Roll back by disabling the timer, running `lvchange --detachprofile
  pve/data`, removing the four installed artifacts and state directory, then
  running `systemctl daemon-reload`.
  ~~Original text below.~~
- **W59 (original) — watch the thin pool, not the RAM.** pve1's `local-lvm` is a 794 GiB
  thin pool at 1.58% used (~819 GiB available), holding both
  `vm-100-disk-0` (300 GiB thin, Ragweld) and HAOS's 32 GiB. Sizing is not a
  problem and the 300 GiB can be grown later with `pct resize`. The risk is
  pool exhaustion: if `pve/data` hits 100% **every thin volume goes read-only,
  HAOS included**, and on this node `thin_pool_autoextend_*` is unset with only
  16 GiB of unallocated VG to extend into — no automatic rescue. Before corpus
  seeding (Task 7): add a `pve/data` `Data%`/`Meta%` alert at 70% warn / 85%
  page (Prometheus+Alertmanager are already in the stack; a root cron running
  `lvs --noheadings -o data_percent,metadata_percent pve/data` is the fallback),
  The original global `80/10` autoextend prescription is superseded by W81;
  use the scoped `80/1` profile above and record the shared ceiling in the
  evidence so seeding is sized against a known budget.
- **W17 — Cloudflare limits.** Note the 100 MB request-body and ~100 s idle
  response limits in the evidence file; corpus seeding stays rsync.
- **Live firewall correction — the Proxmox cluster firewall is disabled.** A
  syntactically valid `/etc/pve/firewall/100.fw` is installed as dormant
  defense-in-depth, but it is not the active boundary and this rollout must not
  enable the cluster firewall globally just for one guest. LXC 100 instead
  owns an `nftables` guard at filter priority `-200`: established/related and
  loopback traffic remain allowed; DHCP from `192.168.68.1`, LAN ICMP, LAN
  TCP/22, and required ICMPv6 neighbor/router discovery are allowed; new
  `eth0` input and forward traffic is dropped. This priority runs before
  Docker's filter chains, so published containers cannot bypass it. Acceptance
  uses temporary real listeners on 58000 and 58012: each must return `200`
  inside the guest, time out from the Mac, and then be removed. Re-run the same
  live-listener proof after Docker starts.
- **Live DRM ownership correction — mode alone is insufficient.** `dev0` and
  `dev1` without explicit GIDs appeared as `root:root` mode `0660`, so the
  planned `render`/`video` memberships granted nothing. Resolve the guest's
  actual group IDs, set `dev0 ... gid=<guest-render-gid>` and
  `dev1 ... gid=<guest-video-gid>`, reboot the LXC, and prove the `ragweld`
  user can read and write both devices. On this guest the verified IDs are
  render `992` and video `44`.
- **Live Flyte nested-k3s correction — use a container-scoped log sink.** The
  bundled Flyte sandbox reached a healthy k3s control plane but kubelet exited
  with `open /dev/kmsg: no such file or directory`. Do **not** pass pve1's real
  kernel-message device into the privileged LXC. Map `/dev/null:/dev/kmsg` only
  on the already-privileged Flyte container. The pinned image has been proven
  live with that mapping: its nested k3s node reached `Ready` while pve1's
  `/dev/kmsg` remained outside the LXC boundary.
- **Live SSH correction — restart the socket-activated service.** Debian 13's
  `ssh.socket` owns port 22. A SIGHUP `systemctl reload ssh` passed `sshd -t`
  but then sshd failed to re-bind the systemd-owned socket. Use
  `systemctl restart ssh`, re-run `sshd -t`, inspect the effective key-only
  values, and prove a second direct SSH session before firewall activation.
- **Deployment lock timing.** Evidence commits made after the first baseline
  advance `origin/main`. Refresh `/root/ragweld-deployment-commit` once after
  the Task 2 checkpoint and immediately before cloning; then clone and compare
  as the `ragweld` owner. Do not add a root global `safe.directory` exception
  for the service-owned repository.

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
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct set 100 --dev0 path=/dev/dri/renderD128,mode=0660,gid=992 --dev1 path=/dev/dri/card0,mode=0660,gid=44; pct config 100'
```

Expected: both exact device entries present; no `/dev/kmsg`, Plex/media bind mount, or Proxmox socket mount. The pinned Debian 13 template uses guest GIDs render `992` and video `44`; verify them before first application start and stop if the image differs.

- [ ] **Step 5: Start and validate LXC resources**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pct start 100; pct exec 100 -- nproc; pct exec 100 -- free -h; pct exec 100 -- df -h /; pct exec 100 -- ls -l /dev/dri; pct exec 100 -- stat -c "%n uid=%u gid=%g mode=%a" /dev/dri/renderD128 /dev/dri/card0; pct exec 100 -- ip -4 addr show dev eth0'
```

Expected: 16 CPUs, roughly 24 GiB cap, 300 GiB thin root, both DRM devices with the expected guest group ownership, and a LAN IP. Record the IP and reserve it in the router/DHCP system if the current homelab already uses reservations; do not invent a static address inside Debian.

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
apt-get install -y ca-certificates curl git gnupg jq libgl1 libglib2.0-0t64 lsof openssl rsync sudo uidmap fuse-overlayfs python3 python3-venv build-essential pciutils vainfo
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
docker inspect ragweld-flyte-1 --format '{{json .HostConfig.Devices}}'
docker exec ragweld-flyte-1 test -c /dev/kmsg
docker exec ragweld-flyte-1 kubectl get nodes
```

Expected: every required service running/healthy, including Flyte and the full Langfuse dependency group; no vLLM container; total memory remains below the LXC cap with headroom. Flyte's only device mapping is `/dev/null` to `/dev/kmsg`, that path is a character device inside the container, and the nested k3s node reports `Ready`.

- [ ] **Step 3: Verify API liveness and readiness**

```bash
curl -fsS http://127.0.0.1:58012/api/health
curl -fsS http://127.0.0.1:58012/api/ready
```

Expected: HTTP 200; Postgres, Neo4j, LiteLLM, and index manifests ready; vLLM `ok=true` with `info.status="disabled by configuration"` and `info.required=false`.

- [ ] **Step 4: Verify every companion UI through Caddy using Host headers**

Unauthenticated requests to `me`, `grafana`, `langfuse`, `mlflow`, and `flyte` hostnames through `127.0.0.1:58000` must redirect to Authelia. `auth.ragweld.com` must return the Authelia portal. Direct public ports must not exist in `ss -lntp`; only loopback listeners are permitted for origin UIs.

- [ ] **Step 5: Send one paid gateway smoke request**

Use LiteLLM at `127.0.0.1:54000/v1`, model `openai.gpt-5.6-terra`, prompt `Reply with OK only.`, `temperature=0`, `max_tokens=8`, retry zero, and no fallback. Record response ID, resolved model, token usage, and cost only. Do not record the key or headers.

```bash
set -a
. /etc/ragweld/runtime.env
set +a
curl -fsS --retry 0 http://127.0.0.1:54000/v1/chat/completions \
  -H "Authorization: Bearer ${LITELLM_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"model":"openai.gpt-5.6-terra","messages":[{"role":"user","content":"Reply with OK only."}],"temperature":0,"max_tokens":8}' \
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

- [x] **Step 1: Materialize 2,000 public Epstein email rows**

Run inside `/opt/ragweld` as the `ragweld` user:

```bash
uv run python -c 'from pathlib import Path; from server.synthetic.hf_epstein_emails import materialize_epstein_email_dataset; materialize_epstein_email_dataset(output_dir=Path("/srv/ragweld/corpora/epstein-files-public"), eval_output_path=Path("/srv/ragweld/corpora-metadata/epstein-files-public-eval.json"), manifest_output_path=Path("/srv/ragweld/corpora-metadata/epstein-files-public-manifest.json"), batch_size=100, limit=2000, max_eval_rows=200, replace=True)'
```

Expected: exactly 2,000 text files, one out-of-corpus manifest, and 200 or fewer evidence-graded eval rows. Record dataset ID `to-be/epstein-emails`, config `default`, split `train`, timestamp, and manifest SHA-256.

- [x] **Step 2: Download one public-domain multimodal PDF**

```bash
install -d -o ragweld -g ragweld -m 0755 /srv/ragweld/corpora/nasa-apollo-11 /srv/ragweld/corpora-metadata
sudo -u ragweld curl -fL --retry 2 --output /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf https://ntrs.nasa.gov/api/citations/19700008096/downloads/19700008096.pdf
file /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf
head -c 8 /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf
sha256sum /srv/ragweld/corpora/nasa-apollo-11/A11_MissionReport.pdf
```

Record NASA NTRS document ID `19700008096`, distribution `Public`, and copyright `Work of the US Gov. Public Use Permitted` in the provenance metadata.
Reject an HTML response even when curl returns `200`; the file must identify as
PDF and begin `%PDF-` before registration.

- [x] **Step 3: Register both corpora through the real API**

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

- [x] **Step 4: Estimate before indexing**

POST `/api/index/estimate` for each corpus. Record file/chunk/token/cost estimates. Stop if the system proposes unexpected per-chunk cloud enrichment spend; keep local Hugging Face embeddings and use OpenRouter only for the bounded semantic/enrichment calls explicitly shown by the estimate.

```bash
curl -fsS -X POST http://127.0.0.1:58012/api/index/estimate -H 'Content-Type: application/json' -d '{"corpus_id":"epstein-files-public","repo_path":"/srv/ragweld/corpora/epstein-files-public","force_reindex":false}' | jq
curl -fsS -X POST http://127.0.0.1:58012/api/index/estimate -H 'Content-Type: application/json' -d '{"corpus_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11","force_reindex":false}' | jq
```

- [x] **Step 5: Index the text corpus, then the PDF corpus**

POST `/api/index` with `force_reindex=false`, monitor the real stream/status endpoint until terminal completion, and require new Postgres/Qdrant/Neo4j generations. Do not start both indexes concurrently.

```bash
curl -fsS -X POST http://127.0.0.1:58012/api/index -H 'Content-Type: application/json' -d '{"corpus_id":"epstein-files-public","repo_path":"/srv/ragweld/corpora/epstein-files-public","force_reindex":false}' | jq
watch -n 5 'curl -fsS http://127.0.0.1:58012/api/index/epstein-files-public/status | jq'
curl -fsS -X POST http://127.0.0.1:58012/api/index -H 'Content-Type: application/json' -d '{"corpus_id":"nasa-apollo-11","repo_path":"/srv/ragweld/corpora/nasa-apollo-11","force_reindex":false}' | jq
watch -n 5 'curl -fsS http://127.0.0.1:58012/api/index/nasa-apollo-11/status | jq'
```

Exit each `watch` only after `status` is `complete`, `error`, or `cancelled`.
Treat `error` and `cancelled` as blockers and inspect the persisted run events.

- [x] **Step 6: Ask real evidence questions**

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
- Produces: verified initial backup, recorded existing PBS policy, safe logical-backup commands, isolated restore proof, and final source/runtime hashes.

- [ ] **Step 1: Create and verify the first LXC backup**

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'vzdump 100 --storage pbs-beelink --mode snapshot --compress zstd; pvesm list pbs-beelink --content backup --vmid 100 | tail -n 3'
```

Expected: `TASK OK` and a new LXC 100 backup identifier.

- [ ] **Step 2: Record the existing enabled PBS policy**

Read the current cluster backup policy and record the existing enabled job that
already covers VMID 100:

```bash
ssh -i /Users/davidmontgomery/.ssh/proxmox_portable_backup_ed25519 -o IdentitiesOnly=yes -o BatchMode=yes root@192.168.68.171 'pvesh get /cluster/backup --output-format json'
```

Expected: the existing enabled `backup-pbs-cluster` job includes VMID 100,
uses snapshot + zstd, and targets `pbs-beelink`. Do **not** create a duplicate
`ragweld-daily` job.

- [ ] **Step 3: Create logical backup commands without exporting secrets**

Create a root-owned mode-`0700` staging directory first, never write directly
to the final timestamp directory, and promote only after every command and
health check succeeds:

```bash
BACKUP_DATE="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_PARENT="/srv/ragweld/backups"
STAGE_ROOT="$BACKUP_PARENT/.incomplete-$BACKUP_DATE"
FINAL_ROOT="$BACKUP_PARENT/$BACKUP_DATE"
QDRANT_API="http://127.0.0.1:56333"
QDRANT_CONTAINER="$(docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml ps -q qdrant)"
install -d -m 0700 "$BACKUP_PARENT" "$STAGE_ROOT"
install -d -m 0700 "$STAGE_ROOT"/{postgres,neo4j,qdrant,mlflow,langfuse}
set -a
. /etc/ragweld/runtime.env
. /etc/ragweld/langfuse.env
set +a
declare -a QDRANT_SNAPSHOTS=()
restore_services() {
  docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml start neo4j mlflow langfuse-clickhouse langfuse-minio langfuse langfuse-worker >/dev/null
}
cleanup_snapshots() {
  for ENTRY in "${QDRANT_SNAPSHOTS[@]}"; do
    IFS=: read -r COLLECTION SNAPSHOT_NAME <<<"$ENTRY"
    curl -fsS -X DELETE "$QDRANT_API/collections/$COLLECTION/snapshots/$SNAPSHOT_NAME" >/dev/null || true
  done
}
trap 'status=$?; if (( status != 0 )); then restore_services; cleanup_snapshots; rm -rf "$STAGE_ROOT"; fi; exit "$status"' EXIT

docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$STAGE_ROOT/postgres/ragweld.dump"
docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml exec -T langfuse-postgres pg_dump -U langfuse -d langfuse -Fc > "$STAGE_ROOT/langfuse/langfuse-postgres.dump"

for COLLECTION in $(curl -fsS "$QDRANT_API/collections" | jq -r '.result.collections[].name'); do
  SNAPSHOT_NAME="$(curl -fsS -X POST "$QDRANT_API/collections/$COLLECTION/snapshots" | jq -r '.result.name')"
  test -n "$SNAPSHOT_NAME"
  QDRANT_SNAPSHOTS+=("$COLLECTION:$SNAPSHOT_NAME")
  install -d -m 0700 "$STAGE_ROOT/qdrant/$COLLECTION"
  docker cp "$QDRANT_CONTAINER:/qdrant/snapshots/$COLLECTION/$SNAPSHOT_NAME" "$STAGE_ROOT/qdrant/$COLLECTION/$SNAPSHOT_NAME"
  test -s "$STAGE_ROOT/qdrant/$COLLECTION/$SNAPSHOT_NAME"
done

docker compose --project-name ragweld -f /opt/ragweld/docker-compose.yml -f /opt/ragweld/infra/docker-compose.observability.yml stop neo4j mlflow langfuse-clickhouse langfuse-minio langfuse langfuse-worker
docker run --rm -v ragweld_neo4j_data:/data:ro -v "$STAGE_ROOT/neo4j:/backup" neo4j:5.26.20-community neo4j-admin database dump neo4j --to-path=/backup --overwrite-destination=true
docker run --rm -v ragweld_mlflow_data:/source:ro -v "$STAGE_ROOT/mlflow:/backup" alpine:3.22 tar -C /source -czf /backup/mlflow-data.tgz .
docker run --rm -v ragweld_langfuse_clickhouse_data:/source:ro -v "$STAGE_ROOT/langfuse:/backup" alpine:3.22 tar -C /source -czf /backup/langfuse-clickhouse.tgz .
docker run --rm -v ragweld_langfuse_minio_data:/source:ro -v "$STAGE_ROOT/langfuse:/backup" alpine:3.22 tar -C /source -czf /backup/langfuse-minio.tgz .
restore_services

cleanup_snapshots
QDRANT_SNAPSHOTS=()
curl -fsS http://127.0.0.1:58012/api/ready >/dev/null
curl -fsS http://127.0.0.1:55500/health >/dev/null
curl -fsS http://127.0.0.1:53000/api/public/health >/dev/null
chmod -R go-rwx "$STAGE_ROOT"
(
  cd "$STAGE_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum
) > "$STAGE_ROOT/SHA256SUMS"
mv "$STAGE_ROOT" "$FINAL_ROOT"
trap - EXIT
```

Add no backup payload to Git. Only after one clean manual run of that exact
block succeeds should you save it as `/usr/local/sbin/ragweld-logical-backup`
with `#!/usr/bin/env bash` plus `set -euo pipefail`, make it mode `0700`, and
install:

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
remains deferred until measured backup growth establishes a safe retention
window; PBS still enforces seven daily and four weekly whole-LXC restore
points.

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
