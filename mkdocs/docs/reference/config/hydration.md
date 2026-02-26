# Config reference: `hydration`

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

**Total parameters**: 2

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `hydration.hydration_max_chars` | `HYDRATION_MAX_CHARS` | `int` | `2000` | ≥ 500, ≤ 10000 | Max characters to hydrate |
| `hydration.hydration_mode` | `HYDRATION_MODE` | `str` | `"lazy"` | pattern=^(lazy\|eager\|none\|off)$ | Context hydration mode |

### Details (glossary)

??? info "`hydration.hydration_max_chars` (`HYDRATION_MAX_CHARS`) — Hydration Max Chars"
    **Category**: `general`

    Maximum characters to load per chunk when hydrating results with code content. Prevents huge chunks from bloating responses and consuming excessive memory. 0 = no limit (may cause memory issues with large files). Recommended: 2000 for general use, 1000 for memory-constrained environments, 5000 for detailed code review. Chunks larger than this limit are truncated.

    **Badges**:
    - Performance

    **Links**:
    - [Text Truncation](https://en.wikipedia.org/wiki/Truncation)

??? info "`hydration.hydration_mode` (`HYDRATION_MODE`) — Hydration Mode"
    **Category**: `general`

    Controls when full code is loaded from chunks.jsonl. "Lazy" (recommended) loads code after retrieval, providing full context with minimal memory overhead. "None" returns only metadata (file path, line numbers) - fastest but no code content. Use "none" for testing retrieval quality or when you only need file locations, not actual code.

    **Badges**:
    - Lazy Recommended

    **Links**:
    - [Lazy Loading](https://en.wikipedia.org/wiki/Lazy_loading)
