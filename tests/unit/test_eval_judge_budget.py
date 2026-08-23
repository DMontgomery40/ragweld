"""The eval judge/grader output budget is its own tunable, not the chat answer budget.

Ragas faithfulness emits statement lists and reasoning-capable gateway aliases
spend tokens before the verdict; capping the judge at ``chat.max_tokens`` made a
real run fail closed with ``LLMDidNotFinishException``. Both substrates must read
``evaluation.judge_max_tokens``.
"""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from server.evaluation.promptfoo_runner import PromptfooTest, _build_config
from server.models.tribrid_config_model import EvaluationConfig, TriBridConfig


def test_judge_budget_default_and_bounds() -> None:
    cfg = TriBridConfig()
    assert cfg.evaluation.judge_max_tokens == 4096
    assert cfg.chat.max_tokens != cfg.evaluation.judge_max_tokens
    with pytest.raises(ValidationError):
        EvaluationConfig(judge_max_tokens=100)
    with pytest.raises(ValidationError):
        EvaluationConfig(judge_max_tokens=100_000)


def test_promptfoo_grader_uses_the_judge_budget_not_the_chat_budget() -> None:
    cfg = TriBridConfig()
    cfg.chat.max_tokens = 512
    cfg.evaluation.judge_max_tokens = 3000
    cfg.evaluation.promptfoo_grader_model = "openai.gpt-5.6-luna"
    previous = os.environ.get("LITELLM_API_KEY")
    os.environ["LITELLM_API_KEY"] = "sk-ragweld-local"
    try:
        payload = _build_config(
            cfg,
            [
                PromptfooTest(
                    entry_id="q1",
                    question="Which plane management company did Barry Cohen consider switching to from Jet Aviation?",
                    expected_answer="EJM",
                )
            ],
            repo_id="epstein-files-1",
        )
    finally:
        if previous is None:
            os.environ.pop("LITELLM_API_KEY", None)
        else:
            os.environ["LITELLM_API_KEY"] = previous
    grader = payload["defaultTest"]["options"]["provider"]
    assert grader["id"] == "openai:chat:openai.gpt-5.6-luna"
    assert grader["config"]["max_tokens"] == 3000


def test_evaluation_substrate_fields_round_trip_through_the_flat_config() -> None:
    cfg = TriBridConfig()
    cfg.evaluation.judge_max_tokens = 3000
    cfg.evaluation.ragas_enabled = True
    cfg.evaluation.ragas_judge_model = "openai.gpt-5.6-luna"
    cfg.evaluation.ragas_metrics = ["faithfulness"]
    cfg.evaluation.promptfoo_grader_model = "openai.gpt-4.1-nano"
    cfg.evaluation.ragas_judge_timeout_s = 120

    flat = cfg.to_flat_dict()
    assert flat["EVAL_JUDGE_MAX_TOKENS"] == 3000
    rehydrated = TriBridConfig.from_flat_dict(flat)
    assert rehydrated.evaluation.judge_max_tokens == 3000
    assert rehydrated.evaluation.ragas_enabled is True
    assert rehydrated.evaluation.ragas_judge_model == "openai.gpt-5.6-luna"
    assert rehydrated.evaluation.ragas_metrics == ["faithfulness"]
    assert rehydrated.evaluation.promptfoo_grader_model == "openai.gpt-4.1-nano"
    assert rehydrated.evaluation.ragas_judge_timeout_s == 120
