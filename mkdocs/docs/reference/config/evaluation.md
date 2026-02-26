# Config reference: `evaluation`

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
| `evaluation.baseline_path` | `BASELINE_PATH` | `str` | `"data/evals/eval_baseline.json"` | — | Baseline results path |
| `evaluation.eval_dataset_path` | `EVAL_DATASET_PATH` | `str` | `"data/evaluation_dataset.json"` | — | Evaluation dataset path |
| `evaluation.eval_multi_m` | `EVAL_MULTI_M` | `int` | `10` | ≥ 1, ≤ 20 | Multi-query variants for evaluation |
| `evaluation.ndcg_at_10_k` | — | `int` | `10` | ≥ 1, ≤ 200 | K used for ndcg_at_10 metric (default 10). |
| `evaluation.precision_at_5_k` | — | `int` | `5` | ≥ 1, ≤ 200 | K used for precision_at_5 metric (default 5). |
| `evaluation.recall_at_10_k` | — | `int` | `10` | ≥ 1, ≤ 200 | K used for recall_at_10 metric (default 10). |
| `evaluation.recall_at_20_k` | — | `int` | `20` | ≥ 1, ≤ 200 | K used for recall_at_20 metric (default 20). |
| `evaluation.recall_at_5_k` | — | `int` | `5` | ≥ 1, ≤ 200 | K used for recall_at_5 metric (default 5). |

### Details (glossary)

??? info "`evaluation.baseline_path` (`BASELINE_PATH`) — Baseline Path"
    **Category**: `general`

    Directory where evaluation loop saves baseline results for regression testing and A/B comparison. Each eval run's metrics (Hit@K, MRR, latency) are stored here with timestamps. Use this to ensure retrieval quality doesn't regress after configuration changes, reindexing, or model upgrades. Compare current run against baseline to detect improvements or degradations.

    **Links**:
    - [Regression Prevention](https://en.wikipedia.org/wiki/Software_regression)
