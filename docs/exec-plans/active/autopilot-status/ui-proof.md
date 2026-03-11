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

- Bootstrap: passed via `output/automation/bootstrap/latest.json` on 2026-03-11, serving the current-worktree UI at `http://127.0.0.1:4173/web` and API at `http://127.0.0.1:8014/api`.
- Acceptance: failed via `output/automation/acceptance/latest.json` with summary at `tmp/synthetic_acceptance_2026-03-11_1443/summary.json`.
- First failing checkpoint: `synthetic_run_completed`.
- Root cause: UI proof now reaches the real Synthetic Lab on the current worktree stack, but the synthetic run still fails immediately because it generates zero eval rows (`sources_used=0`) and the corpus-scoped seed fallback has no `data/eval_datasets/epstein-files-1.json` to hydrate from.
- Next smallest honest fix: restore/materialize `data/eval_datasets/epstein-files-1.json` for `epstein-files-1` and reconnect bootstrap to the prepared-slice seed path so empty synthetic generation falls back to real eval rows.

## Latest Run (2026-03-11 MDT)

- Branch: `codex/ui-proof-20260311-bootstrap-port-fallback`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `synthetic_run_completed`
- Failure evidence: `Quality gate evaluation failed: no eval items generated`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/tmp/synthetic_acceptance_2026-03-11_1443/summary.json`

## Next Smallest Honest Fix Target

Make Synthetic Lab generate real eval items for `epstein-files-1` after model selection succeeds. The lane now boots a truthful current-worktree UI/API pair and the browser starts a real synthetic run, so the next blocker is restoring the missing eval-seed/prepared-corpus input rather than stack setup or provider routing.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- `scripts/automation_bootstrap.sh` now starts/reuses the current worktree backend + frontend, falls back off a foreign `5173` listener, and creates `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents` when the corpus row is missing.
- `scripts/acceptance_epstein.sh` now consumes the resolved UI/API bases from `output/automation/bootstrap/latest.json` before launching Playwright.
- `web/tmp_synthetic_acceptance.mjs` now stops at the first failed synthetic run instead of drifting into a later eval timeout.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
- `scripts/automation_bootstrap.sh` now falls back off a foreign `8012` listener, restarts stale current-worktree Vite listeners whose proxy still points at the wrong backend, and records the honest `4173/8014` stack in the bootstrap artifact.
- `scripts/acceptance_epstein.sh` now fails closed when bootstrap did not resolve a current-worktree stack instead of silently probing default foreign listeners.
- `web/vite.config.ts` now respects `VITE_API_PROXY_TARGET`, so browser actions in the UI hit the same backend base that bootstrap resolved instead of hardcoding `8012`.
