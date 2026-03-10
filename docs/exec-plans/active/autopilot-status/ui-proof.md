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

## Latest Run (2026-03-10 MDT)

- Branch: `codex/ui-proof-20260310`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `open_synthetic_lab_start`
- Failure evidence: `page.waitForSelector('[data-testid="synthetic-lab-subtab"]')` timeout from `web/tmp_synthetic_acceptance.mjs:213`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/worktrees/6de9/ragweld/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/worktrees/6de9/ragweld/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/worktrees/6de9/ragweld/tmp/synthetic_acceptance_2026-03-10_0930/summary.json`

## Next Smallest Honest Fix Target

Ensure port `5173` serves this worktree's Ragweld UI, not another worktree's Vite process that currently returns `404` for both `/web/rag?...` and `/rag?...`; then rerun acceptance to expose the first product-level defect.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- Hardened `scripts/acceptance_epstein.sh` to emit `output/automation/acceptance/latest.json` on every run and auto-probe `/web` vs root UI base before launching Playwright.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
