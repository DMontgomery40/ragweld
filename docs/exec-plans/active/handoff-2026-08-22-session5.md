# Handoff Prompt — Ragweld Recovery, Session 5

> Checkpoint 2026-08-24 (session 11): **Phase B Chrome drives are DONE except
> the MLX-gated B8 run-start** (execution record:
> `phase-b-chrome-findings-2026-08-24.md`). Every flow was driven with the
> Claude-in-Chrome extension, real input, real domain queries. Six defects
> found and FIXED, each with a real no-interception test and a Chrome
> re-drive: (1) the Neural Visualizer blank/`connect(null)` — drei
> `<Environment preset>` fetched an HDR from raw.githack.com and suspended
> the R3F tree, whose 500ms-delayed root disposal then killed the remounted
> root (identical code in fiber 9.7.0; replaced with procedural
> RoomEnvironment via PMREMGenerator — covers both studios); (2) all nine
> native `window.confirm/alert` call sites (renderer-freezing) replaced by a
> shared promise-based `confirmDialog` + `showToast`; (3) nested `<button>`
> in the Index Stats header; (4) the dead `Tempo trace` link now opens
> Grafana Explore on the provisioned tempo datasource
> (GF_USERS_VIEWERS_CAN_EDIT=true added; proven rendering the full
> chat_stream span waterfall); (5) the SSE eval route silently skipped Ragas
> — shared `_resolve_ragas_answer_route`/`_generate_ragas_answer`/
> `_apply_ragas_scores` now used by BOTH routes, AST contract test pins the
> seam, and a UI-run 10-question eval persisted real Ragas (faithfulness
> 0.8, answer_relevancy 0.656, run `epstein-files-1__20260824_214736`);
> (6) the exhaustive coverage spec could never load the app (absolute
> `goto('/dashboard')` vs the `/web/` base — the documented trap) and
> carried pre-cutover model taxonomy; paths + preflight fixed, but the full
> mutation loop was deliberately NOT run (needs a modernization slice:
> real domain questions, isolated corpus — it leaked `ragweld-exhaustive`
> into the live registry again this session; cleaned). Also driven green:
> B1/B3 (aurora force reindex through the mismatch guard — its live index
> now carries the provider contract, 4 points), B2 (auto-save +
> persistence; weights auto-normalize), B4 (grounded chat with citations,
> per-leg provenance, all three trace links live incl. Langfuse, recall
> intensity, history/new/delete; Export blob download unverifiable under
> automation — Brave drops script downloads without user activation),
> B5 (structured `dependency_unavailable` card with Neo4j stopped; no fake
> answer), B6 (per-field scoped PATCH auto-save + Raw agreement), B7
> (qdrant stop/logs/start from the UI), B9 (dataset add/delete, sampled
> eval runs, full-dataset Promptfoo `...__20260824_214257` 175/200 with
> honest failing-card verdicts), B10 (dashboards render real series under
> load), B11 (1200px reflow clean), B12 (console clean everywhere).
> Incidentals: GitNexus CLI upgraded to 1.6.9 (nvm prefix; the MCP server
> needs a Claude Code restart to read the v42 index), Grafana anonymous
> viewers can use Explore, aurora's stale deterministic embedding contract
> replaced, promptfoo runs the full 200-row dataset from one click with no
> sample control (cost finding, logged). Nits logged in the findings doc.
> NOT pushed — the operator pushes. B8 run-start/cancel needs the operator
> present (MLX rule). Next: A5 residual dead-code removal + the final
> acceptance matrix, the exhaustive-suite modernization slice, and the
> pytest corpus-registry-pollution root cause.
>
> Checkpoint 2026-08-24 (session 10): **A3 is DONE** — the observability
> fabric is complete
> (`a3-observability-fabric-2026-08-24.md` is the execution record). Mimir
> (59009, Prometheus remote_write), Pyroscope (54040, host-API `pyroscope-io`
> agent with server-confirmed profile verification), Faro (Alloy receiver on
> 52347 + `@grafana/faro-web-sdk` in the workbench, events land in Loki as
> `service_name=ragweld-web`), Alertmanager (59093, rules in
> `infra/prometheus-rules.yml`, always-firing `RagweldWatchdog` proves
> delivery; receivers intentionally empty/operator-owned), and **Langfuse v4**
> (53000; worker + own Postgres/ClickHouse 25.12/Redis/MinIO; fresh-install
> `events_only` mode — read via `GET /api/public/v2/observations`). The
> previously-dead Langfuse ingestion is FIXED: `record_langfuse_generation`
> creates a real generation observation on the shared TracerProvider (same
> trace id as `X-Trace-ID`), with per-path observation names
> (chat/reranker/benchmark/eval/synthetic), Langfuse-shaped cost details, and
> a config-built deep link (no SDK network call on the request path).
> `start.sh` provisions per-machine Langfuse secrets into
> `infra/langfuse.env` + `.env` and probes Mimir/Pyroscope `/ready` after
> `up --wait` (distroless images, no container healthchecks). Component
> status is truthful: Langfuse `configured` requires buildable ingestion
> (keys+SDK) and shows live ingestion state; Pyroscope degrades on a failed
> host agent. OpenCost stays disabled (needs Kubernetes; Colima runs plain
> Docker). Adversarial codex pass REFUTED the first cut (2 P1 / 8 P2) — all
> ten acted on (see the slice doc). Colima stays at `--memory 16` (operator:
> the crashes were local-model RAM, not the VM; ~9.4 GiB free held). Gates on
> the final tree: six validators, full pytest 1138/78, strict lane 82, web
> lint/build, Faro Playwright E2E (beacon accepted + events land in Loki),
> live status all-green with real proof (Langfuse trace
> `61b0ef1f787034c02339de3d3230b0d1`: chat.generation $0.000896 gpt-5.6-luna
> + reranker.generation $0.00033 gpt-4.1-nano). Incidental fixes: 12
> pytest-leftover corpora deleted from the live registry (boot 404 noise);
> the positioning guardrail test now pins the operator's 2026-08-24 README
> repositioning (safe claims kept, DSV claims still banned). GitNexus
> detect_changes is BLOCKED by a reader/index version mismatch (storage 42 vs
> reader 40) — run a gitnexus upgrade/re-analyze. NOT pushed — the operator
> pushes. Next: Phase B Chrome drives
> (`frontend-browser-findings-2026-08-20.md` checklist; first defect already
> logged: Neural Visualizer `connect(null)`), then A5 residual dead-code +
> final acceptance matrix.
>
> Checkpoint 2026-08-23 (session 9, landed at `7daf62f`): the **run-state
> authority slice is DONE**
> (`training-run-state-authority-2026-08-23.md`, execution record + codex
> outcome inside). `_load_run` is read-only in BOTH trainers; reconciliation
> is the explicit `reconcile_run` through the per-run CAS authority; the
> reranker gained its own `_transition_run`/`_finalize_stored_run` and every
> terminal/orphan/start status write goes through the authority. The active
> adapters live in a **versioned artifact store**
> (`server/training/artifact_store.py`: `versions/<run_id>/` + atomic fsynced
> `ACTIVE.json` pointer + durable marker + startup/begin-time recovery that
> uses the trainer's run record to decide a stranded promotion; retention =
> current + just-retired + parked rollbacks until the next commit);
> `PromotionSwap` is deleted and all readers resolve the pointer. The live
> `models/learning-*-active` dirs were migrated one-time (gitignored); an
> unmigrated flat layout now fails closed. Adversarial codex pass REFUTED the
> first cut (4 P1 / 5 P2 / 1 P3): eight fixed (recovery-vs-recorded-work,
> reader-safe rollback parking, pointer-restore on failed begin, flat-layout
> fail-closed, snapshot-config lineage in reranker reconcile, two hidden
> root-fallbacks, stale queued->running writes, on-loop metadata reads), two
> documented as pre-existing residuals (terminal-finalize observability tail;
> startup recovery covers global roots, begin-time recovery covers corpus
> overrides). Gates at commit: six validators, pytest 1131/78, strict lane
> 82, web lint/build, live endpoint proof on a temp API on :58013 (no model
> loads). NOT pushed — the operator pushes. Next: A3 observability
> (Mimir/Pyroscope/Faro/Alertmanager/Langfuse), then Phase B Chrome drives.
>
> Checkpoint 2026-08-23 (session 8): **P0-3 is DONE** — local generation runs
> on the HOST via vllm-metal (`~/.venv-vllm-metal`) serving
> `mlx-community/Qwen3.8-27B-4bit` as `ragweld-local` on 127.0.0.1:58080
> (32k ctx, fraction 0.50, single stream, thinking disabled at the serving
> layer, ~12 tok/s). `./start.sh` owns the `local-model` process; the Compose
> `vllm` service is DELETED and LiteLLM/api/Prometheus reach the host through
> `host.docker.internal` — **older runtime notes below that name a Compose
> `vllm` service or `--no-deps litellm` workarounds are obsolete**; after a
> Colima bounce just run `./start.sh --with-observability` (add `--with-flyte`
> when needed). Colima stays at `--cpu 6 --memory 16`. Full record + measured
> parameters: `local-model-vllm-metal-2026-08-22.md`. Adversarial codex pass
> REFUTED the first cut (2 P1, 5 P2, 1 P3): the orphaned-EngineCore stop path,
> identity-blind readiness, docker-backend healthcheck race, port split-brain,
> and stale docs are fixed; the "APIServer survives engine death" P1 was
> empirically refuted (EngineCore kill → APIServer exits in ~3 s and the
> supervised stack tears down cleanly, observed live). Residual: the lifecycle
> lock still serializes `stop.sh` against a `start.sh` that is mid-startup
> (pre-existing; Ctrl-C on the launcher is the recourse). Gates at commit:
> full pytest 1101/78 skipped, strict lane 82 (with Flyte up), web lint/build,
> gateway Playwright 7/7, all validators; proofs: LiteLLM→host chat
> completion, grounded API chat (78 s, 10 sources), Chrome real-mouse drive
> (73 s, cited answer, zero console errors). Next: the run-state follow-up
> slice (`training-run-state-authority-2026-08-23.md`), then A3 observability,
> then Phase B Chrome drives.
>
> Checkpoint 2026-08-23 (session 7, landed at `04dff27`): the P1 slice below is
> committed locally (not pushed) after nineteen adversarial codex passes; the
> two remaining structural items are a planned follow-up slice,
> `training-run-state-authority-2026-08-23.md` (read-only `_load_run`,
> reader-atomic versioned artifact cutover). Next in order: P0-3 local model
> cutover with the operator present (`local-model-vllm-metal-2026-08-22.md`),
> the run-state follow-up, A3 observability, Phase B Chrome drives.
>
> Status 2026-08-23 (session 7): **P1 is DONE** — the Synthetic Lab generates
> grounded eval rows through the gateway (`grounded_qa`; the old provider was a
> package the repo never installed), reranker triplets are mined from real
> retrieval traces, and `epstein-files-1` has a published 200-row dataset,
> 998 triplets, a persisted Ragas eval (faithfulness 0.82 / relevancy 0.64),
> a Promptfoo run (21/25) and a cloud reranker that lifts MRR 0.63 -> 0.78.
> Record: `eval-data-lane-2026-08-22.md` (four adversarial codex passes, 52
> findings, all acted on; the SSE eval route now shares the POST scoring
> path and persists answer provenance, proven on a real index in
> `tests/integration/test_eval_trace_mining.py`). **Two machine crashes happened this
> session** (bf16 4B vLLM in the VM; then host MLX reranker training) and the
> operator set rules: API models for all test/eval/judge traffic
> (`openai.gpt-5.6-luna`), reranking on cloud models
> (`reranker_cloud_provider=litellm`, `openai.gpt-4.1-nano`), no MLX/GPU
> training or local model loads without the operator present, Colima VM at
> `--memory 16`. **P0-2's model choice is rejected**: the local lane must move to
> quantized Qwen 3.8 — the plan, the installed `vllm-metal` runtime and the
> downloaded `mlx-community/Qwen3.8-27B-4bit` are in
> `local-model-vllm-metal-2026-08-22.md` (cutover not landed; LiteLLM must be
> started with `--no-deps` until the compose `vllm` service is removed).
> Flyte-orchestrated Learning Agent training on the new dataset was NOT run
> (host MLX). Next: land P0-3 with the operator present, then A3, then Phase B
> (first defect already logged: Neural Visualizer `connect(null)`).
>
> Status 2026-08-22 (session 6): **P0-2 is DONE** — vLLM serves
> `Qwen/Qwen3-4B-Instruct-2507` (8192 ctx) on a 6 vCPU / 28 GiB Colima profile,
> the Learning Agent trains on `mlx-community/Qwen3-4B-Instruct-2507-4bit`, and
> both were proven with real queries/runs through API, Chrome and Flyte/MLflow.
> See §5 "P0-2 evidence". Session-5 status (kept): **P0-1 is DONE** — the LiteLLM gateway
> now serves 404 catalog-backed aliases (403 OpenRouter routes + `ragweld-local`),
> `infra/litellm-config.yaml` is generated from `data/models.json`, the Chat
> picker reflects the real catalog grouped by provider, and a real grounded
> answer on `epstein-files-1` through `litellm:openai.gpt-5.4-mini` was proven
> via API, Playwright (no interception) and Chrome. See §5 "P0-1 evidence" and
> `docs/references/generation-gateway-catalog.md`. Earlier status: Phase A2
> (Flyte) landed and pushed at `2c5dda6`; `epstein-files-1` (re)indexed on the
> promoted lane; two HARD RULES in force (real queries only; adversarial codex
> review). Everything below the line is the next agent's prompt.

