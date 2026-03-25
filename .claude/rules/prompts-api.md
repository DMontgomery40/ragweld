---
paths:
  - "server/api/**/*.py"
---

# Prompts Management API

> Branch canon for `feat/oss-composition-kickoff`: no fallback or legacy prompt/config API paths. Replace touched surfaces completely.

System prompts are editable via API. All prompts defined in `SystemPromptsConfig`.

## Endpoints
- `GET /api/prompts` — List all prompts with metadata
- `PUT /api/prompts/{prompt_key}` — Update a prompt
- `POST /api/prompts/reset/{prompt_key}` — Reset to Pydantic default

## Categories
- `retrieval`: query_expansion, query_rewrite
- `indexing`: semantic_chunk_summaries, code_enrichment
- `evaluation`: eval_analysis

Note: Chat prompts (prefixed `chat.`) are read-only here — edit via Chat Settings.
