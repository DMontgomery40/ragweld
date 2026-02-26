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

- `generate_docs_from_diff.py` (**authoritative**)  
  Diff-driven doc updates. It builds a context bundle from `git diff` + current docs tree and asks the LLM to output a **unified diff patch** that only edits:
  - `mkdocs/docs/**`
  - `mkdocs.yml`

- `../generate_config_reference_docs.py` (**authoritative for config docs**)  
  Deterministic generator that builds a full **configuration reference** (1000+ parameters) from:
  - `server/models/tribrid_config_model.py` (defaults + constraints)
  - `data/glossary.json` (tooltip-level tuning guidance)
  Output: `mkdocs/docs/reference/config/**`

- `docs_prompt_base.md` (**authoritative**)  
  The shared style + accuracy constraints used by the autopilot.

- `docs_autopilot_enhanced.py` (legacy/manual)  
  Full-regeneration tool (model can rewrite many pages). Not used by the push autopilot.

- `bootstrap_docs.py` (legacy/manual)  
  Deterministic “bootstrap a fixed set of pages” generator. Not used by CI.

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

