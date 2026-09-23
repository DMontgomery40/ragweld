# Config reference: `synthetic`

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

**Total parameters**: 11

??? info "Group index"
    - `generator`
    - `judge`
    - `quality_gate`

## `generator`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `synthetic.generator.concurrency` | — | `int` | `4` | ≥ 1, ≤ 16 | Concurrent generator requests sent to the LiteLLM gateway per synthetic run. Forced to 1 when the selected alias is the single-stream local vLLM serving row. |
| `synthetic.generator.evidence_quote_max_chars` | — | `int` | `200` | ≥ 50, ≤ 1000 | Max characters for evidence quote field |
| `synthetic.generator.expected_answer_max_chars` | — | `int` | `400` | ≥ 50, ≤ 2000 | Max characters for expected answer field |
| `synthetic.generator.max_tokens` | — | `int` | `1200` | ≥ 100, ≤ 16000 | Max tokens for generator LLM response |
| `synthetic.generator.question_max_chars` | — | `int` | `180` | ≥ 50, ≤ 500 | Max characters for generated question text |
| `synthetic.generator.source_excerpt_max_lines` | — | `int` | `80` | ≥ 10, ≤ 500 | Max lines of source chunk content sent as context to the generator |
| `synthetic.generator.temperature` | — | `float` | `0.0` | ≥ 0.0, ≤ 2.0 | Temperature for synthetic generator LLM calls |

## `judge`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `synthetic.judge.answer_supported_min` | — | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Minimum probability that the located evidence quote, not the file name or path, supports the expected answer to the question |
| `synthetic.judge.reader_question_min` | — | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | Minimum probability that a real reader would ask the question about the document's subject (not cover, title-page, report-number or filename trivia, and understandable without the source) |

## `quality_gate`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `synthetic.quality_gate.sample_size` | — | `int` | `50` | ≥ 1, ≤ 10000 | Number of eval items to sample for quality gate evaluation |
| `synthetic.quality_gate.top1_min` | — | `float` | `0.4` | ≥ 0.0, ≤ 1.0 | Minimum top-1 retrieval accuracy to pass quality gate |
