import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from server.api import agent as agent_api
from server.api import reranker as reranker_api
from server.models.tribrid_config_model import AgentTrainRun, CorpusEvalProfile, RerankerTrainRun, TriBridConfig


def _profile(corpus_id: str) -> CorpusEvalProfile:
    return CorpusEvalProfile(
        repo_id=corpus_id,
        label_kind="pairwise",
        avg_relevant_per_query=0.0,
        p95_relevant_per_query=0.0,
        recommended_metric="mrr",
        recommended_k=10,
        rationale="guard-regression",
    )


def _cleanup_run_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def test_reranker_active_guard_blocks_recent_failed_run_but_expires_after_grace() -> None:
    corpus_id = "pytest_reranker_guard"
    started_at = datetime.now(UTC)
    run_id = f"{corpus_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_dir = reranker_api._RUNS_DIR / run_id
    cfg = TriBridConfig()
    run = RerankerTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="failed",
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="mrr",
        primary_k=10,
        metrics_available=["mrr@10", "ndcg@10", "map"],
        metric_profile=_profile(corpus_id),
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
    )

    try:
        reranker_api._save_run(run)

        reranker_api._mark_train_start_guard(corpus_id, run_id, at=datetime.now(UTC))
        assert reranker_api._active_run_id_for_corpus(corpus_id) == run_id

        expired = datetime.now(UTC) - reranker_api._TRAIN_START_GRACE - timedelta(milliseconds=1)
        reranker_api._mark_train_start_guard(corpus_id, run_id, at=expired)
        assert reranker_api._active_run_id_for_corpus(corpus_id) is None
    finally:
        reranker_api._train_start_guard.pop(corpus_id, None)
        _cleanup_run_dir(run_dir)


def test_agent_active_guard_blocks_recent_failed_run_but_expires_after_grace() -> None:
    corpus_id = "pytest_agent_guard"
    started_at = datetime.now(UTC)
    run_id = f"{corpus_id}__{started_at.strftime('%Y%m%d_%H%M%S')}"
    run_dir = agent_api._RUNS_DIR / run_id
    cfg = TriBridConfig()
    run = AgentTrainRun(
        run_id=run_id,
        repo_id=corpus_id,
        status="failed",
        started_at=started_at,
        completed_at=started_at + timedelta(seconds=1),
        config_snapshot=cfg.model_dump(mode="json"),
        config=cfg.to_flat_dict(),
        primary_metric="eval_loss",
        primary_goal="minimize",
        metrics_available=["train_loss", "eval_loss"],
        epochs=1,
        batch_size=1,
        lr=0.0001,
        warmup_ratio=0.0,
        max_length=128,
    )

    try:
        agent_api._save_run(run)

        agent_api._mark_train_start_guard(corpus_id, run_id, at=datetime.now(UTC))
        assert agent_api._active_run_id_for_corpus(corpus_id) == run_id

        expired = datetime.now(UTC) - agent_api._TRAIN_START_GRACE - timedelta(milliseconds=1)
        agent_api._mark_train_start_guard(corpus_id, run_id, at=expired)
        assert agent_api._active_run_id_for_corpus(corpus_id) is None
    finally:
        agent_api._train_start_guard.pop(corpus_id, None)
        _cleanup_run_dir(run_dir)
