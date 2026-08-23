"""Held-out evaluation must be held out by query, and pairs must not multiply a positive per mined negative."""

from __future__ import annotations

from server.training.mlx_qwen3_trainer import deterministic_split_by_query, triplets_to_pairs
from server.training.reranker_trainer import MaterializedTriplet

Q1 = "Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?"
Q2 = "Why did Barry Cohen consider switching plane management from Jet Aviation to EJM?"
Q3 = "Who asked Jeffrey Epstein whether he could speak now on 2016-11-12?"


def _rows() -> list[MaterializedTriplet]:
    rows: list[MaterializedTriplet] = []
    for query in (Q1, Q2, Q3):
        for index in range(5):
            rows.append(MaterializedTriplet(query=query, positive_text=f"pos for {query}", negative_text=f"neg {index} for {query}"))
    return rows


def test_split_by_query_never_puts_one_question_in_both_halves() -> None:
    rows = _rows()
    for seed in range(5):
        train, dev = deterministic_split_by_query(rows, dev_split=0.34, seed=seed)
        train_queries = {r.query for r in train}
        dev_queries = {r.query for r in dev}
        assert train_queries and dev_queries
        assert not (train_queries & dev_queries)
        assert len(train) + len(dev) == len(rows)


def test_split_by_query_is_deterministic_for_a_seed() -> None:
    rows = _rows()
    assert deterministic_split_by_query(rows, dev_split=0.34, seed=3) == deterministic_split_by_query(rows, dev_split=0.34, seed=3)


def test_pairs_emit_one_positive_per_query_and_cap_negatives_by_ratio() -> None:
    rows = [r for r in _rows() if r.query == Q1]
    pairs = triplets_to_pairs(rows, negative_ratio=3)
    positives = [p for p in pairs if p.label == 1]
    negatives = [p for p in pairs if p.label == 0]
    assert len(positives) == 1
    assert positives[0].document == f"pos for {Q1}"
    assert len(negatives) == 3
    assert len({p.document for p in negatives}) == 3
    assert all(p.query == Q1 for p in pairs)


def test_split_by_query_holds_out_at_least_one_question_whenever_two_exist() -> None:
    rows = [r for r in _rows() if r.query in (Q1, Q2)]
    train, dev = deterministic_split_by_query(rows, dev_split=0.1, seed=0)
    assert {r.query for r in dev} and {r.query for r in train}
    assert not ({r.query for r in dev} & {r.query for r in train})
    single = [r for r in _rows() if r.query == Q1]
    train_only, dev_empty = deterministic_split_by_query(single, dev_split=0.1, seed=0)
    assert train_only and dev_empty == []


def test_pairs_never_borrow_negatives_from_other_queries() -> None:
    rows = [
        MaterializedTriplet(query=Q1, positive_text="pos q1", negative_text="neg q1"),
        MaterializedTriplet(query=Q2, positive_text="pos q2", negative_text="neg q2 a"),
        MaterializedTriplet(query=Q2, positive_text="pos q2", negative_text="neg q2 b"),
    ]
    pairs = triplets_to_pairs(rows, negative_ratio=5)
    q1_negatives = [p.document for p in pairs if p.query == Q1 and p.label == 0]
    assert q1_negatives == ["neg q1"]
    q2_negatives = [p.document for p in pairs if p.query == Q2 and p.label == 0]
    assert q2_negatives == ["neg q2 a", "neg q2 b"]


def _decide(**overrides):
    from server.training.promotion import decide_auto_promotion

    params = dict(
        primary_value=0.91,
        baseline_primary=0.80,
        baseline_state="measured",
        dev_examples=3,
        promote_if_improves=True,
        epsilon=0.01,
        backend="mlx_qwen3",
        artifact_dir="/runs/r1/model",
    )
    params.update(overrides)
    return decide_auto_promotion(**params)


def test_auto_promotion_refused_without_dev_split_and_message_renders_na_baseline() -> None:
    # Codex pass 4: the no-dev branch left baseline_primary=None and the completion log
    # formatted it with :.6f, so a correctly refused promotion crashed the finished run.
    decision = _decide(dev_examples=0, baseline_primary=None, baseline_state="absent")
    assert decision.promote is False
    assert "no held-out dev split" in (decision.notice or "")
    assert "baseline=n/a (no held-out dev split)" in decision.message
    assert "primary=0.910000" in decision.message
    assert "Run artifact preserved at /runs/r1/model" in decision.message


