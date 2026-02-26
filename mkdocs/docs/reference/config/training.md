# Config reference: `training`

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

**Total parameters**: 36

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `training.learning_reranker_backend` | `LEARNING_RERANKER_BACKEND` | `Literal["auto", "mlx_qwen3"]` | `"auto"` | allowed="auto", "mlx_qwen3" | Learning reranker backend: auto (prefer MLX Qwen3 on Apple Silicon), mlx_qwen3 (force). Legacy values 'transformers'/'hf' normalize to 'auto'. |
| `training.learning_reranker_base_model` | `LEARNING_RERANKER_BASE_MODEL` | `str` | `"Qwen/Qwen3-Reranker-0.6B"` | — | Base model to fine-tune for MLX Qwen3 learning reranker |
| `training.learning_reranker_grad_accum_steps` | `LEARNING_RERANKER_GRAD_ACCUM_STEPS` | `int` | `8` | ≥ 1, ≤ 128 | Gradient accumulation steps per optimizer update for MLX Qwen3 learning reranker training |
| `training.learning_reranker_lora_alpha` | `LEARNING_RERANKER_LORA_ALPHA` | `float` | `32.0` | > 0.0, ≤ 512.0 | LoRA alpha for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_dropout` | `LEARNING_RERANKER_LORA_DROPOUT` | `float` | `0.05` | ≥ 0.0, ≤ 0.5 | LoRA dropout for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_rank` | `LEARNING_RERANKER_LORA_RANK` | `int` | `16` | ≥ 1, ≤ 128 | LoRA rank for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_target_modules` | — | `list[str]` | `["q_proj", "k_proj", "v_proj", "o_proj"]` | min_length=1 | Module name suffixes to apply LoRA to (MLX Qwen3) |
| `training.learning_reranker_negative_ratio` | `LEARNING_RERANKER_NEGATIVE_RATIO` | `int` | `5` | ≥ 1, ≤ 20 | Negative pairs per positive during learning reranker training |
| `training.learning_reranker_promote_epsilon` | `LEARNING_RERANKER_PROMOTE_EPSILON` | `float` | `0.0` | ≥ 0.0, ≤ 1.0 | Minimum improvement required to auto-promote (primary metric delta) |
| `training.learning_reranker_promote_if_improves` | `LEARNING_RERANKER_PROMOTE_IF_IMPROVES` | `int` | `1` | ≥ 0, ≤ 1 | Promote trained learning artifact to active path only if primary metric improves |
| `training.learning_reranker_telemetry_interval_steps` | `LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS` | `int` | `2` | ≥ 1, ≤ 20 | Emit trainer telemetry every N optimizer steps (plus first/final) |
| `training.learning_reranker_unload_after_sec` | `LEARNING_RERANKER_UNLOAD_AFTER_SEC` | `int` | `0` | ≥ 0, ≤ 86400 | Unload MLX learning reranker model after idle seconds (0 = never) |
| `training.ragweld_agent_backend` | `RAGWELD_AGENT_BACKEND` | `str` | `"mlx_qwen3"` | — | Ragweld agent backend (in-process chat model). Currently: mlx_qwen3 |
| `training.ragweld_agent_base_model` | `RAGWELD_AGENT_BASE_MODEL` | `str` | `"mlx-community/Qwen3-1.7B-4bit"` | — | Shipped base model for the ragweld agent (MLX). |
| `training.ragweld_agent_grad_accum_steps` | `RAGWELD_AGENT_GRAD_ACCUM_STEPS` | `int` | `8` | ≥ 1, ≤ 128 | Gradient accumulation steps per optimizer update for ragweld agent training. |
| `training.ragweld_agent_lora_alpha` | `RAGWELD_AGENT_LORA_ALPHA` | `float` | `32.0` | > 0.0, ≤ 512.0 | LoRA alpha for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_dropout` | `RAGWELD_AGENT_LORA_DROPOUT` | `float` | `0.05` | ≥ 0.0, ≤ 0.5 | LoRA dropout for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_rank` | `RAGWELD_AGENT_LORA_RANK` | `int` | `16` | ≥ 1, ≤ 128 | LoRA rank for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_target_modules` | — | `list[str]` | `["q_proj", "k_proj", "v_proj", "o_proj"]` | min_length=1 | Module name suffixes to apply LoRA to (ragweld agent; MLX Qwen3). |
| `training.ragweld_agent_model_path` | `RAGWELD_AGENT_MODEL_PATH` | `str` | `"models/learning-agent-epstein-files-1"` | — | Active ragweld agent adapter artifact path (directory containing adapter.npz + adapter_config.json). |
| `training.ragweld_agent_promote_epsilon` | `RAGWELD_AGENT_PROMOTE_EPSILON` | `float` | `0.0` | ≥ 0.0, ≤ 10.0 | Minimum eval_loss improvement required to auto-promote (baseline_loss - new_loss >= epsilon). |
| `training.ragweld_agent_promote_if_improves` | `RAGWELD_AGENT_PROMOTE_IF_IMPROVES` | `int` | `1` | ≥ 0, ≤ 1 | Auto-promote trained ragweld agent adapter only if eval_loss improves. |
| `training.ragweld_agent_reload_period_sec` | `RAGWELD_AGENT_RELOAD_PERIOD_SEC` | `int` | `60` | ≥ 0, ≤ 600 | Adapter reload check period (seconds). 0 = check every request. |
| `training.ragweld_agent_telemetry_interval_steps` | `RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS` | `int` | `2` | ≥ 1, ≤ 20 | Emit ragweld agent trainer telemetry every N optimizer steps (plus first/final). |
| `training.ragweld_agent_train_dataset_path` | `RAGWELD_AGENT_TRAIN_DATASET_PATH` | `str` | `""` | — | Training dataset path for the ragweld agent (empty = use evaluation.eval_dataset_path). |
| `training.ragweld_agent_unload_after_sec` | `RAGWELD_AGENT_UNLOAD_AFTER_SEC` | `int` | `0` | ≥ 0, ≤ 86400 | Unload ragweld agent model after idle seconds (0 = never). |
| `training.reranker_train_batch` | `RERANKER_TRAIN_BATCH` | `int` | `16` | ≥ 1, ≤ 128 | Training batch size |
| `training.reranker_train_epochs` | `RERANKER_TRAIN_EPOCHS` | `int` | `2` | ≥ 1, ≤ 20 | Training epochs for reranker |
| `training.reranker_train_lr` | `RERANKER_TRAIN_LR` | `float` | `2e-05` | ≥ 1e-06, ≤ 0.001 | Learning rate |
| `training.reranker_warmup_ratio` | `RERANKER_WARMUP_RATIO` | `float` | `0.1` | ≥ 0.0, ≤ 0.5 | Warmup steps ratio |
| `training.tribrid_reranker_mine_mode` | `TRIBRID_RERANKER_MINE_MODE` | `str` | `"replace"` | pattern=^(replace\|append)$ | Triplet mining mode |
| `training.tribrid_reranker_mine_reset` | `TRIBRID_RERANKER_MINE_RESET` | `int` | `0` | ≥ 0, ≤ 1 | Reset triplets file before mining |
| `training.tribrid_reranker_model_path` | `TRIBRID_RERANKER_MODEL_PATH` | `str` | `"models/learning-reranker-epstein-files-1"` | — | Active learning reranker artifact path (MLX adapter directory). |
| `training.tribrid_triplets_path` | `TRIBRID_TRIPLETS_PATH` | `str` | `"data/training/triplets__epstein-files-1.jsonl"` | — | Training triplets file path |
| `training.triplets_min_count` | `TRIPLETS_MIN_COUNT` | `int` | `100` | ≥ 10, ≤ 10000 | Min triplets for training |
| `training.triplets_mine_mode` | `TRIPLETS_MINE_MODE` | `str` | `"replace"` | pattern=^(replace\|append)$ | Triplet mining mode |

