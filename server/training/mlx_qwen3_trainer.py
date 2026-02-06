from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar, cast

from server.retrieval.mlx_qwen3 import (
    DEFAULT_TASK_INSTRUCTION,
    MLXQwen3TokenIds,
    PROMPT_TEMPLATE_VERSION,
    apply_lora_layers,
    build_pair_tokens,
    mlx_is_available,
    resolve_yes_no_token_ids,
    write_mlx_manifest,
)
from server.training.reranker_trainer import MaterializedTriplet, _pair_metrics_from_scores


@dataclass(frozen=True)
class LabeledPair:
    query: str
    document: str
    label: int  # 0 or 1


T = TypeVar("T")


def deterministic_split(items: list[T], *, dev_split: float = 0.1, seed: int = 0) -> tuple[list[T], list[T]]:
    r = random.Random(int(seed))
    shuffled = list(items)
    r.shuffle(shuffled)

    ds = float(dev_split)
    ds = max(0.0, min(0.5, ds))
    dev_n = int(round(len(shuffled) * ds))
    dev_n = max(1, dev_n) if len(shuffled) >= 10 else min(dev_n, max(0, len(shuffled) - 1))

    dev = shuffled[:dev_n] if dev_n > 0 else []
    train = shuffled[dev_n:] if dev_n > 0 else shuffled
    if not train:
        train = shuffled
        dev = []
    return (train, dev)


def triplets_to_pairs(
    triplets: list[MaterializedTriplet],
    *,
    negative_ratio: int = 5,
) -> list[LabeledPair]:
    # Product policy: cap generated negatives at 5:1 even if config allows larger.
    nr = int(negative_ratio)
    nr = max(1, min(5, nr))
    out: list[LabeledPair] = []
    r = random.Random(0)
    global_neg_pool = [str(t.negative_text) for t in triplets if str(t.negative_text or "").strip()]

    for t in triplets:
        pos_doc = str(t.positive_text)
        out.append(LabeledPair(query=t.query, document=t.positive_text, label=1))

        negatives: list[str] = []
        mined_neg = str(t.negative_text)
        if mined_neg.strip():
            negatives.append(mined_neg)

        need = max(0, nr - len(negatives))
        if need > 0:
            pool = [x for x in global_neg_pool if x != pos_doc and x not in negatives]
            if pool:
                if len(pool) <= need:
                    negatives.extend(pool)
                else:
                    negatives.extend(r.sample(pool, need))

        # Backstop: if pool is exhausted, duplicate mined negative to honor ratio.
        while negatives and len(negatives) < nr:
            negatives.append(negatives[-1])

        for neg_doc in negatives[:nr]:
            out.append(LabeledPair(query=t.query, document=neg_doc, label=0))
    return out


def _tree_map(fn: Callable[..., Any], tree: Any, *rest: Any) -> Any:
    if isinstance(tree, dict):
        return {k: _tree_map(fn, tree[k], *(r[k] for r in rest)) for k in tree}
    if isinstance(tree, list):
        return [_tree_map(fn, tree[i], *(r[i] for r in rest)) for i in range(len(tree))]
    if isinstance(tree, tuple):
        return tuple(_tree_map(fn, tree[i], *(r[i] for r in rest)) for i in range(len(tree)))
    return fn(tree, *rest)


def accumulate_grads(accumulated: Any | None, grads: Any) -> Any:
    if accumulated is None:
        return grads
    return _tree_map(lambda a, b: a + b, accumulated, grads)


def average_grads(grads: Any, *, steps: int) -> Any:
    s = float(max(1, int(steps)))
    return _tree_map(lambda g: g / s, grads)


def _batch_logits_and_lengths(
    tokenizer: Any,
    model: Any,
    token_ids: MLXQwen3TokenIds,
    *,
    pairs: list[LabeledPair],
    instruction: str,
    max_length: int,
) -> tuple[Any, Any, list[int]]:
    import mlx.core as _mx

    mx: Any = _mx

    token_lists: list[list[int]] = [
        build_pair_tokens(
            tokenizer,
            query=p.query,
            document=p.document,
            instruction=instruction,
            max_length=max_length,
        )
        for p in pairs
    ]
    lengths = [len(toks) for toks in token_lists]
    pad_id = getattr(tokenizer, "pad_token_id", None)
    if pad_id is None or int(pad_id) < 0:
        pad_id = getattr(tokenizer, "eos_token_id", 0)
    if pad_id is None:
        pad_id = 0
    pad_id = int(pad_id)

    max_len = max(lengths) if lengths else 0
    padded = [toks + [pad_id] * (max_len - len(toks)) for toks in token_lists]
    masks = [[1] * len(toks) + [0] * (max_len - len(toks)) for toks in token_lists]
    input_ids = mx.array(padded)
    attention_mask = mx.array(masks)

    try:
        logits = model(input_ids, attention_mask=attention_mask)  # type: ignore[misc]
    except Exception:
        logits = model(input_ids)  # (B, L, V)
    bsz = int(len(pairs))
    idx = mx.arange(bsz)
    pos = mx.array([l - 1 for l in lengths])
    last_logits = logits[idx, pos, :]  # (B, V)

    yes = last_logits[:, int(token_ids.yes_id)]
    no = last_logits[:, int(token_ids.no_id)]
    return (yes, no, lengths)