Paste everything below this line into the next agent's first message.

---

Continue the Ragweld recovery and modernization in `/Users/davidmontgomery/ragweld`.
Work autonomously until blocked on something only the operator can provide. Do
not substitute plans, vocabulary, unit tests, or HTTP 200s for real runtime and
rendered-browser proof.

## 0. NEW HARD RULES (read first — they change how you work)

1. **Real queries only. NEVER `test` / `hello` / placeholder input.** Every
   retrieval, chat, eval, search, or answer exercise — in tests, manual probes,
   browser drives, scripts — MUST use a genuine domain question about the
   indexed corpus. Placeholder queries are fake-green AND they poison the
   reranker's triplet-mining signal (every real query/answer pair is training
   data). Example real query for `epstein-files-1`: "Which flights or plane
   management did Jeffrey Epstein discuss with Barry Cohen in October 2017?".
   Codified in `.claude/rules/testing.md` and `AGENTS.md`.
2. **Adversarial review of every major feature via `codex exec` at high
   reasoning effort**, prompted to REFUTE the change, BEFORE calling it done.
   `codex` (codex-cli 0.144.0) is installed at `/usr/local/bin/codex`. Point it
   at the diff; capture the outcome + fixes in the slice's exec-plan/memory
   note. Trivial mechanical edits are exempt. Codified in `.claude/rules/testing.md`.
