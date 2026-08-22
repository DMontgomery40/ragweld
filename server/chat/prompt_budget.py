"""Fit a generation request inside the selected gateway alias's context window.

The catalog (`data/models.json`) carries a positive context window for every
gateway alias (`gateway_rows` enforces it); vLLM's `ragweld-local` row is pinned
to `--max-model-len`. Every generation call must leave room for `max_tokens` of
output, so retrieved context is trimmed before the prompt is assembled and the
exact assembled prompt is checked once more right before it reaches LiteLLM.
Both checks count the same text (`assemble_system_prompt` is the one place the
`## Context` framing is added), so the planner never admits what the guard refuses.

Counting is conservative rather than model-exact. No provider tokenizer is
available locally for the 403 OpenRouter families, so tiktoken's `cl100k_base`
count is inflated by a per-family factor (OpenAI/Qwen tokenizers need no more
than cl100k on prose; Claude-style tokenizers can need ~1.3x on English and more
on non-Latin or whitespace-heavy text, so unknown families get the largest
factor). Image attachments are refused outright for rows without
`supports_vision`; for vision rows each image is charged the documented
worst case of its OpenAI model class (tile-based mini 48,169; tile-based
standard 1,445; 1,536-patch models 3,779; gpt-5.4 2,500-patch cap 6,150;
gpt-5.5 10,000-patch cap 24,600; every bound is at or above the documented
maximum, never below -- over-reservation is the accepted direction;
gpt-5.6 has no cap, so inline images are costed from their real pixel size and
URL images are refused), Anthropic's 4,784, or a labelled 4,800 heuristic for
families without a published maximum (the gateway's own context error is the
backstop there). OpenAI ids with no published input-image formula are refused.
An alias with no known window is refused, never treated as unlimited.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from server.gateway_catalog import gateway_rows_snapshot
from server.models.retrieval import ChunkMatch
from server.models.tribrid_config_model import PromptBudgetExceededDetail

# Chat-template framing (role markers, separators) that the transport adds around the messages.
TEMPLATE_MARGIN_TOKENS = 64
# The transport appends the retrieved context to the system prompt under this header.
CONTEXT_HEADER = "\n\n## Context\n"

# cl100k_base inflation per upstream provider family (catalog `provider`); unknown -> the largest.
TEXT_FACTOR_BY_PROVIDER: dict[str, float] = {
    "ragweld": 1.1,  # Qwen3 tokenizer (151k vocab) tokenizes prose no worse than cl100k
    "openai": 1.1,  # o200k_base is at least as efficient as cl100k_base
    "anthropic": 1.6,
}
TEXT_FACTOR_DEFAULT = 1.6
# OpenAI image accounting (https://developers.openai.com/api/docs/guides/images-vision), worst cases at
# high/auto detail. Tile-based models: 2048/768 scaling then 512px tiles (max 8). Patch-based models: 32px
# patches, a per-model cap (1,536; gpt-5.5: 10,000; gpt-5.6: none) and a per-patch multiplier (max 2.46).
OPENAI_IMAGE_TOKENS_TILE_MINI = 2833 + 8 * 5667  # gpt-4o-mini class -> 48,169
OPENAI_IMAGE_TOKENS_TILE_STANDARD = 85 + 8 * 170  # gpt-4o / gpt-4.1 / gpt-4-turbo / gpt-5 / o1 / o3 -> 1,445
OPENAI_PATCH_MULTIPLIER_MAX = 2.46  # largest documented per-patch multiplier (nano class)
OPENAI_IMAGE_TOKENS_PATCH_1536 = math.ceil(1536 * OPENAI_PATCH_MULTIPLIER_MAX)  # 1,536-patch cap -> 3,779
OPENAI_IMAGE_TOKENS_PATCH_2500 = math.ceil(2500 * OPENAI_PATCH_MULTIPLIER_MAX)  # gpt-5.4 (full) high/auto cap -> 6,150
OPENAI_IMAGE_TOKENS_PATCH_10000 = math.ceil(10000 * OPENAI_PATCH_MULTIPLIER_MAX)  # gpt-5.5 class -> 24,600
OPENAI_PATCH_PIXELS = 32  # gpt-5.6 class has no patch cap: the cost follows the real image dimensions
ANTHROPIC_IMAGE_TOKENS = 4800  # documented maximum 4,784 tokens for a 1.15 MP image
IMAGE_TOKENS_DEFAULT = 4800  # families without a published hard maximum (heuristic; gateway error is the backstop)

ImageSize = tuple[int, int] | None


class ImageBoundError(ValueError):
    """No finite per-image token cost can be established for this row/attachment."""


def openai_image_class(model: str | None) -> str:
    """Classify an OpenAI catalog id by its documented image-token formula."""

    name = str(model or "").strip().lower()
    if name.endswith(":batch"):
        name = name[: -len(":batch")]
    if "-image" in name or "gpt-chat-latest" in name:
        return "unbounded"  # image-generation ids and rolling pointers: no published input-image formula
    if "gpt-4o-mini" in name:
        return "tile_mini"
    if name.startswith(("openai/gpt-4o", "openai/gpt-4-turbo", "openai/chatgpt-4o")):
        return "tile_standard"
    if name.startswith("openai/gpt-4.1"):
        return "patch_1536" if ("-mini" in name or "-nano" in name) else "tile_standard"
    if name.startswith("openai/gpt-5.6"):
        return "patch_uncapped"
    if name.startswith("openai/gpt-5.5"):
        return "patch_10000"
    if name.startswith("openai/gpt-5.4") and not ("-mini" in name or "-nano" in name):
        return "patch_2500"
    if name in ("openai/gpt-5", "openai/gpt-5-codex", "openai/gpt-5-pro") or name.startswith(("openai/o1", "openai/o3")):
        # Documented tile-based (gpt-5: 70 + 140/tile; o-series: 75 + 150/tile), both under the 85 + 170/tile bound.
        return "tile_standard"
    if name.startswith(("openai/gpt-5", "openai/o4")):
        return "patch_1536"
    return "unbounded"


def image_tokens_for_attachment(
    provider: str | None,
    model: str | None,
    *,
    supports_vision: bool,
    size: ImageSize = None,
) -> int:
    """Worst-case tokens one attachment can cost on this row; raises ImageBoundError when none exists."""

    if not supports_vision:
        raise ImageBoundError("does not accept image attachments (catalog supports_vision=false)")
    family = str(provider or "").strip().lower()
    if family == "openai":
        klass = openai_image_class(model)
        if klass == "tile_mini":
            return OPENAI_IMAGE_TOKENS_TILE_MINI
        if klass == "tile_standard":
            return OPENAI_IMAGE_TOKENS_TILE_STANDARD
        if klass == "patch_1536":
            return OPENAI_IMAGE_TOKENS_PATCH_1536
        if klass == "patch_2500":
            return OPENAI_IMAGE_TOKENS_PATCH_2500
        if klass == "patch_10000":
            return OPENAI_IMAGE_TOKENS_PATCH_10000
        if klass == "patch_uncapped":
            if size is None:
                raise ImageBoundError(
                    "has no patch cap for images, so the cost follows the image dimensions; "
                    "attach the image inline (base64) instead of by URL"
                )
            width, height = size
            patches = math.ceil(max(1, int(width)) / OPENAI_PATCH_PIXELS) * math.ceil(max(1, int(height)) / OPENAI_PATCH_PIXELS)
            return math.ceil(patches * OPENAI_PATCH_MULTIPLIER_MAX)
        raise ImageBoundError("has no published finite image token bound; select a bounded vision alias")
    if family == "anthropic":
        return ANTHROPIC_IMAGE_TOKENS
    return IMAGE_TOKENS_DEFAULT


def image_sizes_from_attachments(images: Sequence[Any]) -> list[ImageSize]:
    """Pixel sizes of inline (base64) attachments; URL attachments have no known size."""

    sizes: list[ImageSize] = []
    for attachment in images:
        raw = getattr(attachment, "base64", None)
        if not raw:
            sizes.append(None)
            continue
        try:
            import base64
            from io import BytesIO

            from PIL import Image

            payload = str(raw)
            if "," in payload and payload.lstrip().lower().startswith("data:"):
                payload = payload.split(",", 1)[1]
            with Image.open(BytesIO(base64.b64decode(payload))) as img:
                width, height = img.size
            sizes.append((int(width), int(height)))
        except Exception:
            sizes.append(None)
    return sizes


class PromptBudgetError(RuntimeError):
    """The request cannot fit inside the alias's context window (or the window is unknown)."""

    def __init__(
        self,
        message: str,
        *,
        alias: str,
        context_window: int,
        max_tokens: int,
        prompt_tokens: int,
    ) -> None:
        super().__init__(message)
        self.alias = alias
        self.context_window = max(0, int(context_window))
        self.max_tokens = max(0, int(max_tokens))
        self.prompt_tokens = max(0, int(prompt_tokens))


