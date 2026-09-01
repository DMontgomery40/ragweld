from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import pytest

from server.chat.context_formatter import format_context_for_llm
from server.chat.prompt_budget import (
    CONTEXT_HEADER,
    IMAGE_TOKENS_DEFAULT,
    TEMPLATE_MARGIN_TOKENS,
    TEXT_FACTOR_DEFAULT,
    ImageBoundError,
    PromptBudgetError,
    assemble_system_prompt,
    assert_prompt_within_window,
    conservative_tokens,
    count_tokens,
    fit_context_to_budget,
    image_sizes_from_attachments,
    image_tokens_for_alias,
    image_tokens_for_attachment,
    openai_image_class,
    plan_prompt_budget,
    prompt_budget_exceeded_detail,
    text_factor_for_provider,
)
from server.models.retrieval import ChunkMatch
from server.models.runtime_gateway import GenerationConfig
from server.models.tribrid_config_model import TriBridConfig

ROOT = Path(__file__).resolve().parents[2]
LOCAL_WINDOW = 32768  # start.sh LOCAL_MODEL_MAX_LEN for ragweld-local
# An alias the catalog does not know: the window is passed explicitly and the family defaults
# (largest factors) apply whether or not another test warmed the catalog snapshot.
ALIAS = "unit-test-alias"
QUESTION = "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?"


