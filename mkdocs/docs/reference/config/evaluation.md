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

    BASELINE_PATH is where evaluation baselines are stored so retrieval and generation changes can be compared to a stable reference over time. A strong baseline captures both quality metrics and operational behavior, including ranking quality, grounding rate, latency, and abstention behavior. Store immutable run identifiers with dataset version and config hash so regressions can be traced to exact parameter changes. Without baseline discipline, tuning often produces short-term wins on narrow queries while silently degrading difficult slices that matter in production.

    **Badges**:
    - Evaluation

    **Links**:
    - [GaRAGe: Grounded RAG Evaluation Benchmark (arXiv)](https://arxiv.org/abs/2506.07671)
    - [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation)
    - [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/)
    - [Weights and Biases Experiment Tracking](https://docs.wandb.ai/guides/track/)