@lru_cache(maxsize=1)
def _encoding():  # type: ignore[no-untyped-def]
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def warm_prompt_budget() -> None:
    """Load the tokenizer outside the request path (called from the app lifespan)."""

    _encoding()


def count_tokens(text: str) -> int:
    """Raw cl100k_base token count."""

    value = str(text or "")
    if not value:
        return 0
    return len(_encoding().encode(value, disallowed_special=()))


def conservative_tokens(text: str, *, factor: float = TEXT_FACTOR_DEFAULT) -> int:
    """Token count inflated by a family safety factor (never below the raw count)."""

    raw = count_tokens(text)
    return int(math.ceil(raw * max(1.0, float(factor))))


def assemble_system_prompt(system_prompt: str, context_text: str | None) -> str:
    """The exact system message the transport sends: prompt + `## Context` + context when any."""

    context = str(context_text or "").strip()
    return system_prompt if not context else f"{system_prompt}{CONTEXT_HEADER}{context}"


def _row_for_alias(alias: str):  # type: ignore[no-untyped-def]
    key = str(alias or "").strip()
    if not key:
        return None
    try:
        return gateway_rows_snapshot().get(key)
    except Exception:
        return None


def context_window_for_alias(alias: str) -> int | None:
    """Context window from the catalog snapshot; None when the alias is unknown or the snapshot is cold."""

    row = _row_for_alias(alias)
    if row is None or row.context is None or int(row.context) <= 0:
        return None
    return int(row.context)


