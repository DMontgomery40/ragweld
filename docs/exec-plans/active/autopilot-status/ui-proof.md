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

## Latest Run (2026-03-09 MDT)

- Branch: `codex/ui-proof-epstein-first-failure-20260310`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `open_synthetic_lab_start`
- Failure evidence: `page.goto: net::ERR_CONNECTION_REFUSED` at `http://127.0.0.1:5173/web/rag?subtab=synthetic&corpus=epstein-files-1`
- Acceptance summary: `/Users/davidmontgomery/.codex/worktrees/6514/ragweld/tmp/synthetic_acceptance_2026-03-10_0524/summary.json`

## Next Smallest Honest Fix Target

Bring up the real local stack (`web` on `127.0.0.1:5173`, `api` on `127.0.0.1:8012`) before rerunning acceptance so checkpoint 1 can proceed and expose the first product defect.

## Lane Notes

- `scripts/acceptance_epstein.sh` was missing on this branch and has now been added as a thin wrapper over the existing real UI runner (`web/tmp_synthetic_acceptance.mjs`).
- `./scripts/ci_local_full.sh` is still missing on this branch and blocks the full local gate.
