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

    HYDRATION_MAX_CHARS limits how much raw chunk text is loaded when turning retrieval hits into generation-ready context. This protects latency, memory, and prompt budgets from oversized chunks or unusually large files. A value that is too low can cut away critical lines and reduce answer grounding, while a value that is too high can bloat prompts and increase cost without better relevance. Tune this alongside chunk size, rerank depth, and model context window so each stage has a clear budget. Track truncation rate and citation failures to detect when the cap is suppressing necessary evidence.

    **Badges**:
    - Prompt Budget

    **Links**:
    - [LangChain Contextual Compression](https://python.langchain.com/docs/how_to/contextual_compression/)
    - [LangChain Text Splitters Concepts](https://python.langchain.com/docs/concepts/text_splitters/)
    - [OpenAI Cookbook: Count Tokens with tiktoken](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken)
    - [MoC (2025): Mixtures of Chunking Learners for RAG](https://arxiv.org/abs/2503.09600)

??? info "`hydration.hydration_mode` (`HYDRATION_MODE`) — Hydration Mode"
    **Category**: `general`

    HYDRATION_MODE controls when full chunk content is loaded into the retrieval pipeline. A lazy mode usually gives the best production balance because ranking can run on lightweight metadata first, and full text is fetched only for shortlisted results. A none mode is useful for retrieval diagnostics, fast metadata-only workflows, or systems where generation occurs in a separate step. Choosing the mode changes both latency profile and memory behavior, so it should be treated as an architectural runtime option rather than a cosmetic toggle. Align this setting with your reranker strategy and context assembly stage to avoid unnecessary data loading.

    **Badges**:
    - Runtime Loading

    **Links**:
    - [LangChain Contextual Compression](https://python.langchain.com/docs/how_to/contextual_compression/)
    - [LlamaIndex Node Parsers](https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/)
    - [OpenAI Cookbook: Count Tokens with tiktoken](https://cookbook.openai.com/examples/how_to_count_tokens_with_tiktoken)
    - [TeleRAG (2025): Lookahead Retrieval for Efficient Inference](https://arxiv.org/abs/2502.20969)
