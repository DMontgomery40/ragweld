# Handoff Prompt — Ragweld Recovery, Session 5

> Status 2026-08-22: Phase A2 (Flyte orchestration) landed and is pushed
> (`main == origin/main == 2c5dda6`). The `epstein-files-1` corpus was
> (re)indexed on the promoted lane this session — a real ~4.3k-email dataset,
> not a toy. Two new HARD RULES are now in force (real queries only; adversarial
> codex review of major features). The dominant remaining blocker is that the
> LLM gateway does not actually serve real models. Everything below the line is
> the next agent's prompt.

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
   and the newest entries:
   `memory/task-2026-08-22-flyte-orchestration.md`,
   `memory/task-2026-08-21-qdrant-retrieval-cutover.md`,
   `memory/recovery-findings-closure-and-acceptance-corpus-2026-08-21.md`
5. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`
   ("Status as of 2026-08-21" + session-4 updates)
6. `/Users/davidmontgomery/ragweld/docs/references/training-control-plane-slice.md`,
   `retrieval-lane.md`, `eval-substrates.md`, `observability-online-slice.md`
7. `/Users/davidmontgomery/ragweld/docs/exec-plans/active/frontend-browser-findings-2026-08-20.md`
   (resolved; use as the Phase B regression checklist)

## 2. Verified checkpoint at handoff

- `/Users/davidmontgomery/ragweld`; branch `main` only; one worktree;
  `main == origin/main == 2c5dda6`; tree clean except `.claude/settings.json`
  (a pre-existing unrelated JSON-indent change — leave it or commit separately).
- Phase A2 (Flyte orchestration) landed in `66986ed` + `2c5dda6`: full pytest
  719 passed/63 skipped; strict-lane Flyte suite 6 passed; all validators +
  web lint/build green; live-proven on `aurora_acceptance`.
- `epstein-files-1` (re)indexed this session on the promoted lane — see §4.
- Do NOT create branches/worktrees. Commit verified slices directly to `main`
  and push when the operator authorizes (they push; you prepare).

## 3. Live runtime at handoff

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
- Host API 127.0.0.1:58012 + Vite 127.0.0.1:55173 started with
  `RAGWELD_NODE_BIN="$HOME/.nvm/versions/node/v22.22.0/bin/node" ./start.sh --no-docker`.
  `RAGWELD_NODE_BIN` is required for Promptfoo (system Node too old).
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

**P0 — Make LiteLLM actually serve real models (the dominant blocker).**
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
- Wire LiteLLM so real aliases route through OpenRouter (replacement-only: no
  dead provider-direct entries kept as "legacy"), refresh the catalog, prove a
  real grounded answer on `epstein-files-1` end to end (LiteLLM → OpenRouter),
  and prove the model picker in the UI reflects the real catalog. Spend money.

**P0 — Replace the dead local models (no "legacy" retention).**
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

## 7. Verification gates (run until green before "done")

```
uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
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
