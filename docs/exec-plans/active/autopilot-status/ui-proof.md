# Autopilot Status: UI Proof

## Mission

Continuously prove the real user journey for `epstein-files-1` from the actual browser UI.

## This Lane Owns

- full UI reindex flow
- graph visualization truthfulness
- graph-heavy chat proof
- feedback persistence proof
- eval compare and drilldown proof
- prepared corpus derivation when needed to make the graph honest

## Gate

- `./scripts/acceptance_epstein.sh`
- `./scripts/ci_local_full.sh` when app code changed

## Current Priority

Keep this file updated with the latest acceptance result, the first failing checkpoint, and the next smallest honest fix.

## Latest Result

- Bootstrap: passed via `output/automation/bootstrap/latest.json` on 2026-03-10, serving UI at `http://127.0.0.1:4173/web` and API at `http://127.0.0.1:8012/api`.
- Acceptance: failed via `output/automation/acceptance/latest.json` with summary at `tmp/synthetic_acceptance_2026-03-10_1845/summary.json`.
- First failing checkpoint: `indexing_completed`.
- Root cause: the lane now triggers a real UI reindex before Synthetic Lab, MLX embedding failure falls back to the local `all-MiniLM-L6-v2` path, and transient index-status poll resets no longer stop the flow. The next blocker is practical completion: `epstein-files-1` is large enough that the full UI reindex was still only 2.97% complete after 88 seconds, so the run was cancelled once that honest prerequisite was clear.
- Next smallest honest fix: make the full `epstein-files-1` UI reindex finish reliably enough for acceptance, either by restoring a faster stable dense embedding path or by introducing a truthful prepared corpus derivative that keeps the graph/chat/eval flow representative.

## Latest Run (2026-03-10 MDT)

- Branch: `codex/ui-proof-20260310-epstein-reindex-truth`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `indexing_completed`
- Failure evidence: `Indexing failed before synthetic run: cancelled`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/tmp/synthetic_acceptance_2026-03-10_1845/summary.json`

## Next Smallest Honest Fix Target

Get the full UI-triggered `epstein-files-1` reindex to complete in practical time without dropping backend truth. Synthetic Lab is no longer the first stop: the lane now reaches the indexing tab, starts a real force reindex from the browser, and stays attached long enough to prove that index duration is the next prerequisite.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- `scripts/automation_bootstrap.sh` now starts/reuses the current worktree backend + frontend, falls back off a foreign `5173` listener, and creates `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents` when the corpus row is missing.
- `scripts/acceptance_epstein.sh` now consumes the resolved UI/API bases from `output/automation/bootstrap/latest.json` before launching Playwright.
- `web/tmp_synthetic_acceptance.mjs` now opens the Indexing tab first, enables force reindex from the UI, ignores stale pre-run index status, and retries transient index-status poll resets before failing the lane.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
- `server/indexing/embedder.py` now falls back from unavailable MLX embeddings to the already-configured local sentence-transformer backend, which gets the real `epstein-files-1` reindex moving instead of failing on the first batch.
