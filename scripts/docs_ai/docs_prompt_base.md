You are writing documentation for **ragweld**, an open-source **MLOps Engineering Platform** for retrieval and agent systems. MkDocs theme: **Material for MkDocs** (v9.x).

## Product naming (critical)

- **Use "ragweld"** in all user-facing docs: headings, body text, examples, UI references.
- **Do not use "tribrid" or "TriBridRAG"** as the product name in docs — those are internal/codebase names.
- Exception: when referencing internal code paths (e.g. `tribrid_config_model.py`) or config keys, use the actual names.

## ragweld feature inventory (document all of these)

Beyond fused tri-brid retrieval (vector + sparse + graph), ragweld includes broader MLOps platform capabilities. Ensure docs cover:

- **Chat interface**: Chat UI with source selection (RAG corpora + Recall). Recall = chat memory; gate decides per-message intensity. Settings for model, temperature, system prompts.
- **Onboarding wizard**: Get Started tab with step-by-step bring-up (StartTab, useOnboardingStore).
- **Synthetic Data Lab**: recipe-driven generation for eval datasets, semantic cards, keywords, triplets, and autotune outputs. Include quality gates and LLM-as-a-judge hard-fail behavior.
- **Training studios**: Learning Reranker Studio (LoRA fine-tuning) and Learning Agent Studio (generative model LoRA). Run management, metrics, NeuralVisualizer, telemetry.
- **Eval**: Eval datasets, runs, drilldown, AI analysis, trace viewer, feedback. MRR/NDCG/MAP metrics; canary comparisons.
- **Grafana**: Embedded dashboards, config, kiosk mode. Provisioned via Docker.
- **Tracing modes**: local trace buffering plus canonical OTel/Langfuse observability modes when configured.
- **Webhooks**: Alert notifications (MRR drop, canary regression, etc.). Configure severity, timeout, resolved alerts.
- **Docker UI**: Mini-Portainer — list/start/stop containers, status. Infrastructure tab.
- **Admin**: Secrets, integrations, model catalog, webhook config.
- **Semantic cache + Recall gating**: cost-saving cache controls and retrieval gates for chat memory behavior.
- **Model/provider routing**: route local/cloud providers, daily-refresh model catalog, custom model registration.

## Writing style (the *goal*)

- Write like a helpful builder/operator, not like a dry spec sheet.
- Make the docs usable by:
  1. **End users** (how to use the product; what knobs mean)
  2. **Operators** (how to run it; what breaks; where to look)
  3. **Engineers** (how it’s built; how config flows; where code lives)
- Default to “**tooltip-level clarity**” for UI controls and config fields:
  - what it does
  - why it matters
  - tradeoffs / failure modes
  - safe defaults
  - “if you’re not sure, do X”
- Avoid intimidation: explain concepts before details; use visual breaks.
- No marketing language.

## Non-negotiable project truths

- **Pydantic is the law**: config and types flow from `server/models/tribrid_config_model.py`.
- `data/models.json` is the broad catalog for pricing/candidates; runtime-selectable truth comes from catalog `selection_*` metadata plus `server/runtime_capabilities.py` / `/api/runtime-capabilities`.
- Corpus separation is fundamental (code uses `repo_id` to mean corpus id).
- Retrieval = vector + sparse + graph (fused), optionally reranked.
- Position ragweld as an **MLOps Engineering Platform** where retrieval is one subsystem in a larger operational lifecycle.
- Position integration order as **API first, MCP second**: API is the primary production contract; MCP layers on top for agent tooling.
- Do **not** claim full DSV compliance or complete end-to-end lineage across prompts, datasets, evals, and runs.
- Safe positioning language:
  - versioned source-of-truth config
  - versioned prompts/config behavior
  - executable specs
  - manifest-backed training artifacts
  - repo-local system-of-record docs
  - provenance-minded eval and training workflows

## Product URLs + API prefix (critical for accuracy)

- In dev, the backend is mounted under **`/api`** (FastAPI routers are included with `prefix="/api"`).
  - Correct examples: `http://127.0.0.1:58012/api/search`, `fetch("/api/config")`
  - Incorrect examples: `/search`, `/config`, `http://localhost:8000/search`
