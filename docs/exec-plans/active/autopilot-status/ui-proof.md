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
- Acceptance: failed via `output/automation/acceptance/latest.json` with summary at `tmp/synthetic_acceptance_2026-03-10_1432/summary.json`.
- First failing checkpoint: `synthetic_run_completed`.
- Root cause: Synthetic Lab now uses `/api/chat/models`, so it only offers routable models and correctly starts with the `ragweld:` option; the next real blocker is that the synthetic run immediately fails its quality gate because no eval items are generated for `epstein-files-1`.
- Next smallest honest fix: inspect synthetic recipe output for `epstein-files-1` and the prepared corpus/index state to determine why eval dataset generation yields zero quality samples.

## Latest Run (2026-03-10 MDT)

- Branch: `codex/ui-proof-20260310-epstein-bootstrap`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `synthetic_run_completed`
- Failure evidence: `Quality gate evaluation failed: no eval items generated`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/tmp/synthetic_acceptance_2026-03-10_1432/summary.json`

## Next Smallest Honest Fix Target

Make Synthetic Lab generate real eval items for `epstein-files-1` after model selection succeeds. The lane now auto-starts this worktree's UI/backend, auto-seeds `epstein-files-1`, and selects only routable models, so the next blocker is truthful synthetic/data generation rather than stack setup or provider routing.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- `scripts/automation_bootstrap.sh` now starts/reuses the current worktree backend + frontend, falls back off a foreign `5173` listener, and creates `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents` when the corpus row is missing.
- `scripts/acceptance_epstein.sh` now consumes the resolved UI/API bases from `output/automation/bootstrap/latest.json` before launching Playwright.
- `web/tmp_synthetic_acceptance.mjs` now stops at the first failed synthetic run instead of drifting into a later eval timeout.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
