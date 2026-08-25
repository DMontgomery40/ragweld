# AGENTS.md

This file is the agent entrypoint for `/Users/davidmontgomery/ragweld`.
It is intentionally short: a map, not a manual. Start here, then follow links.

## Mandatory Read Order (Before Doing Anything)

Before running commands, editing files, or making plans:

1. Read this `AGENTS.md` fully.
2. Read `/Users/davidmontgomery/ragweld/CLAUDE.md` fully.
3. Read the project-local memory index at `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`.
4. Read the current recovery handoff:
   `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`
5. Read any additional repo-local references that the current handoff marks as required context.

Do not touch code, tests, data, servers, or UI before that read pass is complete.

## Naming (ragweld vs tribrid)

This project was renamed to **ragweld**. The codebase and API still use **tribrid**
in many places (module names, config keys, UI labels, docs titles). This is
expected and not a bug.

- Do not attempt mass-renames of `tribrid` -> `ragweld`.
- Treat `tribrid` as stable internal naming; treat `ragweld` as the product/repo name.

## Main Canon and Replacement-Only Modernization

Local `main` is the canonical development line and `origin/main` is its publication target.
Keep one local branch and one worktree unless the user explicitly authorizes another.
Modernization work is **replacement-only**.

- Do not add legacy fallbacks, compatibility shims, transition periods, dual-write paths, or "temporary" old/new coexistence logic.
- If a slice is being replaced on this branch, the touched backend, UI, docs, tests, and agent instructions must move to the new path together.
- If the replacement is not ready, do not land a half-migrated cutover that routes back into the legacy subsystem.
- If older docs, memories, prompts, or rules conflict with this canon, this section wins.

Locked target stack:
- Inference: `vLLM`
- Gateway/routing: `LiteLLM`
- Orchestration: `Flyte`
- Retrieval/indexing: `Haystack + Docling + Qdrant`
- Graph parity: `Neo4j`
- Training execution: `Unsloth`
- Runs/evals/regressions: `MLflow + Ragas + Promptfoo`
- Eval drilldown substrate: `Langfuse`
- Observability fabric: `OpenTelemetry + Grafana Alloy + Tempo + Loki + Mimir + Pyroscope + Faro`
- Frontend shell/workbench target: `Dockview + react-resizable-panels + TanStack Query + assistant-ui + shadcn/ui + Radix + xterm + Monaco`

Active modernization references:
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`

## Start Here (Repo Map)

Source of truth files (if it is not here, it does not exist):
- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` (current aggregate for validated config + registered API boundary shapes)
- `/Users/davidmontgomery/ragweld/data/models.json` (model catalog: providers, pricing, context)
- `/Users/davidmontgomery/ragweld/data/glossary.json` (tooltips + terminology)

Generated types chain (do not hand-write API types):
- `/Users/davidmontgomery/ragweld/scripts/generate_types.py` (Pydantic -> TS)
- `/Users/davidmontgomery/ragweld/web/src/types/generated.ts` (generated output; do not edit)

Knowledge base (repo-local, versioned):
- `/Users/davidmontgomery/ragweld/docs/index.md` (entrypoint)
- `/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md` (docs-autopilot ownership + CI contract)

Config reality map (machine-checked by `scripts/check_config_reality.py`):
- `/Users/davidmontgomery/ragweld/spec/config_reality_map.json`

## Operating Model (Agent-First)

- Humans specify intent and acceptance criteria; agents execute and verify.
- Prefer progressive disclosure: follow links to the closest source of truth.
- If a rule matters, enforce it mechanically (scripts/hooks/tests), not as prose.
- If knowledge is not in this repo, it does not exist to the agent: encode it here.
- Keep changes small and verifiable; avoid wide refactors unless explicitly required.

## Hard Invariants (Non-Negotiable)

- Pydantic validates serialized boundaries: FastAPI request/response bodies, persisted operator configuration, and untrusted external or cross-process payloads.
- Boundary models belong in the closest domain-owned module. `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` remains the current aggregate and config composition root, not the mandatory home of every internal type.
- Public frontend wire types are generated and imported from `generated.ts`; do not hand-copy them.
- Internal Python types and local frontend props, form state, Zustand state, and view models may be handwritten near their owners.
- Explicit, typed, tested transformations are allowed at real boundaries. Hidden or lossy mapping, competing canonical schemas, compatibility fallbacks, and dual-read/write contracts are forbidden.
- Put real operator/runtime tunables in typed config. Keep constants, invariants, derived values, and UI-only state in ordinary code.
- OSS-composition fork rule: on this branch, replacement means replacement.
  - Do not keep old behavior alive by silently routing back into the legacy subsystem once a replacement slice exists.
  - Do not introduce migration seams, compatibility adapters, legacy toggles, or transition periods on this branch.
  - If the new path is broken, fix the new path before landing the slice; do not add fallback spaghetti.
