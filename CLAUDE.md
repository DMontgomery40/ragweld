# TriBridRAG - Claude Code Instructions

## THE ARCHITECTURE IN ONE SENTENCE

**Pydantic is the law. Everything else derives from it. You cannot add features that don't exist in Pydantic first.**

---

## TERMINOLOGY (CORPUS VS REPO)

TriBridRAG is **corpus-first**: a **corpus** is any folder you index/search/GraphRAG over (a git repo, a docs folder, a monorepo subtree, etc.). Corpus separation is fundamental: each corpus has its own storage + graph + config.

**Important compatibility note:** the codebase and API still use the field name `repo_id` for the **corpus identifier**. Treat `repo_id` as `corpus_id`.

---

## SOURCE OF TRUTH FILES (THE LAW)

These files define what exists. If something isn't in these files, IT DOES NOT EXIST.

### 1. `server/models/tribrid_config_model.py` (~500+ fields)
- Every tunable parameter in the entire system
- Every feature flag, threshold, weight, path, URL
- If the UI has a slider, the Pydantic model has the field
- If the backend has a configurable behavior, the Pydantic model has the field

### 2. `data/models.json` (~50+ model definitions)  
- Every LLM/embedding/reranker model the system knows about
- Provider, family, input/output pricing, context window
- Used by: cost calculator, model picker, chunking (max context)

### 3. `data/glossary.json` (~250 terms)
- Every tooltip definition
- Term, definition, category, links
- Used by: TooltipIcon component, Glossary tab

---

## THE DERIVATION CHAIN

```
┌─────────────────────────────────────────────────────────────────┐
│  tribrid_config_model.py   (PYDANTIC - SOURCE OF TRUTH)         │
│  - TriBridConfig                                                │
│  - RetrievalConfig, FusionConfig, RerankerConfig, etc.          │
│  - ~500 fields with Field(description=..., ge=..., le=...)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ GENERATED (pydantic2ts)
┌─────────────────────────────────────────────────────────────────┐
│  web/src/types/generated.ts   (TYPESCRIPT - AUTO-GENERATED)     │
│  - DO NOT EDIT BY HAND                                          │
│  - Run: uv run scripts/generate_types.py                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ IMPORTS FROM generated.ts
┌─────────────────────────────────────────────────────────────────┐
│  web/src/stores/*.ts   (ZUSTAND STORES)                         │
│  - useConfigStore.ts                                            │
│  - Types come from generated.ts, NOT hand-written               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ USES STORES
┌─────────────────────────────────────────────────────────────────┐
│  web/src/hooks/*.ts   (REACT HOOKS)                             │
│  - useConfig(), useFusion(), useReranker()                      │
│  - Return types match store types (from generated.ts)           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ USES HOOKS
┌─────────────────────────────────────────────────────────────────┐
│  web/src/components/**/*.tsx   (REACT COMPONENTS)               │
│  - Props derived from hook return types                         │
│  - NO custom interfaces that don't trace back to Pydantic       │
└─────────────────────────────────────────────────────────────────┘
```

---

## HARD RULES

### Rule 1: Pydantic First
**Before adding ANY feature:**
1. Add the field to `tribrid_config_model.py` with proper Field() constraints
2. Run `uv run scripts/generate_types.py` to regenerate TypeScript
3. THEN implement the feature

**WRONG:** Add a slider to the UI, then figure out where to store the value
**RIGHT:** Add to Pydantic → generate types → add to store → add to hook → add to component

### Rule 2: No Hand-Written API Types
All TypeScript interfaces for API data MUST come from `generated.ts`.

```typescript
// WRONG - hand-written interface
interface SearchResponse {
  results: ChunkMatch[];
  latency: number;
}

// RIGHT - imported from generated
import { SearchResponse } from '../types/generated';
```

### Rule 3: No Adapters/Transformers
If the backend returns shape A and the frontend expects shape B:
- **WRONG:** Write an adapter function to convert A → B
- **RIGHT:** Change the Pydantic model to return shape B

Adapters are technical debt. Fix the source.

### Rule 4: Config Controls Everything
Every behavior that could vary must be controlled by config:
- Thresholds → `tribrid_config_model.py`
- Feature flags → `tribrid_config_model.py`  
- Model selection → `data/models.json`
- Tooltips → `data/glossary.json`