def _bce_yes_no_loss(yes: Any, no: Any, labels: Any) -> Any:
    """Stable BCE-style loss over (yes,no) logits using logsumexp."""
    import mlx.core as _mx

    mx: Any = _mx

    m = mx.maximum(yes, no)
    log_denom = m + mx.log(mx.exp(yes - m) + mx.exp(no - m))
    # label=1 => log_denom - yes ; label=0 => log_denom - no
    loss = labels * (log_denom - yes) + (1.0 - labels) * (log_denom - no)
    return mx.mean(loss)


def evaluate_mlx_qwen3_reranker(
    *,
    base_model: str,
    adapter_dir: Path,
    triplets: list[MaterializedTriplet],
    max_length: int,
    instruction: str = DEFAULT_TASK_INSTRUCTION,
    lora_rank: int = 16,
    lora_alpha: float = 32.0,
    lora_dropout: float = 0.05,
    lora_target_modules: list[str] | None = None,
) -> dict[str, float]:
    if not mlx_is_available():
        raise RuntimeError("MLX is not available (install mlx + mlx-lm)")

    lora_target_modules = list(
        lora_target_modules or ["q_proj", "k_proj", "v_proj", "o_proj"]
    )

    def _load_and_score() -> dict[str, float]:
        import mlx.core as _mx
        import mlx_lm as _mlx_lm

        mx: Any = _mx
        mlx_load: Any = getattr(_mlx_lm, "load")

        model, tokenizer, *_ = mlx_load(str(base_model))
        model.freeze()
        applied = apply_lora_layers(
            model,
            rank=int(lora_rank),
            alpha=float(lora_alpha),
            dropout=float(lora_dropout),
            target_modules=list(lora_target_modules),
        )
        if int(applied) <= 0:
            raise RuntimeError(
                "LoRA injection applied to 0 modules. "
                "This usually means training.learning_reranker_lora_target_modules does not match the model architecture."
            )

        token_ids = resolve_yes_no_token_ids(tokenizer)

        fp = adapter_dir / "adapter.npz"
        if fp.exists():
            weights = mx.load(str(fp))
            model.load_weights(list(cast(Any, weights).items()), strict=False)

        pos_scores: list[float] = []
        neg_scores: list[float] = []
        for t in triplets:
            pairs = [
                LabeledPair(query=t.query, document=t.positive_text, label=1),
                LabeledPair(query=t.query, document=t.negative_text, label=0),
            ]
            yes, no, _ = _batch_logits_and_lengths(
                tokenizer, model, token_ids, pairs=pairs, instruction=instruction, max_length=int(max_length)
            )
            m = mx.maximum(yes, no)
            log_denom = m + mx.log(mx.exp(yes - m) + mx.exp(no - m))
            score = mx.exp(yes - log_denom)
            mx.eval(score)
            s = [float(x) for x in score.tolist()]
            pos_scores.append(s[0])
            neg_scores.append(s[1])

        return _pair_metrics_from_scores(pos_scores, neg_scores)

    return _load_and_score()


def _evaluate_triplets_current(
    *,
    model: Any,
    tokenizer: Any,
    token_ids: MLXQwen3TokenIds,
    triplets: list[MaterializedTriplet],
    max_length: int,
    instruction: str,
) -> dict[str, float]:
    import mlx.core as _mx

    mx: Any = _mx

    pos_scores: list[float] = []
    neg_scores: list[float] = []
    for t in triplets:
        pairs = [
            LabeledPair(query=t.query, document=t.positive_text, label=1),
            LabeledPair(query=t.query, document=t.negative_text, label=0),
        ]
        yes, no, _ = _batch_logits_and_lengths(
            tokenizer, model, token_ids, pairs=pairs, instruction=instruction, max_length=int(max_length)
        )
        m = mx.maximum(yes, no)
        log_denom = m + mx.log(mx.exp(yes - m) + mx.exp(no - m))
        score = mx.exp(yes - log_denom)
        mx.eval(score)
        s = [float(x) for x in score.tolist()]
        pos_scores.append(s[0])
        neg_scores.append(s[1])

    return _pair_metrics_from_scores(pos_scores, neg_scores)


