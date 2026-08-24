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

## Flow drives (B6–B12)

Pending below; updated as each flow completes.