3. **GUI proof standard is raised.** Phase B proofs come ONLY from the
   Claude-in-Chrome extension driving the real app with real mouse/keyboard and
   real domain queries — never API calls, never Playwright request interception.
   Playwright E2E (no interception) is for regression tests; interactive truth
   is Chrome-only.
4. **Spending money is authorized** where it removes a real blocker (OpenRouter
   inference, a real eval/triplet run). No cloud GPU spend for Unsloth without a
   fresh explicit ok. Do a final cost-aware acceptance pass, not a thrash.

## 1. Mandatory context (read fully, in this order, before any command)

1. `/Users/davidmontgomery/ragweld/AGENTS.md`
2. `/Users/davidmontgomery/ragweld/CLAUDE.md`
3. `/Users/davidmontgomery/ragweld/.claude/rules/testing.md` (the two new rules)
4. `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
   (its newest entry: `memory/recovery-findings-closure-and-acceptance-corpus-2026-08-21.md`)
   and the Claude project memory
   `/Users/davidmontgomery/.claude/projects/-Users-davidmontgomery-ragweld/memory/MEMORY.md`
   with its task logs `task-2026-08-22-local-models-p0-2.md`,
   `task-2026-08-22-gateway-catalog.md`, `task-2026-08-22-flyte-orchestration.md`,
   `task-2026-08-21-qdrant-retrieval-cutover.md`
5. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`
   ("Status as of 2026-08-21" + session-4 updates)
