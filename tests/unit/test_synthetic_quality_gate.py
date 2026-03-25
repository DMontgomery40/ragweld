from __future__ import annotations

import pytest

from server.models.tribrid_config_model import SyntheticRunSummary
from server.synthetic.orchestrator import _evaluate_quality_gate
from server.synthetic.recipes import synthetic_generation_model_category


def test_synthetic_generation_model_category_accepts_expected_prefixes() -> None:
    assert synthetic_generation_model_category("openai/gpt-4o-mini") == "openai"
    assert synthetic_generation_model_category("openrouter:openai/gpt-4o-mini") == "openrouter"
    assert synthetic_generation_model_category("local:qwen3-coder:14b") == "local"
    assert synthetic_generation_model_category("ragweld:mlx-community/Qwen3-1.7B-4bit") == "ragweld"


@pytest.mark.asyncio
async def test_quality_gate_fails_below_threshold() -> None:
    summary = SyntheticRunSummary()
    artifacts_payloads = {
        "eval_dataset_json": [
            {
                "question": "What is in file alpha?",
                "expected_paths": ["alpha.txt"],
                "expected_answer": "alpha",
                "tags": ["synthetic"],
            }
        ]
    }

    passed, reason = await _evaluate_quality_gate(
        run_id="unit_synth_gate",
        repo_id="unit_synth_gate_repo",
        artifacts_payloads=artifacts_payloads,
        summary=summary,
    )

    assert passed is False
    assert isinstance(reason, str)
    assert summary.quality_gate_passed is False
    assert summary.quality_gate_threshold == pytest.approx(0.40)
    assert "quality_eval_json" in artifacts_payloads
    if summary.quality_top1_accuracy is not None:
        assert summary.quality_top1_accuracy == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_quality_gate_fails_when_no_eval_items() -> None:
    summary = SyntheticRunSummary()
    artifacts_payloads: dict[str, object] = {"eval_dataset_json": []}

    passed, reason = await _evaluate_quality_gate(
        run_id="unit_synth_gate_empty",
        repo_id="unit_synth_gate_repo",
        artifacts_payloads=artifacts_payloads,
        summary=summary,
    )

    assert passed is False
    assert isinstance(reason, str)
    assert "no eval items generated" in reason
    assert summary.quality_gate_passed is False
    assert summary.quality_sample_size == 0
    assert summary.quality_gate_threshold == pytest.approx(0.40)
    assert summary.quality_failure_reason == reason
    assert "quality_eval_json" in artifacts_payloads
