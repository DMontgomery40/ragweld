from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


def mlx_is_available() -> bool:
    try:
        import mlx  # noqa: F401
        import mlx_lm  # noqa: F401

        return True
    except Exception:
        return False


SYSTEM_PROMPT: str = (
    "Judge whether the Document meets the requirements based on the "
    "Query and the Instruct provided. Note that the answer can only "
    'be "yes" or "no".'
)

DEFAULT_TASK_INSTRUCTION: str = "Given a web search query, retrieve relevant passages that answer the query"

PREFIX: str = f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n"

# NOTE: Suffix must match the actual inference prompt prefix for the first generated token.
SUFFIX: str = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

PROMPT_TEMPLATE_VERSION: str = "mlx_qwen3_v1"


def _suffix_hash() -> str:
    return hashlib.sha256(SUFFIX.encode("utf-8")).hexdigest()


def _adapter_fingerprint(adapter_dir: Path) -> tuple[int, int] | None:
    p = adapter_dir / "adapter.npz"
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def _json_load(path: Path) -> dict[str, Any]:
    import json

    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return cast(dict[str, Any], obj)


def _json_dump(path: Path, obj: Any) -> None:
    import json

    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class MLXQwen3TokenIds:
    yes_id: int
    no_id: int
    suffix_hash: str


def resolve_yes_no_token_ids(tokenizer: Any) -> MLXQwen3TokenIds:
    yes_tokens = tokenizer.encode(SUFFIX + "yes", add_special_tokens=False)
    no_tokens = tokenizer.encode(SUFFIX + "no", add_special_tokens=False)
    if not yes_tokens or not no_tokens:
        raise ValueError("Failed to resolve yes/no token ids: tokenizer returned empty token sequence")

    yes_id = int(yes_tokens[-1])
    no_id = int(no_tokens[-1])
    if yes_id == no_id:
        raise ValueError(f"Failed to resolve yes/no token ids: yes_id == no_id == {yes_id}")

    special_ids: set[int] = set()
    for attr in ("all_special_ids", "special_ids"):
        ids = getattr(tokenizer, attr, None)
        if ids:
            try:
                special_ids.update(int(x) for x in list(ids))
            except Exception:
                pass
    if yes_id in special_ids or no_id in special_ids:
        raise ValueError(
            "Failed to resolve yes/no token ids: resolved to a special token. "
            f"yes_id={yes_id} no_id={no_id} specials={sorted(special_ids)[:20]}"
        )

    return MLXQwen3TokenIds(yes_id=yes_id, no_id=no_id, suffix_hash=_suffix_hash())


def apply_lora_layers(
    model: Any,
    *,
    rank: int,
    alpha: float,
    dropout: float,
    target_modules: list[str],
) -> int:
    """Inject trainable LoRA adapters into a loaded MLX model.

    Notes:
    - We intentionally do NOT depend on `mlx.nn.LoRALinear` (not available in all MLX versions).
    - This wrapper works with plain `mlx.nn.Linear` modules by adding low-rank matrices A/B.
    """
    import mlx.core as _mx
    import mlx.nn as _nn

    mx: Any = _mx
    nn: Any = _nn

    target_set = set(str(x).strip() for x in (target_modules or []) if str(x).strip())
    if not target_set:
        return 0

    class _LoRALinear(nn.Module):  # type: ignore[misc]
        def __init__(self, base: Any, *, r: int, scale: float, dropout_p: float) -> None:
            super().__init__()
            self.base = base
            self.r = int(r)
            self.scale = float(scale)
            self.dropout = nn.Dropout(float(dropout_p)) if float(dropout_p) > 0.0 else None

            try:
                out_dim, in_dim = int(base.weight.shape[0]), int(base.weight.shape[1])
            except Exception as e:
                raise ValueError(f"Cannot infer Linear dims for LoRA injection (missing base.weight.shape): {e}") from e

            # Standard LoRA init: A ~ N(0, 0.01), B = 0
            self.lora_A = mx.random.normal((self.r, in_dim)) * 0.01
            self.lora_B = mx.zeros((out_dim, self.r))

        def __call__(self, x: Any) -> Any:  # noqa: D401
            y = self.base(x)
            z = x if self.dropout is None else self.dropout(x)
            # (B, in) @ (r, in)^T => (B, r) ; then @ (out, r)^T => (B, out)
            lora = (z @ self.lora_A.T) @ self.lora_B.T
            return y + (lora * self.scale)

    scale = float(alpha) / float(max(1, int(rank)))
    num_wrapped = 0

    # Snapshot names up-front; we mutate modules during iteration.
    try:
        named = list(model.named_modules())
    except Exception:
        named = []

    for name, module in named:
        short = str(name).split(".")[-1]
        if short not in target_set:
            continue
        if isinstance(module, _LoRALinear):
            continue
        if not isinstance(module, (nn.Linear, getattr(nn, "QuantizedLinear", nn.Linear))):
            continue

        lora_layer = _LoRALinear(module, r=int(rank), scale=float(scale), dropout_p=float(dropout))

        parts = str(name).split(".")
        parent = model
        for part in parts[:-1]:
            if part.isdigit():
                parent = parent[int(part)]
            else:
                parent = getattr(parent, part)
        setattr(parent, parts[-1], lora_layer)
        num_wrapped += 1

    return int(num_wrapped)