def train_mlx_qwen3_reranker(
    *,
    run_id: str,
    base_model: str,
    output_dir: Path,
    train_triplets: list[MaterializedTriplet],
    dev_triplets: list[MaterializedTriplet],
    epochs: int,
    batch_size: int,
    gradient_accumulation_steps: int,
    lr: float,
    warmup_ratio: float,
    max_length: int,
    negative_ratio: int = 5,
    seed: int = 0,
    instruction: str = DEFAULT_TASK_INSTRUCTION,
    lora_rank: int = 16,
    lora_alpha: float = 32.0,
    lora_dropout: float = 0.05,
    lora_target_modules: list[str] | None = None,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, object]:
    if not mlx_is_available():
        raise RuntimeError("MLX is not available (install mlx + mlx-lm)")
    if not train_triplets:
        raise ValueError("No training triplets to train on")

    lora_target_modules = list(
        lora_target_modules or ["q_proj", "k_proj", "v_proj", "o_proj"]
    )
    train_pairs = triplets_to_pairs(train_triplets, negative_ratio=int(negative_ratio))

    num_micro_batches = max(1, math.ceil(len(train_pairs) / max(1, int(batch_size))))
    effective_steps_per_epoch = max(1, math.ceil(num_micro_batches / max(1, int(gradient_accumulation_steps))))
    total_steps = int(effective_steps_per_epoch * max(1, int(epochs)))
    warmup_steps = int(total_steps * float(max(0.0, min(1.0, float(warmup_ratio)))))

    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        if emit is None:
            return
        try:
            emit(str(event_type), dict(payload))
        except Exception:
            return

    def _train_sync() -> dict[str, object]:
        import mlx.core as _mx
        import mlx.nn as _nn
        import mlx.optimizers as _optim
        import mlx_lm as _mlx_lm

        mx: Any = _mx
        nn: Any = _nn
        optim: Any = _optim
        mlx_load: Any = getattr(_mlx_lm, "load")

        model, tokenizer, *_ = mlx_load(str(base_model))
        model.freeze()
        applied = apply_lora_layers(
            model,
            rank=int(lora_rank),
            alpha=float(lora_alpha),
            dropout=float(lora_dropout),
            target_modules=list(lora_target_modules),
        )
        if int(applied) <= 0:
            raise RuntimeError(
                "LoRA injection applied to 0 modules. "
                "This usually means training.learning_reranker_lora_target_modules does not match the model architecture."
            )

        try:
            trainable_scalars = 0
            for _, param in model.trainable_parameters():
                try:
                    trainable_scalars += int(param.size)
                except Exception:
                    # Best-effort; avoid blocking training on unexpected param shapes.
                    continue
            _emit(
                "log",
                {
                    "message": (
                        f"MLX LoRA injected into {int(applied)} modules; "
                        f"trainable_scalars≈{int(trainable_scalars):,}; "
                        f"target_modules={list(lora_target_modules)}"
                    )
                },
            )
        except Exception:
            pass

        token_ids = resolve_yes_no_token_ids(tokenizer)

        proj_dirs_1: dict[str, Any] | None = None
        proj_dirs_2: dict[str, Any] | None = None
        w0_dot1: float = 0.0
        w0_dot2: float = 0.0
        prev_x: float = 0.0
        prev_y: float = 0.0

        def _dot_trainable(dirs: dict[str, Any]) -> float:
            total = None
            for name, param in model.trainable_parameters():
                d = dirs.get(str(name))
                if d is None:
                    continue
                s = mx.sum(param * d)
                total = s if total is None else total + s
            if total is None:
                return 0.0
            mx.eval(total)
            return float(total.item())

        def _dirs_norm(dirs: dict[str, Any]) -> float:
            total = None
            for arr in dirs.values():
                s = mx.sum(arr * arr)
                total = s if total is None else total + s
            if total is None:
                return 1.0
            mx.eval(total)
            return float(mx.sqrt(total).item())

        # Deterministic 2D projection telemetry in LoRA parameter space.
        # Uses a fixed random direction basis in LoRA parameter space (seed=0).
        try:
            mx.random.seed(0)
            d1: dict[str, Any] = {}
            d2: dict[str, Any] = {}
            for name, param in model.trainable_parameters():
                nm = str(name)
                d1[nm] = mx.random.normal(param.shape)
                d2[nm] = mx.random.normal(param.shape)

            n1 = max(1e-12, _dirs_norm(d1))
            n2 = max(1e-12, _dirs_norm(d2))
            for k in list(d1.keys()):
                d1[k] = d1[k] / float(n1)
                d2[k] = d2[k] / float(n2)

            proj_dirs_1 = d1
            proj_dirs_2 = d2
            w0_dot1 = _dot_trainable(proj_dirs_1)
            w0_dot2 = _dot_trainable(proj_dirs_2)
        except Exception:
            proj_dirs_1 = None
            proj_dirs_2 = None

        scheduler = optim.schedulers.join_schedules(
            [
                optim.schedulers.linear_schedule(0.0, float(lr), warmup_steps),
                optim.schedulers.cosine_decay(float(lr), max(1, total_steps - warmup_steps)),
            ],
            [warmup_steps],
        )
        optimizer = optim.AdamW(learning_rate=scheduler, weight_decay=0.01)

        def loss_fn(batch: list[LabeledPair]) -> Any:
            yes, no, _ = _batch_logits_and_lengths(
                tokenizer,
                model,
                token_ids,
                pairs=batch,
                instruction=instruction,
                max_length=int(max_length),
            )
            labels = mx.array([float(p.label) for p in batch])
            return _bce_yes_no_loss(yes, no, labels)

        loss_and_grad = nn.value_and_grad(model, loss_fn)

        global_step = 0
        r = random.Random(int(seed))
        accumulated_grads = None
        accumulated_loss = 0.0
        micro_step_in_accum = 0
        samples_in_accum = 0
        effective_step_started = time.perf_counter()

        def _grad_norm(tree: Any) -> float:
            total = None

            def _walk(node: Any) -> None:
                nonlocal total
                if isinstance(node, dict):
                    for v in node.values():
                        _walk(v)
                    return
                if isinstance(node, (list, tuple)):
                    for v in node:
                        _walk(v)
                    return
                s = mx.sum(node * node)
                total = s if total is None else total + s

            _walk(tree)
            if total is None:
                return 0.0
            mx.eval(total)
            return float(mx.sqrt(total).item())

        def _emit_step(
            *,
            epoch_fraction: float,
            avg_loss: float,
            grads_avg: Any,
            sample_count: int,
            step_time_ms: float,
        ) -> None:
            nonlocal prev_x, prev_y
            pct = 100.0 * (global_step / float(max(1, total_steps)))
            grad_n = _grad_norm(grads_avg)
            lr_now = float(lr)

            proj_x = 0.0
            proj_y = 0.0
            if proj_dirs_1 is not None and proj_dirs_2 is not None:
                dot1 = _dot_trainable(proj_dirs_1)
                dot2 = _dot_trainable(proj_dirs_2)
                proj_x = float(dot1 - w0_dot1)
                proj_y = float(dot2 - w0_dot2)
                prev_x = proj_x
                prev_y = proj_y

            _emit(
                "telemetry",
                {
                    "step": int(global_step),
                    "epoch": float(epoch_fraction),
                    "proj_x": float(proj_x),
                    "proj_y": float(proj_y),
                    "loss": float(avg_loss),
                    "lr": float(lr_now),
                    "grad_norm": float(grad_n),
                    "step_time_ms": float(step_time_ms),
                    "sample_count": int(max(0, sample_count)),
                },
            )
            _emit(
                "progress",
                {
                    "step": int(global_step),
                    "epoch": float(epoch_fraction),
                    "percent": float(min(100.0, max(0.0, pct))),
                    "message": f"loss={avg_loss:.4f}",
                    "metrics": {
                        "train_loss": float(avg_loss),
                        "lr": float(lr_now),
                        "grad_norm": float(grad_n),
                    },
                },
            )

        for epoch in range(int(max(1, epochs))):
            indices = list(range(len(train_pairs)))
            r.shuffle(indices)

            for i in range(0, len(indices), max(1, int(batch_size))):
                batch_indices = indices[i : i + max(1, int(batch_size))]
                batch = [train_pairs[j] for j in batch_indices]
                if micro_step_in_accum == 0:
                    effective_step_started = time.perf_counter()
                    samples_in_accum = 0

                loss, grads = loss_and_grad(batch)
                accumulated_grads = accumulate_grads(accumulated_grads, grads)
                accumulated_loss += float(loss.item())
                micro_step_in_accum += 1
                samples_in_accum += int(len(batch))

                if micro_step_in_accum < int(max(1, gradient_accumulation_steps)):
                    continue

                # Apply a single update per effective step (after summing/averaging grads).
                grads_avg = average_grads(accumulated_grads, steps=micro_step_in_accum)
                optimizer.update(model, grads_avg)
                mx.eval(model.parameters(), optimizer.state, loss)

                global_step += 1
                avg_loss = accumulated_loss / float(micro_step_in_accum)
                step_time_ms = float((time.perf_counter() - effective_step_started) * 1000.0)
                accumulated_grads = None
                accumulated_loss = 0.0
                micro_step_in_accum = 0
                _emit_step(
                    epoch_fraction=float(epoch) + (i / float(max(1, len(indices)))),
                    avg_loss=float(avg_loss),
                    grads_avg=grads_avg,
                    sample_count=int(samples_in_accum),
                    step_time_ms=float(step_time_ms),
                )

            # Flush remainder micro-batches at epoch end (if any).
            if micro_step_in_accum > 0 and accumulated_grads is not None:
                grads_avg = average_grads(accumulated_grads, steps=micro_step_in_accum)
                optimizer.update(model, grads_avg)
                mx.eval(model.parameters(), optimizer.state)
                global_step += 1
                avg_loss = accumulated_loss / float(micro_step_in_accum)
                step_time_ms = float((time.perf_counter() - effective_step_started) * 1000.0)
                accumulated_grads = None
                accumulated_loss = 0.0
                _emit_step(
                    epoch_fraction=float(epoch + 1),
                    avg_loss=float(avg_loss),
                    grads_avg=grads_avg,
                    sample_count=int(samples_in_accum),
                    step_time_ms=float(step_time_ms),
                )
                micro_step_in_accum = 0
                samples_in_accum = 0

            # End-of-epoch evaluation on dev triplets (proxy metrics).
            if dev_triplets:
                metrics = _evaluate_triplets_current(
                    model=model,
                    tokenizer=tokenizer,
                    token_ids=token_ids,
                    triplets=dev_triplets,
                    max_length=int(max_length),
                    instruction=str(instruction),
                )
                _emit("metrics", {"step": global_step, "epoch": float(epoch + 1), "metrics": metrics})

        # Save adapter artifact.
        output_dir.mkdir(parents=True, exist_ok=True)
        if proj_dirs_1 is not None and proj_dirs_2 is not None:
            try:
                proj_npz: dict[str, Any] = {}
                for name, arr in proj_dirs_1.items():
                    safe = str(name).replace("/", "_").replace(".", "_")
                    proj_npz[f"d1__{safe}"] = arr
                for name, arr in proj_dirs_2.items():
                    safe = str(name).replace("/", "_").replace(".", "_")
                    proj_npz[f"d2__{safe}"] = arr
                mx.savez(str(output_dir / "projection_dirs.npz"), **proj_npz)
            except Exception:
                pass
        lora_weights: dict[str, Any] = {}
        for name, param in model.trainable_parameters():
            lora_weights[str(name)] = param
        mx.savez(str(output_dir / "adapter.npz"), **lora_weights)

        adapter_cfg = {
            "backend": "mlx_qwen3",
            "base_model": str(base_model),
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "lora_rank": int(lora_rank),
            "lora_alpha": float(lora_alpha),
            "lora_dropout": float(lora_dropout),
            "target_modules": list(lora_target_modules),
            "applied_modules": int(applied),
            "yes_token_id": int(token_ids.yes_id),
            "no_token_id": int(token_ids.no_id),
            "suffix_hash": str(token_ids.suffix_hash),
        }
        import json

        (output_dir / "adapter_config.json").write_text(json.dumps(adapter_cfg, indent=2) + "\n", encoding="utf-8")
        write_mlx_manifest(
            out_dir=output_dir,
            base_model=str(base_model),
            run_id=str(run_id),
            yes_token_id=int(token_ids.yes_id),
            no_token_id=int(token_ids.no_id),
        )

        return {
            "ok": True,
            "backend": "mlx_qwen3",
            "total_steps": int(total_steps),
        }

    return _train_sync()


def train_qwen3_lora_reranker(**kwargs: Any) -> dict[str, object]:
    """Compatibility alias for the MLX Qwen3 LoRA training entrypoint."""
    return train_mlx_qwen3_reranker(**kwargs)
