"""Integration tests for evaluation persistence."""

import pytest

from server.models.eval import EvalMetrics, EvalResult, EvalRun
from server.models.tribrid_config_model import TriBridConfig


@pytest.mark.integration
@pytest.mark.asyncio
async def test_eval_run_persistence(test_config: TriBridConfig) -> None:
    """Test that eval runs can be persisted and retrieved."""
    # This would require a real database connection
    # For now, test the model serialization
    from datetime import datetime

    metrics = EvalMetrics(
        mrr=0.75,
        recall_at_5=0.8,
        recall_at_10=0.9,
        recall_at_20=0.95,
        precision_at_5=0.6,
        ndcg_at_10=0.82,
        latency_p50_ms=50.0,
        latency_p95_ms=150.0,
    )

    results = [
        EvalResult(
            entry_id="e1",
            question="How does function X work?",
            retrieved_chunks=["c1", "c2", "c3"],
            expected_chunks=["c1", "c3"],
            reciprocal_rank=1.0,
            recall=0.67,
            latency_ms=45.0,
        )
    ]

    run = EvalRun(
        run_id="run-123",
        repo_id="repo-1",
        dataset_id="default",
        config_snapshot=test_config.model_dump(),  # Convert to dict for storage
        metrics=metrics,
        results=results,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )

    # Test serialization round-trip
    json_data = run.model_dump_json()
    restored = EvalRun.model_validate_json(json_data)

    assert restored.run_id == run.run_id
    assert restored.metrics.mrr == metrics.mrr
    assert len(restored.results) == 1


@pytest.mark.integration
def test_eval_metrics_aggregation() -> None:
    """Test aggregating metrics from multiple results."""
    results = [
        EvalResult(
            entry_id=f"e{i}",
            question=f"Question {i}",
            retrieved_chunks=[f"c{i}"],
            expected_chunks=[f"c{i}"],
            reciprocal_rank=1.0 if i % 2 == 0 else 0.5,
            recall=1.0 if i % 2 == 0 else 0.5,
            latency_ms=50.0 + i * 10,
        )
        for i in range(10)
    ]

    # Calculate MRR
    mrr = sum(r.reciprocal_rank for r in results) / len(results)
    assert 0.7 < mrr < 0.8  # Should be around 0.75

    # Calculate average recall
    avg_recall = sum(r.recall for r in results) / len(results)
    assert avg_recall == 0.75
