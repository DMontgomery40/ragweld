# Exhaustive UI Suite (Playwright)

This suite is a single canonical, long-running "touch everything" UI validator.

What it does:
- Walks every top-level tab and declared subtab.
- Enumerates visible controls (`button`, `input`, `select`, `textarea`, switches, comboboxes).
- Mutates controls with deterministic actions.
- Enforces post-change cycle: `Apply All Changes -> refresh -> double-check`.
- Runs cross-surface propagation scans for matching control ids/names.
- For retrieval-impacting controls, runs chat probe questions and sends feedback.
- Uses 3 real-world probes per retrieval-impacting mutation (default).
- Verifies provider coverage targets: OpenAI, OpenRouter, Cohere (fails fast when missing).
- Uses a medium metrics budget by default (checks core metrics every 3 retrieval mutations).
- Records per-action outcomes to `output/playwright/exhaustive/outcomes.ndjson`.
- Writes aggregate summary to `output/playwright/exhaustive/summary.json`.

## Run

Prerequisites:
- Full stack running (frontend + backend + required infra).
- At minimum one working local model and one working cloud model configured.

Preflight once (cheap inventory + readiness checks):

```bash
cd /Users/davidmontgomery/ragweld
npm --prefix web exec -- playwright test \
  --config /Users/davidmontgomery/ragweld/playwright.exhaustive.config.ts \
  --grep "exhaustive ui mutation" \
  --workers 1 \
  --project web-exhaustive \
  --reporter=list \
  --timeout=0 \
  --headed
```

with:

```bash
EXHAUSTIVE_MODE=preflight
```

Then run the full pass once:

```bash
EXHAUSTIVE_MODE=full EXHAUSTIVE_RESUME=1 \
npm --prefix web exec -- playwright test \
  --config /Users/davidmontgomery/ragweld/playwright.exhaustive.config.ts
```

## Important Env Knobs

- `EXHAUSTIVE_SUITE_TIMEOUT_MS` (default: 48h)
- `EXHAUSTIVE_TEST_TIMEOUT_MS` (default: 10m per test action timeout window)
- `EXHAUSTIVE_API_BASE_URL` (default: `http://127.0.0.1:58012/api`)
- `EXHAUSTIVE_OUTPUT_DIR` (default: `output/playwright/exhaustive`)
- `EXHAUSTIVE_MODE=preflight|full` (default: `full`)
- `EXHAUSTIVE_RESUME=1|0` (default: `1`; resumes from prior `outcomes.ndjson`)
- `EXHAUSTIVE_SELECT_ALL_OPTIONS=1` only for deep runs; default is one safe option change per select
- `EXHAUSTIVE_PROPAGATION_SCAN=0` to disable cross-surface mirror checks
- `EXHAUSTIVE_DESTRUCTIVE=1` to allow destructive actions that are blocked by default
- `EXHAUSTIVE_METRICS_BUDGET=low|medium|high` (default: `medium`)

## Policy Defaults

- Never touches secret/key/webhook/password fields.
- Destructive actions are blocked by default (run separately with `EXHAUSTIVE_DESTRUCTIVE=1`).
- Feedback defaults to thumbs-up unless the answer text contains obvious failure signals.