### Details (glossary)

??? info "`training.learning_reranker_backend` (`LEARNING_RERANKER_BACKEND`) — Learning Reranker Backend"
    **Category**: `reranking`

    Backend used when RERANKER_MODE="learning". auto selects the MLX Qwen3 LoRA backend (Apple Silicon). mlx_qwen3 forces the same MLX backend. Legacy values (transformers/hf) are accepted for backward compatibility but normalize to auto.

    **Badges**:
    - Backend selector

??? info "`training.learning_reranker_base_model` (`LEARNING_RERANKER_BASE_MODEL`) — Learning Reranker Base Model"
    **Category**: `reranking`

    Base model identifier to fine-tune FROM when using the MLX Qwen3 learning backend (e.g. Qwen/Qwen3-Reranker-0.6B). Training produces a LoRA adapter artifact written under TRIBRID_RERANKER_MODEL_PATH and inference loads that adapter on top of this base. Changing the base model makes existing adapters incompatible.

    **Badges**:
    - MLX only

??? info "`training.learning_reranker_grad_accum_steps` (`LEARNING_RERANKER_GRAD_ACCUM_STEPS`) — Learning Reranker Grad Accum Steps"
    **Category**: `reranking`

    Number of micro-batches to accumulate gradients over before applying one optimizer update when training the MLX Qwen3 learning reranker. This increases effective batch size without increasing memory. Typical: 4–16; default 8.

    **Badges**:
    - MLX only
    - Affects training speed

