# Fable Closeout Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`. Do not create branches, worktrees, or subagents; this repository is locked to one `main` worktree on the Mac and LXC100.

**Goal:** Review, repair, deploy, and visibly accept the Ragweld changes between `60b23717` and `9efd4a0c` by 2026-08-31 12:00 America/Denver without losing source, runtime state, or operator evidence.

**Architecture:** Review the critical 411-file range as five ownership-aligned tranches. Each tranche starts from root-cause evidence and a fresh GitNexus map, uses Fable at high effort only for verified defects, receives an independent `deepseek-v4-flash` adversarial review, runs on LXC100, and is accepted through the authenticated browser with visible clicks.

**Tech Stack:** Git/GitNexus, Claude Code Fable 5, LiteLLM/OpenRouter DeepSeek V4 Flash, Python/FastAPI/Pydantic, React/Vite/assistant-ui, Postgres/Qdrant/Neo4j, Proxmox pve1/LXC100, Caddy/Authelia/Cloudflare Tunnel, Grafana/Langfuse/MLflow/Flyte.

**Spec:** `docs/exec-plans/active/handoff-2026-08-28-pve1-fresh-agent.md`

## Global Constraints

- Mac is source editing only; run every test, build, model, database, indexing, and acceptance workload in `/opt/ragweld` on LXC100.
- Keep exactly one local branch and worktree on the Mac and LXC100.
- Before editing an existing symbol, run GitNexus upstream impact and warn on HIGH/CRITICAL risk.
- Use TDD for every fix and expand coverage to the bug family; no mocks, request interception, skip stubs, or placeholder questions.
- Do not hand-edit `mkdocs/**`; fix docs-autopilot inputs.
- Fable invocation contract: `claude -p --model fable --effort high`, one bounded tranche at a time, no worktrees or subagents.
- DeepSeek review contract: production LiteLLM model `deepseek.deepseek-v4-flash`, full tranche diff and evidence, temperature 0, resolve P1/P2 and re-review.
- Browser proof is a visible operator drive: screenshots first, then real clicks, dropdowns, typing, scrolling, graph zoom/node selection, and companion-UI navigation. DOM/API-only proof is insufficient.

---

### Task 1: Freeze Baseline and Failure Matrix

**Files:**
- Modify: `docs/exec-plans/active/fable-closeout-2026-08-31.md`

**Interfaces:**
- Consumes: Mac and LXC100 `main` at `9efd4a0c`; preserved Tranche 0 package.
- Produces: exact test failures with command, environment, traceback, blame, and tranche owner.

- [ ] Record GitNexus `detect-changes --scope compare --base-ref 60b23717` risk and process count.
- [ ] On LXC100, run the standard validators and save exact exit codes/counts in the ledger.
- [ ] Run the complete backend suite once with current production services available; group failures by root cause and rerun each ambiguous failure in isolation.
- [ ] Run frontend lint/build and the existing exhaustive Playwright suite only after confirming no active index run and sufficient box headroom.
- [ ] Record live deployment hash/marker, service readiness, corpus inventory, index activity, container inventory, capacity guard, and backup timer state without printing secrets.

### Task 2: Tranche A — Deployment, Config, Auth, MCP, and Secret Boundaries

**Files:**
- Review: `deploy/proxmox/**`, `start.sh`, `server/config.py`, `server/config_control_plane.py`, `server/config_redaction.py`, `server/services/config_store.py`, `server/mcp/**`, `server/api/config.py`, `server/main.py`
- Tests: `tests/unit/test_proxmox_deployment_contract.py`, `tests/unit/test_runtime_lifecycle.py`, `tests/api/test_config_redaction.py`, `tests/api/test_mcp_api_key_guard.py`, `web/tests/e2e/exhaustive/routing_shell.spec.ts`

**Interfaces:**
- Consumes: production config and ingress topology.
- Produces: restart-safe config rendering, zero credential exposure, authenticated MCP, and exact deployment marker parity.

