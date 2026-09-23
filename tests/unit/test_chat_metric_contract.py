"""Ratchet: the chat metric contract in the observability plan is what `/metrics` emits.

Dashboards and alerts are written against the plan's **Chat metric contract** table; the
emitters are written against `server/observability/metrics.py`. This parses the table (and
the latency-bucket line under it) out of the plan and compares it with the live Prometheus
registry and the code-side label vocabularies, so neither side can drift alone. A missing
plan or table fails: the contract is binding, not optional.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from prometheus_client import REGISTRY

import server.observability.metrics as metrics
from server.models.chat_config import RecallIntensity
from server.models.tribrid_config_model import FeedbackSurface, RunOutcome, TraceCostSummary

PLAN = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "exec-plans"
    / "active"
    / "observability-chat-telemetry-2026-09-23.md"
)


def _contract_section() -> str:
    text = PLAN.read_text(encoding="utf-8")
    match = re.search(r"^## Chat metric contract.*?$(.*?)(?=^## )", text, flags=re.MULTILINE | re.DOTALL)
    assert match, f"{PLAN} has no '## Chat metric contract' section"
    return match.group(1)


def _contract_rows() -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for line in _contract_section().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4 or not cells[0].startswith("`tribrid_"):
            continue
        name = cells[0].strip("`")
        labels = tuple(re.findall(r"`([a-z_]+)`", cells[2]))
        rows[name] = {"type": cells[1], "labels": labels, "semantics": cells[3]}
    assert rows, "the contract table has no metric rows"
    return rows


def _label_values(semantics: str, label: str) -> set[str]:
    """The backticked values after "`label` ∈" up to the next ';' or sentence end."""
    match = re.search(rf"`{label}` ∈ (.+?)(?:;|\.\s|\.$|$)", semantics)
    assert match, f"no value set for {label!r} in: {semantics}"
    segment = match.group(1)
    tokens = re.findall(r"`([a-z0-9_]+)`", segment)
    for prefix, lo, hi in re.findall(r"`([a-z]+)(\d)`\.\.`[a-z]+(\d)`", segment):
        tokens.extend(f"{prefix}{n}" for n in range(int(lo), int(hi) + 1))
    return set(tokens)


def _contract_buckets() -> tuple[float, ...]:
    match = re.search(r"\*\*Latency buckets \(seconds\)\*\*[^`]*`([0-9., ]+)`", _contract_section())
    assert match, "the contract names no latency buckets"
    return tuple(float(value) for value in match.group(1).split(","))


def _collector(name: str):  # noqa: ANN202 - prometheus_client exposes no public collector type here
    collector = REGISTRY._names_to_collectors.get(name)  # the registry's own index
    assert collector is not None, f"{name} is not registered on the default registry"
    return collector


def test_every_contract_metric_is_registered_with_its_type_and_labels() -> None:
    for name, row in _contract_rows().items():
        collector = _collector(name)
        assert collector._type == row["type"], (name, collector._type, row["type"])
        assert tuple(collector._labelnames) == row["labels"], (name, collector._labelnames, row["labels"])


def test_chat_histograms_use_exactly_the_contract_buckets() -> None:
    buckets = _contract_buckets()
    assert metrics.CHAT_LATENCY_BUCKETS == buckets
    histograms = [name for name, row in _contract_rows().items() if row["type"] == "histogram"]
    assert sorted(histograms) == [
        "tribrid_chat_duration_seconds",
        "tribrid_chat_time_to_first_event_seconds",
        "tribrid_chat_time_to_first_text_seconds",
    ]
    for name in histograms:
        upper_bounds = tuple(bound for bound in _collector(name)._upper_bounds if bound != float("inf"))
        assert upper_bounds == buckets, (name, upper_bounds)


def test_label_vocabularies_match_the_contract() -> None:
    rows = _contract_rows()
    semantics = {name: str(row["semantics"]) for name, row in rows.items()}

    assert set(get_args(RunOutcome)) == _label_values(semantics["tribrid_chat_requests_total"], "outcome")
    assert set(metrics.CHAT_TOKEN_KINDS) == _label_values(semantics["tribrid_chat_tokens_total"], "kind")
    assert set(metrics.FEEDBACK_SIGNALS) == _label_values(semantics["tribrid_feedback_events_total"], "signal")
    assert set(get_args(FeedbackSurface)) == _label_values(semantics["tribrid_feedback_events_total"], "surface")
    assert {intensity.value for intensity in RecallIntensity} == _label_values(
        semantics["tribrid_recall_gate_decisions_total"], "intensity"
    )
    cost_sources = set(re.findall(r"`([a-z]+)`", semantics["tribrid_chat_cost_usd_total"].split("(", 1)[1]))
    assert set(get_args(TraceCostSummary.model_fields["cost_source"].annotation)) == cost_sources


def test_feedback_route_accepts_exactly_the_contract_signals() -> None:
    """The route validates against the same tuple the counter is labelled with."""
    from server.api import feedback

    assert feedback.FEEDBACK_SIGNALS is metrics.FEEDBACK_SIGNALS

