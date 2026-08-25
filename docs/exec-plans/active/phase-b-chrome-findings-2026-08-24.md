# Phase B Chrome Drive Findings — Session 11

Date: 2026-08-24

Status: in progress

Protocol: every flow is driven by the Claude-in-Chrome extension against the
real app at `http://127.0.0.1:55173/web/` with real mouse/keyboard and real
domain queries (rule 0.1/0.3). Defects are fixed in-repo with a real test
(Playwright, no interception) and re-driven in Chrome before commit. Checklist
B1–B12 is defined in `handoff-2026-08-21-session4.md` §6.

Session constraint: the operator's Chrome window is occluded/minimized during
this session (`document.visibilityState === "hidden"`), so requestAnimationFrame
does not fire and background timers are throttled. DOM interaction, network,
and screenshots are unaffected. RAF-dependent proofs (WebGL canvases) were
driven by advancing R3F frames explicitly; the Playwright specs run in a
visible viewport and cover the animated path.

## Defect 1 (carried in): Learning Ranker Neural Visualizer blank + `connect(null)` — FIXED

Logged 2026-08-22 (eval-data-lane session Chrome drive): the Learning Reranker
Studio's Neural Visualizer rendered a blank panel and drei OrbitControls logged
`connect(null)`.

### Root cause

