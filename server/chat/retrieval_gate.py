from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from server.models.chat_config import (
    RecallFusionOverrides,
    RecallGateConfig,
    RecallIntensity,
    RecallPlan,
    RecallSignals,
)
from server.observability.metrics import RECALL_GATE_DECISIONS_TOTAL

# -----------------------------------------------------------------------------
# Pattern banks (compiled once). Keep these cheap: no network, no embeddings.
# -----------------------------------------------------------------------------

GREETING_PATTERNS = re.compile(
    r"^(hi|hello|hey|yo|sup|howdy|good\s+(morning|afternoon|evening)|"
    r"what'?s\s+up|greetings)[\s!.?]*$",
    re.IGNORECASE,
)

FAREWELL_PATTERNS = re.compile(
    r"^(bye|goodbye|see\s+ya|later|peace|cheers|take\s+care|"
    r"thanks?(\s+(a\s+lot|so\s+much))?)[\s!.?]*$",
    re.IGNORECASE,
)

ACKNOWLEDGMENT_PATTERNS = re.compile(
    r"^(ok(ay)?(\s+(got\s+it|thanks?))?|got\s+it|sure|yep|yeah|yes|no|nah|nope|right|exactly|"
    r"makes?\s+sense|understood|perfect|great|cool|nice|awesome|"
    r"sounds?\s+good|agreed|k|lol|haha|lmao|ty|thx|hmm+|ah+|oh+)[\s!.?]*$",
    re.IGNORECASE,
)

# Explicit past conversation references — strong signal for Recall.
RECALL_TRIGGER_PATTERNS = re.compile(
    r"(we\s+(discussed|talked|chatted|covered|went\s+over|decided)|"
    r"you\s+(said|mentioned|suggested|told|explained|recommended)|"
    r"(last|earlier|before|previous(ly)?|remember\s+when|"
    r"as\s+(I|we)\s+mentioned|from\s+our|in\s+our\s+last|"
    r"do\s+you\s+recall|what\s+was\s+that|what\s+did\s+we|"
    r"didn't\s+we|wasn't\s+there|back\s+when\s+we))",
    re.IGNORECASE,
)

DEFINITE_SHARED_CONTEXT = re.compile(
    r"\b(the\s+(thing|issue|problem|approach|idea|plan|decision|"
    r"conversation|discussion|point|question|bug|change))\b",
    re.IGNORECASE,
)

# Questions that typically don't need chat history.
STANDALONE_QUESTION_PATTERNS = re.compile(
    r"^(what\s+is|what'?s\s+the|how\s+does|how\s+do\s+I|explain|define|"
    r"what\s+are\s+the|show\s+me|can\s+you|where\s+is|"
    r"how\s+to|what'?s\s+the\s+difference)",
    re.IGNORECASE,
)


def extract_recall_signals(
    *,
    message: str,
    conversation_turn: int,
    last_recall_had_results: bool,
    rag_corpora_active: bool,
) -> RecallSignals:
    """Extract classification signals for Recall gating.

    Must be fast (<1ms). Pure string analysis + conversation state.
    """

    msg_stripped = (message or "").strip()
    token_count = len(msg_stripped.split()) if msg_stripped else 0

    is_question = bool(
        "?" in msg_stripped
        or re.match(
            r"^(what|where|how|why|when|who|which|is|are|do|does|can|could|should|would|will|did)\b",
            msg_stripped,
            re.IGNORECASE,
        )
    )

    is_recall_trigger = bool(RECALL_TRIGGER_PATTERNS.search(msg_stripped))
    is_standalone = bool(STANDALONE_QUESTION_PATTERNS.match(msg_stripped)) and not is_recall_trigger

    return RecallSignals(
        token_count=token_count,
        is_question=is_question,
        is_greeting=bool(GREETING_PATTERNS.match(msg_stripped)),
        is_acknowledgment=bool(
            ACKNOWLEDGMENT_PATTERNS.match(msg_stripped) or FAREWELL_PATTERNS.match(msg_stripped)
        ),
        is_follow_up=bool(token_count <= 5 and conversation_turn > 0 and not is_question),
        is_recall_trigger=is_recall_trigger,
        has_definite_article=bool(DEFINITE_SHARED_CONTEXT.search(msg_stripped)),
        is_standalone_question=is_standalone,
        conversation_turn=int(conversation_turn),
        last_recall_had_results=bool(last_recall_had_results),
        rag_corpora_active=bool(rag_corpora_active),
    )


# The rule that decided a Recall plan: the `reason` label of
# `tribrid_recall_gate_decisions_total`. Low-cardinality by construction (one value per rule).
RecallGateRule = Literal[
    "disabled_default",
    "user_override",
    "greeting",
    "ack",
    "explicit_reference",
    "topic_followup",
    "standalone_question",
    "rag_active",
    "short_question",
    "short_statement",
    "first_message",
    "default",
]


@dataclass(frozen=True, slots=True)
class RecallDecision:
    plan: RecallPlan
    rule: RecallGateRule