def text_factor_for_provider(provider: str | None) -> float:
    return TEXT_FACTOR_BY_PROVIDER.get(str(provider or "").strip().lower(), TEXT_FACTOR_DEFAULT)


def _provider_for_alias(alias: str) -> str | None:
    row = _row_for_alias(alias)
    return str(row.provider) if row is not None else None


def image_tokens_for_alias(alias: str, *, size: ImageSize = None) -> int:
    """Per-attachment worst case for the alias's catalog row; unknown rows get the heuristic default."""

    row = _row_for_alias(alias)
    if row is None:
        return IMAGE_TOKENS_DEFAULT
    return image_tokens_for_attachment(row.provider, row.model, supports_vision=bool(row.supports_vision), size=size)


def _resolve_image_tokens(
    alias: str,
    image_sizes: Sequence[ImageSize],
    image_tokens: int | None,
    *,
    max_tokens: int,
) -> int:
    sizes = list(image_sizes)
    if not sizes:
        return 0
    if image_tokens is not None:
        return int(image_tokens) * len(sizes)
    total = 0
    for size in sizes:
        try:
            total += image_tokens_for_alias(alias, size=size)
        except ImageBoundError as exc:
            raise PromptBudgetError(
                f"alias {alias!r} {exc}",
                alias=alias,
                context_window=context_window_for_alias(alias) or 0,
                max_tokens=max_tokens,
                prompt_tokens=total,
            ) from exc
    return total


@dataclass(slots=True, frozen=True)
class PromptBudget:
    alias: str
    context_window: int
    max_tokens: int
    fixed_tokens: int
    available_for_context: int
    text_factor: float


def _resolve_window(alias: str, context_window: int | None, *, max_tokens: int, prompt_tokens: int) -> int:
    window = context_window if context_window is not None else context_window_for_alias(alias)
    if window is None or int(window) <= 0:
        raise PromptBudgetError(
            f"alias {alias!r} has no known context window; the catalog row must carry a positive context "
            "before it can serve generation",
            alias=alias,
            context_window=0,
            max_tokens=max_tokens,
            prompt_tokens=prompt_tokens,
        )
    return int(window)


def _fixed_tokens(system_prompt: str, user_message: str, *, factor: float, image_tokens_total: int) -> int:
    return (
        conservative_tokens(system_prompt, factor=factor)
        + conservative_tokens(user_message, factor=factor)
        + max(0, int(image_tokens_total))
        + TEMPLATE_MARGIN_TOKENS
    )


def plan_prompt_budget(
    *,
    alias: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    image_sizes: Sequence[ImageSize] = (),
    context_window: int | None = None,
    text_factor: float | None = None,
    image_tokens: int | None = None,
) -> PromptBudget:
    """Reserve the output allowance and the fixed prompt parts; fail when nothing fits."""

    provider = _provider_for_alias(alias)
    factor = float(text_factor) if text_factor is not None else text_factor_for_provider(provider)
    output = int(max_tokens)
    images_total = _resolve_image_tokens(alias, image_sizes, image_tokens, max_tokens=output)
    fixed = _fixed_tokens(system_prompt, user_message, factor=factor, image_tokens_total=images_total)
    window = _resolve_window(alias, context_window, max_tokens=output, prompt_tokens=fixed)
    if output >= window:
        raise PromptBudgetError(
            f"chat.max_tokens={output} leaves no room for input in the {window}-token window of {alias}",
            alias=alias,
            context_window=window,
            max_tokens=output,
            prompt_tokens=fixed,
        )
    available = window - output - fixed
    if available < 0:
        raise PromptBudgetError(
            f"system prompt + message (+ images) need {fixed} tokens but only {window - output} remain after "
            f"reserving {output} output tokens in the {window}-token window of {alias}",
            alias=alias,
            context_window=window,
            max_tokens=output,
            prompt_tokens=fixed,
        )
    return PromptBudget(
        alias=alias,
        context_window=window,
        max_tokens=output,
        fixed_tokens=fixed,
        available_for_context=available,
        text_factor=factor,
    )


