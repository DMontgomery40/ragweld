# Curious-user browser drive — 2026-08-25 (session 13b)

Method: the real app in Chrome (Vite 55173 → API 58012), driven as an operator
who has never seen it: every tab and subtab in order, scrolled top to bottom,
every panel expanded, settings changed and applied, refreshed and re-checked,
real Aurora questions in Chat. Isolated corpus `ragweld-drive-81854` (acceptance
fixture, deterministic embeddings, cheap paid alias, own log/triplets files) is
the active corpus so config tweaks are scoped and reversible. Console and
network errors are read on every surface.

Findings are numbered as they are met; each gets a status (OPEN / FIXED /
PRODUCT-DECISION) before the session closes.

## Findings

### Get Started (`/start`)

- **F1 (P3, UX/legibility)** — Every wizard step change renders the new step
  dimmed for 1–3 s while the step indicator has already moved (all five step
  panels are mounted at once; the cross-fade is slow enough that a screenshot
  1 s after Next shows unreadable content under the wrong dot). On a 93-PPI
  display this reads as broken. Status: OPEN.
- **F2 (P3, terminology)** — Step 4 subtitle "Try these Golden Questions" uses
  the banned term (`.claude/rules/terminology.md`: eval_dataset). Status: OPEN.
- **F3 (P2, honesty, verify on Learning Agent)** — Grafana Command Center on a
  fresh corpus labels the training lane `workflow=legacy_local` / "Legacy local
  lane" and says "runs use the local training lane without an orchestrator",
  although Flyte orchestration is live (session 4) and "legacy" naming is
  banned on `main`. Status: OPEN.
- **F4 (P1, dead surface)** — The onboarding wizard is a mock. In
  `web/src/components/tabs/StartTab.tsx` only the step dots, Next/Back and Done
  (`navigate('/dashboard')`) have handlers. Everything else is a vanilla-JS-era
  element with an `id`/`data-*` hook and no code behind it: "Use a Folder" /
  "Use a GitHub Repo" cards, Folder/GitHub mode tabs, Browse..., the path /
  URL / branch / token inputs, the Build Your Indexes progress/log, the three
  golden-question Ask buttons and their trace links, "Save to Eval Dataset",
  the three tuning sliders (the "Settings to Apply" box never fills), "Save as
  a Project", "Run a Tiny Evaluation", the "Have questions?" Ask, the three
  question pills, and "Open full Chat →" (`href="#"`). Reproduced live: a real
  question typed into the help box + Ask → no request, no navigation, no error.
  A first-time operator's first screen does nothing it promises. Replacement
  rule: wire it to the real APIs or remove it. Status: OPEN.

### Dashboard / System Status (lead's notes; agent A inventories the tab in full)

- **F5 (P3, honesty flash)** — On navigation the docked Grafana Command
  Center shows `mode=unknown`, "Grafana missing", "LiteLLM off", "Gateway not
  active", "Not indexed" for ~3 s before its refresh lands. Wrong statuses are
  shown instead of a loading state. Status: OPEN.
- **F6 (P2, wrong number)** — Storage Requirements tiles read `CHUNKS 0 B`,
  `POSTGRES TOTAL 0 B`, `NEO4J STORE 0 B`, `KEYWORDS 0` for a corpus with 4
  indexed chunks; only the Qdrant estimate (6 KB) is non-zero.
  `IndexStats.storage.postgres_total_bytes` is 0 (`server/api/index.py:702`).
  Status: OPEN.
- **F7 (P2, honesty)** — Embedding Configuration tile says
  `BAAI/bge-small-en-v1.5 · 384 · float32` and
  `GET /api/index/<id>/stats` reports `embedding_provider=huggingface`,
  `embedding_model=BAAI/bge-small-en-v1.5` for a corpus whose config is
  `embedding_backend=deterministic`, `embedding_model=text-embedding-3-large`,
  `embedding_type=huggingface` — three different stories for one corpus; the
  deterministic backend advertises itself as a real HF model. Status: OPEN.
- **F8 (P2, missing data)** — "Top Folders (Last 5 Days): No recent indexing
  metrics available" right after a completed index run;
  `GET /api/index/<id>/runs/latest` has `files_processed: null`,
  `chunks_created: null` although `total_chunks: 4`. Status: OPEN.

## Master inventory (merged, deduplicated, ranked)

Five drive agents (A shell+dashboard, B chat, C grafana/benchmark/eval, D rag,
E infrastructure+admin) plus the lead's own pass (F1–F8) produced 114 raw
findings; identical root causes seen from several surfaces are merged below
with every source id kept. Full per-surface reports follow as appendices —
they are the inventory of record; this table is the triage view. Nothing was
fixed during the drive (operator instruction).

### P1 — blocks or misleads the operator

| # | Finding | Sources | Where |
|---|---|---|---|
| M1 | Onboarding wizard is a mock: only step dots / Next / Back / Done are wired; folder/GitHub cards, path inputs, index step, golden-question Asks, Save to Eval Dataset, sliders, Save as a Project, Run a Tiny Evaluation, help Ask, pills and "Open full Chat" do nothing | F4 | `/start`, `web/src/components/tabs/StartTab.tsx` |
| M2 | Global settings search renders blank result rows, Enter does nothing, and every keystroke runs a RAG `/api/search` against the active corpus (queries then appear in Monitoring traces) | F-A-1 | topbar, `web/src/hooks/useGlobalSearch.ts:47-186`, `GlobalSearch.tsx:154` |
| M3 | Docked Grafana Command Center is not its own scroll container: the whole window scrolls (≈5000 px), the shell disappears, main and dock scroll independently | F-A-2, F-C-9 | dock, `web/src/styles/main.css:862-866` |
| M4 | Light theme: the docked deck keeps its dark gradient but flips text tokens dark → title, 20 chips, buttons and card titles unreadable (~1.2:1) | F-A-3 | dock, `OperatorDeck.tsx` |
| M5 | A non-forced re-index of an already-indexed corpus always fails: `start_index` returns cached stats without writing the staging corpus, then `promote_staging_index` raises "Staging corpus not found"; UI reports "Connection lost" and a permanent error run (reproduced independently by A at 18:36 and D at 18:45) | F-A-4, F-rag-2 | `server/api/index.py:771-772, 1555`, `server/db/postgres.py:1806-1807`, Dashboard Run Indexer + RAG Index Now |
| M6 | Chat opens on a thread scoped to `recall_default + epstein-files-1` while the app's active corpus is the Aurora corpus (unchecked in Sources); a new operator's first question goes to the wrong corpus | F-chat-1 | `ChatInterface.tsx:1140-1150`, `chatSessions.ts:123-125`, `chat.default_corpus_ids` |
| M7 | Fusion weights: a single-field edit is re-normalised server-side, all three inputs show 17-digit floats, and the typed value can never be restored from the UI (0.4 → 0.4545…, back to 0.4 → 0.4230…) | F-rag-3 | `FusionConfig.validate_weights_sum_to_one`, `RetrievalSubtab.tsx:969-1010` |
| M8 | Benchmark runs raw generation with `context_chunks=[]` and never says so: both models answered the Aurora question from world knowledge | F-C-1 | `server/chat/benchmark_runner.py:61-67`, `/benchmark` |
| M9 | Every "Search Rate / Latency / Success" panel counts only `/api/search`; chat retrieval never increments `SEARCH_REQUESTS_TOTAL` / `SEARCH_LATENCY_SECONDS`; On-call Overview p95 renders a giant NaN | F-C-2 | `server/api/search.py:83`, `server/main.py:307-309`, dashboards |
| M10 | Infrastructure → Monitoring alert thresholds target `/api/monitoring/alert-thresholds` (no such route anywhere): every input empty, Save always 404 | F-E-1 | `useAlertThresholdsStore.ts:93,131`, `MonitoringSubtab.tsx:32-57` |
| M11 | "Open Grafana Dashboard" / "Open Prometheus" buttons target :3000 / :9090 (nothing listens; real ports 3301 / 59090, which the deck above already links); Prometheus is also Grafana's default datasource although Mimir is the locked stack | F-E-2, F-C-11 | `Infrastructure/MonitoringSubtab.tsx:304,316`, `GrafanaConfig.tsx:444-458` |
| M12 | MCP subtab: `/api/mcp/http/status|start|stop|restart` and `/api/mcp/test` do not exist; "HTTP status unavailable" sits under a tile that says HTTP is running; "Run test" shows "Failed to load MCP status" | F-E-3 | `MCPServerService.ts`, `useMCPServer.ts:104-106`, `MCPSubtab.tsx:115` |

### P2 — wrong or broken, workaround exists

| # | Finding | Sources | Where |
|---|---|---|---|
| M13 | "Apply All Changes" is decorative on Chat Settings, Grafana Config, Eval Run Settings, all RAG subtabs and the dock Config: every control auto-persists on change (`patchSectionDebounced`), the button only lights after a failed PATCH, and a Dashboard-family tile click silently writes `ui.grafana_dashboard_uid` | F-chat-4, F-C-4, F-C-13, F-rag-6, F-A-10 | `web/src/hooks/useConfig.ts:78-121`, `useApplyButton.ts:35-38` |
| M14 | Helpful / Not helpful are 10 px black-on-dark at 0.78 opacity — effectively invisible; this is the reranker feedback control | F-chat-2 | `ChatInterface.tsx:784-841` |
| M15 | `ui.chat_streaming_enabled` has no consumer: request still streams, badge/Stop still show | F-chat-3 | `ChatSettings.tsx:83,652` |
| M16 | Stop mid-stream leaves a permanent "Streaming" partial message with raw markdown, no citations, feedback still offered | F-chat-6 | chat |
| M17 | Citation "Open in editor" links are `vscode://file/<relative>` without the corpus root | F-chat-5 | `ChatInterface.tsx:108-110` |
| M18 | Sources list mixes RRF corpus scores (~0.04) with recall similarity (~0.7) in one column; recall memories outrank the grounding doc, no preview | F-chat-8 | `ChatInterface.tsx:748-782` |
| M19 | gpt-4.1-nano fabricated a crontab "from the corpus" with normal citations/confidence (grounding failure surfaced with no warning) | F-chat-7 | chat prompt / model choice |
| M20 | Dashboard → Monitoring "Recent Alerts" → `GET /api/webhooks/alertmanager/status` 404 ("Failed to load"; acceptance residual 4) | F-A-5, F-E-17 | `web/src/api/dashboard.ts:75` |
| M21 | "Top Folders (Last 5 Days)" can never show data (`setTopFolders([])` is the only setter); run summaries carry `files_processed: null`, `chunks_created: null` | F8, F-A-6 | `SystemStatusSubtab.tsx:22,90,561`, index run summary |
| M22 | Storage tiles: CHUNKS / POSTGRES TOTAL / NEO4J 0 B for a corpus with 4 chunks; Storage subtab shows "4 points · 0.1% of total" (a count as a byte share) | F6, F-A-7 | `server/db/postgres.py:812-830`, `server/api/index.py:702` |
| M23 | Embedding tile / index stats claim `huggingface / BAAI/bge-small-en-v1.5` for a `deterministic` corpus whose config says `text-embedding-3-large` (three stories); the index estimate dialog says 543 tokens / 2 chunks vs the real 443 / 4 | F7, F-rag-19 | index stats contract, `IndexingSubtab.tsx:661-665` |
| M24 | HEALTH pill: no popover/details, silently re-polls, shows "OK" while `/api/health` says postgres/neo4j `unknown` | F-A-8 | `App.tsx:194` |
| M25 | Dock "Dashboards" subtab hides the 7-dashboard catalog behind "Grafana embedding is disabled" | F-A-9 | dock |
| M26 | LEARN, Dock Current and Swap drop `corpus=` from the URL | F-A-11 | shell |
| M27 | Grafana template variables (corpus_id/run_id/model/…) are declared on all six `ragweld-*` dashboards but referenced by no panel; the iframe never passes `var-corpus_id` | F-C-3 | dashboards JSON, `GrafanaDashboards` iframe src |
| M28 | Benchmark forgets results/lineage/selection on reload although runs are persisted; default selection is the first two catalog rows; no cost/tokens despite `include_cost_tracking=true`; `model_id`/`model_name` null | F-C-5, F-C-6 | `BenchmarkTab.tsx:413-466`, `/api/benchmark/results` |
| M29 | Eval Dataset form has no expected_answer / evidence / tags fields, so Promptfoo skips every entry; no import/export | F-C-7 | `eval?subtab=dataset` |
| M30 | Trace Viewer is not corpus-scoped (single hard-coded "All corpora" option; shows whatever request was last in the process); "Policy: — • Intent: — • Final K: —" placeholders are permanent on both the Trace subtab and Retrieval's Trace Preview | F-C-8, F-rag-18 | `TraceViewer.tsx:359`, `useTrace.ts:25-26`, `RetrievalSubtab.tsx:2220-2240` |
| M31 | Six of twelve "Open surface" chips land on ingestion endpoints or error pages (OTLP 405, Tempo 404, LiteLLM/vLLM `/v1` Not Found, Faro collector, Langfuse sign-in / no access) | F-C-10 | `OperatorDeck.tsx` links |
| M32 | Eval/Benchmark/Prompt Regressions dashboard shows process-wide gauges as "0%" and global run counters under a corpus-scoped page | F-C-12 | dashboard exprs, label-less gauges |
| M33 | Retrieval UI min/max exceed Pydantic `ge`/`le` on 12+ controls; a 422 shows as "Request failed with status code 422" with no field name while UI and API disagree | F-rag-4 | `RetrievalSubtab.tsx` bounds vs `RetrievalConfig` |
| M34 | Retrieval exposes tunables nothing reads (`topk_dense`, `topk_sparse`, `bm25_weight`, `rrf_k_div`, `langgraph_final_k`, `hydration_mode`, `graph_storage.graph_search_top_k`), each duplicating a live field on the same page | F-rag-5 | `RetrievalSubtab.tsx:150-180`, config model |
| M35 | Learning Agent Studio "Start Run" is pushed outside the panel at the default dock layout (only "THIS CORPUS \| AL" visible) | F-rag-1 | `AgentTraining/TrainingStudio.tsx:1846-1856` |
| M36 | Synthetic Lab Judge Model select overflows and puts a horizontal scrollbar on the RAG pane | F-rag-7 | `SyntheticLabSubtab.tsx:63-72, 466-483` |
| M37 | Learning Reranker Studio shows "Request failed with status code 404" as the Recommended Metric when the corpus has no eval dataset | F-rag-8 | `RerankerTraining/TrainingStudio.tsx:2042`, `server/api/reranker.py:2664` |
| M38 | Graph Explorer on this corpus: 0 entities/relationships/communities; hint names a toggle on another page and omits that a Force re-index is required (a plain re-index fails, M5); no "no matches" state for a search; Filters expand to empty headings; Expand (fullscreen visualizer) disabled with no reason; inline legend lacks `concept` | F-rag-9, F-rag-10, F-rag-11 | `GraphSubtab.tsx:677-681, 984-1021, 1168`, `useGraph.ts` |
| M39 | Docker "Logs" shows "No logs available." for stderr-only containers (Loki, Postgres): endpoint returns only stdout | F-E-4 | `server/api/docker.py:426` |
| M40 | Unknown routes (`/web/evaluation`, `/web/nonsense`) render a blank pane with breadcrumb "Home"; no catch-all | F-E-5 | `TabRouter.tsx` |
| M41 | Admin Advanced marks 101 fields `global` while Basic's save path is always corpus-scoped (`withCorpusScope`) | F-E-6 | `configControlPlane.tsx:404-408`, `web/src/api/config.ts:29-31` |
| M42 | Postgres DSN with embedded password is a cleartext text field and is returned by `GET /api/config`, while Neo4j's password is env-only | F-E-7 | `PathsSubtab.tsx:111-128` |
| M43 | Recall gate silently overrode the configured default intensity (light → deep) with no visible reason | F-chat-10 | `server/chat/retrieval_gate.py:131-234` |

### P3 — cosmetic, legibility, terminology, copy

| # | Finding | Sources |
|---|---|---|
| M44 | Wizard step cross-fade leaves the new step unreadable for 1–3 s while the indicator has moved | F1 |
| M45 | Command Center first paint shows false negatives ("Grafana missing", "LiteLLM off", "Not indexed", `mode=unknown`) for ~3 s on every navigation; Overview fan-out (11 calls) fires 4× per mount; ~194 `/api/` calls in 10 idle minutes | F5, F-A-19, F-C-18, F-C-19 |
| M46 | "legacy" on live features everywhere: `workflow=legacy_local` / "Legacy local lane" / "Target lane: Legacy local" (dock, deck, Learning Agent Studio, control-plane API `lane` literal), "Legacy suffix prompts" + "falls back to the legacy base+suffix" (Chat Settings, a runtime fallback path), "Base prompt (legacy)" ×3 (Eval Prompts), "Greedy — Legacy fixed-char windowing" (Indexing), 19 glossary rows | F3, F-A-12, F-chat-9, F-C-15, F-rag-12, F-rag-14, F-E-13 |
| M47 | Other banned terms in copy: "Golden Questions" (Start), "Learning Ranker" nav/breadcrumb/help, `semantic_cards` recipe id + `semantic_cards_jsonl` artifact kind, "incident cards" / "integration card" (deck, Admin), 22 "card" glossary rows, `GOLDEN_PATH` glossary row, "REPO" column header, "Active Repository … repos.json" tooltip, "Cohere Rerank Calls/min" threshold, Netlify API key secret | F2, F-A-13, F-rag-13, F-E-13, F-E-16, F-C-16 |
| M48 | Code-repo framing on a document corpus: chat placeholder/empty-state/suggestion chips, "database repositories/snippets" in system prompts and answers, Layer Weights (GUI/Retrieval/Indexer/Vendor), Path Boosts `/gui,/server`, Intent matrix, default exclude dirs, "📦 Code Indexing", Help's `hybrid_alpha` (field does not exist) and "Admin → General" (subtab does not exist) | F-chat-14, F-C-16, F-rag-21, F-A-13 |
| M49 | Legibility floor: 334 text leaves at 9 px and dozens at 10 px on System Status; deck eyebrows 10 px with alpha; nav links 3.96:1 and the ACTIVE nav entry 3.72:1; 11–13 px muted helper text across Chat, Retrieval, Graph, Infrastructure, Eval; opacity on text (tagline 0.6, feedback 0.78, disabled Apply 0.6, Swap 0.5); Light-theme glossary counts 1.2:1 | F-A-17, F-chat-11, F-chat-12, F-C-17, F-rag-16, F-E-12 |
| M50 | Layout: Qdrant generation id overflows its tile; "0 nodes • 0 edges" wraps into a 33 px column; Benchmark 39,000 px model list with no filter and page-level scroll; Loading spinner over the Run button; corpus modal horizontal overflow stripe; Infrastructure subtab keeps the previous scroll offset; docker logs "modal" trapped by `.tab-content { transform }` (Escape/focus/title/tail all wrong); tooltip persists over a modal; dock toast covers the HEALTH pill; chat document-level scroll clips the header after Trace | F-C-14, F-rag-11, F-C-24, F-C-22, F-A-17, F-E-10, F-E-11, F-C-23, F-A-18, F-chat-17 |
| M51 | Feedback gaps: Copy and Export give no confirmation; toggle saves in Admin give no "Saved"; Ops log wiped on subtab switch after a failed run; "Jump to latest" on an empty thread; Escape does not close the Sources dropdown; focus leaves the composer after send; assistant header says "LiteLLM", never which model; `ragweld-local` selectable with no state hint | F-chat-15, F-E-9, F-A-14, F-chat-16, F-chat-18, F-chat-13, F-chat-22 |
| M52 | Small defects: Data Quality placeholders render a literal `\n`; disabled "Bypass if Images" toggle painted enabled and flippable without persisting; Force reindex checkbox repeated in four cards; Prompt-set tile truncates to `prompt_set__`; incident lineage "X -> X"; Eval Analysis chevron inverted; `GET /api/eval/results` 404 on every empty-state load; MCP tile links to `/mcp/` (406 in a browser); `grafana?subtab=dashboard` silently redirected; two option lists for the same dashboard setting; Graph "Max hops" is UI-local but looks like config; Storage calculator `?` marks are 10 px native titles; "Total corpora" tooltip shows the Active-corpus text; Sources/Benchmark settings sections are placeholders; per-field Admin saves refetch the 451-field registry + readiness | F-rag-15, F-rag-17, F-rag-19, F-C-20, F-A-20, F-C-13, F-C-21, F-E-14, F-C-25, F-rag-10, F-A-16, F-A-15, F-chat-20, F-E-8 |
| M53 | React warning: `key` spread into `<a>` props in the markdown link renderer (once per chat load) | F-chat-21 |
| M54 | Corpus switcher exposes a one-click "Delete corpus" trash button on every row including the active one (not exercised) | F-A-21 |

### Works (so this is not only a complaint list)

Every service tile, container, port and uptime string matched the API; the
Command Center chips/links/integration matrix matched `/api/observability/*`;
chat answered seven of seven answerable Aurora questions correctly with
citations and refused the unanswerable one; feedback landed in the reranker
log; threads, history, delete-confirm, markdown, tables and code blocks work;
Grafana embed, all 11 dashboards and both datasources answer; Tempo trace
deep link renders the chat trace; Benchmark ran and "Set baseline" wrote a
real alias; dataset CRUD, prompt edit/restore, Admin Basic/Advanced/Raw/
Dependencies round-trips all persisted and restored with zero global drift;
dockview panels drag/close/reset; the index contract lock and its banner
behave; console was clean on every surface except the one React warning.

### Coverage

Every nav entry and every declared subtab was visited, scrolled to the bottom,
expanded and exercised within the hard limits (no training / model loads /
service lifecycle / paid multi-minute runs / corpus switches / secrets). Not
exercised: the graph visualizer's node/zoom/pan controls (0 entities on this
corpus — see the final section), Learning-mode reranker application (would
load MLX), Run Eval / Promptfoo / synthetic generation / AI analysis, Delete
corpus / Delete index, Raw section replace, dock Settings model/secret writes.


## Graph visualizer (lead's drive, last — after a force re-index with the semantic KG on)

Setup: `graph_indexing.semantic_kg_enabled=true`, `semantic_kg_mode=llm`,
`semantic_kg_llm_model=openai.gpt-5.6-luna`, `graph_storage.include_communities=true`,
then `POST /api/index` with `force_reindex=true` on the drive corpus (4 chunks →
4 paid extraction calls, ~40 s). Result: 46 entities (26 concept, 6 org, 6
event, 4 person, 4 location), 45 relationships (37 `associated_with`, 5
`located_in`, 2 `participated_in`, 1 `owns`), **1 community**. Then
`rag?subtab=graph`: inline visualizer, community click, entity click, Expand
(fullscreen), scroll-zoom, drag-pan, node click, Esc, Table view, search.

- **G1 (P1)** — Community detection produced a single bucket holding all 46
  entities, and its id is the STAGING corpus id:
  `__staging__ragweld-drive-81854__20260825T185404_e1d5549a5c:(root)` with
  summary "Entities in '(root)'" (`GET /api/graph/<id>/communities`). The
  staging→promoted rename did not touch community ids, and "(root)" is a
  hierarchy placeholder, not a Louvain community; the UI shows it as
  "(root) · 46 members · level 0". The operator's "no communities" is correct
  in substance. Status: OPEN.
- **G2 (P1)** — Inline visualizer for the whole corpus renders "46 nodes • 0
  edges": 45 relationships exist but the full-graph view draws none (only a
  selected entity's neighborhood shows edges). Status: OPEN.
