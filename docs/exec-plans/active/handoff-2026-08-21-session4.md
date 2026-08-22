# Handoff Prompt — Ragweld Recovery, Session 4

> Status 2026-08-21 (later in session 4): Phase A1 (retrieval promotion
> cutover) landed on `main`; see the execution record in
> `retrieval-promotion-cutover-2026-08-21.md` and `docs/references/retrieval-lane.md`.
> A2 (Flyte orchestration) landed later in session 4: Compose-owned `flyte`
> service, `scripts/flyte_register_learning_agent.sh`, flyteadmin REST client,
> launch/execute/status/cancel wiring; see
> `docs/references/training-control-plane-slice.md`. Continue from A3.
> After A2, `aurora_acceptance` scoped config is `workflow=flyte` +
> `tracking=mlflow`: Phase B needs `./start.sh --with-flyte` with the launch
> plan registered (`scripts/flyte_register_learning_agent.sh`) before B8, or
> Learning Agent launches on aurora fail closed with a typed 503. The Flyte
> sandbox's launch plan lives in an unbound in-cluster volume — a container
> recreate/`down` drops it (stop/start is safe); re-run the register script.
> The transient dev-proxy 503s seen once in Chrome on
> `/api/index/{id}/status|stats` and `/api/chat/models` (not present in the API
> log, not reproducible) belong to B12.

Paste everything below this line into the next agent's first message.

---

Continue the Ragweld recovery and modernization work in
`/Users/davidmontgomery/ragweld`. Work autonomously until blocked on something
only the operator can provide. Do not substitute plans, vocabulary, unit tests,
or HTTP 200s for real runtime and rendered-browser proof.

## 1. Mandatory context (read fully, in this order, before any command)

1. `/Users/davidmontgomery/ragweld/AGENTS.md`
2. `/Users/davidmontgomery/ragweld/CLAUDE.md`
3. `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`
   and the entry `memory/recovery-findings-closure-and-acceptance-corpus-2026-08-21.md`
   (traps, gotchas, what is real vs. not)
4. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`
   (see "Status as of 2026-08-21")
5. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/retrieval-promotion-cutover-2026-08-21.md`
6. `/Users/davidmontgomery/ragweld/docs/references/eval-substrates.md`,
   `training-control-plane-slice.md`, `retrieval-lane.md`,
   `observability-online-slice.md`
7. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`
   (all resolved; use as the regression checklist for the frontend phase)

## 2. Verified checkpoint at handoff

- Repository: `/Users/davidmontgomery/ragweld`; branch `main` only; one worktree;
  clean tree; `main == origin/main == ec7e852`.
- 19 verified commits since the prior handoff (`56ee2ca`). Each landed with
  the standard gates green; several were adversarially reviewed by a subagent
  with findings fixed before commit.
- Do not create branches or worktrees. Commit verified slices directly to
  `main` and push normally.

## 3. Live runtime at handoff (inspect before starting anything)

- Docker context `colima-ragweld`; Compose project `ragweld` with all of:
  postgres, neo4j, qdrant (v1.17.1, 127.0.0.1:56333), mlflow (v2.22.2,
  127.0.0.1:55500), litellm (54000), vllm (58080), grafana (3301),
  prometheus (59090), loki (53100), tempo (53200), alloy (52345/54319/54320),
  promtail, postgres-exporter. Alloy and promtail live in
  `infra/docker-compose.observability.yml` — recreate them with BOTH `-f`
  files.
- Host API 127.0.0.1:58012 and Vite 127.0.0.1:55173 were started with
  `RAGWELD_NODE_BIN="$HOME/.nvm/versions/node/v22.22.0/bin/node" ./start.sh --no-docker`
  (no tmux; `./stop.sh --no-docker` stops only owned processes).
  `RAGWELD_NODE_BIN` is required for Promptfoo: the system Node 22.14 is
  refused by promptfoo 0.122.0.
- Corpora: `aurora_acceptance` (the deterministic acceptance corpus from
  `tests/fixtures/acceptance_corpus`, indexed on the promoted Postgres +
  Qdrant + Neo4j lane; scoped config has `training.ragweld_agent_tracking_backend=mlflow`
  and `evaluation.ragas_enabled=true` from the live proofs) and
  `recall_default` (Recall chat memory; graph is never applied to it by design).

## 4. What is real now (do not re-prove; do regression-check)

- Typed 409/503 retrieval/generation boundaries with a structured chat error
  card; recall dense-contract enforcement; stored-global-config fallback fix.
- Native lane acceptance: create → index → three legs → grounded
  LiteLLM→vLLM answer → citations → rendered in browser, plus fail-closed
  drills.
- Pilot lane (Haystack/Docling/Qdrant): real contracts, service Qdrant,
  Docling extraction, sparse IDF + config-driven fusion, pilot answer with
  citations, staged atomic promotion, corpus-delete cleanup.
- MLflow tracking real (runs/metrics/artifacts, cancel → KILLED); Ragas and
  Promptfoo execute for real on eval runs; Flyte/Unsloth fail closed with exact
  blockers.
- Observability: host API logs in Loki (`{ragweld_service=~"api|..."}`),
  readiness-path probes, dashboards provisioned and querying live metrics,
  traces discoverable in Tempo.

## 5. Phase A — remaining backend mandate (in this order)

A1. **Retrieval promotion cutover** (atomic, replacement-only). Follow
    `retrieval-promotion-cutover-2026-08-21.md` exactly: index writes go to a
    staged Qdrant generation (dense + sparse) with chunk rows staying in
    Postgres as control/state; `server/retrieval/fusion.py` vector and sparse
    legs query Qdrant; Neo4j graph leg unchanged; recall writes move to the
    same path; delete `PostgresClient.vector_search/sparse_search*/fts_search*/
    bm25_search_pg_search/pg_search_available/file_path_search/ensure_vector_index`,
    the embedding writes in `upsert_embeddings`, dead sparse-engine config, the
    pilot's separate endpoints/UI once the canonical paths ARE the new lane,
    and their tests/docs/glossary entries. Update
    `tests/integration/test_required_retrieval_leg_contract.py` sparse fixture
    to sparse-model drift. Close the slice only with the full clean flow on the
    promoted lane for `aurora_acceptance` (index → three legs → answer +
    citations → browser), strict lane, and full gates. Do not start it unless
    you can land it green in one commit; do not delete the native lane before
    that proof.
A2. **Flyte orchestration**: provision a local Flyte control plane
    (e.g. `flytectl demo start` on the Colima VM), register a real Learning
    Agent launch plan, and wire launch/status/cancel in
    `server/api/agent.py` + `server/training/control_plane.py` so
    `training.ragweld_agent_workflow_backend=flyte` executes instead of
    refusing. Keep the typed 503 for the unreachable case. Unsloth stays a
    reported hardware blocker (needs CUDA; no cloud GPU spend without explicit
    authorization).
A3. **Observability deployments**: add Mimir (Prometheus remote write),
    Pyroscope (+ Python profiling SDK for the host API), Faro (Alloy faro
    receiver + web SDK), Alertmanager, and Langfuse as Compose services with
    functional readiness probes (`server/observability/status.py` already
    has the readiness-path table); never report them healthy from config
    presence alone. OpenCost only if it can be made real on Colima.
A4. After each slice: narrowest tests, then
    `uv run python scripts/check_docs_ownership.py`, `uv run scripts/check_banned.py`,
    `uv run scripts/validate_types.py`, `uv run python scripts/check_runtime_capabilities_catalog.py`,
    `uv run python scripts/validate_contract_bundle.py`, `uv run pytest -q`,
    `npm --prefix web run lint`, `npm --prefix web run build`,
    `RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh`; adversarial
    subagent review; commit; push; `main == origin/main`; clean tree.

## 6. Phase B — full frontend tie-in through Claude-in-Chrome (real user behavior)

Only after Phase A lands. Every proof in this phase must come from the
Claude-in-Chrome extension driving the real app at `http://127.0.0.1:55173/web/`
with actual mouse clicks, typing, scrolling, dropdown selections, and form
submits — not API calls, not Playwright, not request interception. Record
evidence (screenshots saved to disk + DOM reads + console/network reads) per
flow and attach it to the exec-plan status.