- OSS-composition fork UI rule: protected operator-facing surfaces are mandatory in every slice.
  - Do not land backend-only fork work that leaves the workbench UI stale, misleading, or missing the new control/visibility surface.
  - Every material migration slice must either preserve or explicitly advance the in-product UI for the affected surface in the same branch.
  - Training Center, eval drilldown, retrieval/indexing controls, graph parity surfaces, Grafana embeds, and the dock/workbench shell are first-class acceptance targets, not cleanup work for later.
- Qdrant/Haystack/Docling are allowed and expected on this branch. Old instructions that ban Qdrant are stale here.
- `mkdocs/**` and `mkdocs.yml` are docs-autopilot output. Do not hand-edit them in normal feature work.
- Tests must be real (no fake-green):
  - No Playwright request interception stubs for new/edited E2E tests.
  - No Python mocking (`unittest.mock`, `monkeypatch`) in new/edited tests.
  - Real queries only: retrieval/chat/eval/search/answer exercises must use a
    genuine domain question, never `test`/`hello`/placeholder input. Every
    query/answer pair is reranker triplet-mining signal; placeholders are
    fake-green. See `.claude/rules/testing.md`.
- Major features/slices get an adversarial review by an independent stronger
  model before "done" — preferred `codex exec` at high reasoning effort,
  prompted to refute the change. See `.claude/rules/testing.md`.

## Product Positioning

- Do not market ragweld as fully DSV-compliant today.
- Safe selling points:
  - versioned source-of-truth config
  - versioned prompts/config behavior
  - quality-loop lineage bundles across prompt/config/dataset/run/publish/promote flows
  - executable specs
  - manifest-backed training artifacts
  - repo-local system-of-record docs
  - provenance-minded eval and training workflows
- Do not claim:
  - full end-to-end lineage across prompts, datasets, evals, and runs
  - complete dataset/eval artifact governance
  - fully realized DSV-style tracking across the whole loop
- If positioning changes, update `/Users/davidmontgomery/ragweld/README.md`, landing/onboarding copy in `web/src`, docs-autopilot guidance, repo-local docs, project memory, and tests together.

## Docs Ownership

- Docs-autopilot is essential infrastructure in this repo. Published MkDocs output must track the literal code and config that exist.
- "Docs are written by an agent" means the docs-autopilot **CI job** (`scripts/docs_ai/run_ci_autopilot.py`, OpenAI via GitHub Actions), never the coding assistant in this checkout. To get a page written, change the generator's inputs (code, `data/models.json`, `data/glossary.json`, `scripts/docs_ai/docs_prompt_base.md`) and push; do not write the page. Read `scripts/docs_ai/README.md` ("Who writes the docs") before touching anything under `mkdocs/`.
- Treat `mkdocs/**` and `mkdocs.yml` as generated/published output, not as source-of-truth engineering docs.
- If docs behavior/content needs to change, edit the real sources instead:
  - code and API/config sources
  - `/Users/davidmontgomery/ragweld/data/models.json`
  - `/Users/davidmontgomery/ragweld/data/glossary.json`
  - `/Users/davidmontgomery/ragweld/scripts/docs_ai/docs_prompt_base.md`
  - `/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md`
  - repo-local KB pages under `/Users/davidmontgomery/ragweld/docs/`

## Workflow Checklist (Any Change)

1. Locate the source of truth (Pydantic model, models.json, glossary.json, spec/).
2. Make the minimal change in the source of truth first.
3. Regenerate derived artifacts when required (e.g. `generate_types.py`).
4. Update the closest agent-facing docs entry (`docs/` KB page or `scripts/docs_ai/README.md`) if behaviour changed. Do not hand-edit `mkdocs/**` or `mkdocs.yml`.
5. Run verification commands (below) until green.
6. Only then consider the work done.

## Verification Commands

```bash
cd /Users/davidmontgomery/ragweld

uv run python scripts/check_docs_ownership.py
uv run scripts/check_banned.py
uv run scripts/validate_types.py
uv run python scripts/generate_litellm_config.py --check
uv run pytest -q
```

If you changed frontend code:

```bash
npm --prefix web run lint
npm --prefix web run build
```

## Where to Write Things Down

- Principles / taste invariants: `/Users/davidmontgomery/ragweld/docs/design-docs/core-beliefs.md`
- Larger work plans: `/Users/davidmontgomery/ragweld/docs/exec-plans/active/`
- Tech debt backlog: `/Users/davidmontgomery/ragweld/docs/exec-plans/tech-debt-tracker.md`
- References (links, snippets, external context you want in-repo): `/Users/davidmontgomery/ragweld/docs/references/index.md`
- Current branch handoff: `/Users/davidmontgomery/ragweld/docs/exec-plans/active/handoff-2026-08-22-session5.md`