??? info "`training.learning_reranker_lora_alpha` (`LEARNING_RERANKER_LORA_ALPHA`) — Learning Reranker LoRA Alpha"
    **Category**: `reranking`

    LoRA scaling (alpha) for MLX Qwen3 fine-tuning. Effective LoRA scale is alpha/rank. Typical: 16–64; start at 32.

    **Badges**:
    - MLX only

??? info "`training.learning_reranker_lora_dropout` (`LEARNING_RERANKER_LORA_DROPOUT`) — Learning Reranker LoRA Dropout"
    **Category**: `reranking`

    LoRA dropout probability for MLX Qwen3 fine-tuning. Small dropout (0.0–0.1) can reduce overfitting on small mined datasets. Start at 0.05.

    **Badges**:
    - MLX only

??? info "`training.learning_reranker_lora_rank` (`LEARNING_RERANKER_LORA_RANK`) — Learning Reranker LoRA Rank"
    **Category**: `reranking`

    LoRA rank (r) for MLX Qwen3 fine-tuning. Higher rank increases adapter capacity (and training/inference cost) and can improve quality with enough data. Typical: 8–32; start at 16.

    **Badges**:
    - MLX only
    - Affects training cost

??? info "`training.learning_reranker_negative_ratio` (`LEARNING_RERANKER_NEGATIVE_RATIO`) — Learning Reranker Negative Ratio"
    **Category**: `reranking`

    When converting mined triplets into labeled (query, document) pairs for pairwise training, use up to this many negatives per positive. Higher ratios can improve discrimination but increase training time. Typical: 3–5; default 5.

    **Badges**:
    - Quality vs cost

??? info "`training.learning_reranker_promote_epsilon` (`LEARNING_RERANKER_PROMOTE_EPSILON`) — Learning Reranker Promotion Epsilon"
    **Category**: `reranking`

    Minimum dev-metric improvement required to auto-promote a newly trained learning reranker artifact over the active baseline. Use a small epsilon (e.g., 0.002) to avoid promoting on noise.

    **Badges**:
    - Prevents noise promotions

??? info "`training.learning_reranker_promote_if_improves` (`LEARNING_RERANKER_PROMOTE_IF_IMPROVES`) — Learning Reranker Promotion Gate"
    **Category**: `reranking`

    If enabled (1), training only promotes the newly trained artifact to TRIBRID_RERANKER_MODEL_PATH if the primary dev metric improves over the active baseline by at least LEARNING_RERANKER_PROMOTE_EPSILON. If disabled (0), successful training always promotes.

    **Badges**:
    - Safety

??? info "`training.learning_reranker_telemetry_interval_steps` (`LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS`) — Learning Reranker Telemetry Interval Steps"
    **Category**: `reranking`

    Emit trainer telemetry every N optimizer steps (plus first and final events). Default: 2. Range: 1-20. Lower values give smoother live charts but increase event volume.

