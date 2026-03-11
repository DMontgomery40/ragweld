# Autopilot Status: Stability

## Mission

Keep ragweld booting, serving, and rendering while reducing obvious regression risk.

## This Lane Owns

- startup failures
- lifecycle leaks
- race conditions
- backend/frontend contract mismatches
- narrow correctness fixes outside eval/data replacement work

## This Lane Does Not Own

- broad eval/data redesign
- graph-only acceptance work unless needed to unblock basic product function

## Gate

- `./scripts/ci_local_fast.sh` (currently missing on `origin/main`; used equivalent repo checks this run)
- `./scripts/ci_local_full.sh` (currently missing on `origin/main`; used equivalent repo checks this run)

## Automation Infra

- Host `crontab` is the authoritative scheduler for `ragweld-stability-loop`, `ragweld-ui-proof-loop`, and `ragweld-eval-data-loop`.
- The matching desktop automation entries remain `PAUSED` on purpose; that disables the desktop scheduler, not the host cron lanes.
- Install or repair the worker-lane cron block with `python3 /Users/davidmontgomery/ragweld/scripts/install_codex_exec_crons.py --apply`.

## Current Priority

Keep this file updated with the top 3 highest-confidence defects and the latest landed fix.

## Top 3 Defects (2026-03-10)

1. Acceptance journey preflight still fails when local UI/API are not started (`ERR_CONNECTION_REFUSED` on `/web/rag`).
2. Startup health polling still duplicates under React StrictMode, though one init path was removed in this run.
3. Monitoring deep-link startup still fans out to broad API calls instead of active-subtab-scoped behavior.

## Latest Landed Fix

- Removed redundant startup health check from `useAppInit`, leaving health polling ownership in `App`.
- Runtime evidence (real Playwright capture against local Vite runtime): startup `/api/health` requests dropped from `6` to `4`.
- Verification on this branch: `uv run scripts/check_banned.py`, `uv run scripts/validate_types.py`, `uv run pytest -q`, `npm --prefix web run lint`, `npm --prefix web run build`.