- **G3 (P1)** — Fullscreen ("Expand"): the canvas keeps the inline panel's
  size (`CANVAS 227×520` measured while the overlay was open) so the graph is
  a thumbnail in the middle of a 1000×600 overlay; **scroll-zoom does nothing**
  (5 wheel ticks, identical frame), drag-pan works, **node click does nothing**
  (no details, no selection change), only the hub is labelled ("1 hub
  labeled"), and the hint promises "Scroll to zoom • Click node for details".
  `GraphSubtab.tsx:1232-1233` sizes the fullscreen canvas from
  `fullscreenSize`, which evidently never updates from the overlay. Status: OPEN.
- **G4 (P2)** — Fullscreen legend is the code-graph taxonomy
  (`function / class / module / variable / concept`, `GraphSubtab.tsx:1164-1168`,
  colour switch at `:305-311`) while the corpus entities are
  `person/org/location/event/concept`; the inline legend has person/org/…
  but no `concept` (26 of 46 entities). Colours in fullscreen therefore mean
  nothing for this corpus. Status: OPEN.
- **G5 (P2)** — Clicking the community row does nothing visible (no subgraph,
  no member list, no selection state), although the tip says "Select an entity
  (or a community) to render a subgraph." Status: OPEN.
- **G6 (P2)** — Entity duplication: "KestrelDB" ×2 and "Pelican gateway" ×2
  (once `org`, once `concept`) in `GET …/entities`; the Aurora hub's
  neighborhood lists "Aurora Tidal Observatory (org)" twice and the fullscreen
  view draws two labelled "Aurora Tidal Observatory" nodes. Extraction runs per
  chunk and never merges same-name entities across chunks/types. Status: OPEN.
- **G7 (P2)** — Every relationship shows "No provenance"; the extraction
  prompt asks for `evidence_text` and `confidence` per relation, but
  `GET …/entity/<id>/relationships` returns `properties: {}` and `weight: 1.0`
  for all 45 — evidence is dropped before Neo4j. Status: OPEN.
- **G8 (P2)** — After a search, the Details → Relationships list degrades from
  names to raw chunk-position ids (`observatory-overview.md:1-15:0:0 ─ owns →
  observatory-overview.md:1-15:0:3`) because endpoint names are looked up in
  the currently listed entities; "File: —" although the id embeds the file
  path. Entity ids themselves are chunk positions (`<file>:<lines>:<chunk>:<n>`),
  which the UI exposes as identity. Status: OPEN.
- **G9 (P3)** — Inline visualizer panel is 130 px wide beside the dock; nodes
  are unlabelled dots; "46 nodes • 0 edges" wraps into a 33 px column
  (F-rag-11); search results keep the previously selected entity as a stale
  extra row ("2 shown" but three rows). Status: OPEN.
- Works: `zoomToFit` on load, entity click → neighborhood (6 nodes / 6 edges
  with real names), Table view Details (name, type, description from the
  extraction), Esc closes fullscreen, search filters by name, no failed API
  calls, no console errors.

Master-table additions: G1/G2/G3 join the P1 list (M55–M57), G4–G8 the P2
list (M58–M62), G9 the P3 list (M63).

---

# Appendix — per-surface reports (verbatim)


---

## Report A — A-dashboard-shell.md

## A — Shell + Dashboard — curious-user drive inventory (2026-08-25)

Drive corpus `ragweld-drive-81854` (never switched). Browser viewport 2174x1476 CSS px at operator zoom 0.67 / dpr 0.9. Evidence screenshots in `A-shots/`.
Baselines pulled with curl against 127.0.0.1:58012 at 12:24–12:41 PM:
- `/api/observability/status` → `mode=otel_langfuse`, `severity=info`, `slo_state=unknown`, 17 components (flyte/mlflow/unsloth/opencost `enabled=false`), `incident_count=0` at start (later 1–2 as other agents ran prompts/benchmarks).
- `/api/observability/catalog` → 7 dashboards (oncall_overview default, gateway_serving, retrieval_indexing_graph, training_workflow, eval_benchmark_prompt_regressions, cost_capacity, frontend_rum), all with `orgId=1` Grafana links.
- `/api/index/ragweld-drive-81854/stats` → 4 files / 4 chunks / 443 tokens / huggingface BAAI/bge-small-en-v1.5 / 384-d / last_indexed 18:17:41Z.
- `/api/index/ragweld-drive-81854/runs/latest` → at 12:24: run `20260825T181736_5aa29d863c` status `complete`; at 12:36: run `20260825T183630_934311bec4` status `error` (see F-A-4).

### Surfaces visited
- Shell (every page): left nav (9 entries, hover/active measured), topbar (LEARN, global search palette with "fusion"/"reranker"/"top_k", Auto/Dark/Light theme select round-trip, HEALTH pill), bottom `#save-btn`, dock header (Settings, Dock, Dock Current, Choose…, Swap, Clear — all pressed; docked Dashboard/System Status via Choose…, cleared, re-docked Grafana Overview), docked Grafana Command Center (Overview scrolled to bottom, Dashboards, Incidents, Config subtabs; every chip/link inventoried; Config checkbox toggled + reverted).
- `dashboard?subtab=system` — 6 status tiles, 3 `?` tooltips hovered, ↻ Refresh Status, Quick Actions Refresh Status / Reload Config / Corpus modal (opened, inspected, closed with Esc, NOT switched) / Run Indexer (clicked; failed), embedding/costs/storage panels, Top Folders; scrolled to bottom (1629px).
- `dashboard?subtab=monitoring` — 3 panels (Monitoring Logs, Recent Query Traces, Loki Log Aggregation); scrolled to bottom (1363px). No dock/current controls, chat-source toggles, recall-intensity or threshold controls exist on this subtab.
- `dashboard?subtab=storage` — 6 storage tiles + total, "TriBrid RAG Storage Calculator Suite" (Storage Requirements + Optimization Planner, ~20 inputs), Storage Optimization Tips; scrolled to bottom (2952px); 18 `?` marks (title-attribute tooltips, not glossary).
- `dashboard?subtab=help` — Quick Start, Key Concepts (6), Common Tasks (5), External Resources; scrolled (1986px).
- `dashboard?subtab=glossary` — 428 entries, 7 category chips, search box used ("fusion" → filtered set); scrolled to bottom (97,990px tall list).

### Findings

#### F-A-1 — Global settings search returns blank result rows; Enter does nothing
- Severity: P1
- Surface: shell topbar — "Search settings (Ctrl+K)" → command palette "Search all settings… / Search through all 600+ settings"
- What I did: focused the topbar box (palette opens), typed `fusion`, then `reranker`, then `top_k`; pressed Enter on the first.
- What happened: each query renders 3 result rows that are completely empty (DIVs with two empty children, `textContent == ""`); Enter closed the palette and did not navigate. No "No results" state either. Console: none. Failed API: none — but each keystroke POSTs `/api/search` against the drive corpus (the queries then show up in Dashboard → Monitoring "Recent Query Traces" as `fusion`, `reranker`, `top_k` with repo `ragweld-drive-81854`).
- Expected: setting names/labels with the section they live in; Enter jumps to the field. Settings search should not run a RAG retrieval against the active corpus, or if it does, results need a label.
- Evidence: `A-shots/A-global-search-blank-rows.jpg`; `web/src/hooks/useGlobalSearch.ts:47-81` builds the settings index only from `.settings-section` elements rendered on the current route (none on Dashboard), then `:160-186` maps `/api/search` matches to `{file_path,start_line,…}` with no `label/name/title`, and `web/src/components/Search/GlobalSearch.tsx:154` renders `result.label || result.name || ''` → blank.

#### F-A-2 — Docked Grafana Command Center is not scrollable; the whole window scrolls and the shell disappears
- Severity: P1
- Surface: shell — right-hand DOCK with "Dock: Grafana — Overview"
- What I did: measured layout; wheel-scrolled 10 ticks over the dock.
- What happened: `.obs-deck-root` is 4686px tall, `#sidepanel .tab-content` is `overflow:hidden` (`web/src/styles/main.css:862-866`), so the CSS grid `.layout` grows to 4842px and `document.scrollHeight` = 4897 on a 1476px viewport. Wheel over the dock scrolls `window` to `scrollY=1000`: topbar (LEARN/search/theme/HEALTH), left nav, breadcrumb and subtab bar all scroll off-screen; the left pane becomes a black void below "Apply All Changes". `window.scrollTo()` is ignored (scrollY snaps back to 0), but wheel/scrollIntoView move it. Focusing the LEARN button or the search box also shifted the page (scrollY 288/10).
- Expected: the dock scrolls inside its own pane; the shell stays fixed.
- Evidence: `A-shots/A-dock-wheel-scrolls-whole-window.jpg`.

#### F-A-3 — Light theme: docked Command Center renders headings, chips and buttons dark-on-dark (invisible)
- Severity: P1 (in Light mode the dock is unusable)
- Surface: shell theme select → Light; docked Grafana Command Center (Overview)
- What I did: switched Auto → Dark → Light → Auto (persists as `localStorage.THEME_MODE`; `data-theme` follows).
- What happened: in Light, the deck keeps its dark gradient background but text tokens go dark: "Grafana Command Center" title invisible (measured on the deck: color rgb(24,24,27) on rgba(10,23,35,0.88) chips → ~1.2:1), all 20 chip links (OTLP export … Qdrant, Grafana Overview … System Prompts) are dark blobs with no readable text, "Refresh Surface" is a dark pill, card titles (Dashboards & Export Path, Tempo + Langfuse, …) vanish, "Open surface" buttons in the Integration Matrix are empty pills. Main pane in Light is fine.
- Expected: deck tokens flip with the theme or the deck pins its own light palette.
- Evidence: `A-shots/A-light-theme-dock-invisible-text.jpg`.

#### F-A-4 — Quick Action "Run Indexer" fails on the drive corpus: "Staging corpus not found" then "Connection lost"
- Severity: P1 (needs a second look — a concurrent run from another agent may have raced it)
- Surface: `dashboard?subtab=system` — Quick Actions → Run Indexer
- What I did: clicked Run Indexer once at ~12:36:39.
- What happened: ops log: `Indexing started … (run_id=20260825T183639_934311bec4)` → `Staged Qdrant generation ragweld_chunks_ragweld_drive_81854_fe98d8ca__eb6215f8 (dense + sparse)` → `✗ Error: Staging corpus not found: __staging__ragweld-drive-81854__20260825T183639_934311bec4` → `✗ Error: Connection lost`; progress stuck at 0%. `GET /api/index/ragweld-drive-81854/runs/latest` afterwards returned run `20260825T183630_934311bec4` (9 s earlier, not the id my click produced) with the same error; `/api/index/status` `lines[0]` = "Index error: Staging corpus not found…". A minute later the ops panel had re-rendered with run id …183630. Two runs 9 s apart with the same suffix `934311bec4` suggests another agent's index run collided with mine.
- Expected: 4-doc reindex completes in seconds; the status line should not say "Connection lost" for a server-side RuntimeError; a failed run should still be visible after switching subtabs (see F-A-14).
- Evidence: `server/db/postgres.py:1807` (`promote_staging_index` raises when the `__staging__` corpus row is missing); `/api/index/ragweld-drive-81854/runs` is 404 (no run list to inspect).

#### F-A-5 — Monitoring "Recent Alerts" shows "Failed to load" because the endpoint does not exist (404)
- Severity: P2
- Surface: `dashboard?subtab=monitoring` — Monitoring Logs → Recent Alerts
- What I did: opened the subtab.
- What happened: "Failed to load"; network: `GET /api/webhooks/alertmanager/status` → 404 (twice). Alert History says "No recent alerts" although the load failed.
- Expected: alert feed from Alertmanager (which `/api/observability/status` reports reachable at :59093), or an honest "not wired" state.
- Evidence: `web/src/api/dashboard.ts:75` calls `api('/webhooks/alertmanager/status')`; no matching route under `server/`.

#### F-A-6 — "Top Folders (Last 5 Days)" can never show data
- Severity: P2
- Surface: `dashboard?subtab=system` — Top Folders panel
- What happened: "No recent indexing metrics available." 20 minutes after a successful index of 4 files.
- Evidence: `web/src/components/Dashboard/SystemStatusSubtab.tsx:22,90` — `setTopFolders([])` is the only setter call; the table branch at `:561` is dead.

#### F-A-7 — Storage tiles say CHUNKS 0 B / POSTGRES TOTAL 0 B for a corpus with 4 chunks
- Severity: P2
- Surface: `dashboard?subtab=system` Storage Requirements, and `dashboard?subtab=storage`
- What happened: CHUNKS `0 B`, CHUNK SUMMARIES `0 B`, NEO4J `0 B`, POSTGRES TOTAL `0 B`, QDRANT POINTS `4`, QDRANT DENSE VECTORS (EST.) `6 KB`, TOTAL `6 KB`; API `/api/index/status` `storage_breakdown.chunks_bytes=0`, `qdrant_points=4`, while `/stats` says `total_chunks=4, total_tokens=443`. Storage subtab additionally prints "4 points · 0.1% of total" — a point count expressed as a share of bytes — and "QDRANT DENSE VECTORS 100.0% of total".
- Expected: either real Postgres chunk-row bytes (`server/db/postgres.py:812-830` sums `chunks` rows `WHERE repo_id=$1`, which returns 0 here) or drop the tile; don't mix counts into byte percentages.

#### F-A-8 — HEALTH pill has no popover/details; it silently re-polls
- Severity: P2
- Surface: shell topbar — HEALTH pill + "OK @ hh:mm:ss"
- What I did: clicked it (real click and JS click).
- What happened: nothing visible — no popover, toast or navigation; it only re-fires `GET /api/health`. `/api/health` reports `postgres: unknown`, `neo4j: unknown`, which the pill never surfaces ("OK").
- Evidence: `web/src/App.tsx:194` `<button id="btn-health" onClick={checkHealth}>`. Also: the pill's status text is 10px monospace.

#### F-A-9 — Dock "Dashboards" subtab shows only "Grafana embedding is disabled"; the 7-dashboard catalog is hidden
- Severity: P2
- Surface: dock → Grafana Command Center → Dashboards
- What happened: with `ui.grafana_embed_enabled=false`, the subtab is a single sentence ("Enable embedding in the Config subtab to load the dashboard iframe"). No list of the catalog's 7 provisioned dashboards or their external links, which the Overview chips do expose.
- Expected: catalog list with "Open in Grafana" links regardless of iframe embedding.

#### F-A-10 — Dock "Config" form auto-saves on checkbox toggle, shows "Saving…" in the global Apply button, and its initial values did not match persisted config
- Severity: P2
- Surface: dock → Grafana Command Center → Config → "ENABLE EMBEDDED GRAFANA"
- What I did: ticked the checkbox once, then unticked it.
- What happened: the tick fired `PATCH /api/config/ui?corpus_id=ragweld-drive-81854` immediately (no Apply step) and `#save-btn` turned into "Saving…" (disabled) until my second click fired a second PATCH. Before the tick the form displayed preset "On-call Overview", ORG ID `2`, UID `ragweld-oncall-overview`, refresh `30s`, kiosk `1 (minimal)`; after it the form displayed preset "Custom", ORG ID `1`, UID `tribrid-overview`, refresh `10s`, kiosk `tv` — which is what `GET /api/config` actually holds (`ui.grafana_dashboard_uid=tribrid-overview`, `grafana_org_id=1`, `grafana_refresh=10s`, `grafana_kiosk=tv`, `grafana_embed_enabled=false`), and Grafana calls at page load already targeted `dashboards/uid/tribrid-overview`. So the form initially showed non-persisted values. Final state verified via API: `grafana_embed_enabled=false` (reverted).
- Expected: form reflects persisted config on open; edits go through Apply All Changes like other settings, or the dock's own Apply; no stale "Saving…".
- Evidence: `web/src/components/Grafana/GrafanaConfig.tsx:17-20` defaults (`'ragweld-oncall-overview'`, org `1`).

#### F-A-11 — LEARN, "Dock Current" and Swap drop `corpus=` from the URL
- Severity: P2
- Surface: topbar LEARN; dock header Dock Current / Swap
- What happened: LEARN navigated to `/web/dashboard?subtab=glossary` (corpus param gone); Dock Current moved the main view to `/web/grafana?subtab=overview` (corpus gone); Swap → `/web/dashboard?subtab=glossary`. Active corpus stayed ragweld-drive-81854 server-side, but a reload/share of that URL loses the corpus scope other agents rely on.

#### F-A-12 — "workflow=legacy_local" / "Legacy local lane" wording on a live feature
- Severity: P3 (terminology ban: "legacy" on live features)
- Surface: dock Overview chips (`workflow=legacy_local`), WORKFLOW card ("legacy_local" badge, "Legacy local lane"), Live Evidence → Workflow control plane ("legacy_local"). The API says the local lane is the active, working lane ("Local workflow lane active; runs execute in-process"), so labelling it "legacy" contradicts the replacement-only canon.
- Evidence: `web/src/components/Observability/OperatorDeck.tsx:245,343`; `server/models/tribrid_config_model.py:3419-3420` (`lane: Literal["legacy_local","flyte_mlflow_unsloth"] = "legacy_local"`).

#### F-A-13 — Banned terminology in operator-facing copy
- Severity: P3
- Help subtab (`web/src/components/Dashboard/HelpSubtab.tsx:121`): Key Concept "Learning Ranker" (should be reranker).
- Help subtab `:167`: "Try adjusting hybrid_alpha (0.3-0.7)…" — no `hybrid_alpha` field exists in `server/models/tribrid_config_model.py` (fusion uses weights/RRF). Quick Start also says "hybrid search alpha" and "Use the Admin tab to save and compare different RAG configurations" / "Admin → General to add repository paths" — not verified to exist.
- Glossary data (`data/glossary.json`, rendered in Dashboard → Glossary and tooltips): 22 "card/cards" hits ("Card Search Enabled" / `CARD_SEARCH_ENABLED` "card-based semantic matching… if cards are stale", "Card Semantic Bonus"), 1 "Golden Questions Path" (`GOLDEN_PATH`), 1 "brittle rankers", 19 "legacy" ("REPO_PATH (legacy)", "Legacy CSV path-boost setting"), 34 "profile(s)" (mostly Colima profile — legitimate).
- Monitoring → Recent Query Traces column header "REPO" (corpus).
- Dock Config: button "Open Prometheus" while the stack is Mimir (`web/src/components/Grafana/GrafanaConfig.tsx:458`).

#### F-A-14 — Ops log is wiped on subtab switch and status line reverts to "Ready" after a failed run
- Severity: P3
- Surface: `dashboard?subtab=system` — Dashboard Operations panel + status line
- What happened: after F-A-4, switching Monitoring → System Status shows status "Ready" and log "Ready for operations…", while `/runs/latest` is `error`. The "✗ Error: Connection lost" line is gone.

#### F-A-15 — Tooltip for "Total corpora" shows the Active-corpus definition; glossary lacks a key for it
- Severity: P3
- Surface: `dashboard?subtab=system` — TOTAL CORPORA `?`
- Evidence: `SystemStatusSubtab.tsx:229,239` both use `<TooltipIcon name="SYS_STATUS_CORPUS" />`; `SYS_STATUS_TOTAL_CORPORA` is absent from `data/glossary.json`. The corpus/MCP/containers tooltips otherwise show the glossary text correctly (12px bubble).

#### F-A-16 — Storage calculator `?` marks are 10px title-attribute tooltips, not glossary tooltips
- Severity: P3
- Surface: `dashboard?subtab=storage` — 18 `<span class="tooltip">?</span>` at 10px with `title="Total size of your data/documents to index"` etc.; hovering shows nothing in-app (native title only), none map to glossary keys.

#### F-A-17 — Legibility floor violations (measured with getComputedStyle)
- Severity: P3
- 334 text leaves at **9px** on `dashboard?subtab=system` (Embedding Configuration labels "Model/Dimensions/Precision", Indexing Costs labels, storage labels) and dozens at **10px** (MCP server line "py-http:127.0.0.1:58012 ✓ | py-stdio:available", timestamps "8/25/2026, 12:24:23 PM", storage tile labels "Chunks", "Qdrant points", HEALTH status text, storage `?` marks, the 8px "●" bullet in dock Settings).
- Topbar tagline "Versioned Config · API / MCP" 11px at `opacity:0.6` (opacity on text).
- Left nav links 13px at rgb(113,113,122) on rgb(9,9,11) ≈ **3.96:1**; the ACTIVE entry ("Dashboard") is rgb(100,116,139) on rgb(24,24,27) ≈ **3.72:1** — the selected item is the least legible. Hover state is fine (rgb(228,228,231) on rgb(24,24,27)).
- Inactive subtab buttons (main and dock) 12px at 3.96:1; active pill 6.9:1 OK.
- Light theme: glossary category counts "(27)", "(46)"… 11px rgb(24,24,27) on rgba(0,0,0,0.2) ≈ 1.2:1 (unreadable).
- `#save-btn` disabled state rests at opacity 0.6.
- Corpus switcher modal: one child overflows horizontally (scrollWidth 586 > clientWidth 518) and a white scrollbar stripe renders under the modal; the glossary tab content also shows a horizontal scrollbar stripe at the bottom.

#### F-A-18 — Dock toast covers the topbar HEALTH pill
- Severity: P3
- Surface: after Choose… → Grafana Overview the toast "Dock set to: Grafana — Overview [Undo] [x]" renders over "HEALTH OK @ …" at the top-right until dismissed.

#### F-A-19 — Command Center placeholder chips read as facts while loading
- Severity: P3
- Surface: dock Overview during the first ~2 s after mount / after Swap
- What happened: chips show `mode=unknown severity=unknown incidents=0` and METRICS says "Grafana missing", WORKFLOW "Unknown", RETRIEVAL "Not indexed" before the fetch completes, then flip to `mode=otel_langfuse`, "Grafana reachable", "Qdrant generation live". Also the deck polls 9 endpoints (`observability/status` ×2 incl. one without corpus_id, catalog, incidents, eval/benchmark/prompts summaries, traces/latest, loki/status, control-plane/status) every cycle — 194 `/api/` requests in ~10 minutes on one idle tab.

#### F-A-20 — Incident feed lineage line shows "X -> X"
- Severity: P3
- Surface: dock → Incidents → PROMPT_REGRESSION card: "Current prompt set · prompt_set__1ba7c39ddce2526a1dc3a2d5 -> prompt_set__1ba7c39ddce2526a1dc3a2d5 · Prompt-set lineage currently selected" — the "changed since" evidence points from an id to the same id.

#### F-A-21 — Corpus switcher exposes a one-click "Delete corpus" trash button on every corpus, including the active one
- Severity: P3 (not exercised; risk note)
- Surface: Quick Actions → "Corpus: Aurora drive corpus" → Select Corpus modal
- What happened: each row has a red trash button `aria-label="Delete corpus …"` (also on the ACTIVE row); the Create corpus form and "Create & Select" sit below. Two rows point at the same directory (`Aurora drive corpus` → `/Users/…/tests/fixtures/acceptance_corpus`, `Aurora Acceptance` → `tests/fixtures/acceptance_corpus`). Closed with Esc; active corpus unchanged.

### Works as expected (brief)
- Theme select: Auto/Dark/Light apply instantly, persist in `localStorage.THEME_MODE`, `data-theme` follows; main pane fine in both.
- Left nav: hover (lighter text + elevated bg) and `aria-current=page` on the active entry; "📌" pin follows whatever is docked (Grafana 📌 / Dashboard 📌); Benchmark/Eval Analysis links carry descriptive `title`s.
- Dock header: Settings ↔ Dock toggle; Settings pane = Quick Model Switcher (404 options, "Ragweld local (vLLM Metal)" selected), embedding provider/model, reranker/rerank model, Secrets Ingest dropzone, "Persist to defaults.json", Apply Changes. Dock Current docks the current subtab and moves the main view to the previously docked surface; Choose… opens "Choose something to dock" (Recommended + Everything, search works: "System Status" → 1 hit) and docks the pick with an Undo toast; Swap exchanges main/dock; Clear shows "Nothing docked yet — Dock Chat / Dock Current / Choose…" and hides Swap/Clear.
- Command Center Overview after load: chips match `/api/observability/status` (`mode=otel_langfuse`, `severity=info`, `incidents=n`, `latest_route=POST /api/…`); 12 external links match the status `links[]` URLs; 6 workbench chips match catalog `workbench_links`; Integration Matrix lists all 17 components with the same `detail` strings as the API (Qdrant "4 points, 4 dense (384-d), generation ragweld_chunks_ragweld_drive_81854_fe98d8ca__a8e4a5e7"); Live Evidence trace/route updates as other agents hit chat/search. Incidents count/severity matched `/api/observability/incidents` at each read.
- System Status tiles: HEALTH healthy, ACTIVE CORPUS "Aurora drive corpus (ragweld-drive-81854)", TOTAL CORPORA 4 (modal lists 4), MCP SERVERS, CONTAINERS 22/22, LOCAL RUNTIME :55173/:58012; Embedding panel (BAAI/bge-small-en-v1.5, 384, float32) and Total tokens 443 match `/stats`; ↻ Refresh Status and Quick Action Refresh Status re-fetch index/status, health, mcp/status, docker/status, docker/services, dev/status, stats and print "✓ Status refreshed"; Reload Config prints "✓ Configuration reloaded successfully"; MCP/Containers tiles deep-link to Infrastructure.
- Tooltips: SYS_STATUS_CORPUS / MCP_SERVERS / CONTAINERS bubbles show the glossary definitions.
- Glossary: search filters live ("fusion" → BM25 Weight (Hybrid Fusion), Fusion Method, RRF K…, Vector Weight (Hybrid Fusion)…), each entry shows key, tags, definition and reference links; Loki panel "Connected · http://127.0.0.1:53100" matches `loki/status`.
- Apply All Changes with nothing dirty: disabled, no request on click.
- No console errors on any surface; no 4xx/5xx except the alertmanager 404 (F-A-5).

### Not exercised (and why)
- Generate Keywords, Run Eval (hard limits). "Delete corpus" trash buttons and "Create & Select" in the corpus modal (destructive / would switch corpus). Dock Settings "Apply Changes", Quick Model Switcher and Secrets Ingest (model/secret changes). "Enable embedded Grafana" left off (reverted after F-A-10); dock Config text fields not edited. External "Open surface"/Grafana/Qdrant links not followed (leave the app). Undo on the dock toast not pressed. Storage calculator inputs are UI-local (never enable Apply) — not changed.

---

## Report B — B-chat.md

## Chat tab — curious-user drive inventory (2026-08-25)

Corpus: `ragweld-drive-81854` (Aurora acceptance fixtures at `tests/fixtures/acceptance_corpus/`). Tab used: 1950917897 (closed at end). Models used: `openai.gpt-5.6-luna` (default), `openai.gpt-4.1-nano` (Q2–Q5). `ragweld-local` selected but never sent. No training/eval/index actions taken. All settings changes restored and verified via API.

### Surfaces visited
- `chat?subtab=ui` — Chat Workbench: Sources dropdown (3 retrieval-leg checkboxes, Recall checkbox + intensity select + `?` tooltip, 3 corpus checkboxes with INDEXED badges), model picker (400+ options, provider-grouped), Export / History / New chat / Delete / Settings header buttons, message list, composer (`#chat-input`, Attach, `#chat-send`), 3 Retrieval-legs pills under the composer, status line, Routing Trace panel (3 cards + Grafana/Tempo/Langfuse buttons + event log) and Logs (Loki) panel below. Scrolled to bottom, opened dropdown, opened every dialog, hovered the Recall tooltip. 7 real Aurora questions + 1 unanswerable + 1 stop-mid-stream.
- `chat?subtab=settings` — Chat Settings with 7 section tabs: Model (1 base textarea, 4 state textareas, 2 "legacy suffix" textareas, 3 number inputs, Generation Gateway block), Sources (placeholder text only, 0 controls), Recall (17 controls: 9 toggles, 7 numbers, 1 select), Multimodal (1 toggle), Providers (2 toggles, 4 text inputs; LiteLLM + managed vLLM), Benchmark ("coming soon", 0 controls), UI (1 toggle). Each section opened; one control of each kind changed, persisted, reloaded, verified, restored.

### Question grading (all against `tests/fixtures/acceptance_corpus/*.md`)
| # | Model | Question | Expected | Result |
|---|---|---|---|---|
| Q1 | luna | Salinity calibration cadence + standard | 45 days, Halcyon reference brine | Correct; cited `sensor-calibration.md:1-12` |
| Q2 | nano | Pelican gateway on inbound frames | checksum validation + arrival timestamps | Correct |
| Q3 | nano | Pelican heartbeat gap 90 s | fail over to Osprey standby (manual, confirm checksum feed, 6 h mirrored) | Correct, all three details |
| Q4 | nano | Long summary (stopped mid-stream) | n/a | Stopped after ~2.5 s; see F-chat-6 |
| Q5 | nano | Observatory annual budget (unanswerable) | must say it does not know | Correct: "snippets do not include any information about the observatory's annual budget" |
| Q6 | nano | KestrelDB pipeline as list + table + fenced code "from the corpus" | stages, 02:15 UTC / <11 min, 400 days; NO command exists in corpus | List/table facts correct; code block is a fabricated crontab (see F-chat-7) |
| Q7 | luna | Temperature probe verification | monthly, dual platinum reference thermometer pair (wet lab) | Correct |
| Q8 | luna | Long summary, run to completion | 90 s / Osprey / manual / 6 h / >4 min generator + station lead | Correct, 2.7k chars, honest that data-pipeline.md has no failover/power text |
| Q9 | luna | Power interruption threshold + who is notified | > 4 minutes, station lead | Correct |

### Findings

#### F-chat-1 — Chat opens scoped to the wrong corpus (Epstein) while the URL/app says `ragweld-drive-81854`
- Severity: P1
- Surface: `chat?subtab=ui` — Sources dropdown / active thread
- What I did: Navigated to `chat?subtab=ui&corpus=ragweld-drive-81854` on a fresh tab.
- What happened: The message list showed a prior thread full of `HOUSE_OVERSIGHT_*` citations; Sources read "2 selected" = `recall_default` + `epstein-files-1`; `source-corpus-ragweld-drive-81854` unchecked. localStorage `ragweld-chat-threads:v2` thread carried `sources.corpus_ids: ["recall_default","epstein-files-1"]`. `GET /api/config` `chat.default_corpus_ids` = `["recall_default"]`. No API failures.
- Expected: Chat scope should follow (or at least visibly flag) the active corpus; a curious operator selecting the Aurora corpus in the header would send their first question to the Epstein corpus without noticing.
- Evidence: `/var/folders/fh/tnbpt3jd26l_4b09q54m033c0000gn/T/claude-chrome-screenshots-HxghRx/screenshot-1787682281866-0.jpg`, `screenshot-1787682364906-1.jpg`; `web/src/components/Chat/ChatInterface.tsx:1140-1150` (defaults only applied when the thread has no corpus_ids), `chatSessions.ts:123-125`.

#### F-chat-2 — Helpful / Not helpful buttons are effectively invisible (black 10px text on dark)
- Severity: P2
- Surface: `chat?subtab=ui` — assistant message footer
- What I did: `getComputedStyle` on the Helpful button of a completed answer.
- What happened: `font-size 10px`, `color rgb(0,0,0)`, wrapper `opacity 0.78`, message background `rgb(15,15,18)`. Copy/Trace in the same row use `color: inherit`; the feedback buttons do not set color so they render as browser-default black. Visually they cannot be seen on the dark theme (only the post-click "Feedback saved" is legible).
- Expected: Legibility floor: >= 11px, no opacity on text, contrast >= 4.5:1. This is the control that feeds reranker feedback signal.
- Evidence: `web/src/components/Chat/ChatInterface.tsx:784-841` (footer at 10px, `opacity: 0.78`, Helpful/Not helpful without `color`); screenshot `screenshot-1787682541148-12.jpg` (row right of "Copy Trace" is blank).

#### F-chat-3 — "Streaming responses" setting is dead: request still streams and UI still shows Streaming/Stop
- Severity: P2
- Surface: `chat?subtab=settings` — UI > Streaming responses; `chat?subtab=ui`
- What I did: Toggled Streaming responses off (persisted: `ui.chat_streaming_enabled=false` after reload), asked Q9.
- What happened: Badge "Streaming" and Stop button appeared at t+1 s; route `POST /api/chat/stream`; Routing Trace `chat.request` still shows `"stream": true`.
- Expected: Either the request goes non-streaming or the control is removed. `grep chat_streaming_enabled web/src server` finds only `ChatSettings.tsx:83,652` and the config model — no consumer.
- Evidence: `screenshot-1787683216376-53.jpg`; `web/src/components/Chat/ChatSettings.tsx:83`.

#### F-chat-4 — Every Chat Settings control auto-persists on change; "Apply All Changes" is decorative here
- Severity: P2
- Surface: `chat?subtab=settings` — all sections + `#save-btn`
- What I did: With `#save-btn` disabled, clicked the Streaming toggle.
- What happened: `#save-btn` immediately read "Saving..." (disabled) without being clicked; after also editing Max tokens, Default intensity and the Direct prompt textarea, `GET /api/config` already held all four new values before any Apply click. A stray keystroke in a system prompt is committed to persisted config within the debounce window.
- Expected: Explicit Apply semantics as advertised by the button, or an honest "auto-saved" indicator and no Apply button.
- Evidence: `web/src/hooks/useConfig.ts:82-113` (`useConfigField` -> `patchSectionDebounced`); screenshot `screenshot-1787683112023-51.jpg` (status "Saving..." while no Apply was clicked).

#### F-chat-5 — Citation "Open in editor" links use relative paths and cannot resolve
- Severity: P2
- Surface: `chat?subtab=ui` — Sources list under each answer
- What I did: Read `href` of `[data-testid="chat-citation-link"]`.
- What happened: `vscode://file/sensor-calibration.md:1`, `vscode://file/recall/conversations/<uuid>.md:13`, `vscode://file/HOUSE_OVERSIGHT_025879__msg_000__row_000785.txt:2` — no corpus root prefixed, so VS Code cannot open them. The corpus root is known to the API (`/api/repos` path = `/Users/davidmontgomery/ragweld/tests/fixtures/acceptance_corpus`).
- Expected: absolute path (corpus root + file_path) or an in-app chunk viewer.
- Evidence: `web/src/components/Chat/ChatInterface.tsx:108-110`.

#### F-chat-6 — Stopping a stream leaves a permanently "Streaming" partial message with raw markdown and feedback buttons
- Severity: P2
- Surface: `chat?subtab=ui` — Stop button while streaming
- What I did: Sent the long summary question, clicked Stop (`#chat-send` reading "Stop") ~2.5 s in.
- What happened: Button returned to "Send" (good), but the partial message keeps the "Streaming" badge indefinitely, ends on a truncated `**Post-Fail` (unclosed markdown rendered literally), has no citations, no Trace button (no run id), and still offers Helpful / Not helpful. No "stopped by user" marker. Routing Trace stays on the previous run.
- Expected: badge cleared, an explicit "stopped" state, feedback disabled for partial output.
- Evidence: `screenshot-1787682732146-26.jpg`.

#### F-chat-7 — Model fabricated a "corpus" code snippet (grounding failure surfaced with no warning)
- Severity: P2
- Surface: `chat?subtab=ui` — answer to Q6 (gpt-4.1-nano)
- What I did: Asked for "one example command or config snippet from the corpus in a fenced code block".
- What happened: Answer produced a crontab (`15 2 * * * /usr/local/bin/kestreldb-compact`) "as per the data pipeline documentation". The four corpus docs contain no command or config. The UI presented it with the same citations/confidence as grounded content.
- Expected: The RAG prompt should hold the line ("the corpus contains no such snippet") as it did for the budget question; nothing in the UI distinguishes grounded vs. invented spans. Noting model choice (nano) as a contributing factor.
- Evidence: DOM tags `OL,TABLE,PRE,CODE` confirmed; `tests/fixtures/acceptance_corpus/data-pipeline.md`.

#### F-chat-8 — Sources list mixes incomparable score scales; recall memories outrank the grounding document
- Severity: P2
- Surface: `chat?subtab=ui` — Sources under each answer
- What I did: Read the Sources list for Q1.
- What happened: `sensor-calibration.md:1-12 score 0.040` (the doc that answered) sits below five `recall/conversations/<uuid>.md:1-1 score 0.700/0.689/...` entries. RRF-fused corpus scores (~0.02–0.04) and recall similarity (~0.7) are shown in the same column, so the "best" sources look like opaque conversation fragments. The recall entries give no preview of what was recalled.
- Expected: separate "Corpus" vs "Recall memory" groups, per-group score semantics, or normalized display.
- Evidence: `screenshot-1787682478213-10.jpg`; `ChatInterface.tsx:748-782`.

#### F-chat-9 — "Legacy suffix prompts" / "falls back to the legacy base+suffix" copy on a live feature
- Severity: P3 (terminology ban)
- Surface: `chat?subtab=settings` — Model section
- What I did: Opened Model section, scrolled to the heading.
- What happened: H4 "Legacy suffix prompts" (14px) and helper text "If a selected prompt is empty, the system falls back to the legacy base+suffix prompt composition." Also a runtime fallback path, which the canon forbids.
- Expected: no "legacy" labels on live surfaces; no fallback composition.
- Evidence: `web/src/components/Chat/ChatSettings.tsx:122,188`; `screenshot-1787683294004-55.jpg`.

#### F-chat-10 — Recall gate ignored the configured default intensity (observed "deep" with default "light")
- Severity: P3 (needs confirmation)
- Surface: `chat?subtab=settings` Recall > Default intensity; `chat?subtab=ui` status line
- What I did: Set Default intensity to `light` (persisted, verified after reload), asked Q9 in an existing thread.
- What happened: Status line "Recall: deep 10 matches | ragweld-drive-81854: 4 | 1882ms". Earlier with default `standard` the line showed "standard 5 matches"; the budget question showed "skip".
- Expected: Possibly heuristics (`deep_on_explicit_reference`, `server/chat/retrieval_gate.py:165`) legitimately override the default, but the operator has no way to see *why* — the "Show decision in status bar" toggle shows only the intensity, not the reason string that `retrieval_gate.py:229` computes.
- Evidence: status text captured at 12:40; `server/chat/retrieval_gate.py:131,165,226-234`.

#### F-chat-11 — Sources dropdown labels are muted 12px (corpus names in the de-emphasis tier)
- Severity: P3 (legibility)
- Surface: `chat?subtab=ui` — Sources dropdown
- What I did: Measured with `getComputedStyle`.
- What happened: Retrieval-leg labels, "Corpora", every corpus name: `12px rgb(113,113,122)` on `rgb(9,9,11)` (~4.0:1); INDEXED badge `11px` with `opacity 0.9`; `?` icon 11px. Primary choices (which corpus to query) are rendered in the muted tier.
- Expected: >= 4.5:1 for support text, >= 7:1 for the actual selectable names; no opacity on text.
- Evidence: `web/src/components/Chat/SourceDropdown.tsx:228-253`.

#### F-chat-12 — Message footer/meta typography below the floor
- Severity: P3 (legibility)
- Surface: `chat?subtab=ui` — assistant message
- What I did: Measured.
- What happened: body markdown 13px; citation labels 11px; time/provider badge 11px; debug footer (run_id, trace_id…) 11px `rgb(113,113,122)`; composer hint "Press Ctrl+Enter to send…" 11px muted; status line 11px muted; Copy/Trace 10px at 0.78 opacity.
- Expected: body >= 14px, meta >= 11.5px, no opacity on text.
- Evidence: `ChatInterface.tsx:114,706-716,754-768,784-799,850-860`.

#### F-chat-13 — Assistant header shows "LiteLLM", never which model answered
- Severity: P3
- Surface: `chat?subtab=ui` — assistant message header
- What I did: Switched picker to gpt-4.1-nano and asked Q2; request body carried `model: litellm:openai.gpt-4.1-nano`.
- What happened: Header badge reads "LiteLLM" for every answer. After switching models mid-thread there is no per-message record of which model produced which answer (Export JSON was not inspected for this).
- Expected: model alias in the message header or debug footer.

#### F-chat-14 — Empty state and composer copy are codebase-centric, not corpus-centric
- Severity: P3 (copy)
- Surface: `chat?subtab=ui` — New chat empty state, `#chat-input` placeholder
- What happened: Placeholder "Ask ragweld about your codebase..."; welcome "ASSISTANT-UI REBUILD — Chat stays grounded in recall, sources, and session continuity"; suggestion chips "Where is auth token validation implemented?", "Summarize the retrieval and recall pipeline.", "Show me the operator-facing observability surfaces." — none relate to the selected corpus (an observatory). "ASSISTANT-UI REBUILD" is an engineering label, not operator copy. The system prompts call the corpus "database repositories"/"database snippets", which leaks into answers ("The provided database snippets do not include…").
- Evidence: `screenshot-1787682436095-6.jpg`; `ChatInterface.tsx:888-900`.

#### F-chat-15 — Copy gives no confirmation; Export downloads silently
- Severity: P3
- Surface: `chat?subtab=ui` — message "Copy", header "Export"
- What I did: Clicked Copy (message) and Export (header) with a toast observer + download hook.
- What happened: Copy: no toast, no state change. Export: created `chat-export-<ts>.json` blob (24 KB) via anchor click, no toast. Both are "did anything happen?" moments for a new operator (and downloads are inert in some hosted contexts).
- Expected: "Copied"/"Exported" feedback.

#### F-chat-16 — "Jump to latest" pill shows on an empty thread; Escape does not close the Sources dropdown
- Severity: P3
- Surface: `chat?subtab=ui`
- What happened: After New chat with zero messages the "Jump to latest" button is still rendered. The Sources dropdown stays open after Escape and after New chat; only clicking "Sources" again closes it.
- Evidence: `screenshot-1787682436095-6.jpg`.

#### F-chat-17 — Document-level scroll clips the app header after Trace / trace-panel updates
- Severity: P3 (layout)
- Surface: `chat?subtab=ui` — Trace button / Routing Trace panel
- What I did: Clicked Trace, then observed after answers.
- What happened: `document.documentElement.scrollTop` went to 97.8 px (top nav "ragweld" and Interface/Settings subtabs cut off) while `#tab-chat` also scrolled; the Routing Trace scrollIntoView appears to scroll the window rather than the tab container. Resetting `scrollTop=0` was undone by the next update.
- Evidence: `screenshot-1787682541148-12.jpg`, `screenshot-1787682658173-18.jpg`.

#### F-chat-18 — Focus leaves the composer after send
- Severity: P3
- Surface: `chat?subtab=ui` — composer
- What happened: 0.5 s after Ctrl+Enter, `document.activeElement` is `<body>`; the operator must click the box again to ask a follow-up. Enter inserts a newline (config `chat.send_shortcut = "ctrl+enter"`, hint text agrees), Shift+Enter also inserts a newline.

#### F-chat-19 — Retrieval-leg controls are duplicated in two places
- Severity: P3
- Surface: `chat?subtab=ui`
- What happened: Vector/Sparse/Graph exist as checkboxes inside the Sources dropdown (`source-toggle-*`) and again as pills under the composer (`chat-toggle-*`, "On Vector / On Sparse / Off Graph"). They stay in sync but the pill labels read as status ("Off Graph") rather than as toggles.

#### F-chat-20 — Sources and Benchmark settings sections are placeholders
- Severity: P3
- Surface: `chat?subtab=settings` — Sources, Benchmark
- What happened: Sources: "This tab is a placeholder for source selection defaults…" (0 controls, yet `chat.default_corpus_ids` exists and is what caused F-chat-1). Benchmark: "Split-screen model comparison + pipeline profiling controls live here (coming soon)." (0 controls). Config keys `chat.send_shortcut` and `chat.show_source_dropdown` are not exposed anywhere in Chat Settings.

#### F-chat-21 — Console warning: React `key` spread into `<a>` props
- Severity: P3
- Surface: `chat?subtab=ui` (first load)
- What happened: `A props object containing a "key" prop is being spread into JSX … <a {...props}>` from the markdown link renderer. One occurrence per load; no other console errors during the whole drive.

#### F-chat-22 — Selecting `ragweld-local` gives no indication of local-model state
- Severity: P3
- Surface: `chat?subtab=ui` — model picker
- What I did: Selected "Ragweld local (vLLM Metal)" (did not send).
- What happened: Selection accepted silently; no banner about whether vllm-metal is loaded, no cost/latency hint, no confirmation. Providers section says expected served model `mlx-community/Qwen3.8-27B-4bit` but the picker gives no such context.

### Works as expected (brief)
- Streaming: "Streaming" badge + Send→Stop during generation; answers in 2–8 s; `POST /api/chat/stream` with `corpus_ids: ["recall_default","ragweld-drive-81854"]`, `include_vector/sparse: true`, `include_graph: false`.
- Model picker: switching to `openai.gpt-4.1-nano` is honored in the request body; default (luna) omits the field and the route card confirms `LiteLLM → openai.gpt-5.6-luna @ http://127.0.0.1:54000/v1`.
- Helpful feedback: toast "Feedback recorded."; `GET /api/reranker/logs?corpus_id=ragweld-drive-81854&limit=50` gained `{kind:"feedback", signal:"thumbsup", event_id:<run_id>, context:"chat"}` (3 logs after).
- Trace button: fills Routing Trace (Canonical Trace / Request Route / Cost cards, e.g. `$0.000209`, `chat_stream 2786 ms`, `catalog 888 tokens`), full `chat.request` + `retrieval.fusion` JSON (fusion_vector_results 9, sparse 6, per-corpus breakdown), and the Grafana dock flipped to "Live trace present".
- Recall intensity `?` tooltip: rich, with references; Recall status line reports mode/matches/latency per turn and "skip" for the budget question.
- Threads: New chat creates a fresh thread inheriting the previous thread's sources; History sidebar "Chats (n)" with title/time/msgs/active; switching swaps messages and per-thread sources; sidebar and header Delete both open the same honest confirm modal ("removes it from the local chat history. Recall memory is not deleted."); Cancel works; Delete removed the thread (3→2, localStorage agrees). Titles auto-derive from the first message (no rename affordance exists).
- Markdown: headings, ordered lists, GFM table, fenced code with per-block Copy button all render.
- Unanswerable question handled honestly; long answer (2.7k chars) renders and "Jump to latest" tracks.
- Settings persistence: toggle, number, select, textarea all survived reload and matched `GET /api/config`; restore verified (max_tokens 512, intensity standard, streaming true, prompt marker removed).
- No failed API calls (`window.__apiFails` empty on both subtabs throughout); no horizontal page scroll.

### Not exercised (and why)
- Sending on `ragweld-local` (protocol: never send on the local model).
- Structured error card (`chat-structured-error-card`) — never appeared naturally; not forced.
- Image attach / multimodal (`chat-attach-button`) — not in scope; would need an image upload.
- Text inputs in Providers (LiteLLM/vLLM base URL, alias, expected served model) — changing them would reroute live generation; no safe text field exists elsewhere in Chat Settings, and there is no slider control anywhere in Chat Settings.
- Clipboard content verification for Copy — `navigator.clipboard.readText()` hung the evaluate (permission prompt); only the absence of any confirmation was verified.
- Grafana dashboard / Tempo trace / Langfuse trace buttons in the Routing Trace panel — open external tabs; belongs to the Grafana/dock group.
- Rename thread — no affordance exists (see Works/Threads).

---

## Report C — C-grafana-benchmark-eval.md

## Group C: Grafana / Benchmark / Eval Analysis — curious-user drive inventory (2026-08-25)

Corpus: `ragweld-drive-81854` (Aurora drive corpus, 4 md docs). Tab used: own MCP tab (closed at end).
Note on the environment: a persisted right-hand Dock ("Dock: Grafana — Overview", key `tribrid-dock-storage` in localStorage) was open in every screenshot; it is shared across all drive tabs, so I left it alone.

### Surfaces visited
- `grafana?subtab=dashboard` — NOT a valid subtab; the app silently rewrote the URL to `?subtab=overview`. Subtabs are Overview / Dashboards / Incidents / Config.
- `grafana?subtab=overview` — "Grafana Command Center": 6 chips (mode/corpus/severity/incidents/workflow/latest_route), 12 external link pills + 6 internal pills, 9 status tiles, Integration Matrix (13 rows, each with "Open surface"), Live Evidence, ML Quality, Incident Feed. Scrolled to bottom (3741px). No collapsibles. Every one of the 12 external + 2 trace deep links opened in my tab (results below).
- `grafana?subtab=dashboards` — 7 "Dashboard family" tiles, Dashboard select (8 opts), Range select (10 opts), Reload, Open, embedded Grafana iframe (kiosk=tv). Clicked a tile, changed Range, clicked Reload, opened every dashboard directly in Grafana and read every panel's PromQL through the Grafana API.
- `grafana?subtab=incidents` — one card "Incident Feed", zero controls, no scroll.
- `grafana?subtab=config` — 1 select (preset), 1 checkbox, 1 number, 7 text inputs, 1 select (kiosk), 3 link buttons. Changed one of each kind, reloaded, verified via API, restored.
- `benchmark` — 404 model checkboxes in 53 provider groups (no search/filter), Prompt textarea, Run; ran ONE benchmark with exactly `openai.gpt-4.1-nano` + `openai.gpt-5.6-luna`; Lineage panel; results table; SplitScreen; PipelineProfile; reload.
- `eval?subtab=analysis` — Swap/Run Eval toggle, Run Settings (expanded, 15 controls), RAG Evaluation Logs (expanded), Promptfoo regression panel (sample-size select + Run button), empty state. Did NOT click Run Eval / Run Promptfoo / Run First Evaluation.
- `eval?subtab=dataset` — corpus select (+ ? tooltip), Question + Expected paths inputs, Add Entry, list with Edit/Delete. Added 2 real entries, edited 1, deleted 1, reloaded, verified via API.
- `eval?subtab=prompts` — 18 `<details>` prompt editors in 4 sections (Chat 8, Retrieval, Indexing, Evaluation), all collapsed by default. Expanded Main RAG Chat, Edit → Save Changes, reload, verified via API, restored.
- `eval?subtab=trace` — "LATEST TRACE" card: corpus select (1 option), Refresh, trace ids, route, cost, 2 links, events list.
- External targets opened: OTLP :54320/v1/traces, Alloy :52345, Tempo :53200, Mimir :59009, Pyroscope :54040, Faro :52347/collect, Alertmanager :59093, Langfuse :53000, Grafana :3301, LiteLLM :54000/v1, vLLM :58080/v1, Qdrant :56333/dashboard, Tempo-trace Explore link, Langfuse-trace link, localhost:9090 (Prometheus).

### Findings

#### F-C-1 — Benchmark answers are not grounded in the corpus and the UI never says so
- Severity: P1
- Surface: `benchmark` — Prompt panel / results table
- What I did: selected `openai.gpt-4.1-nano` + `openai.gpt-5.6-luna`, prompt "How often is the salinity sensor array calibrated, and against which reference standard?", clicked Run (12.2 s).
- What happened: nano answered "generally ranges from weekly to monthly ... NIST"; luna answered "Which salinity sensor array do you mean?". Neither mentions the corpus answer (every 45 days, Halcyon reference brine). No label anywhere says retrieval is bypassed; placeholder reads "Enter a prompt to run across multiple models…". console: none; failed API calls: none.
- Expected: either run the prompt through the RAG pipeline for the active corpus, or state on the surface that Benchmark compares raw model generation with `context_chunks=[]`.
- Evidence: `server/chat/benchmark_runner.py:61-67` (`system_prompt=config.chat.system_prompt_base`, `temperature_no_retrieval`, `context_chunks=[]`); screenshot `/var/folders/fh/tnbpt3jd26l_4b09q54m033c0000gn/T/claude-chrome-screenshots-HxghRx/screenshot-1787683042808-49.jpg`; `GET /api/benchmark/results?corpus_id=ragweld-drive-81854` run `daf43e8718fe487ea7aada23ce3f46b2`.

#### F-C-2 — Every "Search Rate / Latency / Success" Grafana panel is blind to chat traffic
- Severity: P1
- Surface: `grafana?subtab=dashboards` — On-call Overview, TriBrid Overview, Retrieval/Indexing/Graph, Cost & Capacity, Frontend/RUM (9 panels total)
- What I did: compared `http://127.0.0.1:58012/metrics` against the panel PromQL pulled from `GET :3301/api/dashboards/uid/*`.
- What happened: after 2 chat retrievals, `tribrid_search_requests_total 0.0` and `tribrid_search_latency_seconds_count 0.0` while `tribrid_vector_leg_latency_seconds_count 2.0` and every `tribrid_search_stage_latency_seconds_count{...} 2.0`. Later snapshot: `search_requests_total 4` vs `vector_leg_latency_count 15` (only the RAG tab's `/api/search` calls counted). On-call Overview rendered "Search Latency (p95)" as a giant green **NaN**, "Traffic Overview" flat 0 req/s, while the chat traces existed in Tempo.
- Expected: `SEARCH_REQUESTS_TOTAL` / `SEARCH_LATENCY_SECONDS` incremented on every retrieval (chat path included), or the panels titled honestly ("/api/search only"); NaN should render as "No data".
- Evidence: `server/api/search.py:83` (`SEARCH_REQUESTS_TOTAL.inc()` only here), `server/main.py:307-309` (`SEARCH_LATENCY_SECONDS.time()` wrapper); panel exprs: `sum(rate(tribrid_search_requests_total[5m]))`, `histogram_quantile(0.95, rate(tribrid_search_latency_seconds_bucket[5m]))`.

#### F-C-3 — Dashboard template variables (Corpus/Run/Model/Provider/Prompt Set/Workflow) are decorative
- Severity: P2
- Surface: `grafana?subtab=dashboards` — all 6 `ragweld-*` dashboards
- What I did: read templating + every panel target via the Grafana API; opened On-call Overview non-kiosk.
- What happened: all six dashboards declare `corpus_id, run_id, model, provider, prompt_set, workflow_id` (all `*`, prompt_set=`current`), but not one panel expression references `$corpus_id` or any variable, and the app's iframe URL never passes `var-corpus_id=ragweld-drive-81854`. Operator notes claim "Use the shared dashboard variables to keep the same corpus/run/model context across tabs."
- Expected: variables wired into queries and pre-filled from the active corpus, or removed.
- Evidence: iframe src `http://127.0.0.1:3301/d/ragweld-oncall-overview/on-call-overview?from=now-1h&to=now&theme=dark&refresh=10s&kiosk=tv&orgId=1`; dashboards JSON (no `$` in any expr).

#### F-C-4 — Grafana Config auto-saves every keystroke and bypasses "Apply All Changes"
- Severity: P2
- Surface: `grafana?subtab=config` — every control
- What I did: set Refresh 10s→30s, Org ID 1→2, Kiosk tv→1 (minimal), unticked "Enable embedded Grafana". `#save-btn` stayed disabled throughout and briefly showed "Saving…" on its own. Reloaded: UI showed 30s / 2 / 1 / unchecked; `GET /api/config` `ui.grafana_refresh=30s`, `ui.grafana_org_id=2`, `ui.grafana_kiosk=1`, `ui.grafana_embed_enabled=false`. Restored all (verified `ui.grafana_*` back to 10s/1/tv/true, uid `tribrid-overview`).
- What happened: no Apply gate, no toast, no undo; clicking a "Dashboard family" tile on the Dashboards subtab also silently persisted `ui.grafana_dashboard_uid=ragweld-oncall-overview` to the corpus config (the corpus started at `tribrid-overview`, which is also what `tribrid_config.json:454` holds). Typing an Org ID digit-by-digit writes intermediate values.
- Expected: same Apply/dirty flow as the rest of Settings, with a toast; tile click should not write config.
- Evidence: `#save-btn.is-disabled` + text "Saving…" during change; `server/models/tribrid_config_model.py:5733-5772` defaults.

#### F-C-5 — Benchmark page forgets everything on reload; no history although runs are persisted
- Severity: P2
- Surface: `benchmark` — whole page
- What I did: after the run and "Set baseline", reloaded.
- What happened: results, lineage panel, prompt all gone; selection reverted to the first two list entries (`RAGWELD LOCAL (VLLM METAL)` + `AIONLABS: AION-2.0`, an arbitrary default). `GET /api/benchmark/results?corpus_id=…` still returns the run; the Grafana overview tile shows "Run present · 2658.9 ms avg". There is no previous-runs list anywhere on the page.
- Expected: a history/previous-runs list (the API exists) and a remembered selection.
- Evidence: `web/src/components/Benchmark/BenchmarkTab.tsx:413-466` (only `runResult` state is rendered).

#### F-C-6 — Benchmark shows no cost/token data although config says cost tracking is on
- Severity: P2
- Surface: `benchmark` — results table / SplitScreen / PipelineProfile
- What I did: read the results (table columns Model | Latency (ms) | Response | Error; SplitScreen "Latency: 2.88s ✓ OK"; PipelineProfile "generate 2441.8ms").
- What happened: `chat.benchmark.include_cost_tracking=true`, `include_timing_breakdown=true`, model rows advertise "$0.00010 IN / $0.00040 OUT PER 1K", yet the run JSON has no cost/tokens (`result keys: model,response,latency_ms,breakdown_ms,error,model_id,model_name`; `model_id`/`model_name` are null). Breakdown is a single `generate` bucket. The Grafana overview's LiteLLM tile does show cost for chat ($0.000727), so the data exists elsewhere.
- Expected: cost + tokens per model, or drop the config flag.
- Evidence: `GET /api/benchmark/results` payload above.

#### F-C-7 — Eval Dataset form cannot capture `expected_answer`, so Promptfoo can never grade anything
- Severity: P2
- Surface: `eval?subtab=dataset` — Add Eval Entry / Edit
- What I did: added and edited entries; only Question + "Expected paths (comma-separated)" fields exist (also in the inline Edit form).
- What happened: `GET /api/dataset` rows have `"expected_answer": null, "evidence_quote": null, "tags": []`. The Promptfoo panel on Eval Analysis says it "Answers sampled eval entries with an expected answer" and the model has `skipped_entries: "Dataset entries skipped because they have no expected_answer"`. There is no import/export control.
- Expected: expected-answer (and evidence quote/tags) fields in the form; import/export.
- Evidence: `server/models/tribrid_config_model.py:2695,2791,2860`.

#### F-C-8 — Trace Viewer is not corpus-scoped; its corpus select has a single hard-coded option
- Severity: P2
- Surface: `eval?subtab=trace` — "LATEST TRACE" select / Refresh
- What I did: read the select (`[""|All corpora]`), clicked Refresh (fires `GET /api/traces/latest` with no corpus param).
- What happened: the card shows whatever the last request in the whole process was (here a `/api/search` from another tab), labelled "LATEST TRACE" under a page that is otherwise scoped to `ragweld-drive-81854`. Summary line renders as "Policy: — • Intent: — • Final K: — • Vector: qdrant" (three dashes, no explanation); Request Cost "Unavailable / unavailable".
- Expected: select populated from `/api/corpora`, default = active corpus, request sent with `corpus_id`.
- Evidence: `web/src/components/Evaluation/TraceViewer.tsx:359` (`<option value="">All corpora</option>` only); `web/src/hooks/useTrace.ts:25-26` (`?repo=` only when selectedRepo set).

#### F-C-9 — Docked Grafana Overview makes the whole window scroll 5000px
- Severity: P2
- Surface: any route with the Dock open (observed on `eval?subtab=analysis`, `benchmark`, `grafana`)
- What I did: measured `document.documentElement.scrollHeight=5033` vs `innerHeight=1414`; `.layout` is 4978px tall; no scroller inside the dock pane.
- What happened: the dock pane does not contain its own overflow, so the page body grows to the dock content height and a window scrollbar appears (visible at far right of every screenshot); the main pane keeps its own inner scroller so the two scroll independently and confusingly.
- Expected: dock pane with `overflow:auto`, body never scrolls.
- Evidence: chain `DIV.content-scroll ov=auto 1254/1254` → `DIV.layout ov=visible sh=4978`.

#### F-C-10 — Six of twelve "Open surface" chips land on non-pages
- Severity: P2
- Surface: `grafana?subtab=overview` — link pills + Integration Matrix "Open surface"
- What I did: navigated to every href in my tab.
- What happened:
  - OTLP export `:54320/v1/traces` → plain text `405 method not allowed, supported: [POST]`
  - Tempo `:53200` → `404 page not found`
  - LiteLLM Gateway `:54000/v1` → `{"detail":"Not Found"}`
  - vLLM Endpoint `:58080/v1` → `{"detail":"Not Found"}`
  - Faro `:52347/collect` → Chrome error page (GET on a collector; fetch no-cors returns opaque, so the listener is up)
  - Langfuse `:53000` → sign-in page; Langfuse trace deep link `/project/ragweld/traces/<id>` → "You do not have access to this trace. Sign In"
  - Working: Alloy (component list, all Healthy), Mimir (admin page), Pyroscope (UI), Alertmanager (1 alert `RagweldWatchdog`), Grafana (home, anonymous), Qdrant dashboard (collections list), Tempo trace Explore link (renders the `ragweld.chat_stream` trace, 7 spans, 3.79 s).
- Expected: chips that are ingestion endpoints should not be presented as "Open surface" links (or should go to a status/UI page, e.g. Tempo `/status`, LiteLLM `/ui`, vLLM `/docs`).
- Evidence: Integration Matrix row `OTLP export` detail even says "listener present (HTTP 405 to GET)".

#### F-C-11 — "Open Prometheus" goes to a port nothing listens on
- Severity: P2
- Surface: `grafana?subtab=config` — "Open Prometheus" button (also `Infrastructure > Monitoring`)
- What I did: href is `http://localhost:9090`; `fetch('http://localhost:9090/')` and `127.0.0.1:9090` → "Failed to fetch"; Grafana `up{job="prometheus"}` = `localhost:9090` inside the compose network only.
- What happened: dead link. Prometheus is also not in the locked stack (Mimir is) yet it is Grafana's DEFAULT datasource and every `ragweld-*` panel targets datasource uid `prometheus`; the `mimir` datasource is provisioned but unused by any dashboard.
- Expected: link to a published port or remove; dashboards on the canonical datasource.
- Evidence: `web/src/components/Grafana/GrafanaConfig.tsx:444-458`; `GET :3301/api/datasources` (`prometheus … isDefault:true`, `mimir …`).

#### F-C-12 — Eval/Benchmark/Prompt Regressions dashboard shows "0%" for gauges that just mean "no run since restart"
- Severity: P2
- Surface: `grafana?subtab=dashboards` — Eval/Benchmark/Prompt Regressions
- What I did: opened the dashboard; queried its exprs.
- What happened: "Latest Promptfoo Pass Ratio" renders a big green **0%**, "Latest Eval Top-1 Accuracy" 0, from `tribrid_promptfoo_last_pass_ratio=0` / `tribrid_eval_last_top1_accuracy=0` — process-wide gauges with no corpus label (the dashboard's own note admits they "reset on API restart"). Run counters are also global: "Benchmark Runs (24h)" = 10, "Promptfoo Runs" = 2, "Eval Runs" = 1 while this corpus has 1/0/0.
- Expected: gauges absent/"No data" until a run exists; per-corpus labels or an explicit "all corpora" title.
- Evidence: `/metrics` values; exprs `tribrid_promptfoo_last_pass_ratio`, `sum(increase(tribrid_benchmark_runs_total[24h])) or vector(0)`.

#### F-C-13 — Eval Analysis "Run Settings" auto-saves without Apply; Final K persisted on keystroke
- Severity: P2
- Surface: `eval?subtab=analysis` — Run Settings › Final K (eval)
- What I did: changed Final K 5→6 (no Apply; `#save-btn` stayed disabled), reloaded.
- What happened: `retrieval.eval_final_k=6` in `GET /api/config` immediately; UI showed 6 after reload; panel also re-opened expanded (open state persisted). Restored to 5 (verified). The header copy says "Most values persist per corpus" but not which, nor that they save instantly. Also note the header arrow is `▼` when collapsed and `▶` when expanded (inverted).
- Expected: consistent Apply flow or an explicit "saved" indicator; correct chevron direction.
- Evidence: `retrieval.eval_final_k` in config; screenshot ss_9056dnh4o.

#### F-C-14 — Qdrant generation id overflows its tile
- Severity: P3
- Surface: `grafana?subtab=overview` — RETRIEVAL tile and Integration Matrix › HAYSTACK_DOCLING_QDRANT
- What I did: measured overflow.
- What happened: `ragweld_chunks_ragweld_drive_81854_fe98d8ca__a8e4a5e7` spills past the card border (article `scrollWidth 404 / clientWidth 238`; `.obs-card-metric 388/206`; `.obs-card-detail 364/189`), visibly overlapping the neighbouring column.
- Expected: `overflow-wrap:anywhere` or truncation with title.

#### F-C-15 — "legacy" labels on live features (terminology ban)
- Severity: P3
- Surface: `grafana?subtab=overview` chip `workflow=legacy_local`, WORKFLOW tile "legacy_local / Legacy local lane", Live Evidence "Workflow control plane legacy_local"; `eval?subtab=prompts` three editors titled "Base prompt (legacy)", "RAG suffix (legacy)", "Recall suffix (legacy)" (these are the live `system_prompt_base` etc. used by Benchmark per F-C-1).
- Expected: neutral names ("local lane", "Base prompt").

#### F-C-16 — Code/database-centric copy on a corpus-first product
- Severity: P3
- Surface: `eval?subtab=prompts` — "Main RAG Chat: … for answering database questions", prompt body "agentic RAG database assistant", "RAG only: Code corpora returned results", "Query Rewrite: Optimize user query for code search", "Code Enrichment: Extract metadata from code chunks"; `eval?subtab=dataset` placeholder "Question (e.g., Where is X implemented?)"; CORPUS `?` tooltip reads "Active Repository … repos.json" (glossary key REPO).
- Expected: corpus terminology (`.claude/rules/terminology.md`).

#### F-C-17 — Legibility floor violations (10–11px eyebrow/label text, dim tiers)
- Severity: P3
- Surface: `grafana?subtab=overview`: 72 leaf nodes < 12px — eyebrows "OPERATOR SURFACE", "METRICS", "TRACES", … at **10px** `rgba(180,193,210,0.72)`; chips and tile status ("Grafana", "Waiting for request", "legacy_local") at 11px `rgba(214,224,236,0.86)`; `grafana?subtab=dashboards` "DASHBOARD FAMILY" 11px. `benchmark`: every model row's second line ("ALIAS … CTX … PER 1K") 12px `rgb(113,113,122)` uppercase with 0.4px tracking; lineage buttons "SET BASELINE/SET CANARY/SET PROMOTED" 14px `rgb(100,116,139)` on `rgb(24,24,27)` (~4:1). `eval?subtab=trace`: all trace metadata 11px `rgb(113,113,122)`. `eval?subtab=analysis`: "📜 Auto"/"🗑️ Clear" 11px; disabled "Swap" at opacity 0.5.
- Expected: nothing below 11px, labels ≥ 11.5px, body ≥ 14px, no opacity on text (`~/.claude/rules/design-legibility.md`).

#### F-C-18 — Grafana Overview first paint shows false negatives for ~3 s
- Severity: P3
- Surface: `grafana?subtab=overview` (main pane and dock copy on every navigation)
- What I did: screenshot at t≈0 and t≈6 s.
- What happened: before the fetch resolves the tiles read "Grafana missing", "Not surfaced", "Gateway not active", "LiteLLM off", "Not indexed", "mode=unknown", "severity=unknown" — all wrong; they flip to reachable/on after load. The dock copy shows this on every route change.
- Expected: neutral "loading" placeholders.

#### F-C-19 — Overview mounts fire the 11-call observability fan-out four times
- Severity: P3
- Surface: `grafana?subtab=overview` with dock
- What I did: read network log after load; then counted fetches for 20 s (0 further calls, so no polling).
- What happened: `/api/observability/status|catalog|incidents`, `/api/eval|benchmark|prompts/observability/summary`, `/api/traces/latest`, `/api/loki/status`, `/api/agent/train/control-plane/status`, `/api/index/…/stats` each requested 4× on load (main pane + dock, doubled).
- Expected: one fetch shared between panes.

#### F-C-20 — Prompt-set tile truncates the id to `prompt_set__`
- Severity: P3
- Surface: `grafana?subtab=overview` — PROMPTS tile metric line
- What happened: tile shows `prompt_set__` while the ML Quality section shows `prompt_set__9c3053c24497be45818c8d63`.

#### F-C-21 — Page-load noise: Eval Analysis calls an endpoint that 404s on the empty state
- Severity: P3
- Surface: `eval?subtab=analysis`
- What happened: `GET /api/eval/results?corpus_id=ragweld-drive-81854` → `404 {"detail":"No eval runs found"}` on every load (captured by the fetch hook); `/api/eval/runs` returns `{"ok":true,"runs":[]}` fine.
- Expected: 200 with empty payload, or skip the call when runs=[].

#### F-C-22 — Benchmark "Loading…" spinner overlaps the Run button while running
- Severity: P3
- Surface: `benchmark` — Prompt panel header
- What happened: during the run a "Loading…" label + spinner renders on top of the (now "Running…") button (screenshot ss_30810g719).

#### F-C-23 — Tooltip persists over a modal
- Severity: P3
- Surface: `eval?subtab=dataset`
- What happened: the CORPUS `?` tooltip (12px text) stayed open after the pointer left and rendered at full brightness above the dimmed backdrop of the "Delete eval entry" confirm dialog (screenshot ss_2042572ke).

#### F-C-24 — Model list: 404 rows, ~39,000px tall, no search, page-level scroll
- Severity: P3
- Surface: `benchmark` — Models column
- What happened: no filter/search; the list is not its own scroll container (`scrollHeight 39009` on `.tab-content`), so finding `openai.*` means scrolling ~30 screens; the Prompt/results column scrolls away with it. Render itself was fast (`domComplete 379 ms`).

#### F-C-25 — Grafana embed: `?subtab=dashboard` deep link silently redirected; family tiles duplicate the Config preset select
- Severity: P3
- Surface: `grafana?subtab=dashboard` → `overview`; Dashboards subtab select (8 opts) vs Config preset select (10 opts incl. "Codex Session Ingest", "Reranker Training") — same setting, two option lists.

### Works as expected (brief)
- Grafana anonymous embed loads; dashboards `tribrid-overview`, 6 `ragweld-*`, `tribrid-rag-metrics`, `codex-session-ingest`, `reranker-training` exist (11 total). Both `prometheus` and `mimir` datasources answer queries (`tribrid_chunks_indexed_current=4` matches `/api/index/…/stats total_chunks=4`; graph entities 0 matches `GET /api/graph/ragweld-drive-81854/stats total_entities=0`). Loki has `ragweld_service=web` Faro streams (RUM panel query would work). Tempo trace deep link works; Alertmanager reachable with the watchdog alert.
- Range select updates the iframe (`from=now-24h`); Open link matches iframe src.
- Incidents subtab numbers match `GET /api/observability/incidents` (0/0).
- Benchmark: Run disabled until prompt + 2–4 models; "88 chars" counter; run completed in ~12 s; "Set baseline" → toast `Lineage alias "baseline" now points at bundle__ad2e...38c4c487ae23`, badge flips to ✓ BASELINE, `GET /api/lineage/aliases?corpus_id=ragweld-drive-81854` lists `baseline` and `current` → `bundle__ad2e7b1e894c38c4c487ae23`. No 17-digit floats in the UI (API `latency_ms: 2875.9687499841675` is rounded to 2876 / 2.88s / 2441.8ms).
- Eval Analysis: all run buttons untouched; Promptfoo panel expanded by default with sample-size select (10/25/50/100/All); Run Settings min/max constraints present (final_k 1–50, multi_m 1–20, rrf_k 1–200, weights 0–1 step 0.05, topk 10–200/5–100).
- Dataset: Add disabled for empty/whitespace question and for paths-only; question-only allowed; toasts "Entry added / updated / deleted"; confirm dialog for delete; list + API consistent after reload (1 entry left: salinity question with `sensor-calibration.md, observatory-overview.md`).
- Prompts: all 18 editors collapsed by default and stay collapsed after reload; Edit → textarea (13px) + Cancel/Save Changes; toast "Prompt saved successfully"; `system_prompts.main_rag_chat` persisted (668 chars) and restored to the original 655 chars. No version/diff UI exists.
- No console errors on any surface in my tab; the only ≥400 API call was F-C-21.

### Not exercised (and why)
- Run Eval / Run First Evaluation / Run Promptfoo Regression / AI analysis — forbidden (paid, multi-minute).
- Prompt "Reset" buttons — would overwrite the live prompt with a default I could not verify equals the current value.
- Dock controls (Dock Current / Choose… / Swap / Clear) — dock state is shared localStorage across all drive tabs.
- Changing the CORPUS selects on Eval Analysis / Eval Dataset — forbidden (would switch to epstein-files-1 / recall_default / aurora_acceptance).
- Grafana panel *rendering* in the background tab: stat panels sometimes painted blank because Chrome throttles hidden tabs, so panel values were verified through the datasource API instead of pixels.
- `localhost:9090` navigation was blocked by the browser tool's domain allow-list; verified dead via fetch instead.

---

## Report D — D-rag.md

## RAG tab — curious-user drive inventory (2026-08-25)

Drive corpus stayed `ragweld-drive-81854` throughout (every corpus selector verified). Every config change was reverted; final API check: `final_k=10`, `keywords_max_per_repo=50`, `scoring.path_boosts` default, `fusion={0.4,0.3,0.3,rrf_k=60,normalize=true}`, `reranker_mode=none`, `semantic_cache.bypass_if_images=true`, `graph_search.max_hops=2`. The Grafana dock occupied the right 50% of the window for the whole drive (left pane ~1020 CSS px wide), which is the realistic operator layout and is what exposed the overflow findings.

### Surfaces visited
- `rag?subtab=data-quality` — Synthetic Lab callout (3 buttons), compact corpus select (4 corpora, kept on drive), Refresh chunk summaries / Generate keywords, Chunk summaries config (2 inputs + 3 textareas + Save filters + Build), Keywords config (5 inputs), Chunk summaries list (empty). Scrolled to bottom; tooltip hovered; number control changed/verified/restored.
- `rag?subtab=retrieval` — Universal Controls (corpus, generation alias, Final K, Query Rewrites, 3 leg toggles) + 4 section cards: Search Paths (30 controls), Fusion & Scoring (17 incl. Monaco intent matrix), Generation (17 incl. Model Assignments Overview `<details>`), Ops & Tracing → Runtime Compatibility (38) and Observability & Integrations (27 + Load Latest Trace). All four walked, all `<details>` opened, 3 tooltips hovered. Changed one number, one select, one text, one toggle, one weight; verified via `GET /api/config`; restored.
- `rag?subtab=graph` — Visualization + Table views, `graph-corpus-select` (kept on drive), Max hops, Stats (5 tiles + hint), Communities, Entities (search/Reset/Filters), Visualization panel + Expand. Search run, filters expanded, Expand attempted, Table view read, Max hops changed/restored, all `/api/graph/*` endpoints probed.
- `rag?subtab=reranker-config` — Disabled/Learning/Cloud mode cards, Cloud reranker (provider, model, top-n, key status), Shared behavior (snippet chars), Runtime info + Refresh. Cloud applied and verified, restored to `none`. Learning mode NOT applied (see Not exercised).
- `rag?subtab=learning-ranker` — Learning Reranker Studio: mode warning, Synthetic callout, header actions, Mine/Train/Evaluate/Promote row (not clicked), layout presets, Setup strip, dockview panels Runs / Visualizer / Inspector (6 tabs) / Timeline + Logs. Closed a panel, Reset View, Focus Viz, Balanced, sash drag, all inspector tabs read, Show/Hide setup.
- `rag?subtab=learning-agent` — Learning Agent Studio: header, Cancel/Promote/Export/Reset telemetry (not clicked), presets, Setup strip (chips + Training Control Plane), dockview Runs / Visualizer / Inspector (Run HUD, Live Metrics, Run Overview, Run Diff, Config, Debug Prompt) / Timeline + Logs. Start Run NOT clicked (and not visible — see F-rag-1).
- `rag?subtab=indexing` — Last run status strip, contract-lock banner, target corpus select (kept on drive), path override, Corpus settings `<details>`, 4 component cards (Embedding 15 controls, Chunking 9 strategy cards + 10 controls, Tokenization 13, Graph & Options 12), Index Stats header (collapsible + Refresh), Index Now / Force reindex / Hide Logs / Delete index (not clicked), terminal. Index Now run once (Cancel first, then confirm).
- `rag?subtab=synthetic` — Recipe Builder (provider, recipe, generator/judge model, 4 numeric), Start Run / Start Full Stack (enabled only after picking models; not clicked), Runs (empty), Artifacts + Publish (empty).

### Findings

#### F-rag-1 — Learning Agent Studio: "Start Run" and half of "All corpora" are pushed outside the panel and invisible
- Severity: P2 (blocks the primary action at the default dock layout; workaround: collapse the dock)
- Surface: `rag?subtab=learning-agent` — studio header actions
- What I did: loaded the subtab with the Grafana dock open (left pane 1023 px); measured `getBoundingClientRect()` of the header buttons vs the studio section.
- What happened: `This corpus` right=1176 (visible), `All corpora` right=1288 (half clipped), `Start Run` left=1294/right=1384 while the section's right edge is 1217 — Start Run is fully outside the visible area; the screenshot shows only "THIS CORPUS | AL". No horizontal scroll is offered. The Reranker studio header fits because its description is shorter.
- Expected: header actions wrap under the description or the description shrinks; Start Run must always be reachable.
- Evidence: `web/src/components/AgentTraining/TrainingStudio.tsx:1846-1856` (`.studio-header-actions` beside a long `studio-subtitle`).

#### F-rag-2 — "Index Now" on an already-indexed corpus fails instantly with "Staging corpus not found"
- Severity: P1 (the one allowed mutating action on the drive corpus does not work; the operator gets an error run with no explanation)
- Surface: `rag?subtab=indexing` — Index Now → confirm "Start indexing"
- What I did: clicked Index Now, read the estimate dialog, Cancel (verified `runs/latest` unchanged and dialog closed), clicked Index Now again, confirmed, polled `/api/index/ragweld-drive-81854/status` every 2 s.
- What happened: status `error` after 3 s; `GET /api/index/ragweld-drive-81854/runs/latest` → `run_id=20260825T184542_8e1226b04b, status=error, started 18:45:42.936Z, completed 18:45:43.067Z, progress 0, total_files 0, error="Staging corpus not found: __staging__ragweld-drive-81854__20260825T184542_8e1226b04b"`. Terminal shows `🚀 Indexing started…`, `📦 Staged Qdrant generation …__938b57ec (dense + sparse)`, then the error. Console: `[TerminalService] SSE error for indexing_terminal`. An identical failed run (`20260825T183630_934311bec4`, someone else's attempt 9 min earlier) was already displayed as "Last run status: error" when I arrived. Index stats were not damaged (4 files / 4 chunks / 443 tokens, last_indexed 12:17:41).
- Expected: a non-forced re-index either no-ops with a clear "index is up to date" message or actually re-indexes; it must never leave an error run.
- Evidence: `server/api/index.py:771-772` — `if not force_reindex and repo_id in _STATS: return _STATS[repo_id]` returns cached stats before anything is written under `write_repo_id=staging_repo_id`; `_background_index_job` then calls `postgres.promote_staging_index` (`server/api/index.py:1555`) which raises at `server/db/postgres.py:1806-1807`. The confirm dialog (`IndexingSubtab.tsx:661-665`) gives no hint that only Force reindex will work.

#### F-rag-3 — Fusion weights are re-normalised server-side and drift; UI renders 17-digit floats and can never restore 0.4/0.3/0.3
- Severity: P1 (operator cannot set the values they typed; config silently mutates)
- Surface: `rag?subtab=retrieval` — Fusion & Scoring → 1) Fusion Strategy → Vector/Sparse/Graph Weight
- What I did: set Vector Weight 0.4 → 0.5 (single field PATCH `/api/config/fusion`), waited, read UI + API; then set it back to 0.4.
- What happened: after 0.5 the API/UI held `0.45454545454545453 / 0.2727272727272727 / 0.2727272727272727` (all three inputs show the full 17-digit value). Setting 0.4 back produced `0.42307692307692313 / 0.28846153846153844 / 0.28846153846153844`. Only a manual PATCH with all three weights restored `0.4/0.3/0.3`. Apply button stayed disabled throughout (auto-save).
- Expected: either normalise on the client with rounding (2–3 dp) and show the operator the resulting split, or accept the three weights as one edit; never render >2 dp.
- Evidence: `server/models/tribrid_config_model.py` FusionConfig `validate_weights_sum_to_one` (≈4641-4654) divides each weight by the sum when the total is outside 0.99–1.01; `web/src/components/rag/RetrievalSubtab.tsx:969-1010` PATCHes one field at a time with `snapNumber` (no rounding). Note: the inputs are `disabled` unless Fusion Method = weighted; I drove them with a synthetic input event, the same drift occurs in weighted mode.

#### F-rag-4 — UI min/max exceed the Pydantic `ge`/`le` bounds; the resulting 422 is shown as a bare "Request failed with status code 422" and UI/API disagree
- Severity: P2
- Surface: `rag?subtab=retrieval` (and Ops & Tracing) — number inputs
- What I did: typed Final K = 150 (UI `max=200`).
- What happened: PATCH `/api/config/retrieval` → 422; red "Configuration Error — Request failed with status code 422" banner with Retry Load / Dismiss, footer "Apply All Changes *" + "Error: Request failed with status code 422"; the input kept 150 while `GET /api/config` kept 10 until I typed a valid value. No field or bound is named.
- Bound mismatches found by comparing every control's `min/max` with `model_fields` metadata: Final K 1–200 vs le 100; Vector Top-K min 1 vs ge 10; Sparse Top-K min 1 vs ge 10; Graph Top-K 1–200 vs 5–100; Eval Final K max 100 vs le 50; Multi Query M max 20 vs le 10; LangGraph Max Rewrites min 0 vs ge 1; Hydration Max Chars 200–20000 vs 500–10000; Filename Boost (Exact) min 0 vs ge 1.0; Filename Boost (Partial) max 5 vs le 3.0; Trace Retention 1–1000 vs 10–500; Alert Webhook Timeout max 60 vs le 30; (Synthetic Lab) Curate threshold 0–10 has no model bound, Cloud Top-N 1–100 vs le 200 (stricter, fine).
- Expected: UI bounds generated from the model constraints; validation errors name the field and bound.
- Evidence: `RetrievalSubtab.tsx:455-460, 619-627, 650-657, 695-701, 514-520, 613-619, 640-646, 492-498` etc.; `uv run python` dump of `RetrievalConfig/…model_fields` metadata.

#### F-rag-5 — Retrieval exposes tunables that nothing in the server reads (dead config presented as live controls)
- Severity: P2 (misleads the operator; the "Retrieval Balance" section is a no-op)
- Surface: `rag?subtab=retrieval` — Ops & Tracing → 3) Retrieval Balance, 2) Compatibility & Evaluation, 1) Hydration; Search Paths Vector/Sparse Top-K
- What I did: grepped `server/` (excluding `server/models/`) for each key.
- What happened: zero references for `retrieval.topk_dense`, `retrieval.topk_sparse`, `retrieval.bm25_weight`, `retrieval.rrf_k_div`, `retrieval.langgraph_final_k`, `hydration_mode` (both `retrieval.hydration_mode` and `hydration.hydration_mode`), `graph_storage.graph_search_top_k`. Each duplicates a live field shown elsewhere on the same page: Vector Top-K (`vector_search.top_k`=50) vs TopK Dense (75); Sparse Top-K vs TopK Sparse; Fusion weights vs "Retrieval BM25/Vector Weight"; RRF K vs RRF K Div; `graph_search.max_hops/include_communities/top_k` vs `graph_storage.max_hops/include_communities/graph_search_top_k`.
- Expected: dead keys removed from the model and UI (replacement-only rule), or clearly marked; one owner per tunable.
- Evidence: `RetrievalSubtab.tsx:150-180` (useConfigField list), `tribrid_config_model.py:3701+` RetrievalConfig; grep counts above.

