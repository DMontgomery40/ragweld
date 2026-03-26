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

- Bootstrap: passed via `output/automation/bootstrap/latest.json` on 2026-03-26, serving the current-worktree UI at `http://127.0.0.1:5173/web` and API at `http://127.0.0.1:8016/api`.
- Acceptance: failed via `output/automation/acceptance/latest.json` with summary at `tmp/synthetic_acceptance_2026-03-26_0640/summary.json`.
- First failing checkpoint: Generator model selection in Synthetic Lab.
- Root cause: the UI-proof harness now fails closed on GPT-5-only synthetic selection, and the current `origin/main` Synthetic Lab exposes only `ragweld:mlx-community/Qwen3-1.7B-4bit` for `epstein-files-1`, so the real browser flow cannot select a compliant generator/judge model before a run starts.
- Next smallest honest fix: restore the live Synthetic Lab policy path so the UI/API surface `synthetic_data_kit` plus runnable GPT-5 model options instead of the fallback Ragweld local model.

## Latest Run (2026-03-26 MDT)

- Branch: `codex/ui-proof-20260326-epstein-eval-seed`
- Bootstrap command: `./scripts/automation_bootstrap.sh`
- Acceptance command: `./scripts/acceptance_epstein.sh`
- Result: `failed`
- First failing checkpoint: `Generator Model`
- Failure evidence: `No selectable GPT-5 option found for Generator Model. Available values: Select a model, ragweld:mlx-community/Qwen3-1.7B-4bit`
- Bootstrap artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/bootstrap/latest.json`
- Acceptance artifact: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/output/automation/acceptance/latest.json`
- Acceptance summary: `/Users/davidmontgomery/.codex/exec-worktrees/ragweld-ui-proof-loop/tmp/synthetic_acceptance_2026-03-26_0640/summary.json`

## Next Smallest Honest Fix Target

Cut Synthetic Lab back over to its live `synthetic_data_kit` + GPT-5 policy surface. The lane now boots a truthful current-worktree UI/API pair and the browser reaches the real Synthetic Lab, so the next blocker is the stale model/provider surface rather than stack startup or acceptance harness plumbing.

## Lane Notes

- Added `scripts/automation_bootstrap.sh` with artifact output at `output/automation/bootstrap/latest.json`.
- `scripts/automation_bootstrap.sh` now starts/reuses the current worktree backend + frontend, falls back off a foreign `5173` listener, and creates `epstein-files-1` from `/Users/davidmontgomery/epstein-files/documents` when the corpus row is missing.
- `scripts/acceptance_epstein.sh` now consumes the resolved UI/API bases from `output/automation/bootstrap/latest.json` before launching Playwright.
- `web/tmp_synthetic_acceptance.mjs` now stops at the first failed synthetic run instead of drifting into a later eval timeout.
- Added `scripts/automation_stop_gate.py` and `scripts/ci_local_full.sh` to restore the lane's required local gate commands.
- `scripts/automation_bootstrap.sh` now falls back off a foreign `8012` listener, restarts stale current-worktree Vite listeners whose proxy still points at the wrong backend, and records the honest `4173/8014` stack in the bootstrap artifact.
- `scripts/acceptance_epstein.sh` now fails closed when bootstrap did not resolve a current-worktree stack instead of silently probing default foreign listeners.
- `web/vite.config.ts` now respects `VITE_API_PROXY_TARGET`, so browser actions in the UI hit the same backend base that bootstrap resolved instead of hardcoding `8012`.
- `scripts/automation_bootstrap.sh` now searches past the default backend/UI candidate ports when foreign listeners occupy `8012-8015` or the configured UI slots, so the current worktree can still claim a truthful stack instead of failing closed at launcher setup.
- `scripts/acceptance_epstein.sh` now invokes the real `node` binary directly instead of hanging behind an `npm exec -- node` install prompt.
- `web/tmp_synthetic_acceptance.mjs` now fails closed unless Synthetic Lab exposes a GPT-5 model option, which keeps the lane honest when the UI regresses back to fallback local models.