def test_auto_promotion_gates_on_beating_measured_baseline_by_epsilon() -> None:
    assert _decide(primary_value=0.82).promote is True
    assert _decide(primary_value=0.81).promote is False  # equal to baseline + eps is not an improvement
    assert _decide(primary_value=0.5, promote_if_improves=False).promote is True
    assert "baseline=0.800000" in _decide(primary_value=0.5).message


def test_auto_promotion_minimize_goal_for_loss_metrics() -> None:
    # The Learning Agent gates on eval loss: lower is better.
    kwargs = dict(goal="minimize", metric_label="final_eval_loss", baseline_primary=1.0)
    assert _decide(primary_value=0.98, **kwargs).promote is True
    assert _decide(primary_value=0.99, **kwargs).promote is False  # equal to baseline - eps
    assert _decide(primary_value=1.2, **kwargs).promote is False
    assert "final_eval_loss=1.200000" in _decide(primary_value=1.2, **kwargs).message


def test_auto_promotion_promotes_first_artifact_when_no_baseline_exists() -> None:
    for state in ("absent", "incompatible"):
        decision = _decide(baseline_primary=None, baseline_state=state, primary_value=0.3)
        assert decision.promote is True, state
        assert decision.notice is None


def test_auto_promotion_refuses_when_active_baseline_evaluation_failed() -> None:
    # Codex pass 5 P1: a failed baseline eval used to look like "no active artifact" and
    # the unmeasured run overwrote a live model. Unknown quality is not absence.
    decision = _decide(baseline_primary=None, baseline_state="failed", primary_value=0.99)
    assert decision.promote is False
    assert "baseline evaluation failed" in (decision.notice or "")
    assert "baseline=n/a (baseline evaluation failed)" in decision.message
    # Only the operator disabling the improvement gate lets it through.
    assert _decide(baseline_primary=None, baseline_state="failed", promote_if_improves=False).promote is True


def test_auto_promotion_refuses_when_the_final_measurement_is_missing() -> None:
    # Same class, other side of the comparison: no final held-out value means nothing was proven.
    decision = _decide(primary_value=None)
    assert decision.promote is False
    assert "final held-out evaluation produced no measurement" in (decision.notice or "")
    assert "primary=n/a" in decision.message
    assert _decide(primary_value=None, promote_if_improves=False).promote is True


def test_auto_promotion_no_dev_split_wins_over_every_baseline_state() -> None:
    for state in ("absent", "incompatible", "measured", "failed"):
        for flag in (True, False):
            decision = _decide(
                dev_examples=0,
                promote_if_improves=flag,
                baseline_state=state,
                baseline_primary=0.1 if state == "measured" else None,
                primary_value=0.99,
            )
            assert decision.promote is False, (state, flag)


def test_auto_promotion_measured_state_without_a_value_is_a_failed_baseline() -> None:
    # A caller claiming "measured" with nothing to show is an evaluation that produced no number.
    decision = _decide(baseline_primary=None, baseline_state="measured", primary_value=0.99)
    assert decision.promote is False
    assert "baseline evaluation failed" in (decision.notice or "")


def test_auto_promotion_never_promotes_a_non_finite_final_metric() -> None:
    # Codex pass 6 P1: NaN/inf fell through to promote=True with an absent baseline.
    import math

    for value in (math.nan, math.inf, -math.inf):
        for state, baseline in (("absent", None), ("incompatible", None), ("measured", 0.5), ("failed", None)):
            for flag in (True, False):
                decision = _decide(primary_value=value, baseline_state=state, baseline_primary=baseline, promote_if_improves=flag)
                assert decision.promote is False, (value, state, flag)
                assert "not a number" in (decision.notice or ""), (value, state, flag)