??? info "`training.learning_reranker_unload_after_sec` (`LEARNING_RERANKER_UNLOAD_AFTER_SEC`) — Learning Reranker Idle Unload"
    **Category**: `reranking`

    If >0, unload the MLX Qwen3 reranker model from memory after this many seconds of inactivity. Set to 0 to keep the model resident (faster first rerank, higher memory use).

    **Badges**:
    - MLX only
    - Affects latency

??? info "`training.ragweld_agent_backend` (`RAGWELD_AGENT_BACKEND`) — RAGWELD_AGENT_BACKEND"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_base_model` (`RAGWELD_AGENT_BASE_MODEL`) — RAGWELD_AGENT_BASE_MODEL"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_grad_accum_steps` (`RAGWELD_AGENT_GRAD_ACCUM_STEPS`) — RAGWELD_AGENT_GRAD_ACCUM_STEPS"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_lora_alpha` (`RAGWELD_AGENT_LORA_ALPHA`) — RAGWELD_AGENT_LORA_ALPHA"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_lora_dropout` (`RAGWELD_AGENT_LORA_DROPOUT`) — RAGWELD_AGENT_LORA_DROPOUT"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_lora_rank` (`RAGWELD_AGENT_LORA_RANK`) — RAGWELD_AGENT_LORA_RANK"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_model_path` (`RAGWELD_AGENT_MODEL_PATH`) — RAGWELD_AGENT_MODEL_PATH"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_promote_epsilon` (`RAGWELD_AGENT_PROMOTE_EPSILON`) — RAGWELD_AGENT_PROMOTE_EPSILON"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_promote_if_improves` (`RAGWELD_AGENT_PROMOTE_IF_IMPROVES`) — RAGWELD_AGENT_PROMOTE_IF_IMPROVES"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_telemetry_interval_steps` (`RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS`) — RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.ragweld_agent_train_dataset_path` (`RAGWELD_AGENT_TRAIN_DATASET_PATH`) — RAGWELD_AGENT_TRAIN_DATASET_PATH"
    **Category**: `general`

    No detailed tooltip available yet.