#### F-rag-6 — "Apply All Changes" is not the save path on any RAG subtab; every control auto-persists on change, and the button only lights up after a failed PATCH
- Severity: P2 (label misleads: there is no batch/preview; a typo is live immediately)
- Surface: all RAG subtabs — footer `#save-btn`
- What I did: changed Max keywords per corpus 50→60 on Data Quality; 600 ms later the footer read "Saving..."; API already had 60; reload confirmed 60; Apply remained disabled the whole time. Same for Normalize Scores select, Path Boosts text, Reranker mode cards, Force reindex.
- What happened: `useConfigField.setValue` calls `patchSectionDebounced` immediately (`web/src/hooks/useConfig.ts:78-121`); `isDirty` is `JSON.stringify(config) !== JSON.stringify(persisted)` (`web/src/hooks/useApplyButton.ts:35-38`) so it only becomes true when a PATCH is rejected (F-rag-4). Controls whose change never enables Apply because they are UI-local: Graph "Max hops", Synthetic Lab recipe/model/number inputs, Intent Matrix editor (has its own Apply Changes), dock layout presets (these PATCH `/api/config/ui` directly and flash "Saving...").
- Expected: rename/remove the footer button or make it the real commit point.

#### F-rag-7 — Synthetic Lab: Judge Model select overflows the panel and puts a horizontal scrollbar on the whole RAG pane
- Severity: P2
- Surface: `rag?subtab=synthetic` — Recipe Builder → Judge Model
- What I did: measured `.rag-subtab-content` scrollWidth/clientWidth and the select's right edge.
- What happened: scrollWidth 1172 > clientWidth 1088 (`hscroll=true`); Judge Model `<select>` right=1342 vs panel right 1234/1258. A horizontal scrollbar appears under the pane (visible in screenshot). Each picker holds 405 options grouped by provider.
- Expected: `min-width:0`/`width:100%` on the picker row so the two model selects share the row.
- Evidence: `web/src/components/rag/SyntheticLabSubtab.tsx:63-72` (`.setting-row` select) wrapped by `<div style={{flex:1}}>` at `:466-483`.

