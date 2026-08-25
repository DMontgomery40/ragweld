# Handoff — Session 12 (2026-08-24 → 25)

Status: session complete. Read `AGENTS.md` → `CLAUDE.md` → project memory →
`ragweld-recovery-foundation-2026-08-19.md` before acting; this handoff and
`phase-b-chrome-findings-2026-08-24.md` (defects 7–13) are required context.

## 1. Scope / status

Three slices landed this session, all committed locally:

1. **Defect 7** — Eval Analysis unscrollable (Promptfoo panel: 200 expanded
   cards inside the fixed header under an `overflow:hidden` root). Header now
   scrolls with content; results collapse; sample-size dropdown (default 25)
   closes the one-click-full-dataset cost trap; promptfoo POST timeout fixed.
2. **A5** — residual dead-code removal (spec prose YAMLs + tautological parse
   test, `GET /api/loki/query_range`, ~200 lines of caller-less frontend
   symbols, dead synthetic model gate, runtime Google Fonts → self-hosted
   Inter) + the **final acceptance matrix**
   (`final-acceptance-matrix-2026-08-24.md`), closing recovery item 5.
3. **Defects 8–13** (operator-reported "done surfaces that weren't"):
   miswired ML-quality Grafana dashboard → seven real label-less metrics +
   rewired panels; silent lineage-alias buttons → global toasts + visible
   alias state; 290-key flat "OTHER" config list → two-tier prefix
   classifier with honest "cannot affect results" scoping; AI-analysis 30s
   client timeout → bounded 660s; System Prompts + Promptfoo collapse;
   langchain-openai process-wide cached async client × ragas per-call event
   loops → explicit per-call judge clients.

Nothing is half-landed. Every slice has its no-interception Playwright
coverage and a codex adversarial review acted on (defect-7 slice: 2 P1/6 P2;
defects 8–13 slice: 2 P1/5 P2/3 P3 — outcomes recorded in the findings doc).

## 2. Working tree / branch

- `main` ahead of `origin/main` by exactly this session's 4 commits
  (`3d3022c` eval-analysis fix, `f0cf39a` A5 removal, `bdca0c9` acceptance
  matrix, `20bfd54` defects 8–13). **Operator pushes; never push
  unprompted.**
- Uncommitted, deliberately: `AGENTS.md` + `CLAUDE.md` GitNexus tooling
  blocks and untracked `.claude/skills/` — the operator keeps these local.
  To commit a real edit to `AGENTS.md` without them:
  `git show HEAD:AGENTS.md` → apply edit → `git hash-object -w` →
  `git update-index --cacheinfo 100644,<hash>,AGENTS.md`.

## 3. Running processes (no tmux)

- **Backend**: host uvicorn on 127.0.0.1:58012 — started manually this
  session (not by start.sh), pid file `.ragweld-runtime/backend.pid`, log
  `.ragweld-runtime/backend.log`. Its env replicates start.sh (sourced
  `.env`, provider keys unset, `LITELLM_BASE_URL`/`LITELLM_API_KEY`,
  nvm node v22.22.0 first on PATH). **Next boot: prefer `./start.sh` so the
  canonical launcher owns it again.**
- **Frontend**: Vite on 127.0.0.1:55173 (`/web/` base).
- **Local model**: host `vllm-metal` serving Qwen3.8-27B-4bit on 58080
  (`.ragweld-runtime/local-model.pid`) — do not restart/load models without
  the operator present (hard rule, two prior machine crashes).
- **Compose (`ragweld` project)**: postgres, neo4j, qdrant, litellm, flyte,
  mlflow, grafana/loki/tempo/alloy/prometheus/mimir/pyroscope/alertmanager,
  langfuse (v4 + clickhouse/redis/minio/postgres) — all up/healthy.

## 4. Verification state (final tree)

Ran and green: `check_docs_ownership`, `check_banned`, `validate_types`,
`generate_litellm_config --check` (404 aliases), `check_config_reality`
(451 keys), contract-bundle export+validate, `npm --prefix web run lint` +
`build`, `uv run pytest -q` → **1140 passed / 78 skipped** (one test fewer:
the deleted tautological spec-parse test), exhaustive-config Playwright
`eval_analysis_layout` → **4/4** repeatedly. Live proofs: eval run
`epstein-files-1__20260825_013817` end-to-end from the stream route (top1
0.6, topk 0.8, faithfulness 0.717, relevancy 0.752,
`tribrid_eval_runs_total` exactly 1.0), promptfoo 9/10 (gauge 0.9), three
benchmark runs, dashboard tiles all real, AI analysis generated via
`ragweld-local`.

