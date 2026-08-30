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

### Details (glossary)

??? info "`semantic_cache.bypass_if_images` (`SEMANTIC_CACHE_BYPASS_IF_IMAGES`) — Semantic Cache Bypass If Images"
    **Category**: `retrieval`

    Skips the cache entirely for requests that carry images. The cache key is built from text embeddings, so two requests with identical text and different attachments are indistinguishable to it. Leave this on unless the cache key is extended to cover attachments.

??? info "`semantic_cache.chat_history_window` (`SEMANTIC_CACHE_CHAT_HISTORY_WINDOW`) — Semantic Cache Chat History Window"
    **Category**: `retrieval`

    How many preceding messages are folded into the cache key for a chat turn. Zero keys on the latest message alone, which over-matches across unrelated threads. A larger window makes the key more specific and the hit rate lower; it is the direct trade between reuse and answering the right question.

??? info "`semantic_cache.enabled` (`SEMANTIC_CACHE_ENABLED`) — Semantic Cache Enabled"
    **Category**: `retrieval`

    Turns the semantic answer cache on. Unlike a key-value cache it matches on embedding similarity, so a paraphrase of an earlier question can be served from the earlier answer without touching retrieval or the generation model. That is where the saving comes from and also where the risk lives: a near-miss match returns an answer grounded in a slightly different question. Leave it off while a corpus is being re-indexed, because entries written against the previous generation stay valid-looking until they expire.

??? info "`semantic_cache.max_entries` (`SEMANTIC_CACHE_MAX_ENTRIES`) — Semantic Cache Max Entries"
    **Category**: `retrieval`

    Upper bound on cached entries before the oldest are evicted. Each entry holds a query embedding plus the stored response, so this is the main lever on the cache's memory footprint. Sizing it far above the number of distinct questions your operators actually ask buys nothing; sizing it below that thrashes and the hit rate collapses without any error to show for it.

??? info "`semantic_cache.max_temperature_for_write` (`SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE`) — Semantic Cache Max Temperature for Write"
    **Category**: `retrieval`

    Answers generated above this sampling temperature are never written to the cache. A high-temperature response is one sample out of many plausible ones, so caching it turns a deliberate choice to vary into a single frozen answer served to everyone. Deterministic and near-deterministic generations are the only ones worth reusing.

??? info "`semantic_cache.min_query_chars` (`SEMANTIC_CACHE_MIN_QUERY_CHARS`) — Semantic Cache Min Query Chars"
    **Category**: `retrieval`

    Queries shorter than this are neither served from nor written to the cache. Very short strings embed poorly and sit close to each other in vector space, so a two-character query can match almost anything above the similarity threshold. This is the guard against that class of false hit; raise it if you see unrelated answers returned for terse queries.

??? info "`semantic_cache.mode` (`SEMANTIC_CACHE_MODE`) — Semantic Cache Mode"
    **Category**: `retrieval`

    Which half of the cache is active. read_write is the normal steady state. read_only serves existing entries but writes none, which is what you want while validating a config change: the cache stops absorbing answers produced under settings you are still testing. write_only fills the cache without serving from it, useful for warming after an index rebuild before you trust reads.