- [ ] Reproduce configuration, redaction, MCP, Caddy/Authelia, and restart paths on the deployed commit.
- [ ] Invoke Fable only for confirmed Tranche A regressions.
- [ ] Run focused tests, deployment contract, generated-type validation, and frontend build on LXC100.
- [ ] Submit exact diff/evidence to DeepSeek V4 Flash; fix verified P1/P2 and re-review.
- [ ] Browser-drive Admin Basic/Raw, Infrastructure MCP, login/session persistence, and public MCP link with visible controls.

### Task 3: Tranche B — Indexing, Persistence, Corpus Cleanup, and Figures

**Files:**
- Review: `server/api/index.py`, `server/indexing/**`, `server/db/postgres.py`, `server/retrieval/qdrant_store.py`, `server/indexing/provenance.py`, `tests/corpus_reaper.py`, `server/project_paths.py`
- Tests: `tests/api/test_index_*`, `tests/unit/test_figure_*`, `tests/unit/test_index_*`, `tests/integration/test_index_*`, `tests/integration/test_corpus_reaper.py`, `web/tests/e2e/exhaustive/figure_workflow.spec.ts`

**Interfaces:**
- Consumes: promoted Postgres/Qdrant/Neo4j generations and existing Apollo/code corpora.
- Produces: non-destructive indexing, honest estimates, atomic figure chunks, bounded reaping, and preserved provenance.

- [ ] Reproduce estimate cold/warm states, cancellation, promotion, deletion, reaper prefixes/age guard, figure extraction, and index-run adoption.
- [ ] Invoke Fable only for confirmed Tranche B regressions.
- [ ] Require regression plus category coverage and run focused/integration suites on LXC100.
- [ ] Submit exact diff/evidence to DeepSeek V4 Flash; fix verified P1/P2 and re-review.
- [ ] Browser-drive corpus selection, Index Now estimate/confirmation, index history, Figures controls, citation badge, PDF page/region viewer, and no-restart-during-index invariant.

### Task 4: Tranche C — Graph, Chat, Recall, and Source Viewer

**Files:**
- Review: `server/api/graph.py`, `server/db/neo4j.py`, `server/api/chat.py`, `server/chat/**`, `server/chat/recall_indexer.py`, `server/api/documents.py`, `web/src/components/RAG/GraphSubtab.tsx`, `web/src/components/Chat/**`, `web/src/components/Documents/**`
- Tests: `tests/unit/test_graph_*`, `tests/api/test_graph_*`, `tests/integration/test_graph_*`, `tests/unit/test_recall_indexer.py`, `tests/integration/test_recall_document_viewer_live.py`, `web/tests/e2e/exhaustive/graph_explorer.spec.ts`, `web/tests/e2e/exhaustive/chat_*.spec.ts`, `web/tests/e2e/exhaustive/source_viewer.spec.ts`

**Interfaces:**
- Consumes: corpus-scoped graph/search/chat contracts.
- Produces: slash-safe graph entities, preserved search results on expansion failure, corpus-bound conversations, honest source counts, and accessible source documents.

- [ ] Reproduce graph route ordering, multi-hop center duplication, export, chat send/stop/history, source popovers, recall scope, and error-before-done handling.
- [ ] Invoke Fable only for confirmed Tranche C regressions.
- [ ] Run focused/live tests on LXC100 with real corpus questions.
- [ ] Submit exact diff/evidence to DeepSeek V4 Flash; fix verified P1/P2 and re-review.
- [ ] Browser-drive Chat and Graph using visible selection, send/stop, dropdowns, history, citation click, graph node click, zoom, details, table/export, and hard-reload comparison.

### Task 5: Tranche D — Observability, Eval, Benchmark, and Studios

**Files:**
- Review: `server/observability/**`, `server/api/observability.py`, `server/api/eval.py`, `server/api/benchmark.py`, `server/api/synthetic.py`, `server/api/lineage.py`, `web/src/components/Observability/**`, `web/src/components/Evaluation/**`, `web/src/components/Benchmark/**`, `web/src/components/RerankerTraining/**`
- Tests: `tests/api/test_observability_*`, `tests/unit/test_observability_*`, `tests/unit/test_eval_analysis_persistence.py`, `tests/api/test_synthetic_endpoints.py`, `web/tests/e2e/exhaustive/observability_deck.spec.ts`, `web/tests/e2e/exhaustive/eval_*.spec.ts`, `web/tests/e2e/exhaustive/synthetic_lab_gating.spec.ts`

