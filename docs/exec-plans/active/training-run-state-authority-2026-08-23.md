# Training run-state authority and artifact cutover — follow-up slice (2026-08-23)

Status: LANDED 2026-08-23 (session 9). Execution record at the end of this file.

Opened from the eval-data lane's adversarial review (codex passes 17–19, record in
`eval-data-lane-2026-08-22.md`). The lane landed a per-run transition authority
(`server/api/agent.py::_transition_run`, the reranker's `_run_state_lock`) and a
locked, compensated promotion transaction (`server/training/promotion.py`). Two
findings are a redesign of pre-existing trainer architecture rather than a patch
and are deliberately NOT in that commit:

## 1. Run records must be read-only on load (`_maybe_reconcile_run`)

`server/api/agent.py::_load_run` (and the reranker's equivalent) reconcile
inconsistent persisted state while loading: a run can be set to
`completed`/`failed`/`cancelled` and saved from a supposedly read-only helper,
outside `_run_state_lock` / `_transition_run`, without `_finalize_stored_run`
(so without lineage attachment or MLflow termination).

Reviewer scenario: after an API restart, reading an idle persisted MLflow run
marks it cancelled locally while its MLflow record stays running; concurrent
threaded loads and reconciliation can save competing records outside the CAS.

Target: `_load_run` becomes side-effect-free; reconciliation is an explicit
async step (`reconcile_run(run_id)`) that transitions through the authority
and finalizes through `_finalize_stored_run`; endpoints that list/get runs
call it. Both trainers.

## 2. Artifact cutover must be reader-atomic and crash-recoverable

`PromotionSwap` renames the active directory away before renaming the staged
copy into place. Inference readers do not take the promotion lock, so they can
observe a missing active path for the rename window; a crash between the two
renames strands `.bak_*`/`.tmp_*` with no active directory; a crash after the
swap but before lineage/run completion leaves an unrecorded candidate active.
There is no startup recovery and no directory/tree fsync protocol.

Target: immutable versioned artifact directories
(`models/<name>/versions/<run_id>/`) published through one atomic pointer
switch (a symlink or a fsynced pointer file) that readers resolve; a durable
promotion marker with startup recovery (same phase design as
`server/training/triplet_rows.py`'s publish marker); readers share the
cutover protocol. Both trainers and both manual promote endpoints.

## Also in scope when this slice opens

- Multi-worker deployments: the run-state authority is an `asyncio.Lock`
  (training jobs are in-process, single-worker is the stated contract). If
  more than one API worker is ever supported, the authority must become a
  per-run interprocess lock or a transactional store.
- `_request_train_run_cancel` semantics for a run that is already terminal
  (currently `True`, "nothing to cancel"): decide whether the API should say
  so explicitly.

## Acceptance

- Real interleaving tests (not pre-written terminal records) for: reconcile
  vs completion, cancel vs promotion, execute handoff vs cancel, restart with
  a stranded promotion.
- A reader that resolves the active artifact during a promotion never sees a
  missing path.
- `codex exec` adversarial pass at high effort before done.

---

## Execution record (2026-08-23, session 9)

### 1. Read-only loads + explicit reconciliation (both trainers)

- `_load_run` in `server/api/agent.py` and `server/api/reranker.py` is
  read-only: no reconcile-on-load, no writes, ever.
- Reconciliation is the explicit `reconcile_run(run_id)` step: a pure
  `_reconcile_decision` (terminal metrics stream -> adopt its status and
  timestamp without duplicating events; >=2h-idle orphan -> cancelled with
  terminal events; the reranker's legacy-stub case kept), then a transition
  through the authority (`_transition_run`: per-run lock, re-read stored
  record, compare-and-set) finalized by `_finalize_stored_run` (lineage
  attached, MLflow terminated with FINISHED/KILLED/FAILED, start-guard
  popped). Endpoints that list/get/stream/cancel/promote runs call it; the
  reranker gained its own `_transition_run` + `_finalize_stored_run`, and its
  three job terminal handlers plus the orphan-cancel path now go through the
  authority instead of writing directly.
- `_active_run_id_for_corpus` (both trainers) reconciles candidates so an
  orphaned `running` record cannot block new starts forever.
- Cancel of an already-terminal run is an explicit no-op: `OkResponse` gained
  an optional `message` ("Run already ended with status=...; nothing to
  cancel."), types regenerated.

### 2. Reader-atomic, crash-recoverable artifact store

- New `server/training/artifact_store.py`: immutable versions under
  `<root>/versions/<run_id>/` (fsynced tree before visibility), a fsynced
  `ACTIVE.json` pointer switched atomically, `.promote.lock` flock,
  `.promote.json` durable marker (`switching`/`committed`), deterministic
  `recover_artifact_store` (rolls back an unrecorded candidate, finishes a
  died commit, sweeps staging debris, fails closed on an unreadable
  marker/pointer), retention of current + just-retired version.
- `PromotionSwap` is DELETED; `run_promotion_transaction` now takes a
  `VersionedArtifactSwap` (same begin/work/commit-or-rollback contract, alias
  compensation unchanged). The reranker manual promote writes its manifest via
  the swap's `prepare` callback on the staged copy (versions stay immutable),
  and now holds the run-state lock with a fresh in-work `_load_run` (the agent
  side already did).
- Readers resolve the pointer: reranker inference (`server/retrieval/rerank.py`),
  baseline evals, eval jobs, score/evaluate endpoints, `/api/reranker/info`
  `resolved_path`, and lineage's runtime-model-set snapshot
  (`server/lineage/registry.py`). MLX cache invalidation prefix-matches the
  store root so version-dir keys are dropped.
- Startup recovery runs in the API lifespan
  (`server/main.py::_recover_artifact_stores`) for both configured roots.
- Live dirs migrated one-time to the versioned layout (operator machine):
  `models/learning-agent-active -> versions/aurora_acceptance__20260822_190536`,
  `models/learning-reranker-active -> versions/epstein-files-1__20260823_023509`;
  both resolve through the pointer. No legacy flat-layout reader exists.

### 3. Also-in-scope items

- Multi-worker: the authority remains an `asyncio.Lock`; single-worker
  in-process training is the stated deployment contract (documented on the
  lock in both modules). The artifact store itself is interprocess-safe
  (flock + marker).
- `_request_train_run_cancel` on a terminal run: kept returning True at the
  helper layer; the API answer is now explicit via `OkResponse.message`.

### Acceptance evidence

- `tests/unit/test_artifact_store.py` (17): publish/resolve, rollback (incl.
  first promotion and vanished-previous), retention/prune, prepare callback,
  crash recovery per marker phase, unreadable marker fails closed,
  begin-recovers-first, and the reader-atomicity concurrency test (readers
  resolving + reading through back-to-back promotions never see a missing or
  mixed artifact inside the retention window) — the "restart with a stranded
  promotion" and "reader never sees a missing path" acceptance items.
- `tests/unit/test_run_state_authority.py` (8): `_load_run` purity, terminal
  stream adoption without duplicate events, orphan cancellation, real
  interleavings for reconcile-vs-completion and cancel-vs-completion (both
  trainers, lock actually held and released mid-test), orphan cancel through
  the authority, start-gate reconciliation.
- Execute-handoff-vs-cancel interleaving remains covered by
  `tests/unit/test_flyte_state_apply.py` + the strict-lane Flyte suites (the
  handoff critical section is unchanged; its CAS partner paths moved onto the
  same authority).
- Updated shared suites: promotion tests in `tests/unit/test_reranker_split.py`
  rebuilt on the versioned store (post-swap failure rollback, cross-process
  serialization, begin-failure, independent alias/artifact compensation,
  lineage-lock failure, cache prefix invalidation); endpoint no-op-cancel
  tests in `tests/api/test_reranker_train_endpoints.py` and
  `tests/api/test_agent_training_control_plane_endpoints.py`.

### Adversarial review (codex exec, high effort) — REFUTED: 4 P1, 5 P2, 1 P3; 8 acted on, 2 documented

Acted on:
- P1: recovery could roll back an already-recorded promotion (crash between the
  work step's durable run-record write and the committed marker) -> recovery
  takes a `promotion_recorded(run_id)` predicate; each trainer supplies its
  run-record truth (`_promotion_recorded`: `promoted_bundle_id` set) at every
  swap site and at startup. Recorded work finishes the commit
  (`finished_commit_of_recorded_promotion`); unrecorded work still rolls back.
- P1: rollback deleted a candidate a reader may have pinned while it was
  active -> rollback (and recovery's rollback) parks the candidate as an
  unreferenced version; the next successful commit prunes it. New test proves
  a pinned candidate stays readable through rollback until the next commit.
- P1: a pointer write whose directory fsync failed left ACTIVE naming a
  deleted directory with no marker -> begin's cleanup restores the previous
  pointer before discarding the candidate whenever the pointer write was
  attempted; if even that restore fails, the candidate and the marker are
  kept so the next recovery repairs the store (never a dangling pointer).
- P2: an unmigrated flat (pre-store) layout silently read as "no artifact" ->
  `resolve`/`begin` now fail closed with a migration hint when the root holds
  flat adapter files and no pointer (replacement-only: never read, never
  hidden).
- P2: reranker reconciliation attached lineage from today's corpus config (or
  none) -> it uses the run's own `config_snapshot`
  (`_cfg_from_run_snapshot`, mirroring the agent), including the orphan-cancel
  path.
- P2: two hidden flat-root fallbacks -> lineage's runtime-model-set snapshot
  records the store's pointer file (absent/corrupt recorded honestly, never
  the root tree as a fake artifact); `/api/reranker/info` returns an empty
  `resolved_path` when nothing is resolvable instead of the root.
- P2: both jobs saved a stale pre-baseline object as `running` outside the
  authority -> queued->running is a `_transition_run` CAS in both trainers; a
  run cancelled during setup now aborts instead of being resurrected.
- P3: learning-rerank manifest/adapter-config reads ran on the event loop ->
  pinned resolve + both metadata reads bundled into one worker call.
- The reader concurrency test was renamed to its honest bound (retention
  window), counts store mutations (begin/commit/rollback), and now races
  readers against rollbacks as well as commits.

Documented residuals (not regressions of this slice):
- Terminal finalization is durable-record-first: a crash between the terminal
  `_save_run` and the MLflow termination / terminal events leaves a terminal
  record whose MLflow run is still open or whose stream lacks `complete`;
  reconciliation only repairs `running` records, so that tail is not retried.
  Pre-existing ordering (the old reconcile-on-load had the same shape); a
  terminal-record repair lane is future work if it bites in practice.
- Startup recovery covers the global config's store roots; a corpus-scoped
  override of a model path is recovered at the start of every promotion
  against that root (begin-time recovery), not at process start. All stored
  corpus configs share the global roots today.
- Alias compensation for a promotion that crashes mid-work (aliases moved,
  run record not yet saved) remains best-effort: recovery restores the
  pointer, and the `current`/`promoted` aliases self-correct on the next
  successful promotion. The old swap had no crash recovery at all here.
