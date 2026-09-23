import pytest

from server.chat.retrieval_gate import classify_for_recall
from server.models.chat_config import RecallGateConfig, RecallIntensity

config = RecallGateConfig()


@pytest.mark.parametrize(
    "message,expected",
    [
        ("hi", RecallIntensity.skip),
        ("hello!", RecallIntensity.skip),
        ("thanks", RecallIntensity.skip),
        ("ok got it", RecallIntensity.skip),
        ("lol", RecallIntensity.skip),
    ],
)
def test_skip_greetings_and_acknowledgments(message: str, expected: RecallIntensity) -> None:
    plan = classify_for_recall(
        message=message,
        conversation_turn=3,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=config,
    )
    assert plan.intensity == expected


@pytest.mark.parametrize(
    "message",
    [
        "what's the auth flow?",
        "how does chunking work?",
        "explain the retrieval pipeline",
        "where is the config file?",
    ],
)
def test_skip_standalone_questions(message: str) -> None:
    """Standalone technical questions don't need chat history."""
    plan = classify_for_recall(
        message=message,
        conversation_turn=1,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=config,
    )
    assert plan.intensity == RecallIntensity.skip


@pytest.mark.parametrize(
    "message",
    [
        "what did we discuss about auth?",
        "you mentioned a better approach",
        "as we talked about earlier",
        "remember when we decided on chunking?",
        "what was that thing you suggested?",
    ],
)
def test_deep_on_explicit_recall_reference(message: str) -> None:
    """Explicit past references trigger deep Recall query."""
    plan = classify_for_recall(
        message=message,
        conversation_turn=5,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=config,
    )
    assert plan.intensity == RecallIntensity.deep
    assert plan.fusion_overrides.recency_weight == config.deep_recency_weight


@pytest.mark.parametrize(
    "message",
    [
        "the bug",
        "the approach",
        "the issue we found",
    ],
)
def test_standard_on_definite_article(message: str) -> None:
    """Definite articles imply shared context — standard Recall."""
    plan = classify_for_recall(
        message=message,
        conversation_turn=3,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=config,
    )
    assert plan.intensity == RecallIntensity.standard


def test_user_override_honored() -> None:
    plan = classify_for_recall(
        message="hi",  # normally would be skip
        conversation_turn=0,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=config,
        user_override=RecallIntensity.deep,  # user forces deep
    )
    assert plan.intensity == RecallIntensity.deep
    assert plan.user_override is True


def test_gate_disabled_always_queries() -> None:
    disabled_config = RecallGateConfig(enabled=False)
    plan = classify_for_recall(
        message="hi",
        conversation_turn=0,
        last_recall_had_results=True,
        rag_corpora_active=True,
        config=disabled_config,
    )
    assert plan.intensity == disabled_config.default_intensity


def test_skip_when_rag_active_if_configured() -> None:
    aggressive_config = RecallGateConfig(skip_when_rag_active=True)
    plan = classify_for_recall(
        message="continue",
        conversation_turn=1,
        last_recall_had_results=True,
        rag_corpora_active=True,  # RAG is active
        config=aggressive_config,
    )
    assert plan.intensity == RecallIntensity.skip



_STATEMENT = "I want to compare ingestion throughput numbers across both staging clusters this week"


@pytest.mark.parametrize(
    ("message", "turn", "gate", "override", "rule", "intensity"),
    [
        ("Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?", 0, RecallGateConfig(enabled=False), None, "disabled_default", RecallIntensity.standard),
        ("Which flights did Jeffrey Epstein arrange for Barry Cohen in October 2017?", 0, config, RecallIntensity.deep, "user_override", RecallIntensity.deep),
        ("hello!", 3, config, None, "greeting", RecallIntensity.skip),
        ("ok got it", 3, config, None, "ack", RecallIntensity.skip),
        ("what did we discuss about auth?", 5, config, None, "explicit_reference", RecallIntensity.deep),
        ("the bug", 3, config, None, "topic_followup", RecallIntensity.standard),
        ("how does chunking work?", 1, config, None, "standalone_question", RecallIntensity.skip),
        ("continue", 1, RecallGateConfig(skip_when_rag_active=True), None, "rag_active", RecallIntensity.skip),
        ("is the retry budget per request?", 2, config, None, "short_question", RecallIntensity.light),
        ("sounds reasonable to me", 2, config, None, "short_statement", RecallIntensity.light),
        (_STATEMENT, 0, config, None, "first_message", RecallIntensity.standard),
        (_STATEMENT, 2, config, None, "default", RecallIntensity.standard),
    ],
)
def test_every_gate_rule_is_named_and_counted(
    message: str,
    turn: int,
    gate: RecallGateConfig,
    override: RecallIntensity | None,
    rule: str,
    intensity: RecallIntensity,
) -> None:
    """Each rule of the gate has its own `reason`, and the chat lane's entry point counts
    the decision as `tribrid_recall_gate_decisions_total{intensity,reason}`."""
    from prometheus_client import REGISTRY

    from server.chat.retrieval_gate import decide_recall

    kwargs = {
        "message": message,
        "conversation_turn": turn,
        "last_recall_had_results": True,
        "rag_corpora_active": True,
        "config": gate,
        "user_override": override,
    }
    decision = decide_recall(**kwargs)
    assert (decision.rule, decision.plan.intensity) == (rule, intensity)

    labels = {"intensity": intensity.value, "reason": rule}
    before = REGISTRY.get_sample_value("tribrid_recall_gate_decisions_total", labels) or 0.0
    plan = classify_for_recall(**kwargs)
    after = REGISTRY.get_sample_value("tribrid_recall_gate_decisions_total", labels)

    assert plan.intensity == intensity
    assert after == before + 1.0