6. `/Users/davidmontgomery/ragweld/docs/references/training-control-plane-slice.md`,
   `retrieval-lane.md`, `eval-substrates.md`, `observability-online-slice.md`
7. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`
   (resolved; use as the Phase B regression checklist)

## 2. Verified checkpoint at handoff

- `/Users/davidmontgomery/ragweld`; branch `main` only; one worktree.
  **Local `main` carries P0-1 (`bf34506`) and P0-2 (`8536e5e`), ahead of
  `origin/main` (`2c5dda6`); NOT pushed — the operator pushes.** Tree clean.
  Gates at `8536e5e`: full pytest 812 passed/65 skipped; strict lane 69 passed;
  all validators + `generate_litellm_config.py --check` + web lint/build green;
  Playwright gateway spec 3/3. Earlier:
  Gates at `bf34506`: full pytest 765 passed/63 skipped; strict lane 67
  passed (needs Flyte up); all validators + `generate_litellm_config.py
  --check` + web lint/build green; Playwright gateway spec 3/3.
- Phase A2 (Flyte orchestration) landed in `66986ed` + `2c5dda6`: full pytest
  719 passed/63 skipped; strict-lane Flyte suite 6 passed; all validators +
  web lint/build green; live-proven on `aurora_acceptance`.
- `epstein-files-1` (re)indexed this session on the promoted lane — see §4.
- Do NOT create branches/worktrees. Commit verified slices directly to `main`
  and push when the operator authorizes (they push; you prepare).

## 3. Live runtime at handoff

- Colima profile `ragweld` = `--vm-type vz --cpu 6 --memory 28` (session 6).
- Docker context `colima-ragweld`; Compose project `ragweld`. Up: postgres,
  neo4j, qdrant (127.0.0.1:56333), mlflow (55500), litellm (54000), vllm
  (58080), grafana (3301), prometheus (59090), loki (53100), tempo (53200),
  alloy, promtail, postgres-exporter, **flyte** (127.0.0.1:30080 console/admin,
  minio 30002; the Flyte v1.16.8 sandbox). Alloy/promtail/observability live in
  `infra/docker-compose.observability.yml` — recreate with BOTH `-f` files.
- Flyte is behind `./start.sh --with-flyte`; the `learning-agent-train` launch
  plan is registered (`scripts/flyte_register_learning_agent.sh`). Its launch
  plan lives in an UNBOUND sandbox volume — `stop`/`start` keeps it, a container
  recreate/`down` drops it; re-run the register script if `workflow=flyte`
  starts 503-ing "not registered".
- Host API 127.0.0.1:58012 + Vite 127.0.0.1:55173. Session 5 restarted them
  by hand (`.venv/bin/uvicorn server.main:app --host 127.0.0.1 --port 58012`
  and `web/node_modules/.bin/vite --host 127.0.0.1 --port 55173 --strictPort`,
  both with `RAGWELD_NODE_BIN="$HOME/.nvm/versions/node/v22.22.0/bin/node"`)
  because `start.sh`'s EXIT trap tears both down when its uvicorn child is
  killed. `RAGWELD_NODE_BIN` is required for Promptfoo (system Node too old).
  LiteLLM container was recreated on the generated config (404 aliases).
- Corpora: `epstein-files-1` (§4), `aurora_acceptance` (deterministic acceptance
  corpus; its scoped config is now `workflow=flyte` + `tracking=mlflow`, so
  Learning Agent launch on aurora needs `./start.sh --with-flyte` or it fails
  closed with a typed 503), `recall_default` (chat memory; graph never applied).

## 4. Data: `epstein-files-1` is the real dataset now (done this session)

- Source: HF `to-be/epstein-emails`, materialized at
  `~/epstein-files/hf-to-be-epstein-emails` (4272 body-first `.txt` emails,
  metadata footer; hygiene fixed 2026-03-26; manifest is a sidecar).
- Indexed on the promoted lane: Postgres chunk rows + Qdrant dense
  (`BAAI/bge-small-en-v1.5`@384, local, offline, $0) + sparse (fastembed bm25)
  + Neo4j lexical graph. ~1195 chunks. Semantic KG was OFF (needs a real LLM —
  see §5 P0). Verify with a REAL query (rule 0.1), not "test".
- **This is the corpus the website demo depends on.** `ragweld.com` (the Astro
  marketing site + vendored demo at `/demo/`, repo
  `/Users/davidmontgomery/ragweld.com`, Netlify) serves Epstein data from Neon,
  populated by `ragweld.com/scripts/index-epstein.cjs`, which COPIES the
  already-indexed local `epstein-files-1` from THIS repo's Postgres+Neo4j.
  **That copy script is almost certainly broken by the retrieval cutover**: it
  reads chunk embeddings from Postgres, but the cutover moved vectors to Qdrant
  and dropped `chunks.embedding`. Fixing the website→Neon sync (read vectors
  from Qdrant, or export from the new lane) is a cross-repo task — do it in the
  `ragweld.com` repo, coordinated, not by reviving the old Postgres-vector path
  here.

## 5. Remaining mandate, in priority order

**P0-1 — DONE 2026-08-22: LiteLLM serves the real catalog.** Evidence:
- `data/models.json` GEN rows = 403 OpenRouter routes (all text-output feed
  rows except 12 `~provider/…-latest` rolling pointers and 6 `openrouter/*`
  meta-routers) + the `ragweld`
  vLLM row; each carries `gateway_alias` (`openai.gpt-5.4-mini`) and
  `gateway_upstream` (`openrouter/openai/gpt-5.4-mini`). Provider-direct GEN
  rows and the `ragweld-openrouter-smoke` alias are deleted.
- `infra/litellm-config.yaml` is GENERATED by `scripts/generate_litellm_config.py`
  (`--check` is a verification gate; `tests/unit/test_gateway_catalog.py`
  enforces catalog == mirror == YAML). Refresh: `uv run python
  scripts/refresh_models_catalog.py --apply` then `docker compose
  --project-name ragweld -f docker-compose.yml -f infra/docker-compose.observability.yml
  up -d --force-recreate --no-deps litellm`.
- `/api/chat/models` joins discovery with the catalog (provider, display
  name, context, pricing, vision); the Chat picker groups by provider; trace
  cost resolves by alias (`server/observability/costing.py`).
- Proof: LiteLLM `/v1/models` = 404; API chat with
  `sources.corpus_ids=[epstein-files-1]` + the Barry Cohen Oct-2017 question
  -> cited `HOUSE_OVERSIGHT_026216__msg_000__row_001162.txt` answer,
  `llm_used: true`; Chrome drive (real mouse/keyboard) selected "OpenAI:
  GPT-5.4 Mini", Epstein-only sources, got the cited answer (run `df4eb737…`,
  OpenRouter `gen-…` id, zero console errors); Playwright spec
  `web/tests/e2e/gateway/model_picker.spec.ts` (`NODE_PATH=web/node_modules
  npm --prefix web exec -- playwright test --config playwright.gateway.config.ts`).
- Adversarial review: `codex exec` (high) REFUTED the first pass (2 blockers +
  9 majors/minors) and the second on residuals (catalog bypass in the router,
  sequential lockstep writes, meta-router re-entry via upsert, uppercase
  aliases, sync IO in upsert) and a third on residuals (stale snapshot after
  CLI refresh, no interprocess lock, config-validate blind to unknown aliases);
  all fixed and re-verified — see
  `memory/task-2026-08-22-gateway-catalog.md` (upsert lockstep, non-catalog
  alias filtering, router exclusion, costing off the loop, Pydantic-validated
  rows, grouped Benchmark/Synthetic pickers, tiered pricing flag).

**P0 (original text, kept for context) — Make LiteLLM actually serve real models.**
Today the gateway effectively serves ONE tiny local model (`ragweld-local` →
vLLM `Qwen/Qwen3-0.6B`, max-len 2048, single stream) plus a single OpenRouter
smoke alias (`ragweld-openrouter-smoke` → `openrouter/openai/gpt-5.4-mini`).
`data/models.json` has 161 provider-DIRECT entries and ZERO routed through
OpenRouter. The operator had ~370 models via OpenRouter and wants that back.
- `OPENROUTER_API_KEY` is present in `infra/litellm.env`.
- `scripts/refresh_models_catalog.py` pulls the OpenRouter models feed
  (`https://openrouter.ai/api/v1/models`) into `data/models.json` + the web
  mirror. `server/chat/provider_router.py` already has OpenRouter routing
  (`select_provider_route`, gated on gateway.enabled + key).
- **Routing architecture (verified this session):** ALL generation goes
  through LiteLLM by ALIAS. `server/chat/provider_router.py`
  (`select_provider_route`) deliberately ignores provider/model identifiers and
  direct credentials — it resolves a LiteLLM gateway alias
  (`config.chat.litellm.default_model` or the picker's `model_override`) and
  sends it to LiteLLM. `infra/litellm-config.yaml`'s `model_list` maps each
  alias to the real upstream. So "serve ~370 OpenRouter models" is primarily a
  **`model_list` generation task**: generate LiteLLM entries mapping aliases →
  `openrouter/<provider>/<model>` for the catalog, and make those aliases the
  same ones `data/models.json` (+ the model picker) exposes. Today
  `model_list` has exactly two entries (`ragweld-local`,
  `ragweld-openrouter-smoke`); that is the whole gap.
- Wire it replacement-only (no dead provider-direct entries kept as "legacy"),
  refresh `data/models.json` (`scripts/refresh_models_catalog.py` — run it as
  `uv run python scripts/refresh_models_catalog.py ...`, it needs the repo on
  `PYTHONPATH`; a bare `python3` import of `server` fails), keep the LiteLLM
  `model_list` and the catalog aliases in lockstep, prove a real grounded
  answer on `epstein-files-1` end to end (LiteLLM → OpenRouter) with a REAL
  domain query, and prove the model picker reflects the real catalog in the
  browser. Spend money. This is a major feature → adversarial `codex exec`
  review before done (rule 0.2).

**P0-2 — DONE 2026-08-22 (session 6): the dead local models are replaced.** Evidence:
- Colima `ragweld` is now `--cpu 6 --memory 28` (host 48 GiB / 12 cores; vLLM
  reserves one vCPU and computes on five). `start.sh` and
  `tests/unit/test_runtime_launch_contract.py` carry that string.
- vLLM serves `Qwen/Qwen3-4B-Instruct-2507` (`Qwen3ForCausalLM`, bf16,
  `--max-model-len 8192`, `VLLM_CPU_KVCACHE_SPACE=4` = 29,056 KV tokens; ~15-17 GiB
  container). The catalog `ragweld` row, `VLLMConfig.default_model`,
  `tribrid_config.json`, the ProviderSetup placeholder and the docs moved with it;
  the launch-contract test pins compose model == config default == catalog row and
  catalog `context` == `--max-model-len`; `test_clean_start_defaults.py` sweeps 15
  live surfaces for the retired ids. LiteLLM still serves 404 aliases.
- Learning Agent base `training.ragweld_agent_base_model` =
  `mlx-community/Qwen3-4B-Instruct-2507-4bit` (Pydantic default, env loader,
  `tribrid_config.json`, TrainingStudio default, and the three stored per-corpus
  configs updated through `PUT /api/config?corpus_id=…`). The 1.7B-trained adapter
  in `models/learning-agent-active` was removed; run
  `aurora_acceptance__20260822_190536` (workflow=flyte `ra36477bf94be50f9180`,
  MLflow `22697a68…`) trained on the 4B base in 25 s, eval_loss 0.2332, and
  promoted a fresh adapter (manifest base_model = new). The Studio HUD shows it.
- `ui.chat_stream_timeout` is 600 (ceiling) in the runtime + stored configs:
  measured CPU throughput is ~2 tok/s on 3 compute cores (911-token grounded
  prompt + 143 tokens = 115 s); the Chrome chat on 5 cores took 81 s end to end.
- The `chat_template_kwargs.enable_thinking=false` passthrough in the Ragas and
  Promptfoo runners is deleted (workaround for the retired thinking-mode model).
- Proof: API `POST /api/chat` with `litellm:ragweld-local` on `epstein-files-1`
  and the Barry Cohen question -> 10 sources, trace provider LiteLLM/ragweld-local,
  $0 catalog cost; Chrome (real mouse/keyboard, new chat, Epstein-only sources)
  -> grounded answer naming the plane-management emails (Jet Aviation -> EJM,
  depreciation rules, cushions/internet, business plan), `llm_used: true`,
  `provider_response_id: chatcmpl-…` (vLLM, not OpenRouter), 1325 tokens, 81 s,
  no console errors.
- Adversarial review (`codex exec`, high): pass 1 REFUTED (1 blocker, 6 major,
  1 minor) -> dead in-process MLX chat path deleted (training-only adapters, truthful
  copy), validated adapter manifest + 409 on base/backend mismatch, timeout defaults
  600/900, readiness verifies vLLM `root`/`max_model_len`, repo-wide retired-id scan.
  Pass 2 REFUTED (4 major, 1 minor) -> whole-directory artifact validation (weights +
  adapter_config + manifest cross-checked + run identity), a real prompt budget
  (`server/chat/prompt_budget.py`: tiktoken counting, catalog window per alias,
  lowest-rank trimming, fail-closed guard in both transports, typed 413
  `prompt_budget_exceeded`, config-validate warning), frontend timeout literals tied
  to the Pydantic contract, operator docs fixed. Deferred (documented): a catalog
  capability flag to reject thinking-mode judge aliases; GraphRAG concurrency vs
  `--max-num-seqs 1`. Pass 3 REFUTED (7 major, 1 minor) -> streaming refusals
  are a typed 413 while priming (was an untyped 500), recall memory is trimmed
  before RAG evidence and a request that would lose all evidence is refused
  instead of silently answering without sources, trimming is linear and runs
  off the event loop (tokenizer prewarmed in the lifespan), the handler no
  longer imports `server.api` (fresh-process import test), text counts carry a
  1.25x cross-family factor and images 1600 tokens each, every gateway catalog
  row must carry a positive context (unknown windows fail closed), budget
  refusals use 413 so FastAPI's 422 validation contract stays intact
  (OpenAPI-vs-runtime test), stale operator docs/links fixed. Pass 4 REFUTED (2 P1,
  1 P2) -> token counting is per upstream family (text factor and per-image
  worst case from the catalog `provider`; Anthropic vision 4,784/image), the
  `## Context` framing is assembled in one place so planner and guard count the
  same text, stream refusals re-raise before any byte (413; registered on
  `/api/chat/stream`), and trimming is a binary search over full renders (maximal
  retention, O(log n)). Pass 5 REFUTED (1 P1, 1 P2) -> per-image accounting is
  model-class-aware from documented OpenAI maxima (gpt-4o-mini 48,169; patch-based
  3,778; tile-standard 1,445; Anthropic 4,784+), attachments are refused on rows
  with `supports_vision=false` (incl. `ragweld-local`), other families keep a
  labelled 4,800 heuristic; budget unit tests are snapshot-order independent.
  Pass 6 REFUTED (1 P1, 1 P2) -> OpenAI image accounting is per documented
  formula class (tile-mini 48,169; tile-standard 1,445; 1,536-patch 3,779;
  gpt-5.5 24,600; gpt-5.6 costed from real inline pixels, URL images refused;
  image-generation ids refused), every catalog OpenAI vision id is classified by
  an explicit test table, and a configured `vision_model_override` now forces the
  route for image requests over the picker's model. Pass 7 REFUTED (2 P2) ->
  gpt-5.4 gets its 2,500-patch class, the unit test holds an independent per-id
  table of documented maxima (bound >= documented for every catalog OpenAI vision
  id; over-reservation is the accepted direction), and the final guard decodes
  inline image sizes inside the worker thread. Pass 8 REFUTED (1 P3, 1 P2) ->
  gpt-5/o-series classified tile-based with their own documented maxima and a
  strict 3x over-reservation check; the semantic-cache image fingerprint runs off
  the loop (and is skipped when `bypass_if_images` applies) and both transports
  serialize image-bearing bodies in a worker, with an event-loop heartbeat
  regression over five multi-MiB attachments. Pass 9 was stopped before it
  produced a verdict; the pass-8 fix set (tile classification of gpt-5/o-series,
  off-loop image fingerprint + body serialization, heartbeat regression) is the
  only delta without an independent review. Known, documented residuals: image
  bounds for families without a published maximum are a labelled 4,800 heuristic;
  text factors are cl100k-based estimates (1.1 OpenAI/Qwen, 1.6 others); the
  gateway's own context error remains the backstop for both.
  Details: `~/.claude/projects/-Users-davidmontgomery-ragweld/memory/task-2026-08-22-local-models-p0-2.md`.
- Stale model caches still on disk (the `dcg` hook refuses recursive force
  deletes from the agent; nothing references them): host
  `~/.cache/huggingface/hub/models--mlx-community--Qwen3-1.7B-4bit` (938 MB) and
  volume `ragweld_hf_cache` path `/root/.cache/huggingface/hub/models--Qwen--Qwen3-0.6B`
  (1.5 GB). Operator may purge.
- Runtime notes: only loki/promtail have a restart policy — after a Colima bounce
  run `docker compose --project-name ragweld -f docker-compose.yml -f
  infra/docker-compose.observability.yml up -d postgres neo4j qdrant mlflow vllm
  litellm flyte grafana prometheus loki tempo alloy promtail postgres-exporter`
  (the Flyte launch plan survived two stop/start bounces); restart the host API
  afterwards. The dead in-process MLX chat path (`server/chat/ragweld_mlx.py`)
  was deleted in this session; Learning Agent adapters are training-only.

**P0-2 (original text, kept for context) — Replace the dead local models (no "legacy" retention).**
Session-5 findings: Qwen has shipped Qwen3.5 (2026-03), 3.6 (2026-04) and
3.8 (2026-08), but those are `Qwen3_5ForConditionalGeneration` (linear
attention + multimodal) and the CPU vLLM image (`vllm-openai-cpu:v0.26.0-arm64`)
cannot run them; the realistic "current Qwen3 ~4B" for CPU vLLM is
`Qwen/Qwen3-4B-Instruct-2507` (`Qwen3ForCausalLM`, non-thinking, so the
`<think>` JSON gotcha disappears). MLX base: `mlx-community/Qwen3-4B-Instruct-2507-4bit`.
**Blocker:** the Colima VM is 16 GiB with ~13 GiB in use (vllm 6.3 GiB for
0.6B incl. 4 GiB KV, neo4j 2.7, flyte 1.7); a 4B bf16 model needs ~8 GiB of
weights alone. Operator host action required before this can be proven:
`colima stop ragweld && colima start --profile ragweld --vm-type vz --cpu 4 --memory 28`
(then update the `colima start … --memory` string asserted in
`tests/unit/test_runtime_launch_contract.py` and `start.sh`).
vLLM `Qwen3-0.6B` and the MLX agent base `mlx-community/Qwen3-1.7B-4bit` are a
year out of date and too small to be useful. Replace with a current Qwen3
~3–8B (operator leans Qwen; Gemma is the alternative) — update `VLLM_MODEL` in
`docker-compose.yml`, the MLX agent base
(`training.ragweld_agent_base_model`), `data/models.json`, and any hardcoded
`Qwen3-1.7B`/`0.6B` references. Replacement-only: DELETE the outdated model
artifacts/dirs and stale catalog rows; do not keep them alive as fallbacks.
Confirm the new model actually loads/serves and answers a real query. (Note the
Qwen3 `<think>` gotcha: JSON-emitting judges/graders need
`chat_template_kwargs.enable_thinking=false`.)

**P1 — Real eval dataset + reranker triplet mining from `epstein-files-1`.**
The old 18-row synthetic artifact was garbage (`top1≈0.0556`; see
`docs/exec-plans/active/autopilot-status/eval-data.md`). With a real LLM (P0)
available: generate a real eval dataset from `epstein-files-1` (Distilabel/Ragas
per that lane), run Ragas + Promptfoo for real, and mine reranker triplets from
REAL query/answer/retrieval traces (never placeholders). Then exercise the
Flyte-orchestrated Learning Agent training on that data (MLX host backend; the
Flyte lane is wired — §Phase A2 done).

**P1 — Finish Phase A.**
- A3: add Mimir (Prom remote-write), Pyroscope (+ host-API profiling SDK),
  Faro (Alloy faro receiver + web SDK), Alertmanager, Langfuse as Compose
  services with FUNCTIONAL readiness probes
  (`server/observability/status.py` has the readiness-path table). Never report
  healthy from config presence. OpenCost only if it can be made real on Colima.
- A5: residual dead-code removal + the full final acceptance matrix (with real
  queries), including a paid OpenRouter acceptance retest once P0 lands.
- A2 (Flyte) is DONE. Unsloth stays a hardware blocker (needs CUDA; darwin/arm64
  host) — report it, do not fake it, no cloud GPU spend without explicit ok.

**P2 — Phase B: full Chrome-driven GUI tie-in (raised bar).**
Only after P0 (a working LLM). Drive every flow in
`frontend-browser-findings-2026-08-20.md`'s checklist (B1–B12 from the session-4
handoff) as a real user in Chrome, with REAL domain queries, recording
screenshots + DOM + console/network evidence. B8 drives the Flyte lane
(`./start.sh --with-flyte`). Every defect found is fixed in-repo with a real
test (Playwright without interception, or pytest without mocks, real queries)
and re-driven in Chrome before commit. Console/network must be clean after each
flow except intentionally provoked failures.

## 6. Lessons learned (carry these — they cost time)

- **Never do blocking network IO on the event loop.** The Flyte reconcile bug
  produced proxy 5xx with NOTHING in the API log (the parked "B12" symptom).
  Pattern that works: blocking probe via `asyncio.to_thread`, then apply state
  on the loop thread so `asyncio.Event.set()` stays loop-safe
  (`server/api/agent.py` `_fetch_flyte_state`/`_apply_flyte_state`). Any
  external-probe-on-load must follow this.
- **Adversarial review catches what gates cannot.** The blocking-IO regression
  and an unpopulated public field (`workflow_phase`) were both found by review,
  not by green tests. This is why rule 0.2 exists.
- Sandbox/control-plane state in unbound Docker volumes vanishes on recreate
  (Flyte launch plan). Know what survives `stop/start` vs `down`.
- Qwen3 `<think>` output breaks JSON judges unless thinking is disabled.
- vLLM is single-stream (`--max-num-seqs 1`); serialize judge/eval calls.
- Strict-lane-only tests (`requires_postgres/neo4j/qdrant/flyte`) are skipped by
  plain `pytest`; run `RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh`.
- `check_banned.py` flags any `patch(` (incl. `client.patch`) and the words
  `monkeypatch`/`mock` even in comments — use `client.request("PATCH", ...)` and
  avoid those words in test source.
- `infra/litellm-config.yaml` is a single-file read-only bind mount: never
  replace it via tmp+rename (inode changes under the container); the generator
  writes in place, and LiteLLM still needs `--force-recreate --no-deps litellm`.
- `start.sh` has an EXIT trap: killing its uvicorn child tears down Vite too.
- Two `data-testid=model-picker` exist when the Sidepanel shows the Quick
  Model Switcher; Playwright must use `.first()`. The app is served under
  `/web/`, so `page.goto('/chat')` hits the origin root (404) — use relative
  paths. claude-in-chrome `find` refs go stale after DOM changes.

## 7. Verification gates (run until green before "done")

```
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/generate_litellm_config.py --check
uv run python scripts/check_runtime_capabilities_catalog.py
uv run python scripts/validate_contract_bundle.py
uv run pytest -q
npm --prefix web run lint && npm --prefix web run build
RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh
# GUI slices: real Playwright E2E (no interception) + Chrome interactive proof
```
Then the adversarial `codex exec` review (rule 0.2). Regenerate `generated.ts` +
contract bundle after any registered-boundary change; never hand-edit them,
`mkdocs/**`, or `.env` secrets into git.

## 8. Non-negotiables carried forward

- One branch, one worktree, clean tree between slices; never create branches/
  worktrees. Replacement-only: no fallbacks, shims, dual paths, or legacy
  toggles kept "just in case".
- Pydantic at serialized boundaries; generated wire types; local/UI types stay
  local. No compatibility fallbacks or dual contracts.
- Do not manage Colima from repo code; do not run `reset-data.sh` without the
  exact confirmation workflow.
- Do not mass-rename `tribrid` identifiers.
- Subagents and the main session must never edit the same files concurrently.