**WRONG:** Hardcode `if score > 0.5`
**RIGHT:** `if score > config.retrieval.confidence_threshold`

### Rule 5: Field Constraints Are Law
Pydantic Field() constraints define valid ranges:

```python
rrf_k: int = Field(default=60, ge=1, le=200, description="RRF smoothing")
```

- The UI slider MUST have min=1, max=200
- The API MUST reject values outside [1, 200]
- The default MUST be 60

Don't override these in the frontend. The Pydantic model IS the spec.

---

## BANNED PATTERNS

### Imports That Will Break The Build
```python
# BANNED - we don't use these
from qdrant_client import ...     # Use pgvector
import qdrant_client             # Use pgvector
from redis import ...            # Removed
import redis                     # Removed
from langchain import ...        # Banned (use langgraph directly if needed)
import langchain                 # Banned (use langgraph directly if needed)
```

**Note:** LangGraph IS allowed - it's needed for graph RAG orchestration. But use it directly, not through LangChain wrappers.

### Terms That Don't Exist
| WRONG | RIGHT |
|-------|-------|
| card, cards | chunk_summary, chunk_summaries |
| golden questions | eval_dataset |
| ranker | reranker |
| profile, profiles | (removed - no profiles) |
| onboarding | (removed - no onboarding) |

### Architecture Smells
- `class *Adapter` → Fix the Pydantic model instead
- `class *Transformer` → Fix the Pydantic model instead  
- `class *Mapper` → Fix the Pydantic model instead
- `function transform*` → Fix the Pydantic model instead
- `interface` in .tsx files → Import from generated.ts

---

## FILE CREATION RULES

### Before Creating Any File:
1. Is it in `TRIBRID_STRUCTURE.md`? If NO → **DON'T CREATE IT**
2. Does it need Pydantic types? → Add to config model FIRST
3. Is it a new component? → What hook does it use? → What store? → What Pydantic model?

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
│   └── tribrid_config_model.py  # ~500 fields
├── api/                 # FastAPI routers - return Pydantic models
├── db/                  # Database clients (Postgres, Neo4j)
├── retrieval/           # Search pipeline
├── indexing/            # Chunking, embedding, graph building
└── services/            # Business logic

web/src/
├── types/
│   └── generated.ts     # AUTO-GENERATED from Pydantic - DO NOT EDIT
├── stores/              # Zustand stores - use types from generated.ts
├── hooks/               # React hooks - wrap stores
├── components/          # React components - use hooks
└── api/                 # API client - typed with generated.ts

data/
├── models.json          # LLM model definitions
└── glossary.json        # Tooltip definitions
```

---

## COMMANDS

### Regenerate TypeScript Types
```bash
uv run scripts/generate_types.py
```
Run this after ANY change to Pydantic models.

### Validate Type Sync
```bash
uv run scripts/validate_types.py
```
Fails if generated.ts doesn't match Pydantic models.

### Check For Banned Patterns
```bash
uv run scripts/check_banned.py
```
Fails if code contains banned imports or terms.

---

## RALPH LOOP (HOW TO RUN IT CORRECTLY)

**Do NOT rely on “completion promises” alone.** The model can always output `<promise>COMPLETE</promise>` early.  
This repo prevents fake completion with a **verification-based Stop hook** that blocks stopping until checks pass.

### What Actually Enforces Completion

- **Stop hook**: `.claude/hooks/verify-tribrid.sh`
  - Blocks stopping if required files are missing, validators fail, or tests fail
- **Ralph loop**: the `ralph-loop` plugin keeps re-feeding the *same prompt* each iteration

### Preconditions (required)

- **Start Claude Code from repo root**:
  - `cd /Users/davidmontgomery/tribrid-rag`
- **Restart Claude Code after changing `.claude/settings.json`**
  - Hooks are snapshotted at startup (changes won’t apply mid-session)
- **Project config must include both**:
  - `enabledPlugins.ralph-loop@claude-plugins-official = true`
  - `hooks.Stop` running `"$CLAUDE_PROJECT_DIR"/.claude/hooks/verify-tribrid.sh`

### Start a Ralph Loop (recommended pattern)

In Claude Code, run:

```bash
/ralph-loop "Continue implementing TriBridRAG.

