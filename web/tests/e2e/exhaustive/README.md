# Exhaustive UI Suite (Playwright)

This suite is a single canonical, long-running "touch everything" UI validator,
plus a few focused regression specs that share its harness.

What `coverage.spec.ts` does:
- Provisions its own corpus (`ragweld-exhaustive-<stamp>`) over the deterministic
  acceptance fixture (`tests/fixtures/acceptance_corpus`, the Aurora Tidal
  Observatory), scoped to deterministic embeddings, no enrichment/semantic KG, no
  reranker, the cheap paid probe alias, and its OWN query log + triplets file under
  `data/logs/exhaustive/<id>/` (the reranker log API only serves paths under `data/logs/`) (never the operator's shared
  `data/logs/queries.jsonl` / `data/training/triplets.jsonl`); indexes it for real;
  deletes it (and that directory) at the end — a failed delete is retried and reported,
  never marked done.
- Walks every top-level tab and declared subtab with that corpus active.
- Enumerates visible controls (`button`, `input`, `select`, `textarea`, switches, comboboxes).
- Mutates controls with deterministic actions (never keys/secrets/webhooks, and never
  whole-word host/port/url/path/endpoint/dsn fields — those rewire the live backend).
  Every click is checked against the API responses it triggered: a 4xx/5xx during the
  action is a failed action, not an "ok" click.
- Enforces post-change cycle: `Apply All Changes -> refresh -> double-check`. Controls that
  never make Apply dirty and leave the corpus config untouched are UI-local session state
  (theme, chat sources, model picker) and are recorded as `skip:ui-local`; a mutation that
  saved but did not survive the refresh — or saved nothing — is a persistence failure.
- Runs cross-surface propagation scans for matching control ids/names.
- For retrieval-impacting controls, asks real corpus questions in Chat and grades the
  answer against the probe's evidence groups (every group must be present): thumbs-up
  only for a grounded answer (the feedback is reranker triplet-mining signal), and an
  ungrounded answer after a retrieval mutation is a recorded failure.
- Verifies provider coverage targets: OpenAI, OpenRouter, Cohere (fails fast when missing).
- Uses a medium metrics budget by default (checks core metrics every 3 retrieval mutations).
- Three modes: `preflight` (inventory only), `smoke` (bounded by `EXHAUSTIVE_BUDGET_MS`,
  unreached surfaces reported as `skip:budget`, still fails on failed actions) and `full`
  (must complete every surface within the budget or the run FAILS). There is no
  cross-run resume: each run provisions a fresh corpus, so a previous run's "ok"
  fingerprints say nothing about it.
- Proves isolation: the unscoped `/api/config` is compared section by section before and
  after the run; any drift is a recorded failure. It is NOT restored automatically — a
  concurrent operator edit must never be overwritten by a stale test snapshot — the
  drifted sections are named so the operator can decide.
- Records per-action outcomes to `output/playwright/exhaustive/outcomes.ndjson`, writes
  `summary.json` (with run metadata: corpus, budget, elapsed, surfaces completed), and
  FAILS the test when any action failed (and, in `full` mode, when the budget ran out).

## Run

Prerequisites:
- Full stack running (frontend + backend + required infra), started from the repo root.
- The paid gateway alias used for probes (`EXHAUSTIVE_CHAT_MODEL`, default
  `openai.gpt-5.6-luna`) must be advertised by `/api/chat/models`.
- Run from the repo root: the corpus fixture path resolves from `process.cwd()`.

Preflight once (cheap inventory + readiness checks; provisions but does not index):

```bash
cd /Users/davidmontgomery/ragweld
EXHAUSTIVE_MODE=preflight \
npm --prefix web exec -- playwright test \
  --config /Users/davidmontgomery/ragweld/playwright.exhaustive.config.ts \
  --grep "exhaustive ui mutation" \
  --workers 1 \
  --project web-exhaustive \
  --reporter=list
```

Then a bounded smoke pass (proves the loop; not a coverage claim):

```bash
EXHAUSTIVE_MODE=smoke EXHAUSTIVE_BUDGET_MS=600000 \
npm --prefix web exec -- playwright test \
  --config /Users/davidmontgomery/ragweld/playwright.exhaustive.config.ts \
  --grep "exhaustive ui mutation"
```

And the full pass (every surface must complete within the budget):

```bash
EXHAUSTIVE_MODE=full EXHAUSTIVE_BUDGET_MS=7200000 \
npm --prefix web exec -- playwright test \
  --config /Users/davidmontgomery/ragweld/playwright.exhaustive.config.ts \
  --grep "exhaustive ui mutation"
```

The other specs in this directory (`chat_reliability`, `eval_analysis_layout`,
`learning_reranker_visualizer`, `native_dialog_replacement`, `lineage_alias_meta`, …)
run with the same config and no `--grep`.

## Important Env Knobs

- `EXHAUSTIVE_BUDGET_MS` (default: 30 min) — wall-clock budget for the mutation loop
- `EXHAUSTIVE_SUITE_TIMEOUT_MS` (default: budget + 15 min) — Playwright test timeout for the loop
- `EXHAUSTIVE_TEST_TIMEOUT_MS` (default: 10 m) — per-test timeout for the other specs
- `EXHAUSTIVE_API_BASE_URL` (default: `http://127.0.0.1:58012/api`)
- `EXHAUSTIVE_OUTPUT_DIR` (default: `output/playwright/exhaustive`)
- `EXHAUSTIVE_MODE=preflight|smoke|full` (default: `full`)
- `EXHAUSTIVE_CHAT_MODEL` (default: `openai.gpt-5.6-luna`) — gateway alias for every probe
- `EXHAUSTIVE_CORPUS_PREFIX` (default: `ragweld-exhaustive`) — prefix of the per-run corpus id
- `EXHAUSTIVE_PROVIDER_MODELS` — `provider=alias,...` overrides for the provider-coverage probes
- `EXHAUSTIVE_INDEX_TIMEOUT_MS` (default: 5 min) — wait for the provisioning index run
- `EXHAUSTIVE_PROBES_PER_MUTATION` (default: 1; max 10) — chat probes per retrieval mutation
- `EXHAUSTIVE_SELECT_ALL_OPTIONS=1` only for deep runs; default is one safe option change per select
- `EXHAUSTIVE_PROPAGATION_SCAN=0` to disable cross-surface mirror checks
- `EXHAUSTIVE_DESTRUCTIVE=1` to allow destructive actions that are blocked by default
- `EXHAUSTIVE_METRICS_BUDGET=low|medium|high` (default: `medium`)

## Policy Defaults

- Never touches secret/key/webhook/password fields, whole-word host/port/url/path fields, or search/query boxes (filling them with a generated string is a placeholder query; retrieval is probed through Chat with real questions).
- Never drives the host-served local model for probes; test traffic uses the paid alias.
- Destructive actions are blocked by default (run separately with `EXHAUSTIVE_DESTRUCTIVE=1`),
  and so are host-side training / model lifecycle, process or container lifecycle, and
  paid multi-minute runs: by label (start/launch/run/execute/train/…) AND by surface —
  every button on the Training Studios, Indexing, Graph, Eval Analysis, Benchmark,
  Docker, MCP, Services and System Status surfaces is skipped whatever it says
  (`skip:blocked-action`), so a bare "Start Run" can never reach the host.
- Real corpus questions only (`.claude/rules/testing.md`); feedback is graded against evidence.