#### F-rag-8 — Learning Reranker Studio setup shows a raw HTTP error where the Recommended Metric should be
- Severity: P2
- Surface: `rag?subtab=learning-ranker` — Setup strip → Recommended Metric
- What happened: cell reads "Request failed with status code 404". `GET /api/reranker/train/profile?corpus_id=ragweld-drive-81854` → 404 `{"detail":"No eval_dataset entries found for corpus_id=ragweld-drive-81854"}`. Neighbouring Triplet status reads `triplets=0 · queries=12`.
- Expected: friendly empty state ("No eval dataset yet — build one in Eval Analysis / Synthetic Lab") instead of the axios message.
- Evidence: `web/src/components/RerankerTraining/TrainingStudio.tsx:2042` renders `profileError` verbatim; `server/api/reranker.py:2664`.

#### F-rag-9 — Graph Explorer for this corpus is empty and the hint points at a control that is not on this page
- Severity: P2 (priority surface for the operator; the visualizer cannot be opened at all)
- Surface: `rag?subtab=graph`
- What I did: read stats/communities/entities; searched "Pelican"; expanded Filters; clicked Expand; opened Table view; probed every `/api/graph/ragweld-drive-81854/*` route.
- What happened (exact copy):
  - Stats tiles: Entities 0, Relationships 0, Communities 0, Documents 4, Chunks 4 (matches `GET …/stats`: `total_entities 0, total_relationships 0, total_communities 0, total_documents 4, total_chunks 4, entity_breakdown {}, relationship_breakdown {}`).
  - Hint under stats: "Chunk graph is present, but the entity graph is empty. Enable Semantic KG (concepts + relations) or index code entities to populate entities/communities." — no link; the toggle is the "Neo4j GraphRAG semantic KG" checkbox in Indexing → Graph & Options (`graph_indexing.semantic_kg_enabled=false`) and needs a Force re-index (F-rag-2 makes a plain re-index fail).
  - Communities: "No communities found." (`GET …/communities` → `[]`). Members of a community: `GET …/community/0/members` → 200 `[]`.
  - Entities: "0 shown"; after searching "Pelican" (`GET …/entities?limit=200&q=Pelican` → 200 `[]`) the panel still says "Search for entities to begin, or select a community." — no "no results for 'Pelican'" state. Filters expands to headings "Entity types" / "Relationship types" with zero checkboxes (breakdowns empty) and no explanation.
  - Visualization: "0 nodes • 0 edges", legend person/org/location/event, "Select an entity (or a community) to render a subgraph." "Tip: click a node to load its neighborhood." Expand button (title "Expand graph to fullscreen view") is `disabled` because `filteredEntities.length === 0` (`GraphSubtab.tsx:1004-1021`) with no tooltip explaining why; the fullscreen overlay (`aria-label="Fullscreen graph visualization"`, scroll-zoom/drag-pan/click-node/Esc per `:1309`) can therefore not be reached for this corpus, so node click / zoom / pan could not be exercised.
  - Table view: same panels plus "Details — Select a community or entity to view details."
  - `GET …/entity/nonexistent` and `…/neighbors` → 404 `{"detail":"Entity not found"}`; `POST …/query` → 422 `Field required: cypher` (raw Cypher endpoint, not used by the UI).
