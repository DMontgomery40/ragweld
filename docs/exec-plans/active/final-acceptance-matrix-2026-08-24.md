# Final Acceptance Matrix — OSS-Composition Modernization

Date: 2026-08-24 (session 12)

Status: living document; closes the "full final acceptance matrix" half of
recovery item 5. Each row names the locked-stack target or protected surface,
its acceptance state, and where the proof lives. "Proven" means real services,
real queries, and a rendered browser or real pytest/Playwright evidence — no
mocks, no interception.

## Locked stack

| Target | State | Evidence |
|---|---|---|
| vLLM (local inference) | PROVEN | Host `vllm-metal` serves Qwen3.8-27B-4bit, 32k ctx, ~12 tok/s; compose vLLM deleted; `start.sh` local-model process (`local-model-vllm-metal-2026-08-22.md`) |
| LiteLLM (gateway/routing) | PROVEN | model_list generated from `data/models.json` (403 OpenRouter routes + ragweld-local, lockstep-checked); grounded chat E2E with real cost ($0.000322/1203 tok) and provider ids (`phase-b-chrome-findings-2026-08-24.md` B4) |
| Flyte (orchestration) | PROVEN (control plane) / OPERATOR-GATED (run drive) | `workflow=flyte` creates a real execution; launch/execute-callback/status/cancel through flyteadmin (`handoff-2026-08-21-session4.md`); B8 run-start/cancel UI drive deferred until the operator is present (MLX host rule) |
| Haystack + Docling + Qdrant (retrieval/indexing) | PROVEN | Promotion cutover: Postgres chunk rows + Qdrant dense/sparse generations; pilot + pgvector/FTS deleted (`retrieval-promotion-cutover-2026-08-21.md`); B1/B3 force-reindex through the mismatch guard, promoted generation points=4 (findings doc) |
| Neo4j (graph parity) | PROVEN | Graph leg live in retrieval; B5 outage drill returns the structured `dependency_unavailable` card, recovery to ready |
| Unsloth (training execution) | FAILS CLOSED (honest blocker) | Requires CUDA; host is Apple Silicon. Exact blocker surfaced in Training Center readiness; no cloud GPU spend without authorization |
| MLflow (runs) | PROVEN | Compose service, runs/metrics/artifacts, cancel → KILLED (`eval-substrates.md`) |
| Ragas (evals) | PROVEN | Single shared Ragas path for both eval routes (defect 5); UI-run eval persisted faithfulness 0.8 / answer_relevancy 0.656 rendered in the Ragas card |
| Promptfoo (regressions) | PROVEN | Real CLI 0.122.0 over the gateway; full-dataset 175/200 with honest failing verdicts (B9); sample-size control (default 25) proven with a real 10-entry UI run (defect 7) |
| Langfuse (eval drilldown substrate) | PROVEN | v4 live with real ingestion (events_only + v2 observations API, ClickHouse 25.12 pin) (`a3-observability-fabric-2026-08-24.md`) |
| OTel + Alloy + Tempo + Loki + Mimir + Pyroscope + Faro (+ Alertmanager) | PROVEN | All Compose services with functional readiness and wired data paths (A3); trace link opens Grafana Explore rendering the full chat_stream span waterfall (defect 4). OpenCost stays `disabled` honestly (needs a Kubernetes API server) |
| assistant-ui chat shell | PROVEN | Chat tab on assistant-ui with ragweld SSE adapter; grounded cited answers, structured failure cards, recall intensity, history/delete (B4/B5) |

## Protected operator surfaces (fork UI rule)

| Surface | State | Evidence |
|---|---|---|
| Training Center / Learning Agent Studio | PARTIAL (operator-gated) | Truthful control-plane state, live Flyte/MLflow links, run history HUD, revived Neural Visualizer (defect 1); run-start/cancel drive awaits an operator-present session (B8) |
| Eval drilldown (Eval Analysis) | PROVEN | B9 + defect 5 + defect 7: real runs, Ragas card, Promptfoo panel with sample control, scrollable layout pinned by `eval_analysis_layout.spec.ts` |
| Retrieval/indexing controls | PROVEN | B2 auto-save/persistence; B1/B3 force-reindex; contract-lock banner honesty |
| Graph parity surfaces | PROVEN | B5 failure drill; graph leg pills and citations in chat |
| Grafana embeds / Command Center | PROVEN | B10: seven provisioned dashboard families, live series under real load |
| Dock/workbench shell | PROVEN | B11 responsive pass; B12 console/network hygiene (zero app errors) |
| Infrastructure services/Docker | PROVEN | B7: real stop/logs/start of Qdrant from the UI |
| Chat | PROVEN | B4/B5; Export blob download unverifiable under automation — re-check manually (Brave drops script downloads without user activation) |

## Known residuals (tracked, not blocking acceptance)

1. B8 run-start/cancel drive — requires the operator at the machine (MLX rule,
   two prior crashes).
2. ~~Exhaustive-suite modernization~~ — done 2026-08-25 (session 13): isolated
   indexed corpus per run, evidence-graded Aurora questions, wall-clock budget,
   global-config isolation proof, blocked host-side actions, fails on failed
   actions (`session13-pr-loop-and-registry-pollution-2026-08-25.md` §4).
3. ~~Pytest/Playwright corpus-registry pollution root cause~~ — found and closed
   2026-08-25 (session 13): corpus deletion now removes corpus-scoped lineage,
   the synthetic run store has an isolation seam pytest uses, and the exhaustive
   suite provisions/deletes its own corpus (same record, §3). Pre-existing orphan
   directories are listed for operator removal.
4. Dead-endpoint UI surfaces needing a product decision (A5 sweep, 2026-08-24):
   `MCPSubtab` start/stop/restart/test controls, both `MonitoringSubtab`s
   (alert thresholds / alertmanager status), and `QuickActions` reranker
   options (silently falls back to constants) — all call endpoints that have
   never existed. Build the backends or remove the features; do not half-delete.
5. Two consumer-less synthetic backend routes kept deliberately
   (`POST /api/synthetic/run/{id}/cancel`, `GET …/artifact/preview`) — real
   orchestrator capability with no UI consumer after the dead-wrapper removal.
   Wire them into the UI or delete them in the next synthetic slice.
6. `card_source` field + `publish/semantic_cards` route segment — banned-term
   remnants that survive the `\b` regexes; renaming is a Postgres migration +
   contract-bundle break. Deliberately out of scope for dead-code removal.
7. docs-autopilot generator emits `grid chunk_summaries` (88 occurrences) where
   Material for MkDocs needs the literal `grid cards` class — card grids render
   unstyled. Fix belongs in the generator inputs, and Actions is billing-locked
   (catch-up dispatch documented in memory).
8. GitNexus MCP reader at storage v40 vs index v42 — the CLI works; the MCP
   server needs the upgraded build.
9. Unsloth execution and OpenCost — blocked on CUDA host / Kubernetes
   respectively; both fail closed with exact operator messages.
