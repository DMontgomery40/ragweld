# Indexing API

<div class="grid chunk_summaries" markdown>

-   :material-file-document-multiple:{ .lg .middle } **Start**

    ---

    `POST /index` with `IndexRequest`.

-   :material-progress-clock:{ .lg .middle } **Status**

    ---

    `GET /index/status` returns progress, current file.

-   :material-harddisk:{ .lg .middle } **Stats**

    ---

    `GET /index/stats` returns storage breakdown.

</div>

[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }

!!! tip "Force reindex"
    Set `force_reindex=true` only when you need a clean rebuild. Incremental updates are cheaper.

!!! note "BM25 vocabulary"
    `/index/vocab-preview` helps debug tokenizer/stemmer stopword settings.

!!! warning "Repo path"
    Ensure `repo_path` points to a locally accessible directory (bind-mount in Docker).
    A registered relative path — for example the Recall corpus's `data/recall` — resolves against the project root, not the API process's working directory (`_resolve_corpus_root` in `server/api/index.py`), and a `422` for a missing root names the resolved path it looked for.

| Route | Method | Description |
|-------|--------|-------------|
| `/index` | POST | Start indexing |
| `/index/status` | GET | Current state |
| `/index/stats` | GET | Storage stats |
| `/index/{corpus_id}/graph-schema/proposal` | GET | Read the saved schema proposal for review restore (`current` / `missing` / `stale` / `ineligible`); read-only — never generates, never bills |
| `/index/{corpus_id}/runs/latest` | GET | Latest run summary (run id, status, progress, figure counts); `?finalize=false` for a pure read |
| `/index/{corpus_id}/runs/{run_id}` | GET | Read one exact index or schema-proposal run, including its saved accounting |
| `/index/{corpus_id}/runs/{run_id}/costs/reconcile` | POST | Refresh a saved run's native spend from the gateway ledger it recorded |
| `/index/{corpus_id}/runs/{run_id}/events` | GET | One page of a run's event log as `IndexRunEventPage` (`?limit=500`): the most recent events plus the run's real `total` and `first_index`, so a cap is never shown as a fact |

!!! note "Runs are observable regardless of who started them"
    Every indexing run is recorded against the corpus and can be polled by any client — the UI, a CI job that started the run via `POST /api/index`, or a scheduled automation. The **RAG → Indexing** tab polls `/api/index/{corpus_id}/status` and, when it finds a run it did not start itself, mirrors its progress bar, current file, event log, and Stop button, marking the run "started outside this tab". This means an indexing job kicked off by an API call or a schedule is never invisible in the workbench.

!!! note "A 409 fence conflict names the run and what it is doing"
    Starting, stopping, or deleting an index on a corpus whose fence is held answers the typed `IndexRunConflictResponse`. Alongside `run_id`, `owner`, `started_at` and `heartbeat_at`, the detail carries:

    - `phase` — the holding run's fence phase: `building` while it indexes, `retiring` while it retires the previous generation.
    - `stage` — what the holding run last reported doing (its most recent `log`/`progress` run event, e.g. `Converting apollo-11-mission-report.pdf: still running (600s elapsed)`), or `null` when the run has logged nothing yet. The stage is read from the tail of the holding run's event log — never the full file — and the reader deliberately does not drain the live write queue, so it can lag by at most a moment and never hangs the response.

    The same builder serves the corpus-delete refusal (`DELETE /api/repos/{corpus_id}` and `DELETE /api/corpora/{corpus_id}`, both of which document the `409` in their OpenAPI responses), so the delete refusal and the index-start refusal cannot drift apart. A delete also accepts an `only_unindexed` query flag; with it set, the same `409` position can instead answer the typed `corpus_already_indexed` refusal — the corpus id plus the `last_indexed` timestamp read under the corpus write lock — so conditional cleanup can never delete a corpus whose index committed after the caller listed it.

!!! note "A poll for a deleted corpus is a typed 404, not a 500"
    `GET /api/index/status` and `GET /api/index/stats` resolve the corpus's scoped config as part of answering; when the named corpus is not registered — for example, a Dashboard tab left open across a corpus deletion — both answer `404` with the corpus-not-found message instead of an unhandled `500`, and both document the `404` in their OpenAPI responses (`server/api/index.py`).

!!! note "Run history survives deletion"
    Deleting an index — or the corpus itself — no longer deletes its run records. Every saved attempt, including its frozen pre-run estimate, request census and reconciled native costs, stays readable through `GET /api/index/{corpus_id}/runs/{run_id}` even after the index or the corpus registration is gone. Current-state readers (`GET /api/index/{corpus_id}/status`) key off the durable generation manifest instead, so a deleted corpus answers `404` there while its paid history remains auditable. See [Native run accounting](operations/native_costs.md).