def build_pair_tokens(
    tokenizer: Any,
    *,
    query: str,
    document: str,
    instruction: str,
    max_length: int,
) -> list[int]:
    prefix_tokens: list[int] = [int(x) for x in tokenizer.encode(PREFIX, add_special_tokens=False)]
    suffix_tokens: list[int] = [int(x) for x in tokenizer.encode(SUFFIX, add_special_tokens=False)]

    payload_prefix = f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: "
    payload_prefix_tokens: list[int] = [int(x) for x in tokenizer.encode(payload_prefix, add_special_tokens=False)]
    doc_tokens: list[int] = [int(x) for x in tokenizer.encode(str(document or ""), add_special_tokens=False)]

    budget = int(max_length) - len(prefix_tokens) - len(payload_prefix_tokens) - len(suffix_tokens)
    if budget < 0:
        # We still must preserve suffix. If the static prompt parts exceed max_length, fail loudly.
        raise ValueError(
            "max_length too small for prompt template. "
            f"max_length={max_length} static_len={len(prefix_tokens)+len(payload_prefix_tokens)+len(suffix_tokens)}"
        )

    if len(doc_tokens) > budget:
        doc_tokens = doc_tokens[:budget]

    return prefix_tokens + payload_prefix_tokens + doc_tokens + suffix_tokens


def _score_pairs_sync(
    model: Any,
    tokenizer: Any,
    token_ids: MLXQwen3TokenIds,
    *,
    pairs: list[tuple[str, str]],
    instruction: str,
    max_length: int,
    include_logits: bool,
) -> tuple[list[float], list[float | None], list[float | None]]:
    import mlx.core as _mx

    mx: Any = _mx

    # Tokenize
    token_lists: list[list[int]] = [
        build_pair_tokens(
            tokenizer,
            query=q,
            document=d,
            instruction=instruction,
            max_length=max_length,
        )
        for (q, d) in pairs
    ]
    lengths = [len(toks) for toks in token_lists]
    if not lengths:
        return ([], [], [])

    pad_id = getattr(tokenizer, "pad_token_id", None)
    if pad_id is None or int(pad_id) < 0:
        pad_id = getattr(tokenizer, "eos_token_id", 0)
    if pad_id is None:
        pad_id = 0
    pad_id = int(pad_id)

    max_len = max(lengths)
    padded = [toks + [pad_id] * (max_len - len(toks)) for toks in token_lists]
    attn_masks = [[1] * len(toks) + [0] * (max_len - len(toks)) for toks in token_lists]
    input_ids = mx.array(padded)
    attention_mask = mx.array(attn_masks)

    # Keep compatibility with mlx_lm model call signatures that may not expose
    # attention_mask. We still construct the mask to avoid left/right padding bugs.
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

    # Stable logsumexp for 2 logits.
    m = mx.maximum(yes, no)
    log_denom = m + mx.log(mx.exp(yes - m) + mx.exp(no - m))
    score = mx.exp(yes - log_denom)

    if include_logits:
        mx.eval(score, yes, no)
        scores = [float(x) for x in score.tolist()]
        yes_out = cast(list[float | None], [float(x) for x in yes.tolist()])
        no_out = cast(list[float | None], [float(x) for x in no.tolist()])
        return (scores, yes_out, no_out)

    mx.eval(score)
    scores = [float(x) for x in score.tolist()]
    return (scores, [None] * len(scores), [None] * len(scores))