Known browser quirk: the operator's Chrome renders a ~2370px CSS viewport at a
1600px window (page zoom); exact-viewport layout checks remain a Playwright
concern, but user-behavior proof is Chrome-only.

Flows to drive end to end, each as a user would:
B1. Dashboard → Quick Actions → Run Indexer for `aurora_acceptance` on the
    promoted lane; watch progress in the UI; confirm stats update.
B2. RAG → Retrieval: change a fusion weight and a toggle, see the auto-save
    ack, reload, confirm persistence; Run the canonical search from the UI and
    see per-leg provenance.
B3. RAG → Indexing: open the tab and confirm nothing mutates config (no
    "Apply All Changes *"); trigger a force reindex from the UI.
B4. Chat: pick the corpus in Sources, enable all three legs, send a question,
    see the grounded answer + citations + trace block; click the Tempo /
    Grafana links and confirm they open to the real trace/dashboard; toggle
    Recall intensity; use History / New chat / Export.
B5. Chat failure UX: cause a real contract failure (e.g. stop Neo4j with the
    graph leg on) and confirm the structured error card renders with no
    generated answer; restore the service.
B6. Admin → Basic/Advanced/Raw: flip a boolean toggle and a select, verify the
    readiness chips react, verify Raw shows the same value.
B7. Infrastructure → Services/Docker: confirm host API vs optional container
    labels; stop/start the qdrant container from the Docker subtab and watch
    status flip; view container logs from the UI.
B8. Training Center (Learning Agent Studio): set tracking=mlflow, start a
    small run from the UI, watch live metrics, cancel a second run, open the
    MLflow link and confirm the run state there; with Phase A2 done, do the
    same with workflow=flyte and open the Flyte console link.
B9. Eval Analysis: add a dataset entry with an expected answer via the dataset
    UI, run an eval with Ragas enabled, open the drill-down Ragas card, click
    Run Promptfoo regression, expand a failing/passing test, open Trace Viewer.
B10. Grafana tab: open each provisioned dashboard and confirm panels render
     real series (no "No data" on gateway/serving panels during load).
B11. Responsive pass: resize to a narrower desktop width in Chrome and
     re-drive B4 and B6; no clipped dock, no overlaps.
B12. Console/network hygiene: after every flow, `read_console_messages` must
     show no errors/warnings attributable to the app, and
     `read_network_requests` must show no 4xx/5xx other than the ones
     intentionally provoked in B5.

Fix every defect found in Phase B in the repo (backend or frontend) with a
real test (Playwright without interception or pytest without mocks), then
re-drive the flow in Chrome before committing. Update
`frontend-browser-findings-2026-08-20.md` (or a new dated findings file) with
the evidence.

## 7. Non-negotiables carried forward

- One branch, one worktree, clean tree between slices; never create
  branches/worktrees.
- Replacement-only: no fallbacks, shims, dual paths, toggles back to legacy.
- Pydantic at serialized boundaries; generated wire types; never hand-edit
  `generated.ts`, the contract bundle, or `mkdocs/**`.
- No `unittest.mock`/`monkeypatch` in Python tests; no Playwright request
  interception. `check_banned.py` also flags any `patch(` — use
  `client.request("PATCH", ...)`.
- Do not manage Colima from repo code; do not run `reset-data.sh` without the
  exact confirmation workflow; no paid OpenRouter requests except a final
  acceptance retest; no cloud GPU spend without explicit authorization.
- Do not mass-rename `tribrid` identifiers.
- Subagents and the main session must never edit the same files concurrently.

## 8. Gotchas that cost time this session

- Qwen3 `<think>` output breaks JSON-emitting judges/graders unless
  `chat_template_kwargs.enable_thinking=false` is passed.
- vLLM is single-stream (`max-num-seqs 1`); serialize judge calls and expect
  minutes per eval entry.
- `requires_postgres/neo4j/qdrant` tests run only in the strict lane; plain
  `pytest` skips them.
- Ragas needs `langchain*<1` pins (already in `pyproject.toml`).
- Promptfoo: `RAGWELD_NODE_BIN` must point at a supported Node.
- Brace-matching code removal stops at destructured parameter objects; check
  for orphaned `: {` fragments.
- promtail logs benign "could not inspect container" errors for removed
  strict-lane containers.
