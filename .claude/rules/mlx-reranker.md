---
paths:
  - "server/reranker/**/*.py"
  - "server/training/**/*.py"
---

# MLX Learning Reranker

> Local `main` is canonical: no legacy fallback backends or transition-period dual paths in touched slices.

Fine-tunable Qwen3 LoRA learning reranker running locally via MLX on Apple Silicon.

## Architecture
- **Inference**: `server/reranker/mlx_qwen3.py` — MLXQwen3Reranker class with hot-reload + idle unload
- **Training**: `server/training/mlx_qwen3_trainer.py` — LoRA fine-tuning with gradient accumulation
- **Artifacts**: `server/reranker/artifacts.py` — Backend detection (transformers vs MLX)

## Key Config Fields (TrainingConfig)

| Field | Default | Purpose |
|-------|---------|---------|
| `learning_reranker_backend` | "auto" | auto/transformers/mlx_qwen3 |
| `learning_reranker_base_model` | "Qwen/Qwen3-Reranker-0.6B" | HuggingFace model |
| `learning_reranker_lora_rank` | 16 | LoRA rank (r) |
| `learning_reranker_lora_alpha` | 32.0 | LoRA scaling |
| `learning_reranker_grad_accum_steps` | 8 | Gradient accumulation |
| `learning_reranker_promote_if_improves` | 1 | Auto-promote on improvement |

## APIs
- `POST /api/reranker/score` — Debug scoring endpoint
- `POST /api/reranker/train/run/{run_id}/promote` — Promote trained adapter