class MLXQwen3Reranker:
    """MLX Qwen3 learning reranker (LoRA adapter) with hot reload + idle unload."""

    def __init__(
        self,
        *,
        base_model: str,
        adapter_dir: str,
        lora_rank: int,
        lora_alpha: float,
        lora_dropout: float,
        lora_target_modules: list[str],
    ) -> None:
        self._base_model = str(base_model).strip()
        self._adapter_dir = str(adapter_dir).strip()
        self._lora_rank = int(lora_rank)
        self._lora_alpha = float(lora_alpha)
        self._lora_dropout = float(lora_dropout)
        self._lora_target_modules = list(lora_target_modules)

        self._lock = asyncio.Lock()
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._token_ids: MLXQwen3TokenIds | None = None
        self._adapter_fp: tuple[int, int] | None = None
        self._last_reload_check_mono: float = 0.0

        self._in_use: int = 0
        self._last_used_mono: float = 0.0
        self._unload_after_sec: int = 0
        self._unload_generation: int = 0

    async def score_pairs_batched(
        self,
        pairs: list[tuple[str, str]],
        *,
        instruction: str = DEFAULT_TASK_INSTRUCTION,
        max_length: int = 512,
        include_logits: bool = False,
        reload_on_change: bool = False,
        reload_period_sec: int = 60,
        unload_after_sec: int = 0,
    ) -> tuple[list[float], list[float | None], list[float | None]]:
        if not pairs:
            return ([], [], [])

        self._unload_after_sec = int(unload_after_sec or 0)

        async with self._lock:
            await self._ensure_loaded_locked()
            await self._maybe_reload_adapter_locked(
                reload_on_change=bool(reload_on_change),
                reload_period_sec=int(reload_period_sec or 0),
            )
            model = self._model
            tokenizer = self._tokenizer
            token_ids = self._token_ids
            if model is None or tokenizer is None or token_ids is None:
                raise RuntimeError("MLX Qwen3 reranker not loaded")
            self._in_use += 1
            self._last_used_mono = time.monotonic()
            self._unload_generation += 1
            unload_generation = self._unload_generation

        try:
            return await asyncio.to_thread(
                _score_pairs_sync,
                model,
                tokenizer,
                token_ids,
                pairs=list(pairs),
                instruction=str(instruction or DEFAULT_TASK_INSTRUCTION),
                max_length=int(max_length),
                include_logits=bool(include_logits),
            )
        finally:
            async with self._lock:
                self._in_use = max(0, self._in_use - 1)
                self._last_used_mono = time.monotonic()
                self._schedule_idle_unload_locked(unload_generation=unload_generation)

    async def _ensure_loaded_locked(self) -> None:
        if self._model is not None and self._tokenizer is not None and self._token_ids is not None:
            return

        if not mlx_is_available():
            raise RuntimeError("MLX is not available (install mlx + mlx-lm)")

        base_model = self._base_model
        adapter_dir = Path(self._adapter_dir)
        lora_rank = self._lora_rank
        lora_alpha = self._lora_alpha
        lora_dropout = self._lora_dropout
        lora_target_modules = list(self._lora_target_modules)

        def _load() -> tuple[Any, Any, MLXQwen3TokenIds, tuple[int, int] | None]:
            import mlx.core as _mx
            import mlx_lm as _mlx_lm

            mx: Any = _mx
            mlx_load: Any = getattr(_mlx_lm, "load")

            model, tokenizer, *_ = mlx_load(base_model)
            # Apply LoRA once (the adapter weights will fill in trainable params).
            if not bool(getattr(model, "_tribrid_lora_applied", False)):
                model.freeze()
                apply_lora_layers(
                    model,
                    rank=lora_rank,
                    alpha=lora_alpha,
                    dropout=lora_dropout,
                    target_modules=lora_target_modules,
                )
                setattr(model, "_tribrid_lora_applied", True)

            token_ids = resolve_yes_no_token_ids(tokenizer)

            fp = _adapter_fingerprint(adapter_dir)
            if fp is not None:
                weights = mx.load(str(adapter_dir / "adapter.npz"))
                model.load_weights(list(cast(Any, weights).items()), strict=False)

            return (model, tokenizer, token_ids, fp)

        model, tokenizer, token_ids, fp = await asyncio.to_thread(_load)
        self._model = model
        self._tokenizer = tokenizer
        self._token_ids = token_ids
        self._adapter_fp = fp
        self._last_reload_check_mono = time.monotonic()

    async def _maybe_reload_adapter_locked(self, *, reload_on_change: bool, reload_period_sec: int) -> None:
        if not reload_on_change:
            return

        model = self._model
        tokenizer = self._tokenizer
        if model is None or tokenizer is None:
            return

        now = time.monotonic()
        period = float(max(1, int(reload_period_sec or 0)))
        if (now - self._last_reload_check_mono) < period:
            return
        self._last_reload_check_mono = now

        adapter_dir = Path(self._adapter_dir)
        new_fp = _adapter_fingerprint(adapter_dir)
        if new_fp == self._adapter_fp:
            return

        def _reload() -> tuple[tuple[int, int] | None, MLXQwen3TokenIds]:
            import mlx.core as _mx

            mx: Any = _mx

            token_ids = resolve_yes_no_token_ids(tokenizer)
            if new_fp is None:
                # Adapter missing; keep LoRA layers but effectively revert to base weights.
                return (None, token_ids)
            weights = mx.load(str(adapter_dir / "adapter.npz"))
            model.load_weights(list(cast(Any, weights).items()), strict=False)
            return (new_fp, token_ids)

        fp, token_ids = await asyncio.to_thread(_reload)
        self._adapter_fp = fp
        self._token_ids = token_ids

    def _schedule_idle_unload_locked(self, *, unload_generation: int) -> None:
        sec = int(self._unload_after_sec or 0)
        if sec <= 0:
            return

        async def _task() -> None:
            await asyncio.sleep(sec)
            async with self._lock:
                if unload_generation != self._unload_generation:
                    return
                if self._in_use > 0:
                    return
                if (time.monotonic() - float(self._last_used_mono)) < float(sec):
                    return
                self._model = None
                self._tokenizer = None
                self._token_ids = None
                self._adapter_fp = None

        asyncio.create_task(_task())


