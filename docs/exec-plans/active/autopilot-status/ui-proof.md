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

- The acceptance harness (`./scripts/acceptance_epstein.sh`) has not been re-run
  since 2026-03-26; the result recorded below is obsolete and must not drive work.
- Generator/judge selection no longer involves a `ragweld:` local model: every
  generation route is a LiteLLM alias (`litellm:ragweld-local` =
  `mlx-community/Qwen3.8-27B-4bit` on the host vllm-metal `local-model`
  process since 2026-08-23, plus the 403 OpenRouter routes). The retired
  `ragweld:mlx-community/Qwen3-1.7B-4bit` selection cannot recur.
- Current interactive proof (2026-08-23): Chrome drive of Chat on
  `epstein-files-1` through `ragweld-local` (Qwen3.8-27B on Metal, streamed
  grounded cited answer, 73 s), recorded in
  `docs/exec-plans/active/local-model-vllm-metal-2026-08-22.md`; earlier
  2026-08-22 drives in `handoff-2026-08-22-session5.md` §5.
- Next smallest honest fix: re-run the acceptance harness against the LiteLLM
  catalog and record the first failing checkpoint here.

## Last Recorded Run (2026-03-26 MDT, obsolete)

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

Superseded 2026-08-22: the Synthetic Lab's provider is `grounded_qa` (gateway
aliases for generator/judge, verbatim evidence checks); `synthetic_data_kit`
was never an installable dependency and is deleted. UI proof for the lane is
the Chrome drive recorded in `docs/exec-plans/active/eval-data-lane-2026-08-22.md`.

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
