# Ralph UI Exhaustive Iteration Contract

You are working in `/Users/davidmontgomery/ragweld`.

## Scope

Work only on the current PRD story. Do not do broad refactors.

## Mandatory Run

1. Run exhaustive Playwright suite:

```bash
npm --prefix web exec playwright test --config ../playwright.exhaustive.config.ts
```

2. Read:
- `output/playwright/exhaustive/outcomes.ndjson`
- `output/playwright/exhaustive/summary.json`

## Fix Policy

Apply fix only if all are true:
- root cause is obvious,
- patch is small/local,
- confidence is high,
- low regression risk.

For non-obvious failures:
- do not guess,
- write structured finding in `docs/exec-plans/active/exhaustive-ui-realness-suite.md` follow-up section (or a dedicated linked note),
- include reproduction surface/control/action + likely cause + next verification step.

## Required Validation After Any Code Change

```bash
python3 scripts/jev_lint.py
uv run scripts/check_contract_integrity.py
uv run scripts/validate_types.py
uv run pytest -q
npm --prefix web run lint
npm --prefix web run build
```

If any command cannot run, state exact blocker and stop.

## Completion

Mark the active story `passes=true` in `scripts/ralph-ui-exhaustive/prd.json` only when:
- targeted issue is resolved,
- validation passes,
- exhaustive suite no longer reports that story’s failure.