def test_auto_promotion_treats_a_non_finite_baseline_as_failed() -> None:
    import math

    decision = _decide(baseline_state="measured", baseline_primary=math.nan, primary_value=0.99)
    assert decision.promote is False
    assert "baseline evaluation failed" in (decision.notice or "")
    assert _decide(baseline_state="measured", baseline_primary=math.inf, primary_value=0.99, promote_if_improves=False).promote is True


def test_finite_metric_guards_keep_nan_out_of_run_records() -> None:
    # Codex pass 7: NaN/inf metrics reached primary_series, best/final values and the persisted
    # summary by attribute assignment, and FastAPI later refused to serialize the run.
    import math

    from server.training.metric_values import finite_metrics, finite_or_none, stability_stddev

    assert finite_or_none(0.5) == 0.5
    assert finite_or_none("0.25") == 0.25
    for bad in (None, math.nan, math.inf, -math.inf, "nine", True, "9" * 400):
        assert finite_or_none(bad) is None, bad
    kept, dropped = finite_metrics({"mrr": 0.7, "ndcg": math.nan, "map": math.inf, "train_loss": "x"})
    assert kept == {"mrr": 0.7}
    assert dropped == ["ndcg", "map", "train_loss"]
    assert stability_stddev([]) is None
    assert stability_stddev([0.5, 0.5, 0.5]) == 0.0
    assert stability_stddev([0.2, math.nan, 0.4], window=5) == 0.1  # the NaN is not part of the window


def test_reranker_primary_value_is_none_not_zero_when_the_metric_is_absent_or_non_finite() -> None:
    import math

    from server.api.reranker import _format_metrics_for_run, _primary_value
    from server.models.tribrid_config_model import RerankerTrainRun

    run = RerankerTrainRun.model_construct(primary_metric="mrr", primary_k=10)
    assert _primary_value(run, _format_metrics_for_run(run, {"mrr": 0.8, "ndcg": 0.7, "map": 0.6})) == 0.8
    assert _primary_value(run, _format_metrics_for_run(run, {"mrr": math.nan, "ndcg": 0.7, "map": 0.6})) is None
    assert _primary_value(run, _format_metrics_for_run(run, {"ndcg": 0.7})) is None
    assert "mrr@10" not in _format_metrics_for_run(run, {"mrr": math.inf})


def test_stability_stddev_is_numerically_stable_and_never_infinite() -> None:
    # Codex pass 8: naive sum-of-squares on 1e308 inputs produced inf, which then reached the summary.
    from server.training.metric_values import stability_stddev

    assert stability_stddev([1e308, 1e308]) == 0.0
    value = stability_stddev([1e308, -1e308])
    assert value is None or value >= 0.0


def test_training_event_and_summary_boundaries_refuse_non_finite_values() -> None:
    # Codex pass 8: event/summary floats were unconstrained, so a NaN progress metric persisted as
    # `NaN` and Starlette refused to serialize the run. The boundary now fails closed at
    # construction *and* on attribute assignment.
    import math
    from datetime import UTC, datetime

    import pytest
    from pydantic import ValidationError

    from server.models.tribrid_config_model import (
        AgentTrainMetricEvent,
        AgentTrainRunSummary,
        RerankerTrainMetricEvent,
        RerankerTrainRunSummary,
    )

    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        AgentTrainMetricEvent(type="progress", ts=now, run_id="r", metrics={"train_loss": math.nan})
    with pytest.raises(ValidationError):
        RerankerTrainMetricEvent(type="telemetry", ts=now, run_id="r", loss=math.inf)
    for cls in (RerankerTrainRunSummary, AgentTrainRunSummary):
        summary = cls()
        with pytest.raises(ValidationError):
            summary.primary_metric_final = math.nan
        with pytest.raises(ValidationError):
            summary.stability_stddev = math.inf
        summary.primary_metric_final = 0.5
        assert summary.primary_metric_final == 0.5