- Expected: the hint should link to the Semantic KG toggle and say a re-index is required; a "no matches" state; legend should include `concept` (the default `semantic_kg_allowed_entity_types` includes concept; the fullscreen legend at `GraphSubtab.tsx:1168` has it, the inline legend at `:991` does not).
- Evidence: `web/src/components/rag/GraphSubtab.tsx:677-681, 728-729, 888-890, 984-1021, 1080`; `web/src/hooks/useGraph.ts:118-140`; `server/api/graph.py:54-135`.

#### F-rag-10 — Graph "Max hops" is a UI-local value that looks like the config field
- Severity: P3
- Surface: `rag?subtab=graph` — Max hops (1–5)
- What happened: set 3, waited 3 s: `graph_search.max_hops` and `graph_storage.max_hops` both still 2; Apply never enabled. It only scopes the neighbour fetch (`useGraph.ts:161-173`). No help icon.

#### F-rag-11 — Graph visualization header wraps into a 33 px column at this pane width
- Severity: P3
- What happened: the "0 nodes • 0 edges" element measured 33×70 px (four lines: "0 / nodes / • 0 / edges") next to the legend; visible in screenshot.

#### F-rag-12 — Learning Agent Studio labels the live lane "legacy"; breadcrumb/route says "Learning Ranker"
- Severity: P3 (terminology bans)
- What happened: Setup → Training Control Plane: "Target lane: Legacy local", chip "legacy"; API `GET /api/agent/train/control-plane/status` → `lane="legacy_local", ready=false, workflow_backend=local, tracking_backend=local, execution_backend=mlx_qwen3`; components Flyte "disabled — Local workflow lane active; runs execute in-process without an orchestrator.", MLflow "disabled — Local run/artifact truth still active.", Unsloth "disabled — Execution backend is mlx_qwen3."; operator_hint "Learning Agent: runs use the local training lane without an orchestrator; run truth stays in local run files; training executes on the host mlx_qwen3 backend. The full target lane is workflow=flyte, tracking=mlflow, execution=unsloth (Unsloth needs a CUDA host)." The UI copy matches the API word for word (good), but "legacy" is used as the name of the live lane, also in the Grafana dock chip `workflow=legacy_local`. Breadcrumb "RAG / Learning Ranker" and route title use "Ranker" while the page heading says "Learning Reranker Studio".
- Evidence: `web/src/components/AgentTraining/ControlPlaneStatus.tsx:24,29`; `web/src/config/routes.ts:124`; `web/src/components/Dashboard/HelpSubtab.tsx:121`.

#### F-rag-13 — Banned term "cards" surfaces as the synthetic recipe id and in the Data Quality shortcut URL
- Severity: P3
- What happened: Data Quality "Semantic Summaries" button navigates to `rag?subtab=synthetic&synthetic_context=data-quality&synthetic_recipe=semantic_cards&synthetic_autorun=0` (and drops `corpus=` from the URL, though the store keeps the drive corpus). Synthetic Lab's Recipe select shows raw ids `eval_dataset, semantic_cards, triplets, keywords, autotune_retrieval, full_stack`; Provider shows `grounded_qa`. Artifact kinds are `semantic_cards_jsonl` (labelled "Semantic Summaries" only in the artifacts table).
- Evidence: `web/src/components/rag/SyntheticCallout.tsx:24`; `SyntheticLabSubtab.tsx:437-451, 88-97`.

#### F-rag-14 — "legacy" wording on live indexing options
- Severity: P3
- What happened: Chunking strategy card "Greedy — Legacy fixed-char windowing using the greedy fallback target."; source also has "Fixed chars … (fallback, legacy)". Ops & Tracing sections are named "Runtime Compatibility" / "Compatibility & Evaluation" with copy "compatibility gates used by LangGraph and fallback policies".
- Evidence: `IndexingSubtab.tsx:64-67`; `RetrievalSubtab.tsx:1411, 1470-1472, 1633`.

#### F-rag-15 — Data Quality textarea placeholders render a literal "\n"
- Severity: P3
- What happened: placeholders read `node_modules\nvenv\ndist`, `*.min.js\n*.lock\n**/*.test.ts`, `deprecated\nlegacy\nTODO` (JSX attribute strings do not process escapes).
- Evidence: `DataQualitySubtab.tsx:281, 291, 302`; zoom screenshot `/var/folders/fh/tnbpt3jd26l_4b09q54m033c0000gn/T/claude-chrome-screenshots-HxghRx/screenshot-1787682562402-15.png`.

#### F-rag-16 — Legibility floor: 11 px muted grey helper text everywhere
- Severity: P3
- What happened: measured `getComputedStyle`: section descriptions, card descriptions, stats labels, run_id/replayed-events, "0 shown", "Entity types", tips are 11 px at `rgb(113,113,122)` on the dark panel (Retrieval: 9 nodes at 11 px, 22 at 12 px, 411 at 13 px); "Synthetic Lab status=idle" 11.52 px with opacity 0.8 on the value; help `?` icons 11 px. Body copy is 13 px (floor says ≥14).
- Evidence: `RetrievalSubtab.tsx:551` (`fontSize: 11`), `GraphSubtab.tsx` stat labels, `IndexingSubtab.tsx` helper copy.

#### F-rag-17 — Disabled toggle has no disabled affordance and can be flipped without persisting
- Severity: P3
- Surface: Retrieval → Ops & Tracing → Semantic Cache → "Bypass if Images" (disabled while Cache Enabled is off)
- What happened: `input.disabled=true` but the track is painted in the "on" colour `rgb(100,116,139)`, cursor `pointer`, opacity 1. `form_input` flipped the DOM state (UI showed off) while the API stayed `true` — UI/API disagree until reload.
- Evidence: `RetrievalSubtab.tsx:1849-1856`.

#### F-rag-18 — Trace Preview shows "Policy: — • Intent: — • Final K: —" for a real trace
- Severity: P3
- What happened: Load Latest Trace → "Trace refreshed at 12:34:16 PM / Routing Trace / Policy: — • Intent: — • Final K: — • Vector: qdrant / Events (3): chat.request, retrieval.fusion, chat.response". `GET /api/traces/latest` has `route_summary`, `cost_summary`, `external_links`, `events[]` (kind/ts/msg/data) but no policy/intent/final_k → the placeholders are permanent.
- Evidence: `RetrievalSubtab.tsx:2220-2240`.

#### F-rag-19 — Index estimate disagrees with the real index and the same "Force reindex" checkbox is repeated in all four cards
- Severity: P3
- What happened: confirm dialog "Start indexing? — Index estimate for "ragweld-drive-81854" — Files: 4 • Size: 2.12 KiB — Tokens (est): 543 • Chunks (est): 2 — Embedding: huggingface/BAAI/bge-small-en-v1.5 (deterministic, skip_dense=no) — Cost (est): $0.00 • Time (est): 12.0s–24.0s"; the live index has 4 chunks / 443 tokens. "Force reindex" appears in Embedding, Chunking, Tokenization and Graph cards (same field). Toggling it hides the lock banner and enables provider/model/dimension/tokenizer fields (works); restored to off.

#### F-rag-20 — Reranker cloud-mode layout
- Severity: P3
- What happened: in Cloud mode the Model select + "Context: 1,047,576 tokens" sit in a second column at a different baseline from Provider / Cloud Top-N and the green "LITELLM_API_KEY: Configured — Secret is present in the backend environment and ready to use." box floats mid-column (screenshot). Provider options: cohere, litellm; Model options: openai.gpt-4.1-nano, openai.gpt-5.6-luna. Mode persisted (`reranker_mode=cloud`) and restored to `none`; runtime info `Enabled: false / Device: cpu / Model: —` from `GET /api/reranker/info`.

#### F-rag-21 — Code-repo concepts presented to a document corpus
- Severity: P3 (product honesty)
- What happened: Fusion & Scoring → Layer Weights (GUI / Retrieval / Indexer / Vendor Penalty / Freshness), Source Preference (Vendor Mode `prefer_first_party`, Path Boosts `/gui,/server,/indexer,/retrieval`), Intent Overrides (gui/eval/infra/server/indexer matrix; help text "…for the intent;< 1.0 penalizes" missing a space), Data Quality default exclude dirs (`node_mcp`, `web/dist`, `gui`, …) and the "Max chunk summaries" tooltip ("miss important modules") all assume a code repository; nothing on the Aurora corpus maps to them. Heading "📦 Code Indexing" on the Indexing subtab.

### Works as expected (brief)
- Data Quality: compact corpus selector shows 4 corpora and stayed on Aurora drive corpus; number edit 50→60 persisted through reload and via `GET /api/config` (`keywords.keywords_max_per_repo`), restored to 50; Refresh chunk summaries → `GET /api/chunk_summaries?corpus_id=…` 200 `{chunk_summaries:[], last_build:null}` → "No builds yet. / No chunk summaries to show."; tooltip for Max Chunk Summaries renders glossary content with source links; no failed API calls, no console errors.
- Retrieval: every Search Paths / Fusion / Generation / Ops control value matched `GET /api/config` on load; select (Normalize Scores → Disabled → Enabled), text (Path Boosts) and number edits persisted and were restored; Fusion Method tooltip content correct; Model Assignments Overview lists Chat Answer/Enrichment/Query Expansion/Rewrite = litellm ragweld-local, Semantic KG LLM = openai.gpt-5.6-luna, Embedding huggingface BAAI/bge-small-en-v1.5, Reranker none (disabled), all OK; LiteLLM Client Key + Langfuse public/secret show "Configured"; Tracing Mode `otel_langfuse`, OTLP endpoint/Tempo/Alloy/Langfuse URLs populated; Load Latest Trace works.
- Graph: corpus select kept on drive; every graph endpoint answers 200 with consistent empty payloads; Table/Visualization toggle works; 404s only for deliberately bogus entity ids.
- Reranker: mode cards write `reranking.reranker_mode`; key hint shows for cloud mode; Refresh hits `/api/reranker/info` 200.
- Learning Reranker Studio: mode warning text exactly reflects `reranker_mode=none`; dockview close/Reset View/Focus Viz/Balanced/sash drag all work (Visualizer 499→380 px, Inspector 278→397 px after drag); inspector empty states: Run HUD "Select a run.", Live Metrics "No metric events yet. run_id=— running=false task=— progress=0%", Run Overview "Select a run to see details.", Run Diff "Need at least two runs to compare.", Debug Score Pair "Run a score probe to inspect backend output."; Timeline + Logs "No events yet."; Runs "No runs yet." — all consistent with no runs.
- Learning Agent Studio: readiness copy matches the control-plane API exactly (F-rag-12 is only about the word "legacy"); chips Corpus/Backend mlx_qwen3/Workflow local/Tracking local/Base model mlx-community/Qwen3-4B-Instruct-2507-4bit/Dataset "(uses evaluation.eval_dataset_path)"; Inspector Config tab exposes backend (mlx_qwen3/unsloth), workflow (local/flyte), tracking (local/mlflow), base model, adapter dir, dataset path, Synthetic Dataset Builder; Run Diff / Overview / Live Metrics empty states as above.
- Indexing: contract-lock banner present and correct ("Index contract is locked for this corpus. Enable Force reindex to edit provider/model/dimension/tokenizer fields."); path override empty with "Using: /Users/davidmontgomery/ragweld/tests/fixtures/acceptance_corpus"; Index Stats header collapses/expands, Refresh → `GET …/stats` and tiles match the API (4 files, 4 chunks, 443 tokens, huggingface, BAAI/bge-small-en-v1.5, 384d, 8/25/2026 12:17:41 PM); Cancel on the confirm dialog leaves `runs/latest` untouched; Hide/Show Logs toggles; REPO_PATH tooltip renders; embedding provider cards, tokenization and sparse contract fields are correctly disabled under the lock.
- Synthetic Lab: `GET /api/synthetic/runs?corpus_id=…&limit=50` 200 → "No synthetic runs yet." / "Select a run to inspect artifacts."; Start buttons stay disabled until both generator and judge are picked (caption "Select both generator and judge models to enable start actions."); `synthetic.quality_gate/generator/judge` config exists in the API (`top1_min 0.4, sample_size 50, temperature 0, max_tokens 1200/400, concurrency 4`) but is not editable on this page.

