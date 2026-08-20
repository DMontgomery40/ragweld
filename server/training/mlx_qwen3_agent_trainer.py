from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar, cast

from server.retrieval.mlx_qwen3 import apply_lora_layers, mlx_is_available
from server.training.mlx_qwen3_trainer import TrainingCancelledError

T = TypeVar("T")


def deterministic_split(items: list[T], *, dev_split: float = 0.1, seed: int = 0) -> tuple[list[T], list[T]]:
    """Deterministic split that keeps at least 1 dev item when possible."""
    r = random.Random(int(seed))
    shuffled = list(items)
    r.shuffle(shuffled)

    ds = float(dev_split)
    ds = max(0.0, min(0.5, ds))
    dev_n = int(round(len(shuffled) * ds))

    # For agent training we want an eval split whenever the dataset is non-trivial.
    if len(shuffled) >= 2:
        dev_n = max(1, dev_n)
    dev_n = min(dev_n, max(0, len(shuffled) - 1))

    dev = shuffled[:dev_n] if dev_n > 0 else []
    train = shuffled[dev_n:] if dev_n > 0 else shuffled
    if not train:
        train = shuffled
        dev = []
    return (train, dev)


def _iter_trainable_named_params(model: Any) -> Iterable[tuple[str, Any]]:
    """Yield (name, param) from model.trainable_parameters() across MLX API variants."""
    raw = model.trainable_parameters()

    def _flatten(node: Any, path: list[str]) -> Iterable[tuple[str, Any]]:
        if isinstance(node, dict):
            for key, value in node.items():
                yield from _flatten(value, path + [str(key)])
            return
        if isinstance(node, (list, tuple)):
            for idx, value in enumerate(node):
                yield from _flatten(value, path + [str(idx)])
            return
        if hasattr(node, "shape"):
            name = ".".join(path) if path else "param"
            yield (name, node)

    if isinstance(raw, dict):
        yield from _flatten(raw, [])
        return

    for item in raw:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            continue
        param_idx: int | None = None
        for idx in range(len(item) - 1, -1, -1):
            candidate = item[idx]
            if hasattr(candidate, "shape"):
                param_idx = idx
                break
        if param_idx is None:
            continue

        param = item[param_idx]
        name_parts = [str(x) for x in item[:param_idx] if isinstance(x, str) and str(x).strip()]
        name = ".".join(name_parts) if name_parts else str(item[0])
        yield (name, param)


def _tree_map(fn: Callable[..., Any], tree: Any, *rest: Any) -> Any:
    if isinstance(tree, dict):
        return {k: _tree_map(fn, tree[k], *(r[k] for r in rest)) for k in tree}
    if isinstance(tree, list):
        return [_tree_map(fn, tree[i], *(r[i] for r in rest)) for i in range(len(tree))]
    if isinstance(tree, tuple):
        return tuple(_tree_map(fn, tree[i], *(r[i] for r in rest)) for i in range(len(tree)))
    return fn(tree, *rest)


def _tree_leaves(tree: Any) -> list[Any]:
    leaves: list[Any] = []
    if isinstance(tree, dict):
        for value in tree.values():
            leaves.extend(_tree_leaves(value))
        return leaves
    if isinstance(tree, (list, tuple)):
        for value in tree:
            leaves.extend(_tree_leaves(value))
        return leaves
    leaves.append(tree)
    return leaves


def accumulate_grads(accumulated: Any | None, grads: Any) -> Any:
    if accumulated is None:
        return grads
    return _tree_map(lambda a, b: a + b, accumulated, grads)


def average_grads(grads: Any, *, steps: int) -> Any:
    s = float(max(1, int(steps)))
    return _tree_map(lambda g: g / s, grads)


def _token_content_to_text(content: Any) -> str:
    # Support a subset of OpenAI-ish vision message parts by extracting text-only.
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str) and p.strip():
                parts.append(p)
                continue
            if isinstance(p, dict):
                t = p.get("text")
                if isinstance(t, str) and t.strip():
                    parts.append(t)
        return "\n".join(parts)
    return str(content)


@dataclass(frozen=True)
class TokenizedExample:
    input_ids: list[int]  # length L
    target_ids: list[int]  # length L
    target_mask: list[int]  # 0/1 length L (loss computed only where mask=1)


