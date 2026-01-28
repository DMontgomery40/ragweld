# TriBridRAG - Claude Code Instructions

## What You're Building
TriBridRAG: A tri-brid RAG engine combining vector (pgvector) + sparse (Postgres FTS) + graph (Neo4j) search.

## REQUIRED READING BEFORE ANY WORK
1. `TRIBRID_STRUCTURE.md` - The complete file tree (~280 files)
2. `TRIBRID_CONTRACTS.md` - Every class, function, interface definition

## HARD RULES

### Rule 1: Only Create Files Listed in TRIBRID_STRUCTURE.md
Before creating ANY file:
1. Check if it exists in TRIBRID_STRUCTURE.md
2. If not listed → DO NOT CREATE IT
3. If you think something is missing → ASK, don't create

### Rule 2: Match Contracts Exactly
Every class, function, interface must match TRIBRID_CONTRACTS.md exactly:
- Pydantic models → match field names and types
- API endpoints → match routes and response models
- React components → match prop interfaces
- Zustand stores → match state and action signatures

### Rule 3: No Adapters/Transformers/Mappers
If backend returns shape A and frontend expects shape B:
- WRONG: Write adapter code to transform A → B
- RIGHT: Change the Pydantic model to return shape B

### Rule 4: Contract Chain (Data Flows One Direction)
Pydantic Model (server/models/.py)
↓ auto-generated via pydantic2ts
TypeScript Interface (web/src/types/generated.ts)
↓
Zustand Store (web/src/stores/.ts)
↓
React Hook (web/src/hooks/.ts)
↓
React Component (web/src/components/**/.tsx)

### Rule 5: File Creation Order
Follow TRIBRID_CONTRACTS.md order:
1. server/models/*.py (Pydantic models)
2. Run: `pydantic2ts --module server/models --output web/src/types/generated.ts`
3. server/db/*.py
4. server/retrieval/*.py
5. server/indexing/*.py
6. server/api/*.py
7. server/main.py
8. web/src/stores/*.ts
9. web/src/hooks/*.ts
10. web/src/api/*.ts
11. web/src/components/**/*.tsx

## Reference Codebase
`../agro-rag-engine` contains the old version:
- READ from it for UI patterns, CSS, tooltip content
- NEVER write to it
- DO NOT copy its architecture (it's slop)
- DO copy: CSS files, visual component layouts, tooltip text

## What to Copy from agro-rag-engine
- `web/src/styles/*.css` - All CSS files
- Visual layouts from Dashboard, Evaluation, Grafana components
- The 247 tooltips (content only, not implementation)
- UI primitives (Button, ProgressBar, etc.) - update props to match CONTRACTS

## What NOT to Copy
- Adapter/transformer code
- Legacy JS modules (`modules/*.js`)
- Duplicate components (5 Docker tabs exist - we need 1)
- Anything with "cards" in the name (renamed to chunk_summaries)
- Anything with "golden" in the name (renamed to dataset)
- Onboarding wizard
- Profiles system
- VSCode embed