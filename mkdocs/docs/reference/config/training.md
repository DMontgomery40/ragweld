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

**Total parameters**: 45

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `training.learning_reranker_backend` | `LEARNING_RERANKER_BACKEND` | `Literal["auto", "mlx_qwen3"]` | `"auto"` | allowed="auto", "mlx_qwen3" | Learning reranker backend: auto (prefer MLX Qwen3 on Apple Silicon), mlx_qwen3 (force). Stale values such as 'transformers'/'hf'/'mlx' fail validation and must be migrated. |
| `training.learning_reranker_base_model` | `LEARNING_RERANKER_BASE_MODEL` | `str` | `"Qwen/Qwen3-Reranker-0.6B"` | — | Base model to fine-tune for MLX Qwen3 learning reranker |
| `training.learning_reranker_grad_accum_steps` | `LEARNING_RERANKER_GRAD_ACCUM_STEPS` | `int` | `8` | ≥ 1, ≤ 128 | Gradient accumulation steps per optimizer update for MLX Qwen3 learning reranker training |
| `training.learning_reranker_lora_alpha` | `LEARNING_RERANKER_LORA_ALPHA` | `float` | `32.0` | > 0.0, ≤ 512.0 | LoRA alpha for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_dropout` | `LEARNING_RERANKER_LORA_DROPOUT` | `float` | `0.05` | ≥ 0.0, ≤ 0.5 | LoRA dropout for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_rank` | `LEARNING_RERANKER_LORA_RANK` | `int` | `16` | ≥ 1, ≤ 128 | LoRA rank for MLX Qwen3 learning reranker |
| `training.learning_reranker_lora_target_modules` | — | `list[str]` | `["q_proj", "k_proj", "v_proj", "o_proj"]` | min_length=1 | Module name suffixes to apply LoRA to (MLX Qwen3) |
| `training.learning_reranker_negative_ratio` | `LEARNING_RERANKER_NEGATIVE_RATIO` | `int` | `5` | ≥ 1, ≤ 20 | Negative pairs per positive during learning reranker training |
| `training.learning_reranker_promote_epsilon` | `LEARNING_RERANKER_PROMOTE_EPSILON` | `float` | `0.0` | ≥ 0.0, ≤ 1.0 | Minimum improvement required to auto-promote (primary metric delta) |
| `training.learning_reranker_promote_if_improves` | `LEARNING_RERANKER_PROMOTE_IF_IMPROVES` | `bool` | `true` | — | Promote trained learning artifact to active path only if primary metric improves |
| `training.learning_reranker_telemetry_interval_steps` | `LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS` | `int` | `2` | ≥ 1, ≤ 20 | Emit trainer telemetry every N optimizer steps (plus first/final) |
| `training.learning_reranker_unload_after_sec` | `LEARNING_RERANKER_UNLOAD_AFTER_SEC` | `int` | `0` | ≥ 0, ≤ 86400 | Unload MLX learning reranker model after idle seconds (0 = never) |
| `training.ragweld_agent_backend` | `RAGWELD_AGENT_BACKEND` | `str` | `"mlx_qwen3"` | — | Learning Agent LoRA training backend (training-only artifact; chat generation is served through LiteLLM). Currently: mlx_qwen3 |
| `training.ragweld_agent_base_model` | `RAGWELD_AGENT_BASE_MODEL` | `str` | `"mlx-community/Qwen3-4B-Instruct-2507-4bit"` | — | MLX base model the Learning Agent LoRA adapters are trained on. Artifacts trained for another base are not promotable. |
| `training.ragweld_agent_flyte_admin_base_url` | `RAGWELD_AGENT_FLYTE_ADMIN_BASE_URL` | `str` | `""` | — | Base URL for Flyte Admin HTTP access (used for readiness checks and operator links). |
| `training.ragweld_agent_flyte_callback_base_url` | `RAGWELD_AGENT_FLYTE_CALLBACK_BASE_URL` | `str` | `""` | — | Base URL of this Ragweld API as reachable from Flyte task pods (the workflow task hands the run to this API's execute boundary and tracks it). On Colima the host is the VM gateway, for example http://192.168.5.2:58012. |
| `training.ragweld_agent_flyte_console_base_url` | `RAGWELD_AGENT_FLYTE_CONSOLE_BASE_URL` | `str` | `""` | — | Base URL for Flyte Console (used for operator deep links). |
| `training.ragweld_agent_flyte_domain` | `RAGWELD_AGENT_FLYTE_DOMAIN` | `str` | `"development"` | — | Flyte domain/environment that owns Learning Agent executions. |
| `training.ragweld_agent_flyte_launchplan` | `RAGWELD_AGENT_FLYTE_LAUNCHPLAN` | `str` | `""` | — | Flyte launch plan name for the Learning Agent workflow lane. |
| `training.ragweld_agent_flyte_project` | `RAGWELD_AGENT_FLYTE_PROJECT` | `str` | `"ragweld"` | — | Flyte project that owns Learning Agent executions. |
| `training.ragweld_agent_grad_accum_steps` | `RAGWELD_AGENT_GRAD_ACCUM_STEPS` | `int` | `8` | ≥ 1, ≤ 128 | Gradient accumulation steps per optimizer update for ragweld agent training. |
| `training.ragweld_agent_lora_alpha` | `RAGWELD_AGENT_LORA_ALPHA` | `float` | `32.0` | > 0.0, ≤ 512.0 | LoRA alpha for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_dropout` | `RAGWELD_AGENT_LORA_DROPOUT` | `float` | `0.05` | ≥ 0.0, ≤ 0.5 | LoRA dropout for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_rank` | `RAGWELD_AGENT_LORA_RANK` | `int` | `16` | ≥ 1, ≤ 128 | LoRA rank for ragweld agent MLX fine-tuning. |
| `training.ragweld_agent_lora_target_modules` | — | `list[str]` | `["q_proj", "k_proj", "v_proj", "o_proj"]` | min_length=1 | Module name suffixes to apply LoRA to (ragweld agent; MLX Qwen3). |
| `training.ragweld_agent_mlflow_experiment_name` | `RAGWELD_AGENT_MLFLOW_EXPERIMENT_NAME` | `str` | `"ragweld-learning-agent"` | — | MLflow experiment name for Learning Agent runs. |
| `training.ragweld_agent_mlflow_tracking_url` | `RAGWELD_AGENT_MLFLOW_TRACKING_URL` | `str` | `"http://127.0.0.1:55500"` | — | Base URL of the Compose-owned MLflow Tracking server used by Learning Agent runs. |
| `training.ragweld_agent_model_path` | `RAGWELD_AGENT_MODEL_PATH` | `str` | `"models/learning-agent-active"` | — | Root of the Learning Agent's versioned adapter store (versions/ + ACTIVE.json pointer); each version holds adapter.npz + adapter_config.json + manifest.json. Training-only: the baseline for later runs and lineage; never served by the chat gateway. |
| `training.ragweld_agent_promote_epsilon` | `RAGWELD_AGENT_PROMOTE_EPSILON` | `float` | `0.0` | ≥ 0.0, ≤ 10.0 | Minimum eval_loss improvement required to auto-promote (baseline_loss - new_loss >= epsilon). |
| `training.ragweld_agent_promote_if_improves` | `RAGWELD_AGENT_PROMOTE_IF_IMPROVES` | `bool` | `true` | — | Auto-promote trained ragweld agent adapter only if eval_loss improves. |
| `training.ragweld_agent_telemetry_interval_steps` | `RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS` | `int` | `2` | ≥ 1, ≤ 20 | Emit ragweld agent trainer telemetry every N optimizer steps (plus first/final). |
| `training.ragweld_agent_tracking_backend` | `RAGWELD_AGENT_TRACKING_BACKEND` | `Literal["local", "mlflow"]` | `"local"` | allowed="local", "mlflow" | Run/artifact tracking backend for Learning Agent runs. |
| `training.ragweld_agent_train_dataset_path` | `RAGWELD_AGENT_TRAIN_DATASET_PATH` | `str` | `""` | — | Training dataset path for the ragweld agent (empty = use evaluation.eval_dataset_path). |
| `training.ragweld_agent_unsloth_image` | `RAGWELD_AGENT_UNSLOTH_IMAGE` | `str` | `""` | — | Container image or artifact reference used by the Flyte task to run Unsloth training. |
| `training.ragweld_agent_workflow_backend` | `RAGWELD_AGENT_WORKFLOW_BACKEND` | `Literal["local", "flyte"]` | `"local"` | allowed="local", "flyte" | Workflow/orchestration backend for Learning Agent runs. |
| `training.reranker_train_batch` | `RERANKER_TRAIN_BATCH` | `int` | `16` | ≥ 1, ≤ 128 | Training batch size |
| `training.reranker_train_epochs` | `RERANKER_TRAIN_EPOCHS` | `int` | `2` | ≥ 1, ≤ 20 | Training epochs for reranker |
| `training.reranker_train_lr` | `RERANKER_TRAIN_LR` | `float` | `2e-05` | ≥ 1e-06, ≤ 0.001 | Learning rate |
| `training.reranker_warmup_ratio` | `RERANKER_WARMUP_RATIO` | `float` | `0.1` | ≥ 0.0, ≤ 0.5 | Warmup steps ratio |
| `training.tribrid_reranker_mine_mode` | `TRIBRID_RERANKER_MINE_MODE` | `str` | `"replace"` | pattern=^(replace\|append)$ | Triplet mining mode |
| `training.tribrid_reranker_mine_reset` | `TRIBRID_RERANKER_MINE_RESET` | `bool` | `false` | — | Reset triplets file before mining |
| `training.tribrid_reranker_model_path` | `TRIBRID_RERANKER_MODEL_PATH` | `str` | `"models/learning-reranker-active"` | — | Root of the learning reranker's versioned artifact store (versions/ + ACTIVE.json pointer). Readers resolve the pointer to the active immutable MLX adapter version; promotions switch it atomically. |
| `training.tribrid_triplets_path` | `TRIBRID_TRIPLETS_PATH` | `str` | `"data/training/triplets.jsonl"` | — | Training triplets file path |
| `training.triplets_min_count` | `TRIPLETS_MIN_COUNT` | `int` | `100` | ≥ 10, ≤ 10000 | Min triplets for training |
| `training.triplets_mine_mode` | `TRIPLETS_MINE_MODE` | `str` | `"replace"` | pattern=^(replace\|append)$ | Triplet mining mode |

### Details (glossary)

??? info "`training.learning_reranker_backend` (`LEARNING_RERANKER_BACKEND`) — Learning Reranker Backend"
    **Category**: `reranking`

    Selects the execution stack used to train and serve the learning-based reranker. In this project, backend choice determines hardware assumptions, supported model formats, and how adapters are loaded during inference, so it directly affects throughput, reproducibility, and operational complexity. Keep the backend consistent across training and deployment environments whenever possible, or validate compatibility boundaries before shipping adapters. If performance or stability regresses, backend mismatch is one of the first places to investigate.

    **Badges**:
    - Backend selection

    **Links**:
    - [Qwen3 Embeddings and Rerankers (arXiv)](https://arxiv.org/abs/2506.05176)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

??? info "`training.learning_reranker_base_model` (`LEARNING_RERANKER_BASE_MODEL`) — Learning Reranker Base Model"
    **Category**: `reranking`

    Base checkpoint that LoRA adapters are trained against and later mounted on during reranking inference. Adapter weights are architecture-specific, so changing the base model after training usually invalidates existing adapters and can silently degrade ranking quality if not caught. Pin this value explicitly, record it in experiment metadata, and keep train/infer parity to make evaluation deltas trustworthy. In practice, base-model drift is a common root cause of non-reproducible reranker performance.

    **Badges**:
    - Model compatibility

    **Links**:
    - [Qwen3 Embeddings and Rerankers (arXiv)](https://arxiv.org/abs/2506.05176)
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

??? info "`training.learning_reranker_grad_accum_steps` (`LEARNING_RERANKER_GRAD_ACCUM_STEPS`) — Learning Reranker Grad Accum Steps"
    **Category**: `reranking`

    Number of micro-batches whose gradients are accumulated before each optimizer update during reranker training. Increasing this value raises effective batch size without requiring equivalent VRAM, which can stabilize ranking-objective learning but also slows update frequency and may require learning-rate retuning. For RAG rerankers, this parameter is most useful when negatives are hard and memory is constrained, because larger effective batches improve signal diversity per update. Tune it jointly with global batch size, learning rate, and training time budget rather than in isolation.

    **Badges**:
    - Training dynamics

    **Links**:
    - [ERank: Efficient Learning-to-Rank for RAG (arXiv)](https://arxiv.org/abs/2509.00520)
    - [PyTorch Gradient Accumulation](https://pytorch.org/docs/stable/notes/amp_examples.html#gradient-accumulation)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

??? info "`training.learning_reranker_lora_alpha` (`LEARNING_RERANKER_LORA_ALPHA`) — Learning Reranker LoRA Alpha"
    **Category**: `reranking`

    LoRA scaling factor that determines how strongly adapter updates influence the frozen base reranker during training and inference. The effective adaptation strength is tied to alpha relative to rank, so increasing alpha without considering rank can over-amplify updates and destabilize relevance calibration. In ranking-focused fine-tuning, this value is best tuned with validation metrics that emphasize ordering quality, not just loss reduction. Use conservative increments and track metric movement on hard negatives to avoid overfitting narrow retrieval patterns.

    **Badges**:
    - LoRA scaling

    **Links**:
    - [How Relevance Emerges in Fine-tuned Rerankers (arXiv)](https://arxiv.org/abs/2504.08780)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

??? info "`training.learning_reranker_lora_dropout` (`LEARNING_RERANKER_LORA_DROPOUT`) — Learning Reranker LoRA Dropout"
    **Category**: `reranking`

    Dropout probability applied inside LoRA adapter paths during reranker fine-tuning. This acts as regularization against overfitting on narrow training pairs, especially when mined positives and negatives are repetitive or domain-skewed. Too little dropout can produce brittle rankers that fail on unseen queries, while too much can underfit and flatten relevance separation. Tune with validation sets that include both in-domain and near-domain queries so improvements generalize beyond the training distribution.

    **Badges**:
    - LoRA regularization

    **Links**:
    - [How Relevance Emerges in Fine-tuned Rerankers (arXiv)](https://arxiv.org/abs/2504.08780)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

??? info "`training.learning_reranker_lora_rank` (`LEARNING_RERANKER_LORA_RANK`) — Learning Reranker LoRA Rank"
    **Category**: `reranking`

    Adapter rank determines the capacity of LoRA updates layered onto the base reranker. Higher rank can capture richer relevance transformations and improve difficult ranking tasks, but it increases memory, training cost, and overfitting risk if data volume is limited. Lower rank is cheaper and often sufficient for moderate domain adaptation, especially when base model quality is already high. Select rank by balancing retrieval-quality gains against training budget and inference latency targets, then confirm with held-out ranking benchmarks.

    **Badges**:
    - LoRA capacity

    **Links**:
    - [How Relevance Emerges in Fine-tuned Rerankers (arXiv)](https://arxiv.org/abs/2504.08780)
    - [PEFT LoRA Guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)
    - [MLX-LM Repository](https://github.com/ml-explore/mlx-lm)
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

??? info "`training.learning_reranker_negative_ratio` (`LEARNING_RERANKER_NEGATIVE_RATIO`) — Learning Reranker Negative Ratio"
    **Category**: `reranking`

    `LEARNING_RERANKER_NEGATIVE_RATIO` controls how many negative `(query, document)` pairs are generated per positive pair during learning-reranker training (default `5`, range `1`-`20`). Higher ratios usually improve separation between relevant and non-relevant candidates, but they also increase training time, GPU memory usage, and the risk of overfitting to easy negatives if sampling quality is poor. Lower ratios train faster and can be sufficient when negatives are already hard and diverse, but may leave the reranker under-discriminative on near-miss results. Treat this as a quality-versus-cost dial and tune it alongside hard-negative mining strategy and dev-set ranking metrics.

    **Badges**:
    - Quality vs cost

    **Links**:
    - [Reranker Optimization via Geodesic Distances on k-NN Manifolds (arXiv)](https://arxiv.org/abs/2602.15860)
    - [Sentence Transformers: Train Cross-Encoder for Reranking](https://www.sbert.net/examples/cross_encoder/training/rerankers/README.html)
    - [Sentence Transformers Loss Functions](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html)
    - [PyTorch MarginRankingLoss](https://pytorch.org/docs/stable/generated/torch.nn.MarginRankingLoss.html)

??? info "`training.learning_reranker_promote_epsilon` (`LEARNING_RERANKER_PROMOTE_EPSILON`) — Learning Reranker Promotion Epsilon"
    **Category**: `reranking`

    `LEARNING_RERANKER_PROMOTE_EPSILON` sets the minimum dev-metric delta required before a newly trained reranker is allowed to replace the active baseline (range `0.0`-`1.0`, default `0.0`). This threshold is a noise guard: if metric gains are smaller than epsilon, the run is treated as statistically or operationally insignificant and promotion should be blocked. Small nonzero values (for example around `0.001`-`0.005` depending on metric stability) reduce churn from random variation, label noise, and temporary data drift. Calibrate epsilon from repeated baseline evaluations so promotion decisions reflect durable quality changes rather than measurement jitter.

    **Badges**:
    - Prevents noise promotions

    **Links**:
    - [Scaling Search Relevance: Augmenting App Store Ranking with LLM-Generated Judgments (arXiv)](https://arxiv.org/abs/2602.23234)
    - [MLflow Model Registry Tutorial](https://mlflow.org/docs/latest/ml/model-registry/tutorial)
    - [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
    - [SciPy Paired t-test (ttest_rel)](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_rel.html)

??? info "`training.learning_reranker_promote_if_improves` (`LEARNING_RERANKER_PROMOTE_IF_IMPROVES`) — Learning Reranker Promotion Gate"
    **Category**: `reranking`

    `LEARNING_RERANKER_PROMOTE_IF_IMPROVES` is the hard promotion gate for learning-reranker training. When enabled (default), a successful training job promotes the candidate artifact only if the primary dev metric exceeds the current baseline by at least `LEARNING_RERANKER_PROMOTE_EPSILON`; when disabled, every successful run can overwrite the active path. Keeping this enabled is safer in continuous-training loops because it preserves model stability during noisy data windows and imperfect labeling periods. Disable it only for controlled experiments with manual review and explicit rollback procedures.

    **Badges**:
    - Safety

    **Links**:
    - [Scaling Search Relevance: Augmenting App Store Ranking with LLM-Generated Judgments (arXiv)](https://arxiv.org/abs/2602.23234)
    - [MLflow Model Registry Tutorial](https://mlflow.org/docs/latest/ml/model-registry/tutorial)
    - [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
    - [SciPy Paired t-test (ttest_rel)](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_rel.html)

??? info "`training.learning_reranker_telemetry_interval_steps` (`LEARNING_RERANKER_TELEMETRY_INTERVAL_STEPS`) — Learning Reranker Telemetry Interval Steps"
    **Category**: `reranking`

    Defines how often trainer telemetry is emitted in optimizer-step units. Lower values (for example 1-2) produce smoother live curves and faster anomaly detection, but increase event traffic, UI render pressure, and log volume. Higher values reduce overhead and can stabilize weak machines, but hide short-lived instability such as gradient spikes or transient loss explosions. In practice, use tighter intervals while tuning a new objective or dataset, then relax interval size once behavior is stable. This parameter directly shapes observability quality, so tune it with both monitoring fidelity and system cost in mind.

    **Links**:
    - [Query-focused and Memory-aware Reranker for Unrestricted Context (arXiv, 2026)](https://arxiv.org/abs/2602.12192)
    - [Weights & Biases: Log Data During Experiments](https://docs.wandb.ai/guides/track/log)
    - [PyTorch Lightning Logging](https://lightning.ai/docs/pytorch/stable/extensions/logging.html)
    - [REARANK: Reinforcement Learning for RAG Reranking (arXiv, 2025)](https://arxiv.org/abs/2505.20046)

??? info "`training.learning_reranker_unload_after_sec` (`LEARNING_RERANKER_UNLOAD_AFTER_SEC`) — Learning Reranker Idle Unload"
    **Category**: `reranking`

    Idle-time model eviction threshold for the local MLX reranker. When this timer is greater than zero, the reranker is unloaded after inactivity so RAM/VRAM can be reclaimed for other work; when set to zero, the model stays resident and avoids cold-start reload latency. This is a classic memory-latency tradeoff: aggressive unloading helps constrained laptops, while persistent residency is better for frequent back-to-back reranks. Tune this using actual interaction cadence, not defaults: if people pause briefly between trials, use a longer window to avoid repeated thrash from unload/reload cycles.

    **Badges**:
    - MLX only
    - Affects latency

    **Links**:
    - [Query-focused and Memory-aware Reranker for Unrestricted Context (arXiv, 2026)](https://arxiv.org/abs/2602.12192)
    - [Ollama API Reference](https://docs.ollama.com/api)
    - [MLX Documentation](https://ml-explore.github.io/mlx/build/html/index.html)
    - [REARANK: Reinforcement Learning for RAG Reranking (arXiv, 2025)](https://arxiv.org/abs/2505.20046)

??? info "`training.ragweld_agent_backend` (`RAGWELD_AGENT_BACKEND`) — RAGWELD_AGENT_BACKEND"
    **Category**: `general`

    Chooses the runtime stack used to train and evaluate the agent model (for example, a Transformers/TRL pipeline with DeepSpeed, or another backend with different distributed semantics). This setting controls how batches are scheduled, how optimizer state is sharded, how mixed precision is handled, and what checkpoint artifacts are produced. In practice, backend choice affects throughput, memory headroom, resume reliability, and reproducibility more than most single hyperparameters. Keep backend, precision mode, and checkpoint format aligned so promoted adapters can be reloaded without silent drift.

    **Links**:
    - [LoRAFusion: Advancing Efficient Fine-Tuning in Production-Scale Language Models (arXiv 2025)](https://arxiv.org/abs/2510.00206)
    - [Hugging Face TRL: PEFT Integration](https://huggingface.co/docs/trl/main/peft_integration)
    - [Transformers Trainer API](https://huggingface.co/docs/transformers/main_classes/trainer)
    - [DeepSpeed Config: Batch and Training Parameters](https://www.deepspeed.ai/docs/config-json/#batch-size-related-parameters)

??? info "`training.ragweld_agent_base_model` (`RAGWELD_AGENT_BASE_MODEL`) — RAGWELD_AGENT_BASE_MODEL"
    **Category**: `general`

    Specifies the pretrained foundation model that LoRA adapters are attached to. Tokenizer vocabulary, context length behavior, architecture names, and module layout all come from this base model, so changing it after training usually invalidates existing adapters. Treat this as an ABI contract for fine-tuning: adapter weights, target modules, and optimizer state are only portable when the base model family and revision are compatible. Pin exact model revisions to make evaluation and rollback deterministic.

    **Links**:
    - [Linearization of Language Models under Parameter-Efficient Fine-Tuning (arXiv 2026)](https://arxiv.org/abs/2602.08239)
    - [Transformers PreTrainedModel Reference](https://huggingface.co/docs/transformers/main/en/main_classes/model)
    - [Transformers AutoModel Classes](https://huggingface.co/docs/transformers/main/model_doc/auto)
    - [Hugging Face Model Cards](https://huggingface.co/docs/hub/en/model-cards)

??? info "`training.ragweld_agent_grad_accum_steps` (`RAGWELD_AGENT_GRAD_ACCUM_STEPS`) — RAGWELD_AGENT_GRAD_ACCUM_STEPS"
    **Category**: `general`

    Defines how many micro-batches are accumulated before one optimizer update. Effective batch size is roughly `per_device_batch_size * grad_accum_steps * world_size`, so increasing this value lets you emulate larger batches under limited VRAM. The tradeoff is fewer optimizer steps per wall-clock minute and slightly staler gradients, which can change convergence behavior. Tune this together with learning rate and scheduler warmup, not in isolation, because accumulation directly changes update frequency.

    **Links**:
    - [PROMA: Continual Pretraining and RL Fine-Tuning Framework (arXiv 2026)](https://arxiv.org/abs/2601.10498)
    - [Transformers TrainingArguments: gradient_accumulation_steps](https://huggingface.co/docs/transformers/main_classes/trainer#transformers.TrainingArguments.gradient_accumulation_steps)
    - [DeepSpeed Batch Size and Gradient Accumulation Settings](https://www.deepspeed.ai/docs/config-json/#batch-size-related-parameters)
    - [PyTorch Automatic Mixed Precision](https://docs.pytorch.org/docs/stable/amp.html)

??? info "`training.ragweld_agent_lora_alpha` (`RAGWELD_AGENT_LORA_ALPHA`) — RAGWELD_AGENT_LORA_ALPHA"
    **Category**: `general`

    Controls LoRA adapter scaling (commonly applied as `alpha / rank`). Higher alpha increases the effective strength of adapter updates and can speed adaptation, but it also raises the risk of overshooting or overfitting on narrow datasets. Lower alpha makes updates conservative and may underfit unless training runs longer. Treat alpha as a stability/capacity dial coupled to rank and learning rate; when rank changes, revisit alpha instead of keeping a fixed absolute value.

    **Links**:
    - [Linearization of Language Models under Parameter-Efficient Fine-Tuning (arXiv 2026)](https://arxiv.org/abs/2602.08239)
    - [PEFT LoRA Configuration Reference](https://huggingface.co/docs/peft/main/package_reference/lora)
    - [PEFT LoRA Developer Guide](https://huggingface.co/docs/peft/main/developer_guides/lora)
    - [TRL PEFT Integration](https://huggingface.co/docs/trl/main/peft_integration)

??? info "`training.ragweld_agent_lora_dropout` (`RAGWELD_AGENT_LORA_DROPOUT`) — RAGWELD_AGENT_LORA_DROPOUT"
    **Category**: `general`

    Applies dropout on the adapter path during training to reduce co-adaptation and improve generalization when data is limited or noisy. Setting this to `0.0` maximizes determinism and can help on very large, clean corpora, while moderate values often improve robustness on mixed-quality data. Too much dropout suppresses useful signal and slows learning. Tune it alongside alpha and rank because stronger regularization usually needs either more steps or slightly higher adapter capacity.

    **Links**:
    - [FedSA-LoRA: Bayesian Sparse and Adaptive Low-Rank Adaptation (arXiv 2026)](https://arxiv.org/abs/2602.22295)
    - [PEFT LoRA Configuration Reference](https://huggingface.co/docs/peft/main/package_reference/lora)
    - [PyTorch Dropout Layer Reference](https://docs.pytorch.org/docs/stable/generated/torch.nn.Dropout.html)
    - [TRL PEFT Integration](https://huggingface.co/docs/trl/main/peft_integration)

??? info "`training.ragweld_agent_lora_rank` (`RAGWELD_AGENT_LORA_RANK`) — RAGWELD_AGENT_LORA_RANK"
    **Category**: `general`

    Sets the low-rank adapter dimension (`r`), which is the main capacity knob for LoRA. Higher rank increases representational power and typically improves fit on complex tasks, but also raises VRAM, compute, and risk of overfitting. Lower rank is cheaper and often adequate for style or narrow-domain adaptation. Choose rank using validation metrics under fixed budget constraints, and retune alpha when rank changes because update scaling depends on both.

    **Links**:
    - [Adaptive LoRA Exploration in Federated Fine-Tuning (arXiv 2026)](https://arxiv.org/abs/2602.20492)
    - [PEFT LoRA Configuration Reference](https://huggingface.co/docs/peft/main/package_reference/lora)
    - [PEFT LoRA Developer Guide](https://huggingface.co/docs/peft/main/developer_guides/lora)
    - [TRL PEFT Integration](https://huggingface.co/docs/trl/main/peft_integration)

??? info "`training.ragweld_agent_model_path` (`RAGWELD_AGENT_MODEL_PATH`) — RAGWELD_AGENT_MODEL_PATH"
    **Category**: `general`

    Root directory of the Learning Agent's versioned adapter store. Promotions publish each trained LoRA adapter as an immutable version under `versions/<run_id>/` and switch a fsynced `ACTIVE.json` pointer atomically, so readers resolve the pointer once and never observe a half-written or missing artifact; a crashed promotion is repaired at startup. The store retains the current version plus the one it just retired, and the full history stays in each run's artifact directory. Training-only: it provides the baseline for later runs and lineage capture, and is never served by the chat gateway.

    **Links**:
    - [LLMTailor: Fine-Tuning LLMs by Checking Components and LoRA (arXiv 2026)](https://arxiv.org/abs/2602.22158)
    - [Transformers PreTrainedModel Loading and Saving](https://huggingface.co/docs/transformers/main/en/main_classes/model)
    - [Hugging Face Hub Download Guide](https://huggingface.co/docs/huggingface_hub/en/guides/download)
    - [Safetensors Documentation](https://huggingface.co/docs/safetensors/en/index)

??? info "`training.ragweld_agent_promote_epsilon` (`RAGWELD_AGENT_PROMOTE_EPSILON`) — RAGWELD_AGENT_PROMOTE_EPSILON"
    **Category**: `general`

    Sets the minimum metric gain required before a new checkpoint is promoted over the current best. This prevents noisy, statistically insignificant fluctuations from constantly replacing promoted models. Use epsilon in the same unit as your monitored metric (for example absolute NDCG gain or loss decrease), and calibrate it from historical run variance. If epsilon is too small, promotion churn increases; if too large, meaningful improvements are ignored and iteration slows.

    **Links**:
    - [UGCS: Better Checkpoint Selection for LLM Optimization (arXiv 2025)](https://arxiv.org/abs/2511.09864)
    - [Transformers TrainingArguments: load_best_model_at_end](https://huggingface.co/docs/transformers/main_classes/trainer#transformers.TrainingArguments.load_best_model_at_end)
    - [PyTorch Lightning EarlyStopping (min_delta)](https://lightning.ai/docs/pytorch/stable/api/pytorch_lightning.callbacks.EarlyStopping.html)
    - [PyTorch Lightning ModelCheckpoint](https://lightning.ai/docs/pytorch/stable/api/pytorch_lightning.callbacks.ModelCheckpoint.html)

??? info "`training.ragweld_agent_promote_if_improves` (`RAGWELD_AGENT_PROMOTE_IF_IMPROVES`) — RAGWELD_AGENT_PROMOTE_IF_IMPROVES"
    **Category**: `general`

    Boolean gate for checkpoint promotion based on validation outcomes. When enabled, a candidate checkpoint is promoted only if the tracked metric improves versus the current promoted model (typically with `PROMOTE_EPSILON` as the noise threshold). This keeps production candidates aligned to measured quality instead of recency. When disabled, every completed run can overwrite promoted state, which is useful for exploratory debugging but risky for stable deployments.

    **Links**:
    - [UGCS: Better Checkpoint Selection for LLM Optimization (arXiv 2025)](https://arxiv.org/abs/2511.09864)
    - [Transformers Trainer and Best-Checkpoint Selection](https://huggingface.co/docs/transformers/main_classes/trainer)
    - [PyTorch Lightning ModelCheckpoint](https://lightning.ai/docs/pytorch/stable/api/pytorch_lightning.callbacks.ModelCheckpoint.html)
    - [PyTorch Lightning EarlyStopping](https://lightning.ai/docs/pytorch/stable/api/pytorch_lightning.callbacks.EarlyStopping.html)

??? info "`training.ragweld_agent_telemetry_interval_steps` (`RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS`) — RAGWELD_AGENT_TELEMETRY_INTERVAL_STEPS"
    **Category**: `general`

    Controls how often the training/runtime loop emits telemetry snapshots, measured in optimizer or agent steps. Lower values improve observability granularity (you see loss drift, action-quality regressions, and tool-failure spikes sooner) but increase logging overhead, storage volume, and dashboard cost. Higher values reduce overhead but can hide short-lived failures and make root-cause analysis harder because fewer intermediate states are preserved. Tune this together with batch size and run duration: keep intervals small during experiments and incident triage, then increase once behavior is stable.

    **Links**:
    - [AgentSight: Visualizing and Monitoring Foundation Agent Dynamics (arXiv 2025)](https://arxiv.org/abs/2508.02736)
    - [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
    - [Prometheus Instrumentation Best Practices](https://prometheus.io/docs/practices/instrumentation/)
    - [LangSmith Observability Quickstart](https://docs.langchain.com/langsmith/observability-quickstart)

??? info "`training.ragweld_agent_train_dataset_path` (`RAGWELD_AGENT_TRAIN_DATASET_PATH`) — RAGWELD_AGENT_TRAIN_DATASET_PATH"
    **Category**: `general`

    Filesystem path to the training dataset used by the agent/reranker training pipeline. This path determines what examples are loaded, so a wrong mount or stale directory silently changes training behavior and can invalidate evaluation comparisons. Prefer explicit absolute paths and versioned artifacts, and keep schema/format checks near load time (for example JSONL field validation) so bad rows fail early. In multi-environment setups (local, CI, container), treat this as an environment-specific input that must be pinned per run.

    **Links**:
    - [PIPES: Programmatic Pipeline Search for Scalable Data Synthesis and Curation (arXiv 2025)](https://arxiv.org/abs/2509.09512)
    - [Hugging Face Datasets: Load](https://huggingface.co/docs/datasets/loading)
    - [JSON Lines Format](https://jsonlines.org/)
    - [DVC Data Management](https://dvc.org/doc/user-guide/data-management)

??? info "`training.reranker_train_batch` (`RERANKER_TRAIN_BATCH`) — Training Batch Size"
    **Category**: `embedding`

    Number of training examples processed per optimization step during learning-reranker fine-tuning. Larger batches can improve gradient stability and throughput on strong hardware, but they increase memory pressure and can destabilize local/containerized setups if oversized. Smaller batches are safer for constrained environments and can be paired with gradient accumulation to emulate larger effective batch sizes. Tune batch size together with learning rate and sequence length, since all three interact with convergence speed and overfitting risk.

    **Badges**:
    - Lower = safer on Colima

    **Links**:
    - [GraLoRA: Gradient-Driven Low-Rank Adaptation (arXiv 2025)](https://arxiv.org/abs/2505.20355)
    - [GoRA: Gradient-guided LoRA (arXiv 2025)](https://arxiv.org/abs/2502.12171)
    - [PyTorch Optimizer Documentation](https://docs.pytorch.org/docs/stable/optim.html)
    - [Hugging Face PEFT Documentation](https://huggingface.co/docs/peft/index)

??? info "`training.reranker_train_epochs` (`RERANKER_TRAIN_EPOCHS`) — Training Epochs"
    **Category**: `reranking`

    Defines how many full passes over the reranker training dataset are executed. More epochs can improve fit on stable, representative triplets, but excessive epochs on small or noisy data usually reduce generalization and hurt real query performance. Use held-out validation queries and early stopping signals rather than only training loss to choose this value. As your mined data grows or distribution shifts, retune epochs because the optimal point moves with dataset size and difficulty.

    **Badges**:
    - Quality vs overfit

    **Links**:
    - [Sensitivity-LoRA: Hyperparameter Sensitivity (arXiv 2025)](https://arxiv.org/abs/2509.09119)
    - [GraLoRA: Training Stability for LoRA (arXiv 2025)](https://arxiv.org/abs/2505.20355)
    - [Transformers Optimizer & Schedule Docs](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules)
    - [Jina MLX Retrieval Repository](https://github.com/jina-ai/mlx-retrieval)

??? info "`training.reranker_train_lr` (`RERANKER_TRAIN_LR`) — Training Learning Rate"
    **Category**: `reranking`

    Learning rate for reranker fine-tuning updates. It controls update magnitude and is often the highest-impact training hyperparameter: too high causes unstable loss and catastrophic drift, too low undertrains and wastes epochs. Choose LR jointly with batch size, adapter rank, and warmup schedule, and validate using ranking metrics rather than loss alone. For reranker adaptation, conservative starting values with short sweeps are usually safer than aggressive defaults.

    **Badges**:
    - Advanced ML training
    - Requires tuning

    **Links**:
    - [Sensitivity-LoRA: Learning-Rate Sensitivity (arXiv 2025)](https://arxiv.org/abs/2509.09119)
    - [GoRA: Gradient-guided LoRA Optimization (arXiv 2025)](https://arxiv.org/abs/2502.12171)
    - [PyTorch Optimizer Documentation](https://docs.pytorch.org/docs/stable/optim.html)
    - [Transformers Optimizer & Schedule Docs](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules)

??? info "`training.reranker_warmup_ratio` (`RERANKER_WARMUP_RATIO`) — Warmup Ratio"
    **Category**: `reranking`

    `RERANKER_WARMUP_RATIO` defines what fraction of total optimization steps uses a gradual learning-rate ramp before entering the main scheduler phase. In this training stack, warmup protects early updates when the reranker head and backbone are still unstable, reducing gradient spikes and divergence risk that can otherwise corrupt the first checkpoints. Operationally, this value interacts with total step count: short runs need a smaller warmup fraction so useful learning starts early, while longer runs can tolerate a larger warmup to improve stability. Tune it together with batch size and base LR, because warmup that is too short can destabilize training, while warmup that is too long can waste compute on underpowered updates.

    **Badges**:
    - Advanced ML training
    - Stabilizes training

    **Links**:
    - [Warmup-Stable-Decay Learning Rates in Language Model Pre-Training (arXiv)](https://arxiv.org/abs/2602.06797)
    - [Hugging Face Optimizer Schedules (`get_linear_schedule_with_warmup`)](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules#transformers.get_linear_schedule_with_warmup)
    - [Hugging Face `TrainingArguments.warmup_ratio`](https://huggingface.co/docs/transformers/main_classes/trainer#transformers.TrainingArguments.warmup_ratio)
    - [PyTorch `LinearLR` Scheduler](https://pytorch.org/docs/stable/generated/torch.optim.lr_scheduler.LinearLR.html)

??? info "`training.tribrid_reranker_mine_mode` (`TRIBRID_RERANKER_MINE_MODE`) — Triplet Mining Mode"
    **Category**: `general`

    Negative-sampling policy used when generating triplets for reranker training. Random negatives are stable but often weak; semi-hard negatives improve discrimination without overwhelming optimization; hard negatives are highest signal but can inject false negatives and noise if mining quality is low. The right mode depends on corpus ambiguity and label fidelity, so teams typically stage mining as a curriculum (random to semi-hard to hard) with periodic audit sets. Treat this as a data-quality lever first and a model-quality lever second.

    **Badges**:
    - Advanced

    **Links**:
    - [BiCA: Dense Retrieval with Citation-Aware Hard Negatives (arXiv 2025)](https://arxiv.org/abs/2511.08029)
    - [RRRA: Resampling and Reranking through a Retriever Adapter (arXiv 2025)](https://arxiv.org/abs/2508.11670)
    - [SentenceTransformers Utility Functions (including hard-negative mining)](https://www.sbert.net/docs/package_reference/util.html)
    - [SentenceTransformers Losses (Triplet and ranking losses)](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html)

??? info "`training.tribrid_reranker_mine_reset` (`TRIBRID_RERANKER_MINE_RESET`) — Reset Triplets Before Mining"
    **Category**: `general`

    Whether to clear previously mined triplets before a new mining run. Enabling reset gives a clean dataset snapshot and avoids mixing stale and fresh negatives, which is useful for controlled experiments. Disabling reset preserves historical data and can improve coverage, but it also increases the risk of drift and duplicate/noisy samples. Use this setting with explicit dataset versioning so you can reproduce training results and roll back when mining quality drops.

    **Badges**:
    - Destructive

    **Links**:
    - [BiCA: Dense Retrieval with Citation-Aware Hard Negatives (arXiv 2025)](https://arxiv.org/abs/2511.08029)
    - [Hugging Face Datasets: Loading Local JSON/JSONL](https://huggingface.co/docs/datasets/en/loading)
    - [JSON Lines Format Specification](https://jsonlines.org/)
    - [MLflow Tracking (experiment and artifact reproducibility)](https://mlflow.org/docs/latest/tracking.html)

??? info "`training.tribrid_reranker_model_path` (`TRIBRID_RERANKER_MODEL_PATH`) — Reranker Model Path"
    **Category**: `general`

    Root directory of the learning reranker's versioned artifact store, and effectively a deployment control: inference resolves the store's fsynced `ACTIVE.json` pointer to an immutable version directory under `versions/<run_id>/`, so whichever version the pointer names defines live ranking behavior. Promotions publish a new version and switch the pointer atomically (no partial reads during update windows), a crashed promotion is repaired at startup, and the adapter's manifest keeps base-model metadata aligned so a pointer switch cannot silently load incompatible weights.

    **Links**:
    - [RRRA: Resampling and Reranking through a Retriever Adapter (arXiv 2025)](https://arxiv.org/abs/2508.11670)
    - [PEFT Checkpoint Format and Loading](https://huggingface.co/docs/peft/developer_guides/checkpoint)
    - [Transformers from_pretrained() Model Loading](https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.from_pretrained)
    - [Python pathlib (path handling and portability)](https://docs.python.org/3/library/pathlib.html)

??? info "`training.tribrid_triplets_path` (`TRIBRID_TRIPLETS_PATH`) — Triplets Dataset Path"
    **Category**: `general`

    Location of the JSONL triplets corpus used to mine and train the reranker. Because this dataset defines supervision quality, the path should point to a durable, versioned artifact rather than an ad hoc local file. Maintain a consistent schema (query, positive, negative, metadata) and track generation provenance so model regressions can be traced back to specific triplet revisions. In practice, good triplet hygiene often improves ranking quality more than additional training steps.

    **Links**:
    - [BiCA: Dense Retrieval with Citation-Aware Hard Negatives (arXiv 2025)](https://arxiv.org/abs/2511.08029)
    - [SentenceTransformers Losses (Triplet and ranking losses)](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html)
    - [Hugging Face Datasets: Loading Local JSON/JSONL](https://huggingface.co/docs/datasets/en/loading)
    - [JSON Lines Format Specification](https://jsonlines.org/)

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

    Controls how newly mined triplets are persisted to disk: `replace` creates a clean dataset for a reproducible training run, while `append` extends an existing corpus for incremental hard-negative collection. Use `replace` when you want strict experiment comparability, fixed train/validation splits, and clear provenance. Use `append` when your retrieval index, query set, or domain vocabulary is evolving and you intentionally want longitudinal data accumulation. In production retraining pipelines, pair this setting with dataset versioning and a run manifest so you can trace exactly which mined triplets entered each reranker checkpoint.

    **Badges**:
    - Advanced training control
    - Use semi-hard for production

    **Links**:
    - [Reranker Optimization via Geodesic Distances on k-NN Manifolds (arXiv 2026)](https://arxiv.org/abs/2602.15860)
    - [PyTorch TripletMarginLoss](https://pytorch.org/docs/stable/generated/torch.nn.TripletMarginLoss.html)
    - [Sentence-Transformers Loss Functions](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html)
    - [Sentence-Transformers MS MARCO Training Example](https://www.sbert.net/examples/training/ms_marco/README.html)
