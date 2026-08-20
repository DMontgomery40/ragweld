from __future__ import annotations

import pytest

from server.models.tribrid_config_model import SyntheticRunSummary, TriBridConfig
from server.synthetic.orchestrator import _evaluate_quality_gate
from server.synthetic.recipes import synthetic_generation_model_category


def test_synthetic_generation_model_category_accepts_gateway_aliases() -> None:
    assert synthetic_generation_model_category("litellm:synthetic-quality") == "litellm"
    assert synthetic_generation_model_category("synthetic-quality") == "litellm_alias"


@pytest.mark.asyncio
async def test_quality_gate_fails_below_threshold() -> None:
    cfg = TriBridConfig()
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
        cfg=cfg,
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
    cfg = TriBridConfig()
    summary = SyntheticRunSummary()
    artifacts_payloads: dict[str, object] = {"eval_dataset_json": []}

    passed, reason = await _evaluate_quality_gate(
        run_id="unit_synth_gate_empty",
        repo_id="unit_synth_gate_repo",
        cfg=cfg,
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


@pytest.mark.asyncio
async def test_quality_gate_uses_custom_threshold_from_config() -> None:
    cfg = TriBridConfig()
    cfg.synthetic.quality_gate.top1_min = 0.80
    cfg.synthetic.quality_gate.sample_size = 10
    summary = SyntheticRunSummary()
    artifacts_payloads: dict[str, object] = {"eval_dataset_json": []}

    passed, reason = await _evaluate_quality_gate(
        run_id="unit_synth_gate_custom",
        repo_id="unit_synth_gate_repo",
        cfg=cfg,
        artifacts_payloads=artifacts_payloads,
        summary=summary,
    )

    assert passed is False
    assert summary.quality_gate_threshold == pytest.approx(0.80)