!!! tip "Runs keep their own frozen quote — and schema proposals are runs"
    When a run starts, the index job freezes the pre-run estimate under that exact config and saves it on the run record (`IndexRunAccounting.estimate`), so a later config change can never reprice a past run. `GET /api/index/{corpus_id}/runs/latest` also accepts `run_kind=schema_proposal` (default `index`) to read the latest schema-proposal attempt, and `POST /api/index/{corpus_id}/runs/{run_id}/costs/reconcile` re-reads the native spend ledger for the gateway the run recorded — never the currently selected gateway. See [Native run accounting](operations/native_costs.md).

!!! note "Run event logs are pages, not bare lists"
    `GET /api/index/{corpus_id}/runs/{run_id}/events` now answers `IndexRunEventPage`: `events` (the most recent `limit`, oldest first), `total` (everything the run recorded) and `first_index` (where this slice starts). A client that asked for `?limit=500` of a 1,284-event run can now say so, instead of printing its own cap as a fact about the run.

!!! note "Semantic runs need an approved graph schema"
    When the derived graph policy is `semantic` (external corpus, `graph_indexing.enabled`, AST policy off), `POST /api/index` requires `approved_graph_schema_hash` — the exact hash from a reviewed proposal (`POST /api/index/{corpus_id}/graph-schema/proposal`). A missing hash, or a corpus change since the review, answers `409 graph_schema_approval_required` before any run fence is taken. An authenticated operator may also retry a refused entity-sparse run with `graph_empty_override_reason`; the override promotes chunks and vectors only. See [Indexing a corpus](manual/indexing.md) and [Indexing pipeline](indexing.md).

!!! note "Schema proposal sampling is bounded, and a textless PDF refuses fast"
    `POST /api/index/{corpus_id}/graph-schema/proposal` no longer converts whole documents behind the synchronous HTTP boundary. Text-bearing PDFs are sampled through a fast pypdfium2 page reader (`_extract_schema_sample_text_for_path` in `server/api/index.py`) — every page of a document with 36 or fewer pages, or 36 evenly spaced pages of a larger one — with each sampled page stamped `# <file> page <n>` so the sampled positions stay reviewable. A fixed 36-chunk budget is spread across the sampled documents and their full length (`documents-and-positions-v2`). The chunker tokenizer's warm-up is deferred until the first non-empty sample. A corpus whose sampled documents yield no text answers `422` naming the problem instead of starting whole-document OCR behind the public proxy window. See [Indexing pipeline](indexing.md).

!!! note "Proposal budgets and typed failures"
    One proposal is bounded by `graph_indexing.schema_proposal_timeout_s` (default `60` s, range 5–80 — always below the public HTTP deadline), `schema_proposal_reasoning_effort` (default `low`, independent of the per-chunk extraction effort) and `schema_proposal_max_output_tokens` (default `16384`). The total budget covers config loading, sampling, the gateway call and the persisted write: a timed-out proposal answers `504 graph_schema_deadline_exceeded`, an incomplete or refused gateway reply answers `502 graph_schema_generation_failed`, and a corpus or setting that changed while the proposal ran answers `409 graph_schema_context_changed` — in every case the previous proposal and its approval are preserved. Every attempt, including failed provider work, is saved as a `schema_proposal` run record the Indexing card prices through [native accounting](operations/native_costs.md), and changing any budget or the effort invalidates proposal reuse, so the approval you review is always tied to the settings that generated it.