### Not exercised (and why)
- Graph visualizer node click / zoom / pan / fullscreen: impossible on this corpus — 0 entities, Expand disabled (F-rag-9). Did not switch to a populated corpus (protocol: never change the active corpus).
- Reranker "Learning" mode: not applied because with drive-chat running chat traffic it would make the next request load the MLX reranker (model-load ban / crash history). Fields documented from source (`RerankerConfigSubtab.tsx:251-330`): Model path, Backend (auto (prefer MLX Qwen3) / mlx_qwen3 (force)), Base model, Alpha 0–1, Top-N 10–200, Batch, Max len, Unload after sec.
- Learning Reranker: Mine Triplets / Train / Evaluate / Promote / Start Run / Debug Score Pair probe; Learning Agent: Start Run / Cancel / Promote / Reset telemetry; Pop out Viz/Logs (opens popups). All banned or state-changing.
- Data Quality: Generate keywords (banned), Build chunk summaries (not in the allowed-mutation list), Delete summary (no summaries).
- Indexing: Delete index, Force reindex + Index Now (would rebuild the drive corpus with a new contract), path override edits, Generate Keywords in Corpus settings.
- Synthetic Lab: Start Run / Start Full Stack / Publish (no runs).
- Generation Alias / Enrichment Alias changes: would redirect other agents' live chat traffic mid-drive.

---

## Report E — E-infra-admin.md

## Infrastructure + Admin — curious-user drive inventory (2026-08-25)

Driver: drive-infra-admin (tab 1950917900, closed at end). Corpus: `ragweld-drive-81854`. Repo read-only; no repo file touched. All Start/Stop/Restart controls left unclicked; non-existent routes probed with HEAD only.

Screenshot dir: `/var/folders/fh/tnbpt3jd26l_4b09q54m033c0000gn/T/claude-chrome-screenshots-HxghRx/` (referred to below as `SS/`).

### Surfaces visited
- `infrastructure?subtab=services` — read-only container-state grid: Container State banner, 2 host-process tiles, 7 service groups / 24 tiles, 1 Refresh button, 0 links, 0 detail drawers. Scrolled to bottom (2639px). All 22 managed containers match `GET /api/docker/services`; host processes match `GET /api/dev/status`.
- `infrastructure?subtab=docker` — daemon/runtime/count header, 23 service tiles (22 running + "Ragweld API — Missing"), 22×Restart/Stop/Logs, 1 Refresh. Opened Loki + Grafana Logs modals, closed both. No stats (CPU/mem) surface exists. Scrolled to bottom (2495px).
- `infrastructure?subtab=mcp` — 3 transport tiles, ↻ Refresh, MCP spec link, details block, HTTP controls (Start/Stop/Restart/Check), stdio test (Run test). Clicked ↻ Refresh, Check, Run test only. Hovered the `?` tooltip. No config fields, no copy-to-clipboard control exists on this subtab.
- `infrastructure?subtab=paths` — 7 DB-endpoint fields (6 editable + env-only password status), 3 corpus-metadata fields, Save Configuration. Hovered POSTGRES_URL and neo4j_database_mode tooltips (all 7 tooltip names resolve in the 428-term glossary). Edited + saved + restored corpus name. DB fields untouched.
- `infrastructure?subtab=monitoring` — ObservabilityOperatorDeck (chips, 12 deep links, 9 status tiles, integration matrix, live evidence, ML quality, incident feed) + 7 threshold number inputs + Open Grafana / Open Prometheus buttons + Save Alert Configuration. Scrolled to bottom (5189px). Clicked Save (endpoint 404; harmless).
- `admin?subtab=general` — does not exist; `useSubtab` rewrote the URL to `subtab=basic`. Real Admin subtabs: Basic / Advanced / Raw / Dependencies (`web/src/config/routes.ts:192-197`). "Secrets" and "integrations" live in Dependencies.
- `admin?subtab=basic` — Configuration Center: 7 surface sections, 175 registry fields (24/11/28/43/13/16/40), each with its own Save (no slider kind exists). Changed one toggle, one integer, one text, one enum; verified after reload and via API; restored. Scrolled to bottom.
- `admin?subtab=advanced` — Advanced Explorer: search + 4 filter selects over 451 fields (all rendered at once). Exercised search (`neo4j` → 50) and scope=Global (13 with search, 101 alone), reset to 451.
- `admin?subtab=raw` — Raw Section Editor: section select (30 sections), editable JSON textarea, Save Section. Inspected only (whole-section replace not exercised).
- `admin?subtab=dependencies` — 13 integration rows + 14 env-only secret rows (configured/missing chips). Inspected only; no secret value in DOM or in `GET /api/config/readiness`.
- `/web/evaluation`, `/web/nonsense` — empty main pane, breadcrumb "Home", no not-found message.

### Findings

#### F-E-1 — Monitoring alert thresholds are wired to an endpoint that does not exist (all seven inputs empty, Save always fails)
- Severity: P1
- Surface: `infrastructure?subtab=monitoring` — Performance Thresholds / API Anomaly Alerts / Save Alert Configuration
- What I did: opened the subtab; read the 7 inputs; clicked "Save Alert Configuration".
- What happened: on load `GET /api/monitoring/alert-thresholds` → 404, so every input renders with value `""` (min/max/step attributes present, no defaults). Save → `POST /api/monitoring/alert-thresholds` → 404; banner "Error saving alert configuration: Request failed with status code 404". `HEAD /api/monitoring/alerts` also 404. No `monitoring/` route exists anywhere under `server/` (grep of `server/**/*.py` for `alert-thresholds|monitoring/` returns nothing).
- Expected: either a real thresholds endpoint (values loaded, save persists) or the panel removed. Per AGENTS.md this is a "done" surface that is dead.
- Evidence: `SS/screenshot-1787682728220-24.jpg`, `SS/screenshot-1787682728220-25.jpg`; network: `GET /api/monitoring/alert-thresholds 404`, `POST … 404`; source `web/src/stores/useAlertThresholdsStore.ts:93,131`, `web/src/components/Infrastructure/MonitoringSubtab.tsx:32-57`.

#### F-E-2 — "Open Grafana Dashboard" / "Open Prometheus" buttons target ports where nothing listens
- Severity: P1
- Surface: `infrastructure?subtab=monitoring` — Grafana Metrics panel
- What I did: read the handlers; curl-probed the targets and the real containers.
- What happened: buttons call `window.open('http://127.0.0.1:3000')` and `window.open('http://127.0.0.1:9090')`. curl to :3000 and :9090 → connection refused. Real bindings: `ragweld-grafana-1 127.0.0.1:3301->3000`, `ragweld-prometheus-1 127.0.0.1:59090->9090`. The deck 40px above these buttons links Grafana correctly to :3301.
- Expected: buttons resolve the configured Grafana/Prometheus base URLs (the deck already has them) or are removed.
- Evidence: `web/src/components/Infrastructure/MonitoringSubtab.tsx:304,316`; `SS/screenshot-1787682728220-25.jpg`.

#### F-E-3 — MCP subtab: HTTP status, Start/Stop/Restart and "Run test" all target routes that do not exist; errors are misattributed
- Severity: P1
- Surface: `infrastructure?subtab=mcp` — MCP HTTP server controls, stdio MCP test
- What I did: loaded the subtab; clicked ↻ Refresh, Check, Run test; HEAD-probed the POST routes (never clicked Start/Stop/Restart).
- What happened:
  - On load and every 30 s (`useMCPServer.ts:104-106`): `GET /api/mcp/status` 200 + `GET /api/mcp/http/status` 404 → the controls box says "HTTP status unavailable" directly beneath a tile that says "Python HTTP • running • 127.0.0.1:58012/mcp/". Contradictory.
  - Button → endpoint map (`web/src/services/MCPServerService.ts`): Start → `POST /api/mcp/http/start`; Stop → `POST /api/mcp/http/stop`; Restart → `POST /api/mcp/http/restart`; Check → `GET /api/mcp/status` + `GET /api/mcp/http/status`; Run test → `GET /api/mcp/test`. HEAD results: `/api/mcp/http/start` 404, `/stop` 404, `/restart` 404, `/api/mcp/test` 404, `/api/mcp/status` 405 (GET only, exists). Server only defines `/mcp/status` and `/mcp/rag_search` (`server/api/config.py:638,699`).
  - Clicking "Run test" → 404 → red banner **"Failed to load MCP status: {"detail":"Not Found"}"** (the hook stores the raw response body as `error` and the component prefixes the wrong verb, `MCPSubtab.tsx:115`). The result `<pre>` stays "—".
  - Copy says "HTTP transports will appear here when implemented" while the tile shows one running; controls copy says "(if compiled in)".
- Expected: controls that either work against real routes or are not rendered; error text naming the action that failed.
- Evidence: `SS/screenshot-1787682507802-11.jpg`, `SS/screenshot-1787682548148-13.jpg`; `__apiFails`: `404 /api/mcp/http/status` ×N, `404 /api/mcp/test`.

#### F-E-4 — Docker "Logs" shows "No logs available." for containers that only log to stderr (Loki, Postgres)
- Severity: P2
- Surface: `infrastructure?subtab=docker` — Logs modal
- What I did: clicked Logs on Loki; fetched `/api/docker/services/{svc}/logs?tail=20` for six services.
- What happened: loki `success:true, logs:""`; postgres `success:true, logs:""`; grafana 4807 chars, litellm 1874, neo4j 2762, qdrant 4596. Loki is "Up 2 days" — it certainly has logs; `docker logs` writes them to stderr and the endpoint returns only `res.stdout` (`server/api/docker.py:426`), so the modal claims there are none.
- Expected: merge stdout+stderr (or `2>&1`) so every running container shows its tail.
- Evidence: `SS/screenshot-1787682474023-8.jpg`; response `{"success":true,"logs":"","error":null}`.

#### F-E-5 — Unknown routes render a blank main pane with breadcrumb "Home" and no not-found message
- Severity: P2
- Surface: `/web/evaluation?corpus=…`, `/web/nonsense?corpus=…`
- What I did: navigated to both.
- What happened: `TabRouter` has no catch-all route; `Routes` matches nothing, the main pane is empty (only the right-hand Grafana dock renders), breadcrumb shows "Home", no sidebar item is active, no redirect, no console error. `/web/evaluation` is a plausible typo for `/web/eval` and yields the same silent blank.
- Expected: a not-found view with links, or a redirect to `/dashboard` like the `/` route (`TabRouter.tsx:34`).
- Evidence: `SS/screenshot-1787683028414-45.jpg`, `SS/screenshot-1787683028414-46.jpg`.

#### F-E-6 — Registry says `graph_storage.*` fields are `global` scope, but Basic saves them as a corpus override only
- Severity: P2
- Surface: `admin?subtab=basic` — Graph section, `graph_storage.community_algorithm` (enum)
- What I did: changed louvain → label_propagation, Save; read `GET /api/config?corpus_id=ragweld-drive-81854` and `GET /api/config`; restored.
- What happened: request was `PATCH /api/config/graph_storage?corpus_id=ragweld-drive-81854`. Corpus config became `label_propagation`; global config stayed `louvain`. Full deep-diff of global config before/after all four saves: no change. The Advanced tab shows the chip "global" on 101 fields (`tracing.*`, `graph_storage.*`, `mcp.enabled`, …) — the UI tells the operator the value is global while the write path is per-corpus. Either the chip lies or the write path is wrong.
- Expected: `scope: global` fields written without `corpus_id` (and reflected in `GET /api/config`), or the chip removed.
- Evidence: JS result `{"enum":{"before":"louvain","apiCorpusAfter":"label_propagation","apiGlobalAfter":"louvain"}}`; `web/src/components/Admin/configControlPlane.tsx:404-408` (`saveField` → `patchSection` always corpus-scoped via `withCorpusScope`, `web/src/api/config.ts:29-31`).

#### F-E-7 — Postgres DSN with embedded password is shown in cleartext and returned by `GET /api/config`
- Severity: P2
- Surface: `infrastructure?subtab=paths` — PostgreSQL DSN field; `admin?subtab=raw` (indexing section); API
- What I did: read the field; scanned corpus config JSON for credential patterns.
- What happened: `indexing.postgres_url = postgresql://postgres:postgres@localhost:5432/tribrid_rag` is a plain `<input type="text">` (data-testid `postgres-url`) and the same string is in `GET /api/config`. Meanwhile `admin?subtab=dependencies` lists `POSTGRES_PASSWORD` as an env-only secret ("configured") and Paths says "Neo4j credentials now stay env-only". Two contradictory secret policies for the two databases; the Postgres one leaks through DOM and API. (Value is the dev default, but the pattern is what leaks.)
- Expected: DSN without credentials + env-only password status like Neo4j, or a masked field.
- Evidence: `SS/screenshot-1787682590658-17.jpg`; `PathsSubtab.tsx:111-128`; config-scan hit `('indexing.postgres_url', 'postgresql://postgres:postgres@…')`.

#### F-E-8 — Every per-field Save re-fetches the whole 451-field registry and readiness
- Severity: P3
- Surface: `admin?subtab=basic` (and Advanced)
- What I did: watched the network during four saves.
- What happened: each save → `PATCH /api/config/<section>` then `GET /api/config/registry` + `GET /api/config/readiness` + `GET /api/config` (`ConfigBasicsSubtab.tsx:17-20` `saveAndRefresh` → `reload()`). A toggle flip costs three round-trips plus a re-render of 175 cards; on load the registry was fetched 10 times in one session (network log).
- Expected: refresh readiness only, or debounce.
- Evidence: network log entries 25-42 in the `/api/config` capture.

#### F-E-9 — Toggle saves give no "Saved" confirmation; only Save-button fields do
- Severity: P3
- Surface: `admin?subtab=basic` — boolean fields
- What I did: flipped `chat.benchmark.enabled`.
- What happened: PATCH fired, label switched to "Disabled", but no "Saved" status appears (status is only set inside `commit()` for the Save button, `configControlPlane.tsx:214`; the checkbox path calls `onSave` directly). Errors would show, success does not.
- Evidence: JS `toggle.status:false`.

#### F-E-10 — Switching Infrastructure subtabs keeps the previous scroll offset (Docker opened at the bottom of its list)
- Severity: P3
- Surface: `infrastructure?subtab=services` → Docker
- What I did: scrolled Services to the bottom, clicked the Docker subtab.
- What happened: `#tab-infrastructure` is the scroll container and is not reset; Docker rendered with the Langfuse/MLflow tiles in view and the header off-screen.
- Expected: scrollTop reset on subtab change.
- Evidence: `SS/screenshot-1787682441543-7.jpg`.

#### F-E-11 — Docker logs modal: not a full-viewport modal, Escape does not close it, focus is not moved, title wraps, opens at the top of the log
- Severity: P3
- Surface: `infrastructure?subtab=docker` — Logs dialog
- What I did: opened Loki and Grafana logs; pressed Escape; measured rects.
- What happened: overlay rect `[170,98,1071×1194]` inside a 2174×1414 viewport — `position: fixed` is trapped by `.tab-content { transform: translateZ(0) }` (`web/src/styles/micro-interactions.css:837`), so the dock on the right stays fully interactive while the "modal" is open. Escape → dialog still open; `document.activeElement` = BODY. `<h3>` is 100px wide so "Grafana logs" wraps to two lines and the Close button stretches across the header. Grafana logs: 201 lines, `pre.scrollTop=0` of 16285px — the newest lines (bottom) are 15 screens away.
- Expected: portal to body, Escape/focus trap, `aria-labelledby` title on one line, scroll to bottom for a log tail.
- Evidence: `SS/screenshot-1787682474023-8.jpg`; `DockerSubtab.tsx:214-234`.

#### F-E-12 — Legibility: muted labels/help text at 3.96:1 contrast; deck section labels at 10px
- Severity: P3
- Surface: Paths, Monitoring, Services, Docker (all Infrastructure subtabs), Monitoring deck
- What I did: measured with `getComputedStyle`.
- What happened: `<label>` (13px uppercase) and `.small` (12px) use `rgb(113,113,122)` on `rgb(15,15,18)` → **3.96:1** (support-text floor is 4.5:1, body 7:1). Body copy on MCP/Docker/Services is 12px (`fontSize: '12px'` inline) — below the 14px body floor. ObservabilityOperatorDeck section labels ("OPERATOR SURFACE", "METRICS", "TRACES", "INTEGRATION MATRIX", … 30+ of them) are **10px** `rgba(180,193,210,0.72)` — below the 11px hard floor and using alpha on text. Disabled prefix input uses `opacity: 0.6` on text (`PathsSubtab.tsx:251`).
- Evidence: JS `label:["PostgreSQL DSN?","13px",["3.96",…]]`, deck scan list of 10px labels.

#### F-E-13 — Terminology bans in live copy
- Severity: P3
- Surface: Monitoring deck, Admin Basic
- What I did: regex scan of rendered text.
- What happened: "workflow=legacy_local" chip and "Legacy local lane" text on the live Learning-Agent lane (Monitoring deck, also mirrored in the Grafana dock); "the incident **cards** land here first" (deck incident feed); "every integration **card** reflects live readiness" (Admin Basic intro). Also "Cohere Rerank Calls/min" threshold (Monitoring) — Cohere is not in the locked stack (reranker is the gateway/Qwen lane).
- Evidence: scan results `legacyCtx:["workflow=legacy_local","legacy_local","Legacy local lane"]`, `cards:1`, `card:1`, `cohere:2`.

#### F-E-14 — MCP tile links to `http://127.0.0.1:58012/mcp/` which answers 406 in a browser
- Severity: P3
- Surface: `infrastructure?subtab=mcp` — Python HTTP tile
- What I did: curl GET of the href.
- What happened: `406 Not Acceptable … Client must accept text/event-stream`. Opening the link (target=_blank) shows a JSON-RPC error to the operator.
- Expected: not a link, or a copy-to-clipboard of the endpoint (none exists).

#### F-E-15 — Active subtab label rendered invisible once after Save on Paths
- Severity: P3 (seen once, not reproduced)
- Surface: `infrastructure?subtab=paths` — subtab bar
- What I did: saved corpus name while the mouse hovered a tooltip icon; screenshot ~2.5 s later.
- What happened: the "Paths & Stores" button text was not visible (bar read "Services Docker MCP Servers ____ Monitoring"). On revisit the active button rendered normally (computed color `rgb(113,113,122)` = same as inactive; the pill is a `::after`). Possibly a transient `:active`/focus colour from `micro-interactions.css:161`.
- Evidence: `SS/screenshot-1787682680616-21.jpg` vs `SS/screenshot-1787683028414-47.jpg`.

#### F-E-16 — Dependencies lists a "Netlify API Key" as a shell secret
- Severity: P3
- Surface: `admin?subtab=dependencies` — Shell section
- What happened: `NETLIFY_API_KEY` "Optional deployment credential for shell/admin helper flows" — Netlify is not part of the locked stack or this repo's deploy story; reads as stale.

#### F-E-17 — `/api/webhooks/alertmanager/status` is 404 (consumer is Dashboard → Monitoring, not Infrastructure)
- Severity: P2 (owned by the Dashboard group; recorded here because the task asked)
- What I did: `GET /api/webhooks/alertmanager/status` → `404 {"detail":"Not Found"}`. No `webhooks` router in `server/api/`. Infrastructure → Monitoring never calls it; `web/src/components/Dashboard/MonitoringSubtab.tsx:20` does and will show "Failed to load". The Infrastructure deck's Alertmanager row (from `/api/observability/status`) correctly says reachable/HTTP 200 at :59093.

### Works as expected (brief)
- Services: Docker runtime banner, host API/Vite tiles (`/api/dev/status`), 22/22 container tiles and uptime strings exactly match `/api/docker/status` + `/api/docker/services`; "API container — Not deployed (optional)" is honest; Refresh re-polls (3 GETs) with no failures; 30 s auto-poll.
- Docker: daemon "Available", runtime "docker 28.4.0", Managed services 22 — all match the API; "Ragweld API — Missing / Run ./start.sh --docker-backend" honest; Logs for grafana/neo4j/qdrant/litellm show real tails (`?tail=200`); Close button works.
- MCP: `/api/mcp/status` tiles honest (stdio available, HTTP running at 58012/mcp/, Node "not implemented"); ↻ Refresh stamps "Last updated"; glossary tooltip `SYS_STATUS_MCP_SERVERS` renders with title, INTEGRATION chip, body, 3 reference links.
- Paths: all 6 DB fields equal `GET /api/config?corpus_id=…` (`indexing.postgres_url`, `graph_storage.neo4j_uri/user/database/database_mode/database_prefix/auto_create`); prefix + auto-create correctly disabled in shared mode; Neo4j password shows env-only "Configured"; corpus name/path match `/api/repos`; editing corpus name → `PATCH /api/corpora/ragweld-drive-81854` 200 → "Configuration saved successfully!" → API name updated → restored (verified). Apply All Changes stays disabled for this subtab (it uses its own Save; correct — no pending patches).
- Monitoring deck: all 12 deep links resolve to the live ports (Grafana 3301, Tempo 53200, Mimir 59009, Pyroscope 54040, Alertmanager 59093, Langfuse 53000, LiteLLM 54000, vLLM 58080, Qdrant 56333, Loki 53100); Qdrant text "4 points, 4 dense (384-d)" matches the drive corpus; Refresh Surface works.
- Admin Basic: toggle (`chat.benchmark.enabled` true→false), integer (`chat.max_tokens` 512→513), text (`evaluation.baseline_path` +suffix), enum (`graph_storage.community_algorithm`) — each saved via `PATCH /api/config/<section>?corpus_id=…` 200, survived a full reload in the UI, matched the API, and were restored; global `GET /api/config` deep-diff before/after: **no drift caused by me**. Readiness chips (LiteLLM ready, vLLM ready, Flyte/Unsloth/MLflow disabled with the exact missing config paths) match `/api/config/readiness`.
- Admin Advanced: search and the four filters work and the "Showing N of 451" count is honest.
- Admin Raw: section select (30 sections) loads the live JSON for the section; warning text "Section `chat` will be replaced exactly as parsed JSON" is accurate.
- Admin Dependencies: 13 integrations + 14 secrets with configured/missing chips; no secret value in DOM or in the readiness payload (keys are only `requirement`, `configured`, `blocker_for_integrations`).
- Console: zero errors captured across all surfaces. No horizontal page scroll (scrollWidth 2157 < innerWidth 2174).

### Not exercised (and why)
- Docker Start/Stop/Restart and MCP Start/Stop/Restart — hard limit (and the MCP routes are proven 404 via HEAD).
- Paths DB endpoint fields (Postgres DSN, Neo4j URI/user/database/mode/prefix/auto-create) — point at operator infra; only inspected/compared to the API.
- Raw "Save Section" — replaces an entire config section via `PUT /api/config`; too blunt to round-trip safely while other agents share the corpus.
- Monitoring "Open Grafana Dashboard"/"Open Prometheus" — verified targets with curl instead of opening tabs (both refused).
- `admin?subtab=secrets` / `admin?subtab=integrations` — routes do not exist; covered by Dependencies.
- Docker "stats" and Services "detail drawers" — no such controls exist on either subtab.
- Concurrent-change note: during my run the corpus config's `ui.grafana_embed_enabled/org_id/kiosk/refresh` changed (True→False, 1→2, tv→1, 10s→30s). Not mine — the grafana-eval agent was on `grafana?subtab=config` at the time; flagging so the lead can confirm it was restored.

Baseline/after config snapshots: `scratchpad/E-config-{global,corpus}-{baseline,after}.json`.

---

## P1 closure — 2026-08-25 (session 14)

Every P1 in the master table (M1–M12) and the three graph P1s (M55–M57 = G1–G3)
were root-caused and fixed on `main` in this session, each with a real test
(pytest against live services, Playwright against the running app; no mocks,
no request interception, real Aurora questions). Status per finding:

