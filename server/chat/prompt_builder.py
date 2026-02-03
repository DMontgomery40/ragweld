from __future__ import annotations

from server.models.chat_config import ChatConfig


def get_system_prompt(*, has_rag_context: bool, has_recall_context: bool, config: ChatConfig) -> str:
    """Select the system prompt based on what context is present.

    There are 4 states, 4 prompts. Pick one. If the selected prompt is empty,
    fall back to legacy base+suffix composition.
    """

    if has_rag_context and has_recall_context:
        selected = str(getattr(config, "system_prompt_rag_and_recall", "") or "")
    elif has_rag_context:
        selected = str(getattr(config, "system_prompt_rag", "") or "")
    elif has_recall_context:
        selected = str(getattr(config, "system_prompt_recall", "") or "")
    else:
        selected = str(getattr(config, "system_prompt_direct", "") or "")

    if selected.strip():
        return selected.strip()

    # Backwards-compatible composition.
    prompt = str(getattr(config, "system_prompt_base", "") or "")
    if has_recall_context:
        prompt += str(getattr(config, "system_prompt_recall_suffix", "") or "")
    if has_rag_context:
        prompt += str(getattr(config, "system_prompt_rag_suffix", "") or "")
    return prompt.strip() or "You are a helpful assistant."

