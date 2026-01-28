# Claude Code Setup for tribrid-rag

## How It All Fits Together

```
TRIBRID_STRUCTURE.md   →  Complete file tree (~280 files)
TRIBRID_CONTRACTS.md   →  All classes, functions, interfaces
CLAUDE.md              →  Rules for Claude Code (auto-read)
ralph-wiggum plugin    →  Makes Claude loop until task is done
```

---

## Step 1: Create Project & Install Plugin

```bash
mkdir -p /Users/davidmontgomery/tribrid-rag
cd /Users/davidmontgomery/tribrid-rag
claude
```

Then in Claude Code:
```
/plugin install ralph-wiggum@claude-plugins-official
```

---

## Step 2: Add Spec Files to Project Root

Copy these files to `/Users/davidmontgomery/tribrid-rag/`:
- `TRIBRID_STRUCTURE.md`
- `TRIBRID_CONTRACTS.md`

---

## Step 3: Create CLAUDE.md

Claude Code automatically reads `CLAUDE.md`. Create it in project root:

```markdown
# tribrid-rag - Claude Code Instructions

## What You're Building
tribrid-rag: A tri-brid RAG engine combining vector (pgvector) + sparse (Postgres FTS) + graph (Neo4j) search.

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
```
Pydantic Model (server/models/*.py)
       ↓ auto-generated via pydantic2ts
TypeScript Interface (web/src/types/generated.ts)  
       ↓
Zustand Store (web/src/stores/*.ts)
       ↓
React Hook (web/src/hooks/*.ts)
       ↓
React Component (web/src/components/**/*.tsx)
```

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
```

---

## Step 4: Run Ralph Loop for Implementation

The ralph-wiggum plugin makes Claude work iteratively until the task is done:

```
/ralph-wiggum:ralph-loop "Build tribrid-rag following these instructions:

1. Read TRIBRID_STRUCTURE.md and TRIBRID_CONTRACTS.md completely
2. Create files in the order specified in TRIBRID_CONTRACTS.md
3. Every file must match the contracts exactly
4. Copy CSS and visual patterns from ../agro-rag-engine
5. Do NOT create files not listed in TRIBRID_STRUCTURE.md

Start with server/models/*.py, then proceed through the file creation order.

When ALL files in TRIBRID_STRUCTURE.md are created and match TRIBRID_CONTRACTS.md:
Output <promise>COMPLETE</promise>" --max-iterations 100 --completion-promise "COMPLETE"
```

### What Ralph Does:
1. Claude works on the task
2. Claude tries to exit
3. Stop hook intercepts and blocks
4. Same prompt fed back to Claude
5. Claude sees its previous work and continues
6. Repeats until `<promise>COMPLETE</promise>` is output or max iterations hit

---

## Step 5: Breaking It Into Phases (Recommended)

Instead of one giant loop, do phases:

### Phase 1: Backend Models
```
/ralph-wiggum:ralph-loop "Create all Pydantic models in server/models/*.py exactly as specified in TRIBRID_CONTRACTS.md. Create the __init__.py files. When all 10 model files exist and match contracts, output <promise>MODELS_DONE</promise>" --max-iterations 20 --completion-promise "MODELS_DONE"
```

### Phase 2: Database Clients
```
/ralph-wiggum:ralph-loop "Create server/db/postgres.py and server/db/neo4j.py exactly as specified in TRIBRID_CONTRACTS.md. When both files exist with all methods, output <promise>DB_DONE</promise>" --max-iterations 15 --completion-promise "DB_DONE"
```

### Phase 3: Retrieval Pipeline
```
/ralph-wiggum:ralph-loop "Create all files in server/retrieval/*.py exactly as specified in TRIBRID_CONTRACTS.md. When all 7 files exist and match contracts, output <promise>RETRIEVAL_DONE</promise>" --max-iterations 20 --completion-promise "RETRIEVAL_DONE"
```

### Phase 4: Indexing Pipeline
```
/ralph-wiggum:ralph-loop "Create all files in server/indexing/*.py exactly as specified in TRIBRID_CONTRACTS.md. When all 5 files exist and match contracts, output <promise>INDEXING_DONE</promise>" --max-iterations 15 --completion-promise "INDEXING_DONE"
```

