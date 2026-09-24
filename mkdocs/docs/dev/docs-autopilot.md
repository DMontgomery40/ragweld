# Docs Autopilot (how docs stay current)

<div class="grid chunk_summaries" markdown>

-   :material-robot:{ .lg .middle } **Diff-driven**

    ---

    The agent reads `git diff` and proposes doc edits as a unified patch.

-   :material-shield-check:{ .lg .middle } **Scope-limited**

    ---

    It is only allowed to modify `mkdocs/docs/**` and `mkdocs.yml`.

-   :material-file-restore:{ .lg .middle } **Repair rounds**

    ---

    Rejected hunks get a diff repair round, then a whole-page replacement round, before anything is dropped.

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
  - Regenerates the **full config reference** from Pydantic + glossary
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
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

## Repair rounds (what happens when a patch doesn't apply)

`git apply` sometimes rejects a hunk because a page changed after the diff was computed. Before the
generator drops a file, it tries two recovery rounds:

1. **Diff repair round** — the model re-emits only the rejected files, against their real current text.
2. **Page repair round** (default on) — for files still rejected, the model returns each page's
   **complete new content** between `### FILE: <path>` and `### END FILE` markers. Whole-page
   replacements pass the same safety checks as hunks: only already-rejected files may be written,
   only paths under `mkdocs/docs/`, and delete limits still apply (bootstrap runs with `--base EMPTY`
   may rewrite wholesale).

Anything still failing after both rounds is dropped with a `::warning::docs-autopilot:` line, and the
raw replies (`mkdocs-docs-llm-repair-raw.txt`, `mkdocs-docs-llm-page-repair-raw.txt`) are kept so you
can see what the model actually said. Set `DOCS_AUTOPILOT_PAGE_REPAIR=0` to skip the page repair round.

Either way, one more provider-free gate guards publication: the **page-wrapper check**. It walks every
materialized page under `mkdocs/docs/` looking for a leaked Markdown *presentation* wrapper — a leading
`` ```markdown `` fence wrapped around a generated title plus a feature grid — and removes exactly
that wrapper, preserving every other byte. Inner code examples are parsed independently, so their own
closing fences are never mistaken for the wrapper's; a page whose leading fence is ambiguous (a genuine
Markdown-syntax example, an unclosed inner fence) refuses the whole batch rather than guess. The check
runs against the final tree — config reference included — before the strict build, so no output path
(patch, diff repair, or page repair) can publish a wrapped page. The CI orchestrator can also run it
standalone as a bot-owned commit with no content generator or provider call:

```bash
python scripts/docs_ai/run_ci_autopilot.py --repair-page-wrappers-only
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

