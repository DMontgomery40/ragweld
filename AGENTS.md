# AGENTS.md

This file is the agent entrypoint for `/Users/davidmontgomery/ragweld`.
It is intentionally short: a map, not a manual. Start here, then follow links.

## Naming (ragweld vs tribrid)

This project was renamed to **ragweld**. The codebase and API still use **tribrid**
in many places (module names, config keys, UI labels, docs titles). This is
expected and not a bug.

- Do not attempt mass-renames of `tribrid` -> `ragweld`.
- Treat `tribrid` as stable internal naming; treat `ragweld` as the product/repo name.

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
- `mkdocs/**` and `mkdocs.yml` are docs-autopilot output. Do not hand-edit them in normal feature work.
- Tests must be real (no fake-green):
  - No Playwright request interception stubs for new/edited E2E tests.
  - No Python mocking (`unittest.mock`, `monkeypatch`) in new/edited tests.

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
