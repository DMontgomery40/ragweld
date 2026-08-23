"""The synthetic lane has exactly one generation path and no fallback bookkeeping.

Generator/judge failures fail the run; rows the model could not ground are
rejected and counted; nothing is hydrated from a seed dataset. These tests pin
the public contract (config fields, summary fields, prompt tokens) that the
Synthetic Lab renders.
"""

from __future__ import annotations

from server.models.tribrid_config_model import (
    SyntheticGeneratorConfig,
    SyntheticJudgeConfig,
    SyntheticRunStartRequest,
    SyntheticRunSummary,
    SystemPromptsConfig,
    TriBridConfig,
)


def test_synthetic_config_has_no_fallback_switches() -> None:
    assert "fail_on_error" not in SyntheticGeneratorConfig.model_fields
    assert "fail_on_error" not in SyntheticJudgeConfig.model_fields
    assert "degradation" not in SyntheticRunSummary.model_fields


def test_synthetic_config_quality_gate_defaults() -> None:
    cfg = TriBridConfig()
    assert cfg.synthetic.quality_gate.top1_min == 0.40
    assert cfg.synthetic.quality_gate.sample_size == 50


def test_synthetic_config_generator_defaults() -> None:
    cfg = TriBridConfig()
    gen = cfg.synthetic.generator
    assert gen.temperature == 0.0
    assert gen.max_tokens == 1200
    assert gen.question_max_chars == 180
    assert gen.evidence_quote_max_chars == 200
    assert gen.expected_answer_max_chars == 400
    assert gen.source_excerpt_max_lines == 80
    assert gen.concurrency == 4


def test_synthetic_config_judge_defaults() -> None:
    cfg = TriBridConfig()
    assert cfg.synthetic.judge.temperature == 0.0
    assert cfg.synthetic.judge.max_tokens == 400


def test_summary_rejection_counters_default_to_zero() -> None:
    summary = SyntheticRunSummary()
    assert summary.items_generated == 0
    assert summary.items_rejected_ungrounded == 0
    assert summary.items_rejected_malformed == 0
    assert summary.items_curated_in == 0
    assert summary.items_curated_out == 0
    assert summary.triplets_mined == 0
    assert summary.avg_judge_score is None


def test_generator_prompt_carries_every_render_token() -> None:
    prompt = SystemPromptsConfig().synthetic_generator
    for token in ("{num_pairs}", "{question_max_chars}", "{expected_answer_max_chars}", "{evidence_quote_max_chars}"):
        assert token in prompt
    assert "evidence_quote" in prompt
    assert "verbatim" in prompt


def test_only_the_grounded_qa_provider_exists() -> None:
    request = SyntheticRunStartRequest(
        corpus_id="epstein-files-1",
        generator_model="litellm:openai.gpt-5.4-mini",
        judge_model="litellm:openai.gpt-5.4-mini",
    )
    assert request.provider == "grounded_qa"