At the start of EACH iteration:
1) Read TODO.md and pick the first unchecked [ ] item.
2) Implement it end-to-end.
3) Run verification:
   - uv run scripts/check_banned.py
   - uv run scripts/validate_types.py
   - uv run pytest -q
4) Mark the item [x] in TODO.md only when it’s truly done.

IMPORTANT:
- If the Stop hook blocks stopping with a failure reason, fix that exact failure and keep going.
- ONLY when everything is complete and verification passes, output: <promise>COMPLETE</promise>" --max-iterations 200 --completion-promise "COMPLETE"
```

### Monitor / Cancel

- **Monitor iteration**: `grep '^iteration:' .claude/ralph-loop.local.md`
- **Cancel loop**: `/cancel-ralph`

---

## WHAT TO COPY FROM agro-rag-engine

### YES - Copy These
- CSS files from `web/src/styles/` (visual styling)
- Component LAYOUTS (but rewrite to use new hooks/stores)
- Tooltip CONTENT (but put in glossary.json, not JS module)

### NO - Don't Copy These
- Any adapter/transformer code
- Legacy JS modules from `web/src/modules/`
- The architecture (it's slop)
- Anything with Qdrant, Redis, LangGraph

### TRANSLATE - Convert These
| agro-rag-engine | tribrid-rag |
|-----------------|-------------|
| `agro_config_model.py` | `tribrid_config_model.py` (strip banned, add Neo4j) |
| `modules/tooltips.js` | `data/glossary.json` |
| `models.json` | `data/models.json` (same format) |

---

## MANDATORY TESTING RULE

**YOU CANNOT RETURN A RESPONSE TO THE USER IF YOUR CHANGE HAS NOT BEEN TESTED. All temporary feature tests and results go in .tests/ ; all reusable permanent tests go in the non-gitignored tests/**

This is not optional. This is not "if you have time." Every change must be verified before you say "done."

### GUI Changes → Playwright Tests
Not just "screen isn't black." Real interaction tests:
```typescript
// WRONG - useless test
test('page loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).not.toBeEmpty();
});

// RIGHT - real interaction test
test('fusion weight slider updates config', async ({ page }) => {
  await page.goto('/rag');
  await page.getByTestId('fusion-weights-panel').scrollIntoViewIfNeeded();
  const slider = page.getByTestId('vector-weight-slider');
  await slider.fill('0.6');
  await page.getByTestId('save-config').click();
  await expect(page.getByTestId('config-saved-toast')).toBeVisible();
  // Verify it actually saved
  await page.reload();
  await expect(slider).toHaveValue('0.6');
});
```

### API/Search Changes → Real Results
Show actual output, not "it returned 200":
```python
# WRONG - useless test
def test_search():
    response = client.post("/search", json={"query": "test"})
    assert response.status_code == 200

# RIGHT - verify real results
def test_search_returns_relevant_chunks():
    response = client.post("/api/search", json={
        "query": "authentication flow",
        "repo_id": "my-corpus"
    })
    assert response.status_code == 200
    results = response.json()["matches"]
    assert len(results) >= 3
    # Verify relevance - at least one result mentions auth
    assert any("auth" in r["content"].lower() for r in results)
```

### What "Tested" Means
| Change Type | Required Test |
|-------------|---------------|
| New component | Playwright: render, interact, verify state |
| Component edit | Playwright: existing tests still pass + new behavior |
| API endpoint | pytest: real request, real response, real data |
| Config field | pytest: validation works, default applies |
| Retrieval logic | pytest: search returns relevant results |
| Bug fix | Test that reproduces the bug, then passes after fix |

### No Exceptions
- "It's a small change" → Still test it
- "I'm confident it works" → Prove it
- "Tests are slow" → Run them anyway
- "It's just CSS" → Playwright screenshot comparison

---

## WHEN IN DOUBT

1. **Can I add this field?** → Is it in tribrid_config_model.py? No → Add it there first.
2. **Can I create this file?** → Is it in TRIBRID_STRUCTURE.md? No → Ask.
3. **Can I use this type?** → Is it in generated.ts? No → Add to Pydantic first.
4. **Can I hardcode this value?** → Should it be configurable? Yes → Add to config.
5. **Can I write an adapter?** → No. Fix the Pydantic model.
