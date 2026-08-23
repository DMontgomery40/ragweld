from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import UTC, datetime

from server.api.reranker import (
    _append_diagnostic,
    _append_event,
    _load_diagnostics,
    _load_events,
    _run_dir,
)
from server.models.tribrid_config_model import RerankerTrainMetricEvent
from server.observability.metrics import render_latest


def _metric_value(text: str, metric_line_prefix: str) -> float:
    pattern = re.compile(rf"^{re.escape(metric_line_prefix)} ([0-9eE+\\.-]+)$", re.MULTILINE)
    match = pattern.search(text)
    assert match, f"missing metric line: {metric_line_prefix}"
    return float(match.group(1))


def test_reranker_diagnostics_persist_operator_hint() -> None:
    run_id = f"pytest_reranker_diag_{uuid.uuid4().hex[:8]}"
    try:
        _append_diagnostic(
            run_id,
            level="error",
            event="train_run_failed",
            message="Training failed during materialize_triplets",
            operator_hint="Triplet doc_ids did not resolve under the active corpus root.",
            fields={"stage": "materialize_triplets", "triplets_in": 12},
        )

        records = _load_diagnostics(run_id, limit=10)
        assert len(records) == 1
        assert records[0].event == "train_run_failed"
        assert records[0].operator_hint == "Triplet doc_ids did not resolve under the active corpus root."
        assert records[0].fields["stage"] == "materialize_triplets"
    finally:
        shutil.rmtree(_run_dir(run_id), ignore_errors=True)


def test_reranker_event_stream_updates_prometheus_training_metrics() -> None:
    run_id = f"pytest_reranker_metrics_{uuid.uuid4().hex[:8]}"
    try:
        before_text = render_latest()[0].decode("utf-8")
        before_events = _metric_value(before_text, 'tribrid_reranker_train_events_total{type="telemetry"}')

        _append_event(
            run_id,
            RerankerTrainMetricEvent(
                type="telemetry",
                ts=datetime.now(UTC),
                run_id=run_id,
                step=7,
                epoch=1.5,
                operator_hint="Inspect the MLX training loop if telemetry stalls.",
                loss=0.25,
                lr=0.0001,
                grad_norm=0.75,
                step_time_ms=12.0,
                sample_count=16,
            ),
        )

        events, unreadable = _load_events(run_id, limit=10)
        assert len(events) == 1
        assert unreadable.count == 0 and unreadable.first_reason is None
        assert events[0].operator_hint == "Inspect the MLX training loop if telemetry stalls."

        # Codex pass 10: a record that no longer validates (NaN from an older build, a torn line)
        # is counted and explained, never silently dropped from the trace.
        metrics_path = _run_dir(run_id) / "metrics.jsonl"
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(f'{{"type": "metrics", "ts": "2026-08-23T00:00:00Z", "run_id": "{run_id}", "metrics": {{"mrr@10": NaN}}}}\n')
            handle.write("{torn line\n")
        events, unreadable = _load_events(run_id, limit=10)
        assert len(events) == 1
        assert unreadable.count == 2
        assert unreadable.first_reason is not None and "line 2" in unreadable.first_reason
        # Codex pass 12: a byte-corrupt line must not take the rest of the history with it, and
        # corruption outside the requested tail window is still counted.
        with metrics_path.open("ab") as handle:
            handle.write(b"\xff\xfe not utf-8\n")
            for _ in range(12):
                handle.write(
                    json.dumps({"type": "log", "ts": "2026-08-23T00:00:00Z", "run_id": run_id, "message": "step"}).encode("utf-8")
                    + b"\n"
                )
        events, unreadable = _load_events(run_id, limit=5)
        assert len(events) == 5 and all(e.type == "log" for e in events)
        assert unreadable.count == 3

        after_text = render_latest()[0].decode("utf-8")
        after_events = _metric_value(after_text, 'tribrid_reranker_train_events_total{type="telemetry"}')
        assert after_events == before_events + 1.0
        assert _metric_value(after_text, 'tribrid_reranker_train_last_step') == 7.0
        assert _metric_value(
            after_text,
            'tribrid_reranker_train_last_metric{metric="train_loss",phase="stream"}',
        ) == 0.25
    finally:
        shutil.rmtree(_run_dir(run_id), ignore_errors=True)