def _chunk(index: int, words: int, *, recall: bool = False) -> ChunkMatch:
    body = " ".join(f"plane management note {index} token{n}" for n in range(words // 4))
    return ChunkMatch(
        chunk_id=f"HOUSE_OVERSIGHT_{index:06d}.txt:1-4:0",
        file_path=f"HOUSE_OVERSIGHT_{index:06d}.txt",
        start_line=1,
        end_line=4,
        content=body,
        score=1.0 / (index + 1),
        source="vector",
        metadata={"role": "user", "timestamp": "2026-08-22T00:00:00Z", "conversation_id": "c1"} if recall else {},
    )


def _render(rag: list[ChunkMatch], recall: list[ChunkMatch]) -> str:
    return format_context_for_llm(rag_chunks=rag, recall_chunks=recall)


def test_count_tokens_is_real_and_monotonic() -> None:
    assert count_tokens("") == 0
    short = count_tokens(QUESTION)
    assert 10 < short < 40
    assert count_tokens(QUESTION * 10) > short * 8


def test_default_config_fits_the_local_window_with_room_for_context() -> None:
    cfg = TriBridConfig()
    budget = plan_prompt_budget(
        alias=ALIAS,
        system_prompt=str(cfg.system_prompts.main_rag_chat),
        user_message=QUESTION,
        max_tokens=int(cfg.chat.max_tokens),
        context_window=LOCAL_WINDOW,
    )
    assert budget.available_for_context > LOCAL_WINDOW // 2
    assert budget.text_factor == TEXT_FACTOR_DEFAULT  # cold snapshot: unknown family, largest factor
    assert GenerationConfig().gen_max_tokens <= LOCAL_WINDOW // 2


@pytest.mark.parametrize("max_tokens", [LOCAL_WINDOW, LOCAL_WINDOW + 1])
def test_output_allowance_at_or_above_the_window_is_rejected(max_tokens: int) -> None:
    with pytest.raises(PromptBudgetError, match="leaves no room for input") as info:
        plan_prompt_budget(
            alias=ALIAS, system_prompt="short", user_message=QUESTION, max_tokens=max_tokens, context_window=LOCAL_WINDOW
        )
    assert info.value.context_window == LOCAL_WINDOW
    assert info.value.max_tokens == max_tokens


def test_fixed_prompt_parts_that_exceed_the_remaining_window_are_rejected() -> None:
    huge_system = " ".join(["ground every claim"] * (LOCAL_WINDOW // 2))
    with pytest.raises(PromptBudgetError, match="system prompt \\+ message \\(\\+ images\\) need"):
        plan_prompt_budget(alias=ALIAS, system_prompt=huge_system, user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)


def test_unknown_window_fails_closed() -> None:
    with pytest.raises(PromptBudgetError, match="has no known context window") as info:
        plan_prompt_budget(alias="unknown-alias", system_prompt="s", user_message=QUESTION, max_tokens=512, context_window=None)
    assert info.value.context_window == 0
    with pytest.raises(PromptBudgetError, match="has no known context window"):
        assert_prompt_within_window(alias="unknown-alias", system_prompt="s", user_message=QUESTION, max_tokens=512)
    detail = prompt_budget_exceeded_detail(info.value, operation="Chat generation")
    assert detail.context_window == 0 and detail.code == "prompt_budget_exceeded"


def test_images_are_charged_at_the_family_worst_case() -> None:
    no_images = plan_prompt_budget(alias=ALIAS, system_prompt="s", user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    # Unknown family (alias not in the catalog): the labelled heuristic applies per attachment.
    with_images = plan_prompt_budget(alias=ALIAS, system_prompt="s", user_message=QUESTION, max_tokens=512, image_sizes=[None], context_window=LOCAL_WINDOW)
    assert with_images.fixed_tokens - no_images.fixed_tokens == IMAGE_TOKENS_DEFAULT == 4800
    # Enough worst-case images alone exceed the local window once output is reserved.
    over_window_images = (LOCAL_WINDOW - 512) // IMAGE_TOKENS_DEFAULT + 1
    with pytest.raises(PromptBudgetError, match="\\(\\+ images\\)"):
        plan_prompt_budget(
            alias=ALIAS,
            system_prompt="s",
            user_message=QUESTION,
            max_tokens=512,
            image_sizes=[None] * over_window_images,
            context_window=LOCAL_WINDOW,
        )


# Documented per-image maxima (high/auto detail) per catalog id, from OpenAI's image-sizing rules:
# tile-based models: base + 8 tiles x per-tile (2048/768 scaling, 512px tiles); patch-based models:
# cap x the model's multiplier. None = no finite published maximum (dimension-dependent or refused).
TILE_STANDARD_MAX = 85 + 8 * 170  # 1,445 (gpt-4o / gpt-4.1 / gpt-4-turbo)
TILE_MINI_MAX = 2833 + 8 * 5667  # 48,169 (gpt-4o-mini)
TILE_GPT5_MAX = 70 + 8 * 140  # 1,190 (gpt-5 family, tile-based)
TILE_O_SERIES_MAX = 75 + 8 * 150  # 1,275 (o1 / o3, tile-based)
OPENAI_DOCUMENTED_IMAGE_MAX: dict[str, int | None] = {
    "openai/gpt-4-turbo": TILE_STANDARD_MAX,
    "openai/gpt-4.1": TILE_STANDARD_MAX,
    "openai/gpt-4.1-mini": math.ceil(1536 * 1.62),
    "openai/gpt-4.1-nano": math.ceil(1536 * 2.46),
    "openai/gpt-4o": TILE_STANDARD_MAX,
    "openai/gpt-4o-2024-05-13": TILE_STANDARD_MAX,
    "openai/gpt-4o-2024-08-06": TILE_STANDARD_MAX,
    "openai/gpt-4o-2024-11-20": TILE_STANDARD_MAX,
    "openai/gpt-4o-mini": TILE_MINI_MAX,
    "openai/gpt-4o-mini-2024-07-18": TILE_MINI_MAX,
    "openai/gpt-5": TILE_GPT5_MAX,
    "openai/gpt-5-image": None,
    "openai/gpt-5-image-mini": None,
    "openai/gpt-5-mini": math.ceil(1536 * 1.62),
    "openai/gpt-5-nano": math.ceil(1536 * 2.46),
    "openai/gpt-5-pro": TILE_GPT5_MAX,
    "openai/gpt-5.1": math.ceil(1536 * 2.46),
    "openai/gpt-5.1-codex": math.ceil(1536 * 2.46),
    "openai/gpt-5.1-codex-max": math.ceil(1536 * 2.46),
    "openai/gpt-5.1-codex-mini": math.ceil(1536 * 2.46),
    "openai/gpt-5.2": math.ceil(1536 * 2.46),
    "openai/gpt-5.2-chat": math.ceil(1536 * 2.46),
    "openai/gpt-5.2-codex": math.ceil(1536 * 2.46),
    "openai/gpt-5.2-pro": math.ceil(1536 * 2.46),
    "openai/gpt-5.3-codex": math.ceil(1536 * 2.46),
    "openai/gpt-5.4": math.ceil(2500 * 2.46),  # 2,500-patch high/auto ceiling
    "openai/gpt-5.4-image-2": None,
    "openai/gpt-5.4-mini": math.ceil(1536 * 1.62),
    "openai/gpt-5.4-nano": math.ceil(1536 * 2.46),
    "openai/gpt-5.4-pro": math.ceil(2500 * 2.46),
    "openai/gpt-5.5": math.ceil(10000 * 2.46),
    "openai/gpt-5.5-pro": math.ceil(10000 * 2.46),
    "openai/gpt-5.6-luna": None,  # uncapped: dimension-dependent
    "openai/gpt-5.6-luna-pro": None,
    "openai/gpt-5.6-sol": None,
    "openai/gpt-5.6-sol-pro": None,
    "openai/gpt-5.6-terra": None,
    "openai/gpt-5.6-terra-pro": None,
    "openai/gpt-chat-latest": None,  # rolling pointer: no stable formula
    "openai/o1": TILE_O_SERIES_MAX,
    "openai/o1-pro": TILE_O_SERIES_MAX,
    "openai/o3": TILE_O_SERIES_MAX,
    "openai/o3-pro": TILE_O_SERIES_MAX,
    "openai/o4-mini": math.ceil(1536 * 1.72),
    "openai/o4-mini-high": math.ceil(1536 * 1.72),
}


def test_every_openai_vision_alias_in_the_catalog_is_bounded_at_or_above_its_documented_maximum() -> None:
    """Independent oracle: a new OpenAI vision id must be entered here before it can ship; bounds never under-reserve."""
    catalog = json.loads((ROOT / "data" / "models.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for row in catalog["models"]:
        if row.get("provider") != "openai" or not row.get("gateway_alias") or not row.get("supports_vision"):
            continue
        base = row["model"][: -len(":batch")] if row["model"].endswith(":batch") else row["model"]
        assert base in OPENAI_DOCUMENTED_IMAGE_MAX, f"undocumented OpenAI vision id {row['model']}"
        seen.add(base)
        documented = OPENAI_DOCUMENTED_IMAGE_MAX[base]
        if documented is None:
            # Dimension-dependent ids cost from real pixels; ids without a formula are refused outright.
            if openai_image_class(row["model"]) == "patch_uncapped":
                assert image_tokens_for_attachment("openai", row["model"], supports_vision=True, size=(1024, 1024)) == math.ceil(1024 * 2.46)
                with pytest.raises(ImageBoundError):
                    image_tokens_for_attachment("openai", row["model"], supports_vision=True, size=None)
            else:
                with pytest.raises(ImageBoundError):
                    image_tokens_for_attachment("openai", row["model"], supports_vision=True, size=(1024, 1024))
            continue
        bound = image_tokens_for_attachment("openai", row["model"], supports_vision=True, size=(4096, 4096))
        assert bound >= documented, f"{row['model']}: bound {bound} < documented maximum {documented}"
        # Over-reservation is bounded too: never more than 3x the documented maximum.
        assert bound <= 3 * documented, f"{row['model']}: bound {bound} over-reserves more than 3x {documented}"
    assert seen == set(OPENAI_DOCUMENTED_IMAGE_MAX), set(OPENAI_DOCUMENTED_IMAGE_MAX) ^ seen


def test_uncapped_openai_models_are_costed_from_real_pixels_and_refuse_url_images() -> None:
    # 1024 x 1024 -> 32 x 32 patches = 1,024 patches x 2.46 -> 2,520; 4096 x 4096 -> 16,384 patches -> 40,305.
    assert image_tokens_for_attachment("openai", "openai/gpt-5.6-sol", supports_vision=True, size=(1024, 1024)) == math.ceil(1024 * 2.46)
    assert image_tokens_for_attachment("openai", "openai/gpt-5.6-sol", supports_vision=True, size=(4096, 4096)) == math.ceil(16384 * 2.46)
    assert image_tokens_for_attachment("openai", "openai/gpt-5.6-sol", supports_vision=True, size=(33, 1)) == math.ceil(2 * 2.46)
    with pytest.raises(ImageBoundError, match="follows the image dimensions"):
        image_tokens_for_attachment("openai", "openai/gpt-5.6-sol", supports_vision=True, size=None)
    with pytest.raises(ImageBoundError, match="no published finite image token bound"):
        image_tokens_for_attachment("openai", "openai/gpt-chat-latest", supports_vision=True, size=(64, 64))
    with pytest.raises(ImageBoundError, match="does not accept image attachments"):
        image_tokens_for_attachment("ragweld", "mlx-community/Qwen3.8-27B-4bit", supports_vision=False, size=(64, 64))


def test_inline_image_sizes_are_decoded_and_urls_have_none() -> None:
    import base64
    from io import BytesIO

    from PIL import Image

    from server.models.tribrid_config_model import ImageAttachment

    buffer = BytesIO()
    Image.new("RGB", (640, 480), color=(10, 20, 30)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    sizes = image_sizes_from_attachments(
        [
            ImageAttachment(base64=encoded, mime_type="image/png"),
            ImageAttachment(base64="data:image/png;base64," + encoded, mime_type="image/png"),
            ImageAttachment(url="https://example.invalid/plane.png"),
            ImageAttachment(base64="not-an-image", mime_type="image/png"),
        ]
    )
    assert sizes == [(640, 480), (640, 480), None, None]


def test_catalog_vision_rows_resolve_a_bound_or_an_explicit_refusal_and_text_only_rows_refuse() -> None:
    """Every gateway row either yields a finite per-image cost or raises an explicit ImageBoundError."""
    catalog = json.loads((ROOT / "data" / "models.json").read_text(encoding="utf-8"))
    bounded = refused = text_only = 0
    for row in catalog["models"]:
        if not row.get("gateway_alias"):
            continue
        vision = bool(row.get("supports_vision"))
        try:
            bound = image_tokens_for_attachment(row["provider"], row["model"], supports_vision=vision, size=(1024, 1024))
        except ImageBoundError:
            if vision:
                refused += 1
            else:
                text_only += 1
            continue
        assert vision, row["gateway_alias"]
        assert bound >= 1445, row["gateway_alias"]
        if row["provider"] == "anthropic":
            assert bound >= 4784
        bounded += 1
    assert bounded > 200 and text_only > 150 and refused >= 3


def test_family_bounds_are_never_below_the_documented_worst_cases() -> None:
    assert image_tokens_for_attachment("anthropic", "anthropic/claude-sonnet-4", supports_vision=True) >= 4784
    assert image_tokens_for_attachment("mistralai", "mistralai/pixtral-large", supports_vision=True) == IMAGE_TOKENS_DEFAULT
    assert text_factor_for_provider("anthropic") >= 1.5
    assert text_factor_for_provider("unknown-family") == TEXT_FACTOR_DEFAULT >= 1.5
    assert text_factor_for_provider("openai") >= 1.0 and text_factor_for_provider("ragweld") >= 1.0
    # Factors never shrink the raw count.
    assert conservative_tokens(QUESTION, factor=0.5) == count_tokens(QUESTION)


def test_warmed_catalog_resolves_real_aliases_to_their_family_bounds() -> None:
    from server.gateway_catalog import warm_gateway_catalog

    warm_gateway_catalog()
    with pytest.raises(ImageBoundError, match="does not accept image attachments"):
        image_tokens_for_alias("ragweld-local")  # text-only serving row
    assert image_tokens_for_alias("openai.gpt-4o-mini") == 2833 + 8 * 5667
    assert image_tokens_for_alias("openai.gpt-5.5") == math.ceil(10000 * 2.46)
    assert image_tokens_for_alias("openai.gpt-5.4") == math.ceil(2500 * 2.46)
    assert image_tokens_for_alias("openai.gpt-5.4-mini") == math.ceil(1536 * 2.46)
    assert image_tokens_for_alias("openai.gpt-5.6-sol", size=(1024, 1024)) == math.ceil(1024 * 2.46)
    assert image_tokens_for_alias("anthropic.claude-sonnet-4") >= 4784
    local = plan_prompt_budget(alias="ragweld-local", system_prompt="s", user_message=QUESTION, max_tokens=512)
    assert local.context_window == LOCAL_WINDOW and local.text_factor == 1.1
    with pytest.raises(PromptBudgetError, match="does not accept image attachments"):
        plan_prompt_budget(alias="ragweld-local", system_prompt="s", user_message=QUESTION, max_tokens=512, image_sizes=[(64, 64)])
    with pytest.raises(PromptBudgetError, match="does not accept image attachments"):
        assert_prompt_within_window(alias="ragweld-local", system_prompt="s", user_message=QUESTION, max_tokens=512, image_sizes=[(64, 64)])
    with pytest.raises(PromptBudgetError, match="follows the image dimensions"):
        plan_prompt_budget(alias="openai.gpt-5.6-sol", system_prompt="s", user_message=QUESTION, max_tokens=512, image_sizes=[None])


def test_text_counts_carry_the_family_safety_factor() -> None:
    raw = count_tokens(QUESTION)
    assert conservative_tokens(QUESTION) == math.ceil(raw * TEXT_FACTOR_DEFAULT)
    assert conservative_tokens(QUESTION, factor=1.1) == math.ceil(raw * 1.1)


def test_handler_imports_cleanly_in_a_fresh_process() -> None:
    """The chat handler must not depend on server.api (import-order-dependent cycle)."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import server.chat.handler, server.chat.generation, server.chat.prompt_budget"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={**os.environ, "RAGWELD_LOAD_DOTENV": "0"},
    )
    assert result.returncode == 0, result.stderr


def test_oversized_retrieval_drops_recall_memory_before_rag_evidence_and_stays_fast() -> None:
    budget = plan_prompt_budget(alias=ALIAS, system_prompt="Answer from the sources.", user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    # chat.top_k may legally reach 100; each ~2.5k-token chunk fits alone, the set does not.
    rag = [_chunk(i, 2000) for i in range(100)]
    recall = [_chunk(1000 + i, 400, recall=True) for i in range(3)]
    started = time.perf_counter()
    kept_rag, kept_recall, dropped = fit_context_to_budget(budget, rag_chunks=rag, recall_chunks=recall, render=_render)
    elapsed = time.perf_counter() - started
    assert elapsed < 3.0, f"trimming 103 chunks took {elapsed:.1f}s"
    assert dropped > 0
    assert kept_recall == []  # memory goes first
    assert kept_rag and kept_rag == rag[: len(kept_rag)]  # top-ranked evidence survives, order preserved
    kept_cost = conservative_tokens(CONTEXT_HEADER + _render(kept_rag, kept_recall), factor=budget.text_factor)
    assert kept_cost <= budget.available_for_context
    # Maximal: the next dropped chunk would not have fit.
    one_more = conservative_tokens(CONTEXT_HEADER + _render(rag[: len(kept_rag) + 1], []), factor=budget.text_factor)
    assert one_more > budget.available_for_context


def test_context_that_fits_is_never_trimmed_even_when_chunks_are_many_and_small() -> None:
    budget = plan_prompt_budget(alias=ALIAS, system_prompt="Answer from the sources.", user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    rag = [_chunk(i, 16) for i in range(40)]  # tiny chunks: per-chunk framing estimates would over-count
    recall = [_chunk(1000 + i, 16, recall=True) for i in range(10)]
    assert conservative_tokens(CONTEXT_HEADER + _render(rag, recall), factor=budget.text_factor) <= budget.available_for_context
    kept_rag, kept_recall, dropped = fit_context_to_budget(budget, rag_chunks=rag, recall_chunks=recall, render=_render)
    assert (kept_rag, kept_recall, dropped) == (rag, recall, 0)


def test_planner_and_final_guard_count_the_same_assembled_prompt() -> None:
    """Whatever the planner admits, the transport guard accepts; whatever it refuses, the guard refuses."""
    system_prompt = "Answer only from the provided sources and cite them."
    rag = [_chunk(i, 600) for i in range(6)]
    recall = [_chunk(1000, 200, recall=True)]
    admitted = refused = 0
    for max_tokens in range(LOCAL_WINDOW - 4000, LOCAL_WINDOW - 300, 53):
        try:
            budget = plan_prompt_budget(alias=ALIAS, system_prompt=system_prompt, user_message=QUESTION, max_tokens=max_tokens, context_window=LOCAL_WINDOW)
            kept_rag, kept_recall, _ = fit_context_to_budget(budget, rag_chunks=rag, recall_chunks=recall, render=_render)
        except PromptBudgetError:
            refused += 1
            continue
        assembled = assemble_system_prompt(system_prompt, _render(kept_rag, kept_recall))
        assert_prompt_within_window(alias=ALIAS, system_prompt=assembled, user_message=QUESTION, max_tokens=max_tokens, context_window=LOCAL_WINDOW)
        admitted += 1
    assert admitted > 0 and refused > 0


def test_request_is_refused_when_no_retrieved_evidence_fits() -> None:
    budget = plan_prompt_budget(alias=ALIAS, system_prompt="Answer from the sources.", user_message=QUESTION, max_tokens=LOCAL_WINDOW - 292, context_window=LOCAL_WINDOW)
    assert 0 <= budget.available_for_context < 200
    with pytest.raises(PromptBudgetError, match="none of the retrieved evidence fits"):
        fit_context_to_budget(budget, rag_chunks=[_chunk(0, 2000)], recall_chunks=[_chunk(1, 400, recall=True)], render=_render)
    # Recall-only context may be dropped entirely: nothing authoritative is lost.
    kept_rag, kept_recall, dropped = fit_context_to_budget(budget, rag_chunks=[], recall_chunks=[_chunk(1, 2000, recall=True)], render=_render)
    assert (kept_rag, kept_recall, dropped) == ([], [], 1)
    # Evidence survives while the memory that would not fit is dropped.
    roomy = plan_prompt_budget(alias=ALIAS, system_prompt="Answer from the sources.", user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    kept_rag, kept_recall, dropped = fit_context_to_budget(roomy, rag_chunks=[_chunk(0, 2000)], recall_chunks=[_chunk(1, LOCAL_WINDOW, recall=True)], render=_render)
    assert len(kept_rag) == 1 and kept_recall == [] and dropped == 1


def test_final_guard_fails_closed_on_an_oversized_assembled_prompt() -> None:
    oversized = "## Context\n" + " ".join(["plane"] * (LOCAL_WINDOW + 1000))
    with pytest.raises(PromptBudgetError, match=f"exceeding the {LOCAL_WINDOW}-token window of unit-test-alias") as info:
        assert_prompt_within_window(alias=ALIAS, system_prompt=oversized, user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    assert info.value.prompt_tokens > LOCAL_WINDOW - 512
    counted = assert_prompt_within_window(alias=ALIAS, system_prompt="Answer from the sources.", user_message=QUESTION, max_tokens=512, context_window=LOCAL_WINDOW)
    assert counted is not None and counted >= TEMPLATE_MARGIN_TOKENS
