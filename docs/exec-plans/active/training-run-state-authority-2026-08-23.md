# Training run-state authority and artifact cutover — follow-up slice (2026-08-23)

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