??? info "`training.reranker_train_batch` (`RERANKER_TRAIN_BATCH`) — Training Batch Size"
    **Category**: `embedding`

    Batches per gradient step during training. Larger batch sizes stabilize training but require more memory. For Colima or small GPUs/CPUs, use 1–4. If you see the container exit with code -9 (OOM), reduce this value.

    **Badges**:
    - Lower = safer on Colima

    **Links**:
    - [Memory Tips (HF)](https://huggingface.co/docs/transformers/perf_train_gpu_one)
    - [Colima Resources](https://github.com/abiosoft/colima)

??? info "`training.reranker_train_epochs` (`RERANKER_TRAIN_EPOCHS`) — Training Epochs"
    **Category**: `reranking`

    Number of full passes over the training triplets for the learning reranker. More epochs can improve quality but risk overfitting when data is small. Start with 1–2 and increase as your mined dataset grows.

    **Badges**:
    - Quality vs overfit

??? info "`training.reranker_train_lr` (`RERANKER_TRAIN_LR`) — Training Learning Rate"
    **Category**: `reranking`

    Learning rate for learning-reranker optimization during fine-tuning. This controls the size of weight updates during gradient descent. Typical range is 1e-6 to 5e-5. Higher values (3e-5 to 5e-5) converge faster but can destabilize training; lower values (1e-6 to 1e-5) are safer but slower.

    Sweet spot: 2e-5 for most runs. Use 1e-5 for smaller triplet sets or unstable loss curves, and 3e-5 for larger datasets with steady validation metrics.

    Combine with RERANKER_WARMUP_RATIO so early steps ramp smoothly from 0 to target LR.

    • Typical range: 1e-6 to 5e-5
    • Conservative: 1e-5
    • Balanced default: 2e-5
    • Aggressive: 3e-5 to 5e-5
    • Too high: Loss spikes, NaN values, divergence
    • Too low: Slow convergence, limited gains

    **Badges**:
    - Advanced ML training
    - Requires tuning

    **Links**:
    - [Learning Rate Explained](https://machinelearningmastery.com/understand-the-dynamics-of-learning-rate-on-deep-learning-neural-networks/)
    - [Learning Rate Schedules](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules)

??? info "`training.reranker_warmup_ratio` (`RERANKER_WARMUP_RATIO`) — Warmup Ratio"
    **Category**: `reranking`

    Fraction of total training steps to use for linear learning-rate warmup. During warmup, LR ramps from 0 to RERANKER_TRAIN_LR to reduce early instability; after warmup, LR follows its normal schedule.

    Sweet spot: 0.1 (10%). For short runs (<500 steps), 0.05-0.08 is often enough. For long runs (>1000 steps), 0.1-0.15 can improve stability.

    • No warmup: 0.0
    • Short training: 0.05-0.08
    • Balanced default: 0.1
    • Long training: 0.15-0.2
    • Effect: Stabilizes early updates and reduces divergence risk

    **Badges**:
    - Advanced ML training
    - Stabilizes training

    **Links**:
    - [Warmup Schedules](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules#transformers.get_linear_schedule_with_warmup)
    - [Learning Rate Warmup Paper](https://arxiv.org/abs/1706.02677)
    - [Scheduler Visualization](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules)

??? info "`training.tribrid_reranker_mine_mode` (`TRIBRID_RERANKER_MINE_MODE`) — Triplet Mining Mode"
    **Category**: `general`

    Strategy for mining training triplets: random, semi‑hard, or hard negatives. Harder negatives improve discriminative power but may be noisier and slower to mine.

    **Badges**:
    - Advanced

    **Links**:
    - [Hard Negative Mining](https://sbert.net/examples/training/quora_duplicate_questions/README.html)

??? info "`training.tribrid_reranker_mine_reset` (`TRIBRID_RERANKER_MINE_RESET`) — Reset Triplets Before Mining"
    **Category**: `general`

    If enabled, deletes existing mined triplets before starting a new mining run. Use with caution to avoid losing curated datasets.

    **Badges**:
    - Destructive

??? info "`training.tribrid_reranker_model_path` (`TRIBRID_RERANKER_MODEL_PATH`) — Reranker Model Path"
    **Category**: `general`

    Filesystem path to the active learning reranker artifact (relative paths recommended). For the MLX Qwen3 learning reranker this is the active LoRA adapter directory. The service loads from this path on startup or when reloaded.

    **Links**:
    - [Model Checkpoints](https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.from_pretrained)

??? info "`training.tribrid_triplets_path` (`TRIBRID_TRIPLETS_PATH`) — Triplets Dataset Path"
    **Category**: `general`

    Path to the JSONL triplets dataset used for learning reranker mining and training. Default: data/training/triplets__epstein-files-1.jsonl. Keep this in durable storage for reproducible experiments.

    **Links**:
    - [Triplet Loss](https://en.wikipedia.org/wiki/Triplet_loss)

??? info "`training.triplets_min_count` (`TRIPLETS_MIN_COUNT`) — Triplets Min Count"
    **Category**: `general`

    Minimum mined triplets required before training starts. Default: 100. Range: 10-10000. If training skips for insufficient data, mine more triplets or lower this for experimentation.

    **Badges**:
    - Data quality gate
    - Production needs 500+

    **Links**:
    - [Triplet Loss for Ranking](https://arxiv.org/abs/1503.03832)
    - [Hard Negative Mining](https://arxiv.org/abs/2104.08663)
    - [Triplet Mining in RAG (ACL 2025)](https://aclanthology.org/2025.acl-industry.72.pdf)
    - [Learning to Rank](https://en.wikipedia.org/wiki/Learning_to_rank)

??? info "`training.triplets_mine_mode` (`TRIPLETS_MINE_MODE`) — Triplets Mine Mode"
    **Category**: `general`

    How mined triplets are written: replace (overwrite dataset) or append (add to existing file). Default: replace. Use append for incremental collection; use replace for clean, reproducible runs.

    **Badges**:
    - Advanced training control
    - Use semi-hard for production

    **Links**:
    - [Hard Negative Mining](https://arxiv.org/abs/2104.08663)
    - [Negative Sampling Strategies](https://arxiv.org/abs/2007.00808)
    - [Triplet Mining (ACL 2025)](https://aclanthology.org/2025.acl-industry.72.pdf)
