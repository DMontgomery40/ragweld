# Docs Autopilot (ragweld)

This folder contains the **documentation automation** tooling for the MkDocs + mike site in `mkdocs/`.

## The one workflow that matters

In GitHub Actions, the docs autopilot is driven by:

- `.github/workflows/docs-automation.yml` — generates doc updates from code diffs using an LLM
- `.github/workflows/deploy-docs.yml` — builds and deploys the MkDocs site (versioned with `mike`) to `gh-pages`

## Required GitHub secrets

The autopilot **will not write docs** unless you configure:

- `OPENAI_API_KEY` (Actions secret)

Optional (Actions variables or secrets):

- `OPENAI_MODEL` (default: `gpt-5`)
- `OPENAI_MAX_OUTPUT_TOKENS`
- `OPENAI_REASONING_EFFORT`
- `OPENAI_VERBOSITY`

## Scripts

- `run_ci_autopilot.py` (**authoritative for CI orchestration**)  
  The canonical GitHub Actions entrypoint for docs automation.
  - Resolves the base ref
  - Generates the docs plan artifact
  - Runs the LLM patch flow in a disposable git worktree
  - Regenerates deterministic config reference docs
  - Runs `mkdocs build --strict`
  - Commits and pushes only when the transactional worktree succeeds

- `generate_docs_from_diff.py` (**authoritative**)  
  Diff-driven doc updates. It builds a context bundle from `git diff` + current docs tree and asks the LLM to output a **unified diff patch** that only edits:
  - `mkdocs/docs/**`
  - `mkdocs.yml`
  - Includes guardrails against destructive page rewrites in normal incremental runs.
  - Includes screenshot asset inventory context (`mkdocs/docs/assets/images/**`, `web/public/screenshots/**`) so screenshot sections can be kept current.
  - Acts as the docs-autopilot engine; CI orchestration lives in `run_ci_autopilot.py`.

- `../generate_config_reference_docs.py` (**authoritative for config docs**)  
  Deterministic generator that builds a full **configuration reference** (1000+ parameters) from:
  - `server/models/tribrid_config_model.py` (defaults + constraints)
  - `data/glossary.json` (tooltip-level tuning guidance)
  Output: `mkdocs/docs/reference/config/**`

- `docs_prompt_base.md` (**authoritative**)  
  The shared style + accuracy constraints used by the autopilot.
  - If you want autopilot behavior to change consistently (for example, preserve high-traffic page structure or enforce screenshot-section rules), update this file first.

- `docs_autopilot_enhanced.py` (legacy/manual)  
  Full-regeneration tool (model can rewrite many pages). Not used by the push autopilot.

- `bootstrap_docs.py` (legacy/manual)  
  Deterministic “bootstrap a fixed set of pages” generator. Not used by CI.

## Ownership model

- `mkdocs/**` and `mkdocs.yml` are docs-autopilot output. Do not hand-edit them during normal feature work.
- Human/agent changes should target:
  - code and API/config source files
  - `data/models.json`
  - `data/glossary.json`
  - `server/runtime_capabilities.py`
  - `scripts/docs_ai/docs_prompt_base.md`
  - this README and repo-local docs under `docs/`
- The deterministic config reference under `mkdocs/docs/reference/config/**` is still generated from Pydantic + glossary and should never be hand-edited.

## Model catalog truthfulness

- Treat `data/models.json` as the broad pricing/catalog source, not the sole runtime-selection contract.
- Runtime-selectable catalog rows are identified by `selection_roles`, `selection_status`, and `selection_reason`.
- Non-model runtime truth (embedding providers/backends, reranker providers/backends, chunking strategies, indexing/search backends) comes from `server/runtime_capabilities.py` and `/api/runtime-capabilities`.
- Docs autopilot must not describe a catalog-only row as if it were currently runnable/selectable in the product.

## Positioning guardrail

Docs autopilot must not market ragweld as fully DSV-compliant today.

Safe public claims:

- versioned source-of-truth config
- versioned prompts/config behavior
- executable specs
- manifest-backed training artifacts
- repo-local system-of-record docs
- provenance-minded eval and training workflows

Do not generate claims about:

- full end-to-end lineage across prompts, datasets, evals, and runs
- complete dataset/eval artifact governance
- fully realized DSV-style tracking across the whole loop

## Local usage

Plan only (no network):

```bash
python scripts/docs_ai/generate_docs_from_diff.py --base origin/main --output mkdocs-docs-plan.md
```

Generate + apply patch (requires `OPENAI_API_KEY`):

```bash
export OPENAI_API_KEY=...
python scripts/docs_ai/generate_docs_from_diff.py --base origin/main --llm openai --apply
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

To reproduce the full CI orchestration locally from a clean checkout:

```bash
export OPENAI_API_KEY=...
python scripts/docs_ai/run_ci_autopilot.py --base origin/main
```

## Bootstrap / catch-up (one time)

If docs are missing/out-of-date and you want a “generate everything” pass, run against the **git empty tree**:

```bash
# Writes a large plan artifact (no network)
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --output mkdocs-docs-plan.md

# Generates + applies a docs-only patch (requires OPENAI_API_KEY)
export OPENAI_API_KEY=...
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --llm openai --apply
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

In GitHub Actions, manually run `Docs Autopilot (push)` with `base_ref=EMPTY`.