| # | Status | Root cause → fix | Proof |
|---|---|---|---|
| M1 | FIXED | `StartTab.tsx` was a vanilla-JS-era mock. Rebuilt as a four-step wizard on the real APIs: pick/register a corpus (`POST /api/corpora`), build indexes through the live run stream (`useIndexing.startAndStream`), ask a first question through `POST /api/chat` (non-stream, cited), Done → `/chat?corpus=`. GitHub mode, sliders, "Save as a Project", "Run a Tiny Evaluation", help panel and pills removed (no backend). `useOnboardingStore` keeps the wizard corpus across reloads. | `curious_user_p1_fixes.spec.ts` "M1/M5" walks the whole flow on the acceptance corpus, including a **non-forced rebuild** of the indexed corpus (M5 through the UI) and a grounded cited answer. |
| M2 | FIXED | `useGlobalSearch` scraped the current page's DOM and ran a RAG `/api/search` per keystroke. Now indexes the config registry (`GET /api/config/registry`, every field with label/path/surface) plus the controls on the current page; never calls retrieval; config hits deep-link to `/admin?subtab=advanced&q=<path>` where `ConfigExplorerSubtab` pre-fills and highlights the field. | spec "M2" (rows non-blank, no `/api/search` request observed, deep link highlights `fusion.vector_weight`). |
| M3 | FIXED | `.layout` grid grew with dock content; `.sidepanel` had no height bound (`main.css`). Sidepanel now bounded like `.main-content`; the `DockView` native wrapper is a bounded column flex so a docked page's `.tab-content` is its own scroll container; `GrafanaTab`'s inline `overflow: hidden` (which clipped the 6900 px Overview deck in the main pane once the layout stopped growing) removed. | spec "M3" (document never scrolls, panel ≤ viewport, docked page scrolls inside). |
| M4 | FIXED | `OperatorDeck` paints its own dark gradient but inherited Light-theme `--fg`. Deck-scoped dark text tokens. The graph fullscreen modal had the same class of bug (white edges invisible under Light) and got the same treatment. | spec "M4" (title/subtitle/kicker luminance on the dark gradient under `data-theme=light`). |
| M5 | FIXED | `_run_index` returned the process-local `_STATS` cache on a non-forced run without writing the staging corpus; `promote_staging_index` then raised "Staging corpus not found". Short-circuit removed: every run stages + promotes; the embedding-mismatch guard still protects non-forced runs. | `tests/integration/test_index_promoted_lane.py` (non-forced re-index completes, counts preserved, `runs/latest` clean) + the M1/M5 spec. |
| M6 | FIXED | New threads defaulted to `chat.default_corpus_ids` (recall only) or a stale persisted thread. A new thread is now scoped to recall + the active corpus, and an unused thread follows the active corpus when it changes. | spec "M6". |
| M7 | FIXED | `FusionConfig.validate_weights_sum_to_one` renormalized on every save (17-digit drift, typed values unrecoverable). The validator now only rejects an all-zero set; `TriBridFusion.weighted_fusion` normalizes by the sum at use time. | `tests/unit/test_config.py`, `tests/unit/test_fusion.py`. |
| M8 | FIXED | `benchmark_runner` called generation with `context_chunks=[]`. The API now retrieves through the same fusion lane as chat, the runner fits chunks to each alias's window (`fit_context_to_route`, now public) and uses the RAG prompt; `BenchmarkRun.retrieval` (`BenchmarkRetrieval`) and `BenchmarkResult.context_chunks_used` record grounding; retrieval failures fail the run (503) instead of degrading; the Benchmark tab shows a grounded / not-grounded banner. | `tests/integration/test_benchmark_grounding.py` (paid, two cheap aliases; grounded, `context_chunks_used>0`, persisted record) + spec "M8". |
| M9 | FIXED | `tribrid_search_requests_total` / `_latency_seconds` / `_errors_total` lived in `/api/search` and an HTTP middleware. Moved into `TriBridFusion.search`, so chat, benchmark and MCP retrieval count on the same panels; middleware and endpoint counter removed. The mocked `test_metrics_increment_on_search` was deleted (its replacement runs on the real lane). | `test_index_promoted_lane.py` (search + chat retrieval each increment by one). |
| M10 | FIXED | `/api/monitoring/alert-thresholds` never existed. The thresholds form and `useAlertThresholdsStore` are gone; Monitoring now reads the live Prometheus rules through `GET /api/observability/alert-rules` (`ObservabilityAlertRulesResponse`, fails closed when unconfigured/unreachable). New config field `tracing.prometheus_base_url` (+ glossary `PROMETHEUS_BASE_URL`), set on the operator's global config and on the drive corpus. | `tests/api/test_observability_alert_rules.py` (unconfigured, dead port, live Prometheus with `RagweldWatchdog` firing) + spec "M10/M11". |
| M11 | FIXED | Hardcoded `:3000` / `:9090`. Links resolve from `ui.grafana_base_url` / `tracing.prometheus_base_url` / `tracing.alertmanager_base_url` and grey out when unset; Grafana Config gained a Prometheus URL input. Grafana's default datasource is now **Mimir** (`infra/grafana/provisioning/datasources/mimir.yml` `isDefault: true`, Prometheus `false`) and all 82 dashboard datasource references (`uid: prometheus` and the stale `fetlt404vh7nka`) are rebound to `mimir`; verified after a Grafana restart with `/api/datasources` (Mimir default) and a `/api/ds/query` through the Mimir datasource (Prometheus remote-writes every sample to Mimir). | spec "M10/M11"; Grafana API check. |
| M12 | FIXED | `/api/mcp/http/*` and `/api/mcp/test` never existed (the transport is mounted inside the API). Dead lifecycle controls and service methods removed; `MCPStatusResponse.tools` lists the registered tools; the subtab shows the mounted URL, the tools, and a real search probe (`/api/mcp/rag_search`) with a real question. | `tests/api/test_mcp_endpoints.py` + spec "M12". |
| M55 (G1) | FIXED | `detect_communities` was a top-level-directory heuristic (`(root)` on flat corpora) whose ids embedded the staging repo id. Replaced by deterministic label propagation over entity relationships; ids are content hashes (`c-<sha1[:12]>`), members ranked by degree, summary names the hub; isolated entities belong to no community and the UI says why when there are none. Drive corpus after re-index: 6 communities (KestrelDB 12, Salinity sensor calibration 10, …). | `tests/integration/test_graph_communities_live.py` (seeded graph, promotion keeps ids) + spec "G1/G2/G3". |
| M56 (G2) | FIXED | The whole-corpus view fetched `/entities` only. New `GET /api/graph/{corpus}/subgraph?limit=` returns the induced graph over the best-connected entities; `useGraph.loadSubgraph` feeds the visualizer (drive corpus: 47 nodes • 46 edges). | same. |
| M57 (G3) | FIXED | Fullscreen canvas was measured once, 50 ms in, mid-transition (and via a transformed rect). `ResizeObserver` + layout size, fit on size change, explicit `nodePointerAreaPaint` hit area, legend derived from the types present (G4), hub label size capped, modal kept dark under every theme. | spec "G1/G2/G3" (canvas fills the modal, wheel changes `__zoom.k` and repaints, node click selects). |

Residuals noted while fixing (not P1, left open): Grafana default datasource
uid (M11 note above); corpora created before `tracing.prometheus_base_url`
existed carry an empty value in their per-corpus snapshot until patched (the
per-corpus override design, M41); the `_fusion_search_with_cache` TypeError
fallback in `server/chat/handler.py` is a compatibility seam for test doubles;
`tests/api/test_chat_endpoints.py` still uses a `MockFusion` double and
placeholder messages, and two of its tests fail at HEAD without a matching
gateway key; four API tests are order-dependent in the full unit+api lane
(pass in isolation). M13–M54 remain OPEN as inventoried.

### Adversarial review (codex exec, high effort) — pass 1 REFUTED (9 P1 / 7 P2), all acted on

Prompted to refute `c562881` against the full diff. Every finding was checked
against the code before acting; outcome per finding:

1. **G1 label propagation collapsed two bridged cliques** — reproduced with the
   helper (one group for a 6+6 clique pair joined by one edge). Replaced by
   deterministic Louvain (`networkx`, `seed=0`) run in a worker thread; community
   detection failure now fails the semantic-KG run instead of a warning. Unit test
   for the bridged pair + the live test now bridges its two groups.
2. **M5 cutover order** — the staged Qdrant count is verified before Postgres is
   promoted, and `_STATS` is published only after Postgres, Qdrant and Neo4j are all
   promoted (a failed run never reports staging numbers). Live test: a run over a
   missing path errors and leaves `/stats`, chunk rows and search untouched.
   Residual (documented, not P1): promotion is still three sequential store
   swaps, not one atomic selector record.
3. **M8 hand-written benchmark wire types / run-level banner** — `BenchmarkTab` now
   uses generated `BenchmarkRun`/`BenchmarkResult`/`BenchmarkRunRequest`, the
   payload-guessing normalizer is gone, the Context column shows each row's
   `context_chunks_used`, and the banner is "Grounded" only when every answering
   model used corpus context (otherwise "Partially grounded" names the models).
4. **M12 probe bypassed MCP** — the probe is now `POST /api/mcp/probe`, which opens
   a real `ClientSession` over the mounted Streamable HTTP transport and calls the
   registered `search` tool (honouring `mcp.default_mode` / `top_k`); the legacy
   `/api/mcp/rag_search` route and its DTOs are deleted. Live test covers default
   and `sparse_only` modes.
5. **M10 three config scopes** — the Monitoring page requests alert rules with the
   same corpus scope it reads `tracing.prometheus_base_url` from; the route 404s on
   an unknown corpus instead of falling back to global; the field is classified
   `impact=live` (explicit per-field overrides now take precedence over the
   section prefix rule). The two pre-existing observability routes keep their
   corpus-not-found fallback (out of scope; noted as residual).
6. **M9 TypeError compatibility retry** — deleted from `_fusion_search_with_cache`;
   the four `FusionProtocol` test doubles accept the cache kwargs.
7. **M1 hidden safe lane** — the wizard now calls `/api/index/estimate` and shows the
   files/tokens/chunks/cost/time estimate in the in-app confirm dialog before any
   index POST (the E2E asserts no POST before confirmation and that cancel starts
   nothing); the test-lane config patches remain, documented as cost isolation.
8. **M11 half-fixed** — the Mimir datasource migration is done (see M11 row).
9. **Test-policy** — placeholder queries in `tests/unit/test_fusion.py` replaced
   with a real question; the `monkeypatch` index-error test in
   `test_metrics_endpoint.py` converted to a real `requires_postgres` test; the
   graph Playwright test provisions its own semantic-KG corpus instead of skipping.
   Residual, explicit: `test_fusion.py`'s three graph-hydration-mode tests still use
   fake Postgres/Neo4j/Embedder doubles and stay on the `check_banned` allowlist —
   converting them needs seeded chunk-vector/entity graphs per mode and is tracked
   as debt, not claimed.
10. Benchmark temperature policy mirrors chat (corpus scope, not chunk count);
    Qdrant/Neo4j/contract failures map to the same typed 503/409 as search.
11. Prometheus payload validation (`status == "success"`, `data.groups` list), rule
    state as a literal with `unknown`, UI renders unknown/health≠ok distinctly.
12. Global search keeps `corpus`/`subtab` params on control hits and re-runs the
    query when an index arrives after typing.
13. Contract bundle regenerated (`scripts/export_contract_bundle.py`).
14. `FusionConfig` all-zero check applies to `weighted` only (RRF matrix test).
15. `/api/mcp/status` reports the mounted runtime (`server.mcp.server.mounted_state`).
16. Wizard links use React Router `Link` (base-path safe).

Found while proving finding 2: a `POST /api/index` over a path the API cannot
read "completed" with zero files, and an empty directory would have staged and
promoted an empty index over a populated one. Now: a missing/non-directory
`repo_path` is a 400 at the boundary, and a run that finds no files or produces
no chunks fails (staging cleaned up) instead of promoting. Covered by the
promoted-lane live test (400 for the missing path, `status=error` with
"No indexable files" for an empty directory, active stats/chunks/search
unchanged).

### Residuals closed (session 14, operator instruction: no fake stuff, promotion must be real)

- **Atomic promotion (generation manifest).** Promotion is now one Postgres
  transaction: it swaps the chunk rows and writes
  `corpora.meta.generation = {run_id, qdrant_collection, graph_repo_id}`
  (`server/indexing/generations.py`). Every reader of Qdrant and Neo4j — the
  fusion legs, MMR embeddings, graph API, index stats, incidents/status, the
  incremental writers (recall, Codex ingest) — resolves the physical collection
  and graph id from that manifest. Qdrant aliases and the Neo4j staging→active
  relabel are gone; staged resources are verified (point count, lexical-graph
  chunk nodes) before the commit, superseded generations are retired after it,
  and the cancel/error paths never touch staged resources once the manifest is
  written. Corpora indexed before the manifest existed are upgraded once at API
  startup from their alias target (`ensure_generation_manifests`). Proof:
  `test_qdrant_chunk_store.py` (manifest-named generations, retirement, wiped
  reads), `test_index_promoted_lane.py` (manifest per run, superseded
  generation retired, failed run leaves the manifest), the drive corpus and
  `epstein-files-1` searching after the startup upgrade.
- **Graph hydration tests are real.** The three fake-Postgres/Neo4j/Embedder
  unit tests are deleted; `tests/integration/test_graph_hydration_live.py`
  seeds the graph through a real index run (lexical graph + chunk vector index,
  then the semantic KG through the cheap gateway alias) and proves chunk-mode
  hydration by chunk_id, entity expansion adding chunks beyond the vector
  seeds, and entity-mode hydration. `test_fusion.py` and
  `test_metrics_endpoint.py` left the `check_banned` allowlist; the fake-Postgres
  dashboard stats test became live assertions in the promoted-lane test.
- **Observability routes fail closed and are observed with real queries.**
  `/api/observability/{status,catalog,incidents,alert-rules}` return 404 for an
  unknown corpus (no global-config fallback).
  `tests/integration/test_observability_live_queries.py` runs real searches on
  an indexed corpus, checks the retrieval component reports that corpus's live
  generation and point count with no retrieval incident, wipes the live Qdrant
  generation and checks the incident fires (critical, firing) while search
  fails closed.
- **M22 (storage tiles 0 B) fixed on the way.** `get_dashboard_storage_breakdown`
  summed `pg_column_size` per column without COALESCE, so a NULL `language` on
  prose chunks nulled every row and the tiles read 0 B; the live dashboard
  assertions in the promoted-lane test now require real byte counts.

### Adversarial review pass 2 (codex exec, high effort) — REFUTED the manifest slice; all findings acted on

Findings and what changed (session 14d):

- **Retention was current-only.** A reader that resolved the manifest just
  before a commit could find its collection dropped by the retirement that
  followed. The manifest now carries `previous_qdrant_collection` /
  `previous_graph_repo_id`; retention is current + previous, and a commit
  retires only the generation before the one it replaced, by exact id from the
  manifest chain (never a prefix sweep, so another run's staged collection is
  never touched). `GenerationManifest` / `IndexRunFence` are Pydantic models
  (`extra="forbid"`); a malformed manifest raises instead of reading as
  unpromoted.
- **No durable run fence.** Two workers could build and retire against the same
  corpus. `POST /api/index` now claims `corpora.meta.index_run` with a
  `FOR UPDATE` compare-and-set and answers 409 (naming the running run) while it
  is held; the job releases it in `finally`.
- **A committed run could still report `error`/`cancelled`.** The manifest is
  written, then `_publish_complete` publishes status, `_STATS` and the run
  summary immediately; the retirement that follows is best-effort and a
  cancel/error after the commit leaves the run complete.
- **`delete_index` dropped Qdrant before Postgres**, so a failure in the
  external stores left a manifest naming a dropped collection. Postgres first,
  in one transaction (`delete_index_state`: chunk rows + summaries + contracts +
  manifest + fence), then Qdrant, then Neo4j (manifest graph, previous graph,
  staged graphs of this corpus, legacy id).
- **Startup upgrade ran once.** `ensure_generation_manifests_until_done` retries
  every 60s as a lifespan task until it succeeds once (Postgres down at boot no
  longer leaves pre-manifest corpora unpromoted for the process lifetime).
- **Two readers bypassed the manifest** (`config.py` contract lock,
  `config_control_plane.py` readiness): both resolve `physical=` now. Neo4j
  entity/relationship endpoints scope by the manifest graph id.
  `upsert_chunks(pg=)` records the manifest after the points land (never a
  manifest naming an empty collection), with `graph_repo_id=None` — the
  incremental writers build no graph and the manifest says so.
- **Fake compat left in fusion**: the TypeError "older client stubs" retry
  around `chunk_vector_search` is deleted.
- **Legacy shim next to the route**: `POST /api/index/start` ("compatibility
  endpoint for legacy dashboard UI", loose dict with `repo`/`path` aliases,
  leaked its Postgres connection) had no caller anywhere; deleted. `POST
  /api/index` declares 404/409 in the contract bundle.
- **Tests**: `test_graph_hydration_live.py` is three tests over one seeded
  corpus (module-scoped fixture), both neighbor windows at 0 so every hit is
  one the leg hydrated, and the chunk-mode seeds are compared by id with the
  Qdrant dense leg over the same deterministic vectors; entity expansion must
  be a strict superset of those seeds. The promoted-lane test proves the 409
  fence, the fence release, current+previous retention, and the exact
  retirement after a third run. The observability test requires 503 with
  `required_retrieval_leg_failed` exactly.
- Verification: live lane 16 passed (store, promoted lane, communities,
  observability, hydration ×3, incremental writers), quick gates green, full
  `uv run pytest -q` run alone, Playwright P1 spec against the restarted
  backend — see the session-14d memory note for the exact numbers.

### Adversarial review pass 3 (codex exec, high effort) — REFUTED again (10 P1 / 9 P2); all acted on

What changed (session 14e), by finding:

1. **Commit boundary.** The promotion runs as a shielded future; on any
   exception or cancellation around it the run first lets the shielded
   transaction finish, then confirms against the manifest (also shielded).
   Staged resources are cleaned only when the manifest provably does not name
   the run; an unreadable manifest ends the run as `error` with a
   "commit outcome unknown" message and touches nothing.
2. **Fence lease.** `IndexRunFence` carries `owner` (`host:pid`) and
   `heartbeat_at`; the job heartbeats every lease/10 s
   (`indexing.index_run_lease_seconds`, default 600). A fence whose heartbeat
   is older than the lease is taken over by the next `POST /api/index` and
   released by `POST /api/index/{id}/stop`; a live foreign fence answers a
   typed 409 from both. A malformed fence raises (`IndexFenceCorruptError`),
   never reads as absence; release failures are logged, not suppressed.
3. **Ownership CAS.** `promote_staging_index` locks the corpus row, takes the
   per-corpus advisory lock, and refuses to commit unless
   `meta.index_run.run_id == generation.run_id` (`IndexFenceLostError`); its
   meta comes from the locked row, never from the caller's snapshot.
   `delete_index_state` refuses a live foreign fence (409) and clears only a
   stale one.
4. **Incremental writers.** First generation is `set_generation_if_absent`
   under the same advisory lock; a lost race drops the loser's collection and
   writes into the winner's. Recall and Codex ingest stay Postgres-first but
   compensate: a failed vector write deletes the rows it just wrote
   (`delete_chunks_by_ids`), so no chunk ever exists in Postgres only. A full
   re-index replacing incremental rows is corpus semantics (a full run
   replaces the corpus by definition; recall/Codex corpora are never
   full-indexed from a path) and is recorded here rather than papered over.
5. **Startup upgrade.** Set-if-absent under the row lock; the first attempt
   runs inline (15 s bound) before requests are served, retries continue in
   the background. Round-3 manifests (`previous_*` slot) are rewritten to the
   `retired` list shape, only while the row still carries that shape.
6. **Retention.** `previous_*` is replaced by a `retired` list with
   timestamps; entries are dropped by exact id once
   `indexing.generation_retention_seconds` (default 600) elapsed and pruned
   from the manifest under `run_id` ownership. The promoted-lane test proves
   grace 0 (retired at the next commit) and grace 3600 (kept, listed).
7. **Cancel after commit.** `_cancel_index_run` no longer pre-writes
   `cancelled`; the task owns terminal publication and re-publishes
   `complete` when it was committed. A task that ends without any terminal
   state is reported cancelled by the route.
8. **Deletion tombstone.** `delete_index_state` records the exact Qdrant
   collections and Neo4j graph ids (current + retired, merged with an earlier
   unfinished deletion) as `corpora.meta.index_tombstone` in the same
   transaction; `drop_tombstoned_stores` drops them; a failure is a typed 503
   and the tombstone stays for the next attempt; success clears it. Corpus
   deletion follows the same protocol.
9. **Fence test.** The process-local 409 check is gone: the durable CAS is the
   only authority, so the overlapping-run 409 comes from Postgres. The test
   also writes a foreign fence directly on the row (another worker) and
   proves start/delete/stop all answer the typed 409 naming that run, that a
   stale fence is taken over by a new run, and that the stop route releases a
   stale fence.
10. Chat with the gateway disabled must be exactly 503 `generation_unavailable`.
11. Interrupted-run finalisation consults the manifest: a run it names is
    finalised `complete`, never coerced to `error`.
12. Typed 409 envelope `IndexRunConflictDetail`/`IndexRunConflictResponse`
    (registered, generated, in the OpenAPI bundle); `useIndexing` parses it.
13. Graph gauges never fall back to the corpus id when the manifest has no graph.
14. Retrieval readiness reports a manifest lookup or Qdrant status failure as
    `degraded` with the cause (`generation_manifest` / `qdrant_status`), never
    as "run indexing".
15. The caller-less `POST /api/index/stop` shim and the never-implemented
    Neo4j `search` query mode (`graph_storage.neo4j_vector_query_mode`, its env
    mapping and UI category) are deleted.
16. Index event persistence goes through a bounded queue and one writer thread;
    readers flush before reading.
17. Neo4j driver is disconnected when index initialisation fails.
18. The graph-hydration seed comparison is now the sound invariant: the graph
    leg's hits are a prefix of the corpus's exact ranking (the Qdrant dense leg
    over the corpus-isolated collection), never a chunk outside it; the shared
    Neo4j index can only shrink the set.
19. The store test asks a real calibration question over real content.

Verification (session 14e): live lane 16 passed (store contract incl.
set-if-absent, promoted lane incl. foreign/stale fence, takeover, stop,
retention grace 0/3600, tombstone; communities; observability; hydration ×3;
incremental writers), full `uv run pytest -q` alone 1156 passed / 90 skipped,
Playwright `curious_user_p1_fixes` 9 passed against the restarted backend,
quick gates green (453 config keys, contract bundle with the typed 409).
Codex pass 4 launched on the committed diff.

### Adversarial review pass 4 (codex exec, high effort) — REFUTED again (10 P1 / 7 P2); all acted on

Session 14f, by finding:

1. **Tombstone fails closed everywhere.** `generation_from_corpus_row` raises
   `DeletionIncompleteError` while `corpora.meta.index_tombstone` exists; a
   global handler answers the typed 503 `index_deletion_incomplete`
   (`IndexDeletionIncompleteDetail`, declared on search and both delete
   routes). `set_generation_if_absent` and promotion refuse a tombstoned corpus.
2. **Deletion cannot erase a concurrent generation.** No writer can create one
   under a tombstone (above); the tombstone is cleared by compare-and-set on
   its own `created_at`, never unconditionally.
3. **Incremental writes are one unit of work.**
   `PostgresClient.upsert_chunks_with_vectors`: one transaction holds the
   per-corpus advisory lock, resolves/creates the live generation from the
   row-locked manifest, writes the vectors inside it, then commits the rows —
   a failed vector write rolls the rows back (no blind deletes), promotion
   cannot switch generations under the writer. Recall and Codex ingest call it
   once; the bisect/dead-letter contract is unchanged.
4. **Manifest built under the lock.** `promote_staging_index` takes
   `run_id/qdrant_collection/graph_repo_id` and builds the manifest from the
   row-locked previous one, so a first generation that appeared meanwhile
   joins the retired chain.
5. **Unknown stays unknown.** An unreadable manifest leaves an interrupted
   run untouched; a missing corpus is a definitive non-commit.
6. **Durable status.** `GET /api/index/{id}/status` reports a fresh fence held
   by another worker as `indexing`; interrupted-run finalisation respects a
   live fence for the same run. (Streaming stays worker-local: the API runs
   one uvicorn worker; recorded, not papered over.)
7. **Per-store retention.** Retired entries are masked per resource, never
   dropped whole; entries are deduplicated by the ids they name; pruning
   matches by run id; the shape upgrade masks equal ids and never records the
   same pair twice.
8. **Idempotent completion.** `stats` is retained; every confirmed-commit path
   (normal, cancelled, failed) runs the same complete publisher once
   (status, `_STATS`, persisted summary, terminal event).
9. **`onCancelled` reaches the stream** (TerminalService destructures and
   passes it; it is no longer serialised into the query string).
10. **Tests**: six concurrent `acquire_index_fence` claims (exactly one wins,
    the rest name the holder), heartbeat moves the DB-stamped timestamp for
    the holder only, a controlled stop the moment the manifest goes live
    (status/summary `complete`, generation live, fence released), three
    retained generations with mixed expiry then pruned by exact id, the
    round-3 shape upgrade with an equal-id case, fence release polled (it
    happens after publication).
