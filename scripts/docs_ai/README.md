# Docs Autopilot (ragweld)

This folder contains the **documentation automation** tooling for the MkDocs + mike site in `mkdocs/`.

## Who writes the docs (read this before touching `mkdocs/`)

When repo notes say "docs are written by an agent", the agent is **this CI job**:
a GitHub Actions run that diffs the code, sends the diff to the OpenAI
Responses API, applies the returned patch to `mkdocs/docs/**` + `mkdocs.yml`,
and commits it as `docs(ai): autopilot update`. It is **not** the interactive
coding assistant (Claude Code, Codex, etc.) working in this checkout.

Consequences for a coding assistant:

- Never hand-write or hand-edit `mkdocs/**` or `mkdocs.yml`. The next autopilot
  run regenerates from the real sources and your edits are overwritten or
  clobbered (2026-03-02: a hand-rewritten `index.md` lost 247 lines this way).
- To make a page exist or change, change the **inputs** and push to `main`:
  code under `server/**` / `web/**` (including `server/models/**`, the Pydantic
  source of truth), `data/models.json`, `data/glossary.json`,
  `server/runtime_capabilities.py`, and `docs_prompt_base.md` (the style/scope
  rules the LLM follows). The push triggers the autopilot, which writes the
  page. That is what "do it without writing a single doc" means. The repo-local
  KB under `docs/` is the agent-facing engineering record, not an autopilot
  input: the generator drops `.md` files from its change context and the
  workflow does not trigger on `docs/**`.
- If the generated docs are badly behind (the autopilot did not run for a
  while), the fix is a manual `Docs Autopilot (push)` dispatch with `base_ref`
  set to the last `docs(ai)` commit (or `EMPTY` for a full rebuild), not a
  hand-written catch-up. (Push runs diff from the last *successful* run's head
  automatically, and bootstrap by themselves when there is none; runs before
  2026-08-23 could be "successful" without processing anything, so the current
  gap still wants the explicit base.)
- The deterministic config reference (`mkdocs/docs/reference/config/**`) is
  regenerated on every run from the Pydantic model + glossary; edit those.

## The one workflow that matters

In GitHub Actions, the docs autopilot is driven by:

- `.github/workflows/docs-automation.yml` — generates doc updates from code diffs using an LLM,
  pushes the `docs(ai)` commit, then dispatches the publish workflow
- `.github/workflows/deploy-docs.yml` — builds and deploys the MkDocs site (versioned with `mike`) to `gh-pages`

The dispatch step exists because a push made with the workflow's `GITHUB_TOKEN`
never fires another workflow's `push` trigger: before it was added, every
`docs(ai)` commit landed on `main` without a `mike deploy`, and the published
site only refreshed when a human push happened to touch `mkdocs/**`. After the
autopilot step, `run_ci_autopilot.py --publish-state` looks up the last
successful `deploy-docs.yml` run (`gh run list`) and reports
`publish_needed=true` when `main`'s newest commit touching `mkdocs/**` is not
an ancestor of what that run built; the workflow then runs
`gh workflow run deploy-docs.yml --ref main --repo "$GITHUB_REPOSITORY"`. Deciding from deploy history
rather than from "did this run push" also publishes docs commits stranded by
an earlier cancelled or failed run.

Diff base on push events: the job runs with `cancel-in-progress`, so push B
cancels the run for push A. `run_ci_autopilot.py` therefore diffs from the
head of the last *successful* autopilot run on the branch (again via
`gh run list`) when that commit is in the branch history. The push payload's
`before` SHA is never used: it covers only the last push, which is exactly
how A's changes would be lost. With no successful run on record the branch
counts as undocumented — `main` bootstraps from the empty tree (`EMPTY`), any
other branch diffs from its fork point with `origin/main`. If the run history
cannot be read, the run fails closed. An explicit `base_ref` input always
wins.

### Patch application

Hunk `@@` counts from a language model are routinely wrong — that single flaw
stalled this pipeline from 2026-03-12 to 2026-08-28, with `git apply` refusing
otherwise-correct patches as `corrupt patch at line N`. Patches are applied
with `git apply --recount --index`, which recomputes the counts. Context lines
must still match the file exactly, so a patch that invents content is still
refused; only the arithmetic is forgiven. A truncated response (Responses API
`status != "completed"`) is rejected at the transport, because recounting a
hunk that was cut off mid-body would land a half-written page.