def test_event_builders_preserve_zero_and_drop_only_absent_or_non_finite() -> None:
    # Codex pass 9: `finite_or_none(v) or None` and `int(v or 0) or None` erased step 0, epoch 0.0
    # and percent 0.0 from persisted events, so the first epoch showed as null.
    import math
    from datetime import UTC, datetime

    from server.api.agent import build_agent_progress_event, build_agent_telemetry_event
    from server.api.reranker import build_reranker_progress_event, build_reranker_telemetry_event

    now = datetime.now(UTC)
    payload = {"step": 0, "epoch": 0.0, "percent": 0.0, "message": "warmup", "metrics": {"train_loss": 0.0, "lr": math.nan}}
    for build in (build_reranker_progress_event, build_agent_progress_event):
        event, dropped = build("r1", now, payload)
        assert (event.step, event.epoch, event.percent) == (0, 0.0, 0.0)
        assert event.metrics == {"train_loss": 0.0}
        assert dropped == ["lr"]
        full, _ = build("r1", now, {"step": 12, "epoch": 1.5, "percent": 100.0})
        assert (full.step, full.epoch, full.percent) == (12, 1.5, 100.0)
        absent, _ = build("r1", now, {})
        assert (absent.step, absent.epoch, absent.percent, absent.metrics) == (None, None, None, None)
        bad, _ = build("r1", now, {"step": "x", "epoch": math.inf, "percent": "nan"})
        assert (bad.step, bad.epoch, bad.percent) == (None, None, None)
    telemetry = {"step": 0, "epoch": 0.0, "proj_x": 0.0, "proj_y": -0.5, "loss": math.nan, "lr": 0.0, "grad_norm": math.inf, "step_time_ms": 0.0, "sample_count": 0}
    for build in (build_reranker_telemetry_event, build_agent_telemetry_event):
        event = build("r1", now, telemetry)
        assert (event.step, event.epoch, event.proj_x, event.proj_y, event.lr, event.step_time_ms, event.sample_count) == (0, 0.0, 0.0, -0.5, 0.0, 0.0, 0)
        assert event.loss is None and event.grad_norm is None


def test_diff_stability_fallback_uses_the_stable_helper() -> None:
    # Codex pass 9: the run-diff fallback kept the naive sum-of-squares and overflowed on two
    # finite 1e308 metric events.
    from datetime import UTC, datetime

    from server.api.reranker import _compute_stability_stddev_from_events
    from server.models.tribrid_config_model import RerankerTrainMetricEvent, RerankerTrainRun

    run = RerankerTrainRun.model_construct(primary_metric="mrr", primary_k=10)
    now = datetime.now(UTC)
    # Codex pass 11: the persisted event boundary now refuses out-of-domain scores outright ...
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RerankerTrainMetricEvent(type="metrics", ts=now, run_id="r", metrics={"mrr@10": 1e308})
    # ... and the fallback itself is numerically stable on the widest in-domain spread.
    events = [
        RerankerTrainMetricEvent(type="metrics", ts=now, run_id="r", metrics={"mrr@10": 1.0}),
        RerankerTrainMetricEvent(type="metrics", ts=now, run_id="r", metrics={"mrr@10": 0.0}),
    ]
    assert _compute_stability_stddev_from_events(run, events) == 0.5
    assert _compute_stability_stddev_from_events(run, events[:1]) == 0.0
    assert _compute_stability_stddev_from_events(run, []) is None


def test_metric_domains_reject_impossible_finite_values() -> None:
    # Codex pass 10: FiniteFloat only excluded NaN/inf; eval_loss=-1 and mrr=2.0 promoted artifacts.
    from server.training.metric_values import finite_metrics, non_negative_or_none, step_or_none

    kept, dropped = finite_metrics({"mrr": 2.0, "ndcg": 0.9, "map": -0.1, "eval_loss": -1.0, "train_loss": 0.3, "custom": -5.0})
    assert kept == {"ndcg": 0.9, "train_loss": 0.3, "custom": -5.0}
    assert dropped == ["mrr", "map", "eval_loss"]
    assert non_negative_or_none(-30.0) is None and non_negative_or_none(0.0) == 0.0
    # steps are integral: 1.5 is not a step and must not be truncated to 1
    assert step_or_none(1.5) is None and step_or_none(2.0) == 2 and step_or_none("12") == 12 and step_or_none("1.5") is None