11. **Hydration oracle**: overfetch multiplier 1 and a subset (membership)
    assertion against the corpus's exact top-k; order/count are not
    cross-engine invariants.
12. `server/models/index.py` is the index domain module (docstring says so);
    the UI treats an unparseable 409 as a contract failure, never raw text.
13. **Readiness** reports `index_manifests` (the durable upgrade) as a fifth
    dependency; the service is not ready until it ran once.
14. **Neo4j chunk vector index** creation/ONLINE is a promotion prerequisite
    when chunk embeddings are stored (fails the run, never a warning).
15. **Persistence**: unbounded FIFO (nothing dropped), summaries replaced
    atomically by the same writer, readers flush before reading, lifespan
    shutdown flushes and joins the writer.
16. **Typed 409 union**: `IndexFenceCorruptDetail` for a malformed fence,
    discriminated on `code`, in the OpenAPI bundle.
17. **Fence**: database-clock timestamps for heartbeat and staleness; the
    fence names the staged collection/graph and a takeover reclaims them
    exactly (plus the dead run's staging rows). `run_id` is the opaque
    per-claim token (unique per claim; a takeover mints a new one).

Verification (session 14f): live lane 16 passed, full `uv run pytest -q` alone
1156 passed / 90 skipped, Playwright `curious_user_p1_fixes` 9 passed against
the restarted backend, quick gates green, contract bundle carries the typed
409 union and the `index_deletion_incomplete` 503 on every manifest reader.
Codex pass 5 launched on the committed diff.

### Adversarial review pass 5 (codex exec, high effort) — REFUTED again (10 P1 / 8 P2); acted on, residuals recorded

Session 14g, by finding:

1. **Fence claims refuse a tombstoned corpus** (under the same row lock; typed 503).
2. **Cross-store atomicity of incremental writes — recorded residual.** Rows and
   vectors cannot commit atomically without an outbox; the protocol keeps the
   vector write inside the row transaction so no row ever exists without its
   vectors. A vector that lands without its row (row commit failed after the
   vector write) is unreachable — hydration is by chunk_id from Postgres — and
   is overwritten by the retry of the same chunk. Accepted and documented.
3. **Per-resource retention refcount**: a collection or graph is droppable only
   when nothing alive still names it (live generation or an entry inside its
   grace); pruning removes resources, not entries (`without_resources`).
4. **Corpus delete keeps the tombstone** through lineage cleanup; the registry
   row is removed under the corpus advisory lock (writers cannot slip in).
5. **Malformed persisted keys are typed corruption** (`PersistedStateCorruptError`
   for manifest and tombstone; malformed fences already were); nothing reads
   as absent.
6. **De-index is the repair path**: `delete_index_state` clears a malformed
   fence/manifest/tombstone loudly (the corpus namespace sweep still covers
   its collections and graphs) instead of refusing with the same 409.
7. **Unknown commit stays non-terminal** (`indexing` with the explanation); the
   next status read reconciles it against the manifest.
8. **Durable-first readers**: status resolves tombstone → fence → this
   process's state → persisted runs; the dashboard's `running` derives from
   the fence too; `_live_fence` propagates outages (typed 503) and corruption
   (typed 409) instead of reading as idle; stats resolve the tombstone first.
9. **UI stop**: the stream stays connected until the backend answers; the
   component branches on the returned status (`complete` after the commit
   boundary is rendered as complete, never "Cancelled").
10. **Tests**: live tombstone → search/index/status/stats/graph-stats all
    answer 503 `index_deletion_incomplete`, the retried delete clears it;
    heartbeat must strictly advance the DB timestamp; a seeded manifest with
    one due and one fresh retired collection proves per-resource expiry on a
    real commit; the graph-hydration oracle is the same engine
    (`Neo4jClient.chunk_vector_search` on the manifest graph id, same
    parameters) — set equality; the pre-existing fake-based codex-ingest
    bisect suite stays fake (recorded residual: the poison path has no real
    Postgres trigger).
11. **Staged ids are chosen and recorded on the fence before creation**
    (`generation_name` → `record_fence_staging` → `create_generation(physical=)`).
12. **Vector-index contract check**: ONLINE plus label/property/dimension/
    similarity from `SHOW VECTOR INDEXES`; drift fails the run.
13. **Remote stop uses the database clock.**
14. **Upgrade**: alias removal is its own idempotent step; once an upgrade
    attempt has failed, manifest-dependent routes answer 503 until it succeeds
    (middleware; liveness/readiness stay reachable). An unattempted upgrade
    (tests without lifespan) does not gate.
15. **Persistence**: lifespan stops index runs before the writer; summary and
    event reads run off-loop. Bounded spooling with backpressure is a recorded
    residual (unbounded FIFO stays).
16. **Incremental first vector write preserves a live graph pointer.**
17. **Contracts**: 503 unions declared on POST /api/index, status, stats, both
    deletes, the chat family and graph stats; corpus-delete 409 is the
    Pydantic detail; the contract test covers them.
18. **Index boundary models live in `server/models/index.py`**; the aggregate
    re-imports them.

Verification (session 14g): live lane 16 passed, full `uv run pytest -q` alone
1156 passed / 90 skipped, Playwright `curious_user_p1_fixes` 9 passed against
the restarted backend, quick gates green. Codex pass 6 launched on the
committed diff.

### Adversarial review pass 6 (codex exec, high effort) — REFUTED again (9 P1 / 5 P2); all acted on

Session 14h, by finding:

1. **Stale-fence recovery never deletes a live index.** `acquire_index_fence`
   compares the stale fence with the row-locked manifest (`run_id`, or its
   staged collection among the manifest's collections); `FenceClaim.
   taken_over_committed` makes the caller finalize the dead run's summary as
   complete instead of reclaiming. The remote stop path does the same check
   and reports `complete` for a committed dead run. (This was a real defect
   introduced in session 14e.)
2. **Malformed manifests fail closed everywhere**: promotion raises
   `PersistedStateCorruptError` instead of overwriting; the startup upgrade
   validates every present manifest and a corrupt one blocks the upgrade
   (readiness pending, manifest routes gated) until the corpus is de-indexed.
3. **Tombstone intent**: `delete_corpus` tombstones are never cleared by a
   concurrent de-index (`clear_index_tombstone` only clears `deindex`
   intent); only the locked row removal ends them.
4. **Vector-index contract is checked whether or not the run waits for ONLINE**;
   the `SHOW INDEXES` compatibility retry is gone.
5. **Manifest and retirement timestamps come from Postgres `now()`** inside the
   locked transaction (promotion, incremental first write, tombstone) and
   retirement decisions use `database_now()`.
6. **The monkeypatched dashboard status test is deleted**; a live test proves
   the status route resolves the CORPUS-scoped lease from the durable fence
   (stale under the corpus lease, live and named under a fresh fence).
7. **Shared-resource retention test**: due and fresh entries share one graph
   and differ in collection; the shared graph survives on the fresh entry,
   the due entry's own collection goes.
8. **Fence 409 proven only durably** (the in-process overlapping POST is
   gone); the post-commit stop asserts this process still owns the task and
   the fence still names it, with four due retired collections widening the
   post-commit window.
9. **Expansion baseline is the same engine** (Neo4j seeds with expansion off);
   at least one final chunk must lie outside it.
10. **Process state never overrides durable truth**: local progress only for
    the run the fence names (`_ACTIVE_RUNS`), dashboard `running` from the
    fence, cached stats only while this process runs the corpus.
11. **An unknown commit keeps its fence**, expiring into the manifest-aware
    takeover (finalize or reclaim exactly).
12. **Latest-run reconciliation propagates a corrupt fence** as the typed 409.
13. **Consumers import index models from `server.models.index`**; the
    aggregate re-export aliases are gone; the generator imports from the
    domain module.
14. **The contract test asserts the POST /api/index 409 discriminated union.**

Verification (session 14h): live lane 17 passed (incl. the new scoped-lease
status test), full `uv run pytest -q` alone 1156 passed / 91 skipped,
Playwright `curious_user_p1_fixes` 9 passed against the restarted backend,
quick gates green. Codex pass 7 launched on the committed diff.

### Adversarial review pass 7 (codex exec, high effort) — REFUTED again (8 P1 / 3 P2); acted on, residuals recorded

Session 14i, by finding:

1. **Retention-window hydration — recorded residual.** A reader that
   resolved generation G1 and queries G1's retained Neo4j graph after G2
   committed hydrates by chunk_id from G2's rows: ids that still exist come
   back with G2's (same-file) content, ids that vanished are filtered. No
   wrong data is served; the reader may see fewer hits during the commit
   window. Fixing it needs generation-versioned chunk rows or a request-long
   repeatable-read snapshot; accepted and documented.
2. **Tombstone revision**: every write (merges included) mints a revision;
   `clear_index_tombstone` CASes on it, so an older cleanup can never clear a
   newer merged tombstone.
3. **Unknown commits are cancellation-safe**: the outcome is marked unknown
   before the first reconciliation await and cleared only by a definitive
   negative; a second cancellation during reconciliation leaves it unknown;
   the stop route never rewrites an unknown run as cancelled
   (`_UNKNOWN_COMMITS`); reconciliation clears the marker.
4. **Local terminal state yields to a newer manifest** (promoted after the run
   this process remembers); the dashboard's `running` derives from the fence
   only.
5. **Heartbeat in its own thread** (`_FenceHeartbeat`, own event loop): a
   starved API loop can no longer make a live run look dead.
6. **Quarantine, not lockdown**: a corrupt manifest quarantines that corpus
   only (readiness lists it; its reads answer the typed 409
   `persisted_state_corrupt`; DELETE repair routes are exempt from the gate);
   the gate now covers infrastructure failure only.
7. **Shared-resource retention test seeds real Neo4j graphs** (the due entry's
   own graph is physically deleted; the shared graph physically survives).
8. **Post-commit stop waits for the durable `retiring` phase** on the fence
   (written after the commit, before retirement) with eight due collections
   of retirement work; the test still asserts this process's task is live.
   A fully deterministic barrier would need a test seam — recorded.
9. **Stop on a stale uncommitted fence reclaims its staged inventory** (and the
   staging rows) before releasing.
10. Startup storage migration — recorded residual (a one-time rewrite, not a
    read-time fallback).
11. **Reconciliation propagates malformed manifests** as the typed 409 instead
    of "unknown".

Verification (session 14i): live lane 17 passed, full `uv run pytest -q` alone
1156 passed / 91 skipped, Playwright `curious_user_p1_fixes` 9 passed against
the restarted backend, quick gates green. Codex pass 8 launched on the
committed diff.

### Adversarial review pass 8 (codex exec, high effort) — REFUTED (8 P1 / 5 P2); triaged, valid items fixed, the rest adjudicated by ox-alpha

Session 14j. The operator authorised a second opinion from OpenRouter
`stealth/ox-alpha` (1M context) for findings that look pedantic; the full
protocol source, tests, cumulative diff, seven prior reports and this one
were sent (~360k tokens). Fixed as VALID before the verdict:

1. **Heartbeat from a thread used the API loop's asyncpg pool** (a real defect
   from session 14i: `_POOLS_BY_DSN` is process-wide, so beats failed, were
   swallowed, and a live run could expire). `PostgresClient.
   heartbeat_index_fence_standalone` opens a dedicated connection in the
   thread's own loop.
2. **A second cancellation while the promotion task is still pending is not a
   definitive negative**: the run stays unknown (resources and fence kept)
   until the transaction task reaches a terminal state; refusals raised by the
   transaction (`IndexFenceLostError`, `DeletionIncompleteError`,
   `PersistedStateCorruptError`) are definitive negatives.
3. **Reclaim backlog**: a taken-over stale fence's staged inventory is moved,
   in the takeover transaction, to a durable `reclaim_backlog` on the corpus
   row; the stop route pushes an entry before releasing; entries are removed
   only when every store confirmed the cleanup (`reclaim_stale_run` returns
   True).
4. **Validate before fencing**: `acquire_index_fence` validates the manifest
   and backlog before writing any fence, so a corrupt corpus answers the typed
   409 instead of holding a doomed run.
6. **Per-row quarantine covers every persisted key** (manifest, tombstone,
   fence, backlog).
7. **`PersistedStateCorruptResponse` is in the 409 unions** (POST /api/index,
   status, latest run, delete), parsed by the UI, asserted by the contract
   test.
9. **Local terminal status is tied to its run by identity**
   (`_STATUS_RUN_ID`): it yields when the manifest is gone or names another
   run — no clock comparison.
10. **DELETE answers the typed incomplete-deletion 503 when it lost the
    tombstone CAS** (never `ok`).
11. **Observability surfaces corruption/outage**: the retrieval component
    renders it and a critical `retrieval:{corpus}` incident fires ("index
    state unreadable") instead of "not indexed".
12. **Tombstone `revision` is required** (every writer mints one).

Sent to ox-alpha for adjudication (implementer's position in brackets): #5
move the whole indexing pipeline off the event loop [pre-existing
architecture; the heartbeat thread is the mitigation]; #8 deterministic
post-commit cancellation barrier [needs a test seam]; #12 model defaults for
`retired`/`phase` and `_coerce_jsonb_dict` [read-time defaults for optional
persisted fields]; #13 the same-engine seed oracle [it was the reviewer's own
pass-6 recommendation]; plus the standing residuals.

**ox-alpha adjudication (OpenRouter `stealth/ox-alpha`, 322k tokens of
context):** VALID = #1, #2, #3, #4, #6, #7, #9, #10, #11 and the `revision`
part of #12 (all fixed above); OVERREACH = #5 (loop-blocking indexing is a
pre-existing QoS limitation, the heartbeat thread is the safety mitigation),
#13 (the same-engine oracle is the reviewer's own pass-6 recommendation) and
the `_coerce_jsonb_dict` part of #12; ALREADY-RECORDED = #8 (deterministic
post-commit barrier needs a seam) and the `retired`/`phase` defaults (part of
the startup-migration residual). It required regression proof for #1 and #2
and asked that the revision backfill join the migration — done:

- `tests/unit/test_index_commit_outcome.py`: the commit-outcome decision is a
  pure function (`_classify_commit_outcome`) — a pending transaction task is
  always unknown, refusals before writing are definitive negatives, other
  failures defer to the manifest.
- `tests/integration/test_fence_heartbeat_live.py`: a `_FenceHeartbeat` keeps
  the database-stamped heartbeat advancing while the API event loop is
  blocked for 7.5 s (lease 30 s).
- `ensure_generation_manifests` backfills a revision on any tombstone written
  before revisions existed (one-time, on the row).
- Cheap hardenings it suggested: the committed-cancel handler records the run
  it handled (`_CANCELLED_AFTER_COMMIT`) and the post-commit stop test asserts
  it; the chunk-mode hydration test also bounds its hits by the corpus's exact
  Qdrant top-k.

Its verdict: after these, the slice is shippable for a single-worker
deployment with #5 and the six residuals documented as known limitations;
nothing recorded still blocks.

**Final recorded residuals (known limitations):** indexing work can block the
API loop (QoS: delayed stop/status/SSE, not protocol safety); retention-window
hydration from the swapped chunk rows (no wrong data, possibly fewer hits
during the commit window); a fully deterministic post-commit cancellation
barrier needs a test seam; cross-store atomicity of incremental writes without
an outbox (orphan points unreachable and idempotently overwritten); the
pre-existing fake-based codex-ingest bisect unit suite; unbounded run-event
FIFO; worker-local SSE; the startup storage migration (one-time rewrites of
pre-manifest, pre-retention and pre-revision shapes).

Verification (session 14j): live lane 18 passed (incl. the blocked-loop
heartbeat test), full `uv run pytest -q` alone 1161 passed / 92 skipped,
Playwright `curious_user_p1_fixes` 9 passed against the restarted backend,
quick gates green, contract bundle carries the corruption 409 union. Codex
pass 9 (scoped to this diff, adjudicated items marked settled) launched.

### Adversarial review pass 9 (codex exec, scoped to the round-9 diff) — REFUTED (2 P1 / 5 P2 / 1 P3); all acted on

Session 14k. Every finding concerned round-9 code and was accepted:

1. **De-index repairs the reclaim backlog too**: `delete_index_state` hands
   every valid backlog entry's staged ids to the tombstone, drops its staging
   rows, and removes the key whatever shape it had. Live test: a malformed
   backlog → typed 409 on start (no fence written) → DELETE → start succeeds.
2. **`get_index_tombstone` goes through the strict reader** (a malformed
   tombstone is the typed 409, never absent or a raw 500); a lost CAS still
   answers the typed incomplete-deletion 503.
3. **Nothing sits between the claim and the job's heartbeat**: the reclaim
   backlog is drained by the background job after its heartbeat starts, and
   the only post-acquire work (finalizing a committed dead run) releases the
   fence on failure.
4. **Every claim drains the backlog**, so a failed reclaim is retried by the
   next normal run.
5. **A persisted `complete` summary is history**: with no manifest (another
   worker de-indexed), status reports idle instead of resurrecting it.
6. **Status and latest-run declare the corruption 409 union**; the contract
   matrix covers status, latest-run and delete; `reclaim_backlog` is a named
   key of the corruption detail.
7. **The cross-engine Qdrant bound is gone** from the chunk-mode hydration
   test (same-engine equality and corpus scope stay).
8. **The heartbeat test proves two beats** across two blocked-loop intervals
   and joins the thread.

### Self-audit (session 14k, before any further review)

The operator called out the pattern — ten rounds in which lesser models kept
finding defects, several of them introduced while fixing others — and asked
for reasoning and foresight instead of reactive patching. The whole protocol
(job, start/stop/delete/status routes, Postgres claim/promotion/delete/
incremental/reclaim methods, retirement, heartbeat, reclaim helper) was
read end-to-end against a failure matrix: every durable write and a crash
right after it; every `await` in the commit/cleanup paths under a
cancellation; every pair of concurrent operations on one corpus; every
persisted key when malformed; every new test asked whether it stays green
with the behaviour broken. Found and fixed:

- **Thread internals**: `_FenceHeartbeat` set `self._stop`, shadowing
  `threading.Thread._stop()`; `join()` then raised — the heartbeat test
  caught it live (`'Event' object is not callable`). Renamed.
- **Committed after disconnect**: `committed = True` was set after the
  `finally: await postgres.disconnect()`; `contextlib.suppress(Exception)`
  does not catch `CancelledError`, so a stop landing during that disconnect
  read a committed transaction as uncommitted and the cancel handler would
  have dropped the live collection. `committed`/`qdrant_generation` now
  flip the instant the shielded promotion returns.
- **Own cleanup is durable**: the cancel/error handlers dropped staged
  resources inline; a second cancellation mid-cleanup then let `finally`
  release the fence (the only record of the staged ids). Both handlers now
  push a reclaim-backlog entry first and run the exact reclaim
  (`_reclaim_own_staged`, shielded); the entry clears only on confirmed
  success.
- **One staging-id definition** (`staging_repo_id`): three hand-written
  `__staging__{repo}__{run}` copies (index API, Postgres, reclaim) happened
  to agree; a drift there would have silently orphaned staging rows.
- **Staging cleanup on de-index** now covers every staging table
  (`chunk_summaries`, `_last_build`, `corpus_configs`, `chunks`, `corpora`).
- `_UNKNOWN_COMMITS` resets when a new run starts for the corpus; `delete`
  pops every in-memory run marker; the status route no longer infers
  `complete` from a process-cached `IndexStats` (durable inference only).

Verification (session 14k): live lane 19 passed (incl. corrupt-backlog repair
and the two-beat heartbeat), full `uv run pytest -q` alone 1161 passed / 93
skipped, Playwright `curious_user_p1_fixes` 9 passed against the restarted
backend, quick gates green. Codex pass 10 (scoped to this diff) launched.

Further self-audit items while pass 10 ran: `delete_repo` decided fence
staleness with the global config instead of the corpus-scoped lease (fixed:
`load_scoped_config`); the incomplete-deletion 503 hint now depends on the
tombstone's intent (a de-index can never clear a corpus-deletion tombstone;
retry the corpus deletion); the Qdrant namespace sweep was re-checked and is
injective (sha1 suffix in the corpus prefix); the retention invariants
(shared resources across due/fresh entries, live-id masking, pair
deduplication, resource-level pruning, grace 0) have a pure unit suite
(`tests/unit/test_generation_retention.py`).

### Adversarial review pass 10 (codex exec, scoped) — REFUTED (2 P1 / 4 P2 / 1 P3); all acted on

Session 14l. Every finding concerned round-10/self-audit code and was
accepted:

1. **Own cleanup gates the fence release**: `_reclaim_own_staged` reports
   whether the inventory was durably handed to the backlog; if the push
   failed (or a second cancellation interrupted the wait before it was
   recorded), the `finally` keeps the fence — which names the same inventory
   — for the stale takeover, exactly like an unknown commit.
2. **The backlog-repair test seeds a real valid entry** (a real Qdrant
   collection, a real Neo4j graph and real staging rows of a dead run) next to
   the malformed item, asserts status/stats answer the typed 409 at runtime,
   and proves the de-index dropped all three and left no key or tombstone.
3. **Own cleanup uses the exact recorded inventory**: the planned collection
   name recorded on the fence before creation and the graph id recorded with
   it — never a client response that may have been lost, never current
   feature flags.
4. **One strict persisted-index-state reader** (`_read_index_state`: manifest,
   tombstone, fence, reclaim backlog) is used by status, stats and latest-run;
   a malformed backlog now answers the typed 409 on every reader.
5. The completed-summary manifest check reuses that strict read (no second,
   unguarded Postgres round trip).
6. **De-index clears this process's state while the tombstone still blocks
   starts**, so a run claimed after the tombstone clears can never have its
   task/queue/markers erased.
7. The 409 descriptions name the complete union.

### Round 12 — own end-to-end audit (before any reviewer) + adversarial review pass 11

Session 14m. The whole protocol (`generations.py`, the Postgres fence /
promotion / deletion transactions, the job and every handler, stop / takeover /
retire / start / delete) was read end to end and a failure matrix built BEFORE
reading the pass-11 report. Own findings, all fixed:

1. **Graph participation came from three config snapshots** (the fence record,
   `_run_index`'s own reload, and a reload at commit): a flag flipped mid-run
   could orphan a built graph or demand an unbuilt one. One snapshot now: the
   job's config is passed into `_run_index`, and the commit names the graph iff
   the fence recorded one.
2. **De-index left a crashed run's inventory behind**: a stale fence (a run
   that died and was never taken over) was cleared without its staged
   collection / graph joining the tombstone, and its Postgres staging rows were
   never deleted. The fence's inventory now joins the tombstone exactly like a
   backlog entry, and every staging row of THIS corpus is swept with the exact
   `__staging__<corpus>__<run>` rule (`a` never sweeps `a__b`).
3. **Orphan-fence window in `start_index`**: a request cancelled between a
   successful claim and the job's start (e.g. during the pool disconnect) held
   the corpus until the lease expired. Any failure after the claim now releases
   it (shielded).

Pass 11 (codex, scoped) — REFUTED (5 P1 / 3 P2); all acted on:

1. Generation names were 32-bit suffixes created with `recreate=True`: a
   collision with a live/retained collection would have wiped it. Names carry
   a full 128-bit uuid and `create_generation` refuses an existing collection
   (`QdrantGenerationExistsError`); live test proves the data survives.
2. Takeover/stop classified a dead run as committed when its staged collection
   merely appeared among retained ids. Only `manifest.run_id` proves a commit;
   and `reclaim_stale_run` never drops a resource the manifest names (live or
   retained) whatever the entry says. Live test: stop → cancelled, retained
   collection survives, the run's own graph goes, backlog clears; takeover
   claim → `taken_over_committed is False`, reclaim confirms.
3. Dashboard `/api/index/status`, `/api/index/stats` and the latest-run 404
   short-circuit bypassed the strict state read; all three go through it now,
   and the runtime 409 test covers six readers.
4. `due_for_retirement` emits each physical resource exactly once (first due
   holder carries it); the retention test asserts the graph id occurs once.
5. `_dedupe_retired` keeps the entry with the LATEST `retired_at` (shared
   resources never get a shorter grace); a test seeds two entries converging on
   one pair after masking.
6. `requires_qdrant` / `requires_neo4j` markers on the hardened live test.
7. Test resources are acquired inside the protected block and cleaned
   conditionally.
8. `/api/index/{corpus_id}/stats` and both dashboard routes declare the 409
   union; contract bundle regenerated; contract matrix extended.

4. (Found while auditing the incremental writer, pre-existing.) Every chunk /
   summary writer "ensured" the corpus row with a placeholder identity whose
   `ON CONFLICT` clause overwrote the operator-given name and description:
   a recall or Codex-ingest write into a registered corpus renamed it to its id
   and nulled its description. Writers that only need the row to exist now
   preserve the existing identity (`preserve_identity=True`); the registry
   upsert (an explicit rename) is unchanged. The recall live test registers
   "Aurora buoy notes" with a description and proves both survive two writes.

Not tested by a live flip (structural only): the single-snapshot graph
decision and the `start_index` release-on-failure guard.

