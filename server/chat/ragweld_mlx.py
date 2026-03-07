from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from server.retrieval.mlx_qwen3 import apply_lora_layers, mlx_is_available

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve_path(path_str: str) -> Path:
    p = Path(str(path_str or "")).expanduser()
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def _adapter_fingerprint(adapter_dir: Path) -> tuple[int, int] | None:
    p = adapter_dir / "adapter.npz"
    try:
        st = p.stat()
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return (int(st.st_mtime_ns), int(st.st_size))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _read_adapter_config(adapter_dir: Path) -> dict[str, Any] | None:
    return _read_json(adapter_dir / "adapter_config.json")


def _safe_messages_for_chat_template(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize OpenAI-ish message dicts into HF chat-template friendly shape."""
    out: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        if role not in {"system", "user", "assistant"}:
            continue
        content = m.get("content")
        # Generation pipeline already rejects images for ragweld; keep a strict string-only prompt here.
        if isinstance(content, str):
            out.append({"role": role, "content": content})
        else:
            out.append({"role": role, "content": str(content)})
    return out


def _build_prompt(tokenizer: Any, messages: list[dict[str, Any]]) -> str:
    safe_msgs = _safe_messages_for_chat_template(messages)
    # Prefer tokenizer chat template when available (model-specific, future-proof).
    apply_chat_template = getattr(tokenizer, "apply_chat_template", None)
    if callable(apply_chat_template):
        try:
            return cast(
                str,
                apply_chat_template(
                    safe_msgs,
                    tokenize=False,
                    add_generation_prompt=True,
                ),
            )
        except Exception:
            pass

    # Safe fallback: ChatML-ish prompt.
    system = ""
    user = ""
    for m in safe_msgs:
        if m["role"] == "system" and not system:
            system = str(m.get("content") or "")
        if m["role"] == "user":
            user = str(m.get("content") or "")
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def _generate_sync(*, model: Any, tokenizer: Any, prompt: str, temperature: float, max_tokens: int) -> str:
    import mlx_lm as _mlx_lm

    gen = getattr(_mlx_lm, "generate", None)
    if not callable(gen):
        raise RuntimeError("mlx_lm.generate is unavailable")

    # mlx-lm has changed kwarg names across versions; try a few.
    try:
        out = gen(model, tokenizer, prompt, max_tokens=int(max_tokens), temp=float(temperature), verbose=False)
    except TypeError:
        try:
            out = gen(model, tokenizer, prompt, max_tokens=int(max_tokens), temperature=float(temperature), verbose=False)
        except TypeError:
            out = gen(model, tokenizer, prompt, max_tokens=int(max_tokens))

    if isinstance(out, str):
        text = out
    elif isinstance(out, dict) and isinstance(out.get("text"), str):
        text = str(out["text"])
    else:
        text = str(out)

    # Some mlx-lm variants return prompt+completion; strip prompt prefix if present.
    if text.startswith(prompt):
        text = text[len(prompt) :]
    return text


def _stream_worker(
    *,
    model: Any,
    tokenizer: Any,
    prompt: str,
    temperature: float,
    max_tokens: int,
    loop: asyncio.AbstractEventLoop,
    out_q: asyncio.Queue[str | None],
    err_out: list[BaseException],
) -> None:
    """Run mlx-lm stream_generate in a background thread and push deltas into an asyncio queue."""
    try:
        import mlx_lm as _mlx_lm

        stream_generate = getattr(_mlx_lm, "stream_generate", None)
        if not callable(stream_generate):
            raise RuntimeError("mlx_lm.stream_generate is unavailable")

        try:
            it = stream_generate(model, tokenizer, prompt, max_tokens=int(max_tokens), temp=float(temperature))
        except TypeError:
            try:
                it = stream_generate(model, tokenizer, prompt, max_tokens=int(max_tokens), temperature=float(temperature))
            except TypeError:
                it = stream_generate(model, tokenizer, prompt, max_tokens=int(max_tokens))

        for resp in it:
            t = getattr(resp, "text", None)
            if isinstance(t, str) and t:
                loop.call_soon_threadsafe(out_q.put_nowait, t)
            else:
                s = str(resp)
                if s:
                    loop.call_soon_threadsafe(out_q.put_nowait, s)
    except BaseException as e:
        err_out.append(e)
    finally:
        loop.call_soon_threadsafe(out_q.put_nowait, None)


@dataclass
class _Loaded:
    model: Any
    tokenizer: Any
    adapter_fp: tuple[int, int] | None
    last_reload_check_mono: float
    unload_generation: int


class RagweldMLXChatModel:
    """In-process MLX chat model with LoRA adapter hot-reload + idle unload."""

    def __init__(self, *, base_model: str, adapter_dir: str) -> None:
        self._base_model = str(base_model).strip()
        self._adapter_dir = str(adapter_dir).strip()

        self._lock = asyncio.Lock()
        self._loaded: _Loaded | None = None
        self._in_use: int = 0
        self._last_used_mono: float = 0.0
        self._idle_unload_task: asyncio.Task[None] | None = None

    async def generate(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        reload_period_sec: int,
        unload_after_sec: int,
    ) -> str:
        async with self._lock:
            loaded = await self._ensure_loaded_locked()
            await self._maybe_reload_adapter_locked(
                loaded=loaded,
                reload_period_sec=int(reload_period_sec or 0),
            )
            self._in_use += 1
            self._last_used_mono = time.monotonic()
            loaded.unload_generation += 1
            unload_generation = int(loaded.unload_generation)

            model = loaded.model
            tokenizer = loaded.tokenizer

        try:
            prompt = _build_prompt(tokenizer, messages)
            return await asyncio.to_thread(
                _generate_sync,
                model=model,
                tokenizer=tokenizer,
                prompt=prompt,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
            )
        finally:
            async with self._lock:
                self._in_use = max(0, self._in_use - 1)
                self._last_used_mono = time.monotonic()
                self._schedule_idle_unload_locked(
                    unload_after_sec=int(unload_after_sec or 0),
                    unload_generation=unload_generation,
                )

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        reload_period_sec: int,
        unload_after_sec: int,
    ) -> AsyncIterator[str]:
        async with self._lock:
            loaded = await self._ensure_loaded_locked()
            await self._maybe_reload_adapter_locked(
                loaded=loaded,
                reload_period_sec=int(reload_period_sec or 0),
            )
            self._in_use += 1
            self._last_used_mono = time.monotonic()
            loaded.unload_generation += 1
            unload_generation = int(loaded.unload_generation)

            model = loaded.model
            tokenizer = loaded.tokenizer

        try:
            prompt = _build_prompt(tokenizer, messages)
            loop = asyncio.get_running_loop()
            out_q: asyncio.Queue[str | None] = asyncio.Queue()
            err_out: list[BaseException] = []

            # Use a dedicated thread so we can yield deltas as they are produced.
            import threading

            t = threading.Thread(
                target=_stream_worker,
                kwargs={
                    "model": model,
                    "tokenizer": tokenizer,
                    "prompt": prompt,
                    "temperature": float(temperature),
                    "max_tokens": int(max_tokens),
                    "loop": loop,
                    "out_q": out_q,
                    "err_out": err_out,
                },
                daemon=True,
            )
            t.start()

            while True:
                item = await out_q.get()
                if item is None:
                    break
                if item:
                    yield item

            if err_out:
                raise RuntimeError(str(err_out[0]))
        finally:
            async with self._lock:
                self._in_use = max(0, self._in_use - 1)
                self._last_used_mono = time.monotonic()
                self._schedule_idle_unload_locked(
                    unload_after_sec=int(unload_after_sec or 0),
                    unload_generation=unload_generation,
                )

    async def _ensure_loaded_locked(self) -> _Loaded:
        loaded = self._loaded
        if loaded is not None:
            return loaded

        if not mlx_is_available():
            raise RuntimeError("MLX is not available (install mlx + mlx-lm)")

        base_model = self._base_model
        adapter_dir = _resolve_path(self._adapter_dir)

        def _load() -> tuple[Any, Any, tuple[int, int] | None]:
            import mlx.core as _mx
            import mlx_lm as _mlx_lm

            mx: Any = _mx
            mlx_load = _mlx_lm.load

            model, tokenizer, *_ = mlx_load(str(base_model))

            # Apply LoRA layers (needed even for base-only mode so adapter weights can load later).
            if not bool(getattr(model, "_ragweld_lora_applied", False)):
                cfg = _read_adapter_config(adapter_dir) or {}
                rank = int(cfg.get("lora_rank") or 16)
                alpha = float(cfg.get("lora_alpha") or 32.0)
                dropout = float(cfg.get("lora_dropout") or 0.05)
                targets = cfg.get("target_modules")
                if not isinstance(targets, list) or not targets:
                    targets = ["q_proj", "k_proj", "v_proj", "o_proj"]

                model.freeze()
                apply_lora_layers(
                    model,
                    rank=int(rank),
                    alpha=float(alpha),
                    dropout=float(dropout),
                    target_modules=[str(x) for x in list(targets)],
                )
                model._ragweld_lora_applied = True

            fp = _adapter_fingerprint(adapter_dir)
            if fp is not None:
                weights = mx.load(str(adapter_dir / "adapter.npz"))
                model.load_weights(list(cast(Any, weights).items()), strict=False)

            return (model, tokenizer, fp)

        model, tokenizer, fp = await asyncio.to_thread(_load)
        loaded = _Loaded(
            model=model,
            tokenizer=tokenizer,
            adapter_fp=fp,
            last_reload_check_mono=time.monotonic(),
            unload_generation=0,
        )
        self._loaded = loaded
        return loaded

    async def _maybe_reload_adapter_locked(self, *, loaded: _Loaded, reload_period_sec: int) -> None:
        adapter_dir = _resolve_path(self._adapter_dir)
        new_fp = _adapter_fingerprint(adapter_dir)
        now = time.monotonic()
        period = int(reload_period_sec or 0)

        # Always reload immediately when the adapter changes (mtime/size fingerprint).
        if new_fp != loaded.adapter_fp:
            loaded.last_reload_check_mono = now

            # If the adapter disappeared, fully unload so the next request reloads base weights.
            if new_fp is None and loaded.adapter_fp is not None:
                self._loaded = None
                return

            def _reload_changed() -> tuple[int, int] | None:
                import mlx.core as _mx

                mx: Any = _mx
                if new_fp is None:
                    return None
                weights = mx.load(str(adapter_dir / "adapter.npz"))
                loaded.model.load_weights(list(cast(Any, weights).items()), strict=False)
                return new_fp

            fp = await asyncio.to_thread(_reload_changed)
            loaded.adapter_fp = fp
            return

        # No fingerprint change; optionally force a reload on a fixed cadence.
        if period <= 0:
            return
        if (now - float(loaded.last_reload_check_mono)) < float(period):
            return
        loaded.last_reload_check_mono = now
        if new_fp is None:
            return

        def _reload_forced() -> tuple[int, int] | None:
            import mlx.core as _mx

            mx: Any = _mx
            weights = mx.load(str(adapter_dir / "adapter.npz"))
            loaded.model.load_weights(list(cast(Any, weights).items()), strict=False)
            return new_fp

        fp = await asyncio.to_thread(_reload_forced)
        loaded.adapter_fp = fp

    def _schedule_idle_unload_locked(self, *, unload_after_sec: int, unload_generation: int) -> None:
        sec = int(unload_after_sec or 0)
        if sec <= 0:
            return

        prev = self._idle_unload_task
        if prev is not None and not prev.done():
            prev.cancel()

        async def _task() -> None:
            await asyncio.sleep(sec)
            async with self._lock:
                loaded = self._loaded
                if loaded is None:
                    return
                if unload_generation != int(loaded.unload_generation):
                    return
                if self._in_use > 0:
                    return
                if (time.monotonic() - float(self._last_used_mono)) < float(sec):
                    return
                self._loaded = None

        self._idle_unload_task = asyncio.create_task(_task())


_CACHE_LOCK = asyncio.Lock()
_CACHE: dict[tuple[str, str], RagweldMLXChatModel] = {}


async def get_ragweld_chat_model(*, base_model: str, adapter_dir: str) -> RagweldMLXChatModel:
    key = (str(base_model).strip(), str(adapter_dir).strip())
    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        m = RagweldMLXChatModel(base_model=key[0], adapter_dir=key[1])
        _CACHE[key] = m
        return m


async def clear_cache(adapter_dir: str | None = None) -> None:
    target = str(adapter_dir or "").strip()
    async with _CACHE_LOCK:
        if not target:
            _CACHE.clear()
            return
        keys = [k for k in _CACHE.keys() if str(k[1]) == target]
        for k in keys:
            _CACHE.pop(k, None)


async def generate(
    *,
    model_id: str,
    backend: str,
    base_model: str,
    adapter_dir: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    reload_period_sec: int,
    unload_after_sec: int,
) -> tuple[str, str | None]:
    _ = model_id
    be = str(backend or "").strip().lower() or "mlx_qwen3"
    if be != "mlx_qwen3":
        raise RuntimeError(f"Unsupported ragweld backend: {backend}")

    m = await get_ragweld_chat_model(base_model=str(base_model), adapter_dir=str(adapter_dir))
    text = await m.generate(
        messages=list(messages),
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        reload_period_sec=int(reload_period_sec),
        unload_after_sec=int(unload_after_sec),
    )
    return (str(text or ""), None)


async def stream(
    *,
    model_id: str,
    backend: str,
    base_model: str,
    adapter_dir: str,
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    reload_period_sec: int,
    unload_after_sec: int,
) -> AsyncIterator[str]:
    _ = model_id
    be = str(backend or "").strip().lower() or "mlx_qwen3"
    if be != "mlx_qwen3":
        raise RuntimeError(f"Unsupported ragweld backend: {backend}")

    m = await get_ragweld_chat_model(base_model=str(base_model), adapter_dir=str(adapter_dir))
    async for delta in m.stream(
        messages=list(messages),
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        reload_period_sec=int(reload_period_sec),
        unload_after_sec=int(unload_after_sec),
    ):
        yield delta
