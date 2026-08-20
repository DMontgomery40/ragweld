# Docs Autopilot Expansion — Full Feature Coverage

**Date**: 2026-02-25  
**Goal**: Make the docs-autopilot/mkdocs/mike pipeline generate documentation for **all** ragweld features, not just the RAG pipeline. No handwritten docs — everything flows from autopilot on commits.

---

## 1. How the Docs Autopilot Works (Architecture)

### 1.1 Two Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `Docs Autopilot (push)` | Push to `main`/`development` | Generates doc updates from code diffs via LLM, commits back |
| `Publish MkDocs (mike)` | Push to `main` (paths: `mkdocs.yml`, `mkdocs/**`) | Builds site, deploys to `gh-pages` with mike versioning |

### 1.2 Docs Autopilot Flow (`.github/workflows/docs-automation.yml`)

```
1. Checkout repo (fetch-depth: 0)
2. Install uv, mkdocs, mike, etc.
3. Generate plan: python scripts/docs_ai/generate_docs_from_diff.py --base <ref> --output mkdocs-docs-plan.md
4. Call LLM: same script with --llm openai --apply
5. Regenerate config reference: uv run python scripts/generate_config_reference_docs.py --clean
6. mkdocs build --strict
7. git commit + push (if changes)
```

### 1.3 Diff-Driven Context (Critical)

`generate_docs_from_diff.py` builds a **plan** that is sent to the LLM:

1. **Changed files** — `git diff --name-only <base>..HEAD` (filtered)
2. **Selected diffs** — For each file in a *preferred* subset of changed files, include `git diff` content
3. **Current mkdocs.yml** — Nav structure
4. **Current docs tree** — `mkdocs/docs/**/*.md` with first headings
5. **Prompt base** — `docs_prompt_base.md` (style, rules)
6. **Bootstrap-only** — If `base=EMPTY`, also include content of selected existing docs

**Key constraint**: `_select_context_files(changed, limit)` only adds files that are **in the changed set**. So:
- **Normal push**: Only files changed in that commit get their diffs sent to the LLM
- **Bootstrap (base=EMPTY)**: Entire repo is "changed" — preferred list determines which files get diffs

### 1.4 Preferred Files List

In `generate_docs_from_diff.py`, `_select_context_files` uses a `preferred` list to prioritize which changed files get their diffs included. Current list is heavily RAG-focused:

- Pydantic, main.py, config
- API: search, chat, eval, docker, etc.
- Retrieval: fusion, rerank, vector, sparse, graph
- Indexing: chunker, loader, embedder, graph_builder
- Frontend API client layer only (no UI components)

**Missing from preferred list** (so they rarely get diff context):
- Chat UI (ChatInterface, ChatSettings, SourceDropdown, Recall)
- Onboarding (StartTab, useOnboardingStore)
- Training studios (RerankerTraining/TrainingStudio, AgentTraining/TrainingStudio)
- Eval UI (EvalDrillDown, EvalAnalysisTab, TraceViewer)
- Grafana (GrafanaDashboard, GrafanaConfig, GrafanaEmbed)
- Webhooks (IntegrationsSubtab, GeneralSubtab, webhooks API)
- Docker UI (project-scoped Infrastructure Docker and Services subtabs)
- Admin panels (IntegrationsSubtab, GeneralSubtab)

### 1.5 Config Reference (Deterministic)

`generate_config_reference_docs.py` always runs and regenerates `mkdocs/docs/reference/config/**` from:
- `server/models/tribrid_config_model.py`
- `data/glossary.json`

This is comprehensive for config fields. No changes needed there.

---

## 2. Why Coverage Is Limited

1. **Diff-driven**: If chat UI, eval, training studios, etc. haven't changed in a commit, they never enter the diff context.
2. **Preferred list bias**: Even in bootstrap, only ~25–60 files get diffs; the list favors RAG/API.
3. **Prompt scope**: `docs_prompt_base.md` describes TriBridRAG as "vector + sparse + graph" — doesn't tell the LLM about chat recall, eval drilldown, training studios, Grafana, webhooks, Docker UI, onboarding.
4. **Nav structure**: `mkdocs.yml` has no explicit nav entries for Training Studios, Eval Analysis, Grafana, Webhooks, Onboarding — so the LLM has no target pages to create.

---

## 3. Proposed Changes (No Handwritten Docs)

### 3.1 Expand Preferred Files List

Add to `_select_context_files` in `generate_docs_from_diff.py`:

```python
# Chat UI + Recall
"web/src/components/Chat/ChatInterface.tsx",
"web/src/components/Chat/ChatSettings.tsx",
"web/src/components/Chat/SourceDropdown.tsx",
# Onboarding
"web/src/components/tabs/StartTab.tsx",
"web/src/stores/useOnboardingStore.ts",
# Training studios
"web/src/components/RerankerTraining/TrainingStudio.tsx",
"web/src/components/AgentTraining/TrainingStudio.tsx",
"web/src/components/RAG/LearningRankerSubtab.tsx",
"web/src/components/RAG/LearningAgentSubtab.tsx",
"server/api/reranker.py",
"server/api/agent.py",
# Eval
"web/src/components/Evaluation/EvalDrillDown.tsx",
"web/src/components/tabs/EvalAnalysisTab.tsx",
"web/src/components/Evaluation/TraceViewer.tsx",
"server/api/eval.py",
"server/api/dataset.py",
# Grafana + Webhooks
"web/src/components/Grafana/GrafanaDashboard.tsx",
"web/src/components/Grafana/GrafanaConfig.tsx",
"web/src/pages/GrafanaEmbed.tsx",
"web/src/components/Admin/IntegrationsSubtab.tsx",
"web/src/components/Admin/GeneralSubtab.tsx",
"web/src/api/webhooks.ts",
# Docker UI
"web/src/components/Infrastructure/DockerSubtab.tsx",
"server/api/docker.py",
```

### 3.2 Add Feature Inventory to docs_prompt_base.md

Add a section that tells the LLM what ragweld actually includes:

```markdown
## ragweld feature inventory (document all of these)

Beyond tri-brid retrieval (vector + sparse + graph), ragweld includes:

- **Chat interface**: Chat UI with source selection (RAG corpora + Recall). Recall = chat memory; gate decides per-message intensity. Settings for model, temperature, system prompts.
- **Onboarding wizard**: Get Started tab with step-by-step bring-up (StartTab, useOnboardingStore).
- **Training studios**: Learning Reranker Studio (LoRA fine-tuning) and Learning Agent Studio (generative model LoRA). Run management, metrics, NeuralVisualizer, telemetry.
- **Eval**: Eval datasets, runs, drilldown, AI analysis, trace viewer, feedback. MRR/NDCG/MAP metrics; canary comparisons.
- **Grafana**: Embedded dashboards, config, kiosk mode. Provisioned via Docker.
- **Webhooks**: Alert notifications (MRR drop, canary regression, etc.). Configure severity, timeout, resolved alerts.
- **Docker UI**: Mini-Portainer — list/start/stop containers, status. Infrastructure tab.
- **Admin**: Secrets, integrations, model catalog, webhook config.
```

### 3.3 Add Nav Placeholders in mkdocs.yml

Add nav entries so the LLM has targets. The LLM can create pages; nav tells it what structure to aim for:

```yaml
- User Manual:
    ...
    - Chat & Recall: manual/chat_recall.md
    - Onboarding: manual/onboarding.md
- Concepts:
    ...
    - Training studios: guides/training_studios.md
    - Eval & drilldown: guides/eval.md
- Operations:
    ...
    - Grafana & dashboards: operations/grafana.md
    - Webhooks & alerts: operations/webhooks.md
    - Docker UI: operations/docker_ui.md
```

(Exact paths can be adjusted; the point is to give the LLM a target structure.)

### 3.4 Expand _selected_docs_context for Bootstrap

In bootstrap mode, include more existing docs so the LLM can extend them:

```python
rel_paths = [
    # ... existing ...
    "manual/ui.md",
    "eval_guide.md",
    "howto/reranker.md",
    "observability.md",
]
```

### 3.5 Run Bootstrap Once

After applying the above changes, run the autopilot in bootstrap mode to do a one-time catch-up:

```bash
# In GitHub Actions: Docs Autopilot (push) → Run workflow → base_ref=EMPTY
```

Or locally:

```bash
export OPENAI_API_KEY=...
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --llm openai --apply
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

---

## 4. Files Modified (implemented)

| File | Change |
|------|--------|
| `scripts/docs_ai/generate_docs_from_diff.py` | Expanded `preferred` list with chat, onboarding, training studios, eval, Grafana, webhooks, Docker UI; expanded `_selected_docs_context` for bootstrap |
| `scripts/docs_ai/docs_prompt_base.md` | Added feature inventory + suggested doc structure |

---

## 5. Verification

After changes:

```bash
uv run scripts/check_banned.py
uv run scripts/validate_types.py
mkdocs build --strict
```

Then run bootstrap (base=EMPTY) and verify new pages appear.
