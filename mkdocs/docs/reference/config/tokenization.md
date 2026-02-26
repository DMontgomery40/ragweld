# Config reference: `tokenization`

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

**Total parameters**: 7

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `tokenization.estimate_only` | — | `bool` | `false` | — | If true, use fast approximate token counting. |
| `tokenization.hf_tokenizer_name` | — | `str` | `"gpt2"` | — | HuggingFace tokenizer name (strategy='huggingface'). |
| `tokenization.lowercase` | — | `bool` | `false` | — | Lowercase before tokenization. |
| `tokenization.max_tokens_per_chunk_hard` | — | `int` | `8192` | ≥ 256, ≤ 65536 | Absolute hard limit for tokens per chunk (safety ceiling). |
| `tokenization.normalize_unicode` | — | `bool` | `true` | — | Normalize unicode (NFKC) before tokenization for stability. |
| `tokenization.strategy` | — | `Literal["whitespace", "tiktoken", "huggingface"]` | `"tiktoken"` | allowed="whitespace", "tiktoken", "huggingface" | Tokenization strategy used for chunking/budgeting. |
| `tokenization.tiktoken_encoding` | — | `str` | `"o200k_base"` | — | tiktoken encoding name (strategy='tiktoken'). |