def test_reranker_formatting_drops_out_of_domain_scores_and_promotion_refuses_them() -> None:
    from server.api.reranker import (
        _format_metrics_for_run,
        _non_finite_metric_names,
        _primary_value,
    )
    from server.models.tribrid_config_model import RerankerTrainRun

    run = RerankerTrainRun.model_construct(primary_metric="mrr", primary_k=10)
    raw = {"mrr": 2.0, "ndcg": 5.0, "map": 3.0}
    assert _format_metrics_for_run(run, raw) == {}
    assert _non_finite_metric_names(raw) == ["mrr", "ndcg", "map"]
    assert _primary_value(run, _format_metrics_for_run(run, raw)) is None
    assert _decide(primary_value=None, baseline_state="absent", baseline_primary=None).promote is False


def test_persisted_event_boundary_rejects_out_of_domain_metrics_and_telemetry() -> None:
    # Codex pass 11: domains were enforced in the builders only; a hand-written or historical
    # event with mrr@10=2.0 / eval_loss=-1 / negative lr still validated and re-entered diffs.
    from datetime import UTC, datetime

    import pytest
    from pydantic import ValidationError

    from server.models.tribrid_config_model import (
        AgentTrainMetricEvent,
        RerankerTrainMetricEvent,
        RerankerTrainRunSummary,
    )

    now = datetime.now(UTC)
    for ctor, kwargs in (
        (RerankerTrainMetricEvent, {"type": "metrics", "metrics": {"mrr@10": 2.0}}),
        (AgentTrainMetricEvent, {"type": "metrics", "metrics": {"eval_loss": -1.0}}),
        (RerankerTrainMetricEvent, {"type": "telemetry", "loss": -0.5}),
        (RerankerTrainMetricEvent, {"type": "telemetry", "lr": -1e-3}),
        (AgentTrainMetricEvent, {"type": "telemetry", "grad_norm": -2.0}),
        (AgentTrainMetricEvent, {"type": "telemetry", "step_time_ms": -1.0}),
    ):
        with pytest.raises(ValidationError):
            ctor(ts=now, run_id="r", **kwargs)
    with pytest.raises(ValidationError):
        RerankerTrainRunSummary(primary_metric_final=2.0)
    ok = RerankerTrainMetricEvent(type="metrics", ts=now, run_id="r", metrics={"mrr@10": 0.7, "custom": -3.0})
    assert ok.metrics == {"mrr@10": 0.7, "custom": -3.0}  # unknown families carry no domain


def test_promotion_swap_restores_the_previous_artifact_when_post_swap_work_fails(tmp_path) -> None:
    # Codex pass 11 P1: the active artifact was replaced before lineage/run-record writes; a
    # failure there left a new artifact serving while the run was not durably completed.
    import pytest

    from server.training.promotion import PromotionSwap

    active = tmp_path / "active"
    active.mkdir()
    (active / "adapter.safetensors").write_text("v1", encoding="utf-8")
    artifact = tmp_path / "runs" / "r2" / "model"
    artifact.mkdir(parents=True)
    (artifact / "adapter.safetensors").write_text("v2", encoding="utf-8")

    swap = PromotionSwap(artifact, active).begin()
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v2"  # serving the candidate
    with pytest.raises(OSError):
        try:
            raise OSError(28, "No space left on device")  # lineage write fails after the swap
        except OSError:
            swap.rollback()
            raise
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v1"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".bak_") or p.name.startswith(".tmp_")]

    swap = PromotionSwap(artifact, active).begin()
    assert swap.commit() is None
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v2"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".bak_") or p.name.startswith(".tmp_")]

    # first promotion ever: nothing to restore, rollback removes the candidate
    fresh = tmp_path / "fresh_active"
    swap = PromotionSwap(artifact, fresh).begin()
    assert fresh.exists()
    swap.rollback()
    assert not fresh.exists()


