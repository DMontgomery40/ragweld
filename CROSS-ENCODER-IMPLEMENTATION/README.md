# MLX Cross-Encoder Reranker for Apple Silicon

**Trainable, SOTA, native MLX — built for TriBridRAG**

---

## 2026 Landscape: What Actually Exists

After deep research, here's the honest state of trainable cross-encoder rerankers on MLX:

### The Three Viable Paths

| Approach | Repo / Model | Architecture | Training | Quality | License |
|----------|-------------|--------------|----------|---------|---------|
| **A. Qwen3-Reranker + LoRA** ⭐ | `Qwen/Qwen3-Reranker-0.6B` | LLM-based yes/no logit | LoRA via mlx_lm | **SOTA** (#1 MTEB) | Apache 2.0 |
| **B. Pure MLX Cross-Encoder** | This repo + HF weights | BertForSeqClassification | Full params or LoRA | Good (proven arch) | MIT |
| **C. Jina mlx-retrieval** | `jina-ai/mlx-retrieval` | Gemma-3 + LoRA embedding | LoRA, InfoNCE loss | Excellent (Jina) | Apache 2.0 |

### Also notable but not primary:

| Option | What it is | Status |
|--------|-----------|--------|
| `jinaai/jina-reranker-v3-mlx` | 0.6B listwise reranker, native MLX port | **Inference only**, no training. 61.94 nDCG@10 on BEIR. CC-BY-NC-4.0. |
| `pappitti/modernbert-mlx` | ModernBERT in MLX with `ModelForSequenceClassification` | Experimental training, MIT. 20 stars. Needs work. |
| PyTorch MPS fallback | sentence-transformers `CrossEncoderTrainer` on Apple MPS | Mature pipeline, not native MLX. Works today. |
| `ToluClassics/mlx-transformers` | BERT/RoBERTa/XLM-R in MLX | Inference benchmarked, training not demonstrated. |

---

## Recommendation: Approach A (Qwen3-Reranker + LoRA)

**Why this wins for TriBridRAG:**

1. **SOTA quality** — Qwen3 Reranker-8B is #1 on MTEB multilingual. The 0.6B version is competitive with models 4× its size.

2. **The paradigm shifted** — The 2025/2026 SOTA for reranking is LLM-based, not traditional cross-encoder. Instead of `BERT([CLS] query [SEP] doc) → score`, you format it as:
   ```
   System: Judge if Document meets Query requirements. Answer yes/no.
   User: <Query>... <Document>...
   Assistant: <think></think> yes
   ```
   Then compare `P("yes")` vs `P("no")` as the relevance score. This approach captures far richer semantic understanding than a 6-layer BERT.

3. **LoRA trains fast on Apple Silicon** — mlx_lm's LoRA infrastructure is battle-tested. 0.6B trains at 4000-5000 tok/sec on M3 Ultra, ~800-1200 tok/sec on M2 Pro/Max.

4. **Fits your existing architecture** — TriBridRAG already has `RERANKER_MODE` with local/cloud/learning/none. Adding `mlx` mode slots in cleanly.

5. **Domain adaptation is the key value** — You're not training from scratch. You're taking a SOTA base and fine-tuning on your users' actual query-result interaction patterns.

---

## How Qwen3-Reranker Actually Works

Unlike traditional cross-encoders (BertForSequenceClassification), Qwen3-Reranker is a **causal language model** that's been fine-tuned for binary relevance judgments:

```python
# Traditional cross-encoder:
tokenize("[CLS] query [SEP] document [SEP]")
→ BERT encoder → CLS pooling → linear head → score

# Qwen3-Reranker (2025+ SOTA):
format_as_chat(system="Judge relevance...", user="<Query>...<Document>...")
→ Qwen3 decoder → get logits for next token
→ score = softmax(logit["yes"], logit["no"])["yes"]
```

The key insight: the LLM's reasoning capability (even in the 0.6B model) produces much better relevance judgments than a shallow encoder.

---

## Quick Start

### Install dependencies

```bash
pip install mlx mlx-lm sentencepiece transformers datasets
```

### Option 1: Use pre-trained Qwen3-Reranker (no training)

```python
from mlx_cross_encoder import TriBridMLXReranker

reranker = TriBridMLXReranker(
    reranker_type="qwen3",
    model_name="Qwen/Qwen3-Reranker-0.6B",
)

results = reranker.rerank(
    query="authentication token exchange flow",
    documents=[
        "OAuth2 PKCE flow exchanges authorization code for access token",
        "CSS grid layout provides two-dimensional positioning",
        "JWT tokens are signed with HMAC-SHA256 for API auth",
    ],
    top_n=2,
)

for r in results:
    print(f"  [{r['score']:.4f}] {r['document'][:80]}")
```

### Option 2: Fine-tune on your domain data

```python
from mlx_cross_encoder import Qwen3RerankerConfig, Qwen3RerankerTrainer

config = Qwen3RerankerConfig(
    model_name="Qwen/Qwen3-Reranker-0.6B",
    lora_rank=16,
    batch_size=4,
    gradient_accumulation_steps=8,
    num_epochs=3,
    learning_rate=2e-5,
)

trainer = Qwen3RerankerTrainer(config)
trainer.prepare_model()

# Your data: [{"query": str, "document": str, "label": 0 or 1}]
train_data = [...]
eval_data = [...]

trainer.train(train_data, eval_data)
trainer.save_adapter()
```

### Option 3: Traditional cross-encoder in pure MLX

```python
from mlx_cross_encoder import MLXCrossEncoder, MLXCrossEncoderTrainer, MLXCrossEncoderConfig

# Load HuggingFace weights directly into MLX
model = MLXCrossEncoder.from_pretrained("cross-encoder/ms-marco-MiniLM-L-6-v2")
config = MLXCrossEncoderConfig(pretrained_path="cross-encoder/ms-marco-MiniLM-L-6-v2")
trainer = MLXCrossEncoderTrainer(model, config)

# Train
trainer.train(train_data, eval_data)

# Score
score = trainer.score_pair("auth flow", "OAuth2 token exchange")
```

---

## TriBridRAG Integration

### New reranker mode: `mlx`

Add to your config:

```env
RERANKER_MODE=mlx
MLX_RERANKER_TYPE=qwen3
MLX_RERANKER_MODEL=Qwen/Qwen3-Reranker-0.6B
MLX_RERANKER_ADAPTER=./adapters/qwen3-reranker-lora_best
MLX_RERANKER_MAX_LENGTH=512
```

### Integration with existing learning reranker pipeline

The existing TriBridRAG learning reranker mines triplets from query logs and trains a `cross-encoder/ms-marco-MiniLM-L-6-v2` base model. The MLX reranker extends this:

1. **Same triplet mining** — Keep your existing `mineTriplets()` pipeline
2. **Convert triplets to pairs** — Each (query, positive, negative) → 2 labeled pairs
3. **Train MLX reranker** — Use `Qwen3RerankerTrainer` or `MLXCrossEncoderTrainer`
4. **Inference on Apple Silicon** — Native Metal GPU, no PyTorch overhead

### Memory requirements by model

| Model | Params | FP16 Memory | 4-bit Memory | Min Mac |
|-------|--------|-------------|-------------|---------|
| Qwen3-Reranker-0.6B | 600M | ~1.2 GB | ~400 MB | M1 8GB |
| Qwen3-Reranker-4B | 4B | ~8 GB | ~2.5 GB | M2 Pro 16GB |
| Qwen3-Reranker-8B | 8B | ~16 GB | ~5 GB | M2 Max 32GB |
| ms-marco-MiniLM-L-6-v2 | 22M | ~90 MB | N/A | M1 8GB |
| ms-marco-MiniLM-L-12-v2 | 33M | ~130 MB | N/A | M1 8GB |
| bge-reranker-v2-m3 | 568M | ~1.1 GB | N/A | M1 8GB |

---

## Also Worth Knowing

### jina-ai/mlx-retrieval

Jina's educational framework for training embedding + reranker models on MLX. Uses Gemma-3-270m with LoRA. Has proper InfoNCE loss, gradient accumulation, MTEB eval, W&B integration. 166 stars, Apache 2.0.

```bash
git lfs install
git clone https://github.com/jina-ai/mlx-retrieval.git
cd mlx-retrieval
uv venv -p 3.12 && source .venv/bin/activate
uv pip install -r requirements.txt

python train.py \
    --model gemma-3-270m-mlx \
    --batch-size 256 \
    --gradient-accumulation-steps 16 \
    --steps 2000 \
    --eval-tasks NanoMSMARCORetrieval
```

### jina-reranker-v3-mlx (inference only)

Native MLX port of Jina's SOTA listwise reranker. 0.6B params, 61.94 nDCG@10 on BEIR. Processes up to 64 documents simultaneously.

```python
# pip install jina-reranker-v3-mlx (or clone from HF)
from rerank import MLXReranker
reranker = MLXReranker()
results = reranker.rerank(query, documents)
```

### ModernBERT on MLX (pappitti/modernbert-mlx)

Has `ModelForSequenceClassification` which IS cross-encoder architecture. Training is experimental but the model loads and runs. MIT license. Could be the foundation for a lightweight traditional cross-encoder if you want to avoid the LLM-based approach.

---

## Architecture Decision: Why Not Just Use PyTorch MPS?

You could run `sentence-transformers CrossEncoderTrainer` on Apple MPS today. It works. Tom Aarsen's blog post shows training `ModernBERT-base` rerankers in 30 minutes on RTX 3090 — MPS would be 2-3x slower but functional.

**The case for native MLX:**
- 2-5x faster inference than PyTorch MPS on Apple Silicon
- Zero-copy unified memory (no CPU↔GPU transfers)
- MLX's lazy evaluation + operation fusion reduces kernel launch overhead
- M5 Neural Accelerators provide additional 4x speedup (macOS 26.2+)
- Better integration with the Apple Silicon ecosystem long-term

**The case for PyTorch MPS fallback:**
- Mature training pipeline (CrossEncoderTrainer handles everything)
- Proven evaluation (NanoBEIR, CrossEncoderRerankingEvaluator)
- Broader model support
- Then convert trained model to MLX for inference

**Pragmatic recommendation:** Start with Approach A (Qwen3 + MLX LoRA) for training AND inference. Fall back to PyTorch MPS training + MLX inference conversion if you hit issues.

---

## Files

```
mlx_cross_encoder.py    — Full implementation (training + inference + integration)
README.md               — This file
```

## References

- [Qwen3 Embedding paper](https://arxiv.org/abs/2506.05176)
- [jina-ai/mlx-retrieval](https://github.com/jina-ai/mlx-retrieval)
- [jina-reranker-v3-mlx](https://huggingface.co/jinaai/jina-reranker-v3-mlx)
- [ModernBERT-MLX](https://github.com/pappitti/modernbert-mlx)
- [sentence-transformers CrossEncoder training](https://huggingface.co/blog/train-reranker)
- [MLX documentation](https://ml-explore.github.io/mlx/)
- [WWDC25: Get started with MLX](https://developer.apple.com/videos/play/wwdc2025/315/)
- [WWDC25: LLMs on Apple Silicon with MLX](https://developer.apple.com/videos/play/wwdc2025/298/)