def decide_recall(
    *,
    message: str,
    conversation_turn: int,
    last_recall_had_results: bool,
    rag_corpora_active: bool,
    config: RecallGateConfig,
    user_override: RecallIntensity | None = None,
) -> RecallDecision:
    """Decide whether and how to query Recall for this message, and which rule decided it.

    Pure: no metrics. `classify_for_recall` is the counted entry point the chat lane uses.
    NOTE: This only gates Recall (chat memory). RAG corpora are always queried when checked.
    """

    signals = extract_recall_signals(
        message=message,
        conversation_turn=conversation_turn,
        last_recall_had_results=last_recall_had_results,
        rag_corpora_active=rag_corpora_active,
    )

    # Gate disabled: always query Recall at default intensity.
    if not config.enabled:
        return RecallDecision(
            _build_recall_plan(
                config.default_intensity,
                signals,
                config,
                reason="Recall gate disabled — using default intensity.",
            ),
            "disabled_default",
        )

    # User override: honor it.
    if user_override is not None:
        plan = _build_recall_plan(
            user_override,
            signals,
            config,
            reason=f"User override: {user_override.value}",
        )
        plan.user_override = True
        return RecallDecision(plan, "user_override")

    # Rule 1: Greetings → skip Recall.
    if config.skip_greetings and signals.is_greeting:
        return RecallDecision(
            RecallPlan(intensity=RecallIntensity.skip, signals=signals, reason="Greeting — skipping Recall."),
            "greeting",
        )

    # Rule 2: Acknowledgments → skip Recall.
    if config.skip_greetings and signals.is_acknowledgment:
        return RecallDecision(
            RecallPlan(intensity=RecallIntensity.skip, signals=signals, reason="Acknowledgment — skipping Recall."),
            "ack",
        )

    # Rule 3: Explicit recall trigger → deep.
    if config.deep_on_explicit_reference and signals.is_recall_trigger:
        return RecallDecision(
            _build_recall_plan(
                RecallIntensity.deep,
                signals,
                config,
                reason="Explicit past reference — deep Recall query.",
                recency_override=config.deep_recency_weight,
            ),
            "explicit_reference",
        )

    # Rule 4: Definite article implies shared context → standard.
    if signals.has_definite_article and signals.conversation_turn > 0:
        return RecallDecision(
            _build_recall_plan(
                RecallIntensity.standard,
                signals,
                config,
                reason="Definite article implies shared context — standard Recall.",
            ),
            "topic_followup",
        )

    # Rule 5: Standalone question → skip Recall.
    if config.skip_standalone_questions and signals.is_standalone_question:
        return RecallDecision(
            RecallPlan(intensity=RecallIntensity.skip, signals=signals, reason="Standalone question — skipping Recall."),
            "standalone_question",
        )

    # Rule 6: Skip when RAG is active (optional).
    if config.skip_when_rag_active and signals.rag_corpora_active:
        return RecallDecision(
            RecallPlan(
                intensity=RecallIntensity.skip,
                signals=signals,
                reason="RAG corpora active — skipping Recall per config.",
            ),
            "rag_active",
        )

    # Rule 7: Short questions → light (sparse-only).
    if (
        config.light_for_short_questions
        and signals.is_question
        and signals.token_count < 10
        and not signals.is_recall_trigger
        and not signals.is_standalone_question
    ):
        return RecallDecision(
            _build_recall_plan(
                RecallIntensity.light,
                signals,
                config,
                reason="Short question — light Recall check.",
            ),
            "short_question",
        )

    # Rule 8: Short non-question → light.
    if signals.token_count <= config.skip_max_tokens and not signals.is_question:
        return RecallDecision(
            _build_recall_plan(
                RecallIntensity.light,
                signals,
                config,
                reason="Short statement — light Recall check.",
            ),
            "short_statement",
        )

    # Rule 9: First message → default intensity.
    if signals.conversation_turn == 0:
        return RecallDecision(
            _build_recall_plan(
                config.default_intensity,
                signals,
                config,
                reason=f"First message — {config.default_intensity.value} Recall.",
            ),
            "first_message",
        )

    # Fallback: default intensity.
    return RecallDecision(
        _build_recall_plan(
            config.default_intensity,
            signals,
            config,
            reason="No specific pattern — default Recall intensity.",
        ),
        "default",
    )


def classify_for_recall(
    *,
    message: str,
    conversation_turn: int,
    last_recall_had_results: bool,
    rag_corpora_active: bool,
    config: RecallGateConfig,
    user_override: RecallIntensity | None = None,
) -> RecallPlan:
    """Decide the Recall plan for one chat message and count the decision
    (`tribrid_recall_gate_decisions_total{intensity,reason}`)."""

    decision = decide_recall(
        message=message,
        conversation_turn=conversation_turn,
        last_recall_had_results=last_recall_had_results,
        rag_corpora_active=rag_corpora_active,
        config=config,
        user_override=user_override,
    )
    RECALL_GATE_DECISIONS_TOTAL.labels(
        intensity=RecallIntensity(decision.plan.intensity).value, reason=decision.rule
    ).inc()
    return decision.plan


def _build_recall_plan(
    intensity: RecallIntensity,
    signals: RecallSignals,
    config: RecallGateConfig,
    *,
    reason: str,
    recency_override: float | None = None,
) -> RecallPlan:
    """Build a RecallPlan with appropriate per-message overrides."""

    if intensity == RecallIntensity.skip:
        return RecallPlan(
            intensity=intensity,
            signals=signals,
            reason=reason,
        )

    overrides = RecallFusionOverrides()

    if intensity == RecallIntensity.light:
        overrides.include_vector = False
        overrides.include_sparse = True
        overrides.top_k = int(config.light_top_k)
        overrides.enable_rerank = False
        overrides.recency_weight = float(config.standard_recency_weight)
    elif intensity == RecallIntensity.standard:
        overrides.top_k = int(config.standard_top_k)
        overrides.recency_weight = float(recency_override if recency_override is not None else config.standard_recency_weight)
    elif intensity == RecallIntensity.deep:
        overrides.top_k = int(config.deep_top_k)
        overrides.recency_weight = float(recency_override if recency_override is not None else config.deep_recency_weight)
        overrides.enable_rerank = True

    return RecallPlan(
        intensity=intensity,
        fusion_overrides=overrides,
        signals=signals,
        reason=reason,
    )