**Interfaces:**
- Consumes: persisted run truth and canonical traces.
- Produces: truthful probe hysteresis, persisted ML-quality metrics, non-charging cached eval analysis, failed-run promotion refusal, and valid deep links.

- [ ] Reproduce restart persistence, one-miss hysteresis, Loki timeout accounting, Langfuse existence/member distinction, eval cache, and direct failed-run promotion attempts.
- [ ] Invoke Fable only for confirmed Tranche D regressions.
- [ ] Run focused/live tests on LXC100.
- [ ] Submit exact diff/evidence to DeepSeek V4 Flash; fix verified P1/P2 and re-review.
- [ ] Browser-drive Operator Deck, incidents, trace links, Eval drilldown/analysis, Benchmark filters/history, Synthetic Lab details, and promotion controls.

### Task 6: Tranche E — Frontend Config Commit Model, Dashboard, Legibility, and Routing

**Files:**
- Review: `web/src/App.tsx`, `web/src/stores/useConfigStore.ts`, `web/src/hooks/useApplyButton.ts`, `web/src/components/ui/NumberField.tsx`, `web/src/components/ui/confirmDialog.tsx`, `web/src/components/Dashboard/**`, `web/src/components/Dock/**`, `web/src/components/Navigation/**`, `web/src/hooks/useSubtab.ts`, `web/src/styles/**`
- Tests: `tests/unit/test_web_tokens_contrast.py`, `tests/unit/test_config_save_error_surface.py`, `web/tests/e2e/exhaustive/commit_model.spec.ts`, `web/tests/e2e/exhaustive/numberfield_migration.spec.ts`, `web/tests/e2e/exhaustive/dashboard_*.spec.ts`, `web/tests/e2e/exhaustive/legibility_*.spec.ts`, `web/tests/e2e/exhaustive/routing_shell.spec.ts`

**Interfaces:**
- Consumes: generated Pydantic constraints and route/subtab state.
- Produces: staged-until-Apply config, leaf-scoped 422 errors, guarded destructive actions, readable UI, and content that follows tab changes.

- [ ] Reproduce the known heavy-subtab stale-content bug, phantom dirty state, invalid numeric saves, confirmation queue wedging, dock clipping, and route correction behavior.
- [ ] Invoke Fable only for confirmed Tranche E regressions.
- [ ] Run focused tests, lint/build, and relevant Playwright suites on LXC100.
- [ ] Submit exact diff/evidence to DeepSeek V4 Flash; fix verified P1/P2 and re-review.
- [ ] Browser-drive every top-level tab/subtab with visible clicks, dropdown edits, Apply/Discard, confirmation dialogs, narrow viewport, full scrolling, and screenshots.

### Task 7: Merge Gate, Deploy, Re-drive, and Final Cleanup

**Files:**
- Modify: `docs/exec-plans/active/fable-closeout-2026-08-31.md`
- Modify normal docs only when product/runtime truth changed; never edit `mkdocs/**`.

**Interfaces:**
- Consumes: DeepSeek-clean tranches and green LXC verification.
- Produces: pushed/deployed exact hash, live visual acceptance, one-branch/one-worktree topology, and honest residual list.

- [ ] Run GitNexus `detect-changes` before each commit and the full compare before deployment.
- [ ] Run docs ownership, banned patterns, generated types, LiteLLM lockstep, runtime catalog, full pytest, frontend lint/build, and relevant real-browser suites on LXC100.
- [ ] Commit by explicit path to `main`, push non-force, fast-forward clean LXC100, render config, build frontend, write deployment marker, restart, and wait for readiness.
- [ ] Perform the complete authenticated curious-user drive with screenshots and visible interaction; re-drive every fixed path.
- [ ] Verify Mac, origin, LXC, and deployment marker match; one branch/worktree each; no active index; no Fable residue; preservation package checksums pass.
- [ ] Record all commands, model reviews, browser evidence, costs, and unresolved external-only blockers in the ledger.