def test_promotion_swap_serializes_overlapping_promotions_across_processes(tmp_path) -> None:
    # Codex pass 12 P1: two unlocked swaps could undo each other (A rolls back after B begins and
    # deletes B's candidate). The flock on the active path serializes them, so the last committed
    # promotion is what serves.
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    from server.training.promotion import PromotionSwap

    active = tmp_path / "active"
    active.mkdir()
    (active / "adapter.safetensors").write_text("v0", encoding="utf-8")
    artifacts = {}
    for tag in ("alpha", "beta", "gamma"):
        d = tmp_path / "runs" / tag / "model"
        d.mkdir(parents=True)
        (d / "adapter.safetensors").write_text(tag, encoding="utf-8")
        artifacts[tag] = d
    script = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
        from server.training.promotion import PromotionSwap
        tag, outcome = sys.argv[1], sys.argv[2]
        swap = PromotionSwap(Path({str(tmp_path)!r}) / "runs" / tag / "model", Path({str(active)!r})).begin()
        time.sleep(0.3)  # widen the window: without the lock another process would begin here
        if outcome == "rollback":
            swap.rollback()
        else:
            swap.commit()
        """
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", script, "alpha", "rollback"]),
        subprocess.Popen([sys.executable, "-c", script, "beta", "commit"]),
        subprocess.Popen([sys.executable, "-c", script, "gamma", "rollback"]),
    ]
    for proc in procs:
        assert proc.wait(timeout=60) == 0
    # beta is the only committed promotion: whatever the interleaving, it is what serves
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "beta"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".bak_") or p.name.startswith(".tmp_")]
    lock = tmp_path / ".active.promote.lock"
    assert lock.exists()
    # and a same-process second swap still works after the lock was released
    PromotionSwap(artifacts["gamma"], active).begin().commit()
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "gamma"


def test_promotion_swap_begin_failure_leaves_the_active_artifact_untouched(tmp_path) -> None:
    # Codex pass 12 P1: a failed begin (unreadable artifact, failed rename) must not strand the
    # previous tree under .bak_ with the active path missing.
    import pytest

    from server.training.promotion import PromotionSwap

    active = tmp_path / "active"
    active.mkdir()
    (active / "adapter.safetensors").write_text("v1", encoding="utf-8")
    missing_artifact = tmp_path / "runs" / "nope" / "model"
    with pytest.raises(FileNotFoundError):
        PromotionSwap(missing_artifact, active).begin()
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v1"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".bak_") or p.name.startswith(".tmp_")]
    # the lock was released: a later promotion proceeds
    good = tmp_path / "runs" / "good" / "model"
    good.mkdir(parents=True)
    (good / "adapter.safetensors").write_text("v2", encoding="utf-8")
    PromotionSwap(good, active).begin().commit()
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v2"


def test_lineage_alias_compensation_is_compare_and_swap(tmp_path) -> None:
    # Codex pass 12/13: rolling back the artifact left the `promoted` alias pointing at the failed
    # candidate, and a blind restore would also erase an unrelated concurrent alias move.
    import json
    from datetime import UTC, datetime

    from server.lineage.registry import (
        _alias_path,
        load_alias,
        restore_aliases,
        snapshot_aliases,
    )
    from server.models.tribrid_config_model import LineageAlias

    root = tmp_path / "lineage"
    repo = "alias-corpus"

    def _point(alias: str, bundle_id: str) -> None:
        path = _alias_path(repo, alias, root=root)  # type: ignore[arg-type]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(LineageAlias(alias=alias, repo_id=repo, bundle_id=bundle_id, updated_at=datetime.now(UTC)).model_dump(mode="json", by_alias=True)),  # type: ignore[arg-type]
            encoding="utf-8",
        )

    before = snapshot_aliases(repo_id=repo, names=("current", "promoted"), root=root)
    assert before == {"current": None, "promoted": None}
    assert restore_aliases(repo_id=repo, snapshot=before, root=root) == []

    _point("current", "A")
    before = snapshot_aliases(repo_id=repo, names=("current", "promoted"), root=root)
    # the failed transaction wrote bundle C to both aliases
    _point("current", "C")
    _point("promoted", "C")
    assert set(restore_aliases(repo_id=repo, snapshot=before, only_if_pointing_at="C", root=root)) == {"current", "promoted"}
    assert load_alias(repo, "current", root=root).bundle_id == "A"  # type: ignore[union-attr]
    assert load_alias(repo, "promoted", root=root) is None
    # a concurrent, unrelated update moved `current` to B after our snapshot: not ours to undo
    _point("current", "B")
    _point("promoted", "C")
    assert restore_aliases(repo_id=repo, snapshot=before, only_if_pointing_at="C", root=root) == ["promoted"]
    assert load_alias(repo, "current", root=root).bundle_id == "B"  # type: ignore[union-attr]


def test_promotion_transaction_compensates_aliases_and_artifact_independently(tmp_path) -> None:
    # Codex pass 13 P1: alias compensation and artifact rollback ran in one try; a failing alias
    # write skipped the artifact rollback and left the candidate active with the lock held.
    import pytest

    from server.training.promotion import (
        PromotionRollbackError,
        PromotionSwap,
        run_promotion_transaction,
    )

    active = tmp_path / "active"
    active.mkdir()
    (active / "adapter.safetensors").write_text("v1", encoding="utf-8")
    artifact = tmp_path / "runs" / "r2" / "model"
    artifact.mkdir(parents=True)
    (artifact / "adapter.safetensors").write_text("v2", encoding="utf-8")

    def failing_work() -> str | None:
        raise OSError(28, "No space left on device")

    swap = PromotionSwap(artifact, active)
    with pytest.raises(OSError):
        run_promotion_transaction(swap=swap, repo_id="txn-corpus", work=failing_work)
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v1"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".bak_") or p.name.startswith(".tmp_")]
    # the lock was released: the next transaction proceeds and commits
    assert run_promotion_transaction(swap=PromotionSwap(artifact, active), repo_id="txn-corpus", work=lambda: None) is None
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v2"

    # a rollback that cannot restore is reported, never hidden: the retained tree vanished
    swap = PromotionSwap(artifact, active)
    swap.begin()
    assert swap.previous is not None
    import shutil

    shutil.rmtree(swap.previous)
    with pytest.raises(PromotionRollbackError, match="retained previous artifact missing"):
        swap.rollback()
    assert active.exists()  # the candidate was deliberately left in place rather than leaving nothing

    # Codex pass 14 P1: the candidate is parked before the previous tree is restored, so a failed
    # restore rename never leaves the active path empty. Make the previous tree unrenamable by
    # turning it into a file in a read-only parent is not portable; instead prove the order: the
    # previous tree is restored while the candidate still exists on disk (parked), then removed.
    (active / "adapter.safetensors").write_text("candidate", encoding="utf-8")
    swap = PromotionSwap(artifact, active)
    swap.begin()
    swap.rollback()
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "candidate"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith((".bak_", ".tmp_", ".rollback_"))]


def test_await_uncancellable_reraises_cancellation_even_when_the_worker_later_fails() -> None:
    # Codex pass 14 P2: a worker that failed after the cancellation was caught surfaced its own
    # exception instead of the cancellation the task received.
    import asyncio
    import threading
    import time

    from server.training.promotion import await_uncancellable

    started = threading.Event()

    def failing_work() -> None:
        started.set()
        time.sleep(0.3)
        raise RuntimeError("worker failed after cancel")

    async def scenario() -> None:
        task = asyncio.create_task(await_uncancellable(failing_work))
        await asyncio.to_thread(started.wait, 5.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError as exc:
            assert isinstance(exc.__cause__, RuntimeError)  # the worker failure is chained, not swallowed
        else:
            raise AssertionError("the cancellation must win")

    asyncio.run(scenario())


def test_run_records_are_written_atomically(tmp_path) -> None:
    # Codex pass 14 P1: Path.write_text truncated run.json before writing; ENOSPC left a torn record.
    import json

    from server.training.atomic_json import write_json_atomic

    path = tmp_path / "run.json"
    write_json_atomic(path, {"status": "running"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "running"}
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]

    class Explodes:
        pass

    try:
        write_json_atomic(path, {"status": Explodes()})  # not JSON serialisable: the write fails mid-way
    except TypeError:
        pass
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "running"}  # the previous record survived
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_sync_cache_invalidation_keeps_an_in_flight_load_from_caching_stale_weights(tmp_path) -> None:
    # Codex pass 14/15: cache invalidation ran after commit, a load that started before the swap
    # could re-insert a model built from the old files, and a relative config path never matched
    # the absolute cache key. Generation counter + canonical paths close both.
    import os

    import server.retrieval.mlx_qwen3 as mlx

    mlx._MLX_CACHE.clear()
    active = tmp_path / "models" / "learning-reranker-active"
    active.mkdir(parents=True)
    canonical = mlx.canonical_adapter_path(str(active))
    key = ("base", canonical, 16, 32.0, 0.05, ("q_proj",))
    generation = mlx._MLX_CACHE_GENERATION
    mlx.invalidate_mlx_qwen3_cache_sync(str(active))
    assert mlx._MLX_CACHE_GENERATION == generation + 1
    mlx._MLX_CACHE[key] = object()  # type: ignore[assignment]
    mlx.invalidate_mlx_qwen3_cache_sync(str(tmp_path / "models" / "other"))
    assert key in mlx._MLX_CACHE  # a different adapter path is untouched
    # the same directory spelled through a symlink-free but non-canonical path still matches
    mlx.invalidate_mlx_qwen3_cache_sync(str(tmp_path / "models" / "." / "learning-reranker-active"))
    assert key not in mlx._MLX_CACHE
    del os


def test_promotion_transaction_compensates_when_the_lineage_lock_cannot_be_taken(tmp_path) -> None:
    # Codex pass 15 P1: lock construction/acquisition happened after begin but outside the
    # compensation block; a lineage-store failure left the candidate active with the swap open.
    import os

    import pytest

    from server.training.promotion import PromotionSwap, run_promotion_transaction

    active = tmp_path / "active"
    active.mkdir()
    (active / "adapter.safetensors").write_text("v1", encoding="utf-8")
    artifact = tmp_path / "runs" / "r2" / "model"
    artifact.mkdir(parents=True)
    (artifact / "adapter.safetensors").write_text("v2", encoding="utf-8")
    bad_root = tmp_path / "lineage-root-is-a-file"
    bad_root.write_text("not a directory", encoding="utf-8")
    previous_env = os.environ.get("RAGWELD_LINEAGE_ROOT")
    os.environ["RAGWELD_LINEAGE_ROOT"] = str(bad_root)
    try:
        from server.dependency_errors import DependencyUnavailableError

        with pytest.raises((DependencyUnavailableError, OSError)):
            run_promotion_transaction(swap=PromotionSwap(artifact, active), repo_id="lock-corpus", work=lambda: None)
    finally:
        if previous_env is None:
            os.environ.pop("RAGWELD_LINEAGE_ROOT", None)
        else:
            os.environ["RAGWELD_LINEAGE_ROOT"] = previous_env
    # nothing changed: the lineage store was resolved before the swap began
    assert (active / "adapter.safetensors").read_text(encoding="utf-8") == "v1"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith((".bak_", ".tmp_", ".rollback_"))]


def test_await_uncancellable_lets_the_transaction_settle_before_propagating_cancellation() -> None:
    # Codex pass 13 P1: cancelling the await abandoned the worker mid-swap with the lock held.
    import asyncio
    import threading
    import time

    from server.training.promotion import await_uncancellable

    started = threading.Event()
    finished = threading.Event()

    def slow_work() -> str:
        started.set()
        time.sleep(0.4)
        finished.set()
        return "settled"

    async def scenario() -> None:
        task = asyncio.create_task(await_uncancellable(slow_work))
        await asyncio.to_thread(started.wait, 5.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation must propagate once the work settled")
        assert finished.is_set()  # the worker ran to completion before the cancellation surfaced

    asyncio.run(scenario())


def test_canonical_adapter_path_is_repo_root_relative_not_cwd_relative(tmp_path) -> None:
    # Codex pass 16: Path.resolve() made `models/learning-reranker-active` depend on the process CWD.
    import os

    from server.reranker.artifacts import resolve_project_path
    from server.retrieval.mlx_qwen3 import canonical_adapter_path

    expected = str(resolve_project_path("models/learning-reranker-active").resolve())
    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert canonical_adapter_path("models/learning-reranker-active") == expected
    finally:
        os.chdir(cwd)
    assert canonical_adapter_path(expected) == expected
