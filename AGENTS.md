# AGENTS.md

This file is the agent entrypoint for `/Users/davidmontgomery/ragweld`.
It is intentionally short: a map, not a manual. Start here, then follow links.

## Mandatory Read Order (Before Doing Anything)

Before running commands, editing files, or making plans:

1. Read this `AGENTS.md` fully.
2. Read `/Users/davidmontgomery/ragweld/CLAUDE.md` fully.
3. Read the project-local memory index at `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`.
4. Read the latest handoff memory:
   `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/next-agent-canon-reset-handoff-2026-03-26.md`
5. Read any additional memory files that the latest handoff marks as required context.

Do not touch code, tests, data, servers, or UI before that read pass is complete.

## Naming (ragweld vs tribrid)

This project was renamed to **ragweld**. The codebase and API still use **tribrid**
in many places (module names, config keys, UI labels, docs titles). This is
expected and not a bug.

- Do not attempt mass-renames of `tribrid` -> `ragweld`.
- Treat `tribrid` as stable internal naming; treat `ragweld` as the product/repo name.

## Branch Canon (feat/oss-composition-kickoff)

This branch is the OSS-composition fork branch. It is **replacement-only**.

- Do not add legacy fallbacks, compatibility shims, transition periods, dual-write paths, or "temporary" old/new coexistence logic.
- If a slice is being replaced on this branch, the touched backend, UI, docs, tests, and agent instructions must move to the new path together.
- If the replacement is not ready, do not land a half-migrated cutover that routes back into the legacy subsystem.
- If older docs, memories, prompts, or rules conflict with this branch canon, this section wins.

Locked target stack for this branch:
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

Active branch references:
- `/Users/davidmontgomery/ragweld/docs/references/observability-online-slice.md`
- `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`

## Start Here (Repo Map)

Source of truth files (if it is not here, it does not exist):
- `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` (Pydantic: config + API shapes)
- `/Users/davidmontgomery/ragweld/data/models.json` (model catalog: providers, pricing, context)
- `/Users/davidmontgomery/ragweld/data/glossary.json` (tooltips + terminology)

Generated types chain (do not hand-write API types):
- `/Users/davidmontgomery/ragweld/scripts/generate_types.py` (Pydantic -> TS)
- `/Users/davidmontgomery/ragweld/web/src/types/generated.ts` (generated output; do not edit)

Knowledge base (repo-local, versioned):
- `/Users/davidmontgomery/ragweld/docs/index.md` (entrypoint)
- `/Users/davidmontgomery/ragweld/scripts/docs_ai/README.md` (docs-autopilot ownership + CI contract)

Executable specs (structured, machine-checkable intent):
- `/Users/davidmontgomery/ragweld/spec/README.md`

## Operating Model (Agent-First)

- Humans specify intent and acceptance criteria; agents execute and verify.
- Prefer progressive disclosure: follow links to the closest source of truth.
- If a rule matters, enforce it mechanically (scripts/hooks/tests), not as prose.
- If knowledge is not in this repo, it does not exist to the agent: encode it here.
- Keep changes small and verifiable; avoid wide refactors unless explicitly required.

## Hard Invariants (Non-Negotiable)

- Pydantic-first: define shapes and config in `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` first.
- No hand-written API payload types in the frontend: import from `generated.ts`.
- No adapters/transformers/mappers to reshape API payloads: fix the Pydantic model.
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
- Current branch handoff: `/Users/davidmontgomery/ragweld/docs/exec-plans/active/oss-composition-kickoff-handoff-2026-03-25.md`
