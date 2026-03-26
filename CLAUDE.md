# TriBridRAG - Claude Code Instructions

@AGENTS.md

## READ THIS FIRST

Before doing anything else:

1. Read `/Users/davidmontgomery/ragweld/AGENTS.md` fully.
2. Read this file fully.
3. Read the project-local memory index at `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`.
4. Read the latest handoff memory at
   `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/memory/next-agent-canon-reset-handoff-2026-03-26.md`.
5. Read every additional memory file that handoff marks as mandatory context.

Do not plan, browse, edit, or run the app before that read pass is complete.

## THE ARCHITECTURE IN ONE SENTENCE

**Pydantic is the law. Everything else derives from it. You cannot add features that don't exist in Pydantic first.**

## FEATURE BRANCH CANON (feat/oss-composition-kickoff)

This branch is replacement-only.

- No fallbacks.
- No legacy compatibility shims.
- No transition-period dual paths.
- No keeping broken old subsystems alive "just in case."
- If a slice is replaced in backend code, the UI/docs/tests/instructions for that slice must move with it in the same branch.

Locked branch target:
- `vLLM` + `LiteLLM`
- `Flyte`
- `Haystack + Docling + Qdrant`
- `Neo4j` for graph parity
- `Unsloth`
- `MLflow + Ragas + Promptfoo`
- `Langfuse`
- `OpenTelemetry + Grafana Alloy + Tempo + Loki + Mimir + Pyroscope + Faro`
- `assistant-ui` inside the ragweld shell for the future chat rebuild

If older repo notes conflict with this branch canon, this section and `AGENTS.md` win.

## Naming (ragweld vs tribrid)

This project was renamed to **ragweld**. The codebase and API still use **tribrid**
in many places (config keys, module names, docs titles). This is expected.

- Do not attempt mass-renames of `tribrid` -> `ragweld`.

---

## SOURCE OF TRUTH FILES (THE LAW)

These files define what exists. If something isn't in these files, IT DOES NOT EXIST.

1. `server/models/tribrid_config_model.py` (~1000+ fields) — every tunable parameter, feature flag, threshold
2. `data/models.json` (~50+ model definitions) — LLM/embedding/reranker models, pricing, context windows
3. `data/glossary.json` (~250 terms) — tooltip definitions

---

## THE DERIVATION CHAIN

```
tribrid_config_model.py (PYDANTIC - SOURCE OF TRUTH)
    ↓ pydantic2ts (uv run scripts/generate_types.py)
web/src/types/generated.ts (AUTO-GENERATED - DO NOT EDIT)
    ↓ imports
web/src/stores/*.ts (ZUSTAND STORES)
    ↓ wraps
web/src/hooks/*.ts (REACT HOOKS)
    ↓ uses
web/src/components/**/*.tsx (REACT COMPONENTS)
```

---

## HARD RULES (summary — see `.claude/rules/` for domain-specific details)

1. **Pydantic First** — add field to config model before implementing anything
2. **No Hand-Written API Types** — import from `generated.ts`
3. **No Adapters/Transformers** — fix the Pydantic model instead
4. **Config Controls Everything** — no hardcoded thresholds
5. **Field Constraints Are Law** — UI/API must honor `ge`/`le`/`default`

---

## BANNED PATTERNS (brief — see `.claude/rules/pydantic-first.md` for full list)

- Imports: redis, langchain wrappers (LangGraph IS allowed; Qdrant/Haystack/Docling are allowed on this branch)
- Terms: card/cards -> chunk_summary, golden questions -> eval_dataset, ranker -> reranker
- Smells: `class *Adapter`, `class *Transformer`, `class *Mapper`, `interface` in .tsx

---

## FILE CREATION RULES

### Before Creating Any File:
1. Does the feature need configurable parameters? → Add to `tribrid_config_model.py` FIRST
2. Does it need Pydantic types? → Add to config model, run `generate_types.py`
3. Is it a new component? → Trace the chain: What hook? → What store? → What Pydantic model?