_MLX_CACHE_LOCK = asyncio.Lock()
_MLX_CACHE: dict[tuple[str, str, int, float, float, tuple[str, ...]], MLXQwen3Reranker] = {}


async def clear_mlx_qwen3_cache(adapter_dir: str | None = None) -> None:
    """Clear in-process MLX reranker cache.

    If adapter_dir is set, only entries for that adapter path are removed.
    """
    target = str(adapter_dir or "").strip()
    async with _MLX_CACHE_LOCK:
        if not target:
            _MLX_CACHE.clear()
            return
        keys = [k for k in _MLX_CACHE.keys() if str(k[1]) == target]
        for key in keys:
            _MLX_CACHE.pop(key, None)


async def get_mlx_qwen3_reranker(
    *,
    base_model: str,
    adapter_dir: str,
    lora_rank: int,
    lora_alpha: float,
    lora_dropout: float,
    lora_target_modules: list[str],
) -> MLXQwen3Reranker:
    key = (
        str(base_model).strip(),
        str(adapter_dir).strip(),
        int(lora_rank),
        float(lora_alpha),
        float(lora_dropout),
        tuple(str(x) for x in list(lora_target_modules)),
    )
    async with _MLX_CACHE_LOCK:
        cached = _MLX_CACHE.get(key)
        if cached is not None:
            return cached
        rr = MLXQwen3Reranker(
            base_model=key[0],
            adapter_dir=key[1],
            lora_rank=key[2],
            lora_alpha=key[3],
            lora_dropout=key[4],
            lora_target_modules=list(key[5]),
        )
        _MLX_CACHE[key] = rr
        return rr


def write_mlx_manifest(
    *,
    out_dir: Path,
    base_model: str,
    run_id: str,
    yes_token_id: int,
    no_token_id: int,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "tribrid_reranker_manifest.json"
    obj = {
        "backend": "mlx_qwen3",
        "base_model": str(base_model),
        "run_id": str(run_id),
        "created_at": int(time.time()),
        "prompt_template_version": PROMPT_TEMPLATE_VERSION,
        "yes_token_id": int(yes_token_id),
        "no_token_id": int(no_token_id),
        "suffix_hash": _suffix_hash(),
    }
    _json_dump(path, obj)


def read_manifest_backend(active_dir: Path) -> str | None:
    obj = read_manifest(active_dir)
    backend = (obj or {}).get("backend")
    if isinstance(backend, str) and backend.strip():
        return backend.strip()
    return None


def read_manifest(active_dir: Path) -> dict[str, Any] | None:
    path = active_dir / "tribrid_reranker_manifest.json"
    try:
        obj = _json_load(path)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def read_adapter_config(active_dir: Path) -> dict[str, Any] | None:
    """Read MLX LoRA adapter config emitted by training (best-effort)."""
    path = active_dir / "adapter_config.json"
    try:
        obj = _json_load(path)
    except FileNotFoundError:
        return None
    except Exception:
        return None
    if isinstance(obj, dict):
        return obj
    return None


def is_mlx_qwen3_artifact_compatible(*, artifact_dir: Path, base_model: str) -> bool:
    """Return True if artifact_dir looks like a compatible MLX Qwen3 adapter artifact."""
    manifest = read_manifest(artifact_dir) or {}
    backend = str(manifest.get("backend") or "").strip()
    if backend != "mlx_qwen3":
        return False
    manifest_base = str(manifest.get("base_model") or "").strip()
    if manifest_base and manifest_base != str(base_model).strip():
        return False
    return True
