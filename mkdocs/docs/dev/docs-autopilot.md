# Docs Autopilot (how docs stay current)

<div class="grid chunk_summaries" markdown>

-   :material-robot:{ .lg .middle } **Diff-driven**

    ---

    The agent reads `git diff` and proposes doc edits as a unified patch.

-   :material-shield-check:{ .lg .middle } **Scope-limited**

    ---

    It is only allowed to modify `mkdocs/docs/**` and `mkdocs.yml`.

-   :material-rocket-launch:{ .lg .middle } **Auto-deployed**

    ---

    Updated docs are built and deployed (via `mike`) to GitHub Pages (`gh-pages`).

</div>

[Dev workflow](../dev_workflow.md){ .md-button .md-button--primary }
[Docs scripts (repo)](https://github.com/DMontgomery40/ragweld/blob/main/scripts/docs_ai/README.md){ .md-button }

!!! warning "This requires an API key"
    The cloud autopilot will **not** generate docs unless GitHub Actions has `OPENAI_API_KEY` configured as a repository secret.

## What runs on every push

There are two GitHub Actions workflows:

- `Docs Autopilot (push)`:
  - Builds a **plan artifact** from `git diff`
  - Calls the LLM to generate a **unified diff patch**
  - Applies + commits doc updates back to the branch
  - Verifies `mkdocs build --strict`

- `Publish MkDocs (mike)`:
  - Builds the site
  - Deploys to `gh-pages` using `mike` (version: `latest`)

## Required GitHub configuration

In GitHub:

1. Go to **Settings → Secrets and variables → Actions**
2. Add **Repository secret**:
   - `OPENAI_API_KEY`

Optional variables:

- `OPENAI_MODEL` (default: `gpt-5`)

## Local testing

Plan only:

```bash
python scripts/docs_ai/generate_docs_from_diff.py --base origin/main --output mkdocs-docs-plan.md
```

Generate + apply patch (requires `OPENAI_API_KEY`):

```bash
export OPENAI_API_KEY=...
python scripts/docs_ai/generate_docs_from_diff.py --base origin/main --llm openai --apply
mkdocs build --strict
```

## Bootstrap / catch-up (one time)

If you need a “generate everything” pass (e.g., first setup, or docs are badly behind), run against the **git empty tree**:

```bash
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --output mkdocs-docs-plan.md
export OPENAI_API_KEY=...
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --llm openai --apply
mkdocs build --strict
```

In GitHub Actions, run `Docs Autopilot (push)` manually with `base_ref=EMPTY`.

## Guardrails (why this is safe-ish)

- The model is constrained to a **docs-only patch** (no code edits)
- The build must pass `mkdocs build --strict`
- The prompt includes strict accuracy rules (API is under `/api`, default ports, no leaking internal plans)