def fit_context_to_budget(
    budget: PromptBudget,
    *,
    rag_chunks: list[ChunkMatch],
    recall_chunks: list[ChunkMatch],
    render: Callable[[list[ChunkMatch], list[ChunkMatch]], str],
) -> tuple[list[ChunkMatch], list[ChunkMatch], int]:
    """Keep the longest rank-ordered prefix whose rendered context fits: recall memory is dropped first, then RAG.

    The whole context is rendered and counted exactly as the transport will send
    it (`CONTEXT_HEADER` + `render(...)`); if it does not fit, a binary search
    over the number of kept chunks finds the maximal prefix with O(log n) full
    renders. A request that retrieved RAG evidence is refused rather than silently
    downgraded to a no-context prompt when none of that evidence fits. Chunk order
    is preserved. Returns the kept chunks and how many were dropped.
    """

    rag = list(rag_chunks)
    recall = list(recall_chunks)
    ordered = rag + recall  # dropping from the tail removes recall first, then the lowest-ranked RAG
    rag_count = len(rag)
    total = len(ordered)

    def _split(k: int) -> tuple[list[ChunkMatch], list[ChunkMatch]]:
        return ordered[: min(k, rag_count)], ordered[rag_count:k] if k > rag_count else []

    def _cost(k: int) -> int:
        if k <= 0:
            return 0
        kept_rag, kept_recall = _split(k)
        return conservative_tokens(CONTEXT_HEADER + render(kept_rag, kept_recall), factor=budget.text_factor)

    if total == 0 or _cost(total) <= budget.available_for_context:
        return rag, recall, 0

    low, high = 0, total - 1  # invariant: cost(low) fits, cost(high + 1) does not
    while low < high:
        mid = (low + high + 1) // 2
        if _cost(mid) <= budget.available_for_context:
            low = mid
        else:
            high = mid - 1
    kept = low
    if rag_count and kept == 0:
        raise PromptBudgetError(
            f"none of the retrieved evidence fits the {budget.context_window}-token window of {budget.alias} "
            f"after reserving {budget.max_tokens} output tokens; refusing to answer without sources",
            alias=budget.alias,
            context_window=budget.context_window,
            max_tokens=budget.max_tokens,
            prompt_tokens=budget.fixed_tokens + _cost(1),
        )
    kept_rag, kept_recall = _split(kept)
    return kept_rag, kept_recall, total - kept


def assert_prompt_within_window(
    *,
    alias: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    image_sizes: Sequence[ImageSize] = (),
    context_window: int | None = None,
    text_factor: float | None = None,
    image_tokens: int | None = None,
) -> int:
    """Final fail-closed guard over the exact assembled system prompt; returns the counted prompt tokens."""

    provider = _provider_for_alias(alias)
    factor = float(text_factor) if text_factor is not None else text_factor_for_provider(provider)
    output = int(max_tokens)
    images_total = _resolve_image_tokens(alias, image_sizes, image_tokens, max_tokens=output)
    prompt_tokens = _fixed_tokens(system_prompt, user_message, factor=factor, image_tokens_total=images_total)
    window = _resolve_window(alias, context_window, max_tokens=output, prompt_tokens=prompt_tokens)
    if output >= window or prompt_tokens + output > window:
        raise PromptBudgetError(
            f"prompt needs {prompt_tokens} tokens plus {output} output tokens, exceeding the {window}-token window of {alias}",
            alias=alias,
            context_window=window,
            max_tokens=output,
            prompt_tokens=prompt_tokens,
        )
    return prompt_tokens


def prompt_budget_exceeded_detail(exc: PromptBudgetError, *, operation: str) -> PromptBudgetExceededDetail:
    """Build the public, typed refusal detail (HTTP 413)."""

    return PromptBudgetExceededDetail(
        operation=operation,
        message=str(exc),
        operator_hint=(
            "Lower chat.max_tokens, retrieve fewer/shorter chunks (chat top_k, chunk size, history window), "
            "or select an alias with a larger context window. Ragweld refused the request instead of letting "
            "the gateway truncate or reject it."
        ),
        alias=exc.alias,
        context_window=exc.context_window,
        max_tokens=exc.max_tokens,
        prompt_tokens=exc.prompt_tokens,
    )