Because that base is keyed on run *conclusion*, a run is "success" only when
the LLM lane processed its range. An AI patch that fails to apply is dropped
and the run still commits the deterministic config reference, but exits
non-zero; a config reference generation failure or a strict-build failure
leaves the branch unchanged and exits non-zero. Either way the next run
re-covers the same range from the last real success. Expect red runs to mean
exactly that.

Two bounds worth knowing. The generator sends a capped context (changed-file
list and a limited number of file diffs, chosen by its preferred-file list),
so a very large range — a bootstrap or a long catch-up — is documented from
that sample and the frontier still advances past the whole range; expanding
coverage is a generator/prompt change (`docs-autopilot-expansion.md`), not a
reason to hand-write pages. And a branch with no successful run re-attempts a
bootstrap-sized LLM call on every qualifying push until one run succeeds; a
red streak there is an operator signal, not something the job retries
differently.

## Required GitHub secrets

The autopilot **will not write docs** unless you configure:

- `OPENROUTER_API_KEY` (Actions secret) — `gh secret set OPENROUTER_API_KEY`

Optional (Actions variables or secrets):

- `DOCS_AUTOPILOT_MODEL` (default: `z-ai/glm-5.3-flash`)
- `DOCS_AUTOPILOT_MAX_OUTPUT_TOKENS` (default: `131072`, the provider maximum)
- `DOCS_AUTOPILOT_CONTEXT_BUDGET_TOKENS` (default: `700000`)
- `DOCS_AUTOPILOT_REASONING_EFFORT`, `DOCS_AUTOPILOT_VERBOSITY`, `DOCS_AUTOPILOT_API_BASE`

### Why this model

`z-ai/glm-5.3-flash` carries a 1,048,576-token window at ~$0.075/M in and
$0.25/M out, so a full run costs roughly **$0.08**. That budget is what pays
for the thing that actually makes the pipeline work: the plan quotes the
**entire current docs corpus verbatim** (92 pages, ~580 KB) so the model can
copy context lines byte-for-byte instead of guessing them. A run at
2026-08-28 built a 651k-token plan — every page quoted, 138 code diffs
included, and the count of diffs dropped for budget stated in the plan itself.
Nothing is capped silently.

## Scripts

- `run_ci_autopilot.py` (**authoritative for CI orchestration**)  
  The canonical GitHub Actions entrypoint for docs automation.
  - Resolves the base ref
  - Generates the docs plan artifact
  - Runs the LLM patch flow in a disposable git worktree
  - Regenerates deterministic config reference docs
  - Runs `mkdocs build --strict`
  - Commits and pushes only when the transactional worktree succeeds
  - Writes `pushed=true|false` (+ `commit_sha`) to `$GITHUB_OUTPUT`; exits non-zero when
    the LLM lane did not process the range (see "The one workflow that matters")
  - `--publish-state` mode: writes `publish_needed=true|false` + `docs_commit` for the
    branch tip so the workflow can dispatch `deploy-docs.yml`

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

Generate + apply patch (requires `OPENROUTER_API_KEY`):

```bash
export OPENROUTER_API_KEY=...
uv run python scripts/docs_ai/generate_docs_from_diff.py --base origin/main --llm openrouter --apply
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

To reproduce the full CI orchestration locally from a clean checkout:

```bash
export OPENROUTER_API_KEY=...
python scripts/docs_ai/run_ci_autopilot.py --base origin/main
```

## Bootstrap / catch-up (one time)

If docs are missing/out-of-date and you want a “generate everything” pass, run against the **git empty tree**:

```bash
# Writes a large plan artifact (no network)
python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --output mkdocs-docs-plan.md

# Generates + applies a docs-only patch (requires OPENROUTER_API_KEY)
export OPENROUTER_API_KEY=...
uv run python scripts/docs_ai/generate_docs_from_diff.py --base EMPTY --llm openrouter --apply
uv run python scripts/generate_config_reference_docs.py --clean
mkdocs build --strict
```

In GitHub Actions, manually run `Docs Autopilot (push)` with `base_ref=EMPTY`.
