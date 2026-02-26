You are writing documentation for **TriBridRAG**, a tri-brid RAG platform combining:

- **Vector search** (pgvector in PostgreSQL)
- **Sparse search** (PostgreSQL FTS / BM25-style scoring)
- **Graph search** (Neo4j traversal for entities/relationships/communities)

MkDocs theme: **Material for MkDocs** (v9.x).

## Writing style (the *goal*)

- Write like a helpful builder/operator, not like a dry spec sheet.
- Make the docs usable by:
  1. **End users** (how to use the product; what knobs mean)
  2. **Operators** (how to run it; what breaks; where to look)
  3. **Engineers** (how it’s built; how config flows; where code lives)
- Default to “**tooltip-level clarity**” for UI controls and config fields:
  - what it does
  - why it matters
  - tradeoffs / failure modes
  - safe defaults
  - “if you’re not sure, do X”
- Avoid intimidation: explain concepts before details; use visual breaks.
- No marketing language.

## Non-negotiable project truths

- **Pydantic is the law**: config and types flow from `server/models/tribrid_config_model.py`.
- Corpus separation is fundamental (code uses `repo_id` to mean corpus id).
- Retrieval = vector + sparse + graph (fused), optionally reranked.

## Product URLs + API prefix (critical for accuracy)

- In dev, the backend is mounted under **`/api`** (FastAPI routers are included with `prefix="/api"`).
  - Correct examples: `http://127.0.0.1:8012/api/search`, `fetch("/api/config")`
  - Incorrect examples: `/search`, `/config`, `http://localhost:8000/search`
- Default dev entrypoints (unless overridden by env vars):
  - **UI**: `http://127.0.0.1:5173/web`
  - **API**: `http://127.0.0.1:8012/api`

## MkDocs Material formatting (mandatory)

Plain markdown without Material features is unacceptable. Use these heavily:

### Start every page with a feature grid

```html
<div class="grid chunk_summaries" markdown>
...
</div>
```

### Include a “Quick links” block near the top

Use Material buttons (adjust relative paths correctly for nested pages):

```md
[Get started](index.md){ .md-button .md-button--primary }
[Configuration](configuration.md){ .md-button }
[API](api.md){ .md-button }
```

### Use Material features everywhere

- Admonitions: `!!! note`, `!!! tip`, `!!! warning`, `!!! danger`, and `???` collapsibles
- Tabs for code and multi-approach content (`=== "Python"`, `=== "curl"`, `=== "TypeScript"`)
- Code annotations for complex snippets (use `(1)!` markers + numbered explanations)
- Tables for configuration/comparisons
- Definition lists for “what does this setting mean?”
- Task lists for checklists and step-by-step flows

## Mermaid v11 (avoid syntax errors)

- No HTML in Mermaid.
- Prefer simple node IDs (A, B, C…) and put human text in labels.
- Quote labels containing spaces/punctuation/newlines:
  - Good: `A["Vector Search\\n(pgvector)"]`
  - Bad: `A[Vector Search (pgvector)]`

## Linking rules (mkdocs build --strict must pass)

- You may **create, move, or delete** pages and restructure folders as needed.
- After your changes, **every** relative link must resolve and `mkdocs build --strict` must pass.
- Do not create relative links to repository source files; reference code paths as inline code (`` `path/to/file.py` ``) or use absolute GitHub URLs when a clickable link is required.

## Navigation + audience (do not regress)

- The docs MUST include a real, human-first **User Manual** (task-focused, step-by-step, practical).
- Do not publish internal planning artifacts as product docs (no exec plans/runbooks; no `repo/` knowledge base mirroring).
- Prefer narrative explanations and “how to” flows over terse bullet lists; use bullets as checklists, not as the whole page.
