# Config reference: `semantic_cache`

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

**Total parameters**: 13

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `semantic_cache.bypass_if_images` | `SEMANTIC_CACHE_BYPASS_IF_IMAGES` | `bool` | `true` | — | Bypass chat generation cache when images are attached. |
| `semantic_cache.chat_history_window` | `SEMANTIC_CACHE_CHAT_HISTORY_WINDOW` | `int` | `6` | ≥ 0, ≤ 50 | Number of prior conversation turns included in chat cache fingerprint. |
| `semantic_cache.enabled` | `SEMANTIC_CACHE_ENABLED` | `bool` | `false` | — | Enable semantic cache reads/writes. |
| `semantic_cache.max_entries` | `SEMANTIC_CACHE_MAX_ENTRIES` | `int` | `5000` | ≥ 100, ≤ 500000 | Maximum cache rows to retain per scope/endpoint. |
| `semantic_cache.max_temperature_for_write` | `SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE` | `float` | `0.5` | ≥ 0.0, ≤ 2.0 | Skip generation-cache writes when temperature exceeds this value. |
| `semantic_cache.min_query_chars` | `SEMANTIC_CACHE_MIN_QUERY_CHARS` | `int` | `3` | ≥ 1, ≤ 200 | Minimum query length before cache is eligible. |
| `semantic_cache.mode` | `SEMANTIC_CACHE_MODE` | `Literal["read_write", "read_only", "write_only"]` | `"read_write"` | allowed="read_write", "read_only", "write_only" | Cache mode when enabled. |
| `semantic_cache.similarity_threshold_answer` | `SEMANTIC_CACHE_THRESHOLD_ANSWER` | `float` | `0.93` | ≥ 0.0, ≤ 1.0 | Minimum cosine similarity for semantic answer cache hits. |
| `semantic_cache.similarity_threshold_chat` | `SEMANTIC_CACHE_THRESHOLD_CHAT` | `float` | `0.95` | ≥ 0.0, ≤ 1.0 | Minimum cosine similarity for semantic chat cache hits. |
| `semantic_cache.similarity_threshold_search` | `SEMANTIC_CACHE_THRESHOLD_SEARCH` | `float` | `0.9` | ≥ 0.0, ≤ 1.0 | Minimum cosine similarity for semantic search cache hits. |
| `semantic_cache.ttl_seconds_answer` | `SEMANTIC_CACHE_TTL_ANSWER_SEC` | `int` | `1800` | ≥ 10, ≤ 86400 | TTL in seconds for answer cache entries. |
| `semantic_cache.ttl_seconds_chat` | `SEMANTIC_CACHE_TTL_CHAT_SEC` | `int` | `600` | ≥ 10, ≤ 86400 | TTL in seconds for chat cache entries. |
| `semantic_cache.ttl_seconds_search` | `SEMANTIC_CACHE_TTL_SEARCH_SEC` | `int` | `900` | ≥ 10, ≤ 86400 | TTL in seconds for search cache entries. |
