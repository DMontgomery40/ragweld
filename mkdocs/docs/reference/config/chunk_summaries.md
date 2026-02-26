# Config reference: `chunk_summaries`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 8

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chunk_summaries.code_snippet_length` | `CHUNK_SUMMARIES_CODE_SNIPPET_LENGTH` | `int` | `2000` | ≥ 500, ≤ 10000 | Max code snippet length in semantic chunk_summaries |
| `chunk_summaries.exclude_dirs` | — | `list[str]` | `["docs", "agent_docs", "website", "tests", "assets", "internal_docs.md", "out", "checkpoints", "models", "data", "telemetry", "node_mcp", "public", "examples", "bin", "reports", "screenshots", "web/dist", "gui"]` | — | Directories to skip when building chunk_summaries |
| `chunk_summaries.exclude_keywords` | — | `list[str]` | `[]` | — | Keywords that, when present in code, skip the chunk |
| `chunk_summaries.exclude_patterns` | — | `list[str]` | `[]` | — | File patterns/extensions to skip |
| `chunk_summaries.max_routes` | `CHUNK_SUMMARIES_MAX_ROUTES` | `int` | `5` | ≥ 1, ≤ 20 | Max API routes to include per chunk_summary |
| `chunk_summaries.max_symbols` | `CHUNK_SUMMARIES_MAX_SYMBOLS` | `int` | `5` | ≥ 1, ≤ 20 | Max symbols to include per chunk_summary |
| `chunk_summaries.purpose_max_length` | `CHUNK_SUMMARIES_PURPOSE_MAX_LENGTH` | `int` | `240` | ≥ 50, ≤ 500 | Max length for purpose field in chunk_summaries |
| `chunk_summaries.quick_tips` | — | `list[str]` | `[]` | — | Quick tips shown in chunk_summaries builder UI |