### When Adding a New Feature:
1. Add to `tribrid_config_model.py` (if configurable)
2. Add to `data/glossary.json` (tooltip for the feature)
3. Run `uv run scripts/generate_types.py`
4. Update store if needed
5. Update hook if needed
6. Update component

---

## DIRECTORY PURPOSES

```
server/
├── models/              # Pydantic models - THE LAW
├── api/                 # FastAPI routers
├── db/                  # Database clients (Postgres, Neo4j)
├── retrieval/           # Search pipeline
├── reranker/            # MLX/LoRA reranker inference + artifacts
├── indexing/            # Chunking, embedding, graph building
├── training/            # Reranker training (LoRA fine-tuning)
└── services/            # Business logic

web/src/
├── types/generated.ts   # AUTO-GENERATED from Pydantic - DO NOT EDIT
├── stores/              # Zustand stores
├── hooks/               # React hooks
├── components/          # React components
└── api/                 # API client

data/
├── models.json          # LLM model definitions
└── glossary.json        # Tooltip definitions
```

---

## COMMANDS

```bash
uv run scripts/generate_types.py     # Regenerate TS types (after ANY Pydantic change)
uv run scripts/validate_types.py     # Verify type sync
uv run scripts/check_banned.py       # Check banned patterns
./start.sh                           # Docker + Backend + Frontend
./start.sh --with-observability      # + Prometheus + Grafana + Loki
./start.sh --no-frontend             # Backend only
```

---

## RALPH LOOP (HOW TO RUN IT CORRECTLY)

**Do NOT rely on "completion promises" alone.** This repo prevents fake completion with a **verification-based Stop hook** that blocks stopping until checks pass.

### What Actually Enforces Completion
- **Stop hook**: `.claude/hooks/verify-tribrid.sh` — blocks stopping if validators/tests fail
- **Ralph loop**: the `ralph-loop` plugin keeps re-feeding the same prompt each iteration

### Preconditions
- Start Claude Code from repo root: `cd /Users/davidmontgomery/ragweld`
- Restart Claude Code after changing `.claude/settings.json` (hooks snapshot at startup)
- Project config must include `enabledPlugins.ralph-loop@claude-plugins-official = true` and the Stop hook

### Start a Ralph Loop
```bash
/ralph-loop "Continue implementing TriBridRAG.
At the start of EACH iteration:
1) Read TODO.md and pick the first unchecked [ ] item.
2) Implement it end-to-end.
3) Run verification: check_banned, validate_types, pytest
4) Mark [x] only when truly done.
IMPORTANT: If Stop hook blocks, fix that exact failure." --max-iterations 200 --completion-promise "COMPLETE"
```

### Monitor / Cancel
- Monitor: `grep '^iteration:' .claude/ralph-loop.local.md`
- Cancel: `/cancel-ralph`

---

## MANDATORY TESTING RULE

**Every change must be tested before completion.** See `.claude/rules/testing.md` for full details.

- Temporary tests → `.tests/` (gitignored)
- Permanent tests → `tests/`
- Zero-mocked tests enforced for new/edited tests
- No Playwright API mocking, no Python mocking, no skip stubs

---

## AUTO MEMORY RULE

For every major task or significant debugging session, create a dedicated `.md` file in auto memory
(`~/.claude/projects/<project>/memory/`) and link it from MEMORY.md under the appropriate heading.

Each file should capture:
- What was done and why
- Key decisions made
- Gotchas encountered
- Outcome / result

This ensures institutional knowledge accumulates across sessions.

---

## WHEN IN DOUBT

1. **Can I add this field?** → Is it in tribrid_config_model.py? No → Add it there first.
2. **Can I use this type?** → Is it in generated.ts? No → Add to Pydantic first.
3. **Can I hardcode this value?** → Should it be configurable? Yes → Add to config.
4. **Can I write an adapter or fallback?** → No. Fix or replace the real path.
