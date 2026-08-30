from __future__ import annotations

from server.models.chat_config import ChatConfig

# The single fallback when an operator has cleared a 4-state prompt to empty. This is a code
# invariant, not a second configurable prompt system: the legacy base+suffix composition was a
# banned dual path (replacement-only canon; M-101/B-22) and has been removed.
_EMPTY_PROMPT_FALLBACK = "You are a helpful assistant."


def get_system_prompt(*, has_rag_context: bool, has_recall_context: bool, config: ChatConfig) -> str:
    """Select one of the four state prompts based on what context is present.

    There are 4 states, 4 prompts. Pick one. If the selected prompt is empty, use a single
    hardcoded fallback string - never the legacy base+suffix composition, which was a
    transition-period dual path the canon forbids.
    """

    if has_rag_context and has_recall_context:
        selected = str(getattr(config, "system_prompt_rag_and_recall", "") or "")
    elif has_rag_context:
        selected = str(getattr(config, "system_prompt_rag", "") or "")
    elif has_recall_context:
        selected = str(getattr(config, "system_prompt_recall", "") or "")
    else:
        selected = str(getattr(config, "system_prompt_direct", "") or "")

    return selected.strip() or _EMPTY_PROMPT_FALLBACK