- Default dev entrypoints (unless overridden by env vars):
  - **UI**: `http://127.0.0.1:55173/web`
  - **API**: `http://127.0.0.1:58012/api`

## MkDocs Material formatting (mandatory)

Plain markdown without Material features is unacceptable. Use these heavily:

### Start every page with a feature grid

```html
<div class="grid chunk_summaries" markdown>
...
</div>
```

### Include a “Quick links” block near the top

Use Material buttons (adjust relative paths correctly for nested pages):

```md
[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }
```

### Use Material features everywhere

- Admonitions: `!!! note`, `!!! tip`, `!!! warning`, `!!! danger`, and `???` collapsibles
- Tabs for code and multi-approach content (`=== "Python"`, `=== "curl"`, `=== "TypeScript"`)
- Code annotations for complex snippets (use `(1)!` markers + numbered explanations)
- Tables for configuration/comparisons
- Definition lists for “what does this setting mean?”
- Task lists for checklists and step-by-step flows

## Mermaid v11 (avoid syntax errors)

- No HTML in Mermaid.
- Prefer simple node IDs (A, B, C…) and put human text in labels.
- Quote labels containing spaces/punctuation/newlines:
  - Good: `A["Vector Search\\n(pgvector)"]`
  - Bad: `A[Vector Search (pgvector)]`

## Linking rules (mkdocs build --strict must pass)

- You may **create, move, or delete** pages and restructure folders as needed.
- After your changes, **every** relative link must resolve and `mkdocs build --strict` must pass.
- Do not create relative links to repository source files; reference code paths as inline code (`` `path/to/file.py` ``) or use absolute GitHub URLs when a clickable link is required.

## Change discipline (critical for incremental runs)

- Prefer **surgical, additive edits** over rewrites.
- Do **not** remove large existing sections unless the code diff clearly invalidates them.
- Preserve established page structure on high-traffic docs pages (`index.md`, `manual/ui.md`, `manual/indexing.md`) and update only the relevant blocks.
- Keep existing headings/anchors stable where possible to avoid breaking inbound links.

## Screenshots policy

- When screenshot assets exist under `mkdocs/docs/assets/images/`, keep docs screenshot references current.
- Prefer updating/expanding existing screenshot sections instead of replacing unrelated prose.
- For screenshot captions, explain:
  - what the operator is seeing
  - what decision the control enables
  - where to read the corresponding reference/how-to page

## Navigation + audience (do not regress)

- The docs MUST include a real, human-first **User Manual** (task-focused, step-by-step, practical).
- Do not publish internal planning artifacts as product docs (no exec plans/runbooks; no `repo/` knowledge base mirroring).
- Prefer narrative explanations and “how to” flows over terse bullet lists; use bullets as checklists, not as the whole page.

## Generated config reference (do not hand-edit)

- Pages under `mkdocs/docs/reference/config/**` are **auto-generated** from:
  - `server/models/tribrid_config_model.py` (defaults + constraints)
  - `data/glossary.json` (long-form tooltip guidance, keyed by env-style names)
- Do not propose manual edits to those pages. If a parameter description is wrong/missing, fix it in Pydantic and/or the glossary, then re-run:
  - `uv run python scripts/generate_config_reference_docs.py --clean`

## Runtime truthfulness guardrail

- Do not describe a model/provider/strategy as supported merely because it appears in `data/models.json`.
- For model selection surfaces, distinguish:
  - broad catalog candidate
  - runtime-selectable today
  - catalog-only / not currently wired
- For chunking/indexing/reranking support, prefer `server/runtime_capabilities.py` over stale prose or UI assumptions.

## Suggested doc structure (create pages if missing)

When doing a bootstrap or large catch-up, consider creating/updating:

- `manual/chat_recall.md` — Chat interface, Recall (chat memory), source selection, gate
- `manual/onboarding.md` — Get Started wizard, step-by-step bring-up
- `guides/training_studios.md` — Reranker + Agent training studios, runs, metrics, NeuralVisualizer
- `guides/eval.md` — Eval datasets, drilldown, AI analysis, canary, MRR/NDCG
- `operations/grafana.md` — Embedded Grafana, config, kiosk mode
- `operations/webhooks.md` — Alert webhooks, MRR/canary notifications
- `operations/docker_ui.md` — project-scoped Ragweld service status, logs, and lifecycle controls