### Phase 5: API Routers
```
/ralph-wiggum:ralph-loop "Create all files in server/api/*.py exactly as specified in TRIBRID_CONTRACTS.md. Then create server/main.py. When all 13 files exist and match contracts, output <promise>API_DONE</promise>" --max-iterations 25 --completion-promise "API_DONE"
```

### Phase 6: Generate TypeScript Types
```
/ralph-wiggum:ralph-loop "Run pydantic2ts to generate web/src/types/generated.ts from server/models. Verify the types match. Output <promise>TYPES_DONE</promise>" --max-iterations 5 --completion-promise "TYPES_DONE"
```

### Phase 7: Frontend Stores & Hooks
```
/ralph-wiggum:ralph-loop "Create all Zustand stores in web/src/stores/*.ts and all hooks in web/src/hooks/*.ts exactly as specified in TRIBRID_CONTRACTS.md. When all 6 stores and 14 hooks exist, output <promise>STATE_DONE</promise>" --max-iterations 25 --completion-promise "STATE_DONE"
```

### Phase 8: UI Components
```
/ralph-wiggum:ralph-loop "Create all React components in web/src/components/**/*.tsx. Follow TRIBRID_STRUCTURE.md for file paths and TRIBRID_CONTRACTS.md for props. Copy CSS and visual patterns from ../agro-rag-engine/web/src/. When all ~89 component files exist, output <promise>UI_DONE</promise>" --max-iterations 50 --completion-promise "UI_DONE"
```

### Phase 9: Final Assembly
```
/ralph-wiggum:ralph-loop "Create web/src/App.tsx, web/src/main.tsx, and all remaining files. Copy all CSS files from ../agro-rag-engine/web/src/styles/. Verify the complete file tree matches TRIBRID_STRUCTURE.md. When everything is complete, output <promise>COMPLETE</promise>" --max-iterations 20 --completion-promise "COMPLETE"
```

---

## Tips for Success

### Always Set Max Iterations
```
# GOOD - has a limit
/ralph-wiggum:ralph-loop "task" --max-iterations 25

# BAD - will loop forever
/ralph-wiggum:ralph-loop "task"
```

### Include Stuck Instructions
In your prompt, add:
```
If blocked after 10 iterations:
- Document what's blocking progress
- List what was attempted
- Output <promise>BLOCKED</promise> with explanation
```

### Cancel a Running Loop
```
/ralph-wiggum:cancel-ralph
```

### Check Progress
Claude sees the filesystem each iteration. Use TODO files:
```
Create a TODO.md with checkboxes:
- [ ] server/models/config.py
- [ ] server/models/retrieval.py
...
Check off each file as you complete it.
```

---

## Troubleshooting

### "Bash command permission check failed"
Add to `.claude/settings.json`:
```json
{
  "permissions": {
    "allow": [
      "Bash(**/ralph-wiggum/**)"
    ]
  }
}
```

### Claude Creates Files Not in TRIBRID_STRUCTURE.md
The CLAUDE.md rules should prevent this. If it happens:
1. Stop the loop: `/ralph-wiggum:cancel-ralph`
2. Delete the extra files
3. Add to your prompt: "BEFORE creating any file, verify it exists in TRIBRID_STRUCTURE.md"

### Claude Ignores Contracts
Add to your prompt: "After creating each file, verify every class/function signature matches TRIBRID_CONTRACTS.md exactly"

### Loop Exits Too Early
Make sure your completion promise is exact. Ralph uses exact string matching:
- `<promise>DONE</promise>` ✅
- `<promise>DONE!</promise>` ❌ (won't match "DONE")

---

## Quick Reference

| Command | What it does |
|---------|--------------|
| `/plugin install ralph-wiggum@claude-plugins-official` | Install the plugin |
| `/ralph-wiggum:ralph-loop "prompt" --max-iterations N` | Start a loop |
| `/ralph-wiggum:cancel-ralph` | Stop a running loop |
| `/help` | See all commands |
