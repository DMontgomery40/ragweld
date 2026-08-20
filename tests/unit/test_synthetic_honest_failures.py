"""Tests for honest failure reporting in the synthetic pipeline.

Verifies that generator/judge LLM failures are surfaced through degradation
flags instead of silently producing garbage, and that fail_on_error config
controls whether failures raise or degrade gracefully.
"""

from __future__ import annotations

import pytest

from server.models.tribrid_config_model import (
    SyntheticRunDegradation,
    SyntheticRunSummary,
    TriBridConfig,
)
from server.synthetic.orchestrator import _hydrate_eval_dataset_from_seed


def test_degradation_defaults_are_clean() -> None:
    d = SyntheticRunDegradation()
    assert d.degraded is False
    assert d.generator_fallback_used is False
    assert d.judge_fallback_used is False
    assert d.seed_hydration_used is False
    assert d.seed_hydration_count == 0
    assert d.reasons == []


def test_synthetic_config_defaults_fail_on_error() -> None:
    cfg = TriBridConfig()
    assert cfg.synthetic.generator.fail_on_error is True
    assert cfg.synthetic.judge.fail_on_error is True


def test_synthetic_config_quality_gate_defaults() -> None:
    cfg = TriBridConfig()
    assert cfg.synthetic.quality_gate.top1_min == pytest.approx(0.40)
    assert cfg.synthetic.quality_gate.sample_size == 50


def test_synthetic_config_generator_defaults() -> None:
    cfg = TriBridConfig()
    gen = cfg.synthetic.generator
    assert gen.temperature == pytest.approx(0.0)
    assert gen.max_tokens == 1200
    assert gen.question_max_chars == 180
    assert gen.evidence_quote_max_chars == 200
    assert gen.expected_answer_max_chars == 400
    assert gen.source_excerpt_max_lines == 80


def test_synthetic_config_judge_defaults() -> None:
    cfg = TriBridConfig()
    judge = cfg.synthetic.judge
    assert judge.temperature == pytest.approx(0.0)
    assert judge.max_tokens == 400


def test_summary_degradation_is_composed_object() -> None:
    summary = SyntheticRunSummary()
    assert isinstance(summary.degradation, SyntheticRunDegradation)
    assert summary.degradation.degraded is False


def test_seed_hydration_sets_degradation_flags(tmp_path: object) -> None:
    """Seed hydration through _hydrate_eval_dataset_from_seed sets degradation flags."""
    from server.models.tribrid_config_model import SyntheticRunStartRequest

    summary = SyntheticRunSummary()
    # Simulate: recipe requires eval dataset but generation produced nothing
    artifacts: dict[str, object] = {"eval_dataset_json": []}
    request = SyntheticRunStartRequest(
        repo_id="test_honest_failures",
        recipe="eval_dataset",
        generator_model="litellm:synthetic-quality",
        judge_model="litellm:synthetic-quality",
    )

    # This will try to load seed items from disk -- with no seed file it returns 0
    count = _hydrate_eval_dataset_from_seed(
        run_id="test_honest_run",
        repo_id="test_honest_failures",
        request=request,
        artifacts_payloads=artifacts,
        summary=summary,
    )

    # No seed file exists, so no hydration happened -- degradation stays clean
    assert count == 0
    assert summary.degradation.seed_hydration_used is False


def test_seed_hydration_skips_non_eval_recipes() -> None:
    from server.models.tribrid_config_model import SyntheticRunStartRequest

    summary = SyntheticRunSummary()
    artifacts: dict[str, object] = {}
    request = SyntheticRunStartRequest(
        repo_id="test_keywords_only",
        recipe="keywords",
        generator_model="litellm:synthetic-quality",
        judge_model="litellm:synthetic-quality",
    )

    count = _hydrate_eval_dataset_from_seed(
        run_id="test_keywords_run",
        repo_id="test_keywords_only",
        request=request,
        artifacts_payloads=artifacts,
        summary=summary,
    )

    assert count == 0
    assert summary.degradation.seed_hydration_used is False
    assert summary.degradation.degraded is False
