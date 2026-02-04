#!/usr/bin/env python3
"""
MLX Cross-Encoder Reranker — Trainable on Apple Silicon
========================================================

2026 SOTA approaches for training cross-encoder rerankers natively on MLX:

APPROACH A (Recommended): Qwen3-Reranker + LoRA via mlx_lm
  - Uses Qwen/Qwen3-Reranker-0.6B (or 4B/8B)
  - LLM-based yes/no logit reranking (2025+ SOTA paradigm)
  - LoRA fine-tuning via mlx_lm's built-in training
  - #1 on MTEB multilingual leaderboard
  - Supports 8192 token context, 100+ languages

APPROACH B: Pure MLX Cross-Encoder from scratch
  - BertForSequenceClassification-style architecture in MLX
  - Traditional (query, doc) -> relevance_score paradigm
  - Full control over architecture and training loop
  - Uses ModernBERT or BERT weights as initialization

APPROACH C: jina-ai/mlx-retrieval (Jina's educational framework)
  - LoRA training with InfoNCE/NT-Xent loss
  - Gemma-3-270m base model
  - MTEB eval, W&B integration
  - github.com/jina-ai/mlx-retrieval

This file implements Approaches A and B with full training loops.

Dependencies:
    pip install mlx mlx-lm mlx-data sentencepiece transformers datasets

Author: Built for TriBridRAG / RagWeld
License: MIT
"""

import json
import math
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim

# ═══════════════════════════════════════════════════════════════════════════
# APPROACH A: Qwen3-Reranker + LoRA (Recommended SOTA)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Qwen3RerankerConfig:
    """Configuration for Qwen3-Reranker LoRA fine-tuning."""

    # Model selection — 0.6B fits on 8GB, 4B needs 16GB+, 8B needs 32GB+
    model_name: str = "Qwen/Qwen3-Reranker-0.6B"
    mlx_model_path: Optional[str] = None  # Pre-converted MLX path

    # LoRA hyperparameters
    lora_rank: int = 16
    lora_alpha: float = 32.0
    lora_dropout: float = 0.05
    lora_target_modules: list = field(
        default_factory=lambda: ["q_proj", "v_proj", "k_proj", "o_proj"]
    )

    # Training
    learning_rate: float = 2e-5
    batch_size: int = 4
    gradient_accumulation_steps: int = 8
    num_epochs: int = 3
    warmup_ratio: float = 0.1
    max_length: int = 512  # Per query-doc pair
    weight_decay: float = 0.01

    # Evaluation
    eval_steps: int = 100
    save_steps: int = 500
    eval_metric: str = "ndcg@10"

    # Paths
    adapter_path: str = "./adapters/qwen3-reranker-lora"
    data_path: str = "./train-data.jsonl"

    # Qwen3-Reranker uses yes/no logit comparison
    # The prompt template is critical — this is how Qwen3-Reranker works:
    system_prompt: str = (
        "Judge whether the Document meets the requirements based on the "
        "Query and the Instruct provided. Note that the answer can only "
        'be "yes" or "no".'
    )
    task_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )


class Qwen3RerankerTrainer:
    """
    Fine-tune Qwen3-Reranker on your domain data using LoRA on MLX.

    Qwen3-Reranker is an LLM-based reranker that works by:
    1. Formatting (query, document) as a chat prompt
    2. Generating the first token
    3. Comparing P("yes") vs P("no") as the relevance score

    This is the 2025/2026 SOTA paradigm, outperforming traditional
    cross-encoders on virtually every benchmark.

    Usage:
        config = Qwen3RerankerConfig(model_name="Qwen/Qwen3-Reranker-0.6B")
        trainer = Qwen3RerankerTrainer(config)
        trainer.prepare_model()
        trainer.train(train_data, eval_data)
        trainer.save_adapter()
    """

    def __init__(self, config: Qwen3RerankerConfig):
        self.config = config
        self.model = None
        self.tokenizer = None
        self.token_yes_id = None
        self.token_no_id = None

    def prepare_model(self):
        """Load model and apply LoRA adapters."""
        from mlx_lm import load as mlx_load
        from mlx_lm.tuner.utils import apply_lora_layers

        print(f"Loading {self.config.model_name}...")

        if self.config.mlx_model_path:
            self.model, self.tokenizer = mlx_load(self.config.mlx_model_path)
        else:
            # mlx_lm handles HF download + conversion automatically
            self.model, self.tokenizer = mlx_load(self.config.model_name)

        # Get yes/no token IDs — critical for scoring
        self.token_yes_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.token_no_id = self.tokenizer.convert_tokens_to_ids("no")
        print(f"  yes_token_id={self.token_yes_id}, no_token_id={self.token_no_id}")

        # Apply LoRA
        lora_config = {
            "rank": self.config.lora_rank,
            "alpha": self.config.lora_alpha,
            "dropout": self.config.lora_dropout,
            "scale": self.config.lora_alpha / self.config.lora_rank,
        }

        # Freeze base model, add LoRA to target modules
        self.model.freeze()
        num_lora = 0
        for name, module in self.model.named_modules():
            short_name = name.split(".")[-1]
            if short_name in self.config.lora_target_modules:
                if isinstance(module, nn.Linear):
                    lora_layer = nn.LoRALinear.from_linear(
                        module,
                        r=lora_config["rank"],
                        scale=lora_config["scale"],
                        dropout=lora_config["dropout"],
                    )
                    # Replace in parent
                    parts = name.split(".")
                    parent = self.model
                    for p in parts[:-1]:
                        if p.isdigit():
                            parent = parent[int(p)]
                        else:
                            parent = getattr(parent, p)
                    setattr(parent, parts[-1], lora_layer)
                    num_lora += 1

        trainable = sum(p.size for _, p in self.model.trainable_parameters())
        total = sum(p.size for _, p in self.model.parameters())
        print(f"  LoRA applied to {num_lora} layers")
        print(f"  Trainable: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    def format_pair(self, query: str, document: str, instruction: str = None) -> str:
        """
        Format a (query, document) pair using Qwen3-Reranker's chat template.

        The model expects:
          <|im_start|>system
          {system_prompt}<|im_end|>
          <|im_start|>user
          <Instruct>{instruction}
          <Query>{query}
          <Document>{document}<|im_end|>
          <|im_start|>assistant
          <think>

          </think>

        """
        instruction = instruction or self.config.task_instruction
        text = (
            f"<|im_start|>system\n{self.config.system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n"
            f"<Instruct>{instruction}\n"
            f"<Query>{query}\n"
            f"<Document>{document}<|im_end|>\n"
            f"<|im_start|>assistant\n<think>\n\n</think>\n\n"
        )
        return text

    def score_pair(self, query: str, document: str) -> float:
        """Score a single (query, document) pair. Returns P(yes) / (P(yes) + P(no))."""
        text = self.format_pair(query, document)
        tokens = self.tokenizer.encode(text, add_special_tokens=False)

        # Truncate if needed
        if len(tokens) > self.config.max_length:
            tokens = tokens[: self.config.max_length]

        input_ids = mx.array([tokens])
        logits = self.model(input_ids)  # (1, seq_len, vocab_size)

        # Get logits for the last token position
        last_logits = logits[0, -1, :]  # (vocab_size,)

        # Extract yes/no logits and compute score
        yes_logit = last_logits[self.token_yes_id]
        no_logit = last_logits[self.token_no_id]

        # Softmax over just yes/no
        max_logit = mx.maximum(yes_logit, no_logit)
        yes_exp = mx.exp(yes_logit - max_logit)
        no_exp = mx.exp(no_logit - max_logit)
        score = yes_exp / (yes_exp + no_exp)

        mx.eval(score)
        return score.item()

    def score_batch(self, queries: list[str], documents: list[str]) -> list[float]:
        """Score multiple pairs. Returns list of relevance scores."""
        scores = []
        for q, d in zip(queries, documents):
            scores.append(self.score_pair(q, d))
        return scores

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """
        Rerank documents for a query. Returns sorted list of
        {index, document, score} dicts.
        """
        scores = self.score_batch([query] * len(documents), documents)

        results = [
            {"index": i, "document": doc, "score": s}
            for i, (doc, s) in enumerate(zip(documents, scores))
        ]
        results.sort(key=lambda x: x["score"], reverse=True)

        if top_n:
            results = results[:top_n]
        return results

    def compute_loss(self, batch: list[dict]) -> mx.array:
        """
        Compute binary cross-entropy loss for a batch of labeled pairs.

        Each item in batch: {"query": str, "document": str, "label": 0 or 1}
        """
        total_loss = mx.array(0.0)
        for item in batch:
            text = self.format_pair(item["query"], item["document"])
            tokens = self.tokenizer.encode(text, add_special_tokens=False)
            if len(tokens) > self.config.max_length:
                tokens = tokens[: self.config.max_length]

            input_ids = mx.array([tokens])
            logits = self.model(input_ids)
            last_logits = logits[0, -1, :]

            yes_logit = last_logits[self.token_yes_id]
            no_logit = last_logits[self.token_no_id]

            # Binary cross-entropy: label=1 means "yes" is correct
            log_sum = mx.log(mx.exp(yes_logit) + mx.exp(no_logit))
            label = item["label"]
            if label == 1:
                loss = log_sum - yes_logit
            else:
                loss = log_sum - no_logit

            total_loss = total_loss + loss

        return total_loss / len(batch)

    def train(
        self,
        train_data: list[dict],
        eval_data: Optional[list[dict]] = None,
    ):
        """
        Train the LoRA adapter.

        train_data: list of {"query", "document", "label"} dicts
        eval_data: optional evaluation set in same format
        """
        cfg = self.config

        # Optimizer
        num_steps = (len(train_data) // cfg.batch_size) * cfg.num_epochs
        warmup_steps = int(num_steps * cfg.warmup_ratio)

        scheduler = optim.schedulers.join_schedules(
            [
                optim.schedulers.linear_schedule(0.0, cfg.learning_rate, warmup_steps),
                optim.schedulers.cosine_decay(
                    cfg.learning_rate, num_steps - warmup_steps
                ),
            ],
            [warmup_steps],
        )
        optimizer = optim.AdamW(learning_rate=scheduler, weight_decay=cfg.weight_decay)

        # Value-and-grad function
        loss_and_grad = nn.value_and_grad(self.model, self.compute_loss)

        print(f"\n{'='*60}")
        print(f"Training Qwen3-Reranker LoRA")
        print(f"  Samples: {len(train_data)}")
        print(f"  Batch size: {cfg.batch_size} x {cfg.gradient_accumulation_steps} accum")
        print(f"  Effective batch: {cfg.batch_size * cfg.gradient_accumulation_steps}")
        print(f"  Epochs: {cfg.num_epochs}")
        print(f"  Steps: {num_steps}")
        print(f"  Learning rate: {cfg.learning_rate}")
        print(f"  Warmup: {warmup_steps} steps")
        print(f"{'='*60}\n")

        global_step = 0
        best_metric = 0.0
        accumulated_loss = 0.0

        for epoch in range(cfg.num_epochs):
            # Shuffle training data
            import random

            indices = list(range(len(train_data)))
            random.shuffle(indices)

            epoch_loss = 0.0
            epoch_start = time.time()

            for i in range(0, len(indices), cfg.batch_size):
                batch_indices = indices[i : i + cfg.batch_size]
                batch = [train_data[j] for j in batch_indices]

                loss, grads = loss_and_grad(batch)
                mx.eval(loss)

                accumulated_loss += loss.item()

                # Gradient accumulation
                if (i // cfg.batch_size + 1) % cfg.gradient_accumulation_steps == 0:
                    optimizer.update(self.model, grads)
                    mx.eval(self.model.parameters(), optimizer.state)

                    global_step += 1
                    avg_loss = accumulated_loss / cfg.gradient_accumulation_steps
                    epoch_loss += avg_loss
                    accumulated_loss = 0.0

                    if global_step % 10 == 0:
                        elapsed = time.time() - epoch_start
                        print(
                            f"  [Epoch {epoch+1}/{cfg.num_epochs}] "
                            f"Step {global_step}/{num_steps} | "
                            f"Loss: {avg_loss:.4f} | "
                            f"LR: {scheduler(global_step):.2e} | "
                            f"Time: {elapsed:.1f}s"
                        )

                    # Evaluate
                    if eval_data and global_step % cfg.eval_steps == 0:
                        metric = self._evaluate(eval_data)
                        print(f"  >>> Eval {cfg.eval_metric}: {metric:.4f}")
                        if metric > best_metric:
                            best_metric = metric
                            self.save_adapter(suffix="_best")
                            print(f"  >>> New best! Saved.")

                    # Save checkpoint
                    if global_step % cfg.save_steps == 0:
                        self.save_adapter(suffix=f"_step{global_step}")

            print(
                f"\nEpoch {epoch+1} complete | "
                f"Avg loss: {epoch_loss / max(1, global_step):.4f} | "
                f"Time: {time.time() - epoch_start:.1f}s\n"
            )

        # Final save
        self.save_adapter()
        print(f"\nTraining complete. Best {cfg.eval_metric}: {best_metric:.4f}")

    def _evaluate(self, eval_data: list[dict]) -> float:
        """Quick MRR@10 evaluation on labeled data."""
        from collections import defaultdict

        # Group by query
        query_groups = defaultdict(list)
        for item in eval_data:
            query_groups[item["query"]].append(item)

        mrr_sum = 0.0
        for query, items in query_groups.items():
            # Score all docs for this query
            scored = []
            for item in items:
                score = self.score_pair(query, item["document"])
                scored.append((score, item["label"]))

            # Sort by score descending
            scored.sort(key=lambda x: x[0], reverse=True)

            # Find first relevant doc
            for rank, (score, label) in enumerate(scored[:10], 1):
                if label == 1:
                    mrr_sum += 1.0 / rank
                    break

        return mrr_sum / max(1, len(query_groups))

    def save_adapter(self, suffix: str = ""):
        """Save LoRA adapter weights."""
        path = Path(self.config.adapter_path + suffix)
        path.mkdir(parents=True, exist_ok=True)

        # Collect LoRA weights
        lora_weights = {}
        for name, param in self.model.trainable_parameters():
            lora_weights[name] = param

        mx.savez(str(path / "adapter.npz"), **lora_weights)

        # Save config
        config_dict = {
            "model_name": self.config.model_name,
            "lora_rank": self.config.lora_rank,
            "lora_alpha": self.config.lora_alpha,
            "target_modules": self.config.lora_target_modules,
        }
        with open(path / "adapter_config.json", "w") as f:
            json.dump(config_dict, f, indent=2)

        print(f"  Adapter saved to {path}")

    def load_adapter(self, path: str):
        """Load LoRA adapter weights."""
        weights = mx.load(str(Path(path) / "adapter.npz"))
        self.model.load_weights(list(weights.items()), strict=False)
        print(f"  Adapter loaded from {path}")


# ═══════════════════════════════════════════════════════════════════════════
# APPROACH B: Pure MLX Cross-Encoder (Traditional Architecture)
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class MLXCrossEncoderConfig:
    """Config for a traditional BertForSequenceClassification-style cross-encoder."""

    # Base model — use a small BERT/ModernBERT
    vocab_size: int = 30522
    hidden_size: int = 384
    num_hidden_layers: int = 6
    num_attention_heads: int = 12
    intermediate_size: int = 1536
    max_position_embeddings: int = 512
    num_labels: int = 1  # Regression for relevance scoring
    hidden_dropout: float = 0.1
    attention_dropout: float = 0.1
    layer_norm_eps: float = 1e-12

    # Training
    learning_rate: float = 2e-5
    batch_size: int = 16
    num_epochs: int = 3
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_length: int = 256

    # Paths
    save_path: str = "./models/mlx-cross-encoder"
    pretrained_path: Optional[str] = None  # HF model to init from


class BertEmbeddings(nn.Module):
    """BERT-style embeddings: token + position + type."""

    def __init__(self, config: MLXCrossEncoderConfig):
        super().__init__()
        self.word_embeddings = nn.Embedding(config.vocab_size, config.hidden_size)
        self.position_embeddings = nn.Embedding(
            config.max_position_embeddings, config.hidden_size
        )
        self.token_type_embeddings = nn.Embedding(2, config.hidden_size)
        self.norm = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.dropout = nn.Dropout(config.hidden_dropout)

    def __call__(self, input_ids, token_type_ids=None, position_ids=None):
        B, L = input_ids.shape
        if position_ids is None:
            position_ids = mx.arange(L)
        if token_type_ids is None:
            token_type_ids = mx.zeros_like(input_ids)

        embeddings = (
            self.word_embeddings(input_ids)
            + self.position_embeddings(position_ids)
            + self.token_type_embeddings(token_type_ids)
        )
        return self.dropout(self.norm(embeddings))


class BertSelfAttention(nn.Module):
    """Multi-head self-attention."""

    def __init__(self, config: MLXCrossEncoderConfig):
        super().__init__()
        self.num_heads = config.num_attention_heads
        self.head_dim = config.hidden_size // config.num_attention_heads
        self.scale = self.head_dim**-0.5

        self.query = nn.Linear(config.hidden_size, config.hidden_size)
        self.key = nn.Linear(config.hidden_size, config.hidden_size)
        self.value = nn.Linear(config.hidden_size, config.hidden_size)
        self.out_proj = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.attention_dropout)

    def __call__(self, hidden_states, attention_mask=None):
        B, L, _ = hidden_states.shape

        q = self.query(hidden_states).reshape(B, L, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)
        k = self.key(hidden_states).reshape(B, L, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)
        v = self.value(hidden_states).reshape(B, L, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)

        attn_weights = (q @ k.transpose(0, 1, 3, 2)) * self.scale

        if attention_mask is not None:
            # attention_mask: (B, L) -> (B, 1, 1, L)
            mask = attention_mask[:, None, None, :]
            attn_weights = attn_weights + (1.0 - mask) * (-1e9)

        attn_weights = mx.softmax(attn_weights, axis=-1)
        attn_weights = self.dropout(attn_weights)

        attn_output = (attn_weights @ v).transpose(0, 2, 1, 3).reshape(B, L, -1)
        return self.out_proj(attn_output)


class BertLayer(nn.Module):
    """Single transformer encoder layer."""

    def __init__(self, config: MLXCrossEncoderConfig):
        super().__init__()
        self.attention = BertSelfAttention(config)
        self.norm1 = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.norm2 = nn.LayerNorm(config.hidden_size, eps=config.layer_norm_eps)
        self.ffn = nn.Sequential(
            nn.Linear(config.hidden_size, config.intermediate_size),
            nn.GELU(),
            nn.Linear(config.intermediate_size, config.hidden_size),
        )
        self.dropout1 = nn.Dropout(config.hidden_dropout)
        self.dropout2 = nn.Dropout(config.hidden_dropout)

    def __call__(self, hidden_states, attention_mask=None):
        # Self-attention + residual
        attn_out = self.attention(hidden_states, attention_mask)
        hidden_states = self.norm1(hidden_states + self.dropout1(attn_out))

        # FFN + residual
        ffn_out = self.ffn(hidden_states)
        hidden_states = self.norm2(hidden_states + self.dropout2(ffn_out))

        return hidden_states


class MLXCrossEncoder(nn.Module):
    """
    Traditional cross-encoder: BERT-style encoder + classification head.
    Processes (query, document) pairs and outputs a relevance score.

    Architecture: BertForSequenceClassification
    Input: [CLS] query [SEP] document [SEP]
    Output: scalar relevance score from CLS token

    This is the same architecture as:
    - cross-encoder/ms-marco-MiniLM-L-6-v2
    - BAAI/bge-reranker-base
    - tomaarsen/reranker-ModernBERT-base-gooaq-bce
    """

    def __init__(self, config: MLXCrossEncoderConfig):
        super().__init__()
        self.config = config
        self.embeddings = BertEmbeddings(config)
        self.layers = [BertLayer(config) for _ in range(config.num_hidden_layers)]
        self.classifier = nn.Sequential(
            nn.Linear(config.hidden_size, config.hidden_size),
            nn.Tanh(),
            nn.Linear(config.hidden_size, config.num_labels),
        )

    def __call__(self, input_ids, attention_mask=None, token_type_ids=None):
        hidden = self.embeddings(input_ids, token_type_ids)

        for layer in self.layers:
            hidden = layer(hidden, attention_mask)

        # CLS token pooling
        cls_output = hidden[:, 0, :]  # (B, hidden_size)
        logits = self.classifier(cls_output)  # (B, num_labels)

        return logits

    @classmethod
    def from_pretrained(cls, model_name: str) -> "MLXCrossEncoder":
        """
        Load a HuggingFace cross-encoder and convert weights to MLX.

        Supports: cross-encoder/ms-marco-MiniLM-L-6-v2 and similar BERT-based models.
        """
        from transformers import AutoConfig, AutoModelForSequenceClassification
        import numpy as np

        print(f"Loading {model_name} from HuggingFace...")
        hf_config = AutoConfig.from_pretrained(model_name)

        config = MLXCrossEncoderConfig(
            vocab_size=hf_config.vocab_size,
            hidden_size=hf_config.hidden_size,
            num_hidden_layers=hf_config.num_hidden_layers,
            num_attention_heads=hf_config.num_attention_heads,
            intermediate_size=hf_config.intermediate_size,
            max_position_embeddings=hf_config.max_position_embeddings,
            num_labels=getattr(hf_config, "num_labels", 1),
            hidden_dropout=getattr(hf_config, "hidden_dropout_prob", 0.1),
            attention_dropout=getattr(hf_config, "attention_probs_dropout_prob", 0.1),
            layer_norm_eps=getattr(hf_config, "layer_norm_eps", 1e-12),
        )

        model = cls(config)

        # Load HF weights
        hf_model = AutoModelForSequenceClassification.from_pretrained(model_name)
        hf_state = hf_model.state_dict()

        # Convert PyTorch tensors to MLX arrays
        mlx_weights = {}
        for key, val in hf_state.items():
            np_val = val.detach().cpu().numpy()
            mlx_weights[key] = mx.array(np_val)

        # Map HF weight names to our module structure
        weight_map = cls._build_weight_map(config, mlx_weights)
        model.load_weights(list(weight_map.items()))

        print(f"  Loaded {len(weight_map)} weight tensors")
        return model

    @staticmethod
    def _build_weight_map(config, hf_weights):
        """Map HuggingFace BERT weight names to our MLX module names."""
        mapped = {}

        # Embeddings
        prefix_map = {
            "bert.embeddings.word_embeddings.weight": "embeddings.word_embeddings.weight",
            "bert.embeddings.position_embeddings.weight": "embeddings.position_embeddings.weight",
            "bert.embeddings.token_type_embeddings.weight": "embeddings.token_type_embeddings.weight",
            "bert.embeddings.LayerNorm.weight": "embeddings.norm.weight",
            "bert.embeddings.LayerNorm.bias": "embeddings.norm.bias",
        }

        for hf_name, mlx_name in prefix_map.items():
            if hf_name in hf_weights:
                mapped[mlx_name] = hf_weights[hf_name]

        # Encoder layers
        for i in range(config.num_hidden_layers):
            hf_prefix = f"bert.encoder.layer.{i}"
            mlx_prefix = f"layers.{i}"

            layer_map = {
                f"{hf_prefix}.attention.self.query.weight": f"{mlx_prefix}.attention.query.weight",
                f"{hf_prefix}.attention.self.query.bias": f"{mlx_prefix}.attention.query.bias",
                f"{hf_prefix}.attention.self.key.weight": f"{mlx_prefix}.attention.key.weight",
                f"{hf_prefix}.attention.self.key.bias": f"{mlx_prefix}.attention.key.bias",
                f"{hf_prefix}.attention.self.value.weight": f"{mlx_prefix}.attention.value.weight",
                f"{hf_prefix}.attention.self.value.bias": f"{mlx_prefix}.attention.value.bias",
                f"{hf_prefix}.attention.output.dense.weight": f"{mlx_prefix}.attention.out_proj.weight",
                f"{hf_prefix}.attention.output.dense.bias": f"{mlx_prefix}.attention.out_proj.bias",
                f"{hf_prefix}.attention.output.LayerNorm.weight": f"{mlx_prefix}.norm1.weight",
                f"{hf_prefix}.attention.output.LayerNorm.bias": f"{mlx_prefix}.norm1.bias",
                f"{hf_prefix}.intermediate.dense.weight": f"{mlx_prefix}.ffn.layers.0.weight",
                f"{hf_prefix}.intermediate.dense.bias": f"{mlx_prefix}.ffn.layers.0.bias",
                f"{hf_prefix}.output.dense.weight": f"{mlx_prefix}.ffn.layers.2.weight",
                f"{hf_prefix}.output.dense.bias": f"{mlx_prefix}.ffn.layers.2.bias",
                f"{hf_prefix}.output.LayerNorm.weight": f"{mlx_prefix}.norm2.weight",
                f"{hf_prefix}.output.LayerNorm.bias": f"{mlx_prefix}.norm2.bias",
            }

            for hf_name, mlx_name in layer_map.items():
                if hf_name in hf_weights:
                    mapped[mlx_name] = hf_weights[hf_name]

        # Classifier head
        clf_map = {
            "classifier.weight": "classifier.layers.2.weight",
            "classifier.bias": "classifier.layers.2.bias",
            "bert.pooler.dense.weight": "classifier.layers.0.weight",
            "bert.pooler.dense.bias": "classifier.layers.0.bias",
        }
        for hf_name, mlx_name in clf_map.items():
            if hf_name in hf_weights:
                mapped[mlx_name] = hf_weights[hf_name]

        return mapped


class MLXCrossEncoderTrainer:
    """
    Train a traditional BERT-style cross-encoder in pure MLX.

    Produces a model that maps (query, document) -> relevance_score.
    Uses binary cross-entropy loss with sigmoid activation.

    Usage:
        model = MLXCrossEncoder.from_pretrained("cross-encoder/ms-marco-MiniLM-L-6-v2")
        trainer = MLXCrossEncoderTrainer(model, config)
        trainer.train(train_data, eval_data)
    """

    def __init__(
        self,
        model: MLXCrossEncoder,
        config: MLXCrossEncoderConfig,
        tokenizer=None,
    ):
        self.model = model
        self.config = config

        # Use HF tokenizer
        if tokenizer is None:
            from transformers import AutoTokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                config.pretrained_path or "cross-encoder/ms-marco-MiniLM-L-6-v2"
            )
        else:
            self.tokenizer = tokenizer

    def tokenize_pair(self, query: str, document: str) -> dict:
        """Tokenize a (query, document) pair for the cross-encoder."""
        encoded = self.tokenizer(
            query,
            document,
            max_length=self.config.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="np",
        )
        return {
            "input_ids": mx.array(encoded["input_ids"]),
            "attention_mask": mx.array(encoded["attention_mask"]),
            "token_type_ids": mx.array(encoded.get("token_type_ids", [[0] * self.config.max_length])),
        }

    def tokenize_batch(self, pairs: list[dict]) -> dict:
        """Tokenize a batch of pairs."""
        queries = [p["query"] for p in pairs]
        docs = [p["document"] for p in pairs]
        labels = [p["label"] for p in pairs]

        encoded = self.tokenizer(
            queries,
            docs,
            max_length=self.config.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="np",
        )

        return {
            "input_ids": mx.array(encoded["input_ids"]),
            "attention_mask": mx.array(encoded["attention_mask"]),
            "token_type_ids": mx.array(encoded.get("token_type_ids", [[0] * self.config.max_length] * len(queries))),
            "labels": mx.array(labels, dtype=mx.float32),
        }

    def compute_loss(self, batch_dict: dict) -> mx.array:
        """Binary cross-entropy loss for relevance prediction."""
        logits = self.model(
            batch_dict["input_ids"],
            attention_mask=batch_dict["attention_mask"],
            token_type_ids=batch_dict["token_type_ids"],
        )  # (B, 1)

        logits = logits.squeeze(-1)  # (B,)
        labels = batch_dict["labels"]  # (B,)

        # BCE with logits (numerically stable)
        loss = mx.maximum(logits, mx.zeros_like(logits)) - logits * labels + mx.log(
            1.0 + mx.exp(-mx.abs(logits))
        )
        return mx.mean(loss)

    def score_pair(self, query: str, document: str) -> float:
        """Score a single pair."""
        batch = self.tokenize_pair(query, document)
        logits = self.model(
            batch["input_ids"],
            attention_mask=batch["attention_mask"],
            token_type_ids=batch["token_type_ids"],
        )
        score = mx.sigmoid(logits[0, 0])
        mx.eval(score)
        return score.item()

    def rerank(
        self, query: str, documents: list[str], top_n: Optional[int] = None
    ) -> list[dict]:
        """Rerank documents for a query."""
        scores = [self.score_pair(query, doc) for doc in documents]
        results = [
            {"index": i, "document": doc, "score": s}
            for i, (doc, s) in enumerate(zip(documents, scores))
        ]
        results.sort(key=lambda x: x["score"], reverse=True)
        if top_n:
            results = results[:top_n]
        return results

    def train(
        self,
        train_data: list[dict],
        eval_data: Optional[list[dict]] = None,
    ):
        """
        Full training loop.

        train_data: list of {"query": str, "document": str, "label": float}
        """
        cfg = self.config
        num_batches = math.ceil(len(train_data) / cfg.batch_size)
        total_steps = num_batches * cfg.num_epochs
        warmup_steps = int(total_steps * cfg.warmup_ratio)

        scheduler = optim.schedulers.join_schedules(
            [
                optim.schedulers.linear_schedule(0.0, cfg.learning_rate, warmup_steps),
                optim.schedulers.cosine_decay(
                    cfg.learning_rate, total_steps - warmup_steps
                ),
            ],
            [warmup_steps],
        )
        optimizer = optim.AdamW(learning_rate=scheduler, weight_decay=cfg.weight_decay)

        # Define loss function that takes the model and a batch
        def loss_fn(model, batch_dict):
            logits = model(
                batch_dict["input_ids"],
                attention_mask=batch_dict["attention_mask"],
                token_type_ids=batch_dict["token_type_ids"],
            ).squeeze(-1)
            labels = batch_dict["labels"]
            loss = mx.maximum(logits, mx.zeros_like(logits)) - logits * labels + mx.log(
                1.0 + mx.exp(-mx.abs(logits))
            )
            return mx.mean(loss)

        loss_and_grad = nn.value_and_grad(self.model, loss_fn)

        print(f"\n{'='*60}")
        print(f"Training MLX Cross-Encoder")
        print(f"  Model: {cfg.hidden_size}d, {cfg.num_hidden_layers} layers, {cfg.num_attention_heads} heads")
        print(f"  Samples: {len(train_data)}")
        print(f"  Batch size: {cfg.batch_size}")
        print(f"  Epochs: {cfg.num_epochs}")
        print(f"  Total steps: {total_steps}")
        print(f"  LR: {cfg.learning_rate}")
        total_params = sum(p.size for _, p in self.model.parameters())
        print(f"  Parameters: {total_params:,}")
        print(f"{'='*60}\n")

        global_step = 0
        best_mrr = 0.0

        for epoch in range(cfg.num_epochs):
            import random

            indices = list(range(len(train_data)))
            random.shuffle(indices)

            epoch_loss = 0.0
            epoch_start = time.time()

            for batch_idx in range(num_batches):
                start = batch_idx * cfg.batch_size
                end = min(start + cfg.batch_size, len(indices))
                batch_items = [train_data[indices[j]] for j in range(start, end)]

                if not batch_items:
                    continue

                batch_dict = self.tokenize_batch(batch_items)
                loss, grads = loss_and_grad(batch_dict)

                optimizer.update(self.model, grads)
                mx.eval(self.model.parameters(), optimizer.state, loss)

                global_step += 1
                epoch_loss += loss.item()

                if global_step % 20 == 0:
                    avg_loss = epoch_loss / (batch_idx + 1)
                    elapsed = time.time() - epoch_start
                    samples_per_sec = (batch_idx + 1) * cfg.batch_size / elapsed
                    print(
                        f"  [E{epoch+1}] Step {global_step}/{total_steps} | "
                        f"Loss: {loss.item():.4f} (avg {avg_loss:.4f}) | "
                        f"{samples_per_sec:.0f} samples/s"
                    )

            # End-of-epoch eval
            if eval_data:
                mrr = self._eval_mrr(eval_data)
                print(f"\n  Epoch {epoch+1} | MRR@10: {mrr:.4f}")
                if mrr > best_mrr:
                    best_mrr = mrr
                    self.save(suffix="_best")
                    print(f"  New best! Saved.\n")

        self.save()
        print(f"\nDone. Best MRR@10: {best_mrr:.4f}")

    def _eval_mrr(self, eval_data: list[dict], k: int = 10) -> float:
        """Evaluate MRR@k."""
        from collections import defaultdict

        groups = defaultdict(list)
        for item in eval_data:
            groups[item["query"]].append(item)

        mrr_sum = 0.0
        for query, items in groups.items():
            scored = []
            for item in items:
                s = self.score_pair(query, item["document"])
                scored.append((s, item["label"]))
            scored.sort(key=lambda x: x[0], reverse=True)
            for rank, (_, label) in enumerate(scored[:k], 1):
                if label >= 0.5:
                    mrr_sum += 1.0 / rank
                    break

        return mrr_sum / max(1, len(groups))

    def save(self, suffix: str = ""):
        """Save model weights."""
        path = Path(self.config.save_path + suffix)
        path.mkdir(parents=True, exist_ok=True)
        self.model.save_weights(str(path / "model.safetensors"))

        with open(path / "config.json", "w") as f:
            json.dump(self.config.__dict__, f, indent=2, default=str)
        print(f"  Model saved to {path}")

    def load(self, path: str):
        """Load model weights."""
        self.model.load_weights(str(Path(path) / "model.safetensors"))
        print(f"  Model loaded from {path}")


# ═══════════════════════════════════════════════════════════════════════════
# DATA PREPARATION — Mine triplets from TriBridRAG logs
# ═══════════════════════════════════════════════════════════════════════════


def prepare_training_data_from_tribrid_logs(
    log_path: str = "./reranker_logs.jsonl",
    output_path: str = "./train-data.jsonl",
    negative_ratio: int = 5,
) -> list[dict]:
    """
    Convert TriBridRAG reranker logs into training data.

    Expects logs with:
      {"query": str, "results": [{"text": str, "score": float, "clicked": bool}]}

    Generates positive pairs from clicked/high-score results and
    negative pairs from low-score results.
    """
    import random

    data = []
    with open(log_path) as f:
        for line in f:
            entry = json.loads(line)
            query = entry["query"]
            results = entry.get("results", [])

            positives = [r for r in results if r.get("clicked") or r.get("score", 0) > 0.7]
            negatives = [r for r in results if not r.get("clicked") and r.get("score", 0) < 0.3]

            for pos in positives:
                data.append({
                    "query": query,
                    "document": pos["text"],
                    "label": 1,
                })

                # Sample negatives
                negs = random.sample(negatives, min(negative_ratio, len(negatives)))
                for neg in negs:
                    data.append({
                        "query": query,
                        "document": neg["text"],
                        "label": 0,
                    })

    random.shuffle(data)

    with open(output_path, "w") as f:
        for item in data:
            f.write(json.dumps(item) + "\n")

    print(f"Prepared {len(data)} training pairs ({sum(1 for d in data if d['label']==1)} pos, "
          f"{sum(1 for d in data if d['label']==0)} neg)")
    return data


def generate_synthetic_data(num_queries: int = 100) -> list[dict]:
    """Generate synthetic training data for testing the training pipeline."""
    import random

    topics = [
        ("authentication flow", "OAuth2 token exchange with PKCE", "Database schema migration"),
        ("error handling", "try-catch with retry logic in Python", "CSS grid layout tutorial"),
        ("vector search", "pgvector HNSW index configuration", "React component lifecycle"),
        ("knowledge graph", "Neo4j Cypher query for path finding", "Kubernetes pod scheduling"),
        ("code parsing", "Tree-sitter AST node traversal", "Marketing email templates"),
        ("rate limiting", "Token bucket algorithm implementation", "Photo editing with GIMP"),
        ("caching strategy", "Redis TTL with LRU eviction", "Yoga poses for beginners"),
        ("API design", "REST endpoint versioning best practices", "History of the Roman Empire"),
        ("deployment", "Docker multi-stage build for Python", "Cooking Italian pasta"),
        ("monitoring", "Prometheus alerting rules for latency", "Learning to play guitar"),
    ]

    data = []
    for _ in range(num_queries):
        query, positive, negative = random.choice(topics)
        # Add some variation
        query = query + random.choice(["", " implementation", " best practices", " in production"])

        data.append({"query": query, "document": positive, "label": 1})
        data.append({"query": query, "document": negative, "label": 0})

        # Add more negatives from other topics
        for other_query, _, other_neg in random.sample(topics, 3):
            if other_neg != positive:
                data.append({"query": query, "document": other_neg, "label": 0})

    random.shuffle(data)
    return data


# ═══════════════════════════════════════════════════════════════════════════
# TRIBRIDRAG INTEGRATION ADAPTER
# ═══════════════════════════════════════════════════════════════════════════


class TriBridMLXReranker:
    """
    Drop-in adapter for TriBridRAG's reranker interface.

    Supports both Qwen3-Reranker (approach A) and traditional cross-encoder (approach B).

    Usage in TriBridRAG:
        # In your config:
        RERANKER_MODE=mlx
        MLX_RERANKER_TYPE=qwen3  # or "cross-encoder"
        MLX_RERANKER_MODEL=Qwen/Qwen3-Reranker-0.6B
        MLX_RERANKER_ADAPTER=./adapters/qwen3-reranker-lora

        # In Python:
        reranker = TriBridMLXReranker(
            reranker_type="qwen3",
            model_name="Qwen/Qwen3-Reranker-0.6B",
            adapter_path="./adapters/qwen3-reranker-lora_best",
        )
        results = reranker.rerank(query, candidates, top_n=10)
    """

    def __init__(
        self,
        reranker_type: str = "qwen3",  # "qwen3" or "cross-encoder"
        model_name: str = "Qwen/Qwen3-Reranker-0.6B",
        adapter_path: Optional[str] = None,
        max_length: int = 512,
    ):
        self.reranker_type = reranker_type

        if reranker_type == "qwen3":
            config = Qwen3RerankerConfig(model_name=model_name, max_length=max_length)
            self.backend = Qwen3RerankerTrainer(config)
            self.backend.prepare_model()
            if adapter_path:
                self.backend.load_adapter(adapter_path)
        elif reranker_type == "cross-encoder":
            config = MLXCrossEncoderConfig(pretrained_path=model_name, max_length=max_length)
            self.model = MLXCrossEncoder.from_pretrained(model_name)
            self.backend = MLXCrossEncoderTrainer(self.model, config)
            if adapter_path:
                self.backend.load(adapter_path)
        else:
            raise ValueError(f"Unknown reranker type: {reranker_type}")

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
    ) -> list[dict]:
        """Rerank documents. Returns [{"index", "document", "score"}] sorted by score."""
        return self.backend.rerank(query, documents, top_n=top_n)

    def score(self, query: str, document: str) -> float:
        """Score a single (query, document) pair."""
        return self.backend.score_pair(query, document)

    def score_batch(self, query: str, documents: list[str]) -> list[float]:
        """Score multiple documents against one query."""
        return [self.score(query, doc) for doc in documents]


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MLX Cross-Encoder Reranker")
    parser.add_argument(
        "--approach",
        choices=["qwen3", "cross-encoder", "demo"],
        default="demo",
        help="Which approach to use",
    )
    parser.add_argument("--model", default=None, help="Model name or path")
    parser.add_argument("--train", action="store_true", help="Run training")
    parser.add_argument("--data", default=None, help="Training data path")
    parser.add_argument("--synthetic", action="store_true", help="Generate synthetic data")

    args = parser.parse_args()

    if args.approach == "demo":
        print("=" * 70)
        print("MLX Cross-Encoder Reranker — Demo")
        print("=" * 70)
        print()
        print("Generating synthetic training data...")
        data = generate_synthetic_data(50)
        print(f"  {len(data)} pairs generated")
        print(f"  Sample: {json.dumps(data[0], indent=2)}")
        print()
        print("To train Qwen3-Reranker (recommended):")
        print("  python mlx_cross_encoder.py --approach qwen3 --train --synthetic")
        print()
        print("To train traditional cross-encoder:")
        print("  python mlx_cross_encoder.py --approach cross-encoder --train --synthetic")
        print()
        print("Available base models:")
        print("  Qwen3-Reranker:  Qwen/Qwen3-Reranker-0.6B (SOTA, 0.6B)")
        print("                   Qwen/Qwen3-Reranker-4B   (SOTA, 4B)")
        print("                   Qwen/Qwen3-Reranker-8B   (SOTA, 8B)")
        print("  Cross-Encoder:   cross-encoder/ms-marco-MiniLM-L-6-v2 (fast)")
        print("                   cross-encoder/ms-marco-MiniLM-L-12-v2 (balanced)")
        print("                   BAAI/bge-reranker-v2-m3 (multilingual)")
        print("  MLX-native:      jinaai/jina-reranker-v3-mlx (listwise, 0.6B)")
        print()
        print("For TriBridRAG integration:")
        print("  reranker = TriBridMLXReranker('qwen3', 'Qwen/Qwen3-Reranker-0.6B')")
        print("  results = reranker.rerank('auth flow', documents, top_n=10)")

    elif args.approach == "qwen3":
        model_name = args.model or "Qwen/Qwen3-Reranker-0.6B"
        config = Qwen3RerankerConfig(model_name=model_name)

        if args.train:
            if args.synthetic:
                train_data = generate_synthetic_data(200)
                eval_data = generate_synthetic_data(50)
            elif args.data:
                train_data = [json.loads(l) for l in open(args.data)]
                eval_data = train_data[: len(train_data) // 10]
                train_data = train_data[len(eval_data) :]
            else:
                print("Need --data or --synthetic")
                exit(1)

            trainer = Qwen3RerankerTrainer(config)
            trainer.prepare_model()
            trainer.train(train_data, eval_data)

    elif args.approach == "cross-encoder":
        model_name = args.model or "cross-encoder/ms-marco-MiniLM-L-6-v2"
        config = MLXCrossEncoderConfig(pretrained_path=model_name)

        if args.train:
            model = MLXCrossEncoder.from_pretrained(model_name)
            trainer = MLXCrossEncoderTrainer(model, config)

            if args.synthetic:
                train_data = generate_synthetic_data(200)
                eval_data = generate_synthetic_data(50)
            elif args.data:
                train_data = [json.loads(l) for l in open(args.data)]
                eval_data = train_data[: len(train_data) // 10]
                train_data = train_data[len(eval_data) :]
            else:
                print("Need --data or --synthetic")
                exit(1)

            trainer.train(train_data, eval_data)