`TrajectoryScene` (`web/src/components/RerankerTraining/NeuralVisualizerWebGL2.tsx`)
used drei's `<Environment preset="city">`, which fetches
`potsdamer_platz_1k.hdr` from an external CDN (`raw.githack.com`) at runtime
and suspends the R3F tree while the fetch is pending (observed pending 44s+ on
one load). The suspend/reveal cycle re-runs `CanvasImpl`'s unmount effect;
R3F v9's `unmountComponentAtNode` schedules a 500 ms-delayed disposal that then
fires against the remounted root: `events.disconnect()` (→ OrbitControls
`connect(null)`), `forceContextLoss()` (→ "THREE.WebGLRenderer: Context
Lost."), `dispose(scene)`, and `_roots.delete(canvas)` — evicting the live
root from the render loop map. The canvas stays mounted, sized, and
`active: true`, but no frame ever renders again and pointer controls are dead.
Verified against the installed `@react-three/fiber` 9.5.0 dist (identical code
in 9.7.0, so an upgrade does not fix it).

### Fix

Replaced the CDN-fetched suspending environment with three.js's procedural
`RoomEnvironment` via `PMREMGenerator.fromScene` (synchronous, zero network,
offline-capable): `StudioEnvironment` in `NeuralVisualizerWebGL2.tsx`. This
also covers the WebGPU variant and the Learning Agent Studio, which reuse
`TrajectoryScene` / `NeuralVisualizer`.

### Evidence

- Chrome (real input): scene paints the glass terrain + trajectory (center
  drawing-buffer pixels ~rgb(168,236,255) vs clear color #050712); a real
  mouse drag rotates the camera (pixel strip changed) — controls connected;
  zero console errors; no `.hdr` request leaves the machine.
- Regression spec `web/tests/e2e/exhaustive/learning_reranker_visualizer.spec.ts`
  (no interception): canvas reaches settled layout, frameloop ticks (>10
  RAF/s), scene paints above the clear color, drag changes the rendered view,
  no external 3D-asset fetches, no context loss, clean console. 5/5
  consecutive green runs.
- `npm --prefix web run lint` + `npm --prefix web run build` green.

### Incidental

- Dev-server hygiene: two Vite dep-optimizer states (page on `v=ee9d88c6`,
  disk at `v=1cbcaa90`) predated this session's Vite restart; a stale Vite
  can serve mixed module instances after re-optimization. Restarted Vite with
  `--force`; not an app defect.
- The workbench app shell loads Google Fonts (`fonts.gstatic.com`) at
  runtime — the workbench is not fully offline. Out of scope here; candidate
  for the A5 residual pass.

## Defect 2: native window.confirm/alert dialogs freeze the workbench — FIXED

Found driving B1/B3: clicking "Index Now" opened a native `window.confirm`
(the cost/time estimate gate in `IndexingSubtab.handleStartIndex`). Native
dialogs block the renderer's main thread — SSE streams stall, the page reads
as a hard hang when the window is occluded, and the mandated Chrome-extension
proof tooling cannot drive past them (CDP evaluate times out). The repo had 9
native-dialog call sites, including `alert('Changes applied successfully')` on
the Sidepanel Apply Changes path.

### Fix

- New shared promise-based in-app confirm (`web/src/components/ui/confirmDialog.tsx`,
  testids `confirm-dialog`, `confirm-dialog-accept`, `confirm-dialog-cancel`;
  Enter/Escape keyboard handling, danger variant).
- New plain-function toast (`web/src/utils/toast.ts`);
  `useUIHelpers().showToast` now delegates to it.
- Converted: Index Now estimate gate + Delete index (IndexingSubtab), delete
  corpus (RepoSwitcherModal), delete chat (ChatInterface), reset prompt
  (SystemPromptsSubtab), delete eval entry (QuestionManager) → `confirmDialog`;
  Apply Changes success/error (Sidepanel) and reload failure (RetrievalSubtab)
  → toast. Deleted the consumer-less `useErrorHandler.showAlert`.
- Zero native `confirm(`/`alert(`/`prompt(` calls remain in `web/src`.

### Evidence

- Chrome (real input): Index Now now opens the in-app dialog with the real
  estimate (4 files, 543 est tokens, $0.00, 12.0s–24.1s) while the page stays
  interactive; Cancel closes it; no run starts.
- Regression spec `web/tests/e2e/exhaustive/native_dialog_replacement.spec.ts`
  (no interception; native dialogs stubbed to THROW so any regression fails
  loudly): dialog renders, cancel starts no run, clean console. 3/3 green.
- `npm --prefix web run lint` + build green.

## Defect 3: nested `<button>` in Index Stats header (invalid HTML) — FIXED

The clean-console assertion in the new spec caught React's "In HTML, <button>
cannot be a descendant of <button>" error on the Indexing page: the Index
Stats collapsible header was a `<button>` containing the Refresh `<button>`.
Fixed by making the header a keyboard-accessible `div[role=button]`
(`aria-expanded`, Enter/Space). The spec's clean-console assertion now passes,
pinning the regression.

## B1/B3 drive: Dashboard Run Indexer + Indexing force reindex — PASS (with defect 2 fixed)

- Dashboard → Quick Actions: corpus switched to Aurora Acceptance via the
  in-app switcher; Run Indexer surfaced a truthful embedding-contract guard:
  the live aurora index still carried the legacy `deterministic` stored
  contract vs the current `provider` config, and the run failed closed with
  the exact operator action. (The stored contract was stale drift from the
  pre-cutover acceptance design; tests use their own seeded corpora.)
- RAG → Indexing on aurora_acceptance: opening the tab mutated nothing
  (Apply All Changes stayed disabled; the 2026-08-20 P1 regression holds),
  the last failed run and its error were replayed truthfully, and the
  contract-lock banner explained force reindex.
- Force reindex driven from the UI (real clicks, in-app confirm): cleared the
  old index (`force_reindex=1` in the log), embedded the 4 acceptance files
  on the provider contract, promoted Qdrant generation
  `ragweld_chunks_aurora_acceptance_fc42b14b__e382a139` (points=4
  dense_points=4), progress bar Complete/100%, run
  `20260824T203702_f7ead99791` complete, console clean.
- Minor (logged, not fixed): after a server-side run error, the Dashboard
  quick-action console appends `# Error: Connection lost`, implying a
  transport failure when the stream simply ended with the run error. Cosmetic
  truthfulness nit on the dashboard log surface only.

## Defect 4: "Tempo trace" link 404s (Tempo has no UI) — FIXED

Found driving B4: the chat trace block's "Tempo trace" link pointed at
`{tempo_base_url}/trace/{id}` (`apply_default_links`,
`server/observability/runtime.py`), which returns 404 — Tempo is API-only.
GitNexus impact: CRITICAL (all chat/search/answer paths + middleware), but the
change is confined to the emitted URL string.

### Fix

The link now opens Grafana Explore on the in-repo provisioned Tempo
datasource (uid `tempo`) with a TraceQL query for the canonical trace id,
gated on BOTH `tracing.tempo_base_url` and `ui.grafana_base_url`. Grafana's
anonymous Viewer role cannot use Explore, so the compose Grafana env gains
`GF_USERS_VIEWERS_CAN_EDIT: "true"` (viewers get Explore + temporary panel
edits; nothing saveable; 127.0.0.1-bound).

### Evidence

- Unit test `test_tempo_trace_link_targets_grafana_explore_not_the_bare_tempo_port`
  (real request observation, tracing_mode=local) pins the URL shape; suite
  28 passed.
- Chrome (real click): the link opens "Explore - Tempo - Grafana" rendering
  the full `ragweld.chat_stream` span waterfall (14.93s, 10 spans):
  retrieval.vector 7.31s / retrieval.sparse 258.8ms / retrieval.graph 45.77ms
  / generation.gateway_call 4.31s (reranker.generation inside) /
  generation.gateway_stream 2.73s — per-leg provenance visible in the trace.
- Grafana dashboard link 200; Langfuse trace page 200 for the same trace id.

## B2 drive: Retrieval config auto-save + persistence — PASS

- Opening RAG → Retrieval mutates nothing (Apply All Changes disabled).
- Vector weight 0.4 → 0.45 via real input: the UI auto-normalized all three
  weights to sum 1 (0.4286/0.2857/0.2857) and auto-saved server-side with no
  Apply click (verified via `GET /api/config?corpus_id=epstein-files-1`).
- Enable MMR toggled on, page reloaded: checkbox stayed checked and
  `retrieval.enable_mmr=true` persisted.
- Original values restored exactly afterwards via `PUT /api/config`.
- Nits (logged, not fixed): normalized weights render as raw 17-digit floats
  in the inputs; exact-value restoration through the UI is awkward because
  every edit renormalizes. The standalone "canonical search" surface no
  longer exists — per-leg provenance is proven through Chat's trace (B4).

## B4 drive: Chat end-to-end — PASS (with defect 4 fixed)

- Sources: epstein-files-1 selected alongside Recall; all three legs enabled
  (pills flip to On Vector/On Sparse/On Graph).
- Real question "Which flights or plane management did Jeffrey Epstein
  discuss with Barry Cohen in October 2017?" on `OpenAI: GPT-5.6 Luna` →
  grounded answer naming the Jet Aviation → EJM management switch, with
  HOUSE_OVERSIGHT citations + recall citations and scores, trace block
  (run_id, OpenRouter provider_response_id, trace_id, correlation_id,
  llm_used: true).
- Second question (Jet Aviation vs EJM comparison) after the API restart:
  Routing Trace panel shows canonical trace, POST /api/chat/stream 14920ms,
  real cost $0.000322 (1203 tokens), and all three link chips resolve.
- Recall intensity: dropdown auto → light for one message; footer flipped
  from "standard 5 matches" to "light 3 matches" (7705ms).
- History lists sessions with counts; New chat creates and activates a fresh
  session; Delete chat raises the new in-app danger dialog (truthful copy)
  and deletes on accept.
- Export: the handler is a standard blob-anchor download and executed
  without error, but Brave under CDP automation silently drops
  script-initiated downloads (a probe blob download also never landed), so
  the resulting file could not be observed in this environment. Not an app
  defect; re-verify manually when the operator is present.

## B5 drive: Chat failure UX — PASS

Stopped `ragweld-neo4j-1` with the graph leg on and asked a real question:
the assistant rendered the structured error card — code
`dependency_unavailable`, "Neo4j graph store is unavailable.", the exact
required action, "Generation did not run for this request.", contract
details behind a Details disclosure — no raw JSON, no fabricated answer.
Neo4j restarted (healthy) and `/api/ready` reports ready.

## B6 drive: Admin Basic/Raw — PASS

- Runtime readiness chips render live (LiteLLM: ready, vLLM: ready), and
  every field save triggers a readiness + registry refresh (observed
  `GET /api/config/readiness` after each PATCH).
- Boolean toggle `chat.image_gen.enabled`: each click auto-saves via
  `PATCH /api/config/chat?corpus_id=epstein-files-1` (scoped to the active
  corpus, 200). The Raw section editor's `chat` JSON showed the same
  `image_gen.enabled: true` the toggle saved; value restored to `false`
  afterwards. Enum selects ride the same per-field PATCH path.
- The visible selects on Basic are surface filters (integration/scope/
  category), not config fields — noted for clarity.

## B7 drive: Infrastructure Services + Docker — PASS

- Services subtab keeps the truthful taxonomy: "Host processes" (FastAPI +
  Vite from live process probes, both Running), Container State read-only
  with lifecycle in Docker subtab, Data plane cards; Neo4j honestly showed
  "Up 6 minutes" right after the B5 drill.
- Docker subtab: stopped Qdrant with a real click → card flipped to
  "Stopped — Exited (143)" with a START control; LOGS opened a modal with
  the real container log (actix lines from this session's retrievals);
  START brought it back ("Up 4 seconds (health: starting)" → healthy).
- Nit: the logs modal renders at the top of the page — clicking LOGS while
  scrolled down means the modal opens above the viewport.

## Defect 5: SSE eval route silently skips Ragas — FIXED

Found driving B9: the UI's "Run Eval" uses `GET /api/eval/run/stream`, which
had its own metrics assembly with NO Ragas leg — with `ragas_enabled: true`
a 10-question run persisted `metrics.ragas == {}` and no generated answers
(run `epstein-files-1__20260824_211830`), while `POST /api/eval/run` did
full generation + judging. A forbidden dual-path divergence (the P1 fix had
unified retrieval scoring but not the Ragas leg).

### Fix

Extracted shared helpers in `server/api/eval.py` —
`_resolve_ragas_answer_route` (preflight + gateway route),
`_generate_ragas_answer` (grounded answer + RagasSample per entry),
`_apply_ragas_scores` (judging + per-entry and mean scores) — used by BOTH
`evaluate_dataset_entries` (POST core, also the synthetic quality gate) and
`eval_run_stream`. The stream route now emits Ragas progress log events,
persists `generated_answer` per entry, and carries `ragas=` means into
`EvalMetrics`. A failed Ragas preflight now fails the SSE run with an error
event instead of silently skipping.

### Evidence

- `tests/unit/test_eval_ragas_shared_path.py`: AST contract pinning that
  both routes reference all three shared helpers and that the stream route's
  `EvalMetrics` carries `ragas` — the exact divergence class fails loudly.
- Eval unit/API suites green.
- Live post-fix UI re-drive: a fresh 10-question eval from the UI (run
  `epstein-files-1__20260824_214736`) persisted real Ragas —
  faithfulness mean 0.8, answer_relevancy mean 0.656, per-entry
  generated answers and per-entry scores — and the Ragas card renders the
  values (0.8000 / 0.6560) beside MRR 0.6886 in Eval Analysis.

## B9 drive: Eval Analysis — PASS (with defect 5 fixed)

- Eval Dataset UI: added a real entry (Barry Cohen aircraft-management
  question + expected HOUSE_OVERSIGHT path) → "Entry added" toast, count
  201; deleted it through the in-app danger dialog → count exactly 200.
- Run Settings exposes corpus/sample-size/final-k; a real 10-question eval
  ran from the UI (run `epstein-files-1__20260824_211830`): MRR 0.688,
  recall@5 0.8, recall@20 0.9, ndcg@10 0.71, latency p50 4.9s/p95 10.2s.
  (This run exposed defect 5; post-fix Ragas re-drive recorded below.)
- Promptfoo regression launched from the UI (real promptfoo CLI 0.122.0
  via the gateway, luna grader) completed over the FULL published dataset:
  run `epstein-files-1__promptfoo__20260824_214257`, 175/200 passed.
  Failing cards render honest grader verdicts (mostly retrieval misses:
  the expected email absent from retrieved context). Cost-control finding
  (logged, not fixed): the dataset now carries expected answers on all 200
  rows, so one click runs a ~30-minute, several-hundred-LLM-call regression
  with NO sample-size control (the eval runner has one; Promptfoo doesn't).
- Trace Viewer shows the latest trace (canonical id, correlation, root
  span, Grafana/Tempo chips, events). Nits: Policy/Intent/Final-K render
  as em-dashes on an /api/answer trace and Request Cost reads
  "Unavailable" for retrieval-only requests.
- Route nit: `/web/evaluation` (an unknown route) renders an empty "Home"
  shell rather than a not-found redirect.

## B10 drive: Grafana tab — PASS

- Overview: Grafana Command Center with truthful cross-stack chips/cards
  (mode=otel_langfuse, live trace present, Loki reachable, gateway on,
  workflow=legacy_local for the global lane).
- Dashboards: all seven provisioned families listed; embedded TriBrid
  Overview renders live stats; Gateway & Serving renders real series under
  real load (LiteLLM traffic 0.193 req/s with the eval spike, p95 8.75s,
  0% errors). Note: TriBrid Overview's Search Latency p95 stat shows NaN
  when the immediate window has no search traffic (histogram_quantile over
  an empty rate window) — cosmetic, not "No data" during load.

## B11 drive: responsive pass — PASS

At a 1200px window (1333 CSS px at the operator zoom): Chat and Admin both
reflow with `scrollWidth == innerWidth` (no horizontal overflow), the chat
toolbar wraps to two rows, the Settings dock fits, no clipped or overlapped
regions.

## B12: console/network hygiene

Console checked after every flow above (only intentional B5 failures
produced API errors; the fixed nested-button warning was the one app
warning found and is now pinned by a spec). Final sweep across Dashboard,
Retrieval, and Infrastructure loads: zero app console errors.

## Defect 6: exhaustive coverage spec could never load the app — FIXED (suite modernization remains)

Running the full exhaustive Playwright suite (not part of the standard gates;
last exercised before the gateway cutover) found
`coverage.spec.ts` timing out on `.topbar`: every `page.goto` in the spec and
its harness used ABSOLUTE paths (`/dashboard`), which resolve to the origin
root — not the `/web/`-based app — so the spec waited 90s on a 404 page (the
documented `/web/` trap). Fixed: `surfacePath` strips the leading slash and
the three hardcoded gotos are relative. The spec then reached its runtime
preflight, which still carried the PRE-CUTOVER model taxonomy
(`source: local/cloud_direct/openrouter`); updated to the gateway contract
(`ragweld-local` = local lane, any other LiteLLM alias = cloud, providers
derived from alias prefixes).

Reproduced during the suite run: the passing specs leaked a
`ragweld-exhaustive` corpus into the LIVE registry (path pointing at a
deleted temp dir) and left it as the active corpus — the same pollution
class the A3 session cleaned (root cause still an open follow-up). Deleted
via `DELETE /api/corpora/ragweld-exhaustive`; registry back to exactly
epstein-files-1 / recall_default / aurora_acceptance.

Deliberately NOT run: the spec's full mutation loop and its provider-coverage
chat probes — the probe questions are generic meta-questions that predate the
real-queries hard rule, and the loop mutates every control against the live
registry (the suspected source of past test-corpus leakage). The suite needs
a dedicated modernization slice (real domain questions, bounded runtime,
isolated corpus). The other 8 exhaustive specs pass (6 re-verified after the
harness edits).

## Adversarial review (rule 0.2): codex REFUTED the first cut — 2 P1 / 6 P2 / 1 P3

`codex exec` (high effort) reviewed the full session diff. Findings and
outcomes:

- P1 provider-coverage fake-green (harness dropped the API's `override`
  select value; failed probes only logged to the sink) — FIXED:
  `listChatModels` carries `override`, `toModelOverrideValue` uses it, and
  required-provider failures now throw and fail the coverage spec.
- P1 Enter-on-Cancel confirmed destructive dialogs (document-level Enter
  handler) — FIXED: Enter is no longer intercepted; the focused button
  activates natively (confirm is autofocused; Tab/Shift+Tab reaches
  Cancel). Proven interactively: Index Now → Shift+Tab → Enter closed the
  dialog and started no run.
- P2 PMREMGenerator under the explicit WebGPU renderer preference — FIXED:
  the environment effect skips `isWebGPURenderer` (lights still light the
  scene); the WebGL fallback renderer path keeps the environment.
- P2 concurrent confirm dialogs — FIXED: module-level promise queue; one
  dialog at a time, later requests wait.
- P2 role=button still wrapping the Refresh button — FIXED: toggle and
  Refresh are sibling real `<button>`s.
- P2 dialog spec null-swallowing — FIXED: the runs/latest baseline and
  recheck are hard assertions.
- P2 SSE eval silence/cancellation — HARDENED: a log event precedes every
  generation, Ragas judging is per-sample with a progress event and a
  disconnect check between samples (a disconnect abandons at most one paid
  judge call), and attachment flows through the single shared
  `_attach_ragas_scores`. Accepted residual: one in-flight generation or
  judge call itself emits nothing until it returns (bounded by its own
  timeout), and a worker-thread call cannot be interrupted mid-flight.
- P2 AST tests are syntactic — PARTIALLY ACCEPTED: assertions were
  strengthened to pin the single scoring/attachment implementation, but
  they remain divergence guards, not behavior proofs. The behavior proof is
  the live UI run (`epstein-files-1__20260824_214736`, real Ragas means);
  a mock-free automated behavioral test would need the paid judge on every
  test run and is deliberately not added.
- P3 toast accessibility — FIXED: `role=alert`/`aria-live=assertive` for
  errors (8s), `role=status`/polite for the rest.

All fixes re-verified: eval unit/API suites, both regression specs, tsc,
and the interactive keyboard drive above.

## Defect 7 (operator-reported, session 12): Eval Analysis unscrollable + Promptfoo cost trap — FIXED

Reported by the operator after B9's full-dataset run landed: "the whole eval
analysis screen is screwed up you can't scroll down, and those prompts should
be collapsable".

### Root cause

`PromptfooRegressionPanel` rendered every result of the latest run fully
expanded (200 cards ≈ 29,900 px after B9) and was mounted inside the FIXED
header region of `EvalAnalysisTab` — above the `overflow:auto` content area,
inside the tab root's `overflow:hidden`. Measured live: 36,467 px of content
clipped to a 499 px root; the content area got nothing and the clipped header
cannot scroll. The same clipping class also fired on short viewports whenever
the header grew (the 400 px eval LiveTerminal lives there), independent of
Promptfoo.

### Fix

- Only the subtab nav stays pinned; the whole analysis header (title, run
  selectors, Run Settings, terminal, progress) now scrolls with the content.
- The Promptfoo panel moved into the scrollable content flow; per-entry
  results sit in a `CollapsibleSection` (collapsed by default) and each card
  is a closed `<details>` — entry id, verdict, and question scannable,
  response + grader prose behind the disclosure.
- Sample-size dropdown (10/25/50/100/All, default 25) rides the existing
  `EvalRequest.sample_size` field — closes the B9 cost finding where one
  click ran the full 200-row, ~30-minute, several-hundred-LLM-call
  regression. `run_promptfoo` already honored the field; the UI never sent it.
- The promptfoo POST uses `timeout: 0` (the shared axios client's 30 s
  timeout aborted healthy multi-minute runs client-side), and a transport
  failure now starts a bounded recovery poll (15 s cadence, 30 min cap) so a
  server-side run that finishes after an abort still surfaces.

### Evidence

- Regression spec `web/tests/e2e/exhaustive/eval_analysis_layout.spec.ts`
  (no interception): fails on the pre-fix tree (offender: 36,467 px clipped
  into 499), passes post-fix — clipping invariant (no overflow:hidden
  ancestor of the panel may hold overflowing content), reachability of Run
  Eval via real hit-testing, collapse-by-default, per-card `<details>`,
  sample-size control presence/default. Collapse assertions skip loudly (not
  silently pass) when the environment has no recorded run.
- Chrome re-drive with real input: expand section, expand card, all four
  eval subtabs render, zero console errors.
- Sample control proven end-to-end from the UI: run
  `epstein-files-1__promptfoo__20260824_233808`, total 10, 7/3 pass/fail,
  58 s real gateway traffic.
- Full closeout gate green (validators, LiteLLM lockstep, lint, build,
  pytest 1141 passed / 78 skipped).

### Adversarial review (rule 0.2)

codex (high effort) REQUEST CHANGES: 3 P2 / 2 P3. Fixed: stale-corpus
`setRuns` race (current-corpus guard), hidden-run-after-transport-failure
(bounded recovery poll), silent-pass collapse test (explicit `test.skip`
with exact reason), spec type annotation. Refuted with rationale: persisted
collapse-state hermeticity (Playwright runs each test in a fresh context, so
`useUIStore` starts empty). Not refuted by codex: the layout topology and
the sample-size wire path.

Unrelated observation from the drive: a full-dataset promptfoo run started
at 23:15:06Z (before any automation in the session touched the panel) —
consistent with a one-click launch on the old panel; exactly the trap the
default-25 dropdown closes.

## Defects 8–12 (operator-reported, session 12 continuation): five "done" surfaces that weren't

Operator report after the defect-7 fix landed: "grafana benchmarks - empty
0s. set baseline - user cant tell if it does anything. promptfoo prompts -
still not collapsable like i asked. parameters, 290 listed, half of which
don't impact the actual response at all, AND all in one long horrible ux
list. ai analysis - timeout." All five reproduced by driving the real UI
before fixing.

### Defect 8: ML-quality Grafana dashboard was structurally miswired — FIXED

"Eval/Benchmark/Prompt Regressions" queried reranker-TRAINING counters
(`tribrid_reranker_eval_runs_total`, six identical "eval runs" 0-tiles) and
a search-latency histogram "proxy" (NaN on quiet windows). No eval-analysis,
promptfoo, or benchmark metric existed at all. Fix: seven new label-less
metrics (module contract forbids corpus labels) emitted at the three save
points — eval runs counter + last top1/topk gauges (via a
`_record_eval_run_metrics` called once per run; `_save_run` runs twice per
run for lineage attachment, which double-counted in the first cut — codex
P1), promptfoo counter + pass-ratio gauge, benchmark counter + avg-latency
gauge. Label-less instruments expose real zeros from process start so 24h
`increase()` windows can't miss the first run. Dashboard rewired to those
metrics; reranker panels kept under honest titles.

### Defect 9: "Set baseline" wrote lineage aliases with zero feedback — FIXED

`useNotification` stores messages in component-local state; `LineageMeta`
(and AgentTraining's TrainingStudio) never rendered that list, so alias
writes, run starts, cancels, and promotions all reported into the void.
Proven live: the operator's own baseline/current clicks (00:29/00:31Z) had
silently succeeded, and an automation misclick on SET PROMOTED silently
created an alias (deleted; store restored). Fix: both components use the
global `showToast`; `LineageMeta` now loads alias targets, marks the alias
pointing at the current bundle (`✓ current`, aria-pressed, disabled), lists
`alias → bundle` assignments, and distinguishes "no aliases set" from
"alias lookup failed" (codex P2).

### Defect 10: 290-key config snapshot rendered as one flat "OTHER" list — FIXED

`loadEvalKeyCategories` was a stub returning `{}` ("everything groups as
Other" was literally its comment) and the badge called them "retrieval
keys" while including `GRAFANA_DASHBOARD_SLUG` and alert settings; the diff
view attributed "performance change" to Grafana dashboard picks. Fix:
deterministic prefix classifier (`web/src/utils/configKeyCategories.ts`,
first-match rules, unmatched keys land in the response tier so a new
retrieval knob is never filed as ignorable) rendering two tiers — "Affects
retrieval & answers" grouped by domain, and a collapsed "Operational / UI"
tier. "Cannot affect results" claims are restricted to observability/UI/
training categories; data-store wiring (`POSTGRES_URL`, Neo4j) is labeled
"infra wiring" and never waved off (codex P2). Diff rows in both scalar and
array branches carry the tier chip.

### Defect 11: AI Analysis died at the shared 30s axios timeout — FIXED

Reproduced live ("Error: timeout of 30000ms exceeded"). The backend bounds
the LLM call at `generation.gen_timeout` (600s) and the local lane
routinely needs minutes. Client timeout raised to the server budget plus
margin (660s; bounded, not infinite, so a dead connection still fails —
codex P3). Same class fixed for the promptfoo POST (60 min bound).

### Defect 12: prompts still not collapsible — FIXED (correct surface this time)

The defect-7 fix collapsed Promptfoo result cards; the operator's "those
prompts" also meant the System Prompts subtab — 18 fully-expanded prompt
bodies. Every prompt card is now a collapsed `<details>` (label,
description, char count in the summary; body holds Edit/Reset + content;
summary toggle suppressed while editing; deep links open the card before
scrolling). Promptfoo results additionally group failures-first (Failed
open, Passed collapsed).

### Verification

- Extended `eval_analysis_layout.spec.ts` (no interception): prompt-card
  collapse/expand via real click, failures-first grouping, config-tier
  layout with named-key assertions (BM25/VECTOR under response, GRAFANA
  under operational, POSTGRES_URL under infra — never "ignorable").
- Chrome drives with real input on every fixed surface; live post-restart
  metric proof for benchmark/eval/promptfoo tiles.
- codex (high effort) REQUEST CHANGES on the first cut: 2 P1 / 5 P2 / 3 P3
  — all acted on (double-count, label contract, false "cannot affect
  results" for infra keys, alias-error masking, spec depth, bounded
  timeouts, array-row chips, deep-link reveal) except one accepted
  residual: the tier spec still skips loudly on corpora without eval runs,
  and `or vector(0)` still renders 0 when the scrape pipeline itself is
  dead (documented in the dashboard's text panel).

### Defect 13 (found while verifying 8–12): Ragas scoring died on langchain's process-wide client cache — FIXED

Eval runs in restarted API processes failed at scoring with
`APIConnectionError: Connection error`; the buried cause was
`RuntimeError: <asyncio.locks.Event> is bound to a different event loop`.
`langchain_openai` lru_caches ONE async httpx client per (base_url, timeout)
process-wide (`_client_utils._cached_async_httpx_client`); ragas runs each
scoring call on its own event loop, so a cached client born on an earlier
loop poisons every later call. Fix: `score_samples` builds explicit per-call
`http_client`/`http_async_client` for the judge, bypassing the cache; the
sync client is closed in a finally (the async pool dies with ragas's loop).
Proven: two sequential cross-loop scorings in isolation, then a full
in-server UI-path eval run (`epstein-files-1__20260825_013817`, top1 0.6,
topk 0.8, faithfulness 0.717, answer_relevancy 0.752) with
`tribrid_eval_runs_total` at exactly 1.0 (single-increment fix live).

### Final live proof (dashboard)

Eval Runs (24h) 1.00, Promptfoo Runs 2.00, Benchmark Runs 3.02 (increase()
across counter resets), Latest Top-1 60%, Pass Ratio 90%, Benchmark Avg
Latency 28.6 s, reranker training panels honestly at 0 — all real runs, all
rendered in the embedded Grafana dashboard. AI Analysis generated a real
comparison summary via ragweld-local (the >30 s generation that always died
at the old client timeout).

### Process notes (for future drives)

- Navigating the tab or triggering Vite HMR (editing frontend files) while
  an eval stream runs disconnects the SSE and the disconnect hardening
  abandons the run — two paid runs lost that way this session.
- A backend relaunched outside `start.sh` must replicate its env: sourced
  `.env`, gateway exports, and a node ≥22.22 PATH — promptfoo and the
  Ragas judge both fail closed (honestly) without them.

## B8 drive: Training Center — PARTIAL (operator constraint)

The Learning Agent Studio renders truthful control-plane state (Flyte
Console and MLflow Tracking links both live/200, run history with the P0-2
run's HUD: mlx_qwen3, Qwen3-4B base, 24.7s, promoted artifact lineage), and
the Neural Visualizer fix covers this studio too (trajectory renders).
NOT driven: starting/cancelling training runs — training executes on the
host MLX backend and the operator's hard rule (2026-08-23, after two
machine crashes) forbids MLX training runs or local model loads without the
operator present. Re-drive run-start/cancel in an operator-present session.