def _tokenize_chatml_example(
    tokenizer: Any,
    *,
    messages: list[dict[str, Any]],
    max_length: int,
) -> TokenizedExample | None:
    """Tokenize chat messages into (input, target, mask) for SFT.

    We build a ChatML-ish transcript and compute loss only on assistant tokens.
    """

    # Build segments so we can mark assistant-only ranges.
    segments: list[tuple[str, bool]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = _token_content_to_text(m.get("content"))
        segments.append((f"<|im_start|>{role}\n", False))
        segments.append((str(content or ""), role == "assistant"))
        segments.append(("<|im_end|>\n", role == "assistant"))

    # Need at least one assistant token to train on.
    if not any(is_target for _txt, is_target in segments):
        return None

    # Incremental encoding so tokenization matches the full concatenated string.
    full = ""
    toks: list[int] = []
    is_asst_token: list[bool] = []
    for txt, target in segments:
        full_next = full + txt
        try:
            encoded = tokenizer.encode(full_next, add_special_tokens=False)
        except TypeError:
            encoded = tokenizer.encode(full_next)
        new = [int(x) for x in encoded[len(toks) :]]
        toks.extend(new)
        is_asst_token.extend([bool(target)] * len(new))
        full = full_next

    if len(toks) < 2:
        return None

    # Truncate from the left (keep the most recent tokens; ensures we keep assistant response tail).
    max_len = int(max(2, max_length))
    if len(toks) > max_len:
        toks = toks[-max_len:]
        is_asst_token = is_asst_token[-max_len:]

    input_ids = toks[:-1]
    target_ids = toks[1:]
    target_mask = [1 if is_asst_token[i + 1] else 0 for i in range(len(target_ids))]
    if sum(target_mask) <= 0:
        return None

    return TokenizedExample(
        input_ids=[int(x) for x in input_ids],
        target_ids=[int(x) for x in target_ids],
        target_mask=[int(x) for x in target_mask],
    )


def _load_adapter_weights_into_model(mx: Any, model: Any, adapter_dir: Path) -> None:
    weights_path = adapter_dir / "adapter.npz"
    if not weights_path.exists():
        return
    weights = mx.load(str(weights_path))
    model.load_weights(list(cast(Any, weights).items()), strict=False)


def evaluate_mlx_qwen3_agent_loss(
    *,
    base_model: str,
    adapter_dir: Path | None,
    messages: list[list[dict[str, Any]]],
    batch_size: int,
    max_length: int,
    lora_rank: int,
    lora_alpha: float,
    lora_dropout: float,
    lora_target_modules: list[str],
    should_stop: Callable[[], bool] | None = None,
) -> float:
    """Evaluate average SFT loss on a dataset (assistant-token masked NLL)."""
    if not mlx_is_available():
        raise RuntimeError("MLX is not available (install mlx + mlx-lm)")

    import mlx.core as _mx
    import mlx_lm as _mlx_lm

    mx: Any = _mx
    mlx_load: Any = _mlx_lm.load

    model, tokenizer, *_ = mlx_load(str(base_model))
    model.freeze()
    apply_lora_layers(
        model,
        rank=int(lora_rank),
        alpha=float(lora_alpha),
        dropout=float(lora_dropout),
        target_modules=[str(x) for x in list(lora_target_modules or ["q_proj", "k_proj", "v_proj", "o_proj"])],
    )
    if adapter_dir is not None:
        _load_adapter_weights_into_model(mx, model, Path(adapter_dir))

    tok: list[TokenizedExample] = []
    for m in messages:
        ex = _tokenize_chatml_example(tokenizer, messages=m, max_length=int(max_length))
        if ex is not None:
            tok.append(ex)
    if not tok:
        return float("nan")

    pad_id = getattr(tokenizer, "pad_token_id", None)
    if pad_id is None or int(pad_id) < 0:
        pad_id = getattr(tokenizer, "eos_token_id", 0)
    pad_id = int(pad_id or 0)

    def _logsumexp(x: Any, axis: int = -1) -> Any:
        lse = getattr(mx, "logsumexp", None)
        if callable(lse):
            return lse(x, axis=axis)
        m = mx.max(x, axis=axis)
        return m + mx.log(mx.sum(mx.exp(x - mx.expand_dims(m, axis=axis)), axis=axis))

    def _gather_last_axis(x: Any, indices: Any) -> Any:
        take_along_axis = getattr(mx, "take_along_axis", None)
        if callable(take_along_axis):
            gathered = take_along_axis(x, mx.expand_dims(indices, axis=-1), axis=-1)
            return gathered[..., 0]
        take = getattr(mx, "take", None)
        if callable(take):
            return take(x, indices, axis=-1)
        raise RuntimeError("MLX gather op unavailable (need mx.take_along_axis or mx.take)")

    total_loss = 0.0
    total_tokens = 0.0
    for i in range(0, len(tok), max(1, int(batch_size))):
        if should_stop is not None and should_stop():
            raise TrainingCancelledError("Training run cancelled")

        batch = tok[i : i + max(1, int(batch_size))]
        max_len = max(len(ex.input_ids) for ex in batch)
        padded_in: list[list[int]] = []
        padded_tgt: list[list[int]] = []
        padded_mask: list[list[float]] = []
        attn: list[list[int]] = []
        for ex in batch:
            seq_len = len(ex.input_ids)
            padded_in.append(ex.input_ids + [pad_id] * (max_len - seq_len))
            padded_tgt.append(ex.target_ids + [pad_id] * (max_len - seq_len))
            padded_mask.append([float(x) for x in ex.target_mask] + [0.0] * (max_len - seq_len))
            attn.append([1] * seq_len + [0] * (max_len - seq_len))

        input_ids = mx.array(padded_in)
        targets = mx.array(padded_tgt)
        mask = mx.array(padded_mask)
        attention_mask = mx.array(attn)

        try:
            logits = model(input_ids, attention_mask=attention_mask)
        except Exception:
            logits = model(input_ids)

        log_denom = _logsumexp(logits, axis=-1)
        tgt_logits = _gather_last_axis(logits, targets)
        nll = log_denom - tgt_logits
        loss_sum = mx.sum(nll * mask)
        tok_sum = mx.sum(mask)
        mx.eval(loss_sum, tok_sum)
        total_loss += float(loss_sum.item())
        total_tokens += float(tok_sum.item())

    if total_tokens <= 0.0:
        return float("nan")
    return float(total_loss / total_tokens)


def train_mlx_qwen3_agent(
    *,
    run_id: str,
    base_model: str,
    output_dir: Path,
    train_messages: list[list[dict[str, Any]]],
    dev_messages: list[list[dict[str, Any]]],
    epochs: int,
    batch_size: int,
    gradient_accumulation_steps: int,
    lr: float,
    warmup_ratio: float,
    max_length: int,
    seed: int = 0,
    lora_rank: int = 16,
    lora_alpha: float = 32.0,
    lora_dropout: float = 0.05,
    lora_target_modules: list[str] | None = None,
    telemetry_interval_steps: int = 2,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, object]:
    """Train a LoRA adapter for a chat-style Qwen3 model (SFT, assistant tokens only)."""
    if not mlx_is_available():
        raise RuntimeError("MLX is not available (install mlx + mlx-lm)")
    if not train_messages:
        raise ValueError("No training examples to train on")

    lora_target_modules = list(lora_target_modules or ["q_proj", "k_proj", "v_proj", "o_proj"])

    num_micro_batches = max(1, math.ceil(len(train_messages) / max(1, int(batch_size))))
    effective_steps_per_epoch = max(1, math.ceil(num_micro_batches / max(1, int(gradient_accumulation_steps))))
    total_steps = int(effective_steps_per_epoch * max(1, int(epochs)))
    warmup_steps = int(total_steps * float(max(0.0, min(1.0, float(warmup_ratio)))))
    telemetry_every = max(1, int(telemetry_interval_steps))

    def _emit(event_type: str, payload: dict[str, Any]) -> None:
        if emit is None:
            return
        try:
            emit(str(event_type), dict(payload))
        except Exception:
            return

    def _train_sync() -> dict[str, object]:
        import json

        import mlx.core as _mx
        import mlx.nn as _nn
        import mlx.optimizers as _optim
        import mlx_lm as _mlx_lm

        mx: Any = _mx
        nn: Any = _nn
        optim: Any = _optim
        mlx_load: Any = _mlx_lm.load

        def _check_cancel() -> None:
            if should_stop is not None and should_stop():
                raise TrainingCancelledError("Training run cancelled")

        model, tokenizer, *_ = mlx_load(str(base_model))

        # Inject LoRA and freeze base weights.
        model.freeze()
        applied = apply_lora_layers(
            model,
            rank=int(lora_rank),
            alpha=float(lora_alpha),
            dropout=float(lora_dropout),
            target_modules=[str(x) for x in list(lora_target_modules)],
        )

        # Pre-tokenize for speed and deterministic truncation.
        tokenized_train: list[TokenizedExample] = []
        for msgs in train_messages:
            ex = _tokenize_chatml_example(tokenizer, messages=msgs, max_length=int(max_length))
            if ex is not None:
                tokenized_train.append(ex)
        tokenized_dev: list[TokenizedExample] = []
        for msgs in dev_messages:
            ex = _tokenize_chatml_example(tokenizer, messages=msgs, max_length=int(max_length))
            if ex is not None:
                tokenized_dev.append(ex)

        if not tokenized_train:
            raise ValueError("No tokenizable training examples (need assistant messages)")

        pad_id = getattr(tokenizer, "pad_token_id", None)
        if pad_id is None or int(pad_id) < 0:
            pad_id = getattr(tokenizer, "eos_token_id", 0)
        pad_id = int(pad_id or 0)

        def _logsumexp(x: Any, axis: int = -1) -> Any:
            lse = getattr(mx, "logsumexp", None)
            if callable(lse):
                return lse(x, axis=axis)
            m = mx.max(x, axis=axis)
            return m + mx.log(mx.sum(mx.exp(x - mx.expand_dims(m, axis=axis)), axis=axis))

        def _gather_last_axis(x: Any, indices: Any) -> Any:
            take_along_axis = getattr(mx, "take_along_axis", None)
            if callable(take_along_axis):
                gathered = take_along_axis(x, mx.expand_dims(indices, axis=-1), axis=-1)
                return gathered[..., 0]
            take = getattr(mx, "take", None)
            if callable(take):
                return take(x, indices, axis=-1)
            raise RuntimeError("MLX gather op unavailable (need mx.take_along_axis or mx.take)")

        def _batch_loss(batch: list[TokenizedExample]) -> Any:
            max_len = max(len(ex.input_ids) for ex in batch)
            padded_in: list[list[int]] = []
            padded_tgt: list[list[int]] = []
            padded_mask: list[list[float]] = []
            attn: list[list[int]] = []
            for ex in batch:
                seq_len = len(ex.input_ids)
                padded_in.append(ex.input_ids + [pad_id] * (max_len - seq_len))
                padded_tgt.append(ex.target_ids + [pad_id] * (max_len - seq_len))
                padded_mask.append([float(x) for x in ex.target_mask] + [0.0] * (max_len - seq_len))
                attn.append([1] * seq_len + [0] * (max_len - seq_len))

            input_ids = mx.array(padded_in)
            targets = mx.array(padded_tgt)
            mask = mx.array(padded_mask)
            attention_mask = mx.array(attn)

            try:
                logits = model(input_ids, attention_mask=attention_mask)
            except Exception:
                logits = model(input_ids)

            log_denom = _logsumexp(logits, axis=-1)
            tgt_logits = _gather_last_axis(logits, targets)
            nll = log_denom - tgt_logits
            loss_sum = mx.sum(nll * mask)
            tok_sum = mx.sum(mask)
            return loss_sum / mx.maximum(tok_sum, mx.array(1.0))

        loss_and_grad = nn.value_and_grad(model, _batch_loss)

        # Projection basis for the neural visualizer.
        proj_dirs_1: dict[str, Any] | None = None
        proj_dirs_2: dict[str, Any] | None = None
        w0_dot1 = 0.0
        w0_dot2 = 0.0
        try:
            d1: dict[str, Any] = {}
            d2: dict[str, Any] = {}
            for name, param in _iter_trainable_named_params(model):
                nm = str(name)
                d1[nm] = mx.random.normal(param.shape)
                d2[nm] = mx.random.normal(param.shape)

            def _dirs_dot(a: dict[str, Any], b: dict[str, Any]) -> float:
                total = None
                for k, va in a.items():
                    vb = b.get(k)
                    if vb is None:
                        continue
                    s = mx.sum(va * vb)
                    total = s if total is None else total + s
                if total is None:
                    return 0.0
                mx.eval(total)
                return float(total.item())

            def _dirs_norm(a: dict[str, Any]) -> float:
                n2 = _dirs_dot(a, a)
                return float(math.sqrt(max(0.0, float(n2))))

            def _orthogonalize(base: dict[str, Any], target: dict[str, Any], eps: float = 1e-12) -> dict[str, Any]:
                denom = float(_dirs_dot(base, base))
                if not math.isfinite(denom) or denom <= float(eps):
                    return dict(target)
                scale = float(_dirs_dot(target, base)) / float(denom)
                out: dict[str, Any] = {}
                for name, value in target.items():
                    base_v = base.get(name)
                    out[name] = value if base_v is None else (value - (base_v * float(scale)))
                return out

            n1 = max(1e-12, _dirs_norm(d1))
            for k in list(d1.keys()):
                d1[k] = d1[k] / float(n1)
            d2 = _orthogonalize(d1, d2)
            n2 = max(1e-12, _dirs_norm(d2))
            for k in list(d2.keys()):
                d2[k] = d2[k] / float(n2)

            proj_dirs_1 = d1
            proj_dirs_2 = d2

            def _dot_trainable(dirs: dict[str, Any]) -> float:
                total = None
                for name, param in _iter_trainable_named_params(model):
                    d = dirs.get(str(name))
                    if d is None:
                        continue
                    s = mx.sum(param * d)
                    total = s if total is None else total + s
                if total is None:
                    return 0.0
                mx.eval(total)
                return float(total.item())

            w0_dot1 = _dot_trainable(d1)
            w0_dot2 = _dot_trainable(d2)
        except Exception:
            proj_dirs_1 = None
            proj_dirs_2 = None

        # Optimizer + schedule.
        # MLX linear_schedule requires steps > 0; allow warmup_ratio=0.0 safely.
        if warmup_steps <= 0:
            scheduler = optim.schedulers.cosine_decay(float(lr), max(1, total_steps))
        elif warmup_steps >= total_steps:
            scheduler = optim.schedulers.linear_schedule(0.0, float(lr), max(1, warmup_steps))
        else:
            scheduler = optim.schedulers.join_schedules(
                [
                    optim.schedulers.linear_schedule(0.0, float(lr), warmup_steps),
                    optim.schedulers.cosine_decay(float(lr), max(1, total_steps - warmup_steps)),
                ],
                [warmup_steps],
            )
        optimizer = optim.AdamW(learning_rate=scheduler, weight_decay=0.01)

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

        def _param_norm() -> float:
            total = None
            for _name, param in _iter_trainable_named_params(model):
                s = mx.sum(param * param)
                total = s if total is None else total + s
            if total is None:
                return 0.0
            mx.eval(total)
            return float(mx.sqrt(total).item())

        def _eval_loss() -> float | None:
            if not tokenized_dev:
                return None
            total_loss = 0.0
            total_tokens = 0.0
            for j in range(0, len(tokenized_dev), max(1, int(batch_size))):
                _check_cancel()
                batch = tokenized_dev[j : j + max(1, int(batch_size))]
                max_len = max(len(ex.input_ids) for ex in batch)
                padded_in: list[list[int]] = []
                padded_tgt: list[list[int]] = []
                padded_mask: list[list[float]] = []
                attn: list[list[int]] = []
                for ex in batch:
                    seq_len = len(ex.input_ids)
                    padded_in.append(ex.input_ids + [pad_id] * (max_len - seq_len))
                    padded_tgt.append(ex.target_ids + [pad_id] * (max_len - seq_len))
                    padded_mask.append([float(x) for x in ex.target_mask] + [0.0] * (max_len - seq_len))
                    attn.append([1] * seq_len + [0] * (max_len - seq_len))

                input_ids = mx.array(padded_in)
                targets = mx.array(padded_tgt)
                mask = mx.array(padded_mask)
                attention_mask = mx.array(attn)

                try:
                    logits = model(input_ids, attention_mask=attention_mask)
                except Exception:
                    logits = model(input_ids)

                log_denom = _logsumexp(logits, axis=-1)
                tgt_logits = _gather_last_axis(logits, targets)
                nll = log_denom - tgt_logits
                loss_sum = mx.sum(nll * mask)
                tok_sum = mx.sum(mask)
                mx.eval(loss_sum, tok_sum)
                total_loss += float(loss_sum.item())
                total_tokens += float(tok_sum.item())

            if total_tokens <= 0.0:
                return None
            return float(total_loss / total_tokens)

        global_step = 0
        r = random.Random(int(seed))
        accumulated_grads = None
        accumulated_loss = 0.0
        micro_step_in_accum = 0
        samples_in_accum = 0
        effective_step_started = time.perf_counter()

        def _emit_step(*, epoch_fraction: float, avg_loss: float, grads_avg: Any, sample_count: int, step_time_ms: float) -> None:
            pct = 100.0 * (global_step / float(max(1, total_steps)))
            grad_n = _grad_norm(grads_avg)
            lr_now = float(lr)
            param_n = _param_norm()
            update_n = float(lr_now) * float(grad_n)  # approximate (AdamW)

            proj_x = 0.0
            proj_y = 0.0
            if proj_dirs_1 is not None and proj_dirs_2 is not None:
                try:
                    total1 = None
                    total2 = None
                    for name, param in _iter_trainable_named_params(model):
                        d1 = proj_dirs_1.get(str(name))
                        d2 = proj_dirs_2.get(str(name))
                        if d1 is not None:
                            s1 = mx.sum(param * d1)
                            total1 = s1 if total1 is None else total1 + s1
                        if d2 is not None:
                            s2 = mx.sum(param * d2)
                            total2 = s2 if total2 is None else total2 + s2
                    if total1 is not None and total2 is not None:
                        mx.eval(total1, total2)
                        proj_x = float(total1.item()) - float(w0_dot1)
                        proj_y = float(total2.item()) - float(w0_dot2)
                except Exception:
                    proj_x = 0.0
                    proj_y = 0.0

            should_emit_telemetry = bool(
                global_step == 1 or global_step >= total_steps or global_step % telemetry_every == 0
            )
            if should_emit_telemetry:
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
                        "param_norm": float(param_n),
                        "update_norm": float(update_n),
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
            _check_cancel()
            indices = list(range(len(tokenized_train)))
            r.shuffle(indices)

            for i in range(0, len(indices), max(1, int(batch_size))):
                _check_cancel()
                batch_indices = indices[i : i + max(1, int(batch_size))]
                batch = [tokenized_train[j] for j in batch_indices]

                if micro_step_in_accum == 0:
                    effective_step_started = time.perf_counter()
                    samples_in_accum = 0

                loss, grads = loss_and_grad(batch)
                mx.eval(loss)
                grad_leaves = _tree_leaves(grads)
                if grad_leaves:
                    mx.eval(*grad_leaves)

                accumulated_grads = accumulate_grads(accumulated_grads, grads)
                accum_leaves = _tree_leaves(accumulated_grads)
                if accum_leaves:
                    mx.eval(*accum_leaves)

                accumulated_loss += float(loss.item())
                micro_step_in_accum += 1
                samples_in_accum += int(len(batch))

                if micro_step_in_accum < int(max(1, gradient_accumulation_steps)):
                    continue

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
                micro_step_in_accum = 0
                _emit_step(
                    epoch_fraction=float(epoch + 1),
                    avg_loss=float(avg_loss),
                    grads_avg=grads_avg,
                    sample_count=int(samples_in_accum),
                    step_time_ms=float(step_time_ms),
                )
                samples_in_accum = 0

            # End-of-epoch evaluation on dev set.
            ev = _eval_loss()
            if ev is not None and math.isfinite(float(ev)):
                _emit("metrics", {"step": int(global_step), "epoch": float(epoch + 1), "metrics": {"eval_loss": float(ev)}})

        # Save adapter artifact.
        _check_cancel()
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
        for name, param in _iter_trainable_named_params(model):
            lora_weights[str(name)] = param
        mx.savez(str(output_dir / "adapter.npz"), **lora_weights)

        adapter_cfg = {
            "backend": "mlx_qwen3",
            "artifact_kind": "ragweld_agent",
            "base_model": str(base_model),
            "run_id": str(run_id),
            "lora_rank": int(lora_rank),
            "lora_alpha": float(lora_alpha),
            "lora_dropout": float(lora_dropout),
            "target_modules": list(lora_target_modules),
            "applied_modules": int(applied),
        }
        (output_dir / "adapter_config.json").write_text(json.dumps(adapter_cfg, indent=2) + "\n", encoding="utf-8")

        manifest = {
            "backend": "mlx_qwen3",
            "artifact_kind": "ragweld_agent",
            "base_model": str(base_model),
            "run_id": str(run_id),
            "created_at": int(time.time()),
        }
        (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        return {"ok": True, "backend": "mlx_qwen3", "total_steps": int(total_steps)}

    return _train_sync()
