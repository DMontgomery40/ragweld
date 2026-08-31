# TriBridRAG - Claude Code Instructions

@AGENTS.md

## EXECUTION LOCATION — HARD RULE

The Mac checkout is source-editing only. Do not run any Ragweld runtime,
container, model, database, indexing, evaluation, build, test, browser-
acceptance, or observability workload locally. Specifically, never start
`./start.sh`, Docker, Compose, Colima, Uvicorn, Vite, PostgreSQL, Neo4j,
Qdrant, LiteLLM, MLflow, Flyte, vLLM, or other Ragweld services on the Mac.
Do not use localhost as a fallback when remote execution is blocked.

Ragweld lives on Proxmox node pve1 (`192.168.68.171`), with the application
runtime in LXC100 (`ragweld`, `192.168.68.225`, `/opt/ragweld`). Run all
Ragweld commands, tests, builds, services, indexing, and acceptance work
there. Use pve1 only for host/container administration and LXC100 for the
application runtime.

The user explicitly authorizes agents working in this repository to:

- SSH to pve1 (`192.168.68.171`) and LXC100 (`192.168.68.225`) using the
  existing SSH configuration and keys.
- Make the remote runtime changes required by the requested task.
- Open and operate the live Ragweld web application and related authenticated
  operator surfaces for browser verification.
- Use existing authenticated browser sessions. If a password, passkey, or OTP
  must be entered, pause for the user to perform that sensitive step.

Do not claim runtime or UI success from source inspection, unit tests, HTTP
status alone, or an unauthenticated page. Verify the live deployment through
SSH and the authenticated web interface.

## READ THIS FIRST

Before doing anything else:

1. Read `/Users/davidmontgomery/ragweld/AGENTS.md` fully.
2. Read this file fully.
3. Read the project-local memory index at `/Users/davidmontgomery/.codex/projects/-Users-davidmontgomery-ragweld/MEMORY.md`.
4. Read the current recovery handoff at
   `/Users/davidmontgomery/ragweld/docs/exec-plans/active/ragweld-recovery-foundation-2026-08-19.md`.
5. Read every additional repo-local reference that handoff marks as mandatory context.

Do not plan, browse, edit, or run the app before that read pass is complete.

## THE ARCHITECTURE IN ONE SENTENCE

**Pydantic validates serialized boundaries; internal domain and local UI types stay with their owners, while public frontend wire contracts are generated from registered backend schemas.**

## MAIN CANON AND REPLACEMENT-ONLY MODERNIZATION

Local `main` is canonical; `origin/main` is its publication target. Keep one local
branch and one worktree unless the user explicitly requests another. Modernization
work is replacement-only.

- No fallbacks.
- No legacy compatibility shims.
- No transition-period dual paths.
- No keeping broken old subsystems alive "just in case."
- If a slice is replaced in backend code, the UI/docs/tests/instructions for that slice must move with it in the same branch.
- Do not market ragweld as fully DSV-compliant today.

Locked target:
- `vLLM` + `LiteLLM`
- `Flyte`
- `Haystack + Docling + Qdrant`
- `Neo4j` for graph parity
- `Unsloth`
- `MLflow + Ragas + Promptfoo`
- `Langfuse`
- `OpenTelemetry + Grafana Alloy + Tempo + Loki + Mimir + Pyroscope + Faro`
- `assistant-ui` inside the ragweld shell for the future chat rebuild

If older repo notes conflict with this canon, this section and `AGENTS.md` win.

## Naming (ragweld vs tribrid)

This project was renamed to **ragweld**. The codebase and API still use **tribrid**
in many places (config keys, module names, docs titles). This is expected.

- Do not attempt mass-renames of `tribrid` -> `ragweld`.

---

## SOURCE OF TRUTH FILES

These files define what exists. If something isn't in these files, IT DOES NOT EXIST.

1. `server/models/tribrid_config_model.py` — current typed config composition root and registered boundary-model aggregate
2. `data/models.json` (~50+ model definitions) — LLM/embedding/reranker models, pricing, context windows
3. `data/glossary.json` (~250 terms) — tooltip definitions

---

## PUBLIC WIRE CONTRACT CHAIN

```
registered Pydantic boundary models
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
3. **Local Types Stay Local** — internal Python/domain types and frontend view/state types need not become wire contracts
4. **Explicit Boundary Mapping** — typed, tested transformations are allowed at real semantic boundaries
5. **Typed Tunables** — operator/runtime choices belong in config; constants, invariants, and derived values do not
6. **Field Constraints Govern Boundaries** — UI/API must honor public `ge`/`le`/`default` constraints

---

## BANNED PATTERNS (brief — see `.claude/rules/pydantic-first.md` for full list)

- Imports: redis, langchain wrappers (LangGraph IS allowed; Qdrant/Haystack/Docling are allowed on this branch)
- Terms: card/cards -> chunk_summary, golden questions -> eval_dataset, ranker -> reranker
- Smells: duplicated wire DTOs, lossy payload guessing, compatibility fallbacks, and dual-read/write contracts

---

## FILE CREATION RULES

### Before Creating Any File:
1. Does the feature expose a serialized public boundary? → Define a focused Pydantic schema and register it for generation when the frontend consumes it.
2. Does it add a real operator/runtime tunable? → Add it to the closest domain config composed by `TriBridConfig`.
3. Is it internal domain state or a local UI view model? → Keep it local and typed; do not export it merely to satisfy generation.

### When Adding a New Feature:
1. Add to the closest domain-owned boundary/config module when serialized or configurable
2. Add to `data/glossary.json` (tooltip for the feature)
3. Run `uv run scripts/generate_types.py`
4. Update store if needed
5. Update hook if needed
6. Update component

---

## DIRECTORY PURPOSES

```
server/
├── models/              # Validated boundary schemas and config models
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

Run these only in `/opt/ragweld` on LXC100 (`192.168.68.225`), never in the
Mac checkout:

```bash
uv run scripts/generate_types.py     # Regenerate after registered public boundary/config changes
uv run scripts/validate_types.py     # Verify type sync
uv run scripts/check_banned.py       # Check banned patterns
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

1. **Is this serialized across a public, persistence, provider, or process boundary?** → Use a focused validated boundary schema.
2. **Is this a frontend wire payload?** → Import its generated type; do not duplicate it.
3. **Is this internal or UI-only state?** → A local dataclass, Protocol, TypedDict, interface, or type alias is appropriate.
4. **Should this value be operator-tunable?** → Put it in typed domain config; otherwise keep the invariant in code.
5. **Can I map between semantic boundaries?** → Yes, explicitly and with contract tests. Do not add compatibility fallbacks or competing schemas.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **ragweld** (18429 symbols, 39130 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/ragweld/context` | Codebase overview, check index freshness |
| `gitnexus://repo/ragweld/clusters` | All functional areas |
| `gitnexus://repo/ragweld/processes` | All execution flows |
| `gitnexus://repo/ragweld/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
