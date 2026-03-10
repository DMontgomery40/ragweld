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

- Branch: `codex/ui-proof-20260310-epstein-bootstrap`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `synthetic_run_completed`
- Failure evidence: `Unable to resolve model route for 'gpt-4o-mini-2024-07-18' ... neither OpenAI nor OpenRouter is configured`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/tmp/synthetic_acceptance_2026-03-10_1108/summary.json`

## Next Smallest Honest Fix Target

Provide at least one reachable generation model for the real Synthetic Lab flow. The lane now auto-starts this worktree's UI/backend and auto-seeds `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents`, so the next blocker is genuine provider availability rather than corpus or routing setup.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- `scripts/automation_bootstrap.sh` now starts/reuses the current worktree backend + frontend, falls back off a foreign `5173` listener, and creates `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents` when the corpus row is missing.
- `scripts/acceptance_epstein.sh` now consumes the resolved UI/API bases from `output/automation/bootstrap/latest.json` before launching Playwright.
- `web/tmp_synthetic_acceptance.mjs` now stops at the first failed synthetic run instead of drifting into a later eval timeout.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