!!! note "A corpus with no usable domain schema answers a typed 422, not a 500"
    When the sampled text yields no extractable domain — the proposer returns no node types or relationships, or a forbidden label — the domain validator rejects the shape and `POST /api/index/{corpus_id}/graph-schema/proposal` answers a typed `422 graph_schema_unusable` (previously the proposer's `ValueError` escaped as an unhandled `500`). The detail carries `corpus_id`, the extraction alias that ran (`model_alias`), the proposer's own `message`, an `operator_hint` (provide text with named entities and relationships, or point `graph_indexing.semantic_kg_llm_model` at another KG model alias, then generate the proposal again), plus `accounting_run_id` and `accounting_started_at` for the saved attempt, so a failed proposal's provider spend stays attributable. This is a review outcome the operator must read, not a server fault. See [Indexing pipeline](indexing.md).

!!! note "The saved proposal restores read-only — a GET never regenerates"
    `GET /api/index/{corpus_id}/graph-schema/proposal` answers the typed `GraphSchemaProposalState`: `current` (the saved proposal matches the corpus's current input fingerprint and proposal budgets — the proposal rides along), `missing`, `stale`, or `ineligible` (the derived graph policy is not semantic). It never initializes accounting, never calls the provider, and never writes a run record; a corpus that is deleted mid-read answers a typed `404`. Because the corpus row and its scoped config can change while the first observation waits, every read rechecks its context once — two observations, never a retry-until-stable loop — and a Postgres failure in either is the standard typed `503 dependency_unavailable`. The **RAG → Indexing** tab uses this on load to restore your saved review without spending a proposal; see [Indexing a corpus](manual/indexing.md).

```mermaid
flowchart LR
    Start["POST /api/index"] --> Worker["Indexer"]
    Worker --> Status["GET /api/index/status"]
    Worker --> Stats["GET /api/index/stats"]
    Worker --> Latest["GET /api/index/{corpus_id}/runs/latest"]
    Latest --> Events["GET /api/index/{corpus_id}/runs/{run_id}/events"]
```

!!! note "Run summaries record the figure phase"
    Every completed run’s `IndexRunSummary` persists `figures_described`, `figures_failed`, and `figures_undescribed`, plus `figure_description_cost_usd` — a ceiling on the vision-call cost, priced from catalog pricing for the run’s `indexing.figures.vision_model` over the full `max_completion_tokens` budget, and `null` when nothing was described or the alias is unpriced. A run that described no figures reports zero counts and no price, never a `$0.0000` line.

!!! note "Graph extraction outcomes are measured per chunk"
    A semantic run's extraction telemetry carries an `outcome_version` (`checkpoint_v1`) with durable per-chunk outcomes: chunks selected, chunks admitted into the extraction semaphore, durable reusable successes (`succeeded_chunks`, which includes `reused_chunks`), failed, cancelled, and chunks still unfinished when the run ended — the counters must account for every selected chunk, and the summary refuses a record whose progress does not name its owning run. Runs recorded before checkpointing keep their historical file-level aggregates (`whole_file_v0`), which the UI labels as aggregates rather than measured dispatches. On a failed run the graph failure codes come from this measured record (`extraction_failure`, `graph_build_or_promotion_failure`, `progress_persistence_failure`) instead of being inferred from file totals. See [Indexing a corpus](manual/indexing.md).

!!! tip "Polling many corpora? Read runs with `?finalize=false`"
    By default `GET /api/index/{corpus_id}/runs/latest` reconciles a persisted `indexing` run against the manifest and fence before answering — a fence read, a scoped-config load and an event-queue flush per call, and it rewrites the summary when the run turns out to have finished. Pass `finalize=false` for a pure read of the stored summary: no reconcile, no write, no event flush. A never-indexed corpus still answers `404`, so callers can tell “never indexed” from “could not be read”.

!!! note "Tokens and chunks are measured, not a byte ratio"
    `POST /api/index/estimate` no longer divides bytes by a constant. It samples the corpus through the configured chunker (`server/indexing/estimate.py`): for every file format present it measures a systematic sample across the size distribution, extracts each sampled file the way the indexer does, and extrapolates with a ratio estimator on the group's known bytes. The answer carries the point estimate (`estimated_total_tokens`, `estimated_total_chunks`), an error band (`estimated_tokens_low/high`, `estimated_chunks_low/high`, half-width `estimate_relative_error`), what was measured (`sampled_files`, `sampled_bytes`), and `elapsed_seconds`.

    The new `status` field is the contract for when numbers exist at all:

    - `ready` — the only state that carries measurements. Everything measured is populated.
    - `warming` — the estimator's tokenizer is still loading in a fresh API process (~27 s). The endpoint answers immediately with every measured field `null` and `warmup_seconds_remaining` for the wait message; clients poll until `ready`. The Dashboard and Indexing tab warm the tokenizer from their status reads, so this is usually gone before you click.
    - `insufficient_sample` — the sample says nothing about this corpus: a file format group measured nothing, or the band saturated past `indexing.estimate.max_relative_error` (default `0.9`). The file inventory is real; every measured field is `null`, and asking again returns the same refusal.

    In both non-ready states every measured field is `null`, not zero — a consumer that would have rendered "0 chunks" cannot. The floors live under `indexing.estimate.*` in the config model.

    Generation tokens are a separate measurement from these indexing units: the estimator also counts what the sampled chunk text carries into prompt-sized requests (`cl100k_base` over the chunk content, overlap included) and reports the total with its own error band in the estimate assumptions — so a corpus whose configured tokenizer units diverge wildly from real model tokens can no longer understate an extraction forecast.

!!! note "The estimate itemises optional vision costs"
    `POST /api/index/estimate` returns an `IndexEstimate` whose cost fields are additive:

    - `embedding_cost_usd` — always populated when catalog pricing exists for the embedding model
    - `semantic_kg_cost_usd` — present only when `graph_indexing.semantic_kg_enabled` is on
    - `estimated_figures` + `figure_description_cost_usd` — present only when `indexing.figures.enabled` **and** `indexing.figures.describe` are on *and* the corpus contains PDFs; the figure count is a heuristic (PDF pages × 0.4, rounded; omitted entirely when it rounds to zero) and the cost is priced from `data/models.json` for `indexing.figures.vision_model`

    `total_cost_usd` sums whichever components apply and is `null` when any applicable component has no catalog price. When figures are off (or the corpus has no PDFs), the figure fields stay `null` — the estimate never shows a `$0` figure cost that isn't really zero. The **RAG → Indexing** tab renders the breakdown as `Embed $X + Semantic KG $Y + Figures $Z (~N figures)`.

    Time comes from one model (`server/api/index.py` `_index_time_model`): `estimated_seconds` is the point estimate, the phases printed beside it — `estimated_seconds_embedding`, `estimated_seconds_semantic_kg`, `estimated_seconds_figures` — plus the fixed `estimated_seconds_overhead` sum to it exactly, and `estimated_seconds_low/high` are that same number scaled (×0.6–×1.9). The embedding phase is stated rather than derived by subtraction, so the tab's `Embed ~X + Semantic KG ~Y + Figures ~Z + startup ~Zs` breakdown can never disagree with the range quoted next to it — previously the embed leg alone could exceed the range's own lower bound.

!!! tip "Semantic KG cost is priced through the gateway alias"
    `semantic_kg_cost_usd` resolves its model through the same `gateway_alias` lookup the figure price uses — the alias the run would actually call (`graph_indexing.semantic_kg_llm_model`, else the gateway default). A catalog `model` id such as `z-ai/glm-5.3-flash` is not an alias (aliases may not contain a `/`), so resolving by model id would price nothing at all; the default `ragweld-local` alias is a real, priced catalog row at $0/$0, so a default-config corpus reports a true zero rather than an unknown total.

!!! note "Semantic KG pricing is token-based: measured inputs, evidenced outputs"
    The forecast no longer multiplies a per-chunk token guess across the corpus. When a **current** approved schema exists for the corpus, input tokens are measured: the estimator renders the approved extraction prompt — full template, schema payload, examples, and the structured-output schema the extractor sends on every request — over the actually sampled chunk text and extrapolates over the chunk band. Output tokens are priced only from **settled native evidence**: a prior run of the same corpus, alias, and schema hash whose closed request census matches the gateway ledger yields a per-request output mean (reasoning tokens included), scaled to the predicted chunks. With no usable output sample the paid total stays unknown — `semantic_kg_cost_usd` is `null` with an assumption line saying so — instead of inventing an output allowance, and a priced forecast also carries a scenario range built from the sampled chunk band and the observed per-request output minimum/maximum (a scenario, never a confidence interval or a spending limit). An unverifiable schema (no proposal, a stale fingerprint, or an unapproved hash) answers `null` with a "generate the current schema first" assumption, and a generation-token sample past its error ceiling refuses only the semantic price while the rest of the estimate stays ready.

!!! note "The semantic KG time estimate is calibrated from the corpus's last run"
    The semantic KG wall-clock estimate used to model one extraction call per second per worker — it quoted ~12 minutes for a 3,126-chunk rebuild that actually took 2 h 07 min. The model is now seconds **per chunk per worker**: a reasoning-model gateway round-trip costs roughly 10 s by default, and when the corpus's last complete semantic run ran the same extraction alias, the estimate reuses that run's measured rate instead (`GraphExtractionTelemetry.worker_seconds` divided by **fresh** successes — `succeeded_chunks` minus reused checkpoints — recorded on the run summary). The assumption line names its source either way — `measured on run <id> with <alias>` or `default; no completed run with this model to measure from` — and the parallelism is capped at 8 concurrent extraction calls however many `indexing.indexing_workers` you set. Under checkpointed extraction the measured rate is refused when a run's per-chunk outcomes are incomplete, so a mostly-reused rebuild cannot dilute seconds-per-chunk toward zero.

=== "Python"
```python
import httpx
httpx.post("http://127.0.0.1:58012/api/index", json={"corpus_id":"docs","repo_path":"/repo","force_reindex":False})
```

=== "curl"
```bash
curl -sS -X POST http://127.0.0.1:58012/api/index -H 'Content-Type: application/json' -d '{"corpus_id":"docs","repo_path":"/repo","force_reindex":false}'
```

=== "TypeScript"
```typescript
await fetch('http://127.0.0.1:58012/api/index', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({ corpus_id:'docs', repo_path:'/repo', force_reindex:false }) })
```

??? info "Dashboard"
    Use `DashboardIndexStatusResponse` and `DashboardIndexStatsResponse` to populate UI storage and status panels per corpus.