Not run (unchanged surfaces / known exclusions): the exhaustive suite's
full mutation loop (needs its modernization slice), the strict integration
lane, and `playwright.config.ts --project web` (structurally a no-op: its
testMatch catches nothing under `.tests/` and its mkdocs webServer needs a
built `site/`).

## 5. Next steps (ordered)

1. **Exhaustive-suite modernization slice** (defect-6 residual): rebuild
   `coverage.spec.ts`'s mutation loop with real domain questions, bounded
   runtime, and an isolated corpus instead of the live registry.
2. **Registry-pollution root cause**: Playwright runs have twice leaked
   `ragweld-exhaustive` into the live corpus registry; tonight also found
   stale lineage-alias dirs (`data/lineage/aliases/ragweld-exhaustive/`,
   `e2e-*`, `pytest_lineage_*` under `data/synthetic_runs/`). Find the
   seam that lets test runs write live stores and close it.
3. **B8 training drive** — operator-present session only: run-start/cancel
   in Learning Agent Studio (host MLX rule).
4. **A5 deferred product decisions** (detailed in
   `final-acceptance-matrix-2026-08-24.md` residuals): four UI surfaces
   calling endpoints that never existed (MCPSubtab controls, both
   MonitoringSubtabs, QuickActions reranker options with a silent constant
   fallback) — build the six missing backends or remove the features; two
   consumer-less synthetic routes (cancel / artifact preview) — wire into
   UI or delete; `card_source`/`semantic_cards` rename (Postgres migration
   + contract break); docs-autopilot generator emits `grid chunk_summaries`
   where Material needs literal `grid cards` (88 spots render unstyled) —
   fix generator inputs, and Actions is billing-locked (catch-up dispatch
   documented in project memory).
5. **GitNexus MCP reader** still storage v40 vs index v42 — the CLI and
   PreToolUse hook work; the MCP server binary needs upgrading.

## 6. Needs tightening (smaller, none blocking)

- Ragas judge `max_retries=0`: one refused connection fails a whole eval
  run; judge calls also failed once under concurrent gateway load. Consider
  1–2 retries.
- Dashboard: `or vector(0)` renders 0 when the scrape pipeline itself is
  dead (documented in the panel text, still a masking risk); the retired
  corpus-labeled gauge series shows as a twin stat until it leaves the 1h
  window; the `$corpus_id`/`$run_id` template textboxes are wired to
  nothing (label-less metrics) — remove or wire them.
- Benchmark tab's model list is a very long unsearchable scroll (400+
  rows); wants a filter box.
- Carried cosmetic nits from the B-drives: Docker logs modal opens at page
  top; Dashboard quick-action log appends "# Error: Connection lost" after
  server-side run errors; normalized fusion weights render as 17-digit
  floats; `/web/evaluation` unknown route renders an empty "Home" shell;
  TriBrid Overview search-latency stat shows NaN in traffic-free windows;
  Chat Export blob download still unverified under automation (Brave drops
  script downloads — check manually).
- Config drift observed live: `ENRICH_DISABLED` flipped false→true between
  eval runs `214736` and `013817` — likely a leftover from an earlier test
  or drive; confirm it is intentional or flip it back.

## 7. Risks / gotchas

- **Never navigate the tab or edit frontend files (Vite HMR) while an eval
  SSE streams** — the disconnect hardening abandons the run; two paid runs
  were lost to this.
- Manual backend relaunches must replicate start.sh's env (see §3) or
  promptfoo (node <22.22) and the Ragas judge fail closed.
- Prometheus counters reset on API restart; Mimir's `increase()` bridges
  resets, but "Latest …" gauges read 0 until the next run in the new
  process.
- Chrome-extension clicks at the operator's 0.9 zoom are flaky at computed
  coordinates; `find`+ref clicks, `form_input` for selects, and
  `btn.focus()` + real Enter are the reliable patterns. A misclick DID
  silently mutate live lineage state once (now visible/undoable thanks to
  defect-9's fix, but drive carefully).
- One click of "Run Promptfoo regression" at default settings now runs 25
  entries (~3 min, ~50 LLM calls); "All entries" remains an explicit,
  labeled choice (~30 min, several hundred calls).
